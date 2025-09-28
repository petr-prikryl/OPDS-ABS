"""Authentication utilities for the OPDS-ABS application.

This module provides authentication functionality for the application, including
basic auth validation against the Audiobookshelf login endpoint.

Authentication Architecture:
-------------------------
The OPDS-ABS application uses a multi-layered authentication system:

1. Client Authentication Flow:
   - Username/Password: Request → Basic Auth Header → verify_credentials() → Audiobookshelf API → Token
   - API Key (Basic Auth): Request → Basic Auth Header (username:apikey) → verify_credentials() → Audiobookshelf API → Token
   - API Key (Bearer): Request → Bearer Auth Header → verify_credentials() → Audiobookshelf API → Token

2. Component Relationships:
   - FastAPI dependency injection system for auth requirements
   - TOKEN_CACHE for in-memory token storage
   - Persistent cache for tokens across app restarts
   - Configurable authentication via AUTH_ENABLED flag

3. Authentication Methods:
   - Basic Auth with username/password (primary method)
   - Basic Auth with username/API key (alternative method)
   - Bearer Auth with API key (direct Audiobookshelf API method)
   - Authentication can be disabled completely for development/testing

Integration with OPDS:
-------------------
The authentication system is designed to be compatible with OPDS clients
that support HTTP Basic Authentication, while also accommodating API clients
that use Bearer token authentication.

API Key Authentication:
---------------------
API key authentication allows clients to authenticate using Audiobookshelf API keys
instead of passwords. This provides several advantages:

1. Better security since API keys can be revoked without changing the password
2. More granular access control with different API keys for different clients
3. Support for clients that use API keys instead of passwords

To use API key authentication:

Option 1: Basic Auth with API Key (recommended for OPDS clients)
- Format: username:apikey
- Example: Encode "username:apikey" in Base64 and send as `Authorization: Basic <encoded>`
- This works with most OPDS clients that support Basic Auth

Option 2: Bearer Token (for direct API access)
- Format: Bearer apikey
- Example: Send API key as `Authorization: Bearer <apikey>`
- The system will automatically determine the username from the API key
- This matches Audiobookshelf's native API authentication method
"""
import base64
import logging
from typing import Optional, Tuple, Dict
import aiohttp

from fastapi import Request, HTTPException
from fastapi.security import HTTPBasic

from opds_abs.config import AUDIOBOOKSHELF_URL, AUTH_ENABLED, AUTH_CACHE_EXPIRY, API_KEY_AUTH_ENABLED, AUTH_TOKEN_CACHING
from opds_abs.utils.cache_utils import _create_cache_key, cache_get, cache_set
from opds_abs.utils.error_utils import AuthenticationError, log_error

# Create a logger for this module
logger = logging.getLogger(__name__)

# Set up HTTPBasic for FastAPI
security = HTTPBasic(auto_error=False)

# In-memory token cache: username -> (token, display_name)
# This helps maintain authentication across requests by caching tokens
TOKEN_CACHE: Dict[str, Tuple[str, str]] = {}

async def authenticate_with_audiobookshelf(username: str, password: str, api_key: str = None) -> Tuple[str, str]:
    """Authenticate with Audiobookshelf and get a token.

    Args:
        username: Username to authenticate with
        password: Password to authenticate with
        api_key: API key to authenticate with (optional)

    Returns:
        Tuple of (token, display_name)

    Raises:
        AuthenticationError: If authentication fails
    """
    # Log authentication attempt
    if api_key:
        logger.debug(f"Authentication attempt for {username} with API key (length: {len(api_key)})")
    elif password:
        logger.debug(f"Authentication attempt for {username} with password (length: {len(password)})")
    else:
        logger.warning(f"Authentication attempt for {username} without credentials")

    # If API key is provided and API key authentication is enabled, use API key auth
    if api_key and API_KEY_AUTH_ENABLED:
        logger.debug(f"Using API key authentication for {username}")
        return await authenticate_with_api_key(username, api_key)

    # For username/password, check if the "password" might actually be an API key
    # API keys in Audiobookshelf are typically 32+ characters
    # Only try this if API_KEY_AUTH_ENABLED is true
    if password and API_KEY_AUTH_ENABLED and len(password) >= 32:
        logger.debug(f"Password looks like an API key (length: {len(password)}), trying API key auth first")
        try:
            # Try to authenticate with the credential as an API key
            return await authenticate_with_api_key(username, password)
        except AuthenticationError as e:
            # If that fails, continue with regular password authentication
            logger.debug(f"Credential doesn't appear to be a valid API key: {e}")
            logger.debug("Falling back to regular password authentication")
    else:
        logger.debug("Using regular password authentication")

    # Regular username/password authentication
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

