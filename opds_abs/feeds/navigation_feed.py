"""Navigation feed generator"""
# Standard library imports
# None needed currently

# Third-party imports
from lxml import etree

# Local application imports
from opds_abs.core.feed_generator import BaseFeedGenerator
from opds_abs.core.navigation import navigation
from opds_abs.utils import dict_to_xml

class NavigationFeedGenerator(BaseFeedGenerator):
    """Generator for navigation feed.
    
    This class creates OPDS navigation feeds that present the main navigation
    options for browsing Audiobookshelf content through OPDS clients.
    
    Attributes:
        Inherits all attributes from BaseFeedGenerator.
    """
    
    async def generate_nav_feed(self, username, library_id):
        """Generate the navigation buttons under a library.
        
        Creates an OPDS feed containing navigation entries for browsing content
        in different ways (e.g., by authors, series, collections).
        
        Args:
            username (str): The username requesting the feed.
            library_id (str): The ID of the library to generate navigation for.
            
        Returns:
            Response: A FastAPI response object containing the XML feed.
            
        Raises:
            HTTPException: If the user is not authorized or another error occurs.
        """
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