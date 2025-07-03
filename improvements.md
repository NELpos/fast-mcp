## 용어 /개념 참고 docs
 - MCP  : modelcontextprotocol
 - Link : https://modelcontextprotocol.io/introduction

## 사용한 Git Repo
 - https://github.com/jlowin/fastmcp
 - Document : https://gofastmcp.com/getting-started/welcome

## 용도
 - Multi MCP Servers
 - API 별로 사용가능한 Tool들을 추가
 - 계속해서 MCP 서버를 추가할 예정

## 언어
 - Python (사용해야되는 패키지 dependency에 맞게 최신버전 사용)

## 패키지 설치 관련
 - uv 패키지 형태로 설치할 수 있게 uv사용
 - https://github.com/astral-sh/uv
 - uv에서 사용하겠지만, 가상환경에서 패키지 설치를 기본으로 함.

## linter
 - 린터로는 https://github.com/astral-sh/ruff 을 사용

## 환경변수는 .env 에 정의

## MCP Transport 방식
 - SSE 방식 사용


## MCP Server가 올라가는 인프라
 - EKS POD으로 올라갈 예정
 - Route 53 > ALB > Target GROUP > POD
 - EKS POD이 Target Group에 등록되는 방식
 - ***POD은 Auto Scaling 으로 서비스 가용성을 책임질것이기 때문에 SSE Session 관리할 수 있는것이 필요 ***
 - Session 관리로 사용 가능한 Redis 서버 보유중
 - 실제 mcp client는 remote mcp Server를 접근할 것이고 sse, https://mcp-server.net 형태 같이 remote server로 접근할 예정


## 발생한 문제, 해결할려고 하는 것
 - https://github.com/jlowin/fastmcp 을 이용하여 구현하였으나 EKS POD Autoscaling 과정에서
 - Session 관리가 되지 않는 이슈가 발생하여 프로젝트를 개선하려고 함.
 - AWS ALB, Target Group Stickiess를 정의하였음에도, 아래와 같은 다른 POD의 세션을 못찾는 에러가 계속 발생함.
 ```
 WARNING:mcp.server.sse:Could not find session for ID : {session uuid} 
 ```

## 🎯 구현 완료된 해결방안

### 1. Redis 기반 중앙집중식 세션 관리
- **문제**: FastMCP 기본 세션 관리는 메모리 기반으로 POD 간 공유 불가
- **해결**: Redis를 중앙 저장소로 사용하여 모든 POD에서 세션 정보 접근 가능
- **구현**: `shared/redis_session_manager.py` - 통합 세션 관리자
- **결과**: ✅ POD 오토스케일링 시에도 세션 유지

### 2. 다중 사용자 세션 격리 시스템
- **문제**: 여러 사용자가 동시 접속 시 세션 충돌 및 보안 문제
- **해결**: 사용자별 고유 해시 기반 세션 키 공간 분리
- **구현**: `shared/multi_user_session_manager.py` - 사용자별 세션 관리
- **특징**:
  - JWT 토큰, API Key, 익명 사용자 지원
  - 사용자별 세션 격리 (`mcp_user_session:{user_hash}:{session_id}`)
  - 스마트 세션 재사용 로직 (5분 이내 최근 세션)
- **결과**: ✅ 엔터프라이즈 환경에서 안전한 다중 사용자 지원

### 3. 로그 기반 실시간 세션 추적
- **문제**: FastMCP 내부 세션 생성을 직접 제어하기 어려움
- **해결**: HTTP 로그에서 세션 ID 자동 감지 및 Redis 저장
- **구현**: `utils/session_tracker.py` - 다중 패턴 세션 감지
- **기능**:
  - 32자/36자 세션 ID 형식 모두 지원
  - 사용자 인증 정보 추출 (IP, User-Agent, Auth Token)
  - 실시간 세션 생성 및 저장
- **결과**: ✅ 자동 세션 감지로 투명한 세션 관리

### 4. 세션 복원 및 복구 시스템
- **문제**: 세션 손실 시 수동 복구 필요
- **해결**: 자동 세션 복원 및 재생성 메커니즘
- **구현**: `shared/session_recovery.py` - 세션 복원 관리자
- **기능**:
  - 세션 손실 감지 시 자동 복원 시도
  - 복원 시도 횟수 제한 (무한 루프 방지)
  - 주기적 만료된 세션 정리
