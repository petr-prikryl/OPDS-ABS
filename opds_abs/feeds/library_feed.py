"""Library items feed generator"""
import asyncio
from lxml import etree
from fastapi.responses import RedirectResponse

from opds_abs.core.feed_generator import BaseFeedGenerator
from opds_abs.api.client import fetch_from_api, get_download_urls_from_item
from opds_abs.utils import dict_to_xml

class LibraryFeedGenerator(BaseFeedGenerator):
    """Generator for library items feed"""
    
    async def generate_root_feed(self, username):
        """Generate the root feed with libraries"""
        self.verify_user(username)

        data = await fetch_from_api("/libraries")
        feed = self.create_base_feed()
        
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
                                "type": "application/atom+xml"
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
        
    async def generate_library_items_feed(self, username, library_id, params=None):
        """Display all items in the library"""
        self.verify_user(username)

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
                        
                        # Create feed metadata using dictionary approach
                        feed_data = {
                            "id": {"_text": library_id},
                            "author": {
                                "name": {"_text": "OPDS Audiobookshelf"}
                            },
                            "title": {"_text": f"{username}'s books in collection: {collection_data.get('name', 'Unknown')}"}
                        }
                        dict_to_xml(feed, feed_data)
                        
                        # Get ebook files for each book
                        tasks = []
                        for book in sorted_books:
                            book_id = book.get("id", "")
                            tasks.append(get_download_urls_from_item(book_id))
                        
                        ebook_inos_list = await asyncio.gather(*tasks)
                        for book, ebook_inos in zip(sorted_books, ebook_inos_list):
                            self.add_book_to_feed(feed, book, ebook_inos, params.get('filter',''))
                        
                        return self.create_response(feed)
                    else:
                        print("No books with ebooks found in this collection")
                    
            except Exception as e:
                print(f"Error processing collection data: {e}")
                import traceback
                traceback.print_exc()
        
        # If not filtering by collection or collection processing failed, continue with normal flow
        print("Using standard library items endpoint")
        data = await fetch_from_api(f"/libraries/{library_id}/items", params)

        feed = self.create_base_feed(username, library_id)
        
        # Create feed metadata using dictionary approach
        feed_data = {
            "id": {"_text": library_id},
            "author": {
                "name": {"_text": "OPDS Audiobookshelf"}
            },
            "title": {"_text": f"{username}'s books"}
        }
        dict_to_xml(feed, feed_data)

        library_items = self.filter_items(data)

        tasks = []
        for book in library_items:
            book_id = book.get("id", "")
            tasks.append(get_download_urls_from_item(book_id))

        ebook_inos_list = await asyncio.gather(*tasks)
        for book, ebook_inos in zip(library_items, ebook_inos_list):
            self.add_book_to_feed(feed, book, ebook_inos, params.get('filter',''))

        return self.create_response(feed)