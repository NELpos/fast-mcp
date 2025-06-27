import asyncio
import json
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import redis.asyncio as redis
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route
from starlette.endpoints import HTTPEndpoint


class RedisSessionMiddleware(BaseHTTPMiddleware):
    """Redis 기반 세션 미들웨어"""
    
    def __init__(self, app, redis_url: str = "redis://localhost:6379", 
                 session_cookie: str = "session_id", 
                 max_age: int = 3600):
        super().__init__(app)
        self.redis_url = redis_url
        self.session_cookie = session_cookie
        self.max_age = max_age
        self.redis_client = None
    
    async def __aenter__(self):
        self.redis_client = await redis.from_url(self.redis_url)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.redis_client:
            await self.redis_client.close()
    
    async def dispatch(self, request: Request, call_next):
        # Redis 클라이언트 초기화
        if not self.redis_client:
            self.redis_client = await redis.from_url(self.redis_url)
        
        # 세션 ID 가져오기 또는 생성
        session_id = request.cookies.get(self.session_cookie)
        if not session_id:
            session_id = str(uuid.uuid4())
        
        # Redis에서 세션 데이터 로드
        session_data = await self.load_session(session_id)
        request.state.session = session_data
        request.state.session_id = session_id
        
        # 요청 처리
        response = await call_next(request)
        
        # 세션 데이터 저장
        if hasattr(request.state, 'session'):
            await self.save_session(session_id, request.state.session)
        
        # 세션 쿠키 설정
        response.set_cookie(
            key=self.session_cookie,
            value=session_id,
            max_age=self.max_age,
            httponly=True,
            samesite='lax'
        )
        
        return response
    
    async def load_session(self, session_id: str) -> Dict[str, Any]:
        """Redis에서 세션 데이터 로드"""
        try:
            data = await self.redis_client.get(f"session:{session_id}")
            if data:
                return json.loads(data)
        except Exception as e:
            print(f"세션 로드 에러: {e}")
        return {}
    
    async def save_session(self, session_id: str, session_data: Dict[str, Any]):
        """Redis에 세션 데이터 저장"""
        try:
            await self.redis_client.setex(
                f"session:{session_id}",
                self.max_age,
                json.dumps(session_data)
            )
        except Exception as e:
            print(f"세션 저장 에러: {e}")


class SSEManager:
    """SSE 연결 관리자"""
    
    def __init__(self):
        self.connections: Dict[str, asyncio.Queue] = {}
    
    def add_connection(self, session_id: str) -> asyncio.Queue:
        """새 SSE 연결 추가"""
        queue = asyncio.Queue()
        self.connections[session_id] = queue
        return queue
    
    def remove_connection(self, session_id: str):
        """SSE 연결 제거"""
        if session_id in self.connections:
            del self.connections[session_id]
    
    async def send_message(self, session_id: str, message: Dict[str, Any]):
        """특정 세션에 메시지 전송"""
        if session_id in self.connections:
            await self.connections[session_id].put(message)
    
    async def broadcast(self, message: Dict[str, Any], exclude: Optional[str] = None):
        """모든 연결에 메시지 브로드캐스트"""
        for session_id, queue in self.connections.items():
            if session_id != exclude:
                await queue.put(message)


# SSE 매니저 인스턴스
sse_manager = SSEManager()


async def sse_endpoint(request: Request):
    """SSE 엔드포인트"""
    session_id = request.state.session_id
    queue = sse_manager.add_connection(session_id)
    
    async def event_generator():
        try:
            # 연결 메시지
            yield {
                "event": "connected",
                "data": json.dumps({
                    "session_id": session_id,
                    "timestamp": datetime.now().isoformat()
                })
            }
            
            # 메시지 대기 및 전송
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30)
                    yield {
                        "event": message.get("event", "message"),
                        "data": json.dumps(message.get("data", {}))
                    }
                except asyncio.TimeoutError:
                    # 하트비트
                    yield {
                        "event": "heartbeat",
                        "data": json.dumps({"timestamp": datetime.now().isoformat()})
                    }
                    
        except asyncio.CancelledError:
            sse_manager.remove_connection(session_id)
            raise
    
    async def format_sse(data: Dict[str, str]) -> str:
        """SSE 형식으로 포맷"""
        lines = []
        if "event" in data:
            lines.append(f"event: {data['event']}")
        if "data" in data:
            lines.append(f"data: {data['data']}")
        lines.append("")
        return "\n".join(lines) + "\n"
    
    async def sse_stream():
        """SSE 스트림 생성"""
        async for event in event_generator():
            yield await format_sse(event)
    
    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


