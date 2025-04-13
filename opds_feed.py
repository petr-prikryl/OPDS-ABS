"""Create an OPDS feed"""
import asyncio
from base64 import b64encode
from datetime import datetime
from copy import deepcopy
from lxml import etree
from fastapi import HTTPException
from fastapi.responses import Response, RedirectResponse
from fetch_api import fetch_from_api, get_download_urls_from_item
from config import AUDIOBOOKSHELF_API, AUDIOBOOKSHELF_URL, USER_KEYS, API_KEY
import navigation_menu

class OPDSFeed:
    """An OPDS feed of the ebooks in Audiobookshelf"""
    def __init__(self):
        self.base_feed = etree.Element(
            "feed",
            xmlns="http://www.w3.org/2005/Atom",
            nsmap={"opds": "http://opds-spec.org/2010/catalog"}
        )

    def create_base_feed(self, username=None, library_id=None):
        """Create a copy of the base feed"""
        base_feed = deepcopy(self.base_feed)
        if username and library_id:
            etree.SubElement(base_feed, "link",
                href=f"/opds/{username}/libraries/{library_id}/search.xml",
                rel="search",
                type="application/opensearchdescription+xml"
            )
        return base_feed

    async def generate_root_feed(self, username):
        """Generate the root feed"""
        if username not in USER_KEYS:
            raise HTTPException(status_code=404, detail="User not found")

        data = await fetch_from_api("/libraries")
        feed = self.create_base_feed()
        title = etree.SubElement(feed, "title")
        title.text = f"{username}'s Libraries"
        libraries = data.get("libraries", [])
        if len(libraries) == 1:
            return RedirectResponse(
                    url=f"/opds/{username}/libraries/{libraries[0].get('id', '')}",
                    status_code=302
            )

        for library in libraries:
            entry = etree.SubElement(feed, "entry")
            entry_title = etree.SubElement(entry, "title")
            entry_title.text = library["name"]
            etree.SubElement(entry, "link",
                             href=f"/opds/{username}/libraries/{library['id']}",
                             rel="subsection",
                             type="application/atom+xml"
            )
            etree.SubElement(entry, "link",
                             href="/static/images/libraries.png",
                             rel="http://opds-spec.org/image",
                             type="image/png"
            )

        feed_xml = etree.tostring(feed, pretty_print=True, xml_declaration=False, encoding="UTF-8")
        return Response(content=feed_xml, media_type="application/atom+xml")

    async def generate_nav_feed(self, username, library_id):
        """Generate the navigation buttons under a library"""
        if username not in USER_KEYS:
            raise HTTPException(status_code=404, detail="User not found")

        feed = self.create_base_feed(username, library_id)
        title = etree.SubElement(feed, "title")
        title.text = "Navigaton"
        for nav in navigation_menu.navigation:
            entry = etree.SubElement(feed, "entry")
            entry_title = etree.SubElement(entry, "title")
            entry_title.text = nav.get("name", "")
            base_path = f"/opds/{username}/libraries/{library_id}/"
            nav_params = f"{nav.get('params','')}"
            nav_href = f"{base_path}{nav.get('path','')}?{nav_params}"
            etree.SubElement(entry,
                "link",
                href=f"{nav_href}",
                rel="subsection",
                type="application/atom+xml"
            )
            etree.SubElement(entry,
                "link",
                href=f"/static/images/{nav.get('name').lower()}.png",
                rel="http://opds-spec.org/image",
                type="image/png"
            )
            description = etree.SubElement(entry, "content", type="text")
            description.text = nav["desc"]

        feed_xml = etree.tostring(feed, pretty_print=True, xml_declaration=False, encoding="UTF-8")

        return Response(content=feed_xml, media_type="application/atom+xml")

    async def generate_library_items_feed(self, username, library_id, params=None):
        """Display all items in the library"""
        # pylint: disable-msg=too-many-locals
        if username not in USER_KEYS:
            raise HTTPException(status_code=404, detail="User not found")

        params = params if params else {}
        
        # Check if we're filtering by collection using direct collection parameter
        collection_id = params.get('collection')
    

        # If we're filtering by collection, fetch the collection data directly
        if collection_id:
            try:
                # Directly fetch the collection with its books
                collection_endpoint = f"/collections/{collection_id}"
                print(f"Fetching collection from: {collection_endpoint}")
                collection_data = await fetch_from_api(collection_endpoint)
                
                if collection_data:
                    print(f"Successfully fetched collection: {collection_data.get('name')}")
                    if 'books' in collection_data:
                        print(f"Collection has {len(collection_data.get('books', []))} books")
                    else:
                        print("No books found in collection response")
                
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
                    
                    print(f"Found {len(filtered_books)} books with ebooks in collection")
                    
                    if filtered_books:
                        # Add sequence numbers for sorting
                        for i, book in enumerate(filtered_books, 1):
                            book["opds_seq"] = i
                        
                        # Sort the books
                        sorted_books = self.sort_results(filtered_books)
                        
                        # Generate feed using these books directly
                        feed = self.create_base_feed(username, library_id)
                        feed_id = etree.SubElement(feed, "id")
                        feed_id.text = library_id
                        feed_author = etree.SubElement(feed, "author")
                        feed_author_name = etree.SubElement(feed_author, "name")
                        feed_author_name.text = "OPDS Audiobookshelf"
                        title = etree.SubElement(feed, "title")
                        title.text = f"{username}'s books in collection: {collection_data.get('name', 'Unknown')}"
                        
                        # Get ebook files for each book
                        tasks = []
                        for book in sorted_books:
                            book_id = book.get("id", "")
                            tasks.append(get_download_urls_from_item(book_id))
                        
                        ebook_inos_list = await asyncio.gather(*tasks)
                        for book, ebook_inos in zip(sorted_books, ebook_inos_list):
                            self.add_book_to_feed(feed, book, ebook_inos, params.get('filter',''))
                        
                        feed_xml = etree.tostring(feed, pretty_print=True, xml_declaration=False, encoding="UTF-8")
                        return Response(content=feed_xml, media_type="application/atom+xml")
                    else:
                        print("No books with ebooks found in this collection")
                else:
                    print("No valid collection data returned from API")
                    
            except Exception as e:
                print(f"Error processing collection data: {e}")
                import traceback
                traceback.print_exc()
        
        # If not filtering by collection or collection processing failed, continue with normal flow
        print("Using standard library items endpoint")
        data = await fetch_from_api(f"/libraries/{library_id}/items", params)

        feed = self.create_base_feed(username, library_id)
        feed_id = etree.SubElement(feed, "id")
        feed_id.text = library_id
        feed_author = etree.SubElement(feed, "author")
        feed_author_name = etree.SubElement(feed_author, "name")
        feed_author_name.text = "OPDS Audiobookshelf"
        title = etree.SubElement(feed, "title")
        title.text = f"{username}'s books"

        library_items = self.filter_items(data)

        tasks = []
        for book in library_items:
            book_id = book.get("id", "")
            tasks.append(get_download_urls_from_item(book_id))

        ebook_inos_list = await asyncio.gather(*tasks)
        for book, ebook_inos in zip(library_items, ebook_inos_list):
            self.add_book_to_feed(feed, book, ebook_inos, params.get('filter',''))

        feed_xml = etree.tostring(feed, pretty_print=True, xml_declaration=False, encoding="UTF-8")
        return Response(content=feed_xml, media_type="application/atom+xml")

    async def generate_series_feed(self, username, library_id):
        """Display all series in the library"""
        # pylint: disable-msg=too-many-locals
        if username not in USER_KEYS:
            raise HTTPException(status_code=404, detail="User not found")

        series_params = {"limit":2000, "sort":"name"}
        data = await fetch_from_api(f"/libraries/{library_id}/series", series_params)
        #print(f"📥 API response contains {len(data.get('results', []))} items")

        feed = self.create_base_feed(username, library_id)
        feed_id = etree.SubElement(feed, "id")
        feed_id.text = library_id
        title = etree.SubElement(feed, "title")
        title.text = f"{username}'s series"

        series_items = self.filter_series(data)

        for series in series_items:
            self.add_series_to_feed(username, library_id, feed, series)

        feed_xml = etree.tostring(feed, pretty_print=True, xml_declaration=False, encoding="UTF-8")
        return Response(content=feed_xml, media_type="application/atom+xml")

    async def generate_collections_feed(self, username, library_id):
        """Display all collections in the library that have books with ebook files"""
        # pylint: disable-msg=too-many-locals
        if username not in USER_KEYS:
            raise HTTPException(status_code=404, detail="User not found")

        collections_params = {"limit": 2000, "sort": "name"}
        data = await fetch_from_api(f"/libraries/{library_id}/collections", collections_params)

        # Filter collections to only include those with books in the specified library
        # and where at least one book has an ebookFile
        filtered_collections = []
        for collection in data.get("results", []):
            if collection.get("libraryId") == library_id:
                # Get books with ebookFile
                books_with_ebooks = []
                for book in collection.get("books", []):
                    if book.get("media", {}).get("ebookFile") is not None:
                        books_with_ebooks.append(book)
                
                if books_with_ebooks:
                    collection["books"] = books_with_ebooks
                    filtered_collections.append(collection)

        # Sort collections
        filtered_collections = sorted(filtered_collections, key=lambda x: x.get("name", ""))

        # Add each collection to the feed
        feed = self.create_base_feed(username, library_id)
        feed_id = etree.SubElement(feed, "id")
        feed_id.text = library_id
        title = etree.SubElement(feed, "title")
        title.text = f"{username}'s collections"

        for collection in filtered_collections:
            self.add_collection_to_feed(username, library_id, feed, collection)

        feed_xml = etree.tostring(feed, pretty_print=True, xml_declaration=False, encoding="UTF-8")
        return Response(content=feed_xml, media_type="application/atom+xml")

    async def generate_authors_feed(self, username, library_id):
        """Display all authors in the library that have books with ebook files"""
        # pylint: disable-msg=too-many-locals
        if username not in USER_KEYS:
            raise HTTPException(status_code=404, detail="User not found")

        # Fetch authors from the API using the correct endpoint
        authors_params = {"limit": 2000}
        authors_data = await fetch_from_api(f"/libraries/{library_id}/authors", authors_params)
        
        # Create a dictionary of authors by name for fast lookup
        authors_by_name = {}
        for author in authors_data.get("authors", []):
            if author.get("name"):
                authors_by_name[author.get("name")] = author
        
        # Fetch all library items sorted by author name
        items_params = {"limit": 2000, "sort": "media.metadata.authorName"}
        items_data = await fetch_from_api(f"/libraries/{library_id}/items", items_params)
        
        # Process items to get unique authors while maintaining sort order
        seen_author_names = set()
        sorted_authors = []
        
        for item in items_data.get("results", []):
            media = item.get("media", {})
            if media.get("ebookFile") is not None or media.get("ebookFormat"):
                # Get author name from the item's metadata
                author_name = media.get("metadata", {}).get("authorName")
                if author_name and author_name not in seen_author_names:
                    # Check if we have this author in our authors data
                    if author_name in authors_by_name:
                        seen_author_names.add(author_name)
                        sorted_authors.append(authors_by_name[author_name])
        
        # Create the feed
        feed = self.create_base_feed(username, library_id)
        feed_id = etree.SubElement(feed, "id")
        feed_id.text = library_id
        title = etree.SubElement(feed, "title")
        title.text = f"{username}'s authors"
        
        # Add each author to the feed
        for author in sorted_authors:
            self.add_author_to_feed(username, library_id, feed, author)
        
        feed_xml = etree.tostring(feed, pretty_print=True, xml_declaration=False, encoding="UTF-8")
        return Response(content=feed_xml, media_type="application/atom+xml")
    
    async def generate_search_feed(self, username, library_id, params=None):
        """Search for books, series, and authors in the library"""
        if username not in USER_KEYS:
            raise HTTPException(status_code=404, detail="User not found")

        # Extract search query from parameters
        query = params.get("q", "")
        if not query:
            # If no query provided, return empty search results
            feed = self.create_base_feed(username, library_id)
            title = etree.SubElement(feed, "title")
            title.text = f"Search results for: {query}"
            feed_xml = etree.tostring(feed, pretty_print=True, xml_declaration=False, encoding="UTF-8")
            return Response(content=feed_xml, media_type="application/atom+xml")

        # Prepare search parameters
        search_params = {"limit": 2000, "q": query}
        
        # Call the search API endpoint
        search_data = await fetch_from_api(f"/libraries/{library_id}/search", search_params)
        
        # Create the base feed
        feed = self.create_base_feed()
        feed_id = etree.SubElement(feed, "id")
        feed_id.text = f"{library_id}/search/{query}"
        title = etree.SubElement(feed, "title")
        title.text = f"Search results for: {query}"
        
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
                self.add_series_to_feed(username, library_id, feed, series)
        
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
            
            # Create a set to track authors who have books with ebooks
            authors_with_ebooks = set()
            
            # Check each item to see if it matches our search authors and has an ebook
            for item in items_data.get("results", []):
                media = item.get("media", {})
                if media.get("ebookFile") is not None or media.get("ebookFormat"):
                    # Get author name from the item's metadata
                    author_name = media.get("metadata", {}).get("authorName")
                    if author_name and author_name in search_author_names:
                        # This author has at least one book with an ebook
                        authors_with_ebooks.add(author_name)
            
            # Now add each author that has books with ebooks to the feed
            for author_name in authors_with_ebooks:
                author_data = author_data_by_name.get(author_name)
                if author_data:
                    self.add_author_to_feed(username, library_id, feed, author_data)
        
        feed_xml = etree.tostring(feed, pretty_print=True, xml_declaration=False, encoding="UTF-8")
        return Response(content=feed_xml, media_type="application/atom+xml")

    def add_author_to_feed(self, username, library_id, feed, author):
        """Add an author to the feed"""
        # Skip if we don't have necessary data
        if not author.get("id") or not author.get("name"):
            return
        
        entry = etree.SubElement(feed, "entry")
        
        # Add author name as title
        entry_title = etree.SubElement(entry, "title")
        entry_title.text = author.get("name", "Unknown author name")
        
        # Add author ID
        entry_id = etree.SubElement(entry, "id")
        entry_id.text = author.get("id")
        
        # Add description if available
        description = author.get("description")
        if description:
            entry_content = etree.SubElement(entry, "content")
            entry_content.text = description
        else:
            entry_content = etree.SubElement(entry, "content")
            entry_content.text = f"Books by {author.get('name', 'Unknown author')}"
        
        # Create filter for this author
        author_filter = f"filter=authors.{self.create_filter(author.get('id'))}&sort=media.metadata.title"
        
        # Add link to author's books
        etree.SubElement(entry,
            "link",
            href=f"/opds/{username}/libraries/{library_id}/items?{author_filter}",
            rel="subsection",
            type="application/atom+xml"
        )
        
        # Add author image if available
        if author.get("imagePath"):
            image_url = f"{AUDIOBOOKSHELF_API}/authors/{author.get('id')}/image?format=jpeg"
            etree.SubElement(entry,
                "link",
                href=image_url,
                rel="http://opds-spec.org/image",
                type="image/jpeg"
            )
        else:
            # Use the static unknown-author image
            etree.SubElement(entry,
                "link",
                href="/static/images/unknown-author.png",
                rel="http://opds-spec.org/image",
                type="image/png"
            )

    def add_book_to_feed(self, feed, book, ebook_inos, query_filter):
        """Add a book to the feed"""
        # pylint: disable-msg=too-many-locals
        media = book.get("media", {})
        # Extract ebook format - check both direct and nested paths (for search results)
        ebook_format = media.get("ebookFormat", media.get("ebookFile", {}).get("ebookFormat"))
        
        for ebook in ebook_inos:
            book_metadata = media.get("metadata", {})
            #print(f"✅ Adding book: {book_metadata.get('title')} ({ebook_format})")
            book_path = f"{AUDIOBOOKSHELF_API}/items/{book.get('id','')}"
            download_path = f"{book_path}/file/{ebook.get('ino')}/download?token={API_KEY}"
            cover_url = f"{book_path}/cover?format=jpeg"
            series_list = book_metadata.get("seriesName", None)
            added_at = datetime.fromtimestamp(book.get('addedAt')/1000).strftime('%Y-%m-%d')

            entry = etree.SubElement(feed, "entry")
            entry_title = etree.SubElement(entry, "title")
            entry_title.text = book_metadata.get("title", "Unknown Title")
            entry_id = etree.SubElement(entry, "id")
            entry_id.text = book.get("id")
            entry_content = etree.SubElement(entry, "content", type="xhtml")
            entry_content.text = (
                f"{book_metadata.get('description', '')}<br/><br/>"
                f"{'Series: ' + series_list + '<br/>' if series_list else ''}"
                f"Published year: {book_metadata.get('publishedYear')}<br/>"
                f"Genres: {', '.join(book_metadata.get('genres', []))}<br/>"
                f"Added at: {added_at}<br/>"
            )
            entry_author = etree.SubElement(entry, "author")
            entry_author_name = etree.SubElement(entry_author, "name")
            entry_author_name.text = book_metadata.get("authorName", "Unknown Author")
            if query_filter.startswith("series"):
                series_number = book_metadata.get('series',{}).get("sequence","")
                series_name = book_metadata.get('series',{}).get("name","")
                entry_series = etree.SubElement(entry, "author")
                entry_series_name = etree.SubElement(entry_series, "name")
                entry_series_name.text = f" - {series_name} #{series_number}"
            etree.SubElement(
                 entry,
                 "link",
                 href=download_path,
                 rel="http://opds-spec.org/acquisition",
                 type=f"application/{ebook_format or 'epub'}+zip"
             )
            etree.SubElement(
                entry,
                "link",
                href=cover_url,
                rel="http://opds-spec.org/image",
                type="image/jpeg"
            )

    def add_series_to_feed(self, username, library_id, feed, series):
        """Add a series to the feed"""
        # pylint: disable-msg=too-many-locals
        first_book = series.get('books', [])[0]
        first_book_metadata = first_book.get('media', {}).get('metadata', {})
        book_path = f"{AUDIOBOOKSHELF_API}/items/{first_book.get('id','')}"
        cover_url = f"{book_path}/cover?format=jpeg"
        
        # Determine if this was called from search feed by checking if authorName is already set
        # The search feed will directly set authorName, while series feed won't have this property
        from_search_feed = "authorName" in series
        
        print(f"Adding series: {series.get('name')} " + 
              f"with author: {series.get('authorName', 'None')} " +
              f"(from search feed: {from_search_feed})")
        
        entry = etree.SubElement(feed, "entry")
        entry_title = etree.SubElement(entry, "title")
        entry_title.text = series.get("name", "Unknown series name")
        entry_id = etree.SubElement(entry, "id")
        entry_id.text = series.get("id")
        
        # Get author name with proper fallback chain
        author_name = None
        raw_author_name = None
        
        # First try to use explicit authorName that should already be formatted from search feed
        if series.get("authorName") and not series.get("authorName").endswith("None"):
            author_name = series.get("authorName")
            # Extract raw author name (without "Series by " prefix) for atom:author element
            if author_name.startswith("Series by "):
                raw_author_name = author_name[10:]  # Remove "Series by " prefix
            else:
                raw_author_name = author_name
            print(f"  Using authorName from series object: {author_name}")
        
        # Then try to get from first book's metadata
        elif first_book_metadata.get("authorName"):
            raw_author_name = first_book_metadata.get("authorName")
            # Format differently based on the source of the call
            if from_search_feed:
                author_name = f"Series by {raw_author_name}"
            else:
                author_name = raw_author_name
            print(f"  Using author from first book metadata: {author_name}")
        
        # Finally fallback to a generic label
        else:
            if from_search_feed:
                author_name = "Unknown Series"
            else:
                author_name = "Unknown Author"
            raw_author_name = author_name
            print(f"  Using default author label: {author_name}")
        
        # Add proper atom:author element (this is what OPDS readers look for)
        entry_author = etree.SubElement(entry, "author")
        entry_author_name = etree.SubElement(entry_author, "name")
        entry_author_name.text = raw_author_name
        
        # Also keep the content element for backward compatibility
        # Format the content differently based on the source
        entry_content = etree.SubElement(entry, "content")
        if from_search_feed:
            # For search feed, ensure it starts with "Series by"
            if not author_name.startswith("Series by ") and not author_name == "Unknown Series":
                entry_content.text = f"Series by {raw_author_name}"
            else:
                entry_content.text = author_name
        else:
            # For series feed, just use the raw author name
            entry_content.text = raw_author_name
        
        series_filter = f"filter=series.{self.create_filter(series.get('id'))}"
        sort = "sort=media.metadata.series.number"
        params = f"{series_filter}&{sort}"
        etree.SubElement(entry,
            "link",
            href=f"/opds/{username}/libraries/{library_id}/items?{params}",
            rel="subsection",
            type="application/atom+xml"
        )
        etree.SubElement(
            entry,
            "link",
            href=cover_url,
            rel="http://opds-spec.org/image",
            type="image/jpeg"
        )

    def add_collection_to_feed(self, username, library_id, feed, collection):
        """Add a collection to the feed"""
        # pylint: disable-msg=too-many-locals
        if not collection.get("books"):
            return
            
        first_book = collection.get("books")[0]
        first_book_metadata = first_book.get("media", {}).get("metadata", {})
        book_path = f"{AUDIOBOOKSHELF_API}/items/{first_book.get('id','')}"
        cover_url = f"{book_path}/cover?format=jpeg"
        
        entry = etree.SubElement(feed, "entry")
        entry_title = etree.SubElement(entry, "title")
        entry_title.text = collection.get("name", "Unknown collection name")
        
        entry_id = etree.SubElement(entry, "id")
        entry_id.text = collection.get("id")
        
        # Add description if available
        description = collection.get("description")
        if description:
            entry_content = etree.SubElement(entry, "content")
            entry_content.text = description
        else:
            entry_content = etree.SubElement(entry, "content")
            entry_content.text = f"Collection with {len(collection.get('books', []))} books"
        
        # Create direct collection parameter instead of filter
        collection_param = f"collection={collection.get('id')}"
        
        etree.SubElement(entry,
            "link",
            href=f"/opds/{username}/libraries/{library_id}/items?{collection_param}",
            rel="subsection",
            type="application/atom+xml"
        )
        
        etree.SubElement(entry,
            "link",
            href=cover_url,
            rel="http://opds-spec.org/image",
            type="image/jpeg"
        )

    def filter_items(self, data):
        """Find items in a library that have an ebook file, sorted by a field in a specific order"""
        n = 1
        filtered_results = []
        for result in data.get("results", []):
            media = result.get("media", {})
            if "ebookFormat" in media and media.get("ebookFormat", None):
                result.update({"opds_seq":n})
                n += 1
                filtered_results.append(result)

        return filtered_results

    def filter_series(self, data):
        """Find items in a library series that have an ebook file, sorted by a field, asc or desc"""
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
    
    def sort_results(self, data):
        """Sort results"""
        sorted_results = sorted(
                data,
                key=lambda x: x["opds_seq"],
                reverse=False
            )
        return sorted_results

    def extract_value(self, item, path):
        """Extract keys from a JSON path"""
        keys = path.split('.')
        for key in keys:
            item = item.get(key, None)
            if item is None:
                break
        return item

    def create_filter(self, abs_filter=None):
        """Create a filter to be used by Audiobookshelf"""
        return b64encode(abs_filter.encode("utf-8")).decode("utf-8")
