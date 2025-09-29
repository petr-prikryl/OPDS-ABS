"""Configuration settings for the application.

This module provides configuration settings for the application, loaded from
environment variables.
"""
# Standard library imports
import os
import pathlib

# Load configuration from environment variables
AUDIOBOOKSHELF_URL = os.getenv("AUDIOBOOKSHELF_URL", "http://localhost:13378")
AUDIOBOOKSHELF_INTERNAL_URL = os.getenv("AUDIOBOOKSHELF_INTERNAL_URL", AUDIOBOOKSHELF_URL)
AUDIOBOOKSHELF_EXTERNAL_URL = os.getenv("AUDIOBOOKSHELF_EXTERNAL_URL", AUDIOBOOKSHELF_URL)

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
