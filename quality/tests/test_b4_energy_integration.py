"""Tests for B4 Layer 1: Energy Integration — Config + Data Foundation.

Covers:
- D1: Multi-energy sensor config (migration, summation)
- D1b: Zone/house sensor constants
- D1c: Attribution model (4-tier delta)
- D2: Room power profile learning (EMA, standby, cold start, persistence)
"""

import os
import sys
import types
from unittest.mock import MagicMock

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
    "homeassistant.core": {
        "HomeAssistant": _mock_cls, "callback": _identity,
        "CALLBACK_TYPE": _mock_cls, "Event": _mock_cls,
        "State": _mock_cls, "ServiceCall": _mock_cls,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": _mock_cls()},
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.event": {
        "async_track_time_interval": MagicMock(),
        "async_call_later": MagicMock(),
        "async_track_state_change_event": MagicMock(),
        "async_track_time_change": MagicMock(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": MagicMock(),
        "async_dispatcher_send": MagicMock(),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.restore_state": {
        "RestoreEntity": type("RestoreEntity", (), {}),
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
    "homeassistant.components.switch": {
        "SwitchEntity": type("SwitchEntity", (), {}),
    },
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
    "homeassistant.components.number": {
        "NumberEntity": type("NumberEntity", (), {}),
        "NumberMode": MagicMock(),
    },
    "homeassistant.components.select": {
        "SelectEntity": type("SelectEntity", (), {}),
    },
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": MagicMock(), "now": MagicMock(),
        "as_local": lambda dt: dt,
    },
    "aiosqlite": MagicMock(),
    "voluptuous": MagicMock(),
}

for mod_name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(mod_name, _mock_module(mod_name, **attrs))
    else:
        sys.modules.setdefault(mod_name, attrs)

# Insert project root for imports
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# ---------------------------------------------------------------------------
# Bypass __init__.py: register the URA package as a namespace stub
# so we can import individual modules without triggering the full chain.
# ---------------------------------------------------------------------------
import importlib

_ura_pkg = "custom_components.universal_room_automation"
if _ura_pkg not in sys.modules:
    _stub = types.ModuleType(_ura_pkg)
    _stub.__path__ = [
        os.path.join(_project_root, "custom_components", "universal_room_automation")
    ]
    _stub.__package__ = _ura_pkg
    sys.modules[_ura_pkg] = _stub

    # Also stub the parent packages
    for _p in ["custom_components"]:
        if _p not in sys.modules:
            _pp = types.ModuleType(_p)
            _pp.__path__ = [os.path.join(_project_root, _p)]
            _pp.__package__ = _p
            sys.modules[_p] = _pp

import pytest

# ---------------------------------------------------------------------------
# Now import specific URA modules (bypasses __init__.py)
# ---------------------------------------------------------------------------

const_mod = importlib.import_module(
    "custom_components.universal_room_automation.const")

CONF_ENERGY_SENSOR = const_mod.CONF_ENERGY_SENSOR
CONF_ENERGY_SENSORS = const_mod.CONF_ENERGY_SENSORS
CONF_WHOLE_HOUSE_POWER_SENSOR = const_mod.CONF_WHOLE_HOUSE_POWER_SENSOR
CONF_WHOLE_HOUSE_POWER_SENSORS = const_mod.CONF_WHOLE_HOUSE_POWER_SENSORS
CONF_WHOLE_HOUSE_ENERGY_SENSOR = const_mod.CONF_WHOLE_HOUSE_ENERGY_SENSOR
CONF_WHOLE_HOUSE_ENERGY_SENSORS = const_mod.CONF_WHOLE_HOUSE_ENERGY_SENSORS
CONF_ZONE_POWER_SENSORS = const_mod.CONF_ZONE_POWER_SENSORS
CONF_ZONE_ENERGY_SENSORS = const_mod.CONF_ZONE_ENERGY_SENSORS
CONF_HOUSE_DEVICE_POWER_SENSORS = const_mod.CONF_HOUSE_DEVICE_POWER_SENSORS
CONF_HOUSE_DEVICE_ENERGY_SENSORS = const_mod.CONF_HOUSE_DEVICE_ENERGY_SENSORS

# Stub the domain_coordinators subpackage
_dc_pkg = f"{_ura_pkg}.domain_coordinators"
if _dc_pkg not in sys.modules:
    _dc_stub = types.ModuleType(_dc_pkg)
    _dc_stub.__path__ = [
        os.path.join(_project_root, "custom_components",
                     "universal_room_automation", "domain_coordinators")
    ]
    _dc_stub.__package__ = _dc_pkg
    sys.modules[_dc_pkg] = _dc_stub

forecast_mod = importlib.import_module(
    "custom_components.universal_room_automation.domain_coordinators.energy_forecast")

RoomPowerProfile = forecast_mod.RoomPowerProfile
MIN_SAMPLES_PER_CELL = forecast_mod.MIN_SAMPLES_PER_CELL
EMA_ALPHA = forecast_mod.EMA_ALPHA
get_time_bin = forecast_mod.get_time_bin
BIN_HOURS = forecast_mod.BIN_HOURS


