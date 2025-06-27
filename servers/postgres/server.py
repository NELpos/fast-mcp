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
    """Executes a read-only SQL SELECT query on the 'employees' table."""
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
