import redis
import json
import os
import uuid
import asyncio
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from dotenv import load_dotenv
from fastmcp.server.http import StreamableHTTPSessionManager
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http import StreamableHTTPServerTransport
from mcp.server.session import ServerSession
from mcp.server import Server
import logging

load_dotenv()

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

class RedisStreamableHTTPSessionManager:
    """Redis-backed session manager that provides similar functionality to StreamableHTTPSessionManager"""
    
    def __init__(self, redis_url: Optional[str] = None, session_prefix: str = "mcp_transport:"):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
        self.session_prefix = session_prefix
        self.default_expiry = 3600  # 1 hour default expiry
        self.logger = logging.getLogger(__name__)
        
        # Memory storage for compatibility with FastMCP
        self._server_instances = {}  # Keep for compatibility
        
    def _get_transport_key(self, session_id: str) -> str:
        """Get Redis key for transport session"""
        return f"{self.session_prefix}{session_id}"
    
    def _serialize_transport_session(self, session_data: TransportSessionData) -> str:
        """Serialize transport session data to JSON"""
        return json.dumps({
            "session_id": session_data.session_id,
            "transport_type": session_data.transport_type,
            "created_at": session_data.created_at.isoformat(),
            "last_accessed": session_data.last_accessed.isoformat(),
            "server_name": session_data.server_name,
            "is_active": session_data.is_active
        })
    
    def _deserialize_transport_session(self, session_json: str) -> TransportSessionData:
        """Deserialize transport session data from JSON"""
        data = json.loads(session_json)
        return TransportSessionData(
            session_id=data["session_id"],
            transport_type=data["transport_type"],
            created_at=datetime.fromisoformat(data["created_at"]),
            last_accessed=datetime.fromisoformat(data["last_accessed"]),
            server_name=data["server_name"],
            is_active=data.get("is_active", True)
        )
    
    def store_transport_session(self, session_id: str, transport: Optional[StreamableHTTPServerTransport], server_name: str) -> bool:
        """Store transport session in Redis"""
        try:
            session_data = TransportSessionData(
                session_id=session_id,
                transport_type=transport.__class__.__name__ if transport else "SSE_REFERENCE",
                created_at=datetime.now(),
                last_accessed=datetime.now(),
                server_name=server_name,
                is_active=True
            )
            
            session_key = self._get_transport_key(session_id)
            session_json = self._serialize_transport_session(session_data)
            
            self.redis_client.setex(session_key, self.default_expiry, session_json)
            
            # Also store in memory for FastMCP compatibility
            if transport:
                self._server_instances[session_id] = transport
            
            self.logger.info(f"Stored transport session {session_id} in Redis")
            return True
        except Exception as e:
            self.logger.error(f"Failed to store transport session {session_id}: {e}")
            return False
    
    def get_transport_session(self, session_id: str) -> Optional[StreamableHTTPServerTransport]:
        """Get transport session from Redis or memory"""
        try:
            # First check memory cache
            if session_id in self._server_instances:
                # Update last accessed time in Redis
                self.update_transport_session_access(session_id)
                return self._server_instances[session_id]
            
            # Check Redis
            session_key = self._get_transport_key(session_id)
            session_json = self.redis_client.get(session_key)
            
            if not session_json:
                self.logger.warning(f"Transport session {session_id} not found in Redis")
                return None
            
            session_data = self._deserialize_transport_session(session_json)
            
            if not session_data.is_active:
                self.logger.warning(f"Transport session {session_id} is inactive")
                return None
            
            # Session exists in Redis but not in memory - this means we need to recreate transport
            # This is a limitation - we cannot fully recreate the transport from Redis
            # But we can mark it as found and let the application handle recreation
            self.logger.warning(f"Transport session {session_id} found in Redis but not in memory")
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to get transport session {session_id}: {e}")
            return None
    
    def update_transport_session_access(self, session_id: str) -> bool:
        """Update last accessed time for transport session"""
        try:
            session_key = self._get_transport_key(session_id)
            session_json = self.redis_client.get(session_key)
            
            if not session_json:
                return False
            
            session_data = self._deserialize_transport_session(session_json)
            session_data.last_accessed = datetime.now()
            
            updated_json = self._serialize_transport_session(session_data)
            self.redis_client.setex(session_key, self.default_expiry, updated_json)
            
            return True
        except Exception as e:
            self.logger.error(f"Failed to update transport session access {session_id}: {e}")
            return False
    
    def remove_transport_session(self, session_id: str) -> bool:
        """Remove transport session from Redis and memory"""
        try:
            # Remove from Redis
            session_key = self._get_transport_key(session_id)
            redis_deleted = bool(self.redis_client.delete(session_key))
            
            # Remove from memory
            memory_deleted = session_id in self._server_instances
            if memory_deleted:
                del self._server_instances[session_id]
            
            self.logger.info(f"Removed transport session {session_id} (Redis: {redis_deleted}, Memory: {memory_deleted})")
            return redis_deleted or memory_deleted
        except Exception as e:
            self.logger.error(f"Failed to remove transport session {session_id}: {e}")
            return False
    
    def list_transport_sessions(self) -> list[str]:
        """List all active transport session IDs"""
        try:
            keys = self.redis_client.keys(f"{self.session_prefix}*")
            return [key.replace(self.session_prefix, "") for key in keys]
        except Exception as e:
            self.logger.error(f"Failed to list transport sessions: {e}")
            return []
    
    def health_check(self) -> Dict[str, Any]:
        """Health check for Redis connection and session status"""
        try:
            self.redis_client.ping()
            active_sessions = self.list_transport_sessions()
            memory_sessions = list(self._server_instances.keys())
            
            return {
                "redis_connection": "ok",
                "active_transport_sessions": len(active_sessions),
                "memory_transport_sessions": len(memory_sessions),
                "redis_sessions": active_sessions,
                "memory_sessions": memory_sessions
            }
        except Exception as e:
            self.logger.error(f"Transport session health check failed: {e}")
            return {
                "redis_connection": "failed",
                "error": str(e)
            }

