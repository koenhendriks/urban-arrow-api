from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import aiohttp

from .auth import AbstractAuth
from .const import (
    API_BASE_URL,
    CLIENT_TYPE,
    MANUFACTURER_ID,
    PRODUCTION_PROFILE_IMAGE_URL,
    ActivityPeriod,
    BikeSetting,
)
from .exceptions import (
    UrbanArrowApiError,
    UrbanArrowAuthError,
    UrbanArrowConnectionError,
)
from .models import Activity, Bike, BikeSummary, Notification, Telemetry

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=15)


class UrbanArrowClient:
    """Async client for the Pon Connected API as used by the Urban Arrow app."""

    def __init__(self, auth: AbstractAuth, *, language: str = "en") -> None:
        self._auth = auth
        self._session = auth.session
        self._language = language

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        _retry: bool = True,
    ) -> Any:
        access_token = await self._auth.async_get_access_token()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Manufacturer-Id": MANUFACTURER_ID,
            "Client-Type": CLIENT_TYPE,
            "Accept-Language": self._language,
            "Accept": "application/json",
        }
        try:
            async with self._session.request(
                method,
                API_BASE_URL + path,
                params=params,
                json=json,
                headers=headers,
                timeout=DEFAULT_TIMEOUT,
            ) as resp:
                if resp.status == 401 and _retry:
                    await self._auth.async_get_access_token(force_refresh=True)
                    return await self._request(
                        method, path, params=params, json=json, _retry=False
                    )
                if resp.status == 401:
                    raise UrbanArrowAuthError("Access token rejected")
                if resp.status >= 400:
                    raise UrbanArrowApiError(resp.status, await resp.text())
                if resp.status == 204 or resp.content_length == 0:
                    return None
                text = await resp.text()
                if not text:
                    return None
                try:
                    return await resp.json(content_type=None)
                except ValueError:
                    return text
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UrbanArrowConnectionError(str(err)) from err

    # Bikes

    async def get_bikes(self) -> list[BikeSummary]:
        return [BikeSummary.parse(b) for b in await self._request("GET", "v9/bikes")]

    async def get_bike(self, bike_id: str) -> Bike:
        return Bike.parse(await self._request("GET", f"v11/bikes/{bike_id}"))

    async def get_telemetry(self, bike_id: str) -> Telemetry:
        return Telemetry.parse(await self._request("GET", f"v11/bikes/{bike_id}/telemetry"))

    async def get_bike_by_module(self, module_id: str) -> BikeSummary:
        return BikeSummary.parse(await self._request("GET", f"v9/bikes/module/{module_id}"))

    async def check_frame_number(self, frame_number: str) -> dict[str, Any]:
        """Returns ``{"isSmart": bool, "productionProfileId": str}``."""
        return await self._request("GET", f"v10/bikes/frame-number/{frame_number}")

    async def set_nickname(self, bike_id: str, nickname: str) -> None:
        await self._request("PUT", f"v1/bikes/{bike_id}/nickname", json={"nickname": nickname})

    async def flash_lights(self, bike_id: str) -> None:
        await self._request("POST", f"v1/bikes/{bike_id}/flash-lights")

    async def set_setting(self, bike_id: str, setting: BikeSetting, enabled: bool) -> None:
        action = "enable" if enabled else "disable"
        await self._request("PUT", f"v2/bikes/{bike_id}/settings/{setting.value}/{action}")

    async def set_theft_protection(self, bike_id: str, enabled: bool) -> None:
        await self._request(
            "PUT", f"v1/bikes/{bike_id}/theft/detection/mode", json={"enabled": enabled}
        )

    async def get_activity(
        self,
        bike: Bike,
        period: ActivityPeriod,
        start_date: date,
        cutoff_date: date | None = None,
    ) -> Activity:
        """Distance per sub-period (e.g. per day for WEEK) starting at ``start_date``.

        The app passes the pairing date as ``cutoffDate`` so nothing before the
        current owner is returned; we default to the same.
        """
        if cutoff_date is None:
            cutoff_date = bike.paired_on.date() if bike.paired_on else date(1970, 1, 1)
        cutoff_ms = int(
            datetime(cutoff_date.year, cutoff_date.month, cutoff_date.day, tzinfo=UTC).timestamp()
            * 1000
        )
        data = await self._request(
            "GET",
            f"v6/bikes/{bike.id}/activity/history",
            params={
                "timeUnit": period.value,
                "startDate": start_date.isoformat(),
                "cutoffDate": cutoff_ms,
            },
        )
        return Activity.parse(data)

    # Theft

    async def report_theft(
        self, bike_id: str, police_report_number: str | None, phone_number: str | None
    ) -> None:
        await self._request(
            "POST",
            f"v4/bikes/{bike_id}/theft/report",
            json={"policeReportNumber": police_report_number, "customerPhoneNumber": phone_number},
        )

    async def cancel_theft_report(self, bike_id: str) -> None:
        await self._request("POST", f"v1/bikes/{bike_id}/theft/cancel")

    # Notifications (the in-app inbox, not push)

    async def get_notifications(self, version: str = "6") -> list[Notification]:
        data = await self._request("GET", "v4/notifications", params={"version": version})
        return [Notification.parse(n) for n in data or []]

    async def mark_notifications_read(self, ids: list[str], read: bool = True) -> None:
        path = "v7/notifications/mark-as-read" if read else "v7/notifications/mark-as-unread"
        await self._request("PUT", path, json={"content": ids})

    async def delete_notifications(self, ids: list[str]) -> None:
        await self._request("DELETE", "v7/notifications", json={"content": ids})

    # Account / misc

    async def get_user_preferences(self) -> dict[str, Any]:
        return await self._request("GET", "v9/user-preferences")

    async def get_health(self) -> dict[str, Any] | None:
        return await self._request("GET", "health-watcher/v1/health")

    async def get_points_of_interest(self) -> list[dict[str, Any]]:
        return await self._request("GET", "v3/pois")

    @staticmethod
    def image_url(production_profile_id: str) -> str:
        return PRODUCTION_PROFILE_IMAGE_URL.format(profile_id=production_profile_id)
