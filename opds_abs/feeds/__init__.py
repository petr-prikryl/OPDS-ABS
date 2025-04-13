"""Feed generators for OPDS"""

from opds_abs.feeds.library_feed import LibraryFeedGenerator
from opds_abs.feeds.navigation_feed import NavigationFeedGenerator
from opds_abs.feeds.series_feed import SeriesFeedGenerator
from opds_abs.feeds.collection_feed import CollectionFeedGenerator
from opds_abs.feeds.author_feed import AuthorFeedGenerator
from opds_abs.feeds.search_feed import SearchFeedGenerator

__all__ = [
    'LibraryFeedGenerator',
    'NavigationFeedGenerator',
    'SeriesFeedGenerator',
    'CollectionFeedGenerator',
    'AuthorFeedGenerator',
    'SearchFeedGenerator'
]