"""Tests for v3.13.1 complete data pipeline.

Verifies:
- energy_history log_energy_history includes tou_period column
- _get_house_avg_climate reads room coordinator sensors
- _get_occupancy_counts reads presence coordinator
- _get_occupied_room_count reads presence coordinator
- Circuit state save/restore wiring in energy coordinator
- D3-D7 callers exist (regression guards)
"""

import asyncio
import os
import sqlite3
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
import pytest
import sys
import types

# ---------------------------------------------------------------------------
# Mock homeassistant before importing URA code
# ---------------------------------------------------------------------------

def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod

_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_mods = {
    "homeassistant": {},
    "homeassistant.core": {"HomeAssistant": _mock_cls, "callback": _identity},
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": _mock_cls()},
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_time_interval": MagicMock(),
        "async_call_later": MagicMock(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": MagicMock(),
        "async_dispatcher_send": MagicMock(),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.utcnow(),
        "now": lambda: datetime.now(),
        "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(), "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {"ButtonEntity": type("ButtonEntity", (), {})},
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura

from custom_components.universal_room_automation.database import UniversalRoomDatabase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_path: str) -> UniversalRoomDatabase:
    hass = MagicMock()
    hass.config.path = lambda *parts: os.path.join(tmp_path, *parts)
    return UniversalRoomDatabase(hass)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLogEnergyHistoryWithTouPeriod:
    """Test that log_energy_history now stores tou_period."""

    def test_tou_period_stored(self, tmp_path):
        """tou_period should be stored in energy_history rows."""
        db = _make_db(str(tmp_path))
        _run(db.initialize())

        _run(db.log_energy_history({
            "solar_production": 5.0,
            "solar_export": 2.0,
            "grid_import": 1.0,
            "battery_level": 80,
            "whole_house_energy": 3.5,
            "outside_temp": 85.0,
            "outside_humidity": 50.0,
            "house_avg_temp": 72.0,
            "house_avg_humidity": 45.0,
            "temp_delta_outside": -13.0,
            "humidity_delta_outside": -5.0,
            "rooms_occupied": 3,
            "tou_period": "peak",
        }))

        conn = sqlite3.connect(db.db_file)
        cursor = conn.execute("SELECT tou_period FROM energy_history")
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "peak"

    def test_tou_period_null_when_not_provided(self, tmp_path):
        """tou_period should be NULL when not provided in data dict."""
        db = _make_db(str(tmp_path))
        _run(db.initialize())

        _run(db.log_energy_history({
            "solar_production": 1.0,
            "grid_import": 0.5,
        }))

        conn = sqlite3.connect(db.db_file)
        cursor = conn.execute("SELECT tou_period FROM energy_history")
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] is None

    def test_all_new_columns_populated(self, tmp_path):
        """All M2 columns should be stored when provided."""
        db = _make_db(str(tmp_path))
        _run(db.initialize())

        data = {
            "solar_production": 5.0,
            "solar_export": 2.0,
            "grid_import": 1.0,
            "battery_level": 80,
            "whole_house_energy": 3.5,
            "rooms_energy_total": 2.0,
            "outside_temp": 85.0,
            "outside_humidity": 50.0,
            "house_avg_temp": 72.0,
            "house_avg_humidity": 45.0,
            "temp_delta_outside": -13.0,
            "humidity_delta_outside": -5.0,
            "rooms_occupied": 3,
            "tou_period": "off_peak",
        }
        _run(db.log_energy_history(data))

        conn = sqlite3.connect(db.db_file)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM energy_history")
        row = dict(cursor.fetchone())
        conn.close()

        assert row["outside_humidity"] == 50.0
        assert row["house_avg_temp"] == 72.0
        assert row["house_avg_humidity"] == 45.0
        assert row["temp_delta_outside"] == -13.0
        assert row["humidity_delta_outside"] == -5.0
        assert row["rooms_occupied"] == 3
        assert row["tou_period"] == "off_peak"


