"""Authentication utilities for the OPDS-ABS application.

OPDS clients authenticate with HTTP Basic. The credentials are checked against
Audiobookshelf and the resulting ABS token is used for every upstream API call
made on that client's behalf.

Supported credentials:

- ``Authorization: Basic base64(username:password)``: primary method.
- ``Authorization: Basic base64(username:apikey)``: when ``API_KEY_AUTH_ENABLED``
  is on, a secret that is not a valid password is retried as an ABS API key.
- ``Authorization: Bearer <apikey>``: when ``API_KEY_AUTH_ENABLED`` is on.
- ``?token=<apikey>``: when ``API_KEY_AUTH_ENABLED`` is on, for clients that
  cannot send headers. This server never emits tokens in links itself.

Security invariants
-------------------
- The token cache is keyed by a hash of the credential the caller presented, not
  by username. A cache hit therefore proves that the same secret that ABS
  accepted is being presented again. Keying by username alone meant that any
  password (and any book download) was accepted for a user with a cached token.
- A request without credentials never falls back to "the token of the user in
  the URL". With ``AUTH_ENABLED`` such a request gets a 401 challenge.
- ABS tokens are never written to the on-disk cache. The token cache is memory
  only; a restart costs one ``/login`` per client.
- Secrets, tokens and upstream response bodies are never logged.
"""
import asyncio
import base64
import hashlib
import logging
import time
from typing import Dict, Optional, Tuple

import aiohttp
from fastapi import HTTPException, Request

from opds_abs.config import (
    API_KEY_AUTH_ENABLED,
    AUDIOBOOKSHELF_INTERNAL_URL,
    AUTH_CACHE_EXPIRY,
    AUTH_ENABLED,
    AUTH_TOKEN_CACHING,
)
from opds_abs.utils.error_utils import AuthenticationError

logger = logging.getLogger(__name__)

CHALLENGE_HEADERS = {"WWW-Authenticate": 'Basic realm="OPDS-ABS", charset="UTF-8"'}

# Timeout for authentication probes. Kept short so a dead server fails fast.
_AUTH_TIMEOUT = aiohttp.ClientTimeout(total=10)

# Cache of credential fingerprints: fingerprint -> (token, display_name, expires_at, username)
TOKEN_CACHE: Dict[str, Tuple[str, str, float, str]] = {}

# Admin lookups: token -> (is_admin, expires_at)
_ADMIN_CACHE: Dict[str, Tuple[bool, float]] = {}
_ADMIN_CACHE_TTL = 300

# Per-fingerprint locks so a burst of requests from one reader performs a single
# upstream login instead of one per request.
_LOGIN_LOCKS: Dict[str, asyncio.Lock] = {}


class AbsUnavailableError(AuthenticationError):
    """Audiobookshelf could not be reached while checking credentials."""


def _fingerprint(username: str, secret: str) -> str:
    """Hash everything the caller presented.

    Args:
        username: Username from the request (may be a placeholder for API keys).
        secret: Password or API key from the request.

    Returns:
        str: Hex digest used as the token cache key.
    """
    raw = f"{username}\0{secret}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _cached_token(fingerprint: str) -> Optional[Tuple[str, str]]:
    """Return a cached (token, display_name) if it is still valid.

    Args:
        fingerprint: Cache key built from the presented credentials.

    Returns:
        Optional[Tuple[str, str]]: Cached identity, or None.
    """
    if not AUTH_TOKEN_CACHING:
        return None

    entry = TOKEN_CACHE.get(fingerprint)
    if entry is None:
        return None

    token, display_name, expires_at, _username = entry
    if time.time() >= expires_at:
        TOKEN_CACHE.pop(fingerprint, None)
        return None

    return token, display_name


def _cache_token(fingerprint: str, username: str, token: str, display_name: str) -> None:
    """Remember a token for the exact credentials that produced it.

    Args:
        fingerprint: Cache key built from the presented credentials.
        username: Username reported by Audiobookshelf.
        token: Audiobookshelf token or API key.
        display_name: Display name reported by Audiobookshelf.
    """
    if not AUTH_TOKEN_CACHING:
        return

    TOKEN_CACHE[fingerprint] = (
        token,
        display_name,
        time.time() + AUTH_CACHE_EXPIRY,
        username,
    )


