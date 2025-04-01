""" Load environment variables and split API keys """
import os

# Load configuration from environment variables
AUDIOBOOKSHELF_URL = os.getenv("AUDIOBOOKSHELF_URL", "http://localhost:13378")
AUDIOBOOKSHELF_API = f"{AUDIOBOOKSHELF_URL}/api"

# Load user API keys from environment variables
USER_KEYS = {}
users_env = os.getenv("USERS", "")
for pair in users_env.split(","):
    if ":" in pair:
        USERNAME, API_KEY = pair.split(":", 1)
        USER_KEYS[USERNAME] = API_KEY
