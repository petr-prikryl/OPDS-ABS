"""Error handling utilities for the OPDS-ABS application.

This module provides standardized error handling functionality including
custom exceptions, error formatting, and logging helpers.
"""
import logging
from typing import Optional
from fastapi import HTTPException
from fastapi.responses import Response, JSONResponse

# Create a logger for this module
logger = logging.getLogger(__name__)

# Custom exception classes
class OPDSBaseException(Exception):
    """Base exception for all OPDS-ABS specific exceptions."""
    status_code = 500
    default_message = "An internal server error occurred"

class ResourceNotFoundError(OPDSBaseException):
    """Raised when a requested resource is not found."""
    status_code = 404
    default_message = "Resource not found"

class AuthenticationError(OPDSBaseException):
    """Raised when authentication fails."""
    status_code = 401
    default_message = "Authentication failed"

class APIClientError(OPDSBaseException):
    """Raised when there's an error communicating with Audiobookshelf."""
    status_code = 502
    default_message = "Error communicating with Audiobookshelf"

class FeedGenerationError(OPDSBaseException):
    """Raised when there's an error generating a feed."""
    status_code = 500
    default_message = "Error generating feed"

class CacheError(OPDSBaseException):
    """Raised when there's an error with the cache."""
    status_code = 500
    default_message = "Cache operation failed"

# Error handling functions
def handle_exception(
    exc: Exception, 
    context: str = "",
    log_traceback: bool = True,
    return_json: bool = False,
    status_code: Optional[int] = None
) -> Response:
    """Handle an exception in a standardized way.
    
    Args:
        exc: The exception to handle
        context: Additional context about where the error occurred
        log_traceback: Whether to log the full traceback
        return_json: Whether to return a JSON response instead of XML
        status_code: Optional status code to override the default
        
    Returns:
        A Response object with appropriate error details
    """
    # Determine the status code
    if isinstance(exc, OPDSBaseException):
        code = exc.status_code
        message = str(exc) or exc.default_message
    elif isinstance(exc, HTTPException):
        code = exc.status_code
        message = exc.detail
    else:
        code = 500
        message = str(exc) or "An unexpected error occurred"
    
    # Override status code if provided
    if status_code is not None:
        code = status_code
        
    # Log the error
    error_id = id(exc)  # Use the object id as a simple error reference
    log_prefix = f"Error [{error_id}]"
    
    if context:
        log_prefix += f" in {context}"
    
    if log_traceback:
        logger.exception(f"{log_prefix}: {message}")
    else:
        logger.error(f"{log_prefix}: {message}")
    
    # Create error response
    error_detail = {
        "error": True,
        "message": message,
        "error_id": str(error_id),
    }
    
    if context:
        error_detail["context"] = context
        
    # Return appropriate response format
    if return_json:
        return JSONResponse(
            status_code=code,
            content=error_detail
        )
    else:
        # Create simple XML error response
        xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<error xmlns="http://opds-spec.org/2010/catalog">
  <id>{error_id}</id>
  <message>{message}</message>
  {f"<context>{context}</context>" if context else ""}
</error>"""
        return Response(
            content=xml_content,
            media_type="application/xml",
            status_code=code
        )

def convert_to_http_exception(
    exc: Exception, 
    status_code: Optional[int] = None, 
    detail: Optional[str] = None
) -> HTTPException:
    """Convert any exception to an HTTPException with appropriate status code.
    
    Args:
        exc: The exception to convert
        status_code: Optional status code to override the default
        detail: Optional detail message to override the exception message
        
    Returns:
        An HTTPException
    """
    if isinstance(exc, OPDSBaseException):
        code = status_code or exc.status_code
        message = detail or str(exc) or exc.default_message
    elif isinstance(exc, HTTPException):
        code = status_code or exc.status_code
        message = detail or exc.detail
    else:
        code = status_code or 500
        message = detail or str(exc) or "An unexpected error occurred"
    
    return HTTPException(status_code=code, detail=message)

def log_error(
    exc: Exception,
    context: str = "",
    log_traceback: bool = True
) -> None:
    """Log an error in a standardized way.
    
    Args:
        exc: The exception to log
        context: Additional context about where the error occurred
        log_traceback: Whether to log the full traceback
    """
    error_id = id(exc)
    log_prefix = f"Error [{error_id}]"
    
    if context:
        log_prefix += f" in {context}"
    
    if log_traceback:
        logger.exception(f"{log_prefix}: {str(exc)}")
    else:
        logger.error(f"{log_prefix}: {str(exc)}")