def invalidate_token(token: str = None, username: str = None) -> None:
    """Drop cached tokens by token value or by username.

    Args:
        token: Remove every cache entry holding this token (upstream rejected it).
        username: Remove every cache entry belonging to this user.
    """
    if token:
        for key in [k for k, v in TOKEN_CACHE.items() if v[0] == token]:
            TOKEN_CACHE.pop(key, None)
    if username:
        for key in [k for k, v in TOKEN_CACHE.items() if v[3] == username]:
            TOKEN_CACHE.pop(key, None)


def clear_token_cache() -> None:
    """Forget every cached token."""
    TOKEN_CACHE.clear()
    _ADMIN_CACHE.clear()


async def _abs_get_current_user(session: aiohttp.ClientSession, token: str) -> Optional[dict]:
    """Fetch the Audiobookshelf user behind a token.

    ``GET /api/me`` returns the user object itself; some deployments wrap it in
    ``{"user": ...}``. Both shapes are accepted.

    Args:
        session: Reusable aiohttp session.
        token: ABS token or API key.

    Returns:
        Optional[dict]: The user object, or None when ABS rejects the token.

    Raises:
        AbsUnavailableError: ABS answered with an unexpected status.
    """
    async with session.get(
        f"{AUDIOBOOKSHELF_INTERNAL_URL}/api/me",
        headers={"Authorization": f"Bearer {token}"},
    ) as response:
        if response.status in (401, 403):
            return None
        if response.status != 200:
            raise AbsUnavailableError(
                f"Audiobookshelf /api/me returned HTTP {response.status}"
            )
        data = await response.json()

    user = data.get("user") if isinstance(data, dict) else None
    if not isinstance(user, dict):
        user = data if isinstance(data, dict) else None
    return user


async def authenticate_with_api_key(username: str, api_key: str) -> Tuple[str, str]:
    """Authenticate against Audiobookshelf using an API key.

    Audiobookshelf API keys are JWTs with ``type: api`` and are accepted by the
    same bearer strategy as session tokens, so ``GET /api/me`` is the probe.

    Args:
        username: Username associated with the API key, or ``api_key_user``.
        api_key: API key to authenticate with.

    Returns:
        Tuple[str, str]: (token, display_name)

    Raises:
        AuthenticationError: If the API key is rejected.
        AbsUnavailableError: If Audiobookshelf cannot be reached.
    """
    logger.debug("Authenticating with API key for user: %s", username or "api_key_user")

    try:
        async with aiohttp.ClientSession(timeout=_AUTH_TIMEOUT) as session:
            user = await _abs_get_current_user(session, api_key)
    except AbsUnavailableError:
        raise
    except aiohttp.ClientConnectorError as conn_error:
        logger.error(
            "Cannot connect to Audiobookshelf server at %s",
            AUDIOBOOKSHELF_INTERNAL_URL,
        )
        raise AbsUnavailableError(
            "Error connecting to Audiobookshelf: cannot reach the server"
        ) from conn_error
    except aiohttp.ClientError as client_error:
        logger.error("API key authentication error: %s", type(client_error).__name__)
        raise AbsUnavailableError(
            "Error connecting to Audiobookshelf"
        ) from client_error

    if not user or not user.get("username"):
        raise AuthenticationError("API key authentication failed: invalid or expired key")

    actual_username = user["username"]
    if username and username not in ("api_key_user", actual_username):
        logger.warning(
            "API key belongs to user '%s', not '%s'", actual_username, username
        )

    logger.info("API key authentication successful for user: %s", actual_username)
    return api_key, actual_username


