"""OPDS Feed for Audiobookshelf - Entry Point.

This script serves as the entry point for the OPDS-ABS application.
It configures and starts the uvicorn ASGI server with appropriate settings
based on the configured log level.

The server runs on all network interfaces (0.0.0.0) on port 8000 with
hot reload enabled for development convenience.
"""
import uvicorn
import logging
from opds_abs.config import (
    LOG_LEVEL, AUDIOBOOKSHELF_URL,
    AUDIOBOOKSHELF_INTERNAL_URL,
    AUDIOBOOKSHELF_EXTERNAL_URL,
    AUDIOBOOKSHELF_API
)

# Set up logging
logging.basicConfig(level=getattr(logging, LOG_LEVEL))
logger = logging.getLogger("opds_abs")

if __name__ == "__main__":
    # Log URL configurations
    logger.info("-" * 50)
    logger.info("Starting OPDS-ABS server with the following configuration:")
    logger.info(f"AUDIOBOOKSHELF_URL: {AUDIOBOOKSHELF_URL}")
    logger.info(f"AUDIOBOOKSHELF_INTERNAL_URL: {AUDIOBOOKSHELF_INTERNAL_URL}")
    logger.info(f"AUDIOBOOKSHELF_EXTERNAL_URL: {AUDIOBOOKSHELF_EXTERNAL_URL}")
    logger.info(f"AUDIOBOOKSHELF_API: {AUDIOBOOKSHELF_API}")
    logger.info("-" * 50)

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
