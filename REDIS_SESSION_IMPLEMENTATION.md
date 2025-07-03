# Fast-MCP Redis 세션 관리 구현 가이드

## 개요

EKS POD 오토스케일링 환경에서 발생하는 "Could not find session for ID" 에러를 해결하기 위해 Redis 기반 세션 관리 시스템을 구현했습니다.

## 문제 상황

### 기존 문제점
- FastMCP의 기본 세션 관리는 메모리 기반으로 동작
- EKS POD 오토스케일링 시 세션 정보가 다른 POD 간 공유되지 않음
- `WARNING:mcp.server.sse:Could not find session for ID : {session uuid}` 에러 지속 발생

### 해결 목표
- Redis를 활용한 중앙집중식 세션 관리
- POD 간 세션 정보 공유
- 자동 세션 복원 및 모니터링

## 구현된 솔루션

### 1. 기본 의존성 추가

**파일: `pyproject.toml`**
```toml
dependencies = [
    "fastmcp>=2.8.1",
    "python-dotenv>=1.1.0",
    "redis>=5.0.0",        # 추가
    "psycopg>=3.1.0",
]
```

### 2. 환경 설정 파일

**파일: `.env.example`** (신규 생성)
```env
# Database Configuration
DATABASE_URL=postgresql://username:password@localhost:5432/database_name

# Redis Configuration for Session Management
REDIS_URL=redis://localhost:6379/0

# Authentication Configuration
JWT_SECRET_KEY=your-secret-key-here
JWT_ALGORITHM=HS256

# Server Configuration
MCP_SERVER_HOST=0.0.0.0
MCP_SERVER_PORT=9100

# VirusTotal API (if using)
VIRUSTOTAL_API_KEY=your-virustotal-api-key-here

# Environment
ENVIRONMENT=development
```

### 3. Redis 기반 통합 세션 관리자

**파일: `shared/redis_session_manager.py`** (신규 생성)

#### 주요 클래스 및 기능

##### SessionData 및 TransportSessionData
```python
@dataclass
class SessionData:
    session_id: str
    client_id: str
    created_at: datetime
    last_accessed: datetime
    data: Dict[str, Any]

@dataclass
class TransportSessionData:
    session_id: str
    transport_type: str
    created_at: datetime
    last_accessed: datetime
    server_name: str
    is_active: bool = True
```

##### RedisStreamableHTTPSessionManager
- FastMCP의 StreamableHTTPSessionManager와 호환되는 Redis 기반 세션 관리자
- Transport 세션 정보를 Redis에 영구 저장
- 메모리 캐시와 Redis 저장소 동시 관리

##### UnifiedRedisSessionManager
```python
class UnifiedRedisSessionManager:
    """통합 세션 관리자 - 애플리케이션 세션과 Transport 세션을 모두 관리"""
    
    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self.app_session_prefix = "mcp_session:"
        self.transport_session_prefix = "mcp_transport:"
```

**주요 메서드:**
- `create_session()`: 애플리케이션 세션 생성
- `get_session()`: 세션 정보 조회
- `update_session()`: 세션 데이터 업데이트
- `store_transport_session()`: Transport 세션 저장
- `health_check()`: Redis 연결 및 세션 상태 확인

### 4. 세션 복원 시스템

**파일: `shared/session_recovery.py`** (신규 생성)

#### SessionRecoveryManager
- 세션 손실 시 자동 복원 로직
- 복원 시도 횟수 제한 및 타임아웃 관리
- 주기적 정리 작업으로 리소스 최적화

**주요 기능:**
```python
async def handle_session_not_found(self, session_id: str, server: Server):
    """세션 찾기 실패 시 자동 복원 시도"""
    
async def _create_unified_session(self, session_id: str, server: Server):
    """애플리케이션 + Transport 세션 동시 생성"""
```

### 5. 로그 기반 세션 추적 시스템

**파일: `utils/session_tracker.py`** (신규 생성)

#### SessionTracker
- HTTP 로그에서 세션 ID 자동 감지
- 다중 패턴 매칭으로 다양한 세션 ID 형식 지원
- 실시간 세션 생성 및 Redis 저장

