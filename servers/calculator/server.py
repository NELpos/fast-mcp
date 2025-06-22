from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from shared.auth import auth_provider

# Define calculator MCP server
calculator_mcp = FastMCP(name="CalculatorService", auth=auth_provider)

@calculator_mcp.tool
def multiply(a: float, b: float) -> float:
    """Multiplies two numbers together."""
    return a * b

@calculator_mcp.tool
def divide(a: float, b: float) -> float:
    """Divide a by b."""
    if b == 0:
        raise ToolError("Division by zero is not allowed.")
    
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise ToolError("Both arguments must be numbers.")
    
    return a / b
