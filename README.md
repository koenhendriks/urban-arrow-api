# urban-arrow-api

Async Python client for the cloud API behind the Urban Arrow app
(`com.urbanarrow.connected` 5.2.1). Intended as the library for a Home Assistant
integration.

The API is the shared **Pon Connected** backend (also used by Gazelle and other
Pon brands); the `Manufacturer-Id: UA` header selects Urban Arrow.

## Installation

```bash
pip install urban-arrow-api
```

## Quick start

```bash
uv sync
uv run urban-arrow login you@example.com   # prompts for password, stores ~/.config/urban-arrow/token.json
uv run urban-arrow browser-login          # fallback: manual browser login
uv run urban-arrow status         # bike details + telemetry as JSON
uv run urban-arrow raw GET v9/bikes
```

```python
from urban_arrow_api import TokenAuth, UrbanArrowClient, login_with_credentials

async with aiohttp.ClientSession() as session:
    token = await login_with_credentials("you@example.com", "password", session=session)
    client = UrbanArrowClient(TokenAuth(session, token, on_token_update=save_token))
    for summary in await client.get_bikes():
        telemetry = await client.get_telemetry(summary.id)
        print(telemetry.battery_charge, telemetry.location)
```

## Authentication

| | |
|---|---|
| Auth0 tenant | `consumer.login.pon.bike` |
| Client ID | `i2ype1HhtU4rg4LKRdBKgldnfVbVwrG6` |
| Audience | `https://app.connected.pon.bike/` |
| Scope | `openid profile offline_access email` |
| Redirect URI | `urbanarrow://consumer.login.pon.bike/android/com.urbanarrow.connected/callback` |

The password grant is **disabled** for this client (`unauthorized_client`), so
there is no direct username/password token call. Instead,
`login_with_credentials(username, password)` (`login.py`) drives Auth0's hosted
login pages over plain HTTP, the way a browser without JavaScript would:

1. `GET /authorize` (PKCE) redirects to `/u/login/identifier?state=...`
2. `POST` `state` + `username` redirects to `/u/login/password?state=...`
3. `POST` `state` + `username` + `password` redirects to `/authorize/resume`,
   which redirects to `urbanarrow://...callback?code=...`
4. The code is exchanged at `/oauth/token`, same as the app.

This works because the tenant currently has no captcha or MFA on the login
pages. If Auth0 starts showing a captcha or asks for MFA, it raises
`UrbanArrowCaptchaRequired` or `UrbanArrowMfaRequired`. The manual flow
(`create_login_request` + `extract_code` + `exchange_code`, CLI
`browser-login`) stays available as a fallback: log in in a browser and paste
the `urbanarrow://...?code=...` URL back.

After login the refresh token (`offline_access`) keeps the session alive.
`UrbanArrowClient` never handles tokens itself: it asks an `AbstractAuth` for
one via `async_get_access_token()`. `TokenAuth` is the ready-made
implementation; it refreshes through Auth0 and calls `on_token_update` so the
new token can be persisted (Auth0 may rotate refresh tokens). Override
`TokenAuth.async_refresh_token` to add a fallback such as a fresh login.
`Token.as_dict()` / `Token.from_dict()` give a JSON-serialisable form for
storage.

For Home Assistant: the config flow asks for email + password, and the
integration stores the token. It also stores the credentials, so if the refresh
token is ever revoked it can log in again silently, and only start a reauth
flow when that fails.

## Request headers

```
Authorization: Bearer <access_token>
Manufacturer-Id: UA
Client-Type: ANDROID
Accept-Language: <lang>
```

## Endpoints

Base URL: `https://app.connected.pon.bike/api/`. Timestamps are epoch milliseconds.

