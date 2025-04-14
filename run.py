"""
OPDS Feed for Audiobookshelf - Entry Point
"""
import os
import logging
import uvicorn
from opds_abs.main import app
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