"""Library items feed generator"""
# Standard library imports
import asyncio
import logging
import copy

# Third-party imports
from lxml import etree
from fastapi.responses import RedirectResponse

# Local application imports
from opds_abs.core.feed_generator import BaseFeedGenerator
from opds_abs.api.client import fetch_from_api, get_download_urls_from_item
from opds_abs.utils import dict_to_xml
from opds_abs.utils.cache_utils import get_cached_library_items
from opds_abs.utils.auth_utils import verify_user

# Set up logging
logger = logging.getLogger(__name__)

# Cache expiry for library items (in seconds)
LIBRARY_ITEMS_CACHE_EXPIRY = 1800  # 30 minutes

class LibraryFeedGenerator(BaseFeedGenerator):
    """Generator for library items feed"""
    
    async def generate_root_feed(self, username, token=None):
        """Generate the root feed with libraries
        
        Args:
            username (str): The username of the authenticated user.
            token (str, optional): Authentication token for Audiobookshelf.
            
        Returns:
            Response: The root feed listing available libraries.
        """
        # Test log message
        logger.info(f"Generating root feed for user: {username}")
        
        verify_user(username, token)

        data = await fetch_from_api("/libraries", token=token, username=username)
        feed = self.create_base_feed()
        
        # Add feed title using dictionary approach
        feed_data = {
            "title": {"_text": f"{username}'s Libraries"}
        }
        dict_to_xml(feed, feed_data)
        
        libraries = data.get("libraries", [])
        if len(libraries) == 1:
            return RedirectResponse(
                    url=f"/opds/{username}/libraries/{libraries[0].get('id', '')}",
                    status_code=302
            )

        for library in libraries:
            # Create entry data structure
            entry_data = {
                "entry": {
                    "title": {"_text": library["name"]},
                    "link": [
                        {
                            "_attrs": {
                                "href": f"/opds/{username}/libraries/{library['id']}",
                                "rel": "subsection",
                                "type": "application/atom+xml"
                            }
                        },
                        {
                            "_attrs": {
                                "href": "/static/images/libraries.png",
                                "rel": "http://opds-spec.org/image",
                                "type": "image/png"
                            }
                        }
                    ]
                }
            }
            
            # Convert dictionary to XML elements
            dict_to_xml(feed, entry_data)

        return self.create_response(feed)
        
    async def generate_library_items_feed(self, username, library_id, params=None, token=None):
        """Display all items in the library
        
        Args:
            username (str): The username of the authenticated user.
            library_id (str): ID of the library to fetch items from.
            params (dict, optional): Query parameters for filtering and sorting.
            token (str, optional): Authentication token for Audiobookshelf.
            
        Returns:
            Response: The items feed for the specified library.
        """
        verify_user(username, token)

        params = params if params else {}
        
        # Check if we're filtering by collection using direct collection parameter
        collection_id = params.get('collection')
    
        # If we're filtering by collection, fetch the collection data directly
        if collection_id:
            try:
                # Directly fetch the collection with its books
                collection_endpoint = f"/collections/{collection_id}"
                collection_data = await fetch_from_api(collection_endpoint, username=username, token=token)
                                
                # Only proceed if we have collection data with books
                if collection_data and collection_data.get("books"):
                    collection_books = collection_data.get("books", [])
                    
                    # Filter books to only include those with ebookFile or ebookFormat
                    filtered_books = []
                    for book in collection_books:
                        media = book.get("media", {})
                        has_ebook = False
                        
                        # Check for ebookFile
                        if media.get("ebookFile") is not None:
                            has_ebook = True
                            # Make sure ebookFormat is set based on the file extension if it's missing
                            if media.get("ebookFormat") is None:
                                # Extract format from ebookFile extension or set a default
                                ebook_file = media.get("ebookFile", {})
                                if ebook_file and "metadata" in ebook_file:
                                    ext = ebook_file.get("metadata", {}).get("ext", "").lstrip(".")
                                    if ext:
                                        # Set the ebookFormat for use in the feed
                                        media["ebookFormat"] = ext
                                    else:
                                        # Default to epub if extension can't be determined
                                        media["ebookFormat"] = "epub"
                        # Also check for ebookFormat as a backup
                        elif media.get("ebookFormat") is not None and media.get("ebookFormat"):
                            has_ebook = True
                            
                        if has_ebook:
                            filtered_books.append(book)
                                        
                    if filtered_books:
                        # Add sequence numbers for sorting
                        for i, book in enumerate(filtered_books, 1):
                            book["opds_seq"] = i
                        
                        # Sort the books
                        sorted_books = self.sort_results(filtered_books)
                        
                        # Generate feed using these books directly
                        feed = self.create_base_feed(username, library_id)
                        
                        # Create feed metadata using dictionary approach
                        feed_data = {
                            "id": {"_text": library_id},
                            "author": {
                                "name": {"_text": "OPDS Audiobookshelf"}
                            },
                            "title": {"_text": f"{username}'s books in collection: {collection_data.get('name', 'Unknown')}"}
                        }
                        dict_to_xml(feed, feed_data)
                        
                        # Get ebook files for each book
                        tasks = []
                        for book in sorted_books:
                            book_id = book.get("id", "")
                            tasks.append(get_download_urls_from_item(book_id, username=username, token=token))
                        
                        ebook_inos_list = await asyncio.gather(*tasks)
                        for book, ebook_inos in zip(sorted_books, ebook_inos_list):
                            self.add_book_to_feed(feed, book, ebook_inos, params.get('filter',''), token=token)
                        
                        return self.create_response(feed)
                    
            except Exception as e:
                logger.error(f"Error processing collection data: {e}")
                import traceback
                traceback.print_exc()
        
        # If not filtering by collection or collection processing failed, continue with normal flow
        # Determine if we're generating a standard feed or a special feed like "recent"
        sort_param = params.get('sort', '')
        desc_param = params.get('desc', '')
        
        # Check if this is a special feed that can use the cached items
        is_special_feed = (
            sort_param == 'addedAt' or  # From navigation.py for Recent feed
            (sort_param == 'media.metadata.title' and not desc_param)  # Standard items view
        )
        
        # Log the detected parameters to help with debugging
        logger.debug(f"Feed params - sort: {sort_param}, desc: {desc_param}, is_special: {is_special_feed}")
        
        if is_special_feed:
            # For special feeds like "recent", we can reuse the cached library items
            # instead of making a new API call with different sort parameters
            logger.info(f"Using cached library items for {sort_param} feed")
            
            # Get library items from cache utility
            cached_items = await get_cached_library_items(
                fetch_from_api, 
                self.filter_items,
                username, 
                library_id, 
                token=token
            )
            
            # Create a copy to prevent modifying the cached data
            library_items = copy.deepcopy(cached_items)
            
            # Apply the requested sort order in memory
            if sort_param == 'addedAt':
                # Sort by addedAt in descending order (newest first)
                library_items = sorted(
                    library_items,
                    key=lambda x: x.get('addedAt', 0),
                    reverse=True
                )
            elif sort_param == 'media.metadata.title':
                # Sort by title in ascending order
                library_items = sorted(
                    library_items,
                    key=lambda x: x.get('media', {}).get('metadata', {}).get('title', '').lower(),
                    reverse=False
                )
        else:
            # For feeds with other filters or sorts, use the regular API call
            logger.info(f"Fetching library items from API with params: {params}")
            data = await fetch_from_api(f"/libraries/{library_id}/items", params, username=username, token=token)
            library_items = self.filter_items(data)

        feed = self.create_base_feed(username, library_id)
        
        # Create feed metadata using dictionary approach
        feed_data = {
            "id": {"_text": library_id},
            "author": {
                "name": {"_text": "OPDS Audiobookshelf"}
            },
            "title": {"_text": f"{username}'s books"}
        }
        dict_to_xml(feed, feed_data)

        tasks = []
        for book in library_items:
            book_id = book.get("id", "")
            tasks.append(get_download_urls_from_item(book_id, username=username, token=token))

        ebook_inos_list = await asyncio.gather(*tasks)
        for book, ebook_inos in zip(library_items, ebook_inos_list):
            self.add_book_to_feed(feed, book, ebook_inos, params.get('filter',''), token=token)

        return self.create_response(feed)