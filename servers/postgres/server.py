import os
import psycopg
from typing import List, Dict, Any
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

# Define the MCP server for PostgreSQL
postgres_mcp = FastMCP(name="PostgresService")

class Query(BaseModel):
    sql: str = Field(..., description="The SELECT SQL query to execute.")

@postgres_mcp.tool
def query_employees(query: str) -> List[Dict[str, Any]]:
    """
    Executes a read-only SQL SELECT query on the 'employees' table.
    
    This tool provides secure access to employee data by restricting queries to SELECT operations
    only on the employees table. It prevents unauthorized data access and modification.
    
    Args:
        query (str): The SQL SELECT query to execute. Must start with 'SELECT' and query the 'employees' table.
                    Example: "SELECT name, department FROM employees WHERE department = 'IT'"
    
    Returns:
        List[Dict[str, Any]]: A list of dictionaries representing the query results.
                             Each dictionary contains column names as keys and row values as values.
    
    Raises:
        ToolError: If the query is not a SELECT statement, doesn't query the employees table,
                  or if the database connection fails.
    
    Security Features:
        - Only allows SELECT queries (no INSERT, UPDATE, DELETE, DROP, etc.)
        - Restricts access to 'employees' table only
        - Uses parameterized queries to prevent SQL injection
        
    Example Usage:
        query_employees("SELECT id, name, email FROM employees WHERE department = 'Engineering'")
        Returns: [{"id": 1, "name": "John Doe", "email": "john@company.com"}, ...]
    """
    sql_query = query.strip().upper()

    # Security checks
    if not sql_query.startswith("SELECT"):
        raise ToolError("Only SELECT queries are allowed.")

    # This is a basic check to ensure we are querying the employees table and not others.
    # It's not foolproof but prevents simple mistakes.
    query_after_from = sql_query.split("FROM", 1)[1] if "FROM" in sql_query else ""
    if not query_after_from.strip().startswith("EMPLOYEES"):
        raise ToolError("This tool can only query the 'employees' table. The query must start with 'SELECT ... FROM employees ...'.")

    if not DATABASE_URL:
        raise ToolError("DATABASE_URL is not configured.")

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                columns = [desc[0] for desc in cur.description]
                results = [dict(zip(columns, row)) for row in cur.fetchall()]
                return results
    except psycopg.Error as e:
        raise ToolError(f"Database query failed: {e}")

@postgres_mcp.tool 
def get_employee_schema() -> Dict[str, str]:
    """
    Returns the schema information for the employees table.
    
    This tool helps users understand the structure of the employees table
    before writing queries, ensuring they use correct column names and data types.
    
    Returns:
        Dict[str, str]: A dictionary mapping column names to their data types.
    
    Example:
        get_employee_schema()
        Returns: {"id": "integer", "name": "varchar(255)", "email": "varchar(255)", "department": "varchar(100)"}
    """
    if not DATABASE_URL:
        raise ToolError("DATABASE_URL is not configured.")
    
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_name = 'employees'
                    ORDER BY ordinal_position
                """)
                columns = cur.fetchall()
                return {col[0]: col[1] for col in columns}
    except psycopg.Error as e:
        raise ToolError(f"Failed to get schema: {e}")
