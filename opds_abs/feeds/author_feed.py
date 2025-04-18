"""Authors feed generator"""
# Standard library imports
import logging
import asyncio
from typing import Dict, Any, List, Optional

# Local application imports
from opds_abs.core.feed_generator import BaseFeedGenerator
from opds_abs.api.client import fetch_from_api, get_download_urls_from_item
from opds_abs.config import AUDIOBOOKSHELF_API
from opds_abs.utils import dict_to_xml
from opds_abs.utils.cache_utils import get_cached_library_items, get_cached_author_details
from opds_abs.utils.error_utils import (
    FeedGenerationError,
    ResourceNotFoundError,
    log_error,
    handle_exception
)

# Set up logging
logger = logging.getLogger(__name__)

class AuthorFeedGenerator(BaseFeedGenerator):
    """Generator for authors feed.

    This class creates OPDS feeds that list authors who have books with ebook files
    in an Audiobookshelf library.

    Attributes:
        Inherits all attributes from BaseFeedGenerator.
    """

    async def get_author_by_id(self, username: str, library_id: str, author_id: str, token: Optional[str] = None) -> Dict[str, Any]:
        """Get author information by ID from the cached list of authors with ebooks.
        
        Args:
            username (str): The username of the authenticated user.
            library_id (str): ID of the library containing the authors.
            author_id (str): ID of the author to find.
            token (str, optional): Authentication token for Audiobookshelf.
            
        Returns:
            dict: Author information or empty dict if not found.
        """
        # Get all authors with ebooks
        authors_with_ebooks = await self.get_authors_with_ebooks(username, library_id, token=token)
        
        # Find the author with matching ID
        for author in authors_with_ebooks:
            if author.get("id") == author_id:
                return author
                
        # Author not found
        logger.warning("Could not find author with ID %s in library %s", author_id, library_id)
        return {}

    async def filter_items_by_author_id(self, username: str, library_id: str, author_id: str, token: Optional[str] = None) -> List[Dict[str, Any]]:
        """Filter items by author ID using cached items when possible.

        Args:
            username (str): The username of the authenticated user.
            library_id (str): ID of the library containing the items.
            author_id (str): ID of the author to filter by.
            token (str, optional): Authentication token for Audiobookshelf.

        Returns:
            list: Library items filtered by the specified author ID.
        """
        try:
            # Get all library items from cache
            library_items = await get_cached_library_items(
                fetch_from_api,
                self.filter_items,
                username,
                library_id,
                token=token
            )

            # Get author info by ID
            author = await self.get_author_by_id(username, library_id, author_id, token=token)
            author_name = author.get("name")

            if not author_name:
                # Fall back to API call if we couldn't find the author name
                logger.warning("Could not find author name for ID %s, falling back to API filter", author_id)
                params = {"filter": f"authors.{self.create_filter(author_id)}"}
                data = await fetch_from_api(
                        f"/libraries/{library_id}/items",
                        params,
                        username=username,
                        token=token
                )
                return self.filter_items(data)

            logger.info("Filtering cached items by author: %s", author_name)

            # Filter the cached items by author name in-memory
            filtered_items = []
            for item in library_items:
                media = item.get("media", {})
                metadata = media.get("metadata", {})

                # Check if this item's author matches
                if metadata.get("authorName") == author_name:
                    # Only include items with ebooks
                    has_ebook = (
                        media.get("ebookFile") is not None or 
                        (media.get("ebookFormat") is not None and media.get("ebookFormat"))
                    )
                    if has_ebook:
                        filtered_items.append(item)

            logger.info("Found %d ebook items by author %s",
                        len(filtered_items),
                        author_name
            )
            return filtered_items

        except Exception as e:
            logger.error("Error filtering items by author: %s", e)
            # Fall back to API call if there was an error
            params = {"filter": f"authors.{self.create_filter(author_id)}"}
            data = await fetch_from_api(
                    f"/libraries/{library_id}/items",
                    params,
                    username=username,
                    token=token
            )
            return self.filter_items(data)

    async def generate_author_items_feed(self, username: str, library_id: str, author_id: str, token: Optional[str] = None):
        """Generate a feed of items by a specific author.

        Args:
            username (str): The username requesting the feed.
            library_id (str): The ID of the library to generate the feed for.
            author_id (str): The ID of the author to filter by.
            token (str, optional): Authentication token for Audiobookshelf.

        Returns:
            Response: A FastAPI response object containing the XML feed.
        """
        try:
            # Get author details first (including name)
            author = await self.get_author_by_id(username, library_id, author_id, token=token)
            author_name = author.get("name", "Unknown Author")
            
            # Get items filtered by author (using cache when possible)
            library_items = await self.filter_items_by_author_id(
                    username,
                    library_id,
                    author_id,
                    token=token
            )

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

            # Get ebook files for each book - pass both username and token
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
            context = f"Generating author items feed for author {author_id}"
            log_error(e, context=context)

            # Use handle_exception to return a standardized error response
            return handle_exception(e, context=context)

    def add_author_to_feed(self, username: str, library_id: str, feed, author: Dict[str, Any], token: Optional[str] = None):
        """Add an author entry to the OPDS feed.

        Args:
            username (str): The username requesting the feed.
            library_id (str): The ID of the library the author belongs to.
            feed (Element): The lxml Element object representing the feed.
            author (dict): Author information including name, id, and ebook_count.
            token (str, optional): Authentication token for Audiobookshelf.

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

            # Create the base URL for the author's books
            author_url = f"/opds/{username}/libraries/{library_id}/authors/{author_id}"

            # Add token to URL if provided
            if token:
                author_url += f"?token={token}"

            # Create the entry data structure
            entry_data = {
                "entry": {
                    "title": {"_text": author_name or "Unknown author name"},
                    "id": {"_text": author_id or "unknown_id"},
                    "content": {"_text": f"Author with {book_count} ebook{'s' if book_count != 1 else ''}"},
                    "link": [
                        {
                            "_attrs": {
                                "href": author_url,
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

    async def get_authors_with_ebooks(self, username: str, library_id: str, token: Optional[str] = None, bypass_cache: bool = False) -> List[Dict[str, Any]]:
        """Get list of authors who have books with ebook files.

        Args:
            username (str): The username requesting the data.
            library_id (str): The ID of the library to search in.
            token (str, optional): Authentication token for Audiobookshelf.
            bypass_cache (bool): Whether to bypass cache and force fresh data lookup.

        Returns:
            list: A list of dictionaries containing author information with ebook counts.

        Raises:
            ResourceNotFoundError: If no items data could be found.
            FeedGenerationError: If there's an error processing the data.
        """
        try:
            # Use the dedicated caching function for authors with ebooks
            authors_list = await get_cached_author_details(
                fetch_from_api,
                self.filter_items,
                username,
                library_id,
                token=token,
                bypass_cache=bypass_cache
            )
            
            if not authors_list:
                logger.warning("No authors with ebooks found for library %s", library_id)
                raise ResourceNotFoundError("No authors with ebooks found")
                
            logger.info("Found %d authors with ebooks in library %s", 
                       len(authors_list), library_id)
            return authors_list
            
        except ResourceNotFoundError:
            # Re-raise ResourceNotFoundError
            raise
        except Exception as e:
            context = f"Finding authors with ebooks in library {library_id}"
            log_error(e, context=context)
            raise FeedGenerationError(f"Error processing authors with ebooks: {str(e)}") from e

    async def generate_authors_feed(self, username: str, library_id: str, token: Optional[str] = None):
        """Generate an OPDS feed listing authors with ebooks.

        Creates an OPDS feed containing all authors in the specified library
        that have books with ebook files. Each entry includes the author's name,
        image (if available), and link to their books.

        Args:
            username (str): The username requesting the feed.
            library_id (str): The ID of the library to generate the feed for.
            token (str, optional): Authentication token for Audiobookshelf.

        Returns:
            Response: A FastAPI response object containing the XML feed.
        """
        try:
            # Log the request
            logger.info("Fetching authors feed for user %s library %s", username, library_id)

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
                # Get the list of authors who have ebooks (already includes all needed details)
                authors_list = await self.get_authors_with_ebooks(
                    username, library_id, token=token
                )

                if not authors_list:
                    logger.warning("No authors with ebooks found")
                    error_data = {
                        "entry": {
                            "title": {"_text": "No authors with ebooks found"},
                            "content": {"_text": "Could not find any authors with ebooks in the library"}
                        }
                    }
                    dict_to_xml(feed, error_data)
                    return self.create_response(feed)

                # Sort authors by name
                authors_list = sorted(authors_list, key=lambda x: x.get("name", "").lower())
                logger.info("Found %d authors with ebooks", len(authors_list))

                # Add each author to the feed
                for author in authors_list:
                    self.add_author_to_feed(username, library_id, feed, author, token)

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
