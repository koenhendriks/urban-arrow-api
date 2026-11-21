import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from urban_arrow_api import (
    UrbanArrowAuthError,
    UrbanArrowCaptchaRequired,
    login_with_credentials,
)
from urban_arrow_api.const import AUTH0_REDIRECT_URI

PASSWORD = "hunter2"


def _form(extra: str = "", error: str = "") -> str:
    err = f'<span id="error-element-password" class="x">{error}</span>' if error else ""
    # The real page always ships captcha selector strings in inline JS.
    return (
        "<script>q('[data-captcha-sitekey] input')</script>"
        f'<form method="POST"><input type="hidden" name="state" value="s1"/>{extra}{err}</form>'
    )


@pytest.fixture
async def auth0(monkeypatch):
    calls = {"oauth_state": None, "identifier_page": _form()}

    async def authorize(request):
        calls["oauth_state"] = request.query["state"]
        raise web.HTTPFound("/u/login/identifier?state=s1")

    async def identifier(request):
        if request.method == "GET":
            return web.Response(text=calls["identifier_page"], content_type="text/html")
        form = await request.post()
        assert form["username"] == "me@example.com"
        raise web.HTTPFound("/u/login/password?state=s1")

    async def password(request):
        if request.method == "GET":
            return web.Response(text=_form(), content_type="text/html")
        form = await request.post()
        if form["password"] != PASSWORD:
            return web.Response(status=400, text=_form(error="Wrong email or password"), content_type="text/html")
        raise web.HTTPFound("/authorize/resume?state=s1")

    async def resume(request):
        raise web.HTTPFound(f"{AUTH0_REDIRECT_URI}?code=the-code&state={calls['oauth_state']}")

    async def token(request):
        body = await request.json()
        assert body["code"] == "the-code"
        assert body["code_verifier"]
        return web.json_response({"access_token": "a", "refresh_token": "r", "expires_in": 3600})

    app = web.Application()
    app.router.add_get("/authorize", authorize)
    app.router.add_route("*", "/u/login/identifier", identifier)
    app.router.add_route("*", "/u/login/password", password)
    app.router.add_get("/authorize/resume", resume)
    app.router.add_post("/oauth/token", token)
    server = TestServer(app)
    await server.start_server()
    base = str(server.make_url("")).rstrip("/")
    monkeypatch.setattr("urban_arrow_api.auth.AUTHORIZE_URL", base + "/authorize")
    monkeypatch.setattr("urban_arrow_api.auth.TOKEN_URL", base + "/oauth/token")
    yield calls
    await server.close()


async def test_successful_login(auth0):
    token = await login_with_credentials("me@example.com", PASSWORD)
    assert token.access_token == "a"
    assert token.refresh_token == "r"


async def test_wrong_password_surfaces_auth0_message(auth0):
    with pytest.raises(UrbanArrowAuthError, match="Wrong email or password"):
        await login_with_credentials("me@example.com", "nope")


async def test_captcha_widget_is_detected(auth0):
    auth0["identifier_page"] = _form('<div data-captcha-sitekey="abc" data-captcha-provider="auth0"></div>')
    with pytest.raises(UrbanArrowCaptchaRequired):
        await login_with_credentials("me@example.com", PASSWORD)
