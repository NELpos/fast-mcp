from fastmcp import FastMCP, Context
from fastmcp.server.dependencies import get_access_token, AccessToken
from fastmcp.exceptions import ToolError
import asyncio

# Import shared components and subservers
from shared.auth import auth_provider
from servers.calculator.server import calculator_mcp
from servers.virustoal.server import virustotal_mcp

# Create the main MCP server
main_mcp = FastMCP("Main MCP Server", auth=auth_provider, mask_error_details=True)

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
    
    if "data:read_sensitive" not in user_scopes:
        raise ToolError("Insufficient permissions: 'data:read_sensitive' scope required.")
    
    return {
        "user": user_id,
        "sensitive_data": f"Private data for {user_id}",
        "granted_scopes": user_scopes
    }

async def import_subservers():
    await main_mcp.import_server(prefix="calculator", server=calculator_mcp)
    await main_mcp.import_server(prefix="virustotal", server=virustotal_mcp)

if __name__ == "__main__":
    asyncio.run(import_subservers())
    main_mcp.run(transport="streamable-http", host="127.0.0.1", port=9100)