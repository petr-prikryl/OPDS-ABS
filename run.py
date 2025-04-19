"""OPDS Feed for Audiobookshelf - Entry Point.

This script serves as the entry point for the OPDS-ABS application.
It configures and starts the uvicorn ASGI server with appropriate settings
based on the configured log level.

The server runs on all network interfaces (0.0.0.0) on port 8000 with
hot reload enabled for development convenience.
"""
import uvicorn
from opds_abs.config import LOG_LEVEL

if __name__ == "__main__":
    # Use log level from config.py, but convert to lowercase for uvicorn
    log_level = LOG_LEVEL.lower()

    # Run uvicorn with the specified log level and enable colored logs
    uvicorn.run(
        "opds_abs.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=log_level,
        use_colors=True
    )
