"""Configuration settings for the application.

This module provides configuration settings for the application, loaded from
environment variables.
"""
# Standard library imports
import os
import pathlib

# Legacy and fallback logic for Audiobookshelf URLs
_abs_url = os.getenv("AUDIOBOOKSHELF_URL")
_abs_internal = os.getenv("AUDIOBOOKSHELF_INTERNAL_URL")
_abs_external = os.getenv("AUDIOBOOKSHELF_EXTERNAL_URL")

if _abs_url:
	# Legacy: use AUDIOBOOKSHELF_URL for both
	AUDIOBOOKSHELF_INTERNAL_URL = _abs_url
	AUDIOBOOKSHELF_EXTERNAL_URL = _abs_url
elif _abs_internal and not _abs_external:
	AUDIOBOOKSHELF_INTERNAL_URL = _abs_internal
	AUDIOBOOKSHELF_EXTERNAL_URL = _abs_internal
elif _abs_external and not _abs_internal:
	AUDIOBOOKSHELF_INTERNAL_URL = _abs_external
	AUDIOBOOKSHELF_EXTERNAL_URL = _abs_external
else:
	# Both set or none set: use both or fallback to default
	AUDIOBOOKSHELF_INTERNAL_URL = _abs_internal or "http://localhost"
	AUDIOBOOKSHELF_EXTERNAL_URL = _abs_external or AUDIOBOOKSHELF_INTERNAL_URL

# API endpoints
AUDIOBOOKSHELF_API = AUDIOBOOKSHELF_INTERNAL_URL + "/api"

# Authentication configuration
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "true").lower() == "true"
AUTH_CACHE_EXPIRY = int(os.getenv("AUTH_CACHE_EXPIRY", "86400"))  # Default: 24 hours
API_KEY_AUTH_ENABLED = os.getenv("API_KEY_AUTH_ENABLED", "true").lower() == "true"  # Enable API key authentication
AUTH_TOKEN_CACHING = os.getenv("AUTH_TOKEN_CACHING", "true").lower() == "true"  # Enable token caching

# Cache configuration (in seconds)
AUTHORS_CACHE_EXPIRY = int(os.getenv("AUTHORS_CACHE_EXPIRY", "1800"))  # 30 minutes for collections
COLLECTIONS_CACHE_EXPIRY = int(os.getenv("COLLECTIONS_CACHE_EXPIRY", "1800"))  # 30 minutes for collections
DEFAULT_CACHE_EXPIRY = int(os.getenv("DEFAULT_CACHE_EXPIRY", "3600"))  # Default: 1 hour
LIBRARIES_CACHE_EXPIRY = int(os.getenv("LIBRARIES_CACHE_EXPIRY", "3600")) # Default: 1 hour
LIBRARY_ITEMS_CACHE_EXPIRY = int(os.getenv("LIBRARY_ITEMS_CACHE_EXPIRY", "1800"))  # Default: 30 minutes
SEARCH_RESULTS_CACHE_EXPIRY = int(os.getenv("SEARCH_RESULTS_CACHE_EXPIRY", "600"))  # Default: 10 minutes
SERIES_DETAILS_CACHE_EXPIRY = int(os.getenv("SERIES_DETAILS_CACHE_EXPIRY", "3600"))  # Default: 1 hour
SERIES_ITEMS_CACHE_EXPIRY = int(os.getenv("SERIES_ITEMS_CACHE_EXPIRY", "1800"))  # Default: 30 minutes

# Cache persistence configuration
CACHE_PERSISTENCE_ENABLED = os.getenv("CACHE_PERSISTENCE_ENABLED", "true").lower() == "true"
CACHE_FILE_PATH = os.getenv("CACHE_FILE_PATH", str(pathlib.Path(__file__).parent / "data" / "cache.pkl"))
CACHE_SAVE_INTERVAL = int(os.getenv("CACHE_SAVE_INTERVAL", "300"))  # Save cache every 5 minutes by default

# Pagination configuration
PAGINATION_ENABLED = os.getenv("PAGINATION_ENABLED", "true").lower() == "true"  # Enable/disable pagination
ITEMS_PER_PAGE = int(os.getenv("ITEMS_PER_PAGE", "25"))  # Default: 25 items per page

# Logging configuration
LOG_LEVEL = os.environ.get("OPDS_LOG_LEVEL", "INFO").upper()