async def authenticate_with_api_key(username: str, api_key: str) -> Tuple[str, str]:
    """Authenticate with Audiobookshelf using an API key.

    Args:
        username: Username associated with the API key
        api_key: API key to authenticate with

    Returns:
        Tuple of (token, display_name)

    Raises:
        AuthenticationError: If authentication fails
    """
    logger.debug(f"Authenticating with API key for user: {username}")

    # First try the /api/me endpoint (works for newer versions of Audiobookshelf)
    verify_url = f"{AUDIOBOOKSHELF_URL}/api/me"

    try:
        async with aiohttp.ClientSession() as session:
            try:
                # Log what we're about to do
                logger.debug(f"Making API request to: {verify_url}")
                logger.debug(f"With Bearer token authentication")

                # The API key is used as the Bearer token for this request
                async with session.get(
                    verify_url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    timeout=5  # Short timeout for faster detection of server issues
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.warning(f"API key authentication failed on /api/me: Status {response.status} - {error_text}")
                        # Don't raise an exception yet, try the older method
                    else:
                        data = await response.json()
                        logger.debug(f"API response data: {data}")

                        if data and "user" in data:
                            user_data = data.get("user", {})
                            token = api_key  # In Audiobookshelf, the API key IS the token
                            actual_username = user_data.get("username", "")
                            display_name = actual_username

                            logger.info(f"Successfully authenticated with API key for user: {actual_username}")
                            return token, display_name

                # If we get here, /api/me didn't work. Try /api/authorize as fallback
                # Some versions of Audiobookshelf use this endpoint instead
                logger.debug("Trying fallback authentication with /api/authorize")
                authorize_url = f"{AUDIOBOOKSHELF_URL}/api/authorize"

                async with session.get(
                    authorize_url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    timeout=5
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.warning(f"API key authentication failed on /api/authorize: Status {response.status} - {error_text}")

                        # If both methods fail, try one more legacy approach
                        # Some older versions might use POST instead of GET
                        async with session.post(
                            authorize_url,
                            headers={
                                "Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json"
                            },
                            timeout=5
                        ) as post_response:
                            if post_response.status != 200:
                                error_text = await post_response.text()
                                logger.warning(f"API key authentication failed on POST /api/authorize: Status {post_response.status} - {error_text}")
                                raise AuthenticationError(f"API key authentication failed with all methods")

                            data = await post_response.json()
                            logger.debug(f"API response data (POST): {data}")
                    else:
                        data = await response.json()
                        logger.debug(f"API response data (GET): {data}")

                    if not data or "user" not in data:
                        raise AuthenticationError("Invalid response from Audiobookshelf")

                    user_data = data.get("user", {})
                    token = api_key  # In Audiobookshelf, the API key IS the token
                    actual_username = user_data.get("username", "")
                    display_name = actual_username

                    # If username was provided (not the placeholder) and doesn't match, log a warning
                    if username != "api_key_user" and username != actual_username:
                        logger.warning("API key belongs to user '%s', not '%s'", actual_username, username)

                    # Always use the actual username from Audiobookshelf
                    username = actual_username

                    # Cache the token with the correct username
                    TOKEN_CACHE[username] = (token, display_name)

                    return token, display_name
            except aiohttp.ClientConnectorError as conn_error:
                error_id = id(conn_error)
                logger.error("ERROR [%s]: Cannot connect to Audiobookshelf server at %s", error_id, AUDIOBOOKSHELF_URL)
                raise AuthenticationError(
                    f"Error connecting to Audiobookshelf: Cannot connect to host {AUDIOBOOKSHELF_URL.split('//')[1]}"
                ) from None
            except aiohttp.ClientError as client_error:
                logger.error("API key authentication error for %s: %s", username, str(client_error))
                raise AuthenticationError(f"Error connecting to Audiobookshelf: {str(client_error)}") from None
    except AuthenticationError:
        # Re-raise authentication errors without modification
        raise
    except Exception as e:
        context = f"Processing API key authentication response from Audiobookshelf"
        log_error(e, context=context)
        raise AuthenticationError(f"API key authentication error: {str(e)}") from e

def get_credentials_from_request(request: Request) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract credentials from Authorization header.

    Args:
        request: The FastAPI request object

    Returns:
        Tuple of (username, password, api_key) or (None, None, None) if not found
    """
    auth_header = request.headers.get("Authorization")

    # Check for token parameter in query - this is supported by some OPDS clients
    token_param = request.query_params.get("token")
    if token_param and API_KEY_AUTH_ENABLED:
        logger.debug("Found token in query parameters")
        # Get username from query params or header if available
        username = request.query_params.get("username") or request.headers.get("X-Username") or "api_key_user"
        return username, None, token_param

    if not auth_header:
        return None, None, None

    logger.debug(f"Authorization header found: {auth_header[:15]}...")

    try:
        auth_parts = auth_header.split(" ", 1)
        if len(auth_parts) != 2:
            logger.warning(f"Invalid Authorization header format: {auth_header[:15]}...")
            return None, None, None

        auth_type, auth_info = auth_parts

        # Handle Basic Auth (username:password or username:apikey)
        if auth_type.lower() == "basic":
            try:
                decoded = base64.b64decode(auth_info).decode("utf-8")
                logger.debug(f"Decoded Basic auth: {decoded.split(':')[0]}:***")

                # Check if this is username:password format
                if ":" in decoded:
                    parts = decoded.split(":", 1)
                    if len(parts) == 2:
                        username, credential = parts

                        # Examine the credential - if it looks like an API key and API_KEY_AUTH_ENABLED is False,
                        # we should log a warning as this won't work properly
                        if len(credential) >= 32 and not API_KEY_AUTH_ENABLED:
                            logger.warning(
                                f"Credential for {username} looks like an API key (length {len(credential)}) "
                                f"but API_KEY_AUTH_ENABLED is False. Authentication may fail."
                            )

                        # Return as a password - authenticate_with_audiobookshelf will handle it based on settings
                        return username, credential, None

                logger.warning("Basic auth doesn't contain username:password format")
            except Exception as e:
                logger.warning(f"Error decoding Basic auth: {e}")

            return None, None, None

        # Handle API Key Auth in the Authorization: Bearer <api_key> format
        # This is for API clients using the Audiobookshelf API directly
        elif auth_type.lower() == "bearer":
            # Check if API key authentication is enabled
            if not API_KEY_AUTH_ENABLED:
                logger.warning("Bearer token found but API_KEY_AUTH_ENABLED is False. Authentication will fail.")
                return None, None, None

            logger.debug("Found Bearer token in Authorization header")
            # For Bearer token, we need the username from another source
            # Check query parameters for username
            username = request.query_params.get("username")
            if username:
                logger.debug(f"Using username from query parameters: {username}")
                return username, None, auth_info

            # If no username in query, check headers
            username = request.headers.get("X-Username")
            if username:
                logger.debug(f"Using username from X-Username header: {username}")
                return username, None, auth_info

            # If no username provided, use a special value to indicate this is an API key
            # authentication request without username - we'll try to get it from Audiobookshelf
            logger.debug("No username found for Bearer token, using api_key_user placeholder")
            return "api_key_user", None, auth_info
        else:
            logger.warning(f"Unsupported authorization type: {auth_type}")

    except Exception as e:
        logger.warning(f"Error processing authorization header: {e}")

    return None, None, None

async def get_user_token(username: str, password: str = None, api_key: str = None) -> Tuple[str, str]:
    """Get a token for the user, using cache if available.

    Args:
        username: Username to get token for
        password: Password to authenticate with (optional if api_key is provided)
        api_key: API key to authenticate with (optional if password is provided)

    Returns:
        Tuple of (token, display_name)

    Raises:
        AuthenticationError: If authentication fails
    """
    # Skip cache if token caching is disabled or for API key authentication with placeholder username
    skip_cache = not AUTH_TOKEN_CACHING or (api_key and API_KEY_AUTH_ENABLED and username == "api_key_user")

    if not skip_cache:
        # Check in-memory cache first for efficiency
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

    # Not in any cache, caching disabled, or using API key with placeholder username
    logger.debug("Authenticating user %s directly (caching: %s)", username, AUTH_TOKEN_CACHING)

    # Determine which authentication method to use
    if api_key and API_KEY_AUTH_ENABLED:
        # Use direct API key authentication
        token, display_name = await authenticate_with_api_key(username, api_key)

        # For placeholder usernames, we get the real username from authenticate_with_api_key
        if username == "api_key_user":
            username = display_name
            logger.debug("Updated username from API key: %s", username)
    elif password:
        # Use username/password authentication
        token, display_name = await authenticate_with_audiobookshelf(username, password)
    else:
        raise AuthenticationError("No valid authentication credentials provided")

    # Only cache if token caching is enabled
    if AUTH_TOKEN_CACHING:
        # Store in persistent cache using the potentially updated username
        cache_key = _create_cache_key("auth_token", None, username)
        cache_set(cache_key, (token, display_name))

        # Update in-memory cache with the correct username
        TOKEN_CACHE[username] = (token, display_name)
    else:
        logger.debug("Token caching disabled, not storing token for %s", username)

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
        logger.debug("Authentication is disabled, skipping credential verification")
        return None, None, None

    # Extract credentials from request
    username, password, api_key = get_credentials_from_request(request)

    # Special case: API key was provided but API key authentication is disabled
    if api_key and not API_KEY_AUTH_ENABLED:
        logger.warning(f"API key was provided but API_KEY_AUTH_ENABLED is false, authentication will fail")
        raise AuthenticationError(
            "API key authentication is disabled. Please use username/password or enable API_KEY_AUTH_ENABLED."
        )

    # Log what kind of authentication we're dealing with
    if api_key and API_KEY_AUTH_ENABLED:
        logger.debug(f"Attempting API key authentication for user: {username}")
    elif username and password:
        # Special case: Password looks like an API key but API key auth is disabled
        if len(password) >= 32 and not API_KEY_AUTH_ENABLED:
            logger.warning(
                f"Credential for {username} looks like an API key (length {len(password)}) but "
                f"API_KEY_AUTH_ENABLED is false. Will try as regular password."
            )
        logger.debug(f"Attempting username/password authentication for user: {username}")
    else:
        logger.debug(f"No valid credentials found in request")
        return None, None, None

    # API key authentication
    if api_key and API_KEY_AUTH_ENABLED:
        # Get the token using the username and API key
        try:
            # Try with our robust API key authentication
            logger.debug(f"Authenticating with API key, length: {len(api_key)}")
            token, display_name = await get_user_token(username, None, api_key)

            # If we were using the placeholder username, update it with the real one
            if username == "api_key_user":
                logger.debug(f"Updating placeholder username to: {display_name}")
                username = display_name

            logger.info(f"API key authentication successful for user: {username}")
            return username, token, display_name
        except AuthenticationError as e:
            logger.warning(f"API key authentication failed for user {username}: {e}")
            # Re-raise the error to let the authentication middleware handle it properly
            raise

    # Password authentication - requires both username and password
    elif username and password:
        # Get the token using the username and password (cached if possible)
        try:
            logger.debug(f"Authenticating with username/password for: {username}")
            token, display_name = await get_user_token(username, password)
            logger.info(f"Password authentication successful for user: {username}")
            return username, token, display_name
        except AuthenticationError as e:
            logger.warning(f"Password authentication failed for user {username}: {e}")
            # Re-raise the error to let the authentication middleware handle it properly
            raise

    # Invalid credentials combination
    logger.warning(f"Invalid credential combination in request")
    return None, None, None

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
        # Get credentials and token
        username, token, display_name = await verify_credentials(request)

        # If we got valid credentials, return them
        if username and token:
            return username, token, display_name

        # If credentials were provided but invalid, verify_credentials would have raised AuthenticationError
        # If we get here with no credentials, it means no credentials were provided
        return None, None, None

    except AuthenticationError as e:
        # Check if this is a server connection issue
        if "Cannot connect" in str(e) or "not responding" in str(e) or "connecting to Audiobookshelf" in str(e):
            # Server unavailable - raise a 503 Service Unavailable instead of 401
            error_id = id(e)
            error_message = f"Audiobookshelf server is unavailable: {str(e)}"
            logger.error(f"Server unavailable [{error_id}]: {error_message}")

            # Raise an HTTPException with 503 status code
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
