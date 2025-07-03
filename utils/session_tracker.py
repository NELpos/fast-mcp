import re
import logging
import asyncio
from typing import Optional, Dict, Any
from shared.redis_session_manager import unified_session_manager
from shared.multi_user_session_manager import multi_user_session_manager, UserContext

class SessionTracker:
    """
    Tracks session IDs from logs and stores them in Redis
    """
    
    def __init__(self):
        self.session_manager = unified_session_manager
        self.multi_user_manager = multi_user_session_manager
        # Multiple patterns to catch different session ID formats
        self.session_patterns = [
            re.compile(r'session_id=([a-f0-9]{32})'),  # URL parameter (32 chars, no hyphens)
            re.compile(r'session_id=([a-f0-9-]{36})'),  # URL parameter (36 chars with hyphens)
            re.compile(r'"session_id":\s*"([a-f0-9]{32})"'),  # JSON (32 chars)
            re.compile(r'"session_id":\s*"([a-f0-9-]{36})"'),  # JSON (36 chars)
            re.compile(r'session_id:\s*([a-f0-9]{32})'),  # Header-like
            re.compile(r'Session-ID:\s*([a-f0-9]{32})'),  # Header
            re.compile(r'mcp-session-id:\s*([a-f0-9]{32})'),  # MCP header
            re.compile(r'/messages/\?session_id=([a-f0-9]{32})'),  # Full URL path
        ]
        # User-aware session tracking
        self.user_patterns = [
            re.compile(r'authorization:\s*bearer\s+([a-zA-Z0-9._-]+)', re.IGNORECASE),
            re.compile(r'"authorization":\s*"bearer\s+([a-zA-Z0-9._-]+)"', re.IGNORECASE),
            re.compile(r'apikey\s+([a-zA-Z0-9._-]+)', re.IGNORECASE),
        ]
        self.processed_sessions = set()
        
    def extract_session_id_from_log(self, log_message: str) -> Optional[str]:
        """Extract session ID from log message using multiple patterns"""
        for pattern in self.session_patterns:
            match = pattern.search(log_message)
            if match:
                return match.group(1)
        return None
    
    def extract_user_info_from_log(self, log_message: str) -> Dict[str, Any]:
        """Extract user authentication info from log message"""
        user_info = {
            "client_ip": "unknown",
            "user_agent": "unknown",
            "auth_token": None
        }
        
        # Extract IP address
        ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', log_message)
        if ip_match:
            user_info["client_ip"] = ip_match.group(1)
        
        # Extract User-Agent (if present in logs)
        ua_match = re.search(r'user-agent[\'"]:\s*[\'"]([^\'\"]+)[\'"]', log_message, re.IGNORECASE)
        if ua_match:
            user_info["user_agent"] = ua_match.group(1)
        
        # Extract authentication token
        for pattern in self.user_patterns:
            match = pattern.search(log_message)
            if match:
                user_info["auth_token"] = f"Bearer {match.group(1)}"
                break
        
        return user_info

    async def track_session_from_log(self, log_message: str):
        """Track session from log message with multi-user support"""
        session_id = self.extract_session_id_from_log(log_message)
        
        if session_id and session_id not in self.processed_sessions:
            try:
                # Extract user information from log
                user_info = self.extract_user_info_from_log(log_message)
                
                # Create user context
                user_context = self.multi_user_manager.extract_user_context_from_request(user_info)
                
                if user_context:
                    # Multi-user session management
                    session_data = {
                        "source": "log_tracker",
                        "detected_from": "SSE_request_log",
                        "log_message": log_message[:200],
                        "original_session_id": session_id
                    }
                    
                    # Find or create user session
                    user_session = self.multi_user_manager.find_or_create_user_session(
                        session_id, user_context, session_data
                    )
                    
                    print(f"👤 User session for {user_context.user_id} ({user_context.user_type}): {session_id}")
                    
                # Fallback to legacy session management
                app_session = self.session_manager.get_session(session_id)
                
                if not app_session:
                    # Create application session
                    client_id = f"sse_client_{session_id[:8]}"
                    success = self.session_manager.create_session(
                        session_id,
                        client_id,
                        {
                            "source": "log_tracker",
                            "detected_from": "SSE_request_log",
                            "log_message": log_message[:100],
                            "user_context": user_context.user_id if user_context else "unknown"
                        }
                    )
                    
                    if success:
                        print(f"✅ Created application session {session_id}")
                    
                # Create transport session reference
                transport_sessions = self.session_manager.list_transport_sessions()
                if session_id not in transport_sessions:
                    transport_success = self.session_manager.store_transport_session(
                        session_id,
                        None,  # No actual transport object
                        "SSE_SERVER_LOG_TRACKED"
                    )
                    
                    if transport_success:
                        print(f"🚗 Created transport session reference {session_id}")
                
                self.processed_sessions.add(session_id)
                
            except Exception as e:
                print(f"❌ Error tracking session {session_id}: {e}")

# Global session tracker
session_tracker = SessionTracker()

# Custom log handler to capture session IDs
class SessionTrackingHandler(logging.Handler):
    """Custom log handler that tracks session IDs"""
    
    def __init__(self):
        super().__init__()
        self.tracker = session_tracker
        
    def emit(self, record):
        """Handle log record and extract session info"""
        try:
            log_message = self.format(record)
            
            # Run async tracking in the background for any potential session ID
            if any(keyword in log_message.lower() for keyword in ['session', 'mcp-session-id', 'messages']):
                try:
                    # Create task but don't wait for it
                    loop = asyncio.get_event_loop()
                    loop.create_task(self.tracker.track_session_from_log(log_message))
                except RuntimeError:
                    # No event loop, create one
                    asyncio.run(self.tracker.track_session_from_log(log_message))
                
        except Exception as e:
            # Print to console instead of logging to avoid recursion
            print(f"Session tracking error: {e}")

# Add the session tracking handler to uvicorn logger
def setup_session_tracking():
    """Setup session tracking from logs"""
    handler = SessionTrackingHandler()
    handler.setLevel(logging.INFO)
    
    # Add to multiple loggers to catch all session activity
    loggers_to_track = [
        "uvicorn.access",
        "uvicorn.error", 
        "fastmcp",
        "mcp",
        "mcp.server",
        "mcp.server.sse",
        "root"
    ]
    
    for logger_name in loggers_to_track:
        try:
            logger = logging.getLogger(logger_name)
            logger.addHandler(handler)
            logger.setLevel(logging.DEBUG)  # Ensure we catch all logs
        except Exception as e:
            print(f"Could not add handler to {logger_name}: {e}")
    
    print("🔍 Session tracking from logs enabled")