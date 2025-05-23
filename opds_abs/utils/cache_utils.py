"""Caching utilities for API responses.

This module provides functions for caching API responses and other data
to reduce API calls and improve application performance. It implements
a simple in-memory cache with time-based expiration and optional
persistence using pickle.
"""
# Standard library imports
import time
import logging
import os
import pickle
import threading
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Callable
import functools
import hashlib
import json
import asyncio
import base64

# Local application imports
from opds_abs.config import (
    DEFAULT_CACHE_EXPIRY,
    LIBRARY_ITEMS_CACHE_EXPIRY,
    SEARCH_RESULTS_CACHE_EXPIRY,
    SERIES_DETAILS_CACHE_EXPIRY,
    SERIES_ITEMS_CACHE_EXPIRY,  # Add this new constant
    CACHE_PERSISTENCE_ENABLED,
    CACHE_FILE_PATH,
    CACHE_SAVE_INTERVAL,
    AUTHORS_CACHE_EXPIRY
)

logger = logging.getLogger(__name__)

# Cache dictionary: key -> (timestamp, data)
_cache: Dict[str, Tuple[float, Any]] = {}
_last_save_time = 0
_cache_lock = threading.RLock()


def _create_cache_key(endpoint: str, params: Optional[Dict] = None, username: Optional[str] = None) -> str:
    """Create a unique cache key from the endpoint and parameters.

    Args:
        endpoint: API endpoint
        params: Query parameters
        username: Username for user-specific caching

    Returns:
        A unique string key for the cache
    """
    # Convert params to a stable string representation
    params_str = json.dumps(params, sort_keys=True) if params else "{}"

    # Create components for the key
    components = [endpoint, params_str]
    if username:
        components.append(username)

    # Create a hash of the components
    key_str = "".join(components)
    return hashlib.md5(key_str.encode()).hexdigest()


def load_cache_from_disk() -> None:
    """Load the cache from disk if available.

    This function attempts to restore the previously saved cache state from disk
    into memory. It first checks if cache persistence is enabled in the configuration.
    If the cache file exists, it reads and deserializes the data using pickle.

    The function handles various error conditions gracefully, starting with an empty
    cache if the file doesn't exist or if there's an error during loading. It also
    provides detailed logging about the number of items loaded and how many are
    still valid (non-expired).

    The function uses a thread lock to ensure thread safety during cache loading.

    Raises:
        pickle.PickleError: If there is an error unpickling the cache data.
        IOError: If there is an error reading the cache file.
        EOFError: If the cache file is empty or corrupted.
    """
    global _cache

    if not CACHE_PERSISTENCE_ENABLED:
        logger.debug("Cache persistence is disabled, skipping load from disk")
        return

    try:
        cache_path = Path(CACHE_FILE_PATH)

        # Create the directory if it doesn't exist
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        if not cache_path.exists():
            logger.info("Cache file does not exist at %s, starting with empty cache", CACHE_FILE_PATH)
            return

        with cache_path.open("rb") as f:
            with _cache_lock:
                loaded_cache = pickle.load(f)
                _cache = loaded_cache

        # Count non-expired items
        current_time = time.time()
        valid_items = sum(1 for _, (timestamp, _) in _cache.items()
                          if current_time - timestamp <= DEFAULT_CACHE_EXPIRY)

        logger.info("Loaded %d cached items from disk (%d non-expired)", len(_cache), valid_items)

    except (pickle.PickleError, IOError, EOFError) as e:
        logger.warning("Failed to load cache from disk: %s", str(e))
        # Start with an empty cache if loading fails
        _cache = {}


