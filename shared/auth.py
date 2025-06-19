import os
import dotenv
from fastmcp.server.auth import BearerAuthProvider

dotenv.load_dotenv()

def get_auth_provider() -> BearerAuthProvider:
    """
    Creates and returns a configured BearerAuthProvider instance
    based on environment variables.
    """
    jwt_public_key = os.getenv("JWT_PUBLIC_KEY")
    if not jwt_public_key:
        raise ValueError("JWT_PUBLIC_KEY environment variable is not set")

    auth = BearerAuthProvider(
        public_key=jwt_public_key,
        issuer=os.getenv("JWT_ISSUER", "https://dev.example.com"),
        audience=os.getenv("JWT_AUDIENCE", "my-dev-server")
    )
    return auth

# Create a single instance to be shared across the application
auth_provider = get_auth_provider()
