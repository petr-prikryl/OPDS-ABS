"""Collections feed generator"""
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
from opds_abs.utils.cache_utils import _create_cache_key, cache_get, cache_set, get_cached_library_items
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

class CollectionFeedGenerator(BaseFeedGenerator):
    """Generator for collections feed"""
    
    async def get_collection_details(self, username, collection_id, token=None):
        """Fetch detailed information about a specific collection.
        
        Args:
            username (str): The username of the authenticated user.
            collection_id (str): ID of the collection to get details for.
            token (str, optional): Authentication token for Audiobookshelf.
            
        Returns:
            dict: Collection details or None if not found.
        """
        try:
            # Get the collection data
            collection_data = await fetch_from_api(f"/collections/{collection_id}", username=username, token=token)
            return collection_data
        except Exception as e:
            logger.error(f"Error fetching collection details: {e}")
            return None
    
    async def filter_items_by_collection_id(self, username, library_id, collection_id, token=None):
        """Filter items by collection ID using cached items when possible.
        
        Args:
            username (str): The username of the authenticated user.
            library_id (str): ID of the library containing the items.
            collection_id (str): ID of the collection to filter by.
            token (str, optional): Authentication token for Audiobookshelf.
            
        Returns:
            list: Library items filtered by the specified collection ID.
        """
        try:
            # Get collection details to get the books in this collection
            collection_details = await self.get_collection_details(username, collection_id, token=token)
            
            # If we can't get collection details, fall back to API call
            if not collection_details:
                logger.warning(f"Could not find collection details for ID {collection_id}")
                params = {"collection": collection_id}
                data = await fetch_from_api(f"/libraries/{library_id}/items", params, username=username, token=token)
                return self.filter_items(data)
            
            collection_name = collection_details.get("name", "Unknown Collection")
            logger.info(f"Filtering items by collection: {collection_name}")
            
            # Get the book IDs in this collection
            collection_book_ids = [book.get("id") for book in collection_details.get("books", []) if book.get("id")]
            
            if not collection_book_ids:
                logger.warning(f"No book IDs found in collection {collection_id}")
                return []
            
            # Try to get all library items from cache using the shared utility function
            library_items = await get_cached_library_items(
                fetch_from_api,
                self.filter_items,
                username,
                library_id,
                token=token
            )
            
            # Filter the cached items by matching book IDs
            filtered_items = []
            for item in library_items:
                if item.get("id") in collection_book_ids:
                    filtered_items.append(item)
            
            logger.info(f"Found {len(filtered_items)} items in collection {collection_name} from cache")
            return filtered_items
            
        except Exception as e:
            logger.error(f"Error filtering items by collection: {e}")
            # Fall back to API call if there was an error
            params = {"collection": collection_id}
            data = await fetch_from_api(f"/libraries/{library_id}/items", params, username=username, token=token)
            return self.filter_items(data)
    
    async def generate_collection_items_feed(self, username, library_id, collection_id, token=None):
        """Generate a feed of items in a specific collection.
        
        Args:
            username (str): The username requesting the feed.
            library_id (str): The ID of the library to generate the feed for.
            collection_id (str): The ID of the collection to filter by.
            token (str, optional): Authentication token for Audiobookshelf.
            
        Returns:
            Response: A FastAPI response object containing the XML feed.
        """
        try:
            verify_user(username, token)
            
            # Get items filtered by collection (using cache when possible)
            library_items = await self.filter_items_by_collection_id(username, library_id, collection_id, token=token)
            
            # Get collection name
            collection_name = "Unknown Collection"
            collection_details = await self.get_collection_details(username, collection_id, token=token)
            if collection_details:
                collection_name = collection_details.get("name", "Unknown Collection")
            
            # Create the feed
            feed = self.create_base_feed(username, library_id)
            
            # Build the feed metadata
            feed_data = {
                "id": {"_text": library_id},
                "author": {
                    "name": {"_text": "OPDS Audiobookshelf"}
                },
                "title": {"_text": f"{collection_name} Collection"}
            }
            
            # Convert feed metadata to XML
            dict_to_xml(feed, feed_data)
            
            if not library_items:
                error_data = {
                    "entry": {
                        "title": {"_text": "No books found"},
                        "content": {"_text": f"No books in the {collection_name} collection with ebooks were found in this library."}
                    }
                }
                dict_to_xml(feed, error_data)
                return self.create_response(feed)
            
            # Get ebook files for each book
            tasks = []
            for book in library_items:
                book_id = book.get("id", "")
                tasks.append(get_download_urls_from_item(book_id, token=token))
            
            ebook_inos_list = await asyncio.gather(*tasks)
            for book, ebook_inos in zip(library_items, ebook_inos_list):
                self.add_book_to_feed(feed, book, ebook_inos, "", token)
            
            return self.create_response(feed)
            
        except Exception as e:
            # Handle any unexpected errors
            context = f"Generating collection items feed for collection {collection_id}"
            log_error(e, context=context)
            
            # Use handle_exception to return a standardized error response
            return handle_exception(e, context=context)
    
    def add_collection_to_feed(self, username, library_id, feed, collection, token=None):
        """Add a collection to the feed
        
        Args:
            username (str): The username requesting the feed.
            library_id (str): The ID of the library.
            feed (Element): The XML feed element to add the collection to.
            collection (dict): The collection data.
            token (str, optional): Authentication token to include in links.
            
        Raises:
            FeedGenerationError: If there's an error adding the collection to the feed.
        """
        try:
            # Get the first book with an ebook to use for the cover
            cover_url = "/static/images/collections.png"
            
            # Count books with ebooks and find a cover image
            books_with_ebooks = []
            for book in collection.get("books", []):
                media = book.get("media", {})
                if (media.get("ebookFile") is not None or 
                    (media.get("ebookFormat") is not None and media.get("ebookFormat"))):
                    books_with_ebooks.append(book)
                    # Use the first book with an ebook for the cover if we haven't found one yet
                    if cover_url == "/static/images/collections.png" and book.get("id"):
                        book_path = f"{AUDIOBOOKSHELF_API}/items/{book.get('id','')}"
                        cover_url = f"{book_path}/cover?format=jpeg"
            
            # Get the book count for the entry content
            book_count = len(books_with_ebooks)
            collection_id = collection.get("id", "")
            
            # Add token to the collection link if provided
            collection_link = f"/opds/{username}/libraries/{library_id}/collections/{collection_id}"
            if token:
                collection_link = f"{collection_link}?token={token}"
            
            # Create entry data structure
            entry_data = {
                "entry": {
                    "title": {"_text": collection.get("name", "Unknown collection name")},
                    "id": {"_text": collection_id},
                    "content": {"_text": f"Collection with {book_count} ebook{'s' if book_count != 1 else ''}"},
                    "link": [
                        {
                            "_attrs": {
                                "href": collection_link,
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
            
            # Convert dictionary to XML elements
            dict_to_xml(feed, entry_data)
            
        except (ValueError, KeyError) as e:
            context = f"Adding collection {collection.get('name', 'unknown')} to feed"
            log_error(e, context=context)
            raise FeedGenerationError(f"Failed to add collection to feed: {str(e)}") from e
        except Exception as e:
            context = f"Adding collection {collection.get('name', 'unknown')} to feed"
            log_error(e, context=context)
            raise FeedGenerationError(f"Unexpected error adding collection to feed: {str(e)}") from e
    
    async def generate_collections_feed(self, username, library_id, token=None):
        """Display all collections in the library that have books with ebook files
        
        Args:
            username (str): The username requesting the feed.
            library_id (str): The ID of the library.
            token (str, optional): Authentication token for Audiobookshelf.
            
        Returns:
            Response: A FastAPI response object containing the XML feed.
        """
        try:
            verify_user(username, token)
            
            logger.info(f"Fetching collections feed for user {username}, library {library_id}")
            collections_params = {"limit": 1000}
            data = await fetch_from_api(f"/libraries/{library_id}/collections", collections_params, username=username, token=token)

            if not data or "results" not in data:
                raise ResourceNotFoundError(f"No collections found for library {library_id}")

            # Filter collections to only include those with books that have ebook files
            filtered_collections = []
            collection_errors = []
            
            for collection in data.get("results", []):
                # We need to fetch each collection's books separately
                collection_id = collection.get("id", "")
                if collection_id:
                    try:
                        collection_data = await fetch_from_api(f"/collections/{collection_id}", username=username, token=token)
                        
                        # Check if there are ebooks in this collection and count them
                        ebook_count = 0
                        for book in collection_data.get("books", []):
                            media = book.get("media", {})
                            if (media.get("ebookFile") is not None or 
                                (media.get("ebookFormat") is not None and media.get("ebookFormat"))):
                                ebook_count += 1
                        
                        if ebook_count > 0:
                            logger.info(f"Collection '{collection_data.get('name')}' has {ebook_count} ebooks")
                            filtered_collections.append(collection_data)
                    except ResourceNotFoundError as e:
                        context = f"Fetching collection {collection_id}"
                        log_error(e, context=context, log_traceback=False)
                        collection_errors.append(f"Collection {collection.get('name', collection_id)}: {str(e)}")
                    except Exception as e:
                        context = f"Fetching collection {collection_id}"
                        log_error(e, context=context)
                        collection_errors.append(f"Collection {collection.get('name', collection_id)}: {str(e)}")
            
            # Sort collections by name
            filtered_collections = sorted(filtered_collections, key=lambda x: x.get("name", "").lower())

            # Create the feed
            feed = self.create_base_feed(username, library_id)
            
            # Add feed metadata using dictionary approach
            feed_data = {
                "id": {"_text": library_id},
                "title": {"_text": f"{username}'s collections"}
            }
            dict_to_xml(feed, feed_data)

            # Add each collection to the feed
            for collection in filtered_collections:
                self.add_collection_to_feed(username, library_id, feed, collection, token)
                
            # If we have no collections but had errors, add an entry about the errors
            if not filtered_collections and collection_errors:
                error_message = "Some collections could not be retrieved:\n" + "\n".join(collection_errors)
                error_data = {
                    "entry": {
                        "title": {"_text": "Error retrieving some collections"},
                        "content": {"_text": error_message}
                    }
                }
                dict_to_xml(feed, error_data)

            return self.create_response(feed)
        
        except ResourceNotFoundError as e:
            context = f"Generating collections feed for library {library_id}"
            log_error(e, context=context, log_traceback=False)
            
            # Return a feed with the specific error
            feed = self.create_base_feed(username, library_id)
            error_data = {
                "title": {"_text": "Collections not found"},
                "entry": {
                    "content": {"_text": str(e)}
                }
            }
            dict_to_xml(feed, error_data)
            return self.create_response(feed)
        except Exception as e:
            # Handle any other unexpected errors
            context = f"Generating collections feed for user {username}, library {library_id}"
            log_error(e, context=context)
            
            # Use handle_exception to return a standardized error response
            return handle_exception(e, context=context)