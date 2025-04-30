"""Authentication utilities for the OPDS-ABS application.

This module provides authentication functionality for the application, including
basic auth validation against the Audiobookshelf login endpoint.

Authentication Architecture:
-------------------------
The OPDS-ABS application uses a multi-layered authentication system:

1. Client Authentication Flow:
   Request → Basic Auth Header → verify_credentials() → Audiobookshelf API → Token

2. Component Relationships:
   - FastAPI dependency injection system for auth requirements
   - TOKEN_CACHE for in-memory token storage
   - Persistent cache for tokens across app restarts
   - Configurable authentication via AUTH_ENABLED flag

3. Authentication Methods:
   - Basic Auth with username/password (primary)
   - Token-based authentication via URL parameters (secondary)
   - Authentication can be disabled completely for development/testing

Integration with OPDS:
-------------------
The authentication system is designed to be compatible with OPDS clients
that support HTTP Basic Authentication, while also accommodating clients
that only support token-based auth via URL parameters.
"""
import base64
import logging
from typing import Optional, Tuple, Dict
import aiohttp

from fastapi import Request, HTTPException
from fastapi.security import HTTPBasic

from opds_abs.config import AUDIOBOOKSHELF_URL, AUTH_ENABLED, AUTH_CACHE_EXPIRY
from opds_abs.utils.cache_utils import _create_cache_key, cache_get, cache_set
from opds_abs.utils.error_utils import AuthenticationError, log_error

# Create a logger for this module
logger = logging.getLogger(__name__)

# Set up HTTPBasic for FastAPI
security = HTTPBasic(auto_error=False)

# In-memory token cache: username -> (token, display_name)
# This helps maintain authentication across requests by caching tokens
TOKEN_CACHE: Dict[str, Tuple[str, str]] = {}

async def authenticate_with_audiobookshelf(username: str, password: str) -> Tuple[str, str]:
    """Authenticate with Audiobookshelf and get a token.

    Args:
        username: Username to authenticate with
        password: Password to authenticate with

    Returns:
        Tuple of (token, display_name)

    Raises:
        AuthenticationError: If authentication fails
    """
    login_url = f"{AUDIOBOOKSHELF_URL}/login"

    try:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    login_url,
                    json={"username": username, "password": password},
                    headers={"Content-Type": "application/json"},
                    timeout=5  # Shortened timeout for faster detection of server issues
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.warning("Authentication failed for user %s: %s", username, error_text)
                        raise AuthenticationError(f"Authentication failed: {response.status}")

                    data = await response.json()

                    if not data or "user" not in data:
                        raise AuthenticationError("Invalid response from Audiobookshelf")

                    user_data = data.get("user", {})
                    token = user_data.get("token")
                    display_name = user_data.get("username", username)

                    if not token:
                        raise AuthenticationError("No token returned from Audiobookshelf")

                    # Cache the token with the username
                    TOKEN_CACHE[username] = (token, display_name)

                    return token, display_name
            except aiohttp.ClientConnectorError as conn_error:
                # Handle connection errors gracefully without traceback
                error_id = id(conn_error)
                logger.error("ERROR [%s]: Cannot connect to Audiobookshelf server at %s", error_id, AUDIOBOOKSHELF_URL)
                raise AuthenticationError(
                    f"Error connecting to Audiobookshelf: Cannot connect to host {AUDIOBOOKSHELF_URL.split('//')[1]}"
                ) from None  # Use "from None" to suppress the traceback
            except aiohttp.ClientError as client_error:
                # For other client errors, provide a cleaner error message
                logger.error("Authentication error for %s: %s", username, str(client_error))
                raise AuthenticationError(f"Error connecting to Audiobookshelf: {str(client_error)}") from None
    except AuthenticationError:
        # Re-raise authentication errors without modification
        raise
    except Exception as e:
        context = f"Processing authentication response from Audiobookshelf"
        log_error(e, context=context)
        raise AuthenticationError(f"Authentication error: {str(e)}") from e

