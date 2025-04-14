"""Authentication utilities for the OPDS-ABS application.

This module provides authentication functionality for the application, including
basic auth validation against the Audiobookshelf login endpoint and token management.
"""
import base64
import json
import logging
from typing import Optional, Tuple, Dict
import aiohttp

from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from opds_abs.config import AUDIOBOOKSHELF_URL, AUTH_ENABLED, AUTH_CACHE_EXPIRY, USER_KEYS
from opds_abs.utils.cache_utils import _create_cache_key, cache_get, cache_set
from opds_abs.utils.error_utils import AuthenticationError, ResourceNotFoundError, log_error

# Create a logger for this module
logger = logging.getLogger(__name__)

# Set up HTTPBasic for FastAPI
security = HTTPBasic(auto_error=False)

# Cache for user tokens: username -> (token, display_name)
_token_cache: Dict[str, Tuple[str, str]] = {}

# In-memory cache to store username-to-token mappings for the current process
# This helps maintain authentication across requests when tokens aren't passed explicitly
AUTH_MATRIX = {}

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
            async with session.post(
                login_url,
                json={"username": username, "password": password},
                headers={"Content-Type": "application/json"},
                timeout=10
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.warning(f"Authentication failed for user {username}: {error_text}")
                    raise AuthenticationError(f"Authentication failed: {response.status}")
                
                data = await response.json()
                
                if not data or "user" not in data:
                    raise AuthenticationError("Invalid response from Audiobookshelf")
                
                user_data = data.get("user", {})
                token = user_data.get("token")
                display_name = user_data.get("username", username)
                
                if not token:
                    raise AuthenticationError("No token returned from Audiobookshelf")
                
                return token, display_name
                
    except aiohttp.ClientError as e:
        context = f"Authenticating with Audiobookshelf at {login_url}"
        log_error(e, context=context)
        raise AuthenticationError(f"Error connecting to Audiobookshelf: {str(e)}") from e
    except Exception as e:
        if isinstance(e, AuthenticationError):
            raise
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
        logger.warning(f"Invalid authorization header: {e}")
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
    cache_key = _create_cache_key("auth_token", None, username)
    
    # Check cache first
    cached_data = cache_get(cache_key, AUTH_CACHE_EXPIRY)
    if cached_data is not None:
        logger.debug(f"✓ Cache hit for auth token: {username}")
        return cached_data
    
    # Not in cache, authenticate with Audiobookshelf
    token, display_name = await authenticate_with_audiobookshelf(username, password)
    
    # Store in cache
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
    
    # Check if we need to authenticate with Audiobookshelf
    token, display_name = await get_user_token(username, password)
    
    return username, token, display_name

async def get_authenticated_user(request: Request) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """FastAPI dependency to get the authenticated user.
    
    Args:
        request: The FastAPI request object
        
    Returns:
        Tuple of (username, token, display_name) or (None, None, None) if no credentials
        
    Raises:
        HTTPException: If authentication fails
    """
    try:
        # First try to get credentials from the Authorization header
        username, token, display_name = await verify_credentials(request)
        
        # If no token from header but AUTH_ENABLED is True, check query params for token
        if AUTH_ENABLED and not token:
            query_token = request.query_params.get("token")
            if query_token:
                # Extract username from path parameters
                path_username = request.path_params.get("username")
                if path_username:
                    logger.debug(f"Found token in query parameters for user: {path_username}")
                    # Use the username from the path and the token from query params
                    return path_username, query_token, path_username
        
        return username, token, display_name
    except AuthenticationError as e:
        # Convert to HTTPException with WWW-Authenticate header
        raise HTTPException(
            status_code=401,
            detail=str(e),
            headers={"WWW-Authenticate": "Basic realm=\"OPDS-ABS\""}
        )

def require_auth(request: Request) -> Tuple[str, str, str]:
    """FastAPI dependency to require authentication.
    
    Args:
        request: The FastAPI request object
        
    Returns:
        Tuple of (username, token, display_name)
        
    Raises:
        HTTPException: If authentication fails or no credentials provided
    """
    username, token, display_name = get_authenticated_user(request)
    
    if not username or not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic realm=\"OPDS-ABS\""}
        )
        
    return username, token, display_name

def verify_user(username, token=None):
    """Verify that the username exists in the system.
    
    When authentication is enabled (AUTH_ENABLED=true), this will require a valid token.
    When authentication is disabled, it will skip verification.
    
    Args:
        username (str): The username to verify.
        token (str, optional): The authentication token from Audiobookshelf.
        
    Raises:
        ResourceNotFoundError: If authentication is enabled but no valid auth method is found.
    """
    logger.debug(f"Verifying user: {username}, AUTH_ENABLED={AUTH_ENABLED}, token_provided={token is not None}")
    
    # If authentication is disabled, don't verify
    if not AUTH_ENABLED:
        logger.debug("Authentication disabled, skipping verification")
        return
        
    # If a token is provided, store it in our AUTH_MATRIX for this username
    # This helps maintain authentication across requests
    if token:
        logger.debug(f"User {username} authenticated via token")
        AUTH_MATRIX[username] = token
        return
    
    # If no token provided but we have one stored for this user, use that
    if username in AUTH_MATRIX:
        logger.debug(f"User {username} authenticated via stored token in AUTH_MATRIX")
        return
        
    # If no token but username is in USER_KEYS, consider the user authenticated with API key
    if username in USER_KEYS:
        logger.debug(f"User {username} authenticated via API key in USER_KEYS")
        return
        
    # If we get here, authentication is enabled but no valid auth method was found
    logger.warning(f"Authentication failed for user {username}: No valid token or API key found")
    raise ResourceNotFoundError(f"User '{username}' not found or not authenticated")