# ============================================================================
# D1: Multi-energy sensor constants
# ============================================================================

class TestEnergyConstants:
    """Verify new constants exist and are distinct from legacy."""

    def test_plural_energy_sensor_const_exists(self):
        assert CONF_ENERGY_SENSORS == "energy_sensors"

    def test_legacy_energy_sensor_const_preserved(self):
        assert CONF_ENERGY_SENSOR == "energy_sensor"

    def test_plural_differs_from_singular(self):
        assert CONF_ENERGY_SENSORS != CONF_ENERGY_SENSOR

    def test_whole_house_plural_consts_exist(self):
        assert CONF_WHOLE_HOUSE_POWER_SENSORS == "whole_house_power_sensors"
        assert CONF_WHOLE_HOUSE_ENERGY_SENSORS == "whole_house_energy_sensors"

    def test_zone_sensor_consts_exist(self):
        assert CONF_ZONE_POWER_SENSORS == "zone_power_sensors"
        assert CONF_ZONE_ENERGY_SENSORS == "zone_energy_sensors"

    def test_house_device_sensor_consts_exist(self):
        assert CONF_HOUSE_DEVICE_POWER_SENSORS == "house_device_power_sensors"
        assert CONF_HOUSE_DEVICE_ENERGY_SENSORS == "house_device_energy_sensors"


# ============================================================================
# D2: Room Power Profile Learning
# ============================================================================

class TestRoomPowerProfile:
    """Test EMA learning, standby detection, cold start, and persistence."""

    def test_cold_start_first_observation(self):
        """First observation seeds the EMA directly."""
        profile = RoomPowerProfile()
        profile.update("kitchen", 2, 0, 350.0, True)

        # Below MIN_SAMPLES, should return None
        assert profile.get_baseline_watts("kitchen", 2, 0) is None

        # But internal state should exist
        cell = profile._profiles["kitchen"][(2, 0)]
        assert cell["avg_watts"] == 350.0
        assert cell["samples"] == 1

    def test_ema_convergence(self):
        """After many observations at the same value, EMA converges."""
        profile = RoomPowerProfile()
        for _ in range(50):
            profile.update("kitchen", 2, 0, 400.0, True)

        result = profile.get_baseline_watts("kitchen", 2, 0)
        assert result is not None
        assert abs(result - 400.0) < 1.0  # Should be very close to 400

    def test_ema_responds_to_change(self):
        """EMA tracks changes in power draw."""
        profile = RoomPowerProfile()
        # Establish baseline at 200W
        for _ in range(30):
            profile.update("study", 3, 0, 200.0, True)

        # Shift to 600W
        for _ in range(30):
            profile.update("study", 3, 0, 600.0, True)

        result = profile.get_baseline_watts("study", 3, 0)
        assert result is not None
        # Should have moved significantly toward 600 but not fully
        assert result > 300.0

    def test_cold_start_threshold(self):
        """Returns None below MIN_SAMPLES_PER_CELL."""
        profile = RoomPowerProfile()
        for _ in range(MIN_SAMPLES_PER_CELL - 1):
            profile.update("bedroom", 1, 1, 100.0, True)

        assert profile.get_baseline_watts("bedroom", 1, 1) is None

        # One more should cross threshold
        profile.update("bedroom", 1, 1, 100.0, True)
        assert profile.get_baseline_watts("bedroom", 1, 1) is not None

    def test_separate_day_types(self):
        """Weekday and weekend tracked independently."""
        profile = RoomPowerProfile()
        for _ in range(25):
            profile.update("living", 4, 0, 500.0, True)  # weekday evening
            profile.update("living", 4, 1, 800.0, True)  # weekend evening

        weekday = profile.get_baseline_watts("living", 4, 0)
        weekend = profile.get_baseline_watts("living", 4, 1)
        assert weekday is not None
        assert weekend is not None
        assert abs(weekday - 500.0) < 50.0
        assert abs(weekend - 800.0) < 50.0

    def test_standby_learning_from_night_vacant(self):
        """Standby watts learned from NIGHT bin when room is vacant."""
        profile = RoomPowerProfile()
        for _ in range(25):
            profile.update("garage", 0, 0, 45.0, False)  # NIGHT, vacant

        standby = profile.get_standby_watts("garage")
        assert standby is not None
        assert abs(standby - 45.0) < 5.0

    def test_standby_not_learned_when_occupied(self):
        """Standby is NOT updated when room is occupied during NIGHT."""
        profile = RoomPowerProfile()
        for _ in range(25):
            profile.update("bedroom", 0, 0, 200.0, True)  # occupied at night

        assert profile.get_standby_watts("bedroom") is None

    def test_standby_not_learned_from_non_night_bins(self):
        """Standby only learned from NIGHT bin (time_bin=0)."""
        profile = RoomPowerProfile()
        for _ in range(25):
            profile.update("office", 2, 0, 30.0, False)  # MIDDAY, vacant

        assert profile.get_standby_watts("office") is None

    def test_unknown_room_returns_none(self):
        assert RoomPowerProfile().get_baseline_watts("nonexistent", 1, 0) is None
        assert RoomPowerProfile().get_standby_watts("nonexistent") is None

    def test_multiple_rooms_independent(self):
        """Different rooms don't interfere with each other."""
        profile = RoomPowerProfile()
        for _ in range(25):
            profile.update("room_a", 2, 0, 100.0, True)
            profile.update("room_b", 2, 0, 500.0, True)

        a = profile.get_baseline_watts("room_a", 2, 0)
        b = profile.get_baseline_watts("room_b", 2, 0)
        assert a is not None and b is not None
        assert abs(a - 100.0) < 15.0
        assert abs(b - 500.0) < 50.0


