"""SAFETY-HUMIDITY-JUNK-READING-1: implausible-humidity floor.

Humidity sensors emit a ~1s bogus 0% (or 3%) reading while reconnecting.
``HUMIDITY_PLAUSIBLE_MIN_PCT`` (5.0, exclusive) makes the safety coordinator
ignore such readings: no LOW_HUMIDITY hazard, no zone-chip trip, no reset
of the sustained high-humidity clock, and no rate-detector record.

Drives the REAL production code in
``custom_components.universal_room_automation.domain_coordinators.safety``.
"""
from __future__ import annotations

# Import for side effects: installs HA mock modules + safety import.
import test_safety_coordinator  # noqa: F401
from test_safety_coordinator import make_hass

from datetime import datetime, timedelta

import pytest

from custom_components.universal_room_automation.domain_coordinators import (
    safety as safety_mod,
)
from custom_components.universal_room_automation.domain_coordinators.safety import (
    HUMIDITY_PLAUSIBLE_MIN_PCT,
    HazardType,
    SafetyCoordinator,
    ZoneChipRoomInput,
    evaluate_zone_chip,
)
from custom_components.universal_room_automation.domain_coordinators.base import (
    Severity,
)

ENTITY = "sensor.invisoutlet_b7d0_humidity"


def _coord(room_type: str = "normal") -> SafetyCoordinator:
    coord = SafetyCoordinator(make_hass())
    coord._sensor_locations[ENTITY] = "Living Room"
    coord._sensor_room_types[ENTITY] = room_type
    return coord


def _low(hazards):
    return [h for h in hazards if h.type == HazardType.LOW_HUMIDITY]


def _room(hum):
    return ZoneChipRoomInput(
        room_name="Living Room",
        room_type="generic",
        temperature=None,
        humidity=hum,
        leak_sensor_entity_id=None,
        leak_is_on=False,
        leak_device_class=None,
    )


class TestHandleHumidityJunkFloor:
    def test_floor_default_value(self):
        assert HUMIDITY_PLAUSIBLE_MIN_PCT == 5.0

    @pytest.mark.parametrize("junk", [0.0, 3.0, 4.9])
    def test_junk_reading_emits_no_hazard(self, junk):
        coord = _coord()
        hazards = coord._handle_humidity(ENTITY, junk, datetime.utcnow())
        assert hazards == []

    @pytest.mark.parametrize("value", [5.0, 20.0])
    def test_plausible_low_still_fires_medium(self, value):
        coord = _coord()
        low = _low(coord._handle_humidity(ENTITY, value, datetime.utcnow()))
        assert len(low) == 1
        assert low[0].severity == Severity.MEDIUM

    def test_plausible_advisory_still_fires_low(self):
        coord = _coord()
        low = _low(coord._handle_humidity(ENTITY, 28.0, datetime.utcnow()))
        assert len(low) == 1
        assert low[0].severity == Severity.LOW

    def test_junk_does_not_reset_sustained_clock(self):
        coord = _coord()
        now = datetime.utcnow()
        coord._handle_humidity(ENTITY, 82.0, now)
        started = coord._humidity_above_since[ENTITY]
        coord._humidity_hazard_fired.add(ENTITY)

        coord._handle_humidity(ENTITY, 0.0, now + timedelta(seconds=1))
        assert coord._humidity_above_since.get(ENTITY) == started
        assert ENTITY in coord._humidity_hazard_fired

        # A real low-normal reading still clears (existing behaviour).
        coord._handle_humidity(ENTITY, 50.0, now + timedelta(seconds=2))
        assert ENTITY not in coord._humidity_above_since
        assert ENTITY not in coord._humidity_hazard_fired

    def test_floor_zero_disables(self, monkeypatch):
        monkeypatch.setattr(safety_mod, "HUMIDITY_PLAUSIBLE_MIN_PCT", 0)
        coord = _coord()
        low = _low(coord._handle_humidity(ENTITY, 0.0, datetime.utcnow()))
        assert len(low) == 1
        assert low[0].severity == Severity.MEDIUM


