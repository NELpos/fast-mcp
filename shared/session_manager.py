import redis
import json
import os
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

@dataclass
class SessionData:
    session_id: str
    client_id: str
    created_at: datetime
    last_accessed: datetime
    data: Dict[str, Any]

class RedisSessionManager:
    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
        self.session_prefix = "mcp_session:"
        self.default_expiry = 3600  # 1 hour default expiry
        
    def create_session(self, session_id: str, client_id: str, data: Dict[str, Any] = None) -> bool:
        """Create a new session in Redis"""
        if data is None:
            data = {}
            
        session_data = SessionData(
            session_id=session_id,
            client_id=client_id,
            created_at=datetime.now(),
            last_accessed=datetime.now(),
            data=data
        )
        
        session_key = f"{self.session_prefix}{session_id}"
        session_json = json.dumps({
            "session_id": session_data.session_id,
            "client_id": session_data.client_id,
            "created_at": session_data.created_at.isoformat(),
            "last_accessed": session_data.last_accessed.isoformat(),
            "data": session_data.data
        })
        
        try:
            self.redis_client.setex(session_key, self.default_expiry, session_json)
            return True
        except Exception as e:
            print(f"Failed to create session {session_id}: {e}")
            return False
    
    def get_session(self, session_id: str) -> Optional[SessionData]:
        """Retrieve session data from Redis"""
        session_key = f"{self.session_prefix}{session_id}"
        
        try:
            session_json = self.redis_client.get(session_key)
            if not session_json:
                return None
                
            session_dict = json.loads(session_json)
            return SessionData(
                session_id=session_dict["session_id"],
                client_id=session_dict["client_id"],
                created_at=datetime.fromisoformat(session_dict["created_at"]),
                last_accessed=datetime.fromisoformat(session_dict["last_accessed"]),
                data=session_dict["data"]
            )
        except Exception as e:
            print(f"Failed to get session {session_id}: {e}")
            return None
    
    def update_session(self, session_id: str, data: Dict[str, Any]) -> bool:
        """Update session data and refresh last accessed time"""
        session = self.get_session(session_id)
        if not session:
            return False
            
        session.data.update(data)
        session.last_accessed = datetime.now()
        
        session_key = f"{self.session_prefix}{session_id}"
        session_json = json.dumps({
            "session_id": session.session_id,
            "client_id": session.client_id,
            "created_at": session.created_at.isoformat(),
            "last_accessed": session.last_accessed.isoformat(),
            "data": session.data
        })
        
        try:
            self.redis_client.setex(session_key, self.default_expiry, session_json)
            return True
        except Exception as e:
            print(f"Failed to update session {session_id}: {e}")
            return False
    
    def delete_session(self, session_id: str) -> bool:
        """Delete session from Redis"""
        session_key = f"{self.session_prefix}{session_id}"
        
        try:
            return bool(self.redis_client.delete(session_key))
        except Exception as e:
            print(f"Failed to delete session {session_id}: {e}")
            return False
    
    def extend_session(self, session_id: str, expiry_seconds: int = None) -> bool:
        """Extend session expiry time"""
        if expiry_seconds is None:
            expiry_seconds = self.default_expiry
            
        session_key = f"{self.session_prefix}{session_id}"
        
        try:
            return bool(self.redis_client.expire(session_key, expiry_seconds))
        except Exception as e:
            print(f"Failed to extend session {session_id}: {e}")
            return False
    
    def list_sessions(self) -> list[str]:
        """List all active session IDs"""
        try:
            keys = self.redis_client.keys(f"{self.session_prefix}*")
            return [key.replace(self.session_prefix, "") for key in keys]
        except Exception as e:
            print(f"Failed to list sessions: {e}")
            return []
    
    def cleanup_expired_sessions(self) -> int:
        """Clean up expired sessions (Redis handles this automatically, but this can be used for logging)"""
        active_sessions = self.list_sessions()
        return len(active_sessions)
    
    def health_check(self) -> bool:
        """Check if Redis connection is healthy"""
        try:
            self.redis_client.ping()
            return True
        except Exception as e:
            print(f"Redis health check failed: {e}")
            return False

# Global session manager instance
session_manager = RedisSessionManager()