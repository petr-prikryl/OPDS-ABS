"""Tests for feed generation fixes (pagination, authors, series, links)."""
import pytest
from lxml import etree

from opds_abs.core.feed_generator import BaseFeedGenerator
from opds_abs.feeds.author_feed import AuthorFeedGenerator
from opds_abs.feeds.series_feed import SeriesFeedGenerator
from opds_abs.utils.cache_utils import get_cached_author_details


def test_pagination_links_do_not_carry_the_abs_token():
    """Feed links must never contain the ABS token (issue #49)."""
    generator = BaseFeedGenerator()

    feed = generator.create_base_feed(
        "reader", "lib-1", "reader/libraries/lib-1/items?sort=addedAt", token="SECRET-TOKEN"
    )
    generator.add_pagination_links(
        feed, "reader/libraries/lib-1/items?sort=addedAt", 1, 25, 100, token="SECRET-TOKEN"
    )

    xml = etree.tostring(feed, encoding="unicode")

    assert "SECRET-TOKEN" not in xml
    assert "token=" not in xml
    assert "start_index=26" in xml


def test_series_sort_key_handles_unnumbered_and_odd_sequences():
    """Unnumbered or non-numeric sequence values must not raise."""
    def item(sequence):
        return {"media": {"metadata": {"series": {"sequence": sequence}}}}

    items = [item("2"), item(None), item("1.5"), item("1-2"), item(1), item("")]

    sorted_items = sorted(items, key=SeriesFeedGenerator._sequence_sort_key)
    sequences = [
        entry["media"]["metadata"]["series"]["sequence"] for entry in sorted_items
    ]

    # Numbered books first, in numeric order; unnumbered/non-numeric last.
    assert sequences[:3] == [1, "1.5", "2"]
    assert set(map(str, sequences[3:])) == {"None", "1-2", ""}


@pytest.mark.asyncio
async def test_co_authored_books_are_listed_under_each_real_author():
    """A combined authorName ("Ann & Bob") must not become a fake author."""
    items = {
        "results": [
            {
                "id": "book-1",
                "media": {
                    "ebookFormat": "epub",
                    "metadata": {
                        "authorName": "Ann & Bob",
                        "authors": [
                            {"id": "author-ann", "name": "Ann"},
                            {"id": "author-bob", "name": "Bob"},
                        ],
                    },
                },
            },
            {
                "id": "book-2",
                "media": {
                    "ebookFormat": "epub",
                    "metadata": {
                        "authorName": "Ann",
                        "authors": [{"id": "author-ann", "name": "Ann"}],
                    },
                },
            },
        ]
    }
    authors = {
        "authors": [
            {"id": "author-ann", "name": "Ann", "imagePath": "ann.jpg"},
            {"id": "author-bob", "name": "Bob", "imagePath": "bob.jpg"},
        ]
    }

    async def fake_fetch(endpoint, params=None, username=None, token=None):
        if endpoint.endswith("/authors"):
            return authors
        return items

    result = await get_cached_author_details(
        fake_fetch,
        lambda data: data.get("results", []),
        "reader",
        "library-coauthored",
        token="token-coauthored",
        bypass_cache=True,
    )

    by_name = {author["name"]: author for author in result}

    assert set(by_name) == {"Ann", "Bob"}
    assert by_name["Ann"]["ebook_count"] == 2
    assert by_name["Bob"]["ebook_count"] == 1
    assert by_name["Ann"]["id"] == "author-ann"


def test_author_filter_matches_co_authored_items():
    """Filtering by author also finds books with a combined authorName."""
    item = {
        "media": {
            "metadata": {
                "authorName": "Ann & Bob",
                "authors": [
                    {"id": "author-ann", "name": "Ann"},
                    {"id": "author-bob", "name": "Bob"},
                ],
            }
        }
    }

    assert AuthorFeedGenerator._item_matches_author(item, "author-bob", "Bob")
    assert AuthorFeedGenerator._item_matches_author(item, "author-ann", "Ann")
    assert not AuthorFeedGenerator._item_matches_author(item, "author-cy", "Cy")
