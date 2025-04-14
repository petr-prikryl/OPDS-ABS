"""Series feed generator"""
# Standard library imports
import logging
import asyncio

# Third-party imports
from lxml import etree

# Local application imports
from opds_abs.core.feed_generator import BaseFeedGenerator
from opds_abs.api.client import fetch_from_api, get_download_urls_from_item
from opds_abs.config import AUDIOBOOKSHELF_API
from opds_abs.utils import dict_to_xml
from opds_abs.utils.cache_utils import _create_cache_key, cache_get, cache_set
from opds_abs.utils.error_utils import (
    FeedGenerationError,
    ResourceNotFoundError,
    log_error,
    handle_exception
)
from opds_abs.utils.auth_utils import verify_user

# Set up logging
logger = logging.getLogger(__name__)

# Cache expiry for library items (in seconds)
LIBRARY_ITEMS_CACHE_EXPIRY = 1800  # 30 minutes

class SeriesFeedGenerator(BaseFeedGenerator):
    """Generator for series feed"""
    
    async def get_cached_library_items(self, username, library_id, token=None, bypass_cache=False):
        """Fetch and cache all library items that can be reused for filtering.
        
        This method fetches all library items and caches them so they can be 
        reused when filtering by series instead of making additional API calls.
        
        Args:
            username (str): The username of the authenticated user.
            library_id (str): ID of the library to fetch items from.
            token (str, optional): Authentication token for Audiobookshelf.
            bypass_cache (bool): Whether to bypass the cache and force a fresh fetch.
            
        Returns:
            list: All filtered library items containing ebooks.
        """
        cache_key = _create_cache_key(f"/library-items-all/{library_id}", None, username)
        
        # Try to get from cache if not bypassing
        if not bypass_cache:
            cached_data = cache_get(cache_key, LIBRARY_ITEMS_CACHE_EXPIRY)
            if cached_data is not None:
                logger.debug(f"✓ Cache hit for all library items {library_id}")
                return cached_data  # Return cached data
        
        # Not in cache or bypassing cache, fetch the data
        logger.debug(f"Fetching all library items for library {library_id}")
        items_params = {"limit": 10000, "expand": "media"}
        data = await fetch_from_api(f"/libraries/{library_id}/items", items_params, username=username, token=token)
        library_items = self.filter_items(data)
        
        # Store in cache for future use
        cache_set(cache_key, library_items)
        
        return library_items
    
    async def get_series_details(self, username, library_id, series_id, token=None):
        """Fetch detailed information about a specific series.
        
        Args:
            username (str): The username of the authenticated user.
            library_id (str): ID of the library containing the series.
            series_id (str): ID of the series to get details for.
            token (str, optional): Authentication token for Audiobookshelf.
            
        Returns:
            dict: Series details or None if not found.
        """
        try:
            # First get all series to find the one we want
            series_params = {"limit": 2000, "sort": "name"}
            data = await fetch_from_api(f"/libraries/{library_id}/series", series_params, username=username, token=token)
            
            # Find the series with the matching ID
            for series in data.get("results", []):
                if series.get("id") == series_id:
                    return series
            
            return None
        except Exception as e:
            logger.error(f"Error fetching series details: {e}")
            return None
        
    async def filter_items_by_series_id(self, username, library_id, series_id, token=None):
        """Filter items by series ID using cached items when possible.
        
        Args:
            username (str): The username of the authenticated user.
            library_id (str): ID of the library containing the items.
            series_id (str): ID of the series to filter by.
            token (str, optional): Authentication token for Audiobookshelf.
            
        Returns:
            list: Library items filtered by the specified series ID.
        """
        try:
            # Try to get all library items from cache first
            library_items = await self.get_cached_library_items(username, library_id, token=token)
            
            # Get series details to find the name
            series_details = await self.get_series_details(username, library_id, series_id, token=token)
            series_name = series_details.get("name") if series_details else None
            
            if not series_name:
                logger.warning(f"Could not find series name for ID {series_id}")
                # Fall back to API call if we couldn't find the series name
                params = {"filter": f"series.{self.create_filter(series_id)}"}
                data = await fetch_from_api(f"/libraries/{library_id}/items", params, username=username, token=token)
                return self.filter_items(data)
            
            logger.info(f"Filtering cached items by series: {series_name}")
            
            # Filter the cached items by series name in-memory
            filtered_items = []
            for item in library_items:
                media = item.get("media", {})
                metadata = media.get("metadata", {})
                
                # Extract series information from metadata
                series_info = metadata.get("seriesName", "")
                
                # If series name is part of the series info (will be in format "Series Name #X")
                if series_name in series_info:
                    filtered_items.append(item)
            
            # Sort by series sequence number if available
            sorted_items = sorted(
                filtered_items,
                key=lambda x: x.get('media', {}).get('metadata', {}).get('series', {}).get('sequence', 0)
            )
            
            logger.info(f"Found {len(sorted_items)} items in series {series_name}")
            return sorted_items
            
        except Exception as e:
            logger.error(f"Error filtering items by series: {e}")
            # Fall back to API call if there was an error
            params = {"filter": f"series.{self.create_filter(series_id)}", 
                      "sort": "media.metadata.series.number"}
            data = await fetch_from_api(f"/libraries/{library_id}/items", params, username=username, token=token)
            return self.filter_items(data)
    
    async def generate_series_items_feed(self, username, library_id, series_id, token=None):
        """Generate a feed of items in a specific series.
        
        Args:
            username (str): The username requesting the feed.
            library_id (str): The ID of the library to generate the feed for.
            series_id (str): The ID of the series to filter by.
            token (str, optional): Authentication token for Audiobookshelf.
            
        Returns:
            Response: A FastAPI response object containing the XML feed.
        """
        try:
            # Verify the user exists
            verify_user(username, token)
            
            # Get items filtered by series (using cache when possible)
            library_items = await self.filter_items_by_series_id(username, library_id, series_id, token=token)
            
            # Get series name
            series_name = "Unknown Series"
            series_details = await self.get_series_details(username, library_id, series_id, token=token)
            if series_details:
                series_name = series_details.get("name", "Unknown Series")
            
            # Create the feed
            feed = self.create_base_feed(username, library_id)
            
            # Build the feed metadata
            feed_data = {
                "id": {"_text": library_id},
                "author": {
                    "name": {"_text": "OPDS Audiobookshelf"}
                },
                "title": {"_text": f"{series_name} Series"}
            }
            
            # Convert feed metadata to XML
            dict_to_xml(feed, feed_data)
            
            if not library_items:
                error_data = {
                    "entry": {
                        "title": {"_text": "No books found"},
                        "content": {"_text": f"No books in the {series_name} series with ebooks were found in this library."}
                    }
                }
                dict_to_xml(feed, error_data)
                return self.create_response(feed)
            
            # Get ebook files for each book
            tasks = []
            for book in library_items:
                book_id = book.get("id", "")
                tasks.append(get_download_urls_from_item(book_id, username=username, token=token))
            
            ebook_inos_list = await asyncio.gather(*tasks)
            for book, ebook_inos in zip(library_items, ebook_inos_list):
                self.add_book_to_feed(feed, book, ebook_inos, "", token)
            
            return self.create_response(feed)
            
        except Exception as e:
            # Handle any unexpected errors
            context = f"Generating series items feed for series {series_id}"
            log_error(e, context=context)
            
            # Use handle_exception to return a standardized error response
            return handle_exception(e, context=context)
    
    def filter_series(self, data):
        """Find items in a library series that have an ebook file, sorted by a field"""
        n = 1
        filtered_results = []

        for result in data.get("results", []):
            filtered_books = [
                book for book in result.get("books", [])
                if book.get("media", {}).get("ebookFormat") is not None
            ]

            if filtered_books:
                result.update({"books": filtered_books, "opds_seq": n})
                filtered_results.append(result)

        return filtered_results
    
    def add_series_to_feed(self, username, library_id, feed, series, token=None):
        """Add a series to the feed
        
        Args:
            username (str): The username requesting the feed.
            library_id (str): The ID of the library that contains the series.
            feed (Element): The XML element to add the series to.
            series (dict): Series information to add to the feed.
            token (str, optional): Authentication token to include in links.
        """
        first_book = series.get('books', [])[0] if series.get('books') else {}
        first_book_metadata = first_book.get('media', {}).get('metadata', {})
        book_path = f"{AUDIOBOOKSHELF_API}/items/{first_book.get('id','')}"
        cover_url = f"{book_path}/cover?format=jpeg"
        
        # Determine if this was called from search feed by checking if authorName is already set
        # The search feed will directly set authorName, while series feed won't have this property
        from_search_feed = "authorName" in series
        
        # Get author name with proper fallback chain
        author_name = None
        raw_author_name = None
        
        # First try to use explicit authorName that should already be formatted from search feed
        if series.get("authorName") and not series.get("authorName").endswith("None"):
            author_name = series.get("authorName")
            # Extract raw author name (without "Series by " prefix) for atom:author element
            if author_name.startswith("Series by "):
                raw_author_name = author_name[10:]  # Remove "Series by " prefix
            else:
                raw_author_name = author_name
        
        # Then try to get from first book's metadata
        elif first_book_metadata.get("authorName"):
            raw_author_name = first_book_metadata.get("authorName")
            # Format differently based on the source of the call
            if from_search_feed:
                author_name = f"Series by {raw_author_name}"
            else:
                author_name = raw_author_name
        
        # Finally fallback to a generic label
        else:
            if from_search_feed:
                author_name = "Unknown Series"
            else:
                author_name = "Unknown Author"
            raw_author_name = author_name
        
        # Format the content based on the source
        content_text = ""
        if from_search_feed:
            # For search feed, ensure it starts with "Series by"
            if not author_name.startswith("Series by ") and not author_name == "Unknown Series":
                content_text = f"Series by {raw_author_name}"
            else:
                content_text = author_name
        else:
            # For series feed, just use the raw author name
            content_text = raw_author_name
        
        # Use the direct series route instead of query parameters
        series_id = series.get('id')
        
        # Add token to the series link if provided
        series_link = f"/opds/{username}/libraries/{library_id}/series/{series_id}"
        if token:
            series_link = f"{series_link}?token={token}"
        
        # Create entry data structure
        entry_data = {
            "entry": {
                "title": {"_text": series.get("name", "Unknown series name")},
                "id": {"_text": series_id},
                "author": {
                    "name": {"_text": raw_author_name}
                },
                "content": {"_text": content_text},
                "link": [
                    {
                        "_attrs": {
                            "href": series_link,
                            "rel": "subsection",
                            "type": "application/atom+xml"
                        }
                    },
                    {
                        "_attrs": {
                            "href": cover_url,
                            "rel": "http://opds-spec.org/image",
                            "type": "image/jpeg"
                        }
                    }
                ]
            }
        }
        
        # Convert the dictionary to XML elements
        dict_to_xml(feed, entry_data)
    
    async def generate_series_feed(self, username, library_id, token=None):
        """Display all series in the library
        
        Args:
            username (str): The username requesting the feed.
            library_id (str): The ID of the library to generate the feed for.
            token (str, optional): Authentication token for Audiobookshelf.
            
        Returns:
            Response: A FastAPI response object containing the XML feed.
        """
        verify_user(username, token)

        series_params = {"limit": 2000, "sort": "name"}
        data = await fetch_from_api(f"/libraries/{library_id}/series", series_params, username=username, token=token)

        feed = self.create_base_feed(username, library_id)
        
        # Create feed metadata using dictionary approach
        feed_data = {
            "id": {"_text": library_id},
            "title": {"_text": f"{username}'s series"}
        }
        
        # Convert feed metadata to XML
        dict_to_xml(feed, feed_data)

        series_items = self.filter_series(data)

        for series in series_items:
            self.add_series_to_feed(username, library_id, feed, series, token)

        return self.create_response(feed)