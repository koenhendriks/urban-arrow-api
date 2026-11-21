import time

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from urban_arrow_api import (
    BikeSetting,
    Token,
    TokenAuth,
    UrbanArrowAuthError,
    UrbanArrowClient,
    create_login_request,
    extract_code,
)

BIKE = "bike-1"


class FakeBackend:
    def __init__(self) -> None:
        self.requests: list[web.Request] = []
        self.responses: dict[tuple[str, str], list[web.Response]] = {}

    def add(self, method: str, path: str, response: web.Response) -> None:
        self.responses.setdefault((method, path), []).append(response)

    async def handle(self, request: web.Request) -> web.Response:
        self.requests.append(request)
        queue = self.responses[(request.method, request.path)]
        return queue.pop(0) if len(queue) > 1 else queue[0]


@pytest.fixture
async def backend(monkeypatch):
    fake = FakeBackend()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", fake.handle)
    server = TestServer(app)
    await server.start_server()
    base = str(server.make_url("/"))
    monkeypatch.setattr("urban_arrow_api.client.API_BASE_URL", base + "api/")
    monkeypatch.setattr("urban_arrow_api.auth.TOKEN_URL", base + "oauth/token")
    yield fake
    await server.close()


def _token(expires_in: float = 3600) -> Token:
    return Token("access", "refresh", time.time() + expires_in)


async def test_telemetry_parsing_and_headers(backend):
    ts = 1764000000000
    backend.add(
        "GET",
        f"/api/v11/bikes/{BIKE}/telemetry",
        web.json_response(
            {
                "assistLevel": {"value": 3, "lastUpdatedOn": ts},
                "battery": {
                    "charge": {"value": 81, "lastUpdatedOn": ts},
                    "isCharging": {"value": False, "lastUpdatedOn": ts},
                },
                "coordinate": {
                    "value": {"latitude": 52.37, "longitude": 4.89},
                    "lastUpdatedOn": ts,
                },
                "moduleCharge": None,
                "odometer": {"value": 1234.5, "lastUpdatedOn": ts},
                "range": {"value": 40, "lastUpdatedOn": ts},
            }
        ),
    )
    async with aiohttp.ClientSession() as session:
        t = await UrbanArrowClient(TokenAuth(session, _token())).get_telemetry(BIKE)

    headers = backend.requests[0].headers
    assert t.battery_charge.value == 81
    assert t.battery_charging.value is False
    assert t.location.value.latitude == 52.37
    assert t.module_charge is None
    assert t.battery_charge.last_updated.year == 2025
    assert headers["Authorization"] == "Bearer access"
    assert headers["Manufacturer-Id"] == "UA"
    assert headers["Client-Type"] == "ANDROID"


async def test_expired_token_is_refreshed_and_reported(backend):
    backend.add(
        "POST",
        "/oauth/token",
        web.json_response({"access_token": "new", "expires_in": 600, "refresh_token": "r2"}),
    )
    backend.add(
        "PUT", f"/api/v2/bikes/{BIKE}/settings/AUTO_PROTECTION/enable", web.Response(status=204)
    )
    updates = []
    async with aiohttp.ClientSession() as session:
        auth = TokenAuth(session, _token(-1), updates.append)
        await UrbanArrowClient(auth).set_setting(BIKE, BikeSetting.AUTO_PROTECTION, True)

    assert auth.token.access_token == "new"
    assert auth.token.refresh_token == "r2"
    assert updates == [auth.token]
    assert backend.requests[1].headers["Authorization"] == "Bearer new"


async def test_401_triggers_single_refresh_then_retry(backend):
    path = f"/api/v1/bikes/{BIKE}/flash-lights"
    backend.add("POST", path, web.Response(status=401))
    backend.add("POST", path, web.Response(status=200))
    backend.add(
        "POST", "/oauth/token", web.json_response({"access_token": "new", "expires_in": 600})
    )
    async with aiohttp.ClientSession() as session:
        auth = TokenAuth(session, _token())
        await UrbanArrowClient(auth).flash_lights(BIKE)

    assert [r.path for r in backend.requests] == [path, "/oauth/token", path]
    assert auth.token.refresh_token == "refresh"


async def test_revoked_refresh_token_raises_auth_error(backend):
    backend.add("POST", "/oauth/token", web.json_response({"error": "invalid_grant"}, status=403))
    async with aiohttp.ClientSession() as session:
        with pytest.raises(UrbanArrowAuthError):
            await UrbanArrowClient(TokenAuth(session, _token(-1))).get_bikes()


def test_extract_code():
    req = create_login_request()
    assert "code_challenge_method=S256" in req.url
    url = (
        "urbanarrow://consumer.login.pon.bike/android/com.urbanarrow.connected/callback"
        f"?code=abc&state={req.state}"
    )
    assert extract_code(url, req.state) == "abc"
    assert extract_code("abc") == "abc"
    with pytest.raises(UrbanArrowAuthError):
        extract_code(url, "other-state")


async def test_custom_refresh_fallback_is_used(backend):
    backend.add("GET", "/api/v9/bikes", web.json_response([]))

    class FallbackAuth(TokenAuth):
        async def async_refresh_token(self, token: Token) -> Token:
            return Token("relogin", "r3", time.time() + 600)

    async with aiohttp.ClientSession() as session:
        auth = FallbackAuth(session, _token(-1))
        assert await UrbanArrowClient(auth).get_bikes() == []

    assert backend.requests[0].headers["Authorization"] == "Bearer relogin"
