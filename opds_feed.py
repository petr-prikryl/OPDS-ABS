"""Create an OPDS feed"""
import asyncio
from base64 import b64encode
from datetime import datetime
from copy import deepcopy
from lxml import etree
from fastapi import HTTPException
from fastapi.responses import Response, RedirectResponse
from fetch_api import fetch_from_api, get_download_urls_from_item
from config import AUDIOBOOKSHELF_API, USER_KEYS, API_KEY
import navigation_menu

class OPDSFeed:
    """An OPDS feed of the ebooks in Audiobookshelf"""
    def __init__(self):
        self.base_feed = etree.Element(
            "feed",
            xmlns="http://www.w3.org/2005/Atom",
            nsmap={"opds": "http://opds-spec.org/2010/catalog"}
        )

    def create_base_feed(self):
        """Create a copy of the base feed"""
        return deepcopy(self.base_feed)

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
                    url=f"/opds/{username}/library/{libraries[0].get('id', '')}",
                    status_code=302
            )

        for library in libraries:
            entry = etree.SubElement(feed, "entry")
            entry_title = etree.SubElement(entry, "title")
            entry_title.text = library["name"]
            etree.SubElement(entry, "link",
                             href=f"/opds/{username}/library/{library['id']}",
                             rel="subsection",
                             type="application/atom+xml"
            )
            etree.SubElement(entry, "link",
                             href=f"data:image/png;base64,{navigation_menu.LIBRARY}",
                             rel="http://opds-spec.org/image",
                             type="image/png"
            )

        feed_xml = etree.tostring(feed, pretty_print=True, xml_declaration=False, encoding="UTF-8")
        return Response(content=feed_xml, media_type="application/atom+xml")

    async def generate_nav_feed(self, username, library_id):
        """Generate the navigation buttons under a library"""
        if username not in USER_KEYS:
            raise HTTPException(status_code=404, detail="User not found")

        feed = self.create_base_feed()
        title = etree.SubElement(feed, "title")
        title.text = "Navigaton"
        for nav in navigation_menu.navigation:
            entry = etree.SubElement(feed, "entry")
            entry_title = etree.SubElement(entry, "title")
            entry_title.text = nav.get("name", "")
            nav_icon = getattr(navigation_menu, nav.get('name', '').upper())
            base_path = f"/opds/{username}/library/{library_id}/"
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
                href=f"data:image/png;base64,{nav_icon}",
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

        data = await fetch_from_api(f"/libraries/{library_id}/items", params)
        #print(f"📥 API response contains {len(data.get('results', []))} items")

        feed = self.create_base_feed()
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
            #print(f"🔍 Processing: {book.get('id')}")
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

        feed = self.create_base_feed()
        feed_id = etree.SubElement(feed, "id")
        feed_id.text = library_id
        title = etree.SubElement(feed, "title")
        title.text = f"{username}'s series"

        series_items = self.filter_series(data)

        for series in series_items:
            self.add_series_to_feed(username, library_id, feed, series)

        feed_xml = etree.tostring(feed, pretty_print=True, xml_declaration=False, encoding="UTF-8")
        return Response(content=feed_xml, media_type="application/atom+xml")

    def add_book_to_feed(self, feed, book, ebook_inos, query_filter):
        """Add a book to the feed"""
        # pylint: disable-msg=too-many-locals
        ebook_format = book.get("media", {}).get("ebookFormat", None)
        for ebook in ebook_inos:
            book_metadata = book.get("media", {}).get("metadata", {})
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
                 type=f"application/{ebook_format}+zip"
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
        #print(f"✅ Adding series: {series.get('name')}")
        entry = etree.SubElement(feed, "entry")
        entry_title = etree.SubElement(entry, "title")
        entry_title.text = series.get("name", "Unknown series name")
        entry_id = etree.SubElement(entry, "id")
        entry_id.text = series.get("id")
        entry_content = etree.SubElement(entry, "content")
        entry_content.text = first_book_metadata.get("authorName", "Unknown author")
        series_filter = f"filter=series.{self.create_filter(series.get('id'))}"
        sort = "sort=media.metadata.series.number"
        params = f"{series_filter}&{sort}"
        etree.SubElement(entry,
            "link",
            href=f"/opds/{username}/library/{library_id}/items?{params}",
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

        #return filtered_results
        return self.sort_results(filtered_results)


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

        if not filtered_results:
            return filtered_results

        return self.sort_results(filtered_results)

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
