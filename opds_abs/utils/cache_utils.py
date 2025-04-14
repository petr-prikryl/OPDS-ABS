"""Caching utilities for API responses.

This module provides functions for caching API responses and other data
to reduce API calls and improve application performance. It implements
a simple in-memory cache with time-based expiration.
"""
import time
import logging
from typing import Dict, Any, Optional, Tuple, Callable
import functools
import hashlib
import json

logger = logging.getLogger(__name__)

# Cache dictionary: key -> (timestamp, data)
_cache: Dict[str, Tuple[float, Any]] = {}

# Default cache expiry time (in seconds)
DEFAULT_CACHE_EXPIRY = 3600  # 1 hour


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