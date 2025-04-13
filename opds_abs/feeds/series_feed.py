"""Series feed generator"""
from lxml import etree

from opds_abs.core.feed_generator import BaseFeedGenerator
from opds_abs.api.client import fetch_from_api
from opds_abs.config import AUDIOBOOKSHELF_API

class SeriesFeedGenerator(BaseFeedGenerator):
    """Generator for series feed"""
    
    def filter_series(self, data):
        """Find items in a library series that have an ebook file, sorted by a field"""
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
    
    def add_series_to_feed(self, username, library_id, feed, series):
        """Add a series to the feed"""
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
    
    async def generate_series_feed(self, username, library_id):
        """Display all series in the library"""
        self.verify_user(username)

        series_params = {"limit": 2000, "sort": "name"}
        data = await fetch_from_api(f"/libraries/{library_id}/series", series_params)

        feed = self.create_base_feed(username, library_id)
        feed_id = etree.SubElement(feed, "id")
        feed_id.text = library_id
        title = etree.SubElement(feed, "title")
        title.text = f"{username}'s series"

        series_items = self.filter_series(data)

        for series in series_items:
            self.add_series_to_feed(username, library_id, feed, series)

        return self.create_response(feed)