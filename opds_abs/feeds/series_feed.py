"""Series feed generator."""
# Standard library imports
import logging
import asyncio

# Local application imports
from opds_abs.core.feed_generator import BaseFeedGenerator
from opds_abs.api.client import fetch_from_api, get_download_urls_from_item
from opds_abs.config import AUDIOBOOKSHELF_API
from opds_abs.utils import dict_to_xml
from opds_abs.utils.cache_utils import get_cached_library_items, get_cached_series_details
from opds_abs.utils.error_utils import log_error, handle_exception

# Set up logging
logger = logging.getLogger(__name__)

class SeriesFeedGenerator(BaseFeedGenerator):
    """Generator for series feed.

    This class creates OPDS feeds that list series from an Audiobookshelf library and
    the books contained within specific series. It includes methods for fetching
    series details, filtering items by series, and generating series-based feeds.

    The class handles both listing all series in a library and displaying the books
    within a specific series, with proper sorting by sequence number when applicable.
    It also includes helper methods to determine the most common author for a series.

    Attributes:
        Inherits all attributes from BaseFeedGenerator.
    """

    def get_most_common_author(self, items):
        """Get the most common author from a list of items.

        Args:
            items (list): List of library items.

        Returns:
            str: Name of the most common author, or "Unknown Author" if not found.
        """
        # Collect all authors from all items
        all_authors = []

        for item in items:
            media = item.get("media", {})
            metadata = media.get("metadata", {})

            authors = metadata.get("authors", [])
            if authors:
                # Add each author to our list
                for author in authors:
                    author_name = author.get("name", "")
                    if author_name:
                        all_authors.append(author_name)

        if not all_authors:
            return "Unknown Author"

        # Count occurrences of each author
        author_counts = {}
        for author in all_authors:
            if author in author_counts:
                author_counts[author] += 1
            else:
                author_counts[author] = 1

        # Find the most common author
        most_common_author = max(
                author_counts.items(),
                key=lambda x: x[1],
                default=("Unknown Author", 0)
        )

        return most_common_author[0]

    async def get_series_details(self, username, library_id, series_id, token=None):
        """Fetch detailed information about a specific series.

        Args:
            username (str): The username of the authenticated user.
            library_id (str): ID of the library containing the series.
            series_id (str): ID of the series to get details for.
            token (str, optional): Authentication token for Audiobookshelf.

        Returns:
            dict: Series details or None if not found.
        """
        try:
            # First get all series to find the one we want
            series_params = {"limit": 2000, "sort": "name"}
            data = await fetch_from_api(
                    f"/libraries/{library_id}/series",
                    series_params,
                    username=username,
                    token=token
            )

            # Find the series with the matching ID
            for series in data.get("results", []):
                if series.get("id") == series_id:
                    return series

            return None
        except Exception as e:
            logger.error(f"Error fetching series details: {e}")
            return None

    async def filter_items_by_series_id(self, username, library_id, series_id, token=None):
        """Filter items by series ID using cached items when possible.

        Args:
            username (str): The username of the authenticated user.
            library_id (str): ID of the library containing the items.
            series_id (str): ID of the series to filter by.
            token (str, optional): Authentication token for Audiobookshelf.

        Returns:
            list: Library items filtered by the specified series ID.
            dict: Series details including name and most common author.
        """
        try:
            # Get series details to find the name and book IDs using the shared utility function
            series_details = await get_cached_series_details(
                fetch_from_api,
                username,
                library_id,
                series_id,
                token=token
            )

            if not series_details:
                logger.warning("Could not find series details for ID %s", series_id)
                # Fall back to API call if we couldn't find the series details
                params = {"filter": f"series.{self.create_filter(series_id)}"}
                data = await fetch_from_api(
                        f"/libraries/{library_id}/items",
                        params,
                        username=username,
                        token=token
                )
                filtered_items = self.filter_items(data)
                # Get the most common author from the filtered items
                most_common_author = self.get_most_common_author(filtered_items)
                # Create minimal series details with author information
                series_details = {
                        "id": series_id,
                        "name": "Unknown Series",
                        "authorName": most_common_author
                }
                return filtered_items, series_details

            series_name = series_details.get("name", "Unknown Series")
            logger.info("Found series details for: %s", series_name)

            # Extract book IDs from the series details
            series_book_ids = []
            for book in series_details.get("books", []):
                book_id = book.get("id")
                if book_id:
                    series_book_ids.append(book_id)

            if not series_book_ids:
                logger.warning("No book IDs found in series %s", series_name)
                # Fall back to API call if we couldn't find any book IDs
                params = {"filter": f"series.{self.create_filter(series_id)}"}
                data = await fetch_from_api(
                        "/libraries/{library_id}/items",
                        params,
                        username=username,
                        token=token
                )
                filtered_items = self.filter_items(data)
                # Get the most common author from the filtered items
                most_common_author = self.get_most_common_author(filtered_items)
                # Update series details with author information
                series_details["authorName"] = most_common_author
                return filtered_items, series_details

            logger.info("Found %d book IDs in series %s", len(series_book_ids), series_name)

            # Try to get all library items from cache
            library_items = await get_cached_library_items(
                fetch_from_api,
                self.filter_items,
                username,
                library_id,
                token=token
            )

            # Filter the cached items by exact book ID match
            filtered_items = []
            for item in library_items:
                if item.get("id") in series_book_ids:
                    filtered_items.append(item)

            logger.info("Found %d matching items in cache for series %s", len(filtered_items), series_name)

            # If no matching items were found in the cache, try the fallback method
            if not filtered_items:
                logger.warning(f"No matching items found in cache for series %s. Trying API fallback.", series_name)
                params = {"filter": f"series.{self.create_filter(series_id)}"}
                data = await fetch_from_api(
                        f"/libraries/{library_id}/items",
                        params,
                        username=username,
                        token=token
                )
                filtered_items = self.filter_items(data)

            # Sort by series sequence number if available
            sorted_items = sorted(
                filtered_items,
                key=lambda x: x.get('media', {}).get('metadata', {}).get('series', {}).get('sequence', 0)
            )

            # Get the most common author from the series items
            most_common_author = self.get_most_common_author(sorted_items)

            # Update series details with author information
            series_details["authorName"] = most_common_author

            logger.info(
                    "Final result: %d items in series %s by %s",
                    len(sorted_items),
                    series_name,
                    most_common_author
            )
            return sorted_items, series_details

        except Exception as e:
            logger.error(f"Error filtering items by series: %s", e)
            # Fall back to API call if there was an error
            params = {
                    "filter": f"series.{self.create_filter(series_id)}",
                    "sort": "media.metadata.series.number"
            }
            data = await fetch_from_api(
                    f"/libraries/{library_id}/items",
                    params,
                    username=username,
                    token=token
            )
            filtered_items = self.filter_items(data)
            # Get the most common author from the filtered items
            most_common_author = self.get_most_common_author(filtered_items)
            # Create minimal series details with author information
            series_details = {
                    "id": series_id,
                    "name": "Unknown Series",
                    "authorName": most_common_author
            }
            return filtered_items, series_details

    async def generate_series_items_feed(self, username, library_id, series_id, token=None):
        """Generate a feed of items in a specific series.

        Args:
            username (str): The username requesting the feed.
            library_id (str): The ID of the library to generate the feed for.
            series_id (str): The ID of the series to filter by.
            token (str, optional): Authentication token for Audiobookshelf.

        Returns:
            Response: A FastAPI response object containing the XML feed.
        """
        from opds_abs.utils.cache_utils import get_cached_series_items

        try:
            # Get series details for name and author (still useful for feed metadata)
            series_details = await get_cached_series_details(
                fetch_from_api,
                username,
                library_id,
                series_id,
                token=token
            )

            # Get items for this series directly from items endpoint with series filter
            # This ensures we get the proper sequence information
            library_items = await get_cached_series_items(
                fetch_from_api,
                self.filter_items,
                username,
                library_id,
                series_id,
                token=token
            )

            # Get details for series and author
            series_name = "Unknown Series"
            author_name = "Unknown Author"
            if series_details:
                series_name = series_details.get("name", "Unknown Series")

            # Get the most common author if we have library items
            if library_items:
                author_name = self.get_most_common_author(library_items)
            elif series_details:
                # Fall back to series_details if we have it
                author_name = series_details.get("authorName", "Unknown Author")

            # Create the feed
            feed = self.create_base_feed(username, library_id)

            # Build the feed metadata
            feed_data = {
                "id": {"_text": library_id},
                "author": {
                    "name": {"_text": "OPDS Audiobookshelf"}
                },
                "title": {"_text": f"{series_name} Series by {author_name}"}
            }

            # Convert feed metadata to XML
            dict_to_xml(feed, feed_data)

            if not library_items:
                error_data = {
                    "entry": {
                        "title": {"_text": "No books found"},
                        "content": {"_text": f"No ebooks were found in {series_name}."}
                    }
                }
                dict_to_xml(feed, error_data)
                return self.create_response(feed)

            # Items should already be sorted by sequence when fetched from the API
            # But let's ensure they are sorted correctly just to be safe
            sorted_library_items = sorted(
                library_items,
                key=lambda x: float(x.get('media', {}).get('metadata', {}).get('series', {}).get('sequence', 0))
            )

            logger.info(f"Sorted {len(sorted_library_items)} items by sequence number for {series_name}")

            # Get ebook files for each book
            tasks = []
            for book in sorted_library_items:
                book_id = book.get("id", "")
                tasks.append(get_download_urls_from_item(book_id, username=username, token=token))

            ebook_inos_list = await asyncio.gather(*tasks)
            for book, ebook_inos in zip(sorted_library_items, ebook_inos_list):
                self.add_book_to_feed(feed, book, ebook_inos, "", token)

            return self.create_response(feed)

        except Exception as e:
            # Handle any unexpected errors
            context = f"Generating series items feed for series {series_id}"
            log_error(e, context=context)

            # Use handle_exception to return a standardized error response
            return handle_exception(e, context=context)

    def filter_series(self, data):
        """Find items in a library series that have an ebook file, sorted by a field.

        Args:
            data (dict): Series data from the Audiobookshelf API containing results list.

        Returns:
            list: Filtered series results that contain at least one book with an ebook file.
        """
        n = 1
        filtered_results = []

        for result in data.get("results", []):
            filtered_books = [
                book for book in result.get("books", [])
                if book.get("media", {}).get("ebookFormat") is not None
            ]

            if filtered_books:
                result.update({"books": filtered_books, "opds_seq": n})
                filtered_results.append(result)

        return filtered_results

    async def add_series_to_feed(self, username, library_id, feed, series, token=None):
        """Add a series to the feed.

        Args:
            username (str): The username requesting the feed.
            library_id (str): The ID of the library that contains the series.
            feed (Element): The XML element to add the series to.
            series (dict): Series information to add to the feed.
            token (str, optional): Authentication token to include in links.
        """
        first_book = series.get('books', [])[0] if series.get('books') else {}
        first_book_id = first_book.get("id", None)
        first_book_metadata = first_book.get('media', {}).get('metadata', {})
        book_path = f"{AUDIOBOOKSHELF_API}/items/{first_book_id}" if first_book_id else ""
        cover_url = f"{book_path}/cover?format=jpeg" if book_path else ""

        # Determine if this was called from search feed by checking if authorName is already set
        # The search feed will directly set authorName, while series feed won't have this property
        from_search_feed = series.get("authorName", None)

        # Get author name with proper fallback chain
        raw_author_name = None

        # Check for the first book in library items if we have an ID
        if first_book_id:
            try:
                # Use cached library items if possible
                library_items = await get_cached_library_items(
                    fetch_from_api,
                    self.filter_items,
                    username,
                    library_id,
                    token=token
                )

                # Find the book in library items
                for item in library_items:
                    if item.get("id") == first_book_id:
                        # Use media.metadata.authorName from the library item
                        raw_author_name = item.get('media', {}).get('metadata', {}).get('authorName')
                        break
            except Exception as e:
                logger.error(f"Error checking library items for book ID {first_book_id}: {e}")

        # Fall back to the first_book_metadata if we couldn't find the book in library items
        if not raw_author_name and first_book_metadata.get("authorName"):
            raw_author_name = first_book_metadata.get("authorName")

        # Final fallback
        if not raw_author_name:
            raw_author_name = "Unknown Author"

        content_text = raw_author_name
        # Format the content based on the source
        if from_search_feed:
                content_text = f"Series by {raw_author_name}"
                logger.info("Adding series to feed from search: %s", content_text)

        # Use the direct series route instead of query parameters
        series_id = series.get('id')

        # Add token to the series link if provided
        series_link = f"/opds/{username}/libraries/{library_id}/series/{series_id}"
        if token:
            series_link = f"{series_link}?token={token}"

        # Create entry data structure
        entry_data = {
            "entry": {
                "title": {"_text": series.get("name", "Unknown series name")},
                "id": {"_text": series_id},
                "updated": {"_text": self.get_current_timestamp()},
                "author": {
                    "name": {"_text": raw_author_name}
                },
                "content": {"_text": content_text},
                "link": [
                    {
                        "_attrs": {
                            "href": series_link,
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

    async def generate_series_feed(self, username, library_id, token=None):
        """Display all series in the library.

        Args:
            username (str): The username requesting the feed.
            library_id (str): The ID of the library to generate the feed for.
            token (str, optional): Authentication token for Audiobookshelf.

        Returns:
            Response: A FastAPI response object containing the XML feed.
        """
        series_params = {"limit": 2000, "sort": "name"}
        data = await fetch_from_api(f"/libraries/{library_id}/series", series_params, username=username, token=token)

        feed = self.create_base_feed(username, library_id)

        # Create feed metadata using dictionary approach
        feed_data = {
            "id": {"_text": library_id},
            "title": {"_text": f"{username}'s series"}
        }

        # Convert feed metadata to XML
        dict_to_xml(feed, feed_data)

        series_items = self.filter_series(data)

        for series in series_items:
            await self.add_series_to_feed(username, library_id, feed, series, token)

        return self.create_response(feed)
