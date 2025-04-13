"""Collections feed generator"""
import logging
from lxml import etree

from opds_abs.core.feed_generator import BaseFeedGenerator
from opds_abs.api.client import fetch_from_api
from opds_abs.config import AUDIOBOOKSHELF_API
from opds_abs.utils import dict_to_xml

logger = logging.getLogger(__name__)

class CollectionFeedGenerator(BaseFeedGenerator):
    """Generator for collections feed"""
    
    def add_collection_to_feed(self, username, library_id, feed, collection):
        """Add a collection to the feed"""
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
            
        except Exception as e:
            logger.error(f"Error adding collection to feed: {str(e)}")
    
    async def generate_collections_feed(self, username, library_id):
        """Display all collections in the library that have books with ebook files"""
        try:
            self.verify_user(username)
            
            logger.info(f"Fetching collections feed for user {username}, library {library_id}")
            collections_params = {"limit": 1000}
            data = await fetch_from_api(f"/libraries/{library_id}/collections", collections_params, username=username)

            # Filter collections to only include those with books that have ebook files
            filtered_collections = []
            
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
                    except Exception as e:
                        logger.error(f"Error fetching collection {collection_id}: {e}")
            
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

            return self.create_response(feed)
        
        except Exception as e:
            logger.error(f"Error generating collections feed: {str(e)}")
            
            # Return a basic feed with an error message
            feed = self.create_base_feed(username, library_id)
            
            # Create error message using dictionary approach
            error_data = {
                "title": {"_text": "Error generating collections feed"},
                "entry": {
                    "content": {"_text": f"An error occurred: {str(e)}"}
                }
            }
            dict_to_xml(feed, error_data)
            
            return self.create_response(feed)