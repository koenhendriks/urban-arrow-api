"""Headless username/password login through Auth0 Universal Login.

The password grant is disabled for the app's client, so we drive the hosted login
pages the way a browser without JavaScript would: identifier form, password form,
then follow redirects until Auth0 sends us to the app's ``urbanarrow://`` callback
carrying the authorization code. This depends on Auth0's page markup and breaks if
the tenant turns on bot detection (captcha) or MFA; those cases raise distinct
errors so callers can fall back to the manual browser flow.
"""

from __future__ import annotations

import html
import re
from urllib.parse import urljoin

import aiohttp

from .auth import Token, create_login_request, exchange_code, extract_code
from .const import AUTH0_DOMAIN, AUTH0_REDIRECT_URI
from .exceptions import (
    UrbanArrowAuthError,
    UrbanArrowCaptchaRequired,
    UrbanArrowConnectionError,
    UrbanArrowMfaRequired,
)

LOGIN_BASE = f"https://{AUTH0_DOMAIN}"
MAX_REDIRECTS = 10
# Auth0 adapts the page to these hints; claiming JS keeps us on the standard form.
BROWSER_HINTS = {
    "js-available": "true",
    "webauthn-available": "false",
    "webauthn-platform-available": "false",
    "is-brave": "false",
}
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"
)

_STATE_RE = re.compile(r'<input[^>]*name="state"[^>]*value="([^"]+)"')
_ERROR_RE = re.compile(r'id="error-element-[\w-]+"[^>]*>(.*?)</', re.S)
# Match a real widget element, not the selector strings in Auth0's inline JS.
_CAPTCHA_RE = re.compile(r'<[a-z]+\b[^>]*\bdata-captcha-sitekey="[^"]+"')
_PROMPT_ALERT_RE = re.compile(r'id="prompt-alert"[^>]*>.*?<p[^>]*>(.*?)</p>', re.S)


def _form_state(page: str) -> str:
    match = _STATE_RE.search(page)
    if not match:
        raise UrbanArrowAuthError("Unexpected login page: no state field")
    return html.unescape(match.group(1))


def _page_error(page: str) -> str | None:
    match = _ERROR_RE.search(page) or _PROMPT_ALERT_RE.search(page)
    if not match:
        return None
    return html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip() or None


def _check_blockers(url: str, page: str) -> None:
    if _CAPTCHA_RE.search(page):
        raise UrbanArrowCaptchaRequired("Auth0 requires a captcha; use the browser login")
    if "/u/mfa" in url:
        raise UrbanArrowMfaRequired("Account has MFA enabled; use the browser login")


async def _follow(
    session: aiohttp.ClientSession, resp: aiohttp.ClientResponse
) -> tuple[str | None, str, str]:
    """Follow redirects by hand so we can stop at the custom-scheme callback.

    Returns ``(callback_url, last_page_url, last_page_body)``.
    """
    for _ in range(MAX_REDIRECTS):
        location = resp.headers.get("Location")
        if resp.status not in (301, 302, 303, 307) or not location:
            return None, str(resp.url), await resp.text()
        if location.startswith(AUTH0_REDIRECT_URI.split("://")[0] + "://"):
            return location, str(resp.url), ""
        next_url = urljoin(str(resp.url), location)
        if "/u/mfa" in next_url:
            raise UrbanArrowMfaRequired("Account has MFA enabled; use the browser login")
        resp = await session.get(next_url, allow_redirects=False)
    raise UrbanArrowAuthError("Too many redirects during login")


async def login_with_credentials(
    username: str,
    password: str,
    *,
    session: aiohttp.ClientSession | None = None,
) -> Token:
    """Log in with email + password and return a token with a refresh token.

    ``session`` is used only for the final token exchange. The form steps always
    run in a private session because they need their own cookie jar, which must
    not leak into a shared Home Assistant session.
    """
    req = create_login_request()
    try:
        async with aiohttp.ClientSession(
            cookie_jar=aiohttp.CookieJar(),
            headers={"User-Agent": USER_AGENT},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as form_session:
            resp = await form_session.get(req.url, allow_redirects=False)
            callback, url, page = await _follow(form_session, resp)
            if callback is None:
                _check_blockers(url, page)
                state = _form_state(page)
                resp = await form_session.post(
                    url,
                    data={"state": state, "username": username, "action": "default", **BROWSER_HINTS},
                    allow_redirects=False,
                )
                callback, url, page = await _follow(form_session, resp)

            if callback is None:
                _check_blockers(url, page)
                if "/u/login/password" not in url:
                    raise UrbanArrowAuthError(_page_error(page) or "Unknown email address")
                state = _form_state(page)
                resp = await form_session.post(
                    url,
                    data={
                        "state": state,
                        "username": username,
                        "password": password,
                        "action": "default",
                    },
                    allow_redirects=False,
                )
                callback, url, page = await _follow(form_session, resp)

            if callback is None:
                _check_blockers(url, page)
                raise UrbanArrowAuthError(_page_error(page) or "Invalid email or password")

            code = extract_code(callback, req.state)
            if session is not None:
                return await exchange_code(session, code, req.code_verifier)
            return await exchange_code(form_session, code, req.code_verifier)
    except aiohttp.ClientError as err:
        raise UrbanArrowConnectionError(str(err)) from err