| Method | Path | Notes | Client method |
|---|---|---|---|
| GET | `v9/bikes` | List of paired bikes | `get_bikes` |
| GET | `v11/bikes/{id}` | Details, module, firmware, subscription, notification settings | `get_bike` |
| GET | `v11/bikes/{id}/telemetry` | Battery %, charging, GPS, odometer, range, assist level, module charge | `get_telemetry` |
| GET | `v6/bikes/{id}/activity/history?timeUnit=&startDate=&cutoffDate=` | `timeUnit` WEEK/MONTH/QUARTER/YEAR, `startDate` yyyy-MM-dd, `cutoffDate` epoch ms (app uses pairing date). Returns `values: [double]` | `get_activity` |
| POST | `v1/bikes/{id}/flash-lights` | Blink lights (find my bike) | `flash_lights` |
| PUT | `v2/bikes/{id}/settings/{SETTING}/enable` / `disable` | `AUTO_PROTECTION`, `MODULE_BATTERY_MANAGEMENT`, `NOTIFICATION_*` | `set_setting` |
| PUT | `v1/bikes/{id}/theft/detection/mode` | `{"enabled": bool}` | `set_theft_protection` |
| PUT | `v1/bikes/{id}/nickname` | `{"nickname": str}` | `set_nickname` |
| GET | `v9/bikes/module/{moduleId}` | Bike by module id | `get_bike_by_module` |
| GET | `v10/bikes/frame-number/{frameNumber}` | `{isSmart, productionProfileId}` | `check_frame_number` |
| POST | `v4/bikes/{id}/theft/report` | `{policeReportNumber, customerPhoneNumber}` (PUT updates) | `report_theft` |
| POST | `v1/bikes/{id}/theft/cancel` | | `cancel_theft_report` |
| GET | `v4/notifications?version=6` | In-app inbox | `get_notifications` |
| PUT | `v7/notifications/mark-as-read` / `mark-as-unread` | `{"content": [ids]}` | `mark_notifications_read` |
| DELETE | `v7/notifications` | `{"content": [ids]}` | `delete_notifications` |
| GET | `v9/user-preferences` | `{preferredDealerId, theftNotificationSound}` | `get_user_preferences` |
| GET | `v3/pois` | Dealers / points of interest | `get_points_of_interest` |
| GET | `health-watcher/v1/health` | Backend status message (no auth needed) | `get_health` |
| GET | `v1/productionprofiles/{productionProfileId}/image` | Bike image | `image_url` |

Not wrapped (account/commerce, not useful for HA): pairing
(`v10/bikes/pairing/smart|non-smart`, `DELETE v10/bikes/{id}/pairing`),
insurance (`v9/bikes/{id}/insurance*`), subscription payments
(`v10/bikes/{id}/subscription/extension/payment/{variantId}`,
`v7/payments/sessions/*`, `v7/bikes/{id}/subscription/withdraw`), FCM push
registration (`v4/notifications/fcm/register`, `v1/notifications/fcm/unregister`),
dealers (`v3/dealers/...`), FAQ (`v4/faq`, `v3/faq/{id}`), route planning
(`v11/navigation/route`) and version checks (`v3/minimum-version/android`,
`v3/latest-release-version/ANDROID`). All reachable through `client._request`.

## Observed values (real Family Active Line Plus, BES2 system)

- `battery.charge` and `moduleCharge`: percent (72, 22). `moduleCharge` is the
  connectivity module's own backup battery, not the e-bike battery.
- `odometer`: km with 2 decimals (1705.04). `range`: km (26.0).
- `assistLevel`: integer (4).
- Each telemetry value has its own `lastUpdatedOn`; battery and location can be
  hours older than assist level / range, so they come from separate reports.
- Bike details also include `category` ("Bakfiets") and `isSmart`.

## Open questions

- Whether the refresh token rotates, and how long it lives.
- How often telemetry updates while the bike is parked or asleep.

## Development and releases

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

Releases are published to PyPI by `.github/workflows/release.yaml` when a
GitHub release is published. The tag (`v0.1.0` or `0.1.0`) must match
`version` in `pyproject.toml`. PyPI trusted publishing has to be configured once
for the `pypi` environment of this repository.

## License

MIT
