""" Create an OPDS feed """
import asyncio
from copy import deepcopy
from lxml import etree
from fastapi import HTTPException
from fastapi.responses import Response, RedirectResponse
from fetch_api import fetch_from_api, get_download_urls_from_item
from filter_items import filter_ebook_items
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
            etree.SubElement(entry,
                "link",
                href=f"/opds/{username}/library/{library_id}/{nav.get('path', '')}",
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

    async def generate_library_feed(self, username, library_id, sort=None):
        """Display all items in the library"""
        if username not in USER_KEYS:
            raise HTTPException(status_code=404, detail="User not found")

        data = await fetch_from_api(f"/libraries/{library_id}/items")

        print(f"📥 API response contains {len(data.get('results', []))} items")

        feed = self.create_base_feed()
        title = etree.SubElement(feed, "title")
        title.text = f"{username}'s books"

        library_items = filter_ebook_items(data, sort, True) if sort else filter_ebook_items(data)

        tasks = []

        for book in library_items:
            print(f"🔍 Processing: {book.get('id')}")
            book_id = book.get("id", "")

            tasks.append(get_download_urls_from_item(book_id))

        ebook_inos_list = await asyncio.gather(*tasks)
        for book, ebook_inos in zip(library_items, ebook_inos_list):
            self.add_book_to_feed(feed, book, ebook_inos)

        feed_xml = etree.tostring(feed, pretty_print=True, xml_declaration=False, encoding="UTF-8")
        return Response(content=feed_xml, media_type="application/atom+xml")

    async def fetch_library_items(self, library_id):
        """Fetch items from the library"""
        data = await fetch_from_api(f"/libraries/{library_id}/items")
        print(f"📥 API response contains {len(data.get('results', []))} items")
        return data

    def add_book_to_feed(self, feed, book, ebook_inos):
        """Add a book to the feed"""
        ebook_format = book.get("media", {}).get("ebookFormat", None)
        for ebook in ebook_inos:
            book_metadata = book.get("media", {}).get("metadata", {})
            book_path = f"{AUDIOBOOKSHELF_API}/items/{book.get('id','')}"
            download_path = f"{book_path}/file/{ebook.get('ino')}/download?token={API_KEY}"
            cover_url = f"{book_path}/cover?format=jpeg"

            print(f"✅ Adding book: {book_metadata.get('title')} ({ebook_format})")

            entry = etree.SubElement(feed, "entry")
            entry_title = etree.SubElement(entry, "title")
            entry_title.text = book_metadata.get("title", "Unknown Title")
            entry_id = etree.SubElement(entry, "id")
            entry_id.text = book.get("id")
            entry_author = etree.SubElement(entry, "content", type="text")
            entry_author.text = book_metadata.get("authorName", "Unknown Author")
            etree.SubElement(
                entry,
                "link",
                href=download_path,
                rel="http://opds-spec.org/acquisition/open-access",
                type=f"application/{ebook_format}"
            )
            etree.SubElement(
                entry,
                "link",
                href=cover_url,
                rel="http://opds-spec.org/image",
                type="image/jpeg"
            )