class TestProcessSensorJunkFloor:
    @pytest.mark.asyncio
    async def test_junk_not_recorded_in_rate_detector(self):
        coord = _coord()
        coord._numeric_sensors[ENTITY] = "humidity"
        hazards = await coord._process_sensor(ENTITY, "0")
        assert hazards == []
        assert ENTITY not in coord._rate_detector._history

        await coord._process_sensor(ENTITY, "47")
        hist = coord._rate_detector._history[ENTITY]
        assert [v for _, v in hist] == [47.0]

    @pytest.mark.asyncio
    async def test_floor_boundary_value_is_recorded(self):
        """5.0 is plausible (floor is exclusive) — it IS recorded."""
        coord = _coord()
        coord._numeric_sensors[ENTITY] = "humidity"
        await coord._process_sensor(ENTITY, "5.0")
        hist = coord._rate_detector._history[ENTITY]
        assert [v for _, v in hist] == [5.0]


class TestZoneChipJunkFloor:
    def test_junk_humidity_does_not_trip_or_drift(self):
        tripping, drift = evaluate_zone_chip([_room(0.0)], zone_is_outdoor=False)
        assert tripping == []
        assert drift == []

    def test_real_low_humidity_still_trips(self):
        tripping, _ = evaluate_zone_chip([_room(20.0)], zone_is_outdoor=False)
        assert len(tripping) == 1
        assert "humidity 20%" in tripping[0][1]

    def test_chip_floor_boundary_still_trips(self):
        """5.0 is plausible (floor is exclusive) and < 25 → trips."""
        tripping, _ = evaluate_zone_chip([_room(5.0)], zone_is_outdoor=False)
        assert len(tripping) == 1
        assert "humidity 5%" in tripping[0][1]

    def test_chip_floor_zero_disables(self, monkeypatch):
        monkeypatch.setattr(safety_mod, "HUMIDITY_PLAUSIBLE_MIN_PCT", 0)
        tripping, _ = evaluate_zone_chip([_room(0.0)], zone_is_outdoor=False)
        assert len(tripping) == 1


# ---------------------------------------------------------------------------
# Whole-house SafetyAlertBinarySensor._get_alerts (aggregation.py)
# ---------------------------------------------------------------------------


def _house_alert_sensor(monkeypatch, humidity):
    """Bare SafetyAlertBinarySensor wired to one fake room coordinator."""
    import sys
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from test_zone_safety_alert import _install_aggregation_mocks

    _install_aggregation_mocks()
    stale = sys.modules.get("custom_components.universal_room_automation.aggregation")
    if stale is not None and not hasattr(stale, "SafetyAlertBinarySensor"):
        del sys.modules["custom_components.universal_room_automation.aggregation"]
    from custom_components.universal_room_automation import aggregation
    from custom_components.universal_room_automation.const import (
        STATE_HUMIDITY,
    )

    room = SimpleNamespace(
        entry=SimpleNamespace(data={"room_name": "Living Room"}, options={}),
        data={STATE_HUMIDITY: humidity},
    )
    monkeypatch.setattr(aggregation, "_get_room_coordinators", lambda hass: [room])
    inst = object.__new__(aggregation.SafetyAlertBinarySensor)
    inst.hass = MagicMock()
    inst.hass.states.get.return_value = None
    return inst


class TestHouseSafetyAlertJunkFloor:
    def test_junk_humidity_no_house_alert(self, monkeypatch):
        inst = _house_alert_sensor(monkeypatch, 0.0)
        assert [a for a in inst._get_alerts() if a["type"] == "humidity"] == []

    def test_real_low_humidity_house_alert_too_dry(self, monkeypatch):
        inst = _house_alert_sensor(monkeypatch, 20.0)
        hum = [a for a in inst._get_alerts() if a["type"] == "humidity"]
        assert len(hum) == 1
        assert hum[0]["issue"] == "too_dry"

    def test_house_alert_floor_boundary_still_too_dry(self, monkeypatch):
        inst = _house_alert_sensor(monkeypatch, 5.0)
        hum = [a for a in inst._get_alerts() if a["type"] == "humidity"]
        assert len(hum) == 1
        assert hum[0]["issue"] == "too_dry"