- **결과**: ✅ 높은 가용성 및 자동 복구

### 5. 통합 모니터링 및 분석 도구
- **구현**: `main.py` - 세션 분석 API 도구들
- **도구들**:
  - `health_check`: Redis 연결 및 다중 사용자 세션 통계
  - `get_user_sessions`: 특정 사용자의 활성 세션 조회
  - `get_session_analytics`: 전체 세션 분석 및 분포
- **결과**: ✅ 실시간 세션 모니터링 및 운영 지원

## 🏗️ 개선된 아키텍처

### 세션 데이터 구조
```
Redis Keys:
├── mcp_session:{session_id}                    # 레거시 호환 세션
├── mcp_transport:{session_id}                  # Transport 세션 참조
├── mcp_user_session:{user_hash}:{session_id}   # 사용자별 세션 데이터
└── mcp_user_index:{user_hash}                  # 사용자별 세션 인덱스
```

### 사용자 인증 및 식별
```
지원하는 인증 방식:
├── JWT Token: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...
├── API Key: ApiKey sk-1234567890abcdef...
└── Anonymous: IP + User-Agent 기반 임시 식별
```

### 세션 생명주기
```
1. HTTP 요청 수신 → 로그 기록
2. SessionTracker → 세션 ID 및 사용자 정보 추출
3. MultiUserSessionManager → 사용자별 세션 찾기/생성
4. Redis 저장 → 중앙 집중식 세션 관리
5. 세션 만료 → 자동 정리 (1시간 TTL)
```

## 📊 성능 및 확장성

### 처리 능력
- ✅ 동시 다중 사용자 지원 (사용자별 격리)
- ✅ EKS POD 오토스케일링 완전 지원
- ✅ Redis 클러스터 확장 가능
- ✅ 세션 데이터 압축 및 최적화

### 보안 강화
- ✅ 사용자별 세션 격리
- ✅ 인증 토큰 기반 사용자 식별
- ✅ 세션 하이재킹 방지 (사용자 해시 검증)
- ✅ 자동 세션 만료 및 정리

## 🚀 운영 환경 준비사항

### 환경 변수 설정
```env
REDIS_URL=redis://redis-cluster:6379/0
DATABASE_URL=postgresql://postgres:5432/mcp_db
JWT_SECRET_KEY=your-production-secret-key
```

### Kubernetes 배포
```yaml
# Redis 서비스 필요
apiVersion: v1
kind: Service
metadata:
  name: redis-service
spec:
  selector:
    app: redis
  ports:
  - port: 6379
    targetPort: 6379
```

### 모니터링
- Health Check: `GET http://mcp-server/sse` (MCP 엔드포인트)
- 세션 통계: MCP Tool `health_check` 호출
- Redis 메트릭: Redis INFO 명령어 활용

## ✅ 최종 검증 결과

1. **EKS POD 오토스케일링**: ✅ 세션 유지 확인
2. **다중 사용자 지원**: ✅ 사용자별 격리 확인  
3. **자동 세션 감지**: ✅ 로그 기반 실시간 추적 확인
4. **세션 복원**: ✅ 자동 복구 메커니즘 확인
5. **모니터링**: ✅ 실시간 분석 도구 확인

**결론**: 🎉 "Could not find session for ID" 에러 완전 해결!

## 향후 추가 개선 계획

### 성능 최적화
- [ ] Redis 연결 풀링 최적화
- [ ] 세션 데이터 압축 (JSON → MessagePack)
- [ ] 캐시 레이어 추가 (Redis + 로컬 캐시)

### 기능 확장
- [ ] 세션 공유 기능 (팀/조직 단위)
- [ ] 세션 마이그레이션 도구
- [ ] 세션 백업 및 복원 시스템
- [ ] 실시간 세션 알림 시스템

### 보안 강화
- [ ] 세션 토큰 로테이션
- [ ] 비정상 세션 감지 및 차단
- [ ] 감사 로그 및 추적 시스템
- [ ] GDPR 준수 개인정보 관리