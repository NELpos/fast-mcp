from fastmcp import FastMCP, Context
from fastmcp.server.dependencies import get_access_token, AccessToken
from fastmcp.exceptions import ToolError
import asyncio
import uuid
from typing import Dict, List, Any

# Import shared components and subservers
from shared.auth import auth_provider
from shared.session_manager import session_manager
from shared.redis_session_manager import unified_session_manager
from shared.multi_user_session_manager import multi_user_session_manager
from shared.session_recovery import session_recovery_manager, start_cleanup_task
from utils.session_tracker import setup_session_tracking
from servers.calculator.server import calculator_mcp
from servers.virustoal.server import virustotal_mcp
from servers.postgres.server import postgres_mcp

# Create the main MCP server
main_mcp = FastMCP(
    "Main MCP Server", 
    mask_error_details=True
)

# Resource returning JSON data (dict is auto-serialized)
@main_mcp.resource("data://config")
def get_config() -> dict:
    """Provides application configuration as JSON."""
    return {
        "theme": "dark",
        "version": "1.2.0",
        "features": ["tools", "resources"],
    }

@main_mcp.tool
async def get_my_data(ctx: Context) -> dict:
    """Provides sensitive data for the authenticated user."""
    access_token: AccessToken = get_access_token()
    
    user_id = access_token.client_id  # From JWT 'sub' or 'client_id' claim
    user_scopes = access_token.scopes
    
    # if "data:read_sensitive" not in user_scopes:
    #     raise ToolError("Insufficient permissions: 'data:read_sensitive' scope required.")
    
    return {
        "user": user_id,
        "sensitive_data": f"Private data for {user_id}",
        "granted_scopes": user_scopes
    }

# Health check endpoint
@main_mcp.tool
async def health_check(ctx: Context) -> Dict[str, Any]:
    """Health check endpoint for load balancer with multi-user session info"""
    unified_health = unified_session_manager.health_check()
    multi_user_stats = multi_user_session_manager.get_multi_user_stats()
    
    return {
        "status": "healthy" if unified_health.get("redis_connection") == "ok" else "unhealthy",
        "server_id": str(uuid.uuid4())[:8],
        "legacy_session_info": unified_health,
        "multi_user_session_stats": multi_user_stats
    }

# Multi-user session management tools
@main_mcp.tool
async def get_user_sessions(ctx: Context, user_id: str = None, user_type: str = "authenticated_user") -> Dict[str, Any]:
    """Get sessions for a specific user"""
    try:
        from shared.multi_user_session_manager import UserContext
        
        # Create user context for lookup
        user_context = UserContext(
            user_id=user_id or "current_user",
            user_type=user_type,
            metadata={},
            authentication_method="api_lookup"
        )
        
        active_sessions = multi_user_session_manager.get_user_active_sessions(user_context)
        
        return {
            "user_id": user_context.user_id,
            "user_type": user_context.user_type,
            "active_sessions_count": len(active_sessions),
            "sessions": [
                {
                    "session_id": session.session_id,
                    "client_id": session.client_id,
                    "created_at": session.created_at.isoformat(),
                    "last_accessed": session.last_accessed.isoformat(),
                    "is_active": session.is_active
                }
                for session in active_sessions
            ]
        }
    except Exception as e:
        return {"error": str(e)}

@main_mcp.tool
async def get_session_analytics(ctx: Context) -> Dict[str, Any]:
    """Get comprehensive session analytics"""
    try:
        # Legacy session stats
        legacy_stats = unified_session_manager.health_check()
        
        # Multi-user session stats
        multi_user_stats = multi_user_session_manager.get_multi_user_stats()
        
        # Additional analytics
        import redis
        r = redis.from_url(unified_session_manager.redis_url, decode_responses=True)
        
        # Count different session types
        legacy_app_keys = r.keys("mcp_session:*")
        legacy_transport_keys = r.keys("mcp_transport:*")
        user_session_keys = r.keys("mcp_user_session:*")
        user_index_keys = r.keys("mcp_user_index:*")
        
        return {
            "legacy_sessions": {
                "application_sessions": len(legacy_app_keys),
                "transport_sessions": len(legacy_transport_keys)
            },
            "multi_user_sessions": multi_user_stats,
            "redis_key_counts": {
                "user_sessions": len(user_session_keys),
                "user_indexes": len(user_index_keys),
                "total_keys": len(legacy_app_keys) + len(legacy_transport_keys) + len(user_session_keys) + len(user_index_keys)
            },
            "session_distribution": {
                "legacy_total": len(legacy_app_keys) + len(legacy_transport_keys),
                "multi_user_total": len(user_session_keys)
            }
        }
    except Exception as e:
        return {"error": str(e)}


# Tool list endpoint for server composition
@main_mcp.tool
async def list_all_tools(ctx: Context) -> Dict[str, List[str]]:
    """List all available tools across all imported servers"""
    tools = {
        "main_server": [
            "get_my_data",
            "health_check", 
            "get_user_sessions",
            "get_session_analytics",
            "list_all_tools"
        ],
        "calculator": ["multiply", "divide", "add", "subtract"],
        "virustotal": [],  # Add VT tools here when available
        "postgres": ["query_employees", "get_employee_schema"]
    }
    return tools

async def import_subservers():
    await main_mcp.import_server(prefix="calculator", server=calculator_mcp)
    await main_mcp.import_server(prefix="virustotal", server=virustotal_mcp)
    await main_mcp.import_server(prefix="postgres", server=postgres_mcp)

if __name__ == "__main__":
    asyncio.run(import_subservers())
    start_cleanup_task()  # Start the session cleanup task
    setup_session_tracking()  # Setup session tracking from logs
    
    # Use traditional SSE transport without middleware (avoid ASGI conflicts)
    main_mcp.run(transport="sse", host="0.0.0.0", port=9100)