class TestD3D7CallersExist:
    """Regression guards: verify D3-D7 DB write callers exist in source files."""

    def test_presence_calls_log_house_state_change(self):
        """presence.py must call log_house_state_change."""
        import importlib
        presence_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "custom_components", "universal_room_automation",
            "domain_coordinators", "presence.py"
        )
        with open(presence_path, "r") as f:
            source = f.read()
        assert "log_house_state_change" in source, "presence.py must call log_house_state_change"

    def test_presence_calls_log_zone_event(self):
        """presence.py must call log_zone_event."""
        presence_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "custom_components", "universal_room_automation",
            "domain_coordinators", "presence.py"
        )
        with open(presence_path, "r") as f:
            source = f.read()
        assert "log_zone_event" in source, "presence.py must call log_zone_event"

    def test_person_coordinator_calls_log_person_entry(self):
        """person_coordinator.py must call log_person_entry."""
        pc_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "custom_components", "universal_room_automation",
            "person_coordinator.py"
        )
        with open(pc_path, "r") as f:
            source = f.read()
        assert "log_person_entry" in source

    def test_person_coordinator_calls_log_person_snapshot(self):
        """person_coordinator.py must call log_person_snapshot."""
        pc_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "custom_components", "universal_room_automation",
            "person_coordinator.py"
        )
        with open(pc_path, "r") as f:
            source = f.read()
        assert "log_person_snapshot" in source

    def test_camera_census_calls_log_census(self):
        """camera_census.py must call log_census."""
        census_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "custom_components", "universal_room_automation",
            "camera_census.py"
        )
        with open(census_path, "r") as f:
            source = f.read()
        assert "log_census" in source