class SessionEndpoint(HTTPEndpoint):
    """세션 정보 엔드포인트"""
    
    async def get(self, request: Request):
        """현재 세션 정보 반환"""
        return Response(json.dumps({
            "session_id": request.state.session_id,
            "session_data": request.state.session
        }), media_type="application/json")
    
    async def post(self, request: Request):
        """세션에 데이터 저장"""
        data = await request.json()
        request.state.session.update(data)
        return Response(json.dumps({
            "status": "success",
            "session_data": request.state.session
        }), media_type="application/json")


async def send_message_endpoint(request: Request):
    """메시지 전송 엔드포인트"""
    data = await request.json()
    target_session = data.get("target_session")
    message = data.get("message")
    
    if target_session:
        # 특정 세션에 전송
        await sse_manager.send_message(target_session, {
            "event": "message",
            "data": {
                "from": request.state.session_id,
                "message": message,
                "timestamp": datetime.now().isoformat()
            }
        })
    else:
        # 브로드캐스트
        await sse_manager.broadcast({
            "event": "broadcast",
            "data": {
                "from": request.state.session_id,
                "message": message,
                "timestamp": datetime.now().isoformat()
            }
        }, exclude=request.state.session_id)
    
    return Response(json.dumps({"status": "success"}), media_type="application/json")


async def homepage(request: Request):
    """테스트용 홈페이지"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>SSE Redis Session Demo</title>
        <style>
            body { font-family: Arial, sans-serif; padding: 20px; }
            #messages { 
                border: 1px solid #ccc; 
                height: 300px; 
                overflow-y: auto; 
                padding: 10px; 
                margin: 20px 0;
            }
            .message { margin: 5px 0; padding: 5px; background: #f0f0f0; }
            .event { color: #666; font-size: 0.9em; }
            button { margin: 5px; padding: 5px 10px; }
        </style>
    </head>
    <body>
        <h1>SSE Redis Session Demo</h1>
        <div id="session-info"></div>
        <div id="messages"></div>
        <input type="text" id="messageInput" placeholder="메시지 입력">
        <button onclick="sendMessage()">전송</button>
        <button onclick="sendBroadcast()">브로드캐스트</button>
        
        <script>
            let eventSource;
            let sessionId;
            
            // 세션 정보 로드
            fetch('/session')
                .then(res => res.json())
                .then(data => {
                    sessionId = data.session_id;
                    document.getElementById('session-info').innerHTML = 
                        `<p>Session ID: ${sessionId}</p>`;
                });
            
            // SSE 연결
            function connectSSE() {
                eventSource = new EventSource('/sse');
                
                eventSource.onopen = function() {
                    addMessage('SSE 연결됨', 'system');
                };
                
                eventSource.onerror = function(e) {
                    addMessage('SSE 연결 에러', 'error');
                    setTimeout(connectSSE, 5000);
                };
                
                eventSource.addEventListener('connected', function(e) {
                    const data = JSON.parse(e.data);
                    addMessage(`연결됨: ${data.session_id}`, 'connected');
                });
                
                eventSource.addEventListener('message', function(e) {
                    const data = JSON.parse(e.data);
                    addMessage(`메시지 from ${data.from}: ${data.message}`, 'message');
                });
                
                eventSource.addEventListener('broadcast', function(e) {
                    const data = JSON.parse(e.data);
                    addMessage(`브로드캐스트 from ${data.from}: ${data.message}`, 'broadcast');
                });
                
                eventSource.addEventListener('heartbeat', function(e) {
                    console.log('Heartbeat:', e.data);
                });
            }
            
            function addMessage(text, type) {
                const messages = document.getElementById('messages');
                const msgDiv = document.createElement('div');
                msgDiv.className = 'message';
                msgDiv.innerHTML = `<span class="event">[${type}]</span> ${text}`;
                messages.appendChild(msgDiv);
                messages.scrollTop = messages.scrollHeight;
            }
            
            function sendMessage() {
                const input = document.getElementById('messageInput');
                const target = prompt('대상 세션 ID (비워두면 자신에게):');
                
                fetch('/send-message', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        target_session: target || sessionId,
                        message: input.value
                    })
                });
                
                input.value = '';
            }
            
            function sendBroadcast() {
                const input = document.getElementById('messageInput');
                
                fetch('/send-message', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        message: input.value
                    })
                });
                
                input.value = '';
            }
            
            // SSE 연결 시작
            connectSSE();
        </script>
    </body>
    </html>
    """
    return Response(html, media_type="text/html")


# Starlette 앱 생성
app = Starlette(
    routes=[
        Route('/', homepage),
        Route('/sse', sse_endpoint),
        Route('/session', SessionEndpoint),
        Route('/send-message', send_message_endpoint, methods=['POST']),
    ],
    middleware=[
        Middleware(RedisSessionMiddleware, redis_url="redis://localhost:6379")
    ]
)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)