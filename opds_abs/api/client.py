"""Client for interacting with Audiobookshelf API"""
# Standard library imports
import asyncio
import logging
from typing import Optional, Dict, Any, Tuple

# Third-party imports
import aiohttp
from fastapi import HTTPException

# Local application imports
from opds_abs.config import AUDIOBOOKSHELF_API, USER_KEYS, API_KEY
from opds_abs.utils.cache_utils import _create_cache_key, cache_get, cache_set, cached, _cache, clear_cache
from opds_abs.utils.error_utils import (
    AuthenticationError, 
    APIClientError, 
    convert_to_http_exception, 
    log_error
)

logger = logging.getLogger(__name__)

# Cache expiry times (in seconds)
ITEM_CACHE_EXPIRY = 3600  # 1 hour for items
COLLECTION_CACHE_EXPIRY = 1800  # 30 minutes for collections
SEARCH_CACHE_EXPIRY = 600  # 10 minutes for search results
DEFAULT_CACHE_EXPIRY = 1800  # 30 minutes default

# Define cache expiry for different endpoint types
CACHE_EXPIRY_MAPPING = {
    "/items/": ITEM_CACHE_EXPIRY,
    "/libraries/": COLLECTION_CACHE_EXPIRY,
    "/search": SEARCH_CACHE_EXPIRY,
    "/series": COLLECTION_CACHE_EXPIRY,
    "/authors": COLLECTION_CACHE_EXPIRY,
    "/collections": COLLECTION_CACHE_EXPIRY,
}

async def fetch_from_api(
    endpoint: str, 
    params: Dict[str, Any] = None, 
    username: str = None,
    token: str = None,
    bypass_cache: bool = False
) -> Dict[str, Any]:
    """Fetch data from Audiobookshelf API with caching support.
    
    Makes an authenticated request to the Audiobookshelf API using the appropriate 
    authentication method (user token or API key). Results are cached based on 
    endpoint type to improve performance on subsequent calls.
    
    Args:
        endpoint (str): The API endpoint to call (e.g., "/items/123").
        params (dict, optional): Query parameters to include in the request.
        username (str, optional): Username to use for authentication.
        token (str, optional): User-specific auth token from Audiobookshelf login.
        bypass_cache (bool, optional): If True, bypass cache and force a fresh API call.
        
    Returns:
        dict: The JSON response data from the API.
        
    Raises:
        HTTPException: If the API request fails or times out.
    """
    # Determine which authentication to use
    # Priority: 1) Provided token, 2) User's API key from USER_KEYS, 3) Default API key
    auth_header = ""
    
    if token:
        # Use token-based authentication if provided
        auth_header = f"Bearer {token}"
    else:
        # Fall back to API key authentication
        api_key = USER_KEYS.get(username, API_KEY) if username else API_KEY
        
        if not api_key:
            error_msg = f"No authentication available{'for user '+username if username else ''}"
            logger.error(error_msg)
            raise AuthenticationError(error_msg)
            
        auth_header = f"Bearer {api_key}"
    
    # Determine the cache expiry time based on the endpoint
    cache_expiry = DEFAULT_CACHE_EXPIRY
    for key, expiry in CACHE_EXPIRY_MAPPING.items():
        if key in endpoint:
            cache_expiry = expiry
            break
    
    # Create a cache key for this request
    cache_key = _create_cache_key(endpoint, params, username)
    
    # Try to get from cache if not bypassing
    if not bypass_cache:
        cached_data = cache_get(cache_key, cache_expiry)
        if cached_data is not None:
            logger.debug(f"✓ Cache hit for {endpoint}")
            return cached_data
    
    # Not in cache or bypassing cache, make the API call
    headers = {"Authorization": auth_header}
    url = f"{AUDIOBOOKSHELF_API}{endpoint}"
    logger.debug(f"📡 Fetching: {url}{' with params ' + str(params) if params else ''}")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                    url,
                    params=params if params else {},
                    headers=headers,
                    timeout=10
                ) as response:
                response.raise_for_status()
                data = await response.json()
                
                # Store in cache
                cache_set(cache_key, data)
                return data
        except asyncio.TimeoutError as timeout_error:
            context = f"API call to {url}"
            log_error(timeout_error, context=context)
            raise APIClientError(
                f"Timeout while connecting to Audiobookshelf API: {url}"
            ) from timeout_error
        except aiohttp.ClientError as client_error:
            context = f"API call to {url}"
            log_error(client_error, context=context)
            
            # Check if this might be an authentication error
            if hasattr(client_error, "status") and client_error.status in (401, 403):
                raise AuthenticationError(
                    f"Authentication failed for Audiobookshelf API: {str(client_error)}"
                ) from client_error
            
            raise APIClientError(
                f"Error communicating with Audiobookshelf API: {str(client_error)}"
            ) from client_error

@cached(expiry=ITEM_CACHE_EXPIRY)
async def get_download_urls_from_item(
    item_id: str, 
    username: str = None,
    token: str = None
) -> list:
    """Retrieve download URLs for ebook files from an Audiobookshelf item.
    
    Makes an API call to fetch item details and extracts information about
    available ebook files, including their inode numbers needed for generating
    download URLs.
    
    Args:
        item_id (str): The unique identifier of the item to retrieve.
        username (str, optional): Username to use for authentication.
        token (str, optional): User-specific auth token from Audiobookshelf login.
        
    Returns:
        list: A list of dictionaries containing ebook file information including:
            - ino: The inode number of the file
            - filename: The filename of the ebook
            - download_url: An empty string (filled in later)
    """
    try:
        item = await fetch_from_api(f"/items/{item_id}", username=username, token=token)
        ebook_inos = []
        for file in item.get("libraryFiles", []):
            if "ebook" in file.get("fileType", ""):
                ebook_inos.append({
                    "ino":          file.get("ino"),
                    "filename":     file.get("metadata", {}).get("filename", ""),
                    "download_url": ""
                })
        return ebook_inos
    except Exception as e:
        log_error(e, context=f"Getting download URLs for item {item_id}")
        return []

def invalidate_cache(endpoint: str = None, params: dict = None, username: str = None):
    """Invalidate cache for a specific endpoint or item.
    
    Args:
        endpoint: API endpoint to invalidate cache for (if None, key must be provided)
        params: Query parameters (optional)
        username: Username for user-specific cache (optional)
    """
    if endpoint:
        cache_key = _create_cache_key(endpoint, params, username)
        if cache_key in _cache:
            del _cache[cache_key]
            logger.debug(f"Invalidated cache for {endpoint}")
            return True
    return False