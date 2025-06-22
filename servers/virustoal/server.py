import os
import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from shared.auth import auth_provider

# Get VirusTotal API Key from environment variable
API_KEY = os.getenv("VIRUSTOTAL_API_KEY")
BASE_URL = "https://www.virustotal.com/api/v3"

virustotal_mcp = FastMCP(name="VirusTotalService", auth=auth_provider)

@virustotal_mcp.tool
async def get_ip_report(ip_address: str) -> dict:
    """Fetches the VirusTotal report for a given IP address."""
    if not API_KEY:
        raise ToolError("VIRUSTOTAL_API_KEY environment variable is not set.")

    headers = {
        "x-apikey": API_KEY
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{BASE_URL}/ip_addresses/{ip_address}", headers=headers)
            response.raise_for_status()  # Raise an exception for 4xx or 5xx status codes
            return response.json()
        except httpx.HTTPStatusError as e:
            # Provide a more specific error message
            error_details = e.response.json().get("error", {})
            error_message = error_details.get("message", e.response.text)
            raise ToolError(f"API Error: {error_message} (Status code: {e.response.status_code})")
        except httpx.RequestError as e:
            raise ToolError(f"Request failed: {e}")

@virustotal_mcp.tool
async def get_domain_report(domain: str) -> dict:
    """Fetches the VirusTotal report for a given domain."""
    if not API_KEY:
        raise ToolError("VIRUSTOTAL_API_KEY environment variable is not set.")

    headers = {
        "x-apikey": API_KEY
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{BASE_URL}/domains/{domain}", headers=headers)
            response.raise_for_status()  # Raise an exception for 4xx or 5xx status codes
            return response.json()
        except httpx.HTTPStatusError as e:
            # Provide a more specific error message
            error_details = e.response.json().get("error", {})
            error_message = error_details.get("message", e.response.text)
            raise ToolError(f"API Error: {error_message} (Status code: {e.response.status_code})")
        except httpx.RequestError as e:
            raise ToolError(f"Request failed: {e}")
