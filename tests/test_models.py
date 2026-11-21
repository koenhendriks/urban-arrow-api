import json
from pathlib import Path

from urban_arrow_api import Bike, Telemetry

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_parse_real_bike_payload():
    bike = Bike.parse(_load("bike.json"))
    assert bike.name == "Test Arrow"
    assert bike.category == "Bakfiets"
    assert bike.is_smart
    assert bike.protection_level == "MOTION_SENSOR"
    assert bike.module.auto_protection_enabled
    assert bike.module.firmware.version == "260828"
    assert bike.data_subscription.state == "ACTIVE"
    assert bike.data_subscription.can_withdraw_until is None
    assert bike.notifications.battery_full and not bike.notifications.module_battery_low
    assert bike.paired_on.year == 2024


def test_parse_real_telemetry_payload():
    t = Telemetry.parse(_load("telemetry.json"))
    assert t.battery_charge.value == 72
    assert t.module_charge.value == 22
    assert t.odometer.value == 1705.04
    assert t.range.value == 26.0
    assert t.assist_level.value == 4
    assert t.location.value.longitude == 5.0
