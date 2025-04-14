"""Authors feed generator"""
# Standard library imports
import logging
import asyncio

# Third-party imports
from lxml import etree

# Local application imports
from opds_abs.core.feed_generator import BaseFeedGenerator
from opds_abs.api.client import fetch_from_api, get_download_urls_from_item
from opds_abs.config import AUDIOBOOKSHELF_API, USER_KEYS
from opds_abs.utils import dict_to_xml
from opds_abs.utils.cache_utils import _create_cache_key, cache_get, cache_set
from opds_abs.utils.error_utils import (
    FeedGenerationError,
    ResourceNotFoundError,
    log_error,
    handle_exception
)

# Set up logging
logger = logging.getLogger(__name__)

# Cache expiry for library items (in seconds)
LIBRARY_ITEMS_CACHE_EXPIRY = 1800  # 30 minutes

class AuthorFeedGenerator(BaseFeedGenerator):
    """Generator for authors feed.
    
    This class creates OPDS feeds that list authors who have books with ebook files
    in an Audiobookshelf library.
    
    Attributes:
        Inherits all attributes from BaseFeedGenerator.
    """
    
    async def get_cached_library_items(self, username, library_id, bypass_cache=False):
        """Fetch and cache all library items that can be reused for filtering.
        
        This method fetches all library items and caches them so they can be 
        reused when filtering by author instead of making additional API calls.
        
        Args:
            username (str): The username of the authenticated user.
            library_id (str): ID of the library to fetch items from.
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
        data = await fetch_from_api(f"/libraries/{library_id}/items", items_params, username)
        library_items = self.filter_items(data)
        
        # Store in cache for future use
        cache_set(cache_key, library_items)
        
        return library_items
        
    async def filter_items_by_author_id(self, username, library_id, author_id):
        """Filter items by author ID using cached items when possible.
        
        Args:
            username (str): The username of the authenticated user.
            library_id (str): ID of the library containing the items.
            author_id (str): ID of the author to filter by.
            
        Returns:
            list: Library items filtered by the specified author ID.
        """
        try:
            # Try to get all library items from cache first
            library_items = await self.get_cached_library_items(username, library_id)
            
            # Get author details to find the name
            author_details = await self.get_author_details(username, library_id)
            author_name = None
            
            # Find author name by ID
            for _, author in author_details.items():
                if author.get("id") == author_id:
                    author_name = author.get("name")
                    break
            
            if not author_name:
                logger.warning(f"Could not find author name for ID {author_id}")
                # Fall back to API call if we couldn't find the author name
                params = {"filter": f"authors.{self.create_filter(author_id)}"}
                data = await fetch_from_api(f"/libraries/{library_id}/items", params, username)
                return self.filter_items(data)
            
            logger.info(f"Filtering cached items by author: {author_name}")
            
            # Filter the cached items by author name in-memory
            filtered_items = []
            for item in library_items:
                media = item.get("media", {})
                metadata = media.get("metadata", {})
                
                # Check if this item's author matches
                if metadata.get("authorName") == author_name:
                    filtered_items.append(item)
            
            logger.info(f"Found {len(filtered_items)} items by author {author_name}")
            return filtered_items
            
        except Exception as e:
            logger.error(f"Error filtering items by author: {e}")
            # Fall back to API call if there was an error
            params = {"filter": f"authors.{self.create_filter(author_id)}"}
            data = await fetch_from_api(f"/libraries/{library_id}/items", params, username)
            return self.filter_items(data)
    
    async def generate_author_items_feed(self, username, library_id, author_id):
        """Generate a feed of items by a specific author.
        
        Args:
            username (str): The username requesting the feed.
            library_id (str): The ID of the library to generate the feed for.
            author_id (str): The ID of the author to filter by.
            
        Returns:
            Response: A FastAPI response object containing the XML feed.
        """
        try:
            # Verify the user exists
            self.verify_user(username)
            
            # Get items filtered by author (using cache when possible)
            library_items = await self.filter_items_by_author_id(username, library_id, author_id)
            
            # Get author name
            author_name = "Unknown Author"
            author_details = await self.get_author_details(username, library_id)
            for _, author in author_details.items():
                if author.get("id") == author_id:
                    author_name = author.get("name")
                    break
            
            # Create the feed
            feed = self.create_base_feed(username, library_id)
            
            # Build the feed metadata
            feed_data = {
                "id": {"_text": library_id},
                "author": {
                    "name": {"_text": "OPDS Audiobookshelf"}
                },
                "title": {"_text": f"Books by {author_name}"}
            }
            
            # Convert feed metadata to XML
            dict_to_xml(feed, feed_data)
            
            if not library_items:
                error_data = {
                    "entry": {
                        "title": {"_text": "No books found"},
                        "content": {"_text": f"No books by {author_name} with ebooks were found in this library."}
                    }
                }
                dict_to_xml(feed, error_data)
                return self.create_response(feed)
            
            # Get ebook files for each book
            tasks = []
            for book in library_items:
                book_id = book.get("id", "")
                tasks.append(get_download_urls_from_item(book_id))
            
            ebook_inos_list = await asyncio.gather(*tasks)
            for book, ebook_inos in zip(library_items, ebook_inos_list):
                self.add_book_to_feed(feed, book, ebook_inos, "")
            
            return self.create_response(feed)
            
        except Exception as e:
            # Handle any unexpected errors
            context = f"Generating author items feed for author {author_id}"
            log_error(e, context=context)
            
            # Use handle_exception to return a standardized error response
            return handle_exception(e, context=context)
    
    def add_author_to_feed(self, username, library_id, feed, author):
        """Add an author entry to the OPDS feed.
        
        Args:
            username (str): The username requesting the feed.
            library_id (str): The ID of the library the author belongs to.
            feed (Element): The lxml Element object representing the feed.
            author (dict): Author information including name, id, and ebook_count.
        
        Raises:
            FeedGenerationError: If there's an error adding the author to the feed.
        """
        try:
            # Get a cover url if we have a book with an ebook
            cover_url = "/static/images/unknown-author.png"
            if author.get("imagePath"):
                cover_url = f"{AUDIOBOOKSHELF_API}/authors/{author.get('id')}/image?format=jpeg"
            
            # Get author ID and name
            author_id = author.get("id", "")
            author_name = author.get("name", "")
            
            # Get ebook count
            book_count = author.get("ebook_count", 0)
            
            # Create the entry data structure
            entry_data = {
                "entry": {
                    "title": {"_text": author_name or "Unknown author name"},
                    "id": {"_text": author_id or "unknown_id"},
                    "content": {"_text": f"Author with {book_count} ebook{'s' if book_count != 1 else ''}"},
                    "link": [
                        {
                            "_attrs": {
                                "href": f"/opds/{username}/libraries/{library_id}/authors/{author_id}",
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
            
        except (ValueError, KeyError) as e:
            context = f"Adding author {author.get('name', 'unknown')} to feed"
            log_error(e, context=context)
            raise FeedGenerationError(f"Failed to add author to feed: {str(e)}") from e
        except Exception as e:
            context = f"Adding author {author.get('name', 'unknown')} to feed"
            log_error(e, context=context)
            raise FeedGenerationError(f"Unexpected error adding author to feed: {str(e)}") from e
    
    async def get_authors_with_ebooks(self, username, library_id):
        """Get list of authors who have books with ebook files.
        
        Args:
            username (str): The username requesting the data.
            library_id (str): The ID of the library to search in.
            
        Returns:
            list: A list of dictionaries containing author information with ebook counts.
            
        Raises:
            ResourceNotFoundError: If no items data could be found.
            FeedGenerationError: If there's an error processing the data.
        """
        try:
            # Get all library items with detailed info
            items_params = {"limit": 10000, "expand": "media"}
            items_data = await fetch_from_api(f"/libraries/{library_id}/items", items_params, username=username)
            
            if not items_data or "results" not in items_data:
                logger.error("Failed to retrieve library items")
                raise ResourceNotFoundError("Library items data not found")
                
            # Dictionary to keep track of authors with ebooks
            authors_with_ebooks = {}
            
            # Iterate through all items to find those with ebooks
            for item in items_data.get("results", []):
                media = item.get("media", {})
                metadata = media.get("metadata", {})
                has_ebook = False
                
                # Check if this item has an ebook
                if (media.get("ebookFile") is not None or 
                    (media.get("ebookFormat") is not None and media.get("ebookFormat"))):
                    has_ebook = True
                
                if has_ebook:
                    # Get author name from metadata
                    author_name = metadata.get("authorName")
                    if author_name:
                        # Add this author to our tracking dictionary
                        if author_name in authors_with_ebooks:
                            authors_with_ebooks[author_name]["ebook_count"] += 1
                        else:
                            authors_with_ebooks[author_name] = {
                                "name": author_name,
                                "ebook_count": 1
                            }
            
            logger.info(f"Found {len(authors_with_ebooks)} authors with ebooks")
            return list(authors_with_ebooks.values())
            
        except ResourceNotFoundError:
            # Re-raise ResourceNotFoundError
            raise
        except Exception as e:
            context = f"Finding authors with ebooks in library {library_id}"
            log_error(e, context=context)
            raise FeedGenerationError(f"Error processing authors with ebooks: {str(e)}") from e
    
    async def get_author_details(self, username, library_id):
        """Fetch detailed author information from the authors endpoint.
        
        Args:
            username (str): The username requesting the data.
            library_id (str): The ID of the library to get authors from.
            
        Returns:
            dict: A dictionary mapping author names to their detailed information.
            
        Raises:
            ResourceNotFoundError: If author data could not be retrieved.
            FeedGenerationError: If there's an error processing the author data.
        """
        try:
            # Get all authors in the library
            authors_params = {"limit": 2000, "sort": "name"}
            author_data = await fetch_from_api(f"/libraries/{library_id}/authors", authors_params, username=username)
            
            if not author_data or "authors" not in author_data:
                logger.error("Failed to retrieve authors data")
                raise ResourceNotFoundError("Authors data not found")
                
            # Create a dictionary of authors by name for quick lookup
            authors_dict = {}
            for author in author_data.get("authors", []):
                author_name = author.get("name")
                if author_name:
                    authors_dict[author_name] = author
            
            return authors_dict
            
        except ResourceNotFoundError:
            # Re-raise ResourceNotFoundError
            raise
        except Exception as e:
            context = f"Fetching author details for library {library_id}"
            log_error(e, context=context)
            raise FeedGenerationError(f"Error processing author details: {str(e)}") from e
    
    async def generate_authors_feed(self, username, library_id):
        """Generate an OPDS feed listing authors with ebooks.
        
        Creates an OPDS feed containing all authors in the specified library
        that have books with ebook files. Each entry includes the author's name,
        image (if available), and link to their books.
        
        Args:
            username (str): The username requesting the feed.
            library_id (str): The ID of the library to generate the feed for.
            
        Returns:
            Response: A FastAPI response object containing the XML feed.
        """
        try:
            # Verify the user exists
            self.verify_user(username)
            
            # Log the request
            logger.info(f"Fetching authors feed for user {username}, library {library_id}")
            
            # Create the feed
            feed = self.create_base_feed(username, library_id)
            
            # Build the feed metadata
            feed_data = {
                "id": {"_text": library_id},
                "title": {"_text": f"{username}'s authors with ebooks"}
            }
            
            # Convert feed metadata to XML
            dict_to_xml(feed, feed_data)
            
            try:
                # First, get the list of authors who have ebooks
                authors_with_ebooks = await self.get_authors_with_ebooks(username, library_id)
                
                if not authors_with_ebooks:
                    logger.warning("No authors with ebooks found")
                    error_data = {
                        "entry": {
                            "title": {"_text": "No authors with ebooks found"},
                            "content": {"_text": "Could not find any authors with ebooks in the library"}
                        }
                    }
                    dict_to_xml(feed, error_data)
                    return self.create_response(feed)
                
                # Get author details including images and other metadata
                author_details = await self.get_author_details(username, library_id)
                
                # Merge the ebook count with the author details
                authors_list = []
                for author_with_ebooks in authors_with_ebooks:
                    author_name = author_with_ebooks["name"]
                    if author_name in author_details:
                        # Add the ebook count to the author details
                        full_author = author_details[author_name].copy()
                        full_author["ebook_count"] = author_with_ebooks["ebook_count"]
                        authors_list.append(full_author)
                    else:
                        # If we don't have details, use the basic information
                        authors_list.append(author_with_ebooks)
                
                # Sort authors by name
                authors_list = sorted(authors_list, key=lambda x: x.get("name", "").lower())
                
                # Log the results
                logger.info(f"Found {len(authors_list)} authors with ebooks")
                
                # Add each author to the feed
                for author in authors_list:
                    self.add_author_to_feed(username, library_id, feed, author)
                
            except ResourceNotFoundError as e:
                # Handle not found errors
                context = f"Processing authors data for library {library_id}"
                log_error(e, context=context, log_traceback=False)
                
                error_data = {
                    "entry": {
                        "title": {"_text": "Resource not found"},
                        "content": {"_text": str(e)}
                    }
                }
                dict_to_xml(feed, error_data)
            except FeedGenerationError as e:
                # Handle feed generation errors
                context = f"Processing authors data for library {library_id}"
                log_error(e, context=context)
                
                error_data = {
                    "entry": {
                        "title": {"_text": "Error processing authors"},
                        "content": {"_text": str(e)}
                    }
                }
                dict_to_xml(feed, error_data)
            
            return self.create_response(feed)
            
        except Exception as e:
            # Handle any other unexpected errors
            context = f"Generating authors feed for user {username}, library {library_id}"
            log_error(e, context=context)
            
            # Use handle_exception to return a standardized error response
            return handle_exception(e, context=context)