class TestRoomPowerProfilePersistence:
    """Test save/restore round-trip."""

    def test_get_all_profiles_format(self):
        """get_all_profiles returns flat dicts suitable for DB."""
        profile = RoomPowerProfile()
        profile.update("kitchen", 2, 0, 350.0, True)

        rows = profile.get_all_profiles()
        assert len(rows) == 1
        row = rows[0]
        assert row["room_id"] == "kitchen"
        assert row["time_bin"] == 2
        assert row["day_type"] == 0
        assert row["avg_watts"] == 350.0
        assert row["sample_count"] == 1

    def test_standby_persisted_as_virtual_row(self):
        """Standby data persisted with time_bin=-1, day_type=-1."""
        profile = RoomPowerProfile()
        profile.update("garage", 0, 0, 50.0, False)

        rows = profile.get_all_profiles()
        standby_rows = [r for r in rows if r["time_bin"] == -1]
        assert len(standby_rows) == 1
        assert standby_rows[0]["room_id"] == "garage"
        assert standby_rows[0]["day_type"] == -1

    def test_round_trip(self):
        """Save then restore preserves data."""
        original = RoomPowerProfile()
        for _ in range(25):
            original.update("kitchen", 2, 0, 400.0, True)
            original.update("kitchen", 0, 0, 60.0, False)  # standby

        rows = original.get_all_profiles()

        restored = RoomPowerProfile()
        count = restored.restore_from_rows(rows)
        assert count == len(rows)

        # Baseline should match
        orig_val = original.get_baseline_watts("kitchen", 2, 0)
        rest_val = restored.get_baseline_watts("kitchen", 2, 0)
        assert orig_val is not None and rest_val is not None
        assert abs(orig_val - rest_val) < 0.01

        # Standby should match
        orig_standby = original.get_standby_watts("kitchen")
        rest_standby = restored.get_standby_watts("kitchen")
        assert orig_standby is not None and rest_standby is not None
        assert abs(orig_standby - rest_standby) < 0.01

    def test_restore_with_empty_rows(self):
        profile = RoomPowerProfile()
        assert profile.restore_from_rows([]) == 0

    def test_restore_with_invalid_rows(self):
        profile = RoomPowerProfile()
        count = profile.restore_from_rows([
            {"room_id": "", "time_bin": 0, "day_type": 0, "avg_watts": 100},
            {"room_id": "x", "time_bin": 0, "day_type": 0, "avg_watts": None},
        ])
        assert count == 0


class TestTimeBinHelper:
    """Test get_time_bin and BIN_HOURS."""

    def test_night_hours(self):
        for h in range(0, 6):
            assert get_time_bin(h) == 0

    def test_morning_hours(self):
        for h in range(6, 9):
            assert get_time_bin(h) == 1

    def test_midday_hours(self):
        for h in range(9, 12):
            assert get_time_bin(h) == 2

    def test_afternoon_hours(self):
        for h in range(12, 17):
            assert get_time_bin(h) == 3

    def test_evening_hours(self):
        for h in range(17, 21):
            assert get_time_bin(h) == 4

    def test_late_hours(self):
        for h in range(21, 24):
            assert get_time_bin(h) == 5

    def test_bin_hours_sum_to_24(self):
        assert sum(BIN_HOURS.values()) == 24


class TestProfileStatus:
    """Test get_status summary."""

    def test_empty_status(self):
        status = RoomPowerProfile().get_status()
        assert status["rooms_tracked"] == 0
        assert status["total_cells"] == 0
        assert status["mature_cells"] == 0
        assert status["rooms_with_standby"] == 0

    def test_status_tracks_maturity(self):
        profile = RoomPowerProfile()
        for _ in range(MIN_SAMPLES_PER_CELL + 5):
            profile.update("kitchen", 2, 0, 300.0, True)

        status = profile.get_status()
        assert status["rooms_tracked"] == 1
        assert status["total_cells"] == 1
        assert status["mature_cells"] == 1
        assert status["min_samples_threshold"] == MIN_SAMPLES_PER_CELL