**세션 ID 감지 패턴:**
```python
self.session_patterns = [
    re.compile(r'session_id=([a-f0-9]{32})'),     # 32자 (하이픈 없음)
    re.compile(r'session_id=([a-f0-9-]{36})'),    # 36자 (하이픈 포함)
    re.compile(r'"session_id":\s*"([a-f0-9]{32})"'),  # JSON 형식
    re.compile(r'/messages/\?session_id=([a-f0-9]{32})'),  # URL 경로
]
```

#### SessionTrackingHandler
- 커스텀 로그 핸들러로 모든 로그 메시지 모니터링
- 세션 ID 발견 시 자동으로 Redis에 세션 정보 저장

### 6. 미들웨어 시스템 (선택적)

**파일: `middleware/session_middleware.py`** (신규 생성)

#### RedisSessionMiddleware
- HTTP 요청 인터셉트하여 세션 정보 추출
- SSE 스트리밍과의 호환성 문제로 현재 비활성화
- 향후 HTTP transport 사용 시 활용 가능

### 7. 기존 서버 기능 개선

#### Calculator Server 개선
**파일: `servers/calculator/server.py`**

- 기존 함수에 상세한 docstring 추가
- 새로운 함수 추가: `add()`, `subtract()`
- LLM 모델이 도구를 더 잘 이해할 수 있도록 설명 강화

예시:
```python
@calculator_mcp.tool
def multiply(a: float, b: float) -> float:
    """
    두 숫자를 곱합니다.
    
    Args:
        a (float): 곱할 첫 번째 숫자
        b (float): 곱할 두 번째 숫자
        
    Returns:
        float: a * b의 결과
        
    Example:
        multiply(3.5, 2.0) returns 7.0
    """
    return a * b
```

#### PostgreSQL Server 개선
**파일: `servers/postgres/server.py`**

- 기존 `query_employees()` 함수에 상세한 보안 설명 추가
- 새로운 함수 추가: `get_employee_schema()`
- 데이터베이스 스키마 정보 제공 기능

### 8. 메인 서버 통합

**파일: `main.py`**

#### 주요 변경사항

1. **Import 추가:**
```python
from shared.redis_session_manager import unified_session_manager
from shared.session_recovery import session_recovery_manager, start_cleanup_task
from utils.session_tracker import setup_session_tracking
```

2. **Health Check 개선:**
```python
@main_mcp.tool
async def health_check(ctx: Context) -> Dict[str, Any]:
    """로드밸런서용 헬스체크 (통합 세션 정보 포함)"""
    unified_health = unified_session_manager.health_check()
    
    return {
        "status": "healthy" if unified_health.get("redis_connection") == "ok" else "unhealthy",
        "server_id": str(uuid.uuid4())[:8],
        "unified_session_info": unified_health
    }
```

3. **서버 시작 로직:**
```python
if __name__ == "__main__":
    asyncio.run(import_subservers())
    start_cleanup_task()  # 세션 정리 작업 시작
    setup_session_tracking()  # 로그 기반 세션 추적 활성화
    
    # SSE transport로 서버 실행
    main_mcp.run(transport="sse", host="0.0.0.0", port=9100)
```

## Redis 데이터 구조

### 애플리케이션 세션
**키 패턴:** `mcp_session:{session_id}`

**데이터 예시:**
```json
{
  "session_id": "ac6e501d50234efa88a5ae0ea92ea0ff",
  "client_id": "sse_client_ac6e501d",
  "created_at": "2025-07-03T22:34:32.027967",
  "last_accessed": "2025-07-03T22:34:32.027970",
  "data": {
    "source": "log_tracker",
    "detected_from": "SSE_request_log",
    "log_message": "INFO: POST /messages/?session_id=..."
  }
}
```

### Transport 세션
**키 패턴:** `mcp_transport:{session_id}`

