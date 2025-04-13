"""Search feed generator"""
from lxml import etree
from fastapi.responses import Response
from opds_abs.core.feed_generator import BaseFeedGenerator
from opds_abs.api.client import fetch_from_api, get_download_urls_from_item
from opds_abs.feeds.author_feed import AuthorFeedGenerator
from opds_abs.feeds.series_feed import SeriesFeedGenerator
from opds_abs.utils import dict_to_xml


class SearchFeedGenerator(BaseFeedGenerator):
    """Generator for search feed"""
    
    async def generate_search_feed(self, username, library_id, params=None):
        """Search for books, series, and authors in the library"""
        self.verify_user(username)

        # Extract search query from parameters
        query = params.get("q", "")
        if not query:
            # If no query provided, return empty search results
            feed = self.create_base_feed(username, library_id)
            feed_data = {
                "title": {"_text": f"Search results for: {query}"}
            }
            dict_to_xml(feed, feed_data)
            feed_xml = etree.tostring(feed, pretty_print=True, xml_declaration=False, encoding="UTF-8")
            return Response(content=feed_xml, media_type="application/atom+xml")

        # Prepare search parameters
        search_params = {"limit": 2000, "q": query}
        
        # Call the search API endpoint
        search_data = await fetch_from_api(f"/libraries/{library_id}/search", search_params)
        
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
                ebook_inos = await get_download_urls_from_item(lib_item.get("id"))
                self.add_book_to_feed(feed, lib_item, ebook_inos, "")
        
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
        
        # Only fetch library items if we have series with ebooks
        if series_with_ebooks:
            # Fetch all library items with ebooks for author lookup
            items_params = {"limit": 2000, "sort": "media.metadata.title"}
            items_data = await fetch_from_api(f"/libraries/{library_id}/items", items_params)
            
            # Create a map of series IDs to their most common author
            series_author_map = {}
            
            # Process each library item to find series and authors
            for item in items_data.get("results", []):
                media = item.get("media", {})
                metadata = media.get("metadata", {})
                
                # Skip if no ebook
                if not (media.get("ebookFile") is not None or media.get("ebookFormat")):
                    continue
                
                # Get author and series information
                author_name = metadata.get("authorName")
                series_list = metadata.get("series", [])
                
                # Skip processing if there's no series or author information
                if not (author_name and series_list):
                    continue
                
                # Only process series that are in our search results
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
            
            # Now add each series to the feed with author information
            for series in series_with_ebooks:
                series_id = series.get('id')
                series_name = series.get('name')
                
                # Instead of our previous approach, directly query the items endpoint with the series filter
                # to get the books that are definitely in this series
                filter_b64 = self.create_filter(series_id)
                series_filter_param = {"filter": f"series.{filter_b64}", "sort": "media.metadata.series.number", "limit": 1}
                
                # Get the items for this specific series
                try:
                    series_items_data = await fetch_from_api(f"/libraries/{library_id}/items", series_filter_param)
                    series_books = series_items_data.get("results", [])
                    
                    # If we found books in this series, use the author from the first book
                    if series_books:
                        first_book = series_books[0]
                        first_book_author = first_book.get("media", {}).get("metadata", {}).get("authorName")
                        
                        if first_book_author:
                            series["authorName"] = first_book_author
                        else:
                            # Fallback to first book in the search results if no author found
                            first_search_book = series.get('books', [])[0] if series.get('books') else None
                            if first_search_book:
                                search_book_author = first_search_book.get('media', {}).get('metadata', {}).get('authorName')
                                if search_book_author:
                                    series["authorName"] = search_book_author
                                else:
                                    # No author found in first book
                                    series["authorName"] = None
                            else:
                                # No books found
                                series["authorName"] = None
                    else:
                        # No books found in the direct series query
                        # Use the first book from the search results as a fallback
                        first_search_book = series.get('books', [])[0] if series.get('books') else None
                        if first_search_book:
                            search_book_author = first_search_book.get('media', {}).get('metadata', {}).get('authorName')
                            if search_book_author:
                                series["authorName"] = search_book_author
                            else:
                                series["authorName"] = None
                        else:
                            series["authorName"] = None
                    
                except Exception as e:
                    print(f"Error fetching series items: {e}")
                    # Use the first book from the search results as a fallback
                    first_search_book = series.get('books', [])[0] if series.get('books') else None
                    if first_search_book:
                        search_book_author = first_search_book.get('media', {}).get('metadata', {}).get('authorName')
                        if search_book_author:
                            series["authorName"] = search_book_author
                        else:
                            series["authorName"] = None
                    else:
                        series["authorName"] = None
                
                # Add the series to the feed
                series_generator = SeriesFeedGenerator()
                series_generator.add_series_to_feed(username, library_id, feed, series)
        
        # Process authors - authors don't have books array in search results, so we need to fetch items
        # with matching author names and filter for those with ebooks
        # Create a set of author names from search results
        search_author_names = set()
        author_data_by_name = {}
        
        for author_result in search_data.get("authors", []):
            if "name" in author_result:
                author_name = author_result.get("name")
                search_author_names.add(author_name)
                author_data_by_name[author_name] = author_result
        
        # Only proceed if we found author names
        if search_author_names:
            # Get all library items
            items_params = {"limit": 2000, "sort": "media.metadata.authorName"}
            items_data = await fetch_from_api(f"/libraries/{library_id}/items", items_params)
            
            # Dictionary to count ebooks per author
            author_ebook_counts = {}
            
            # Check each item to see if it matches our search authors and has an ebook
            for item in items_data.get("results", []):
                media = item.get("media", {})
                if media.get("ebookFile") is not None or media.get("ebookFormat"):
                    # Get author name from the item's metadata
                    author_name = media.get("metadata", {}).get("authorName")
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
                    author_generator.add_author_to_feed(username, library_id, feed, author_data)
        
        # Instead of calling etree.tostring directly, use the create_response method
        return self.create_response(feed)