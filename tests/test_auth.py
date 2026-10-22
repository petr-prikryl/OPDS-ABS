"""Tests for the authentication layer.

The security bugs in issue #49 are the important ones here: a token cached for
one secret must never satisfy a request that presents a different secret, and a
request without credentials must be challenged.
"""
import base64

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from opds_abs.utils import auth_utils
from opds_abs.utils.error_utils import AuthenticationError


def make_request(headers=None, query_string=b"") -> Request:
    """Build a minimal Starlette request.

    Args:
        headers: Mapping of header name to value.
        query_string: Raw query string bytes.

    Returns:
        Request: A request usable by the credential helpers.
    """
    raw_headers = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": raw_headers,
            "query_string": query_string,
        }
    )


def basic(username: str, secret: str) -> str:
    """Build a Basic Authorization header value."""
    encoded = base64.b64encode(f"{username}:{secret}".encode()).decode()
    return f"Basic {encoded}"


@pytest.fixture(autouse=True)
def clean_caches():
    """Keep tests independent of each other."""
    auth_utils.clear_token_cache()
    yield
    auth_utils.clear_token_cache()


def test_fingerprint_depends_on_secret():
    """Different secrets must produce different cache keys."""
    assert auth_utils._fingerprint("u", "a") != auth_utils._fingerprint("u", "b")
    assert auth_utils._fingerprint("u", "a") == auth_utils._fingerprint("u", "a")


def test_cached_token_is_not_returned_for_another_secret():
    """A cache entry may only be used for the exact secret that created it."""
    right = auth_utils._fingerprint("u", "right-password")
    wrong = auth_utils._fingerprint("u", "wrong-password")

    auth_utils._cache_token(right, "u", "tok", "u")

    assert auth_utils._cached_token(right) == ("tok", "u")
    assert auth_utils._cached_token(wrong) is None


@pytest.mark.asyncio
async def test_wrong_password_does_not_use_cached_token(monkeypatch):
    """A wrong password must reach Audiobookshelf instead of the cache."""
    calls = []

    async def fake_auth(username, password):
        calls.append((username, password))
        raise AuthenticationError("Invalid username or password")

    monkeypatch.setattr(auth_utils, "authenticate_with_audiobookshelf", fake_auth)

    # Prime the cache with a successful login for the real password.
    auth_utils._cache_token(
        auth_utils._fingerprint("reader", "correct"), "reader", "abs-token", "reader"
    )

    with pytest.raises(AuthenticationError):
        await auth_utils.get_user_token("reader", "wrong")

    assert calls == [("reader", "wrong")]


@pytest.mark.asyncio
async def test_credentials_are_cached_per_secret(monkeypatch):
    """The same credentials are only verified upstream once."""
    calls = []

    async def fake_auth(username, password):
        calls.append((username, password))
        return "abs-token", username

    monkeypatch.setattr(auth_utils, "authenticate_with_audiobookshelf", fake_auth)

    first = await auth_utils.get_user_token("reader", "secret")
    second = await auth_utils.get_user_token("reader", "secret")

    assert first == second == ("abs-token", "reader")
    assert calls == [("reader", "secret")]


def test_basic_credentials_are_parsed():
    """Basic auth yields username and password."""
    request = make_request({"Authorization": basic("reader", "s3cret")})
    assert auth_utils.get_credentials_from_request(request) == ("reader", "s3cret", None)


def test_bearer_credentials_are_parsed_as_api_key():
    """Bearer auth yields an API key, with a placeholder username."""
    request = make_request({"Authorization": "Bearer abc123"})
    assert auth_utils.get_credentials_from_request(request) == (
        "api_key_user",
        None,
        "abc123",
    )


def test_query_token_is_parsed_as_api_key():
    """The query token fallback stays available for legacy clients."""
    request = make_request(query_string=b"token=abc123")
    assert auth_utils.get_credentials_from_request(request) == (
        "api_key_user",
        None,
        "abc123",
    )


def test_malformed_basic_header_is_ignored():
    """A header without a colon is not treated as credentials."""
    request = make_request({"Authorization": "Basic " + base64.b64encode(b"reader").decode()})
    assert auth_utils.get_credentials_from_request(request) == (None, None, None)


@pytest.mark.asyncio
async def test_request_without_credentials_gets_401():
    """Anonymous requests are challenged instead of being served a cached token."""
    with pytest.raises(HTTPException) as excinfo:
        await auth_utils.get_authenticated_user(make_request())

    assert excinfo.value.status_code == 401
    assert "Basic" in excinfo.value.headers["WWW-Authenticate"]


@pytest.mark.asyncio
async def test_api_key_login_reads_me_payload(monkeypatch):
    """GET /api/me returns the user object directly (ABS >= 2.x)."""

    class FakeResponse:
        status = 200

        async def json(self):
            return {"id": "user-1", "username": "reader", "type": "admin"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def get(self, url, headers=None):
            assert headers["Authorization"] == "Bearer api-key"
            return FakeResponse()

    monkeypatch.setattr(auth_utils.aiohttp, "ClientSession", FakeSession)

    token, display_name = await auth_utils.authenticate_with_api_key(
        "api_key_user", "api-key"
    )

    assert token == "api-key"
    assert display_name == "reader"
