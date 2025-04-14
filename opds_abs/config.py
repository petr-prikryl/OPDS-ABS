"""Configuration settings for the application.

This module provides configuration settings for the application, loaded from
environment variables.
"""
# Standard library imports
import os

# Load configuration from environment variables
AUDIOBOOKSHELF_URL = os.getenv("AUDIOBOOKSHELF_URL", "http://localhost:13378")
AUDIOBOOKSHELF_API = AUDIOBOOKSHELF_URL + "/api"

# API key is used as default if no user token is available
API_KEY = os.getenv("AUDIOBOOKSHELF_API_KEY", "")

# Authentication configuration
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "true").lower() == "true"
AUTH_CACHE_EXPIRY = int(os.getenv("AUTH_CACHE_EXPIRY", "86400"))  # Default: 24 hours

# User credentials - will be deprecated in favor of Audiobookshelf authentication
users_env = os.getenv("USERS", "")
USER_KEYS = {}

if users_env:
    user_pairs = users_env.split(",")
    for pair in user_pairs:
        if ":" in pair:
            user, key = pair.split(":", 1)
            USER_KEYS[user] = key

# Logging configuration
LOG_LEVEL = os.environ.get("OPDS_LOG_LEVEL", "INFO").upper()