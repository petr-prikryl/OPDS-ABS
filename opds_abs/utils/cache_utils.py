"""Caching utilities for API responses.

This module provides functions for caching API responses and other data
to reduce API calls and improve application performance. It implements
a simple in-memory cache with time-based expiration.
"""
import time
import logging
from typing import Dict, Any, Optional, Tuple, Callable, List
import functools
import hashlib
import json
from functools import wraps

logger = logging.getLogger(__name__)

# Cache dictionary: key -> (timestamp, data)
_cache: Dict[str, Tuple[float, Any]] = {}

# Default cache expiry time (in seconds)
DEFAULT_CACHE_EXPIRY = 3600  # 1 hour
# Cache expiry for library items (in seconds)
LIBRARY_ITEMS_CACHE_EXPIRY = 1800  # 30 minutes
# Cache expiry for search results (in seconds)
SEARCH_RESULTS_CACHE_EXPIRY = 600  # 10 minutes


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


def cache_get(key: str, max_age: int = DEFAULT_CACHE_EXPIRY) -> Optional[Any]:
    """Get an item from the cache if it exists and isn't expired.
    
    Args:
        key: Cache key
        max_age: Maximum age in seconds for cached item
        
    Returns:
        The cached data or None if not found or expired
    """
    if key not in _cache:
        return None
    
    timestamp, data = _cache[key]
    if time.time() - timestamp > max_age:
        # Cache expired, remove it
        del _cache[key]
        return None
    
    return data


def cache_set(key: str, data: Any) -> None:
    """Store an item in the cache.
    
    Args:
        key: Cache key
        data: Data to cache
    """
    _cache[key] = (time.time(), data)


def clear_cache() -> None:
    """Clear all cached items."""
    _cache.clear()


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
                logger.debug(f"Cache hit for {func_name}")
                return cached_data
            
            # Not in cache, call the function
            logger.debug(f"Cache miss for {func_name}")
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
            logger.debug(f"✓ Cache hit for all library items {library_id}")
            return cached_data  # Return cached data
    
    # Not in cache or bypassing cache, fetch the data
    logger.debug(f"Fetching all library items for library {library_id}")
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
            logger.debug(f"✓ Cache hit for search query: {query}")
            return cached_data
    
    # Not in cache or bypassing cache, perform the search
    logger.debug(f"Performing search for query: {query}")
    search_params = {"limit": 2000, "q": query}
    search_data = await fetch_from_api_func(f"/libraries/{library_id}/search", search_params, username=username, token=token)
    
    # Store in cache for future use
    cache_set(cache_key, search_data)
    
    return search_data