def get_credentials_from_request(request: Request) -> Tuple[Optional[str], Optional[str]]:
    """Extract credentials from Authorization header.

    Args:
        request: The FastAPI request object

    Returns:
        Tuple of (username, password) or (None, None) if not found
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None, None

    try:
        auth_type, auth_info = auth_header.split(" ", 1)
        if auth_type.lower() != "basic":
            return None, None

        decoded = base64.b64decode(auth_info).decode("utf-8")
        username, password = decoded.split(":", 1)
        return username, password
    except Exception as e:
        logger.warning("Invalid authorization header: %s", e)
        return None, None

async def get_user_token(username: str, password: str) -> Tuple[str, str]:
    """Get a token for the user, using cache if available.

    Args:
        username: Username to get token for
        password: Password to authenticate with

    Returns:
        Tuple of (token, display_name)

    Raises:
        AuthenticationError: If authentication fails
    """
    # First check in-memory cache
    if username in TOKEN_CACHE:
        logger.debug("Using cached token for user %s", username)
        return TOKEN_CACHE[username]

    # Not in memory cache, check persistent cache
    cache_key = _create_cache_key("auth_token", None, username)
    cached_data = cache_get(cache_key, AUTH_CACHE_EXPIRY)

    if cached_data is not None:
        logger.debug("✓ Cache hit for auth token: %s", username)
        # Update the in-memory cache too
        TOKEN_CACHE[username] = cached_data
        return cached_data

    # Not in any cache, authenticate with Audiobookshelf
    logger.debug("Not in cache, authenticating user %s", username)
    token, display_name = await authenticate_with_audiobookshelf(username, password)

    # Store in persistent cache
    cache_set(cache_key, (token, display_name))

    return token, display_name

async def verify_credentials(request: Request) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Verify the credentials in the request.

    Args:
        request: The FastAPI request object

    Returns:
        Tuple of (username, token, display_name) or (None, None, None) if invalid or no credentials

    Raises:
        AuthenticationError: If authentication is required but fails
    """
    # If authentication is disabled, return None values
    if not AUTH_ENABLED:
        return None, None, None

    # Extract credentials from request
    username, password = get_credentials_from_request(request)
    if not username or not password:
        return None, None, None

    # Get the token using the username and password (cached if possible)
    token, display_name = await get_user_token(username, password)

    return username, token, display_name

async def get_authenticated_user(request: Request) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Create a FastAPI dependency to get the authenticated user.

    Args:
        request (Request): The FastAPI request object

    Returns:
        Tuple of (username, token, display_name) or (None, None, None) if no credentials

    Raises:
        HTTPException: If authentication fails or server is unavailable
    """
    try:
        # Get credentials and token using Basic Auth
        username, token, display_name = await verify_credentials(request)
        return username, token, display_name
    except AuthenticationError as e:
        # Check if this is a server connection issue
        if "Cannot connect" in str(e) or "not responding" in str(e) or "connecting to Audiobookshelf" in str(e):
            # Server unavailable - raise a 503 Service Unavailable instead of 401
            error_id = id(e)
            error_message = f"Audiobookshelf server is unavailable: {str(e)}"
            logger.error("Server unavailable [%s]: %s", error_id, error_message)

            # Instead of returning a Response object directly (which would break the dependency),
            # raise an HTTPException with 503 status code
            raise HTTPException(
                status_code=503,  # Service Unavailable
                detail=error_message
            )
        else:
            # Regular authentication failure - return a 401 with WWW-Authenticate header
            raise HTTPException(
                status_code=401,
                detail=str(e),
                headers={"WWW-Authenticate": "Basic realm=\"OPDS-ABS\""}
            )

async def require_auth(request: Request) -> Tuple[str, str, str]:
    """Create a FastAPI dependency to require authentication.

    Args:
        request: The FastAPI request object

    Returns:
        Tuple of (username, token, display_name)

    Raises:
        HTTPException: If authentication fails or no credentials provided
    """
    username, token, display_name = await get_authenticated_user(request)

    if not username or not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic realm=\"OPDS-ABS\""}
        )

    return username, token, display_name

def get_token_for_username(username: str) -> Optional[str]:
    """Get a cached token for a username if available.

    Args:
        username: The username to get a token for

    Returns:
        str: The token if available, None otherwise
    """
    if username in TOKEN_CACHE:
        return TOKEN_CACHE[username][0]
    return None
