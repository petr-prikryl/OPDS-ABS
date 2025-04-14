"""Collections feed generator"""
# Standard library imports
import logging

# Third-party imports
from lxml import etree

# Local application imports
from opds_abs.core.feed_generator import BaseFeedGenerator
from opds_abs.api.client import fetch_from_api
from opds_abs.config import AUDIOBOOKSHELF_API
from opds_abs.utils import dict_to_xml
from opds_abs.utils.error_utils import (
    FeedGenerationError,
    ResourceNotFoundError,
    log_error,
    handle_exception
)

# Set up logging
logger = logging.getLogger(__name__)

class CollectionFeedGenerator(BaseFeedGenerator):
    """Generator for collections feed"""
    
    def add_collection_to_feed(self, username, library_id, feed, collection):
        """Add a collection to the feed
        
        Args:
            username (str): The username requesting the feed.
            library_id (str): The ID of the library.
            feed (Element): The XML feed element to add the collection to.
            collection (dict): The collection data.
            
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
            
            # Create entry data structure
            entry_data = {
                "entry": {
                    "title": {"_text": collection.get("name", "Unknown collection name")},
                    "id": {"_text": collection.get("id", "unknown_id")},
                    "content": {"_text": f"Collection with {book_count} ebook{'s' if book_count != 1 else ''}"},
                    "link": [
                        {
                            "_attrs": {
                                "href": f"/opds/{username}/libraries/{library_id}/items?collection={collection.get('id', '')}",
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
    
    async def generate_collections_feed(self, username, library_id):
        """Display all collections in the library that have books with ebook files
        
        Args:
            username (str): The username requesting the feed.
            library_id (str): The ID of the library.
            
        Returns:
            Response: A FastAPI response object containing the XML feed.
        """
        try:
            self.verify_user(username)
            
            logger.info(f"Fetching collections feed for user {username}, library {library_id}")
            collections_params = {"limit": 1000}
            data = await fetch_from_api(f"/libraries/{library_id}/collections", collections_params, username=username)

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
                        collection_data = await fetch_from_api(f"/collections/{collection_id}", username=username)
                        
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
                self.add_collection_to_feed(username, library_id, feed, collection)
                
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