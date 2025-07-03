import asyncio
import logging
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
from fastmcp.server.http import StreamableHTTPSessionManager
from mcp.server.streamable_http import StreamableHTTPServerTransport
from mcp.server import Server
from shared.redis_session_manager import unified_session_manager

logger = logging.getLogger(__name__)

class SessionRecoveryManager:
    """
    Manages session recovery and error handling for MCP sessions
    """
    
    def __init__(self, session_manager=None):
        self.session_manager = session_manager or unified_session_manager
        self.recovery_attempts = {}  # Track recovery attempts to prevent infinite loops
        self.max_recovery_attempts = 3
        self.recovery_timeout = 300  # 5 minutes
        
    async def handle_session_not_found(self, session_id: str, server: Server) -> Optional[StreamableHTTPServerTransport]:
        """
        Handle 'Could not find session for ID' errors by attempting recovery
        
        Args:
            session_id: The session ID that couldn't be found
            server: The MCP server instance
            
        Returns:
            StreamableHTTPServerTransport if recovery successful, None otherwise
        """
        logger.warning(f"Attempting to recover session {session_id}")
        
        # Check if we've already attempted recovery too many times
        if self._should_skip_recovery(session_id):
            logger.error(f"Skipping recovery for session {session_id} - too many attempts")
            return None
        
        # Record recovery attempt
        self._record_recovery_attempt(session_id)
        
        try:
            # Step 1: Check if session exists in Redis
            app_session = self.session_manager.get_session(session_id)
            transport_sessions = self.session_manager.list_transport_sessions()
            
            if session_id in transport_sessions:
                logger.info(f"Session {session_id} found in Redis transport sessions")
                # Try to get the actual transport
                transport = self.session_manager.get_transport_session(session_id)
                if transport:
                    logger.info(f"Successfully recovered transport for session {session_id}")
                    return transport
                else:
                    logger.warning(f"Transport session {session_id} exists in Redis but cannot be recreated")
            
            # Step 2: If application session exists, try to create new transport
            if app_session:
                logger.info(f"Found application session {session_id}, creating new transport")
                transport = await self._create_new_transport(session_id, server)
                if transport:
                    # Store the new transport session
                    self.session_manager.store_transport_session(session_id, transport, server.name)
                    logger.info(f"Successfully created new transport for session {session_id}")
                    return transport
            
            # Step 3: Last resort - create both application and transport sessions
            logger.info(f"Creating new unified session for {session_id}")
            success = await self._create_unified_session(session_id, server)
            if success:
                transport = self.session_manager.get_transport_session(session_id)
                if transport:
                    logger.info(f"Successfully created unified session for {session_id}")
                    return transport
            
            logger.error(f"Failed to recover session {session_id}")
            return None
            
        except Exception as e:
            logger.error(f"Error during session recovery for {session_id}: {e}")
            return None
    
    async def _create_new_transport(self, session_id: str, server: Server) -> Optional[StreamableHTTPServerTransport]:
        """Create a new transport session for existing application session"""
        try:
            # Create new transport instance
            transport = StreamableHTTPServerTransport(server)
            
            # Initialize the transport
            await transport.start()
            
            return transport
        except Exception as e:
            logger.error(f"Failed to create new transport for session {session_id}: {e}")
            return None
    
    async def _create_unified_session(self, session_id: str, server: Server) -> bool:
        """Create both application and transport sessions"""
        try:
            # Create application session with default client_id
            client_id = f"recovered_client_{session_id[:8]}"
            app_success = self.session_manager.create_session(
                session_id, 
                client_id, 
                {"recovered": True, "recovery_time": datetime.now().isoformat()}
            )
            
            if not app_success:
                logger.error(f"Failed to create application session for {session_id}")
                return False
            
            # Create transport session
            transport = await self._create_new_transport(session_id, server)
            if not transport:
                logger.error(f"Failed to create transport session for {session_id}")
                return False
            
            # Store transport session
            transport_success = self.session_manager.store_transport_session(session_id, transport, server.name)
            
            return transport_success
            
        except Exception as e:
            logger.error(f"Failed to create unified session for {session_id}: {e}")
            return False
    
    def _should_skip_recovery(self, session_id: str) -> bool:
        """Check if we should skip recovery due to too many attempts"""
        if session_id not in self.recovery_attempts:
            return False
        
        attempts_info = self.recovery_attempts[session_id]
        
        # Check if we've exceeded max attempts
        if attempts_info["count"] >= self.max_recovery_attempts:
            return True
        
        # Check if we're within timeout period
        last_attempt = attempts_info["last_attempt"]
        if datetime.now() - last_attempt < timedelta(seconds=self.recovery_timeout):
            return attempts_info["count"] >= self.max_recovery_attempts
        
        # Reset attempts if timeout has passed
        self.recovery_attempts[session_id] = {
            "count": 0,
            "last_attempt": datetime.now()
        }
        return False
    
    def _record_recovery_attempt(self, session_id: str):
        """Record a recovery attempt for rate limiting"""
        if session_id not in self.recovery_attempts:
            self.recovery_attempts[session_id] = {
                "count": 0,
                "last_attempt": datetime.now()
            }
        
        self.recovery_attempts[session_id]["count"] += 1
        self.recovery_attempts[session_id]["last_attempt"] = datetime.now()
    
    def cleanup_old_attempts(self):
        """Clean up old recovery attempt records"""
        cutoff_time = datetime.now() - timedelta(seconds=self.recovery_timeout * 2)
        
        to_remove = []
        for session_id, attempts_info in self.recovery_attempts.items():
            if attempts_info["last_attempt"] < cutoff_time:
                to_remove.append(session_id)
        
        for session_id in to_remove:
            del self.recovery_attempts[session_id]
    
    def get_recovery_stats(self) -> Dict[str, Any]:
        """Get recovery statistics"""
        return {
            "total_sessions_with_recovery_attempts": len(self.recovery_attempts),
            "recovery_attempts": dict(self.recovery_attempts),
            "max_recovery_attempts": self.max_recovery_attempts,
            "recovery_timeout": self.recovery_timeout
        }

# Global session recovery manager
session_recovery_manager = SessionRecoveryManager()

# Periodic cleanup task
async def periodic_cleanup():
    """Periodically clean up old recovery attempts"""
    while True:
        try:
            session_recovery_manager.cleanup_old_attempts()
            await asyncio.sleep(3600)  # Run every hour
        except Exception as e:
            logger.error(f"Error in periodic cleanup: {e}")
            await asyncio.sleep(300)  # Wait 5 minutes before retry

# Function to start cleanup task when event loop is available
def start_cleanup_task():
    """Start the cleanup task when event loop is running"""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(periodic_cleanup())
    except RuntimeError:
        # No running event loop, will be started later
        pass