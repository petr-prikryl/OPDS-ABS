"""Library items feed generator."""
# Standard library imports
import asyncio
import logging
import copy

# Third-party imports
from fastapi.responses import RedirectResponse

# Local application imports
from opds_abs.core.feed_generator import BaseFeedGenerator
from opds_abs.api.client import fetch_from_api, get_download_urls_from_item
from opds_abs.utils import dict_to_xml
from opds_abs.utils.cache_utils import get_cached_library_items
from opds_abs.config import ITEMS_PER_PAGE, PAGINATION_ENABLED

# Set up logging
logger = logging.getLogger(__name__)

class LibraryFeedGenerator(BaseFeedGenerator):
    """Generator for library items feed.

    This class creates OPDS feeds for Audiobookshelf libraries and their contents.
    It handles generating the root feed that lists all available libraries for a user,
    as well as library-specific feeds that display books within a library.

    The class supports various filtering and sorting options, including collection-based
    filtering and special feeds like "recent" items. It also optimizes performance by
    using cached library items when appropriate.

    The LibraryFeedGenerator is part of the feed hierarchy that inherits from
    BaseFeedGenerator. It works with other feed generators like SeriesFeedGenerator
    and AuthorFeedGenerator to provide a complete OPDS catalog experience.

    Related Classes:
        - BaseFeedGenerator: Parent class providing core feed generation functionality
        - NavigationFeedGenerator: Creates navigational entry points to library views
        - CollectionFeedGenerator: Handles collection-specific views

    Attributes:
        Inherits all attributes from BaseFeedGenerator.
    """

    async def generate_root_feed(self, username, token=None):
        """Generate the root feed with libraries.

        This method creates the top-level OPDS feed that lists all available libraries
        for a user. If the user has only one library, it automatically redirects to
        that library's feed for a smoother user experience.

        Args:
            username (str): The username of the authenticated user.
            token (str, optional): Authentication token for Audiobookshelf.

        Returns:
            Response: The root feed listing available libraries.

        Example:
            ```python
            # In a FastAPI route handler:
            @app.get("/opds/{username}")
            async def opds_root(username: str):
                # Create library feed generator
                feed_gen = LibraryFeedGenerator()

                # Generate the root feed for this user
                return await feed_gen.generate_root_feed(
                    username=username,
                    token="user_auth_token"
                )
            ```
        """
        # Test log message
        logger.debug("Generating root feed for user: %s", username)

        data = await fetch_from_api("/libraries", token=token, username=username)
        feed = self.create_base_feed(username=username, token=token)

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
                                "type": "application/atom+xml;profile=opds-catalog"
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
        """Display all items in the library with optional filtering and sorting.

        This method generates an OPDS feed containing all ebook items in a specific library.
        It supports various filtering options including collection-based filtering and
        different sort orders. The method optimizes performance by using cached data
        for common view types like alphabetically sorted lists or recently added items.

        Args:
            username (str): The username of the authenticated user who is accessing the feed.
            library_id (str): ID of the library to fetch items from.
            params (dict, optional): Query parameters for filtering and sorting. Supported keys:
                - collection: ID of a collection to filter items by
                - sort: Field to sort by (e.g., 'addedAt', 'media.metadata.title')
                - desc: If present, sort in descending order
                - filter: Additional filter criteria
                - start_index: Start index for pagination (1-based, defaults to 1)
            token (str, optional): Authentication token for Audiobookshelf API access.

        Returns:
            Response: A FastAPI response object containing the XML OPDS feed with all
                     matching ebook items from the library.
        """
        params = params if params else {}

        # Extract pagination parameters
        try:
            start_index = int(params.get('start_index', 1))
            if start_index < 1:
                start_index = 1
        except (ValueError, TypeError):
            start_index = 1

        # Check if pagination is enabled
        if not PAGINATION_ENABLED:
            # Pagination is disabled, show all items
            items_per_page = 0
            no_pagination = True
        else:
            # Use items per page from config
            items_per_page = ITEMS_PER_PAGE
            # If items_per_page is 0, we'll show all items without pagination
            no_pagination = (items_per_page <= 0)

        # Current page calculation (1-based)
        page = 1 if no_pagination else ((start_index - 1) // items_per_page) + 1

        # Build current path for pagination links
        path_params = []
        for key, value in params.items():
            if key != 'start_index' and key != 'token':
                path_params.append(f"{key}={value}")

        # Properly construct the path with &
        path_suffix = f"?{'&'.join(path_params)}" if path_params else ""
        current_path = f"{username}/libraries/{library_id}/items{path_suffix}"

        # Add start_index parameter with proper separator
        if not no_pagination:
            if path_params:
                current_path_with_page = f"{current_path}&start_index={start_index}"
            else:
                current_path_with_page = f"{current_path}?start_index={start_index}"
        else:
            current_path_with_page = current_path

        # Make a copy of the params without the start_index for API requests
        api_params = {k: v for k, v in params.items() if k != 'start_index'}

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

                        # Get total books count before pagination
                        total_books = len(sorted_books)

                        # Apply pagination
                        sorted_books = self.paginate_results(sorted_books, start_index, items_per_page)

                        # Generate feed using these books directly
                        feed = self.create_base_feed(username, library_id, current_path_with_page, token)

                        # Create feed metadata using dictionary approach
                        feed_data = {
                            "id": {"_text": library_id},
                            "author": {
                                "name": {"_text": "OPDS Audiobookshelf"}
                            },
                            "title": {"_text": f"{username}'s books in collection: {collection_data.get('name', 'Unknown')}"}
                        }
                        dict_to_xml(feed, feed_data)

                        # Add pagination metadata and links
                        if not no_pagination:
                            self.add_pagination_metadata(feed, page, items_per_page, total_books)
                            self.add_pagination_links(feed, current_path.rstrip('&?'),
                                                    page, items_per_page, total_books, token=token)

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
                logger.error("Error processing collection data: %s", e)
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
        logger.debug("Feed params - sort: %s, desc: %s, is_special: %s", sort_param, desc_param, is_special_feed)

        if is_special_feed:
            # For special feeds like "recent", we can reuse the cached library items
            # instead of making a new API call with different sort parameters
            logger.debug("Using cached library items for %s feed", sort_param)

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
            logger.debug("Fetching library items from API with params: %s", params)
            data = await fetch_from_api(
                    f"/libraries/{library_id}/items",
                    api_params,
                    username=username,
                    token=token
            )
            library_items = self.filter_items(data)

        # Get total count before pagination
        total_items = len(library_items)

        # Apply pagination
        paginated_items = library_items if no_pagination else self.paginate_results(library_items, start_index, items_per_page)

        # Create feed with pagination-aware path
        feed = self.create_base_feed(username, library_id, current_path_with_page, token)

        # Create feed metadata using dictionary approach
        feed_data = {
            "id": {"_text": library_id},
            "author": {
                "name": {"_text": "OPDS Audiobookshelf"}
            },
            "title": {"_text": f"{username}'s books"}
        }
        dict_to_xml(feed, feed_data)

        # Add pagination metadata and links
        if not no_pagination:
            self.add_pagination_metadata(feed, page, items_per_page, total_items)
            self.add_pagination_links(feed, current_path.rstrip('&?'),
                                    page, items_per_page, total_items, token=token)

        tasks = []
        for book in paginated_items:
            book_id = book.get("id", "")
            tasks.append(get_download_urls_from_item(book_id, username=username, token=token))

        ebook_inos_list = await asyncio.gather(*tasks)
        for book, ebook_inos in zip(paginated_items, ebook_inos_list):
            self.add_book_to_feed(feed, book, ebook_inos, params.get('filter',''), token=token)

        return self.create_response(feed)
