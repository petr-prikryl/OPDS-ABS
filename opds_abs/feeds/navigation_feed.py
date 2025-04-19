"""Navigation feed generator"""
# Standard library imports
import logging

# Local application imports
from opds_abs.core.feed_generator import BaseFeedGenerator
from opds_abs.core.navigation import navigation
from opds_abs.utils import dict_to_xml

# Set up logging
logger = logging.getLogger(__name__)

class NavigationFeedGenerator(BaseFeedGenerator):
    """Generator for navigation feed.

    This class creates OPDS feeds that provide navigation options for an Audiobookshelf
    library, such as links to browse by series, authors, and collections.

    Attributes:
        Inherits all attributes from BaseFeedGenerator.
    """

    async def generate_navigation_feed(self, username, library_id, token=None):
        """Generate the navigation feed with links to various sections.

        Args:
            username (str): The username requesting the feed.
            library_id (str): The ID of the library to generate the feed for.
            token (str, optional): Authentication token for Audiobookshelf.

        Returns:
            Response: A FastAPI response object containing the XML feed.
        """
        try:
            # Log the request
            logger.info("Generating navigation feed for user %s, library %s", username, library_id)

            # Create the feed
            feed = self.create_base_feed(username, library_id)

            # Build the feed metadata
            feed_data = {
                "id": {"_text": f"{library_id}/navigation"},
                "title": {"_text": f"Navigation for {username}'s library"},
                "author": {
                    "name": {"_text": "OPDS Audiobookshelf"},
                    "uri": {"_text": "https://github.com/chrhelming/OPDS-ABS"}
                },
                "link": [
                    {
                        "_attrs": {
                            "href": f"/opds/{username}/libraries/{library_id}",
                            "rel": "start",
                            "type": "application/atom+xml;profile=opds-catalog"
                        }
                    }
                ]
            }

            # Add feed title using dictionary approach
            feed_data["title"] = {"_text": "Navigation"}
            dict_to_xml(feed, feed_data)

            for nav in navigation:
                # Set up navigation item paths and URLs
                base_path = f"/opds/{username}/libraries/{library_id}/"
                nav_params = nav.get('params','')

                # Add authentication token to nav_params if available
                if token and nav_params:
                    nav_href = f"{base_path}{nav.get('path','')}?{nav_params}&token={token}"
                elif token:
                    nav_href = f"{base_path}{nav.get('path','')}?token={token}"
                elif nav_params:
                    nav_href = f"{base_path}{nav.get('path','')}?{nav_params}"
                else:
                    nav_href = f"{base_path}{nav.get('path','')}"

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
        except Exception as e:
            logger.error("Error generating navigation feed: %s", e)
            raise
