# FastMCP Server

FastMCP를 사용한 모듈형 MCP 서버 애플리케이션입니다. 이 프로젝트는 JWT 인증을 사용하는 여러 MCP 서버를 하나의 애플리케이션으로 구성한 예제입니다.

## 📋 기능

- **계산기 서버**
  - 기본적인 사칙연산 기능 제공
  - `multiply`: 두 수의 곱 계산
  - `divide`: 두 수의 나눗셈 (0으로 나누기 방지)

- **VirusTotal 통합**
  - IP 주소 기반 위협 정보 조회
  - 도메인 기반 위협 정보 조회

- **인증 및 보안**
  - JWT 기반 인증
  - 범위(Scope) 기반 접근 제어
  - 환경 변수를 통한 민감 정보 관리

## 🚀 시작하기

### 사전 요구사항

- Python 3.8+
- pip 또는 uv 패키지 매니저

### 설치

1. 저장소 복제
   ```bash
   git clone https://github.com/NELpos/fast-mcp.git
   cd fast-mcp
   ```

2. 가상 환경 생성 및 활성화 (선택 사항)
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Linux/Mac
   .venv\Scripts\activate    # Windows
   ```

3. 의존성 설치
   ```bash
   uv pip install -r requirements.txt
   ```

### 환경 변수 설정

`.env` 파일을 생성하고 다음 변수들을 설정하세요:

```env
# JWT 설정
JWT_PUBLIC_KEY=your_public_key_here
JWT_ISSUER=https://your-issuer.com
JWT_AUDIENCE=your-audience

# VirusTotal API 키 (선택 사항)
VIRUSTOTAL_API_KEY=your_virustotal_api_key
```

### JWT 토큰 생성

테스트를 위해 JWT 토큰을 생성하려면:

```bash
python utils/generate_token.py
```

이 스크립트는 공개 키와 테스트용 토큰을 생성합니다. 공개 키를 `.env` 파일의 `JWT_PUBLIC_KEY`로 설정하세요.

## 🏃 서버 실행

```bash
python main.py
```

서버는 기본적으로 `http://127.0.0.1:9100`에서 실행됩니다.

## 🛠️ API 엔드포인트

### 메인 서버
- `POST /mcp/` - MCP 프로토콜 엔드포인트
- `GET /mcp/` - 서버 상태 확인

### 리소스
- `GET /mcp/resources/data://config` - 애플리케이션 구성 정보 반환

## 🛡️ 인증

모든 요청에는 유효한 JWT 토큰이 `Authorization: Bearer <token>` 헤더에 포함되어야 합니다.

## 📂 프로젝트 구조

```
fast-mcp/
├── main.py                  # 메인 애플리케이션 진입점
├── servers/                 # MCP 서버 모듈
│   ├── __init__.py
│   ├── calculator.py        # 계산기 기능 서버
│   └── virustotal.py        # VirusTotal 통합 서버
├── shared/                  # 공유 모듈
│   ├── __init__.py
│   └── auth.py              # 인증 관련 유틸리티
├── utils/                   # 유틸리티 스크립트
│   └── generate_token.py    # JWT 토큰 생성기
├── .env.example             # 환경 변수 예제
└── README.md                # 이 파일
```

## 📝 사용 예제

### 계산기 사용

```python
# 클라이언트 코드 예시
result = await calculator_mcp.multiply(a=5, b=4)
print(result)  # 20.0
```

### VirusTotal 조회

```python
# IP 주소 조회
report = await virustotal_mcp.get_ip_report(ip_address="8.8.8.8")

# 도메인 조회
domain_report = await virustotal_mcp.get_domain_report(domain="google.com")
```

## 📄 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다.