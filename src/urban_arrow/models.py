"""Typed views over the API's JSON. Every model keeps the original payload in ``raw``
because field nullability was inferred from the decompiled app, not from a spec."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any


def _ts(value: Any) -> datetime | None:
    """The backend sends timestamps as epoch milliseconds."""
    if value is None:
        return None
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


@dataclass(slots=True)
class TimedValue[T]:
    value: T | None
    last_updated: datetime | None

    @classmethod
    def parse(cls, data: dict[str, Any] | None) -> TimedValue[T] | None:
        if not data:
            return None
        return cls(data.get("value"), _ts(data.get("lastUpdatedOn")))


@dataclass(slots=True)
class Location:
    latitude: float
    longitude: float


@dataclass(slots=True)
class Telemetry:
    assist_level: TimedValue[int] | None
    battery_charge: TimedValue[float] | None
    battery_charging: TimedValue[bool] | None
    location: TimedValue[Location] | None
    module_charge: TimedValue[float] | None
    odometer: TimedValue[float] | None
    range: TimedValue[float] | None
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Telemetry:
        battery = data.get("battery") or {}
        coordinate = data.get("coordinate")
        location = None
        if coordinate and coordinate.get("value"):
            loc = coordinate["value"]
            location = TimedValue(
                Location(loc["latitude"], loc["longitude"]),
                _ts(coordinate.get("lastUpdatedOn")),
            )
        return cls(
            assist_level=TimedValue.parse(data.get("assistLevel")),
            battery_charge=TimedValue.parse(battery.get("charge")),
            battery_charging=TimedValue.parse(battery.get("isCharging")),
            location=location,
            module_charge=TimedValue.parse(data.get("moduleCharge")),
            odometer=TimedValue.parse(data.get("odometer")),
            range=TimedValue.parse(data.get("range")),
            raw=data,
        )


@dataclass(slots=True)
class BikeSummary:
    id: str
    frame_number: str | None
    is_stolen: bool
    model: str | None
    nickname: str | None
    production_profile_id: str | None
    system: str | None
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def parse(cls, data: dict[str, Any]) -> BikeSummary:
        return cls(
            id=data["id"],
            frame_number=data.get("frameNumber"),
            is_stolen=bool(data.get("isStolen")),
            model=data.get("model"),
            nickname=data.get("nickname"),
            production_profile_id=data.get("productionProfileId"),
            system=data.get("system"),
            raw=data,
        )


@dataclass(slots=True)
class Firmware:
    branch: str | None
    version: str | None
    upgraded_on: datetime | None


@dataclass(slots=True)
class Module:
    id: str | None
    auto_charge_enabled: bool
    auto_protection_enabled: bool
    protection_enabled: bool
    can_data_supported: bool
    supports_telemetry_over_ble: bool
    last_online: datetime | None
    firmware: Firmware | None

    @classmethod
    def parse(cls, data: dict[str, Any] | None) -> Module | None:
        if not data:
            return None
        fw = data.get("firmware")
        return cls(
            id=data.get("id"),
            auto_charge_enabled=bool(data.get("autoChargeEnabled")),
            auto_protection_enabled=bool(data.get("autoProtectionEnabled")),
            protection_enabled=bool(data.get("protectionEnabled")),
            can_data_supported=bool(data.get("canDataSupported")),
            supports_telemetry_over_ble=bool(data.get("supportsTelemetryOverBle")),
            last_online=_ts(data.get("lastOnline")),
            firmware=Firmware(fw.get("branch"), fw.get("version"), _ts(fw.get("upgradedOn")))
            if fw
            else None,
        )


@dataclass(slots=True)
class NotificationSettings:
    battery_full: bool
    battery_low: bool
    module_battery_low: bool
    protection_activated: bool


@dataclass(slots=True)
class DataSubscription:
    state: str | None
    start_date: datetime | None
    end_date: datetime | None
    can_withdraw_until: datetime | None


@dataclass(slots=True)
class Bike:
    id: str
    frame_number: str | None
    model: str | None
    category: str | None
    is_smart: bool
    nickname: str | None
    production_profile_id: str | None
    system: str | None
    protection_level: str | None
    paired_on: datetime | None
    module: Module | None
    notifications: NotificationSettings | None
    data_subscription: DataSubscription | None
    raw: dict[str, Any] = field(repr=False)

    @property
    def name(self) -> str:
        return self.nickname or self.model or self.id

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Bike:
        details = data.get("details") or {}
        notif = data.get("notifications")
        sub = data.get("dataSubscription")
        return cls(
            id=data["id"],
            frame_number=details.get("frameNumber"),
            model=details.get("model"),
            category=details.get("category"),
            is_smart=bool(details.get("isSmart")),
            nickname=details.get("nickname"),
            production_profile_id=details.get("productionProfileId"),
            system=details.get("system"),
            protection_level=details.get("protectionLevel"),
            paired_on=_ts(details.get("pairedOn")),
            module=Module.parse(data.get("module")),
            notifications=NotificationSettings(
                bool(notif.get("batteryFull")),
                bool(notif.get("batteryLow")),
                bool(notif.get("moduleBatteryLow")),
                bool(notif.get("protectionActivated")),
            )
            if notif
            else None,
            data_subscription=DataSubscription(
                sub.get("state"),
                _ts(sub.get("startDate")),
                _ts(sub.get("endDate")),
                _ts(sub.get("canWithdrawUntil")),
            )
            if sub
            else None,
            raw=data,
        )


@dataclass(slots=True)
class Activity:
    bicycle_id: str | None
    period: str | None
    start_date: date | None
    values: list[float]
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Activity:
        start = data.get("startDate")
        return cls(
            bicycle_id=data.get("bicycleId"),
            period=data.get("period"),
            start_date=date.fromisoformat(start[:10]) if isinstance(start, str) else None,
            values=[float(v) for v in data.get("values") or []],
            raw=data,
        )


@dataclass(slots=True)
class Notification:
    id: str
    bicycle_id: str | None
    title: str | None
    body: str | None
    channel: str | None
    type: str | None
    unread: bool
    created_on: datetime | None
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Notification:
        created = data.get("createdOn")
        return cls(
            id=data["id"],
            bicycle_id=data.get("bicycleId"),
            title=data.get("title"),
            body=data.get("body"),
            channel=data.get("channel"),
            type=data.get("type"),
            unread=bool(data.get("unread")),
            created_on=_ts(created) if isinstance(created, int | float) else None,
            raw=data,
        )
