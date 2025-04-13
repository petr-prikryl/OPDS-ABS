"""Navigation feed generator"""
from lxml import etree

from opds_abs.core.feed_generator import BaseFeedGenerator
from opds_abs.core.navigation import navigation

class NavigationFeedGenerator(BaseFeedGenerator):
    """Generator for navigation feed"""
    
    async def generate_nav_feed(self, username, library_id):
        """Generate the navigation buttons under a library"""
        self.verify_user(username)

        feed = self.create_base_feed(username, library_id)
        title = etree.SubElement(feed, "title")
        title.text = "Navigation"
        
        for nav in navigation:
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

        return self.create_response(feed)