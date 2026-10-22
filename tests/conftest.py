"""Shared test configuration.

A fake Audiobookshelf is started before the application modules are imported, so
``opds_abs.config`` points at it for the whole session.
"""
import os
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent
for path in (str(TESTS_DIR), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from fake_abs import start_server  # noqa: E402

SERVER, BASE_URL = start_server()

os.environ["AUDIOBOOKSHELF_URL"] = BASE_URL
os.environ["AUTH_ENABLED"] = "true"
os.environ["API_KEY_AUTH_ENABLED"] = "true"
os.environ["AUTH_TOKEN_CACHING"] = "true"
os.environ["CACHE_PERSISTENCE_ENABLED"] = "false"
os.environ["OPDS_LOG_LEVEL"] = "CRITICAL"
os.environ["ITEMS_PER_PAGE"] = "1"


def pytest_sessionfinish(session, exitstatus):
    """Stop the fake Audiobookshelf after the session."""
    SERVER.shutdown()
