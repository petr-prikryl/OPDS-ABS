"""Client for interacting with Audiobookshelf API."""
# Standard library imports
import asyncio
import logging
from typing import Dict, Any

# Third-party imports
import aiohttp

# Local application imports
from opds_abs.config import (
    AUDIOBOOKSHELF_API,
    AUTH_ENABLED,
    AUTHORS_CACHE_EXPIRY,
    COLLECTIONS_CACHE_EXPIRY,
    DEFAULT_CACHE_EXPIRY,
    LIBRARIES_CACHE_EXPIRY,
    LIBRARY_ITEMS_CACHE_EXPIRY,
    SEARCH_RESULTS_CACHE_EXPIRY,
    SERIES_DETAILS_CACHE_EXPIRY
)
from opds_abs.utils.cache_utils import _create_cache_key, cache_get, cache_set, cached, _cache
from opds_abs.utils.error_utils import AuthenticationError, APIClientError, log_error
from opds_abs.utils.auth_utils import get_token_for_username, TOKEN_CACHE

logger = logging.getLogger(__name__)

# Define cache expiry for different endpoint types
CACHE_EXPIRY_MAPPING = {
    "/items/": LIBRARY_ITEMS_CACHE_EXPIRY,
    "/libraries/": LIBRARIES_CACHE_EXPIRY,
    "/search": SEARCH_RESULTS_CACHE_EXPIRY,
    "/series": SERIES_DETAILS_CACHE_EXPIRY,
    "/authors": AUTHORS_CACHE_EXPIRY,
    "/collections": COLLECTIONS_CACHE_EXPIRY,
}

async def fetch_from_api(
    endpoint: str,
    params: Dict[str, Any] = None,
    username: str = None,
    token: str = None,
    bypass_cache: bool = False
) -> Dict[str, Any]:
    """Fetch data from Audiobookshelf API with caching support.

    Makes an authenticated request to the Audiobookshelf API using the user token.
    Results are cached based on endpoint type to improve performance on subsequent calls.

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
    params = params.copy() if params else {}

    # Try to get a token if one wasn't provided
    if token is None and username is not None:
        # Check if token is in the params
        if 'token' in params:
            token = params.pop('token')  # Extract and remove from params
            logger.debug("Using token from params for user %s", username)
        # Check if api_key is in the params
        elif 'api_key' in params:
            token = params.pop('api_key')  # Use API key as token
            logger.debug("Using API key from params for user %s", username)
        else:
            # Try to get from the TOKEN_CACHE
            token = get_token_for_username(username)
            logger.debug("Token from cache for user %s: %s", username, 'Found' if token else 'Not found')

        # If no token from cache and authentication is enabled, we have a problem
        if token is None and AUTH_ENABLED:
            logger.error("No cached token available for user %s", username)
            raise AuthenticationError("No authentication token available for user %s" % username)

    # If authentication is disabled, proceed without a token
    if not AUTH_ENABLED:
        logger.debug("Authentication disabled, proceeding without token")
        token = None

    # Set up auth header if we have a token
    headers = {}
    if token:
        auth_header = f"Bearer {token}"
        headers["Authorization"] = auth_header
        logger.debug("Using Bearer token authentication for API call to %s", endpoint)
    else:
        logger.warning("No token for API call to %s", endpoint)

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
            logger.debug("✓ Cache hit for %s", endpoint)
            return cached_data

    # Not in cache or bypassing cache, make the API call
    url = f"{AUDIOBOOKSHELF_API}{endpoint}"
    logger.debug("📡 Fetching: %s%s", url, ' with params ' + str(params) if params else '')

    try:
        # Use a shorter timeout for faster failure detection when server is down
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.get(
                        url,
                        params=params,
                        headers=headers
                    ) as response:
                    response.raise_for_status()
                    data = await response.json()

                    # Store in cache
                    cache_set(cache_key, data)
                    return data
            except asyncio.TimeoutError as timeout_error:
                context = f"API call to {url}"
                logger.error("Timeout connecting to Audiobookshelf API at %s", url)
                raise APIClientError(
                    f"Audiobookshelf server is not responding. Please ensure it's running and accessible."
                ) from timeout_error
            except aiohttp.ClientResponseError as resp_error:
                context = f"API call to {url}"
                log_error(resp_error, context=context)

                # Check if this might be an authentication error
                if resp_error.status in (401, 403):
                    token_info = "Token present" if token else "No token"
                    logger.error("Authentication error (%s) for %s: %s", token_info, url, str(resp_error))

                    # Invalidate token cache on auth errors to force re-authentication
                    if username and username in TOKEN_CACHE:
                        del TOKEN_CACHE[username]
                        logger.debug("Invalidated token cache for %s due to auth error", username)

                    raise AuthenticationError(
                        f"Authentication failed for Audiobookshelf API: {str(resp_error)}"
                    ) from resp_error

                # For other response errors, provide a clearer message
                error_msg = f"Audiobookshelf API error (status {resp_error.status}): {str(resp_error)}"
                raise APIClientError(error_msg) from resp_error
    except aiohttp.ClientConnectorError as conn_error:
        # This happens when the server is down or unreachable - log as ERROR but without traceback
        error_id = id(conn_error)
        logger.error("ERROR [%s]: Cannot connect to Audiobookshelf server at %s", error_id, AUDIOBOOKSHELF_API)

        # Check if we have cached data we can use as a fallback
        if not bypass_cache:
            cached_data = cache_get(cache_key, cache_expiry, ignore_expiry=True)
            if cached_data is not None:
                logger.debug("Using expired cache data for %s because server is unreachable", endpoint)
                return cached_data

        raise APIClientError(
            f"Cannot connect to Audiobookshelf server. Please ensure it's running and accessible."
        ) from None  # Use "from None" to suppress the traceback in the logs
    except Exception as e:
        context = f"API call to {url}"
        log_error(e, context=context)
        raise APIClientError(
            f"Error communicating with Audiobookshelf API: {str(e)}"
        ) from e

@cached(expiry=LIBRARY_ITEMS_CACHE_EXPIRY)
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
            - token: The token used for authentication
    """
    try:
        # Log authentication information for debugging
        logger.debug("Getting download URLs for item %s, username: %s, token present: %s", item_id, username, token is not None)

        if token is None and username:
            cached_token = get_token_for_username(username)
            token = cached_token  # Use the cached token if available
            logger.debug("No token provided for download, using cached token: %s", cached_token is not None)

        item = await fetch_from_api(f"/items/{item_id}", username=username, token=token)
        ebook_inos = []
        for file in item.get("libraryFiles", []):
            if "ebook" in file.get("fileType", ""):
                file_info = {
                    "ino":          file.get("ino"),
                    "filename":     file.get("metadata", {}).get("filename", ""),
                    "download_url": "",
                    "token":        token  # Store the token with the file info
                }
                ebook_inos.append(file_info)
                logger.debug("Found ebook file: %s (ino: %s)", file_info['filename'], file_info['ino'])

        logger.debug("Found %d ebook files for item %s", len(ebook_inos), item_id)
        return ebook_inos
    except Exception as e:
        log_error(e, context="Getting download URLs for item %s" % item_id)
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
            logger.debug("Invalidated cache for %s", endpoint)
            return True
    return False
