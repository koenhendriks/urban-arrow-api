"""Auth0 login for the Pon Connected backend.

The tenant has the password grant disabled for the app's client, so login is the
same Authorization Code + PKCE flow the app uses. The redirect goes to the app's
custom ``urbanarrow://`` scheme, which a desktop browser cannot open: the user
copies that final URL (or just its ``code``) back to us. After that the refresh
token keeps the session alive without user interaction.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import inspect
import secrets
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp

from .const import (
    AUTH0_AUDIENCE,
    AUTH0_CLIENT_ID,
    AUTH0_DOMAIN,
    AUTH0_REDIRECT_URI,
    AUTH0_SCOPE,
)
from .exceptions import UrbanArrowAuthError, UrbanArrowConnectionError

TOKEN_URL = f"https://{AUTH0_DOMAIN}/oauth/token"
AUTHORIZE_URL = f"https://{AUTH0_DOMAIN}/authorize"
# Refresh a little before expiry so a request never races the deadline.
EXPIRY_MARGIN_SECONDS = 60


@dataclass(slots=True)
class Token:
    access_token: str
    refresh_token: str
    expires_at: float
    id_token: str | None = None

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at - EXPIRY_MARGIN_SECONDS

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Token:
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=float(data["expires_at"]),
            id_token=data.get("id_token"),
        )


@dataclass(slots=True)
class LoginRequest:
    url: str
    code_verifier: str
    state: str


def create_login_request(*, signup: bool = False, locale: str | None = None) -> LoginRequest:
    code_verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    state = secrets.token_urlsafe(16)
    params = {
        "response_type": "code",
        "client_id": AUTH0_CLIENT_ID,
        "redirect_uri": AUTH0_REDIRECT_URI,
        "audience": AUTH0_AUDIENCE,
        "scope": AUTH0_SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "prompt": "login",
    }
    if signup:
        params["screen_hint"] = "signup"
    if locale:
        params["ui_locales"] = locale
    return LoginRequest(f"{AUTHORIZE_URL}?{urlencode(params)}", code_verifier, state)


def extract_code(redirect: str, expected_state: str | None = None) -> str:
    """Accept either the full ``urbanarrow://...callback?code=...`` URL or a bare code."""
    redirect = redirect.strip()
    if "://" not in redirect and "?" not in redirect:
        return redirect
    query = parse_qs(urlparse(redirect).query)
    if "error" in query:
        raise UrbanArrowAuthError(
            query.get("error_description", query["error"])[0]
        )
    if expected_state is not None and query.get("state", [None])[0] != expected_state:
        raise UrbanArrowAuthError("State mismatch in redirect URL")
    try:
        return query["code"][0]
    except KeyError as err:
        raise UrbanArrowAuthError("No authorization code in redirect URL") from err


async def _token_request(session: aiohttp.ClientSession, payload: dict[str, str]) -> dict[str, Any]:
    try:
        async with session.post(TOKEN_URL, json=payload) as resp:
            data = await resp.json(content_type=None)
            if resp.status in (400, 401, 403):
                raise UrbanArrowAuthError(
                    data.get("error_description") or data.get("error") or str(resp.status)
                )
            resp.raise_for_status()
            return data
    except aiohttp.ClientError as err:
        raise UrbanArrowConnectionError(str(err)) from err


def _token_from_response(data: dict[str, Any], previous_refresh: str | None = None) -> Token:
    refresh = data.get("refresh_token") or previous_refresh
    if not refresh:
        raise UrbanArrowAuthError("Auth0 did not return a refresh token")
    return Token(
        access_token=data["access_token"],
        # Auth0 only returns a new refresh token when rotation is enabled.
        refresh_token=refresh,
        expires_at=time.time() + int(data.get("expires_in", 3600)),
        id_token=data.get("id_token"),
    )


async def exchange_code(
    session: aiohttp.ClientSession, code: str, code_verifier: str
) -> Token:
    data = await _token_request(
        session,
        {
            "grant_type": "authorization_code",
            "client_id": AUTH0_CLIENT_ID,
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": AUTH0_REDIRECT_URI,
        },
    )
    return _token_from_response(data)


async def refresh_token(session: aiohttp.ClientSession, token: Token) -> Token:
    data = await _token_request(
        session,
        {
            "grant_type": "refresh_token",
            "client_id": AUTH0_CLIENT_ID,
            "refresh_token": token.refresh_token,
        },
    )
    return _token_from_response(data, token.refresh_token)


TokenUpdateCallback = Callable[[Token], Awaitable[None] | None]


class AbstractAuth(ABC):
    """Supplies access tokens to the client.

    The client never stores or refreshes tokens itself; subclass this to control
    where tokens live and how they are renewed (e.g. persisted in a config entry).
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.session = session

    @abstractmethod
    async def async_get_access_token(self, *, force_refresh: bool = False) -> str:
        """Return a valid access token; ``force_refresh`` is set after a 401."""


class TokenAuth(AbstractAuth):
    """Holds a ``Token`` and refreshes it through Auth0 when it expires.

    ``on_token_update`` fires after every refresh; persist the token there,
    because Auth0 may rotate the refresh token and invalidate the old one.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: Token,
        on_token_update: TokenUpdateCallback | None = None,
    ) -> None:
        super().__init__(session)
        self._token = token
        self._on_token_update = on_token_update
        self._lock = asyncio.Lock()

    @property
    def token(self) -> Token:
        return self._token

    async def async_refresh_token(self, token: Token) -> Token:
        """Override to add a fallback, e.g. a fresh login when the refresh token is revoked."""
        return await refresh_token(self.session, token)

    async def async_get_access_token(self, *, force_refresh: bool = False) -> str:
        async with self._lock:
            if force_refresh or self._token.expired:
                self._token = await self.async_refresh_token(self._token)
                if self._on_token_update:
                    result = self._on_token_update(self._token)
                    if inspect.isawaitable(result):
                        await result
            return self._token.access_token
