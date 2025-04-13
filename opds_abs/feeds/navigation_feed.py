"""Navigation feed generator"""
from lxml import etree

from opds_abs.core.feed_generator import BaseFeedGenerator
from opds_abs.core.navigation import navigation
from opds_abs.utils import dict_to_xml

class NavigationFeedGenerator(BaseFeedGenerator):
    """Generator for navigation feed"""
    
    async def generate_nav_feed(self, username, library_id):
        """Generate the navigation buttons under a library"""
        self.verify_user(username)

        feed = self.create_base_feed(username, library_id)
        
        # Add feed title using dictionary approach
        feed_data = {
            "title": {"_text": "Navigation"}
        }
        dict_to_xml(feed, feed_data)
        
        for nav in navigation:
            # Set up navigation item paths and URLs
            base_path = f"/opds/{username}/libraries/{library_id}/"
            nav_params = f"{nav.get('params','')}"
            nav_href = f"{base_path}{nav.get('path','')}?{nav_params}"
            
            # Create entry data structure
            entry_data = {
                "entry": {
                    "title": {"_text": nav.get("name", "")},
                    "content": {
                        "_attrs": {"type": "text"},
                        "_text": nav["desc"]
                    },
                    "link": [
                        {
                            "_attrs": {
                                "href": nav_href,
                                "rel": "subsection",
                                "type": "application/atom+xml"
                            }
                        },
                        {
                            "_attrs": {
                                "href": f"/static/images/{nav.get('name').lower()}.png",
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