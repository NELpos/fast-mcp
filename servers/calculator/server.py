from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from shared.auth import auth_provider

# Define calculator MCP server
calculator_mcp = FastMCP(name="CalculatorService", auth=auth_provider)

@calculator_mcp.tool
def multiply(a: float, b: float) -> float:
    """
    Multiplies two numbers together.
    
    Args:
        a (float): The first number to multiply
        b (float): The second number to multiply
        
    Returns:
        float: The result of a * b
        
    Example:
        multiply(3.5, 2.0) returns 7.0
    """
    return a * b

@calculator_mcp.tool
def divide(a: float, b: float) -> float:
    """
    Divides the first number by the second number.
    
    Args:
        a (float): The dividend (number to be divided)
        b (float): The divisor (number to divide by)
        
    Returns:
        float: The result of a / b
        
    Raises:
        ToolError: If b is zero (division by zero) or if arguments are not numbers
        
    Example:
        divide(10.0, 2.0) returns 5.0
    """
    if b == 0:
        raise ToolError("Division by zero is not allowed.")
    
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise ToolError("Both arguments must be numbers.")
    
    return a / b

@calculator_mcp.tool
def add(a: float, b: float) -> float:
    """
    Adds two numbers together.
    
    Args:
        a (float): The first number to add
        b (float): The second number to add
        
    Returns:
        float: The sum of a + b
        
    Example:
        add(2.5, 3.7) returns 6.2
    """
    return a + b

@calculator_mcp.tool
def subtract(a: float, b: float) -> float:
    """
    Subtracts the second number from the first number.
    
    Args:
        a (float): The minuend (number to subtract from)
        b (float): The subtrahend (number to subtract)
        
    Returns:
        float: The result of a - b
        
    Example:
        subtract(10.0, 3.0) returns 7.0
    """
    return a - b
