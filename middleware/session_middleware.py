import asyncio
import logging
from typing import Dict, Any, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from shared.redis_session_manager import unified_session_manager

logger = logging.getLogger(__name__)

MCP_SESSION_ID_HEADER = "mcp-session-id"

class RedisSessionMiddleware(BaseHTTPMiddleware):
    """
    Middleware to intercept MCP session requests and store session info in Redis
    """
    
    def __init__(self, app, session_manager=None):
        super().__init__(app)
        self.session_manager = session_manager or unified_session_manager
        
    async def dispatch(self, request: Request, call_next):
        # Extract session ID from headers or query params
        session_id = self._extract_session_id(request)
        
        if session_id:
            # Log the session activity
            logger.info(f"Processing request for session {session_id}")
            
            # Store or update session info in Redis
            await self._handle_session(session_id, request)
        
        # Continue with the request
        response = await call_next(request)
        
        # Add session info to response headers if needed
        if session_id:
            response.headers["X-MCP-Session-ID"] = session_id
            
        return response
    
    def _extract_session_id(self, request: Request) -> Optional[str]:
        """Extract session ID from request headers or query parameters"""
        
        # Check headers first
        session_id = request.headers.get("mcp-session-id")
        if session_id:
            return session_id
            
        # Check query parameters
        session_id = request.query_params.get("session_id")
        if session_id:
            return session_id
            
        # Check URL path for session ID
        path = str(request.url.path)
        if "/messages/" in path:
            # Extract from URL like /messages/?session_id=xxx
            session_id = request.query_params.get("session_id")
            if session_id:
                return session_id
        
        return None
    
    async def _handle_session(self, session_id: str, request: Request):
        """Handle session tracking in Redis"""
        try:
            # Check if application session exists
            app_session = self.session_manager.get_session(session_id)
            
            if not app_session:
                # Create new application session
                client_id = f"sse_client_{session_id[:8]}"
                success = self.session_manager.create_session(
                    session_id,
                    client_id,
                    {
                        "source": "sse_middleware",
                        "user_agent": request.headers.get("user-agent", "unknown"),
                        "host": request.client.host if request.client else "unknown",
                        "path": str(request.url.path),
                        "method": request.method
                    }
                )
                
                if success:
                    logger.info(f"Created new session {session_id} via middleware")
                else:
                    logger.error(f"Failed to create session {session_id} via middleware")
            else:
                # Update existing session
                self.session_manager.update_session(session_id, {
                    "last_request_path": str(request.url.path),
                    "last_request_method": request.method,
                    "last_request_time": "now"
                })
                logger.debug(f"Updated existing session {session_id}")
                
            # Store transport session info
            transport_sessions = self.session_manager.list_transport_sessions()
            if session_id not in transport_sessions:
                # Create a mock transport session entry for tracking
                self.session_manager.store_transport_session(
                    session_id,
                    None,  # We can't create actual transport here
                    "SSE_SERVER"
                )
                logger.info(f"Stored transport session reference for {session_id}")
                
        except Exception as e:
            logger.error(f"Error handling session {session_id}: {e}")