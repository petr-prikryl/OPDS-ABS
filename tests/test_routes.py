"""Route-level tests: search description and download proxy."""
import pytest
from fastapi.testclient import TestClient
from lxml import etree

import aiohttp

from opds_abs.main import app, _download_headers, _header_value_safe
from opds_abs.utils.auth_utils import get_authenticated_user


@pytest.fixture
def client():
    """TestClient with an authenticated user and a clean dependency override."""
    app.dependency_overrides[get_authenticated_user] = lambda: (
        "reader",
        "SECRET-TOKEN",
        "reader",
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_search_description_is_valid_xml(client):
    """search.xml must be well-formed XML, not HTML (issue #49)."""
    response = client.get("/opds/reader/libraries/lib-1/search.xml")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/opensearchdescription+xml"
    )

    root = etree.fromstring(response.content)
    namespace = {"os": "http://a9.com/-/spec/opensearch/1.1/"}
    template = root.find("os:Url", namespace).get("template")

    assert template.startswith("http://testserver/opds/reader/libraries/lib-1/search?q=")
    assert "SECRET-TOKEN" not in response.text
    assert "&amp;" not in response.text


def test_header_value_helper():
    """Only ASCII header values are considered safe."""
    assert _header_value_safe('attachment; filename="book.epub"')
    assert not _header_value_safe('attachment; filename="Kugeln des Bösen.epub"')
    assert not _header_value_safe('attachment; filename="Kugeln des B\udcf6sen.epub"')


def test_download_headers_replace_unsafe_disposition():
    """A UTF-8 Content-Disposition is dropped instead of breaking the response."""
    headers = _download_headers(
        {
            "Content-Type": "application/epub+zip",
            "Content-Length": "42",
            "Content-Disposition": 'attachment; filename="Kugeln des Bösen.epub"',
        }
    )

    assert headers["Content-Type"] == "application/epub+zip"
    assert headers["Content-Length"] == "42"
    assert "Content-Disposition" not in headers


class FakeContent:
    """Async iterator over a fixed body."""

    def __init__(self, body: bytes):
        self.body = body

    async def iter_any(self):
        yield self.body


class FakeResponse:
    """Minimal aiohttp response double."""

    def __init__(self, status, headers=None, body=b""):
        self.status = status
        self.headers = headers or {}
        self.content = FakeContent(body)
        self.released = False

    def release(self):
        self.released = True


class FakeSession:
    """Minimal aiohttp session double returning one prepared response."""

    response = None
    last_headers = None

    def __init__(self, *args, **kwargs):
        pass

    async def get(self, url, headers=None):
        FakeSession.last_headers = headers
        return FakeSession.response

    async def close(self):
        pass


def test_download_returns_404_for_missing_upstream_file(client, monkeypatch):
    """A missing upstream file is a 404, not an empty 200."""
    FakeSession.response = FakeResponse(404)
    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)

    response = client.get("/opds/proxy/download/item-1/file/123")

    assert response.status_code == 404


def test_download_streams_file_with_ascii_fallback_name(client, monkeypatch):
    """A file with an umlaut downloads instead of raising a 500 (issue #45)."""
    body = b"epub-bytes"
    FakeSession.response = FakeResponse(
        200,
        headers={
            "Content-Type": "application/epub+zip",
            "Content-Length": str(len(body)),
            "Content-Disposition": 'attachment; filename="Kugeln des Bösen.epub"',
        },
        body=body,
    )
    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)

    response = client.get("/opds/proxy/download/item-1/file/123")

    assert response.status_code == 200
    assert response.content == body
    assert response.headers["content-disposition"] == (
        'attachment; filename="book-item-1.epub"'
    )
    assert FakeSession.last_headers["Authorization"] == "Bearer SECRET-TOKEN"