async def authenticate_with_audiobookshelf(username: str, password: str) -> Tuple[str, str]:
    """Authenticate with Audiobookshelf using a username and password.

    Args:
        username: Username to authenticate with.
        password: Password to authenticate with.

    Returns:
        Tuple[str, str]: (token, display_name)

    Raises:
        AuthenticationError: If the credentials are rejected.
        AbsUnavailableError: If Audiobookshelf cannot be reached or is unhealthy.
    """
    logger.debug("Authentication attempt for %s with password", username)

    login_url = f"{AUDIOBOOKSHELF_INTERNAL_URL}/login"

    try:
        async with aiohttp.ClientSession(timeout=_AUTH_TIMEOUT) as session:
            async with session.post(
                login_url,
                json={"username": username, "password": password},
                headers={"Content-Type": "application/json"},
            ) as response:
                if response.status in (401, 403):
                    logger.warning("Authentication failed for user %s", username)
                    raise AuthenticationError("Invalid username or password")
                if response.status != 200:
                    # 429 (login rate limit) or 5xx: the password was never judged,
                    # so do not tell the reader their password is wrong.
                    raise AbsUnavailableError(
                        f"Audiobookshelf /login returned HTTP {response.status}"
                    )

                data = await response.json()

        user_data = data.get("user") if isinstance(data, dict) else None
        if not isinstance(user_data, dict):
            raise AuthenticationError("Invalid response from Audiobookshelf")

        token = user_data.get("token") or user_data.get("accessToken")
        display_name = user_data.get("username") or username

        if not token:
            raise AuthenticationError("No token returned from Audiobookshelf")

        return token, display_name

    except (AuthenticationError, AbsUnavailableError):
        raise
    except aiohttp.ClientConnectorError as conn_error:
        logger.error(
            "Cannot connect to Audiobookshelf server at %s",
            AUDIOBOOKSHELF_INTERNAL_URL,
        )
        raise AbsUnavailableError(
            "Error connecting to Audiobookshelf: cannot reach the server"
        ) from conn_error
    except aiohttp.ClientError as client_error:
        logger.error("Authentication error for %s: %s", username, type(client_error).__name__)
        raise AbsUnavailableError("Error connecting to Audiobookshelf") from client_error