class UnifiedRedisSessionManager:
    """Unified session manager that handles both application and transport sessions"""
    
    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
        self.app_session_prefix = "mcp_session:"
        self.transport_session_prefix = "mcp_transport:"
        self.default_expiry = 3600  # 1 hour default expiry
        self.logger = logging.getLogger(__name__)
        
        # Initialize transport session manager
        self.transport_manager = RedisStreamableHTTPSessionManager(redis_url, self.transport_session_prefix)
        
    # Application session methods (keeping existing functionality)
    def create_session(self, session_id: str, client_id: str, data: Dict[str, Any] = None) -> bool:
        """Create a new application session in Redis"""
        if data is None:
            data = {}
            
        session_data = SessionData(
            session_id=session_id,
            client_id=client_id,
            created_at=datetime.now(),
            last_accessed=datetime.now(),
            data=data
        )
        
        session_key = f"{self.app_session_prefix}{session_id}"
        session_json = json.dumps({
            "session_id": session_data.session_id,
            "client_id": session_data.client_id,
            "created_at": session_data.created_at.isoformat(),
            "last_accessed": session_data.last_accessed.isoformat(),
            "data": session_data.data
        })
        
        try:
            self.redis_client.setex(session_key, self.default_expiry, session_json)
            self.logger.info(f"Created application session {session_id}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to create application session {session_id}: {e}")
            return False
    
    def get_session(self, session_id: str) -> Optional[SessionData]:
        """Retrieve application session data from Redis"""
        session_key = f"{self.app_session_prefix}{session_id}"
        
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
            self.logger.error(f"Failed to get application session {session_id}: {e}")
            return None
    
    def update_session(self, session_id: str, data: Dict[str, Any]) -> bool:
        """Update application session data and refresh last accessed time"""
        session = self.get_session(session_id)
        if not session:
            return False
            
        session.data.update(data)
        session.last_accessed = datetime.now()
        
        session_key = f"{self.app_session_prefix}{session_id}"
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
            self.logger.error(f"Failed to update application session {session_id}: {e}")
            return False
    
    def delete_session(self, session_id: str) -> bool:
        """Delete application session from Redis"""
        session_key = f"{self.app_session_prefix}{session_id}"
        
        try:
            return bool(self.redis_client.delete(session_key))
        except Exception as e:
            self.logger.error(f"Failed to delete application session {session_id}: {e}")
            return False
    
    def extend_session(self, session_id: str, expiry_seconds: int = None) -> bool:
        """Extend application session expiry time"""
        if expiry_seconds is None:
            expiry_seconds = self.default_expiry
            
        session_key = f"{self.app_session_prefix}{session_id}"
        
        try:
            return bool(self.redis_client.expire(session_key, expiry_seconds))
        except Exception as e:
            self.logger.error(f"Failed to extend application session {session_id}: {e}")
            return False
    
    def list_sessions(self) -> list[str]:
        """List all active application session IDs"""
        try:
            keys = self.redis_client.keys(f"{self.app_session_prefix}*")
            return [key.replace(self.app_session_prefix, "") for key in keys]
        except Exception as e:
            self.logger.error(f"Failed to list application sessions: {e}")
            return []
    
    # Transport session methods (delegating to transport manager)
    def get_transport_manager(self) -> RedisStreamableHTTPSessionManager:
        """Get the transport session manager"""
        return self.transport_manager
    
    def store_transport_session(self, session_id: str, transport: Optional[StreamableHTTPServerTransport], server_name: str) -> bool:
        """Store transport session"""
        return self.transport_manager.store_transport_session(session_id, transport, server_name)
    
    def get_transport_session(self, session_id: str) -> Optional[StreamableHTTPServerTransport]:
        """Get transport session"""
        return self.transport_manager.get_transport_session(session_id)
    
    def remove_transport_session(self, session_id: str) -> bool:
        """Remove transport session"""
        return self.transport_manager.remove_transport_session(session_id)
    
    def list_transport_sessions(self) -> list[str]:
        """List all transport session IDs"""
        return self.transport_manager.list_transport_sessions()
    
    # Unified health check
    def health_check(self) -> Dict[str, Any]:
        """Comprehensive health check for both session types"""
        try:
            self.redis_client.ping()
            
            app_sessions = self.list_sessions()
            transport_health = self.transport_manager.health_check()
            
            return {
                "redis_connection": "ok",
                "application_sessions": {
                    "count": len(app_sessions),
                    "sessions": app_sessions
                },
                "transport_sessions": transport_health
            }
        except Exception as e:
            self.logger.error(f"Unified session health check failed: {e}")
            return {
                "redis_connection": "failed",
                "error": str(e)
            }

# Global unified session manager instance
unified_session_manager = UnifiedRedisSessionManager()