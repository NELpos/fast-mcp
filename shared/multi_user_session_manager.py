import redis
import json
import os
import hashlib
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from dotenv import load_dotenv
import logging

load_dotenv()

@dataclass
class UserContext:
    user_id: str
    user_type: str  # "individual", "organization", "service_account"
    metadata: Dict[str, Any]
    authentication_method: str  # "jwt", "api_key", "oauth"

@dataclass
class MultiUserSessionData:
    session_id: str
    user_context: UserContext
    client_id: str
    created_at: datetime
    last_accessed: datetime
    data: Dict[str, Any]
    is_active: bool = True

class MultiUserSessionManager:
    """
    다중 사용자 환경을 위한 세션 관리자
    사용자별 세션 격리 및 컨텍스트 관리
    """
    
    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
        self.session_prefix = "mcp_user_session:"
        self.user_index_prefix = "mcp_user_index:"
        self.transport_prefix = "mcp_user_transport:"
        self.default_expiry = 3600  # 1 hour
        self.logger = logging.getLogger(__name__)
        
    def _get_user_hash(self, user_context: UserContext) -> str:
        """사용자 컨텍스트로부터 고유 해시 생성"""
        user_string = f"{user_context.user_id}:{user_context.user_type}:{user_context.authentication_method}"
        return hashlib.sha256(user_string.encode()).hexdigest()[:16]
    
    def _get_session_key(self, session_id: str, user_hash: str) -> str:
        """사용자별 세션 키 생성"""
        return f"{self.session_prefix}{user_hash}:{session_id}"
    
    def _get_user_index_key(self, user_hash: str) -> str:
        """사용자별 세션 인덱스 키"""
        return f"{self.user_index_prefix}{user_hash}"
    
    def _get_transport_key(self, session_id: str, user_hash: str) -> str:
        """사용자별 transport 세션 키"""
        return f"{self.transport_prefix}{user_hash}:{session_id}"
    
    def extract_user_context_from_request(self, request_info: Dict[str, Any]) -> Optional[UserContext]:
        """
        요청 정보에서 사용자 컨텍스트 추출
        
        Args:
            request_info: {
                'headers': {...},
                'client_ip': '127.0.0.1',
                'user_agent': '...',
                'auth_token': '...',  # JWT, API Key 등
                'session_id': '...'
            }
        """
        try:
            headers = request_info.get('headers', {})
            auth_token = request_info.get('auth_token') or headers.get('authorization')
            user_agent = request_info.get('user_agent') or headers.get('user-agent', 'unknown')
            client_ip = request_info.get('client_ip', 'unknown')
            
            if auth_token:
                # JWT 토큰 파싱 (실제로는 JWT 라이브러리 사용)
                if auth_token.startswith('Bearer '):
                    # JWT 토큰 처리
                    user_id = self._extract_user_from_jwt(auth_token[7:])
                    return UserContext(
                        user_id=user_id,
                        user_type="authenticated_user",
                        metadata={
                            "client_ip": client_ip,
                            "user_agent": user_agent,
                            "auth_method": "jwt"
                        },
                        authentication_method="jwt"
                    )
                elif auth_token.startswith('ApiKey '):
                    # API Key 처리
                    api_key = auth_token[7:]
                    user_id = self._extract_user_from_api_key(api_key)
                    return UserContext(
                        user_id=user_id,
                        user_type="service_account",
                        metadata={
                            "client_ip": client_ip,
                            "user_agent": user_agent,
                            "api_key_hash": hashlib.sha256(api_key.encode()).hexdigest()[:8]
                        },
                        authentication_method="api_key"
                    )
            
            # 인증되지 않은 사용자 - IP 기반 임시 사용자
            user_id = f"anonymous_{hashlib.sha256(f'{client_ip}:{user_agent}'.encode()).hexdigest()[:12]}"
            return UserContext(
                user_id=user_id,
                user_type="anonymous",
                metadata={
                    "client_ip": client_ip,
                    "user_agent": user_agent
                },
                authentication_method="anonymous"
            )
            
        except Exception as e:
            self.logger.error(f"Failed to extract user context: {e}")
            return None
    
    def _extract_user_from_jwt(self, jwt_token: str) -> str:
        """JWT 토큰에서 사용자 ID 추출 (실제로는 JWT 라이브러리 사용)"""
        # 실제 구현에서는 JWT 라이브러리로 토큰 검증 및 파싱
        # 여기서는 단순화된 버전
        try:
            import base64
            # JWT payload 부분만 디코딩 (실제로는 서명 검증 필요)
            parts = jwt_token.split('.')
            if len(parts) >= 2:
                payload = base64.urlsafe_b64decode(parts[1] + '==')
                payload_data = json.loads(payload)
                return payload_data.get('sub') or payload_data.get('user_id', 'unknown_jwt_user')
        except:
            pass
        return f"jwt_user_{jwt_token[:8]}"
    
    def _extract_user_from_api_key(self, api_key: str) -> str:
        """API Key에서 사용자 ID 추출"""
        # 실제로는 데이터베이스에서 API Key 조회
        # 여기서는 단순화된 버전
        return f"api_user_{hashlib.sha256(api_key.encode()).hexdigest()[:12]}"
    
    def find_or_create_user_session(self, session_id: str, user_context: UserContext, 
                                   request_metadata: Dict[str, Any] = None) -> MultiUserSessionData:
        """
        사용자의 기존 세션을 찾거나 새로 생성
        """
        user_hash = self._get_user_hash(user_context)
        
        # 1. 기존 세션 확인
        existing_session = self.get_user_session(session_id, user_context)
        if existing_session and existing_session.is_active:
            # 기존 세션 갱신
            self.update_session_access(session_id, user_context, request_metadata or {})
            return existing_session
        
        # 2. 사용자의 다른 활성 세션 확인
        user_sessions = self.get_user_active_sessions(user_context)
        if user_sessions:
            # 가장 최근 세션 재사용 또는 새 세션 생성 정책 결정
            latest_session = max(user_sessions, key=lambda s: s.last_accessed)
            if (datetime.now() - latest_session.last_accessed).seconds < 300:  # 5분 이내
                # 최근 세션 재사용
                self.logger.info(f"Reusing recent session {latest_session.session_id} for user {user_context.user_id}")
                return latest_session
        
        # 3. 새 세션 생성
        return self.create_user_session(session_id, user_context, request_metadata or {})
    
    def create_user_session(self, session_id: str, user_context: UserContext, 
                           session_data: Dict[str, Any] = None) -> MultiUserSessionData:
        """사용자별 새 세션 생성"""
        user_hash = self._get_user_hash(user_context)
        
        session = MultiUserSessionData(
            session_id=session_id,
            user_context=user_context,
            client_id=f"mcp_client_{user_context.user_type}_{user_hash[:8]}",
            created_at=datetime.now(),
            last_accessed=datetime.now(),
            data=session_data or {},
            is_active=True
        )
        
        try:
            # 세션 저장
            session_key = self._get_session_key(session_id, user_hash)
            session_json = json.dumps({
                "session_id": session.session_id,
                "user_context": asdict(session.user_context),
                "client_id": session.client_id,
                "created_at": session.created_at.isoformat(),
                "last_accessed": session.last_accessed.isoformat(),
                "data": session.data,
                "is_active": session.is_active
            })
            
            self.redis_client.setex(session_key, self.default_expiry, session_json)
            
            # 사용자 세션 인덱스 업데이트
            user_index_key = self._get_user_index_key(user_hash)
            self.redis_client.sadd(user_index_key, session_id)
            self.redis_client.expire(user_index_key, self.default_expiry)
            
            self.logger.info(f"Created session {session_id} for user {user_context.user_id}")
            return session
            
        except Exception as e:
            self.logger.error(f"Failed to create user session: {e}")
            raise
    
    def get_user_session(self, session_id: str, user_context: UserContext) -> Optional[MultiUserSessionData]:
        """사용자별 세션 조회"""
        user_hash = self._get_user_hash(user_context)
        session_key = self._get_session_key(session_id, user_hash)
        
        try:
            session_json = self.redis_client.get(session_key)
            if not session_json:
                return None
            
            session_dict = json.loads(session_json)
            return MultiUserSessionData(
                session_id=session_dict["session_id"],
                user_context=UserContext(**session_dict["user_context"]),
                client_id=session_dict["client_id"],
                created_at=datetime.fromisoformat(session_dict["created_at"]),
                last_accessed=datetime.fromisoformat(session_dict["last_accessed"]),
                data=session_dict["data"],
                is_active=session_dict.get("is_active", True)
            )
        except Exception as e:
            self.logger.error(f"Failed to get user session: {e}")
            return None
    
    def get_user_active_sessions(self, user_context: UserContext) -> List[MultiUserSessionData]:
        """사용자의 모든 활성 세션 조회"""
        user_hash = self._get_user_hash(user_context)
        user_index_key = self._get_user_index_key(user_hash)
        
        try:
            session_ids = self.redis_client.smembers(user_index_key)
            active_sessions = []
            
            for session_id in session_ids:
                session = self.get_user_session(session_id, user_context)
                if session and session.is_active:
                    active_sessions.append(session)
            
            return active_sessions
        except Exception as e:
            self.logger.error(f"Failed to get user active sessions: {e}")
            return []
    
    def update_session_access(self, session_id: str, user_context: UserContext, 
                             new_data: Dict[str, Any] = None):
        """세션 마지막 접근 시간 및 데이터 업데이트"""
        session = self.get_user_session(session_id, user_context)
        if not session:
            return False
        
        session.last_accessed = datetime.now()
        if new_data:
            session.data.update(new_data)
        
        user_hash = self._get_user_hash(user_context)
        session_key = self._get_session_key(session_id, user_hash)
        
        session_json = json.dumps({
            "session_id": session.session_id,
            "user_context": asdict(session.user_context),
            "client_id": session.client_id,
            "created_at": session.created_at.isoformat(),
            "last_accessed": session.last_accessed.isoformat(),
            "data": session.data,
            "is_active": session.is_active
        })
        
        self.redis_client.setex(session_key, self.default_expiry, session_json)
        return True
    
    def deactivate_user_session(self, session_id: str, user_context: UserContext):
        """사용자 세션 비활성화"""
        session = self.get_user_session(session_id, user_context)
        if session:
            session.is_active = False
            user_hash = self._get_user_hash(user_context)
            session_key = self._get_session_key(session_id, user_hash)
            
            session_json = json.dumps({
                "session_id": session.session_id,
                "user_context": asdict(session.user_context),
                "client_id": session.client_id,
                "created_at": session.created_at.isoformat(),
                "last_accessed": session.last_accessed.isoformat(),
                "data": session.data,
                "is_active": False
            })
            
            self.redis_client.setex(session_key, 300, session_json)  # 5분 후 만료
            
            # 사용자 인덱스에서 제거
            user_index_key = self._get_user_index_key(user_hash)
            self.redis_client.srem(user_index_key, session_id)
    
    def cleanup_expired_sessions(self):
        """만료된 세션 정리"""
        # Redis의 자동 만료 기능을 활용하므로 별도 정리 불필요
        # 필요시 사용자 인덱스 정리 로직 추가
        pass
    
    def get_multi_user_stats(self) -> Dict[str, Any]:
        """다중 사용자 세션 통계"""
        try:
            all_session_keys = self.redis_client.keys(f"{self.session_prefix}*")
            all_user_keys = self.redis_client.keys(f"{self.user_index_prefix}*")
            
            active_sessions = 0
            user_types = {}
            
            for key in all_session_keys:
                try:
                    session_data = json.loads(self.redis_client.get(key))
                    if session_data.get("is_active"):
                        active_sessions += 1
                        user_type = session_data.get("user_context", {}).get("user_type", "unknown")
                        user_types[user_type] = user_types.get(user_type, 0) + 1
                except:
                    continue
            
            return {
                "total_session_keys": len(all_session_keys),
                "total_user_indexes": len(all_user_keys),
                "active_sessions": active_sessions,
                "user_type_distribution": user_types
            }
        except Exception as e:
            self.logger.error(f"Failed to get multi-user stats: {e}")
            return {"error": str(e)}

# 글로벌 인스턴스
multi_user_session_manager = MultiUserSessionManager()