def get_credentials_from_request(
    request: Request,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract credentials from the Authorization header or ``token`` query.

    Args:
        request: The incoming request.

    Returns:
        Tuple[Optional[str], Optional[str], Optional[str]]: (username, password, api_key),
        with None for the parts that were not supplied.
    """
    token_param = request.query_params.get("token")
    if token_param and API_KEY_AUTH_ENABLED:
        # API keys are self-identifying; Audiobookshelf tells us the owner.
        return "api_key_user", None, token_param

    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None, None, None

    scheme, _, value = auth_header.partition(" ")
    scheme = scheme.lower()
    value = value.strip()

    if scheme == "basic" and value:
        try:
            decoded = base64.b64decode(value, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            logger.warning("Malformed Basic Authorization header")
            return None, None, None

        username, separator, secret = decoded.partition(":")
        if not separator or not username or not secret:
            logger.warning("Basic Authorization header is not username:password")
            return None, None, None

        if len(secret) >= 32 and not API_KEY_AUTH_ENABLED:
            logger.warning(
                "Credential for %s looks like an API key but API_KEY_AUTH_ENABLED is false",
                username,
            )

        return username, secret, None

    if scheme == "bearer" and value:
        if not API_KEY_AUTH_ENABLED:
            logger.warning("Bearer credentials rejected: API_KEY_AUTH_ENABLED is false")
            return None, None, None
        return "api_key_user", None, value

    if auth_header:
        # Do not log the header itself: "Bearerabc123" without a space is one token.
        logger.warning(
            "Unsupported or malformed Authorization header (%d chars)", len(auth_header)
        )

    return None, None, None


async def get_user_token(
    username: str, password: str = None, api_key: str = None
) -> Tuple[str, str]:
    """Resolve credentials to an ABS token, using the cache when possible.

    Args:
        username: Username from the request.
        password: Password from the request, if any.
        api_key: API key from the request, if any.

    Returns:
        Tuple[str, str]: (token, display_name)

    Raises:
        AuthenticationError: If authentication fails.
    """
    secret = api_key or password
    if not secret:
        raise AuthenticationError("No valid authentication credentials provided")

    fingerprint = _fingerprint(username, secret)

    cached = _cached_token(fingerprint)
    if cached is not None:
        logger.debug("Using cached token for user %s", username)
        return cached

    # One upstream login per credential set, even under a burst of requests.
    lock = _LOGIN_LOCKS.setdefault(fingerprint, asyncio.Lock())
    try:
        async with lock:
            cached = _cached_token(fingerprint)
            if cached is not None:
                return cached

            if api_key and API_KEY_AUTH_ENABLED:
                token, display_name = await authenticate_with_api_key(username, api_key)
            else:
                token, display_name = await authenticate_with_audiobookshelf(
                    username, password
                )

            _cache_token(fingerprint, display_name, token, display_name)
            return token, display_name
    finally:
        # Waiters hold their own reference; dropping ours keeps the dict from
        # growing with every distinct (e.g. mistyped) secret ever tried.
        _LOGIN_LOCKS.pop(fingerprint, None)


async def verify_credentials(
    request: Request,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Verify the credentials in the request.

    Args:
        request: The incoming request.

    Returns:
        Tuple[Optional[str], Optional[str], Optional[str]]: (username, token, display_name)
        or (None, None, None) when the request carries no credentials.

    Raises:
        AuthenticationError: If credentials were supplied but rejected.
    """
    if not AUTH_ENABLED:
        logger.debug("Authentication is disabled, skipping credential verification")
        return None, None, None

    username, password, api_key = get_credentials_from_request(request)

    if api_key and not API_KEY_AUTH_ENABLED:
        raise AuthenticationError(
            "API key authentication is disabled. Use username/password or enable "
            "API_KEY_AUTH_ENABLED."
        )

    if api_key and API_KEY_AUTH_ENABLED:
        token, display_name = await get_user_token(username, None, api_key)
        if username == "api_key_user":
            username = display_name
        return username, token, display_name

    if username and password:
        # A long secret may be an API key sent as a Basic password. Try that
        # first, then fall back to a real password check.
        if API_KEY_AUTH_ENABLED and len(password) >= 32:
            try:
                token, display_name = await get_user_token(username, None, password)
                return username, token, display_name
            except AuthenticationError as api_key_error:
                logger.debug(
                    "Credential for %s is not a valid API key, trying as password: %s",
                    username,
                    api_key_error,
                )

        token, display_name = await get_user_token(username, password)
        return username, token, display_name

    logger.debug("No credentials found in request")
    return None, None, None


async def get_authenticated_user(
    request: Request,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Dependency returning the authenticated user.

    With ``AUTH_ENABLED`` a request without credentials is rejected with a 401
    challenge instead of being served from a cached token.

    Args:
        request: The incoming request.

    Returns:
        Tuple[Optional[str], Optional[str], Optional[str]]: (username, token, display_name)

    Raises:
        HTTPException: 401 when unauthenticated, 503 when ABS is unavailable.
    """
    if not AUTH_ENABLED:
        return None, None, None

    try:
        username, token, display_name = await verify_credentials(request)

        if username and token:
            return username, token, display_name

        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers=CHALLENGE_HEADERS,
        )

    except AbsUnavailableError as e:
        logger.error("Audiobookshelf unavailable: %s", str(e))
        raise HTTPException(
            status_code=503,
            detail=f"Audiobookshelf server is unavailable: {str(e)}",
        ) from e
    except AuthenticationError as e:
        raise HTTPException(
            status_code=401,
            detail=str(e),
            headers=CHALLENGE_HEADERS,
        ) from e


async def require_auth(request: Request) -> Tuple[str, str, str]:
    """Dependency that requires a valid user.

    Args:
        request: The incoming request.

    Returns:
        Tuple[str, str, str]: (username, token, display_name)

    Raises:
        HTTPException: If authentication fails or no credentials were provided.
    """
    username, token, display_name = await get_authenticated_user(request)

    if not username or not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers=CHALLENGE_HEADERS,
        )

    return username, token, display_name


async def is_admin(token: str) -> bool:
    """Check whether an ABS token belongs to an administrator.

    Args:
        token: ABS token or API key.

    Returns:
        bool: True when Audiobookshelf reports the user as an admin.
    """
    cached = _ADMIN_CACHE.get(token)
    if cached is not None and time.time() < cached[1]:
        return cached[0]

    is_admin_user = False
    try:
        async with aiohttp.ClientSession(timeout=_AUTH_TIMEOUT) as session:
            user = await _abs_get_current_user(session, token)
        if user:
            is_admin_user = bool(
                user.get("isAdmin") or user.get("type") == "admin"
            )
    except (AuthenticationError, aiohttp.ClientError) as e:
        logger.warning("Could not verify administrator status: %s", type(e).__name__)
        is_admin_user = False

    _ADMIN_CACHE[token] = (is_admin_user, time.time() + _ADMIN_CACHE_TTL)
    return is_admin_user


async def require_admin(request: Request) -> Tuple[str, str, str]:
    """Dependency that requires an Audiobookshelf administrator.

    Args:
        request: The incoming request.

    Returns:
        Tuple[str, str, str]: (username, token, display_name)

    Raises:
        HTTPException: 401 when unauthenticated, 403 when not an admin.
    """
    username, token, display_name = await require_auth(request)

    if not await is_admin(token):
        raise HTTPException(
            status_code=403,
            detail="Administrator access required",
        )

    return username, token, display_name
