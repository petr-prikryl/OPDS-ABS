"""End-to-end tests through the real routes against a fake Audiobookshelf."""
import base64

import pytest
from fastapi.testclient import TestClient
from lxml import etree

from opds_abs.main import app


def basic(password: str) -> dict:
    """Build Basic auth headers for the test user."""
    token = base64.b64encode(f"reader:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def client():
    """TestClient with the real authentication flow."""
    with TestClient(app) as test_client:
        yield test_client


def test_items_feed_is_paginated_and_token_free(client):
    """A normal catalog request works and never leaks the ABS token."""
    response = client.get("/opds/reader/libraries/lib1/items", headers=basic("secret"))

    assert response.status_code == 200
    assert "Book One" in response.text
    assert "token=" not in response.text
    assert "start_index=2" in response.text


def test_anonymous_request_is_challenged(client):
    """No credentials must never be served from a cached session."""
    response = client.get("/opds/reader/libraries/lib1/items")

    assert response.status_code == 401
    assert "Basic" in response.headers["www-authenticate"]


def test_wrong_password_is_rejected_even_after_success(client):
    """A cached token for the right password must not accept a wrong one."""
    assert client.get("/opds/reader/libraries/lib1/items", headers=basic("secret")).status_code == 200

    response = client.get("/opds/reader/libraries/lib1/items", headers=basic("wrong"))

    assert response.status_code == 401


def test_authors_are_paginated_and_co_authors_split(client):
    """Authors paginate past page 1 and no combined author is invented."""
    page_one = client.get("/opds/reader/libraries/lib1/authors", headers=basic("secret"))
    page_two = client.get(
        "/opds/reader/libraries/lib1/authors?page=2", headers=basic("secret")
    )

    assert page_one.status_code == 200
    assert "page=2" in page_one.text
    assert "Ann &amp; Bob" not in page_one.text + page_two.text
    assert "Bob" in page_two.text


def test_author_items_page_two(client):
    """The page query parameter is honoured for author feeds."""
    response = client.get(
        "/opds/reader/libraries/lib1/authors/author-ann?page=2", headers=basic("secret")
    )

    assert response.status_code == 200
    assert "Book Two" in response.text
    assert "Book One" not in response.text


def test_series_with_unnumbered_book(client):
    """An unnumbered book in a series no longer produces a 500."""
    response = client.get(
        "/opds/reader/libraries/lib1/series/series-1", headers=basic("secret")
    )

    assert response.status_code == 200
    assert "Book One" in response.text
    assert "Book Two" in response.text


def test_search_description(client):
    """The OpenSearch document is well-formed and uses an absolute template."""
    response = client.get(
        "/opds/reader/libraries/lib1/search.xml", headers=basic("secret")
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/opensearchdescription+xml"
    )

    root = etree.fromstring(response.content)
    template = root.find("{http://a9.com/-/spec/opensearch/1.1/}Url").get("template")
    assert template.startswith("http://testserver/opds/reader/libraries/lib1/search?q=")


def test_admin_endpoints_require_an_abs_admin(client):
    """Cache administration is not available to ordinary users."""
    assert client.get("/admin/cache/stats", headers=basic("secret")).status_code == 403
    assert client.get("/admin/cache/stats", headers=basic("admin")).status_code == 200