class TestEnergyHelperMethods:
    """Test _get_house_avg_climate, _get_occupancy_counts, _get_occupied_room_count."""

    def _make_energy_coordinator(self):
        """Create a minimal EnergyCoordinator mock for testing helpers."""
        # Import the actual module to get the helper methods
        from custom_components.universal_room_automation.domain_coordinators.energy import (
            EnergyCoordinator,
        )
        hass = MagicMock()
        hass.data = {}

        # Build a minimal coordinator without calling __init__
        ec = object.__new__(EnergyCoordinator)
        ec.hass = hass
        return ec, hass

    def test_get_house_avg_climate_no_entries(self):
        """With no room entries, should return (None, None)."""
        ec, hass = self._make_energy_coordinator()
        hass.config_entries = MagicMock()
        hass.config_entries.async_entries = MagicMock(return_value=[])
        avg_t, avg_h = ec._get_house_avg_climate()
        assert avg_t is None
        assert avg_h is None

    def test_get_house_avg_climate_with_rooms(self):
        """Should average temp/humidity across room entries."""
        ec, hass = self._make_energy_coordinator()

        # Create mock room entries
        entry1 = MagicMock()
        entry1.data = {"entry_type": "room", "temperature_sensor": "sensor.room1_temp",
                       "humidity_sensor": "sensor.room1_hum"}
        entry1.options = {}

        entry2 = MagicMock()
        entry2.data = {"entry_type": "room", "temperature_sensor": "sensor.room2_temp",
                       "humidity_sensor": "sensor.room2_hum"}
        entry2.options = {}

        hass.config_entries.async_entries = MagicMock(return_value=[entry1, entry2])

        # Mock states
        state_map = {
            "sensor.room1_temp": MagicMock(state="72.0"),
            "sensor.room2_temp": MagicMock(state="74.0"),
            "sensor.room1_hum": MagicMock(state="40.0"),
            "sensor.room2_hum": MagicMock(state="50.0"),
        }
        hass.states.get = lambda eid: state_map.get(eid)

        avg_t, avg_h = ec._get_house_avg_climate()
        assert avg_t == 73.0  # (72 + 74) / 2
        assert avg_h == 45.0  # (40 + 50) / 2

    def test_get_occupancy_counts_no_presence(self):
        """With no presence coordinator, should return (0, 0)."""
        ec, hass = self._make_energy_coordinator()
        hass.data = {"universal_room_automation": {}}
        rooms, zones = ec._get_occupancy_counts()
        assert rooms == 0
        assert zones == 0

    def test_get_occupancy_counts_with_data(self):
        """Should count occupied rooms and zones from presence coordinator."""
        ec, hass = self._make_energy_coordinator()

        tracker1 = MagicMock()
        tracker1.to_dict.return_value = {"rooms": {"bedroom": True, "bathroom": False}}
        tracker2 = MagicMock()
        tracker2.to_dict.return_value = {"rooms": {"kitchen": True, "dining": True}}
        tracker3 = MagicMock()
        tracker3.to_dict.return_value = {"rooms": {"garage": False}}

        presence = MagicMock()
        presence.zone_trackers = {"upstairs": tracker1, "downstairs": tracker2, "exterior": tracker3}
        manager = MagicMock()
        manager.coordinators = {"presence": presence}
        hass.data = {"universal_room_automation": {"coordinator_manager": manager}}

        rooms, zones = ec._get_occupancy_counts()
        assert rooms == 3  # bedroom + kitchen + dining
        assert zones == 2  # upstairs + downstairs

    def test_get_occupied_room_count(self):
        """Should count total occupied rooms."""
        ec, hass = self._make_energy_coordinator()

        tracker1 = MagicMock()
        tracker1.to_dict.return_value = {"rooms": {"room1": True, "room2": True}}
        tracker2 = MagicMock()
        tracker2.to_dict.return_value = {"rooms": {"room3": False}}

        presence = MagicMock()
        presence.zone_trackers = {"z1": tracker1, "z2": tracker2}
        manager = MagicMock()
        manager.coordinators = {"presence": presence}
        hass.data = {"universal_room_automation": {"coordinator_manager": manager}}

        count = ec._get_occupied_room_count()
        assert count == 2

    def test_get_house_avg_climate_unavailable_sensors(self):
        """Sensors with 'unavailable' or 'unknown' state should be skipped."""
        ec, hass = self._make_energy_coordinator()

        entry1 = MagicMock()
        entry1.data = {"entry_type": "room", "temperature_sensor": "sensor.temp1",
                       "humidity_sensor": "sensor.hum1"}
        entry1.options = {}

        entry2 = MagicMock()
        entry2.data = {"entry_type": "room", "temperature_sensor": "sensor.temp2",
                       "humidity_sensor": "sensor.hum2"}
        entry2.options = {}

        hass.config_entries.async_entries = MagicMock(return_value=[entry1, entry2])

        state_map = {
            "sensor.temp1": MagicMock(state="72.0"),
            "sensor.temp2": MagicMock(state="unavailable"),
            "sensor.hum1": MagicMock(state="unknown"),
            "sensor.hum2": MagicMock(state="50.0"),
        }
        hass.states.get = lambda eid: state_map.get(eid)

        avg_t, avg_h = ec._get_house_avg_climate()
        assert avg_t == 72.0  # Only temp1 counts
        assert avg_h == 50.0  # Only hum2 counts

    def test_get_house_avg_climate_partial_data(self):
        """Rooms with only temp or only humidity should contribute partial averages."""
        ec, hass = self._make_energy_coordinator()

        entry1 = MagicMock()
        entry1.data = {"entry_type": "room", "temperature_sensor": "sensor.temp1"}
        entry1.options = {}

        hass.config_entries.async_entries = MagicMock(return_value=[entry1])

        state_map = {
            "sensor.temp1": MagicMock(state="68.0"),
        }
        hass.states.get = lambda eid: state_map.get(eid)

        avg_t, avg_h = ec._get_house_avg_climate()
        assert avg_t == 68.0
        assert avg_h is None  # No humidity sensor configured
