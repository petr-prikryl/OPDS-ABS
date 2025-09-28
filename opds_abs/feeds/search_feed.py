"""Search feed generator."""
# Standard library imports
import logging
from collections import defaultdict


# Local application imports
from opds_abs.core.feed_generator import BaseFeedGenerator
from opds_abs.api.client import fetch_from_api, get_download_urls_from_item
from opds_abs.config import ITEMS_PER_PAGE, PAGINATION_ENABLED
from opds_abs.feeds.author_feed import AuthorFeedGenerator
from opds_abs.feeds.series_feed import SeriesFeedGenerator
from opds_abs.utils import dict_to_xml
from opds_abs.utils.cache_utils import get_cached_library_items, get_cached_search_results
from opds_abs.utils.auth_utils import get_token_for_username

# Set up logging
logger = logging.getLogger(__name__)

class SearchFeedGenerator(BaseFeedGenerator):
    """Generator for search feed.

    This class creates OPDS feeds for search results from an Audiobookshelf library,
    including books, series, and authors that match a search query. The search functionality
    is a critical component of the OPDS catalog, allowing users to find content across
    different organizational structures.

    Architecture Integration:
    -----------------------
    The SearchFeedGenerator serves as a composite feed generator that integrates results
    from multiple content types. It leverages other feed generators (SeriesFeedGenerator
    and AuthorFeedGenerator) to handle the presentation of specialized content types
    within the unified search results feed.

    Search results are intelligently processed to ensure that only items with available
    ebook files are included, and series/author entries are enhanced with additional
    metadata derived from the library items.

    Performance Optimization:
    -----------------------
    This generator heavily utilizes caching to improve performance:
    - Search results are cached to avoid repeated API calls for the same query
    - Library items are pre-fetched and cached for metadata lookups
    - Author and series information is derived from cached data where possible

    Related Components:
    -----------------
    - SeriesFeedGenerator: Used for rendering series entries in search results
    - AuthorFeedGenerator: Used for rendering author entries in search results
    - cache_utils: Provides caching mechanisms for search results and library items

    Attributes:
        Inherits all attributes from BaseFeedGenerator.
    """

    async def generate_search_feed(self, username, library_id, params=None, token=None):
        """Search for books, series, and authors in the library.

        This method processes search requests and generates an OPDS feed containing
        matching books, series, and authors. It handles token management, empty queries,
        and integrates with the caching system to optimize performance.

        Args:
            username (str): The username of the authenticated user.
            library_id (str): ID of the library to search in.
            params (dict, optional): Query parameters for filtering and search. The key
                parameters are:
                - q: The search query string
                - token: Optional authentication token (alternative to the token parameter)
            token (str, optional): Authentication token for Audiobookshelf.

        Returns:
            Response: The search results feed containing matching books, series, and authors.

        Example:
            ```python
            # In a FastAPI route handler:
            @app.get("/opds/{username}/libraries/{library_id}/search")
            async def opds_search(
                username: str,
                library_id: str,
                request: Request,
                auth_info: tuple = Depends(get_authenticated_user)
            ):
                try:
                    auth_username, token, display_name = auth_info

                    # Get query parameters from the request
                    params = dict(request.query_params)

                    # Use appropriate username based on authentication
                    effective_username = display_name if auth_username else username

                    # Initialize the search feed generator
                    search_feed = SearchFeedGenerator()

                    # Generate and return the search results feed
                    return await search_feed.generate_search_feed(
                        effective_username,
                        library_id,
                        params,
                        token=token
                    )
                except Exception as e:
                    # Handle exceptions appropriately
                    context = f"Searching in library {library_id} for user {username}"
                    log_error(e, context=context)
                    return handle_exception(e, context=context)
            ```
        """
        params = params or {}
        query = params.get("q", "")

        # Check if token is in the query params (for OPDS clients that pass it that way)
        if not token and params.get("token"):
            token = params.get("token")

        # Try to get cached token if none was provided
        if not token and username:
            cached_token = get_token_for_username(username)
            if cached_token:
                token = cached_token
                logger.debug("Retrieved cached token for user %s", username)

        # Return empty search results if no query provided
        if not query:
            return self._create_empty_search_feed(username, library_id, query)

        # Get search data and library items from cache or API
        search_data = await get_cached_search_results(fetch_from_api, username, library_id, query, token=token)
        cached_library_items = await get_cached_library_items(
            fetch_from_api,
            self.filter_items,
            username,
            library_id,
            token=token
        )

        # Create the base feed and add metadata
        feed = self.create_base_feed(username, library_id, token=token)
        self._add_feed_metadata(feed, library_id, query)

        # Process books, series, and authors separately
        await self._process_books(feed, search_data, username, library_id, token)
        await self._process_series(feed, search_data, username, library_id, cached_library_items, token)
        await self._process_authors(feed, search_data, username, library_id, cached_library_items, token)

        return self.create_response(feed)


    def _create_empty_search_feed(self, username, library_id, query):
        """Create an empty search feed when no query is provided.

        Args:
            username (str): The authenticated user's username.
            library_id (str): String identifier for the library.
            query (str): The empty or missing search query string.

        Returns:
            Response: An OPDS feed response with empty search results.
        """
        feed = self.create_base_feed(username, library_id)
        feed_data = {
            "title": {"_text": f"Search results for: {query}"}
        }
        dict_to_xml(feed, feed_data)
        return self.create_response(feed)

    def _add_feed_metadata(self, feed, library_id, query):
        """Add metadata to the search feed.

        Args:
            feed: The XML feed object to add metadata to.
            library_id: String identifier for the library being searched.
            query: The search query string used.

        Returns:
            None. Metadata is added directly to the feed object.
        """
        feed_data = {
            "id": {"_text": f"{library_id}/search/{query}"},
            "title": {"_text": f"Search results for: {query}"}
        }
        dict_to_xml(feed, feed_data)


    async def _process_books(self, feed, search_data, username, library_id, token=None):
        """Process book search results and add them to the feed.

        Args:
            feed: The feed object to add books to.
            search_data: The search results data.
            username: The username of the authenticated user.
            library_id: ID of the library to search in.
            token: Authentication token for Audiobookshelf.
        """
        book_results = search_data.get("book", [])

        # Get the cached library items
        cached_library_items = await get_cached_library_items(
            fetch_from_api,
            self.filter_items,
            username,
            library_id,  # Use the correct library_id parameter here
            token=token
        )

        # Create a mapping of book IDs to their full library item data
        book_id_map = {item.get('id'): item for item in cached_library_items if item.get('id')}

        for book_result in book_results:
            await self._process_single_book(feed, book_result, username, book_id_map, token)

    async def _process_single_book(self, feed, book_result, username, book_id_map, token=None):
        """Process a single book and add it to the feed if it has an ebook.

        Args:
            feed: The XML feed object to add the book entry to.
            book_result: Dictionary containing the book search result data.
            username: String representing the authenticated user's username.
            book_id_map: Dictionary mapping book IDs to their complete metadata.
            token: Optional authentication token for Audiobookshelf.

        Returns:
            None. The book is added directly to the feed if it meets criteria.

        Note:
            Books without ebook files are skipped.
        """
        if "libraryItem" not in book_result:
            return

        lib_item = book_result.get("libraryItem", {})
        book_id = lib_item.get("id")

        if not book_id or not self._has_ebook_file(lib_item):
            return

        # Look up the book in our cache for complete metadata
        cached_item = book_id_map.get(book_id)
        if cached_item:
            # Use the cached item which has complete metadata including author information
            lib_item = cached_item

        ebook_inos = await get_download_urls_from_item(book_id, username=username, token=token)
        self.add_book_to_feed(feed, lib_item, ebook_inos, "", token=token)

    def _has_ebook_file(self, lib_item):
        """Check if a library item has an ebook file.

        Args:
            lib_item: Dictionary containing library item metadata from Audiobookshelf API.

        Returns:
            bool: True if the item has an ebook file or format, False otherwise.
        """
        media = lib_item.get("media", {})
        return bool(media.get("ebookFile", media.get("ebookFormat", None)))

    async def _process_series(self, feed, search_data, username, library_id, cached_library_items, token=None):
        """Process series search results and add them to the feed.

        Args:
            feed: The XML feed object to add series entries to.
            search_data: Dictionary containing search results from Audiobookshelf API.
            username: The username of the authenticated user.
            library_id: ID of the library being searched.
            cached_library_items: List of cached library items for metadata lookup.
            token: Optional authentication token for Audiobookshelf.
        """
        # Extract series with ebooks
        series_with_ebooks, series_ids_with_ebooks = self._extract_series_with_ebooks(search_data)

        if not series_with_ebooks:
            return

        # Build map of series IDs to their most common author
        series_author_map = self._build_series_author_map(cached_library_items, series_ids_with_ebooks)

        # Add each series to the feed with author information
        series_generator = SeriesFeedGenerator()
        for series in series_with_ebooks:
            await self._add_series_to_feed(
                series,
                series_generator,
                series_author_map,
                cached_library_items,
                feed,
                username,
                library_id,
                token=token
            )

    def _extract_series_with_ebooks(self, search_results):
        """Extract series information from search results, grouping ebooks by series.

        Args:
            search_results (dict): The search results data from the API.

        Returns:
            dict: A dictionary mapping series names to lists of ebooks in that series.
        """
        series_with_ebooks = []
        series_ids_with_ebooks = set()

        # Process series results and identify which ones have books with ebook files
        for series_result in search_results.get('series', []):
            series_data = series_result.get('series', {})
            books_with_ebooks = [
                book for book in series_result.get('books', [])
                if self._has_ebook_file(book)
            ]

            # If this series has books with ebooks, add it to our list to process later
            if books_with_ebooks:
                # Create a complete series object with all needed data
                series_obj = {
                    'id': series_data.get('id'),
                    'name': series_data.get('name'),
                    'books': books_with_ebooks,
                }
                series_with_ebooks.append(series_obj)
                series_ids_with_ebooks.add(series_data.get('id'))

        return series_with_ebooks, series_ids_with_ebooks

    def _build_series_author_map(self, cached_library_items, series_ids_with_ebooks):
        """Build a map of series IDs to their most common authors.

        Args:
            cached_library_items (list): List of library item dictionaries containing book metadata.
            series_ids_with_ebooks (set): Set of series IDs that have at least one ebook.

        Returns:
            dict: A dictionary mapping series IDs to information about their authors, including:
                - authors: Dict mapping author names to occurrence count
                - most_common: The name of the most frequently occurring author
        """
        series_author_map = {}

        for item in cached_library_items:
            metadata = item.get("media", {}).get("metadata", {})
            author_name = metadata.get("authorName")
            series_list = metadata.get("series", [])

            if not (author_name and series_list):
                continue

            for series in series_list:
                series_id = series.get("id")
                if series_id and series_id in series_ids_with_ebooks:
                    if series_id not in series_author_map:
                        series_author_map[series_id] = {"authors": {}, "most_common": None}

                    # Count occurrences of this author for this series
                    if author_name not in series_author_map[series_id]["authors"]:
                        series_author_map[series_id]["authors"][author_name] = 0
                    series_author_map[series_id]["authors"][author_name] += 1

                    # Update the most common author
                    most_common = series_author_map[series_id]["most_common"]
                    current_count = series_author_map[series_id]["authors"][author_name]

                    if most_common is None or current_count > series_author_map[series_id]["authors"].get(most_common, 0):
                        series_author_map[series_id]["most_common"] = author_name

        return series_author_map

    async def _add_series_to_feed(self, series, series_generator, series_author_map, cached_library_items,
                                feed, username, library_id, token=None):
        """Add a single series to the feed with author information.

        Args:
            series: Dictionary containing series data.
            series_generator: SeriesFeedGenerator instance to handle adding series entries.
            series_author_map: Mapping of series IDs to author information.
            cached_library_items: List of cached library items for metadata lookup.
            feed: The XML feed object to add the series entry to.
            username: String representing the authenticated user's username.
            library_id: String identifier for the library.
            token: Optional authentication token for Audiobookshelf.

        Returns:
            None. The series is added directly to the feed.
        """
        series_id = series.get('id')

        # Find the author for this series
        series_author = self._find_series_author(
            series_id,
            series.get('books', []),
            cached_library_items,
            series_author_map
        )

        # Set the author name in the series object
        series["authorName"] = series_author

        # Add the series to the feed
        await series_generator.add_series_to_feed(username, library_id, feed, series, token=token)

    def _find_series_author(self, series_id, series_books, cached_library_items, series_author_map):
        """Find the author for a series using various data sources.

        Args:
            series_id: String identifier for the series.
            series_books: List of book objects that belong to this series.
            cached_library_items: List of cached library items for metadata lookup.
            series_author_map: Mapping of series IDs to author information.

        Returns:
            String containing the most likely author name for this series, or "Unknown Author"
            if no author can be found.
        """
        # Early return if no series_id
        if not series_id:
            return "Unknown Author"

        # First check if we have an author from the series_author_map (most efficient)
        if series_id in series_author_map and series_author_map[series_id]["most_common"]:
            return series_author_map[series_id]["most_common"]

        # If we have no series books, we can't continue
        if not series_books:
            return "Unknown Author"

        # Create a set of book IDs for O(1) lookup
        series_book_ids = {book.get("id") for book in series_books if book.get("id")}

        if not series_book_ids:
            return "Unknown Author"

        # Try to find books in the series from cached items using set lookup
        for item in cached_library_items:
            book_id = item.get("id")
            if not book_id or book_id not in series_book_ids:
                continue

            # Look for author in different places
            metadata = item.get("media", {}).get("metadata", {})

            # Try authorName field first
            author_candidate = metadata.get("authorName")
            if author_candidate:
                return author_candidate

            # Try authors array if authorName not available
            authors = metadata.get("authors", [])
            if authors and len(authors) > 0:
                first_author = authors[0].get("name")
                if first_author:
                    return first_author

        # Return default if all attempts failed
        return "Unknown Author"

    async def _process_authors(self, feed, search_data, username, library_id, cached_library_items, token=None):
        """Process author search results and add them to the feed.

        Args:
            feed: The XML feed object to add author entries to.
            search_data (dict): Dictionary containing search results from Audiobookshelf API.
            username (str): The username of the authenticated user.
            library_id (str): ID of the library being searched.
            cached_library_items (list): List of cached library items for metadata lookup.
            token (str, optional): Authentication token for Audiobookshelf.

        Returns:
            None. Author entries are added directly to the feed if they have ebooks.
        """
        # Extract author data from search results
        search_author_names, author_data_by_name = self._extract_author_data_from_search(search_data)

        if not search_author_names:
            return

        # Count ebooks per author using cached items
        author_ebook_counts = self._count_ebooks_per_author(cached_library_items, search_author_names)

        # Add each author that has books to the feed
        author_generator = AuthorFeedGenerator()
        for author_name, ebook_count in author_ebook_counts.items():
            self._add_author_to_feed(
                author_generator,
                author_name,
                ebook_count,
                author_data_by_name,
                feed,
                username,
                library_id,
                token=token
            )

    def _extract_author_data_from_search(self, search_data):
        """Extract author data from search results.

        Args:
            search_data (dict): Dictionary containing search results from Audiobookshelf API.

        Returns:
            tuple: A tuple containing:
                - set: Set of author names found in search results
                - dict: Dictionary mapping author names to their complete data objects
        """
        search_author_names = set()
        author_data_by_name = {}

        for author_result in search_data.get("authors", []):
            if "name" in author_result:
                author_name = author_result.get("name")
                search_author_names.add(author_name)
                author_data_by_name[author_name] = author_result

        return search_author_names, author_data_by_name

    def _count_ebooks_per_author(self, cached_library_items, search_author_names):
        """Count how many ebooks each author has in the library.

        Args:
            cached_library_items: List of library item dictionaries containing book metadata.
            search_author_names: Set of author names to count ebooks for.

        Returns:
            dict: A defaultdict mapping author names to the count of their ebooks.
        """
        author_ebook_counts = defaultdict(int)

        for item in cached_library_items:
            author_name = item.get("media", {}).get("metadata", {}).get("authorName")
            if author_name and author_name in search_author_names:
                if self._has_ebook_file(item):
                    author_ebook_counts[author_name] += 1

        return author_ebook_counts

    def _add_author_to_feed(self, author_generator, author_name, ebook_count, author_data_by_name,
                           feed, username, library_id, token=None):
        """Add a single author to the feed with ebook count information.

        Args:
            author_generator (AuthorFeedGenerator): Generator instance to handle adding author entries.
            author_name (str): Name of the author to add to the feed.
            ebook_count (int): Number of ebooks by this author available in the library.
            author_data_by_name (dict): Dictionary mapping author names to their complete data objects.
            feed: The XML feed object to add the author entry to.
            username (str): The username of the authenticated user.
            library_id (str): ID of the library being searched.
            token (str, optional): Authentication token for Audiobookshelf.

        Returns:
            None. The author is added directly to the feed if they have at least one ebook.
        """
        author_data = author_data_by_name.get(author_name)
        if author_data:
            # Add the ebook count to the author data
            author_data["ebook_count"] = ebook_count
            author_data["id"] = author_data.get("id", "")

            # Only add the author if they have at least one ebook
        if ebook_count > 0:
            author_generator.add_author_to_feed(
                username,
                library_id,
                feed,
                author_data,
                token=token
            )
