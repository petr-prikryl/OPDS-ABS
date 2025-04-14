"""Routes for the OPDS feed.

This module contains all the FastAPI route definitions for the OPDS-ABS application
and configures the logging for the application.
"""
# Standard library imports
import os
import logging
import time
from urllib.parse import unquote

# Third-party imports
from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.exception_handlers import http_exception_handler

# Local application imports
from opds_abs.config import LOG_LEVEL
from opds_abs.feeds.library_feed import LibraryFeedGenerator
from opds_abs.feeds.navigation_feed import NavigationFeedGenerator
from opds_abs.feeds.series_feed import SeriesFeedGenerator
from opds_abs.feeds.collection_feed import CollectionFeedGenerator
from opds_abs.feeds.author_feed import AuthorFeedGenerator
from opds_abs.feeds.search_feed import SearchFeedGenerator
from opds_abs.utils.cache_utils import _cache, clear_cache
from opds_abs.api.client import invalidate_cache
from opds_abs.utils.error_utils import (
    OPDSBaseException,
    ResourceNotFoundError,
    FeedGenerationError,
    CacheError,
    handle_exception,
    convert_to_http_exception,
    log_error
)

# Define custom formatter to match uvicorn's style exactly
class ColorFormatter(logging.Formatter):
    """Custom log formatter that adds ANSI color codes to log levels.
    
    This formatter is designed to match uvicorn's log style with colorized
    log level names.
    """
    
    # ANSI color codes
    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",   # Green
        "WARNING": "\033[33m", # Yellow
        "ERROR": "\033[31m",   # Red
        "CRITICAL": "\033[1;31m", # Bold Red
        "RESET": "\033[0m"     # Reset
    }
    
    def format(self, record):
        """Format log record with color prefix.
        
        Args:
            record (LogRecord): The log record to format.
            
        Returns:
            str: The formatted log record with colorized level name.
        """
        if not hasattr(record, 'levelprefix'):
            level_name_length = len(record.levelname)
            spaces_needed = 8 - level_name_length
            spaces = " " * spaces_needed
            
            # Apply color to level name only, not colon or spaces
            levelname_color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
            record.levelprefix = f"{levelname_color}{record.levelname}{self.COLORS['RESET']}:{spaces}"
        return super().format(record)

# Set up logging for the entire application
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(levelprefix)s %(message)s",
    datefmt="[%X]",
    force=True,  # Override any existing configuration
)

# Apply the formatter to the root handler
for handler in logging.root.handlers:
    handler.setFormatter(ColorFormatter("%(levelprefix)s %(message)s"))

# Create a logger for this module
logger = logging.getLogger(__name__)

# Set more specific log level for our app's loggers
app_logger = logging.getLogger("opds_abs")
try:
    app_logger.setLevel(getattr(logging, LOG_LEVEL))
except AttributeError:
    app_logger.setLevel(logging.INFO)
    logger.warning(f"Invalid log level '{LOG_LEVEL}', defaulting to INFO")

# Log that we've configured logging
logger.info(f"OPDS-ABS logging configured at {LOG_LEVEL} level")

# Create instances of our feed generators
library_feed = LibraryFeedGenerator()
navigation_feed = NavigationFeedGenerator()
series_feed = SeriesFeedGenerator()
collection_feed = CollectionFeedGenerator()
author_feed = AuthorFeedGenerator()
search_feed = SearchFeedGenerator()

# Create FastAPI app
app = FastAPI()

# Mount static files directory
app.mount("/static", StaticFiles(directory="opds_abs/static"), name="static")

# Setup templates
templates = Jinja2Templates(directory="opds_abs/templates")

# Custom exception handler for OPDS exceptions
@app.exception_handler(OPDSBaseException)
async def opds_exception_handler(request: Request, exc: OPDSBaseException):
    """Handle custom OPDS exceptions using our error handling utilities.
    
    Args:
        request (Request): The request that caused the exception
        exc (OPDSBaseException): The exception that was raised
        
    Returns:
        Response: A standardized error response
    """
    context = f"{request.method} {request.url.path}"
    return handle_exception(exc, context=context)

