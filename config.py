"""Load environment variables and split API keys."""
import os

# Load configuration from environment variables
# Note: This file is a legacy file. The main configuration is in opds_abs/config.py
# Define URLs with explicit priority for internal/external URLs
AUDIOBOOKSHELF_URL = os.getenv("AUDIOBOOKSHELF_URL", "http://localhost:13378")

# Allow explicit override of internal/external URLs
AUDIOBOOKSHELF_INTERNAL_URL = os.getenv("AUDIOBOOKSHELF_INTERNAL_URL", AUDIOBOOKSHELF_URL)
AUDIOBOOKSHELF_EXTERNAL_URL = os.getenv("AUDIOBOOKSHELF_EXTERNAL_URL", AUDIOBOOKSHELF_URL)

# API endpoints - always use the internal URL for API calls
AUDIOBOOKSHELF_API = f"{AUDIOBOOKSHELF_INTERNAL_URL}/api"

# Load user API keys from environment variables
USER_KEYS = {}
users_env = os.getenv("USERS", "")
for pair in users_env.split(","):
    if ":" in pair:
        USERNAME, API_KEY = pair.split(":", 1)
        USER_KEYS[USERNAME] = API_KEY