def save_cache_to_disk() -> None:
    """Save the current in-memory cache to disk for persistence.

    This function writes the current state of the in-memory cache to a pickle file
    on disk for persistent storage. Before saving, it cleans expired items from the
    cache. The function also implements rate-limiting to prevent excessive disk writes
    by only saving if enough time has passed since the last save operation.

    The function uses a threading lock to prevent race conditions during save operations.
    If cache persistence is disabled in the configuration, this function does nothing.

    Raises:
        pickle.PickleError: If there is an error pickling the cache data.
        IOError: If there is an error writing to the cache file.
    """
    global _last_save_time

    if not CACHE_PERSISTENCE_ENABLED:
        return

    current_time = time.time()

    # Use a lock to prevent concurrent access during save
    with _cache_lock:
        # Only save if enough time has passed since last save
        if current_time - _last_save_time < CACHE_SAVE_INTERVAL:
            return

        # Clean expired items before saving
        expired_keys = []
        for key, (timestamp, _) in _cache.items():
            if current_time - timestamp > DEFAULT_CACHE_EXPIRY:
                expired_keys.append(key)

        for key in expired_keys:
            del _cache[key]

        # Update last save time
        _last_save_time = current_time

    try:
        cache_path = Path(CACHE_FILE_PATH)

        # Create the directory if it doesn't exist
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        # Save cache to file
        with cache_path.open("wb") as f:
            with _cache_lock:
                pickle.dump(_cache, f, protocol=pickle.HIGHEST_PROTOCOL)

        logger.debug("Saved %d cache items to %s", len(_cache), CACHE_FILE_PATH)

    except (pickle.PickleError, IOError) as e:
        logger.error("Failed to save cache to disk: %s", str(e))


def cache_get(key: str, max_age: int = DEFAULT_CACHE_EXPIRY, ignore_expiry: bool = False) -> Optional[Any]:
    """Get an item from the cache if it exists and isn't expired.

    Args:
        key: Cache key
        max_age: Maximum age in seconds for cached item
        ignore_expiry: If True, return the data even if expired (used for fallbacks when server is down)

    Returns:
        The cached data or None if not found or expired
    """
    with _cache_lock:
        if key not in _cache:
            return None

        timestamp, data = _cache[key]
        if not ignore_expiry and time.time() - timestamp > max_age:
            # Cache expired, remove it unless ignore_expiry is True
            del _cache[key]
            return None

        return data


def cache_set(key: str, data: Any) -> None:
    """Store an item in the cache.

    Args:
        key: Cache key
        data: Data to cache
    """
    with _cache_lock:
        _cache[key] = (time.time(), data)

    # Schedule background save if enough time has passed
    if CACHE_PERSISTENCE_ENABLED and time.time() - _last_save_time >= CACHE_SAVE_INTERVAL:
        # Use a thread to save the cache without blocking
        threading.Thread(target=save_cache_to_disk, daemon=True).start()


def clear_cache() -> int:
    """Clear all cached items from memory and disk.

    This function removes all entries from the in-memory cache dictionary,
    effectively invalidating all cached data. If cache persistence is enabled
    in the configuration, it also triggers a save of the empty cache to disk,
    overwriting the previous cache file.

    The function uses a thread lock to ensure thread safety during the operation.

    Returns:
        int: The number of items that were cleared from the cache
    """
    with _cache_lock:
        count = len(_cache)
        _cache.clear()
        logger.info("Cleared %d items from cache", count)

    if CACHE_PERSISTENCE_ENABLED:
        save_cache_to_disk()

    return count