# Fall back to standard HTTPException handling for other exceptions
@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    """Custom handler for HTTPExceptions that logs them before handling.
    
    Args:
        request (Request): The request that caused the exception
        exc (HTTPException): The exception that was raised
        
    Returns:
        Response: The standard FastAPI HTTP exception response
    """
    context = f"{request.method} {request.url.path}"
    log_error(exc, context=context, log_traceback=False)
    return await http_exception_handler(request, exc)

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Render the index page.
    
    Args:
        request (Request): The incoming request object.
        
    Returns:
        HTMLResponse: The rendered index.html template.
    """
    try:
        return templates.TemplateResponse("index.html", {"request": request})
    except Exception as e:
        log_error(e, context="Rendering index page")
        raise convert_to_http_exception(e, status_code=500, 
            detail="Failed to render index page") from e


@app.get("/opds/{username}/libraries/{library_id}/search.xml", response_class=HTMLResponse)
def search_xml(username: str, library_id: str, request: Request):
    """Render the search XML template.
    
    Args:
        username (str): The username of the authenticated user.
        library_id (str): ID of the library to search in.
        request (Request): The incoming request object.
        
    Returns:
        HTMLResponse: The rendered search.xml template.
    """
    try:
        params = dict(request.query_params)
        return templates.TemplateResponse("search.xml", {
            "request": request, 
            "username": username, 
            "library_id": library_id, 
            "searchTerms": params.get('q', '')
        })
    except Exception as e:
        log_error(e, context=f"Rendering search XML for user {username}, library {library_id}")
        raise convert_to_http_exception(e, status_code=500,
            detail="Failed to render search template") from e


@app.get("/opds/{username}")
async def opds_root(username: str):
    """Get the root OPDS feed for a user.
    
    Args:
        username (str): The username of the authenticated user.
        
    Returns:
        Response: The root feed listing available libraries.
    """
    try:
        return await library_feed.generate_root_feed(username)
    except ResourceNotFoundError as e:
        # ResourceNotFoundError is already properly handled in the feed generator
        raise
    except Exception as e:
        context = f"Generating root feed for user {username}"
        log_error(e, context=context)
        return handle_exception(e, context=context)


@app.get("/opds/{username}/libraries/{library_id}")
async def opds_nav(username: str, library_id: str):
    """Get the navigation feed for a library.
    
    Args:
        username (str): The username of the authenticated user.
        library_id (str): ID of the library to get navigation for.
        
    Returns:
        Response: The navigation feed for the specified library.
    """
    try:
        return await navigation_feed.generate_nav_feed(username, library_id)
    except ResourceNotFoundError as e:
        # ResourceNotFoundError is already properly handled in the feed generator
        raise
    except Exception as e:
        context = f"Generating navigation feed for user {username}, library {library_id}"
        log_error(e, context=context)
        return handle_exception(e, context=context)


@app.get("/opds/{username}/libraries/{library_id}/search")
async def opds_search(username: str, library_id: str, request: Request):
    """Search for items in a library.
    
    Args:
        username (str): The username of the authenticated user.
        library_id (str): ID of the library to search in.
        request (Request): The incoming request object containing search parameters.
        
    Returns:
        Response: The search results feed.
    """
    try:
        params = dict(request.query_params)
        return await search_feed.generate_search_feed(username, library_id, params)
    except ResourceNotFoundError as e:
        # ResourceNotFoundError is already properly handled in the feed generator
        raise
    except Exception as e:
        context = f"Searching in library {library_id} for user {username}"
        log_error(e, context=context)
        return handle_exception(e, context=context)


@app.get("/opds/{username}/libraries/{library_id}/items")
async def opds_library(username: str, library_id: str, request: Request):
    """Get items from a specific library.
    
    Args:
        username (str): The username of the authenticated user.
        library_id (str): ID of the library to get items from.
        request (Request): The incoming request object containing filter parameters.
        
    Returns:
        Response: The items feed for the specified library.
    """
    try:
        params = dict(request.query_params)
        return await library_feed.generate_library_items_feed(username, library_id, params)
    except ResourceNotFoundError as e:
        # ResourceNotFoundError is already properly handled in the feed generator
        raise
    except Exception as e:
        context = f"Generating items feed for user {username}, library {library_id}"
        log_error(e, context=context)
        return handle_exception(e, context=context)


@app.get("/opds/{username}/libraries/{library_id}/series")
async def opds_series(username: str, library_id: str):
    """Get series from a specific library.
    
    Args:
        username (str): The username of the authenticated user.
        library_id (str): ID of the library to get series from.
        
    Returns:
        Response: The series feed for the specified library.
    """
    try:
        return await series_feed.generate_series_feed(username, library_id)
    except ResourceNotFoundError as e:
        # ResourceNotFoundError is already properly handled in the feed generator
        raise
    except Exception as e:
        context = f"Generating series feed for user {username}, library {library_id}"
        log_error(e, context=context)
        return handle_exception(e, context=context)


@app.get("/opds/{username}/libraries/{library_id}/series/{series_id}")
async def opds_series_items(username: str, library_id: str, series_id: str):
    """Get items from a specific series using cached data when possible.
    
    Args:
        username (str): The username of the authenticated user.
        library_id (str): ID of the library to get items from.
        series_id (str): ID of the series to filter by.
        
    Returns:
        Response: The items feed for books in the specified series.
    """
    try:
        return await series_feed.generate_series_items_feed(username, library_id, series_id)
    except ResourceNotFoundError as e:
        # ResourceNotFoundError is already properly handled in the feed generator
        raise
    except Exception as e:
        context = f"Generating series items feed for user {username}, library {library_id}, series {series_id}"
        log_error(e, context=context)
        return handle_exception(e, context=context)


@app.get("/opds/{username}/libraries/{library_id}/collections")
async def opds_collections(username: str, library_id: str):
    """Get collections from a specific library.
    
    Args:
        username (str): The username of the authenticated user.
        library_id (str): ID of the library to get collections from.
        
    Returns:
        Response: The collections feed for the specified library.
    """
    try:
        return await collection_feed.generate_collections_feed(username, library_id)
    except ResourceNotFoundError as e:
        # ResourceNotFoundError is already properly handled in the feed generator
        raise
    except Exception as e:
        context = f"Generating collections feed for user {username}, library {library_id}"
        log_error(e, context=context)
        return handle_exception(e, context=context)


@app.get("/opds/{username}/libraries/{library_id}/collections/{collection_id}")
async def opds_collection_items(username: str, library_id: str, collection_id: str):
    """Get items from a specific collection using cached data when possible.
    
    Args:
        username (str): The username of the authenticated user.
        library_id (str): ID of the library to get items from.
        collection_id (str): ID of the collection to filter by.
        
    Returns:
        Response: The items feed for books in the specified collection.
    """
    try:
        return await collection_feed.generate_collection_items_feed(username, library_id, collection_id)
    except ResourceNotFoundError as e:
        # ResourceNotFoundError is already properly handled in the feed generator
        raise
    except Exception as e:
        context = f"Generating collection items feed for user {username}, library {library_id}, collection {collection_id}"
        log_error(e, context=context)
        return handle_exception(e, context=context)


@app.get("/opds/{username}/libraries/{library_id}/authors")
async def opds_authors(username: str, library_id: str):
    """Get authors from a specific library.
    
    Args:
        username (str): The username of the authenticated user.
        library_id (str): ID of the library to get authors from.
        
    Returns:
        Response: The authors feed for the specified library.
    """
    try:
        return await author_feed.generate_authors_feed(username, library_id)
    except ResourceNotFoundError as e:
        # ResourceNotFoundError is already properly handled in the feed generator
        raise
    except Exception as e:
        context = f"Generating authors feed for user {username}, library {library_id}"
        log_error(e, context=context)
        return handle_exception(e, context=context)


@app.get("/opds/{username}/libraries/{library_id}/authors/{author_id}")
async def opds_author_items(username: str, library_id: str, author_id: str):
    """Get items from a specific author using cached data when possible.
    
    Args:
        username (str): The username of the authenticated user.
        library_id (str): ID of the library to get items from.
        author_id (str): ID of the author to filter by.
        
    Returns:
        Response: The items feed for books by the specified author.
    """
    try:
        return await author_feed.generate_author_items_feed(username, library_id, author_id)
    except ResourceNotFoundError as e:
        # ResourceNotFoundError is already properly handled in the feed generator
        raise
    except Exception as e:
        context = f"Generating author items feed for user {username}, library {library_id}, author {author_id}"
        log_error(e, context=context)
        return handle_exception(e, context=context)


@app.get("/admin/cache/stats")
async def get_cache_stats():
    """Get statistics about the cache.
    
    Returns:
        JSONResponse: Statistics about the cache including entry count,
                      age information, and estimated size.
    """
    try:
        now = time.time()
        stats = {
            "total_entries": len(_cache),
            "entries": []
        }
        
        # Calculate memory usage and age of each entry
        for key, (timestamp, data) in _cache.items():
            age = int(now - timestamp)
            stats["entries"].append({
                "key": key[:8] + "...",  # Show truncated key for privacy
                "age_seconds": age,
                "age_minutes": round(age / 60, 1),
                "size_estimate": len(str(data))  # Rough size estimate
            })
        
        # Add summary stats
        if stats["entries"]:
            stats["oldest_entry_age"] = max(entry["age_seconds"] for entry in stats["entries"])
            stats["newest_entry_age"] = min(entry["age_seconds"] for entry in stats["entries"])
            stats["average_entry_age"] = sum(entry["age_seconds"] for entry in stats["entries"]) / len(stats["entries"])
            stats["total_size_estimate"] = sum(entry["size_estimate"] for entry in stats["entries"])
        
        return JSONResponse(content=stats)
    except Exception as e:
        log_error(e, context="Getting cache statistics")
        raise convert_to_http_exception(e, status_code=500,
            detail="Error retrieving cache statistics") from e


@app.post("/admin/cache/clear")
async def clear_all_cache():
    """Clear all items in the cache.
    
    Returns:
        JSONResponse: A message indicating how many items were cleared from the cache.
    """
    try:
        count = len(_cache)
        clear_cache()
        return JSONResponse(content={"message": f"Cleared {count} items from cache"})
    except Exception as e:
        log_error(e, context="Clearing cache")
        raise CacheError("Failed to clear cache") from e


@app.post("/admin/cache/invalidate")
async def invalidate_specific_cache(endpoint: str = None, username: str = None):
    """Invalidate cache for a specific endpoint.
    
    Args:
        endpoint (str, optional): The endpoint to invalidate cache for. Required.
        username (str, optional): The username to invalidate cache for. Defaults to None.
        
    Returns:
        JSONResponse: A message indicating the result of the cache invalidation.
        
    Raises:
        ResourceNotFoundError: If no matching cache entry was found.
    """
    if not endpoint:
        raise ResourceNotFoundError("Endpoint parameter is required")
        
    try:
        success = invalidate_cache(endpoint, username=username)
        
        if success:
            return JSONResponse(content={"message": f"Invalidated cache for {endpoint}"})
        else:
            raise ResourceNotFoundError(f"No cache found for {endpoint}")
    except ResourceNotFoundError:
        # Re-raise ResourceNotFoundError
        raise
    except Exception as e:
        log_error(e, context=f"Invalidating cache for {endpoint}")
        raise CacheError(f"Failed to invalidate cache for {endpoint}") from e