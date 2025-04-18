"""Search feed generator"""
# Standard library imports
import logging
from collections import defaultdict


# Local application imports
from opds_abs.core.feed_generator import BaseFeedGenerator
from opds_abs.api.client import fetch_from_api, get_download_urls_from_item
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
    including books, series, and authors that match a search query.

    Attributes:
        Inherits all attributes from BaseFeedGenerator.
    """

    async def generate_search_feed(self, username, library_id, params=None, token=None):
        """Search for books, series, and authors in the library.

        Args:
            username (str): The username of the authenticated user.
            library_id (str): ID of the library to search in.
            params (dict, optional): Query parameters for filtering and search.
            token (str, optional): Authentication token for Audiobookshelf.

        Returns:
            Response: The search results feed.
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
                logger.debug(f"Retrieved cached token for user {username}")

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
        feed = self.create_base_feed()
        self._add_feed_metadata(feed, library_id, query)

        # Process books, series, and authors separately
        await self._process_books(feed, search_data, username, token)
        await self._process_series(feed, search_data, username, library_id, cached_library_items, token)
        await self._process_authors(feed, search_data, username, library_id, cached_library_items, token)

        return self.create_response(feed)


    def _create_empty_search_feed(self, username, library_id, query):
        """Create an empty search feed when no query is provided."""
        feed = self.create_base_feed(username, library_id)
        feed_data = {
            "title": {"_text": f"Search results for: {query}"}
        }
        dict_to_xml(feed, feed_data)
        return self.create_response(feed)

    def _add_feed_metadata(self, feed, library_id, query):
        """Add metadata to the search feed."""
        feed_data = {
            "id": {"_text": f"{library_id}/search/{query}"},
            "title": {"_text": f"Search results for: {query}"}
        }
        dict_to_xml(feed, feed_data)


    async def _process_books(self, feed, search_data, username, token=None):
        """Process book search results and add them to the feed."""
        book_results = search_data.get("book", [])
        for book_result in book_results:
            await self._process_single_book(feed, book_result, username, token)

    async def _process_single_book(self, feed, book_result, username, token=None):
        """Process a single book and add it to the feed if it has an ebook."""
        if "libraryItem" not in book_result:
            return

        lib_item = book_result.get("libraryItem", {})

        if self._has_ebook_file(lib_item):
            ebook_inos = await get_download_urls_from_item(lib_item.get("id"), username=username, token=token)
            self.add_book_to_feed(feed, lib_item, ebook_inos, "", token=token)

    def _has_ebook_file(self, lib_item):
        """Check if a library item has an ebook file."""
        media = lib_item.get("media", {})
        return bool(media.get("ebookFile", media.get("ebookFormat", None)))

    async def _process_series(self, feed, search_data, username, library_id, cached_library_items, token=None):
        """Process series search results and add them to the feed."""
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

    def _extract_series_with_ebooks(self, search_data):
        """Extract series that have books with ebook files."""
        series_with_ebooks = []
        series_ids_with_ebooks = set()

        # Process series results and identify which ones have books with ebook files
        for series_result in search_data.get('series', []):
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
        """Build a map of series IDs to their most common authors."""
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
        """Add a single series to the feed with author information."""
        series_id = series.get('id')
        series_name = series.get('name')

        # Find the author for this series
        series_author = self._find_series_author(
            series_id, 
            series.get('books', []), 
            cached_library_items, 
            series_author_map
        )

        # If all attempts failed, make one final attempt via API
        if series_author == "Unknown Author":
            api_author = await self._try_fetch_series_author(
                series_id,
                series_generator,
                username,
                library_id,
                token=token
            )
            if api_author:
                series_author = api_author

        # Set the author name in the series object
        series["authorName"] = series_author

        # Add the series to the feed
        series_generator.add_series_to_feed(username, library_id, feed, series, token=token)

    def _find_series_author(self, series_id, series_books, cached_library_items, series_author_map):
        """Find the author for a series using various data sources."""
        # First check if we have an author from the series_author_map
        if series_id in series_author_map and series_author_map[series_id]["most_common"]:
            return series_author_map[series_id]["most_common"]

        # Try to get from the series books in search results
        for search_book in series_books:
            search_book_author = search_book.get('media', {}).get('metadata', {}).get('authorName')
            if search_book_author:
                return search_book_author

        # Try to find books in the series from cached items
        for item in cached_library_items:
            metadata = item.get("media", {}).get("metadata", {})
            for series_entry in metadata.get("series", []):
                if series_entry.get("id") == series_id:
                    author_candidate = metadata.get("authorName")
                    if author_candidate:
                        return author_candidate

        # Return default if all attempts failed
        return "Unknown Author"

    async def _try_fetch_series_author(self, series_id, series_gen, username, library_id, token=None):
        """Make a final attempt to find series author by fetching series details from API."""
        try:
            series_details = await series_gen.get_cached_series_details(username, library_id, series_id, token=token)
            if series_details:
                for book in series_details.get("books", []):
                    author_name = book.get("media", {}).get("metadata", {}).get("authorName")
                    if author_name:
                        return author_name
        except Exception as e:
            logger.debug(f"Error fetching series details for author: {str(e)}")

        return None

    async def _process_authors(self, feed, search_data, username, library_id, cached_library_items, token=None):
        """Process author search results and add them to the feed."""
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
        """Extract author data from search results."""
        search_author_names = set()
        author_data_by_name = {}

        for author_result in search_data.get("authors", []):
            if "name" in author_result:
                author_name = author_result.get("name")
                search_author_names.add(author_name)
                author_data_by_name[author_name] = author_result

        return search_author_names, author_data_by_name

    def _count_ebooks_per_author(self, cached_library_items, search_author_names):
        """Count how many ebooks each author has in the library."""
        author_ebook_counts = defaultdict(int)

        for item in cached_library_items:
            author_name = item.get("media", {}).get("metadata", {}).get("authorName")
            if author_name and author_name in search_author_names:
                if self._has_ebook_file(item):
                    author_ebook_counts[author_name] += 1

        return author_ebook_counts

    def _add_author_to_feed(self, author_generator, author_name, ebook_count, author_data_by_name,
                          feed, username, library_id, token=None):
        """Add a single author to the feed with ebook count information."""
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
