"""Authors feed generator"""
import logging
from lxml import etree

from opds_abs.core.feed_generator import BaseFeedGenerator
from opds_abs.api.client import fetch_from_api
from opds_abs.config import AUDIOBOOKSHELF_API, USER_KEYS
from opds_abs.utils import dict_to_xml

# Set up logging
logger = logging.getLogger(__name__)

class AuthorFeedGenerator(BaseFeedGenerator):
    """Generator for authors feed"""
    
    def add_author_to_feed(self, username, library_id, feed, author):
        """Add an author to the feed"""
        try:
            # Get a cover url if we have a book with an ebook
            cover_url = "/static/images/unknown-author.png"
            if author.get("imagePath"):
                cover_url = f"{AUDIOBOOKSHELF_API}/authors/{author.get('id')}/image?format=jpeg"
            
            # Create link to filter by author name
            author_name = author.get("name", "")
            # Use authorName filter which is in media.metadata.authorName
            author_filter = f"filter=authors.{self.create_filter(author.get('id'))}"
            
            # Get ebook count
            book_count = author.get("ebook_count", 0)
            
            # Create the entry data structure
            entry_data = {
                "entry": {
                    "title": {"_text": author.get("name", "Unknown author name")},
                    "id": {"_text": author.get("id", "unknown_id")},
                    "content": {"_text": f"Author with {book_count} ebook{'s' if book_count != 1 else ''}"},
                    "link": [
                        {
                            "_attrs": {
                                "href": f"/opds/{username}/libraries/{library_id}/items?{author_filter}",
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
            
        except Exception as e:
            logger.error(f"Error adding author to feed: {str(e)}")
    
    async def get_authors_with_ebooks(self, username, library_id):
        """Get list of authors who have books with ebook files"""
        try:
            # Get all library items with detailed info
            items_params = {"limit": 10000, "expand": "media"}
            items_data = await fetch_from_api(f"/libraries/{library_id}/items", items_params, username=username)
            
            if not items_data or "results" not in items_data:
                logger.error("Failed to retrieve library items")
                return []
                
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
            
        except Exception as e:
            logger.error(f"Error finding authors with ebooks: {str(e)}")
            import traceback
            traceback.print_exc()
            return []
    
    async def get_author_details(self, username, library_id):
        """Fetch detailed author information from the authors endpoint"""
        try:
            # Get all authors in the library
            authors_params = {"limit": 2000, "sort": "name"}
            author_data = await fetch_from_api(f"/libraries/{library_id}/authors", authors_params, username=username)
            
            if not author_data or "authors" not in author_data:
                logger.error("Failed to retrieve authors data")
                return {}
                
            # Create a dictionary of authors by name for quick lookup
            authors_dict = {}
            for author in author_data.get("authors", []):
                author_name = author.get("name")
                if author_name:
                    authors_dict[author_name] = author
            
            return authors_dict
            
        except Exception as e:
            logger.error(f"Error fetching author details: {str(e)}")
            import traceback
            traceback.print_exc()
            return {}
    
    async def generate_authors_feed(self, username, library_id):
        """Display all authors in the library that have books with ebook files"""
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
                
            except Exception as e:
                logger.error(f"Error processing authors data: {str(e)}")
                import traceback
                traceback.print_exc()
                
                # Create a basic entry with error info
                error_data = {
                    "entry": {
                        "title": {"_text": "Error processing authors"},
                        "content": {"_text": f"An error occurred while processing author data: {str(e)}"}
                    }
                }
                dict_to_xml(feed, error_data)
            
            return self.create_response(feed)
            
        except Exception as e:
            logger.error(f"Error generating authors feed: {str(e)}")
            import traceback
            traceback.print_exc()
            
            # Return a basic feed with an error message
            feed = self.create_base_feed(username, library_id)
            error_data = {
                "title": {"_text": "Error generating authors feed"},
                "entry": {
                    "content": {"_text": f"An error occurred: {str(e)}"}
                }
            }
            dict_to_xml(feed, error_data)
            
            return self.create_response(feed)