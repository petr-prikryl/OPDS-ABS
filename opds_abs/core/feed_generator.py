"""Base class for generating OPDS feeds"""
from base64 import b64encode
from copy import deepcopy
from lxml import etree
from fastapi import HTTPException
from fastapi.responses import Response

from opds_abs.config import AUDIOBOOKSHELF_API, USER_KEYS

class BaseFeedGenerator:
    """Base class for creating OPDS feed components"""
    
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
        
    def create_response(self, feed):
        """Convert feed to XML and create a response"""
        feed_xml = etree.tostring(feed, pretty_print=True, xml_declaration=False, encoding="UTF-8")
        return Response(content=feed_xml, media_type="application/atom+xml")
        
    def verify_user(self, username):
        """Verify that the username exists"""
        if username not in USER_KEYS:
            raise HTTPException(status_code=404, detail="User not found")
            
    def add_book_to_feed(self, feed, book, ebook_inos, query_filter=""):
        """Add a book to the feed"""
        # Implementation from OPDSFeed.add_book_to_feed
        from datetime import datetime
        
        media = book.get("media", {})
        # Extract ebook format - check both direct and nested paths (for search results)
        ebook_format = media.get("ebookFormat", media.get("ebookFile", {}).get("ebookFormat"))
        
        for ebook in ebook_inos:
            book_metadata = media.get("metadata", {})
            book_path = f"{AUDIOBOOKSHELF_API}/items/{book.get('id','')}"
            download_path = f"{book_path}/file/{ebook.get('ino')}/download?token={USER_KEYS.get(book.get('username'))}"
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
                entry_series_name.text = f" - {series_name} #{series_number}"
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
            
    def create_filter(self, abs_filter=None):
        """Create a filter to be used by Audiobookshelf"""
        return b64encode(abs_filter.encode("utf-8")).decode("utf-8")
        
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