**데이터 예시:**
```json
{
  "session_id": "ac6e501d50234efa88a5ae0ea92ea0ff",
  "transport_type": "SSE_REFERENCE",
  "created_at": "2025-07-03T22:34:32.032212",
  "last_accessed": "2025-07-03T22:34:32.032215",
  "server_name": "SSE_SERVER_LOG_TRACKED",
  "is_active": true
}
```

## 작동 원리

### 1. 세션 생성 과정
1. 클라이언트가 MCP 요청 전송 (`POST /messages/?session_id=xxx`)
2. Uvicorn 로그에 요청 기록
3. `SessionTrackingHandler`가 로그 메시지에서 세션 ID 추출
4. `SessionTracker`가 Redis에 애플리케이션 세션 생성
5. Transport 세션 참조도 Redis에 저장

### 2. 세션 복원 과정
1. FastMCP가 세션을 찾지 못할 때
2. `SessionRecoveryManager`가 Redis에서 세션 정보 확인
3. 필요시 새로운 transport 인스턴스 생성
4. 메모리와 Redis 세션 동기화

### 3. POD 간 세션 공유
1. 모든 세션 정보가 Redis에 중앙 저장
2. 새로운 POD가 시작되어도 Redis에서 세션 정보 조회 가능
3. 세션 만료 시간(1시간) 자동 관리

## 배포 고려사항

### 1. Redis 설정
- Redis 서버가 모든 EKS POD에서 접근 가능해야 함
- 적절한 메모리 및 persistence 설정 필요
- 클러스터 환경에서는 Redis Cluster 고려

### 2. 환경 변수
```bash
REDIS_URL=redis://redis-service:6379/0
DATABASE_URL=postgresql://postgres-service:5432/mcp_db
```

### 3. Kubernetes 설정
- Redis 서비스 및 POD 설정
- ConfigMap/Secret으로 환경 변수 관리
- Health check 엔드포인트 활용

## 모니터링 및 디버깅

### 1. Health Check 엔드포인트
```bash
curl http://localhost:9100/sse  # MCP 서버 상태 확인
```

Health check 응답 예시:
```json
{
  "status": "healthy",
  "server_id": "a1b2c3d4",
  "unified_session_info": {
    "redis_connection": "ok",
    "application_sessions": {"count": 3},
    "transport_sessions": {"count": 1}
  }
}
```

### 2. Redis 직접 확인
```bash
# 애플리케이션 세션 조회
redis-cli KEYS "mcp_session:*"

# Transport 세션 조회  
redis-cli KEYS "mcp_transport:*"

# 특정 세션 데이터 확인
redis-cli GET "mcp_session:ac6e501d50234efa88a5ae0ea92ea0ff"
```

### 3. 로그 모니터링
```bash
# 세션 추적 로그 확인
tail -f server.log | grep -E "(session_id|Created.*session|Session tracking)"
```

## 성능 최적화

### 1. Redis 연결 풀링
- Redis 클라이언트는 자동으로 연결 풀 관리
- 필요시 `connection_pool` 설정 조정

### 2. 세션 만료 관리
- 기본 만료 시간: 1시간
- 필요시 `default_expiry` 값 조정
- Redis의 자동 만료 기능 활용

### 3. 메모리 사용량 최적화
- 불필요한 세션 데이터 정리
- 주기적 cleanup 작업 실행

## 결론

이 구현을 통해 EKS POD 오토스케일링 환경에서도 안정적인 MCP 세션 관리가 가능해졌습니다. Redis를 중앙 저장소로 사용하여 POD 간 세션 공유가 이루어지며, 자동 세션 감지 및 복원 기능으로 사용자 경험을 개선했습니다.

### 주요 장점
- ✅ POD 오토스케일링 환경에서 세션 유지
- ✅ 자동 세션 감지 및 생성
- ✅ 실시간 세션 모니터링
- ✅ 기존 FastMCP 코드와의 호환성 유지
- ✅ 확장 가능한 아키텍처

### 향후 개선사항
- Transport 세션의 실제 객체 복원 기능 강화
- 세션 데이터 압축 및 최적화
- 더 정교한 세션 만료 정책
- 세션 분산 로드밸런싱 지원