"""Search feed generator"""
# Standard library imports
import logging

# Third-party imports
from lxml import etree
from fastapi.responses import Response

# Local application imports
from opds_abs.core.feed_generator import BaseFeedGenerator, AUTH_MATRIX
from opds_abs.api.client import fetch_from_api, get_download_urls_from_item
from opds_abs.feeds.author_feed import AuthorFeedGenerator
from opds_abs.feeds.series_feed import SeriesFeedGenerator
from opds_abs.utils import dict_to_xml
from opds_abs.utils.cache_utils import _create_cache_key, cache_get, cache_set
from opds_abs.utils.auth_utils import verify_user

# Set up logging
logger = logging.getLogger(__name__)

# Cache expiry for library items (in seconds)
LIBRARY_ITEMS_CACHE_EXPIRY = 1800  # 30 minutes
SEARCH_RESULTS_CACHE_EXPIRY = 600  # 10 minutes

class SearchFeedGenerator(BaseFeedGenerator):
    """Generator for search feed"""
    
    async def get_cached_library_items(self, username, library_id, token=None, bypass_cache=False):
        """Fetch and cache all library items that can be reused for filtering.
        
        This method fetches all library items and caches them so they can be 
        reused when processing search results instead of making additional API calls.
        
        Args:
            username (str): The username of the authenticated user.
            library_id (str): ID of the library to fetch items from.
            token (str, optional): Authentication token for Audiobookshelf.
            bypass_cache (bool): Whether to bypass the cache and force a fresh fetch.
            
        Returns:
            list: All filtered library items containing ebooks.
        """
        cache_key = _create_cache_key(f"/library-items-all/{library_id}", None, username)
        
        # Try to get from cache if not bypassing
        if not bypass_cache:
            cached_data = cache_get(cache_key, LIBRARY_ITEMS_CACHE_EXPIRY)
            if cached_data is not None:
                logger.debug(f"✓ Cache hit for all library items {library_id}")
                return cached_data  # Return cached data
        
        # Not in cache or bypassing cache, fetch the data
        logger.debug(f"Fetching all library items for library {library_id}")
        items_params = {"limit": 10000, "expand": "media"}
        data = await fetch_from_api(f"/libraries/{library_id}/items", items_params, username=username, token=token)
        library_items = self.filter_items(data)
        
        # Store in cache for future use
        cache_set(cache_key, library_items)
        
        return library_items
    
    async def get_cached_search_results(self, username, library_id, query, token=None, bypass_cache=False):
        """Fetch and cache search results to avoid repeated API calls for the same search query.
        
        Args:
            username (str): The username of the authenticated user.
            library_id (str): ID of the library to search in.
            query (str): The search query string.
            token (str, optional): Authentication token for Audiobookshelf.
            bypass_cache (bool): Whether to bypass the cache and force a fresh search.
            
        Returns:
            dict: The search results from Audiobookshelf API.
        """
        cache_key = _create_cache_key(f"/libraries/{library_id}/search", {"q": query}, username)
        
        # Try to get from cache if not bypassing
        if not bypass_cache:
            cached_data = cache_get(cache_key, SEARCH_RESULTS_CACHE_EXPIRY)
            if cached_data is not None:
                logger.debug(f"✓ Cache hit for search query: {query}")
                return cached_data  # Return cached data
        
        # Not in cache or bypassing cache, perform the search
        logger.debug(f"Performing search for query: {query}")
        search_params = {"limit": 2000, "q": query}
        search_data = await fetch_from_api(f"/libraries/{library_id}/search", search_params, username=username, token=token)
        
        # Store in cache for future use
        cache_set(cache_key, search_data)
        
        return search_data
    
    async def generate_search_feed(self, username, library_id, params=None, token=None):
        """Search for books, series, and authors in the library
        
        Args:
            username (str): The username of the authenticated user.
            library_id (str): ID of the library to search in.
            params (dict, optional): Query parameters for filtering and search.
            token (str, optional): Authentication token for Audiobookshelf.
            
        Returns:
            Response: The search results feed.
        """
        # Extract search query from parameters
        params = params or {}
        query = params.get("q", "")
        
        # Check if token is in the query params (for OPDS clients that pass it that way)
        if not token and params.get("token"):
            token = params.get("token")
        
        # Get token from AUTH_MATRIX if it exists and wasn't provided in this request
        if not token and username in AUTH_MATRIX:
            token = AUTH_MATRIX.get(username)
            logger.debug(f"Retrieved token from AUTH_MATRIX for user {username}")
        
        # Verify user after extracting all possible token sources
        verify_user(username, token)

        if not query:
            # If no query provided, return empty search results
            feed = self.create_base_feed(username, library_id)
            feed_data = {
                "title": {"_text": f"Search results for: {query}"}
            }
            dict_to_xml(feed, feed_data)
            feed_xml = etree.tostring(feed, pretty_print=True, xml_declaration=False, encoding="UTF-8")
            return Response(content=feed_xml, media_type="application/atom+xml")

        # Call the search API endpoint with caching
        search_data = await self.get_cached_search_results(username, library_id, query, token=token)
        
        # Fetch cached library items once to be used for all operations
        cached_library_items = await self.get_cached_library_items(username, library_id, token=token)
        
        # Create the base feed
        feed = self.create_base_feed()
        
        # Add feed metadata using dictionary approach
        feed_data = {
            "id": {"_text": f"{library_id}/search/{query}"},
            "title": {"_text": f"Search results for: {query}"}
        }
        dict_to_xml(feed, feed_data)
        
        # Process books with ebook files
        for book_result in search_data.get("book", []):
            if "libraryItem" not in book_result:
                continue
                
            # Extract the library item which contains the actual book data
            lib_item = book_result.get("libraryItem", {})
            
            # Check if the book has an ebook file
            media = lib_item.get("media", {})
            if media.get("ebookFile", media.get("ebookFormat", None)):
                # Get ebooks for the book
                ebook_inos = await get_download_urls_from_item(lib_item.get("id"), username=username, token=token)
                self.add_book_to_feed(feed, lib_item, ebook_inos, "", token=token)
        
        # Initialize lists for series with ebooks
        series_with_ebooks = []
        series_ids_with_ebooks = set()
        
        # Process series results and identify which ones have books with ebook files
        for series_result in search_data.get('series', []):
            series_data = series_result.get('series', {})
            books_with_ebooks = []
            
            for book in series_result.get('books', []):
                media = book.get('media', {})
                if media.get('ebookFile', media.get('ebookFormat', None)):
                    books_with_ebooks.append(book)
            
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
        
        # Only process series if we have series with ebooks
        if series_with_ebooks:
            # Create a map of series IDs to their most common author using cached items
            series_author_map = {}
            
            # Process each cached library item to find series and authors
            for item in cached_library_items:
                metadata = item.get("media", {}).get("metadata", {})
                
                # Get author and series information
                author_name = metadata.get("authorName")
                series_list = metadata.get("series", [])
                
                # Skip processing if there's no series or author information
                if not (author_name and series_list):
                    continue
                
                # Only process series that are in our search results
                for series in series_list:
                    logger.debug(f"Processing series {series} for author {author_name}")
                    series_id = series.get("id")
                    if series_id and series_id in series_ids_with_ebooks:
                        logger.debug(f"Found series {series} with {series_id}")
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
            
            # Now add each series to the feed with author information
            for series in series_with_ebooks:
                series_id = series.get('id')
                series_name = series.get('name')
                
                # Find the author for this series from cached data
                series_author = None
                if series_id in series_author_map and series_author_map[series_id]["most_common"]:
                    series_author = series_author_map[series_id]["most_common"]
                
                # If we couldn't find an author from series_author_map, try the series books
                if not series_author:
                    # Try to get from the first book in the series from search results
                    series_books = series.get('books', [])
                    # Try each book in the series until we find an author
                    for search_book in series_books:
                        search_book_author = search_book.get('media', {}).get('metadata', {}).get('authorName')
                        if search_book_author:
                            series_author = search_book_author
                            break
                
                # If we still don't have an author, try to find books in the series from cached items
                if not series_author:
                    # Find books in this series from cached library items
                    series_books = []
                    for item in cached_library_items:
                        metadata = item.get("media", {}).get("metadata", {})
                        for series_entry in metadata.get("series", []):
                            if series_entry.get("id") == series_id:
                                series_books.append(item)
                                author_candidate = metadata.get("authorName")
                                if author_candidate:
                                    series_author = author_candidate
                                    break
                        if series_author:
                            break
                
                # Set the author name in the series object
                if series_author:
                    series["authorName"] = series_author
                else:
                    # If all attempts failed, make one final attempt: 
                    # fetch series details from API endpoint (already cached in SeriesFeedGenerator)
                    series_gen = SeriesFeedGenerator()
                    try:
                        # Use series ID to access cached series details
                        series_details = await series_gen.get_cached_series_details(username, library_id, series_id, token=token)
                        if series_details:
                            # Look for books and author info
                            for book in series_details.get("books", []):
                                author_name = book.get("media", {}).get("metadata", {}).get("authorName")
                                if author_name:
                                    series["authorName"] = author_name
                                    break
                    except Exception as e:
                        logger.debug(f"Error fetching series details for author: {str(e)}")
                    
                    # Only use "Unknown Author" if absolutely necessary after all attempts
                    if "authorName" not in series:
                        series["authorName"] = "Unknown Author"
                        logger.debug(f"Unable to find author for series: {series_name} (id: {series_id})")
                # Add the series to the feed - this will use our cache-aware URL format
                series_generator = SeriesFeedGenerator()
                series_generator.add_series_to_feed(username, library_id, feed, series, token=token)
        
        # Process authors - using cached items to count ebooks per author
        search_author_names = set()
        author_data_by_name = {}
        
        for author_result in search_data.get("authors", []):
            if "name" in author_result:
                author_name = author_result.get("name")
                search_author_names.add(author_name)
                author_data_by_name[author_name] = author_result
        
        # Only proceed if we found author names
        if search_author_names:
            # Dictionary to count ebooks per author using cached items
            author_ebook_counts = {}
            
            # Check each cached item to see if it matches our search authors and has an ebook
            for item in cached_library_items:
                # Get author name from the item's metadata
                author_name = item.get("media", {}).get("metadata", {}).get("authorName")
                if author_name and author_name in search_author_names:
                    # Increment the ebook count for this author
                    if author_name not in author_ebook_counts:
                        author_ebook_counts[author_name] = 0
                    author_ebook_counts[author_name] += 1
            
            # Now add each author that has books with ebooks to the feed
            for author_name, ebook_count in author_ebook_counts.items():
                author_data = author_data_by_name.get(author_name)
                if author_data:
                    # Add the ebook count to the author data
                    author_data["ebook_count"] = ebook_count
                    author_data["id"] = author_data.get("id", "")
                    
                    author_generator = AuthorFeedGenerator()
                    author_generator.add_author_to_feed(username, library_id, feed, author_data, token=token)
        
        return self.create_response(feed)