def cached(expiry: int = DEFAULT_CACHE_EXPIRY) -> Callable:
    """Decorator to cache function results.

    Args:
        expiry: Cache expiry time in seconds

    Returns:
        Decorated function with caching
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Create a cache key based on the function name and arguments
            func_name = func.__name__
            args_str = json.dumps([str(a) for a in args], sort_keys=True) if args else "[]"
            kwargs_str = json.dumps(kwargs, sort_keys=True) if kwargs else "{}"

            cache_key = hashlib.md5(f"{func_name}:{args_str}:{kwargs_str}".encode()).hexdigest()

            # Try to get from cache
            cached_data = cache_get(cache_key, expiry)
            if cached_data is not None:
                logger.debug("Cache hit for %s", func_name)
                return cached_data

            # Not in cache, call the function
            logger.debug("Cache miss for %s", func_name)
            data = await func(*args, **kwargs)

            # Store in cache
            cache_set(cache_key, data)
            return data

        return wrapper
    return decorator


async def get_cached_library_items(fetch_from_api_func, filter_items_func, username, library_id, token=None, bypass_cache=False):
    """Fetch and cache all library items that can be reused for filtering.

    This method fetches all library items and caches them so they can be
    reused when processing search results instead of making additional API calls.

    Args:
        fetch_from_api_func (callable): The function to fetch data from the API.
        filter_items_func (callable): The function to filter items.
        username (str): The username of the authenticated user.
        library_id (str): ID of the library to fetch items from.
        token (str, optional): Authentication token for Audiobookshelf.
        bypass_cache (bool): Whether to bypass the cache and force a fresh fetch.

    Returns:
        list: All filtered library items containing ebooks.
    """
    cache_key = _create_cache_key(f"/library-items-all/{library_id}", None, username)

    # Try to get from cache if not bypassing
    if not bypass_cache:
        cached_data = cache_get(cache_key, LIBRARY_ITEMS_CACHE_EXPIRY)
        if cached_data is not None:
            logger.debug("✓ Cache hit for all library items %s", library_id)
            return cached_data  # Return cached data

    # Not in cache or bypassing cache, fetch the data
    logger.debug("Fetching all library items for library %s", library_id)
    items_params = {"limit": 10000, "expand": "media"}
    data = await fetch_from_api_func(f"/libraries/{library_id}/items", items_params, username=username, token=token)
    library_items = filter_items_func(data)

    # Store in cache for future use
    cache_set(cache_key, library_items)

    return library_items


async def get_cached_search_results(fetch_from_api_func, username, library_id, query, token=None, bypass_cache=False):
    """Fetch and cache search results to avoid repeated API calls.

    Args:
        fetch_from_api_func (callable): The function to fetch data from the API.
        username (str): The username of the authenticated user.
        library_id (str): ID of the library to search in.
        query (str): Search query string.
        token (str, optional): Authentication token for Audiobookshelf.
        bypass_cache (bool): Whether to bypass the cache and force a fresh search.

    Returns:
        dict: Search results from API or cache.
    """
    cache_key = _create_cache_key(f"/libraries/{library_id}/search", {"q": query}, username)

    # Try to get from cache if not bypassing
    if not bypass_cache:
        cached_data = cache_get(cache_key, SEARCH_RESULTS_CACHE_EXPIRY)
        if cached_data is not None:
            logger.debug("✓ Cache hit for search query: %s", query)
            return cached_data

    # Not in cache or bypassing cache, perform the search
    logger.debug("Performing search for query: %s", query)
    search_params = {"limit": 2000, "q": query}
    search_data = await fetch_from_api_func(f"/libraries/{library_id}/search", search_params, username=username, token=token)

    # Store in cache for future use
    cache_set(cache_key, search_data)

    return search_data


async def get_cached_series_details(fetch_from_api_func, username, library_id, series_id, token=None):
    """Fetch and cache detailed information about a specific series.

    This method caches series details to avoid redundant API calls when
    the same series information is requested multiple times.

    Args:
        fetch_from_api_func (callable): The function to fetch data from the API.
        username (str): The username of the authenticated user.
        library_id (str): ID of the library containing the series.
        series_id (str): ID of the series to get details for.
        token (str, optional): Authentication token for Audiobookshelf.

    Returns:
        dict: Series details or None if not found.
    """
    # Create a cache key for this specific series
    cache_key = _create_cache_key(f"/series-details/{library_id}/{series_id}", None, username)

    # Try to get from cache first
    cached_data = cache_get(cache_key, SERIES_DETAILS_CACHE_EXPIRY)
    if cached_data is not None:
        logger.debug("✓ Cache hit for series details %s", series_id)
        return cached_data

    # Not in cache, fetch the series data
    logger.debug("Fetching series details for series %s", series_id)

    # Get all series to find the one with the matching ID
    try:
        series_params = {"limit": 2000, "sort": "name"}
        data = await fetch_from_api_func(f"/libraries/{library_id}/series", series_params, username=username, token=token)

        # Find the series with the matching ID
        series_details = None
        for series in data.get("results", []):
            if series.get("id") == series_id:
                series_details = series
                break

        # Store in cache for future use if we found details
        if series_details:
            cache_set(cache_key, series_details)

        return series_details
    except Exception as e:
        logger.error("Error fetching series details: %s", e)
        return None


async def get_cached_author_details(fetch_func, filter_func, username, library_id, token=None, bypass_cache=False):
    """Fetch and cache author information, focusing on authors who have books with ebook files.

    Args:
        fetch_func (callable): The function to fetch data from the API.
        filter_func (callable): Function to filter items.
        username (str): The username of the authenticated user.
        library_id (str): ID of the library to search in.
        token (str, optional): Authentication token for Audiobookshelf.
        bypass_cache (bool): Whether to bypass cache and force fresh data lookup.

    Returns:
        list: A list of dictionaries containing author information with ebook counts.
    """
    # Create a cache key specifically for authors with ebooks
    cache_key = _create_cache_key(f"/authors-with-ebooks/{library_id}", None, username)

    # Try to get from cache first if not bypassing
    if not bypass_cache:
        cached_data = cache_get(cache_key, AUTHORS_CACHE_EXPIRY)
        if cached_data is not None:
            logger.debug("✓ Cache hit for authors with ebooks in library %s", library_id)
            return cached_data

    # Use cached library items instead of fetching directly
    library_items = await get_cached_library_items(
        fetch_func,
        filter_func,
        username,
        library_id,
        token=token
    )

    if not library_items:
        logger.debug("No library items found for library %s", library_id)
        return []

    # First collect basic author info from items
    authors_with_ebooks = {}

    # Optimize ebook detection with a single pass through the items
    for item in library_items:
        media = item.get("media", {})
        metadata = media.get("metadata", {})

        # Efficient ebook detection
        has_ebook = (
            media.get("ebookFile") is not None or
            (media.get("ebookFormat") is not None and media.get("ebookFormat"))
        )

        if has_ebook:
            # Get author name from metadata
            author_name = metadata.get("authorName")
            if author_name:
                # Add or update author in our tracking dictionary
                if author_name in authors_with_ebooks:
                    authors_with_ebooks[author_name]["ebook_count"] += 1
                else:
                    authors_with_ebooks[author_name] = {
                        "name": author_name,
                        "ebook_count": 1,
                        "id": None,  # Will be populated from author details
                        "imagePath": None  # Will be populated from author details
                    }

    # Now get full author details from the API
    authors_params = {"limit": 2000, "sort": "name"}
    author_data = await fetch_func(f"/libraries/{library_id}/authors", authors_params, username=username, token=token)

    if not author_data or "authors" not in author_data:
        logger.warning("Failed to retrieve full author details")
        # Just return what we have so far
        return list(authors_with_ebooks.values())

    # Enhance author information with details from the author endpoint
    for author in author_data.get("authors", []):
        author_name = author.get("name")
        if author_name and author_name in authors_with_ebooks:
            # Add ID and image path from author details
            authors_with_ebooks[author_name]["id"] = author.get("id")
            authors_with_ebooks[author_name]["imagePath"] = author.get("imagePath")

    # Convert to list for the caller
    authors_list = list(authors_with_ebooks.values())

    # Cache the result for future use
    cache_set(cache_key, authors_list)

    logger.debug("Found %d authors with ebooks in library %s", len(authors_list), library_id)
    return authors_list


async def get_cached_series_items(fetch_from_api_func, filter_items_func, username, library_id, series_id, token=None, bypass_cache=False):
    """Fetch and cache items for a specific series by directly querying the items endpoint with series filter.

    This ensures we get the proper sequence information for items in a series.

    Args:
        fetch_from_api_func (callable): The function to fetch data from the API.
        filter_items_func (callable): The function to filter items.
        username (str): The username of the authenticated user.
        library_id (str): ID of the library containing the items.
        series_id (str): ID of the series to filter by.
        token (str, optional): Authentication token for Audiobookshelf.
        bypass_cache (bool): Whether to bypass the cache and force a fresh fetch.

    Returns:
        list: Library items filtered by the specified series ID with sequence information.
    """
    # Create a cache key for this specific series items
    cache_key = _create_cache_key(f"/series-items/{library_id}/{series_id}", None, username)

    # Try to get from cache if not bypassing
    if not bypass_cache:
        cached_data = cache_get(cache_key, SERIES_ITEMS_CACHE_EXPIRY)
        if cached_data is not None:
            logger.debug("✓ Cache hit for series items %s", series_id)
            return cached_data

    # Not in cache or bypassing cache, query the items endpoint with series filter
    logger.debug("Fetching items for series %s using direct items query", series_id)

    # Create base64 encoded filter for the series ID
    base64_series_id = base64.b64encode(series_id.encode()).decode()

    # Query items endpoint with the series filter to get proper sequence information
    params = {"filter": f"series.{base64_series_id}", "sort": "media.metadata.series.sequence"}
    data = await fetch_from_api_func(
        f"/libraries/{library_id}/items",
        params,
        username=username,
        token=token
    )

    # Filter items that contain ebooks
    filtered_items = filter_items_func(data)

    # Store in cache for future use
    cache_set(cache_key, filtered_items)

    logger.debug("Found %d items for series %s", len(filtered_items), series_id)
    return filtered_items
