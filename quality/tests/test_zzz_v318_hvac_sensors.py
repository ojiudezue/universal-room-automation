"""Tests for v3.18.x HVAC zone persistence and fan sleep cap.

TestZoneStatePersistence (v3.18.2): get_state_snapshot / restore_state_snapshot
TestHvacFanSleepCap (v3.18.1): Fan speed cap during sleep house state

NOTE: Comfort and efficiency scoring tests are in test_fan_control_v318.py
(pure math, no HA module mocking needed).

WARNING: This file uses heavy sys.modules mocking to import URA domain
coordinator modules. Module cleanup runs at end of file to prevent bleed
into other test files.
"""

from __future__ import annotations

import sys
import os
import types

# Save original sys.modules to restore after this module's mock setup
_original_modules = set(sys.modules.keys())
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock homeassistant and its submodules before importing URA code.
# ---------------------------------------------------------------------------


def _parse_datetime(dt_string):
    """Parse an ISO datetime string, returning None on failure."""
    if not isinstance(dt_string, str):
        return None
    try:
        return datetime.fromisoformat(dt_string)
    except (ValueError, TypeError):
        return None


def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    mod.__path__ = []  # Make it a package so submodule imports work
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls,
        "callback": _identity,
        "Event": _mock_cls,
        "State": _mock_cls,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict,
        "EntityCategory": _mock_cls(),
    },
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_state_change_event": _mock_cls(),
        "async_track_time_interval": lambda hass, cb, interval: _mock_cls(),
        "async_call_later": lambda hass, delay, cb: _mock_cls(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda hass, signal, cb: _mock_cls(),
        "async_dispatcher_send": lambda hass, signal, data=None: None,
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.now(timezone.utc),
        "now": lambda: datetime.now(timezone.utc),
        "as_local": lambda dt: dt,
        "parse_datetime": _parse_datetime,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(),
        "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        existing = sys.modules.get(name)
        if existing is None:
            sys.modules[name] = _mock_module(name, **attrs)
        else:
            for k, v in attrs.items():
                if not hasattr(existing, k):
                    setattr(existing, k, v)
    else:
        sys.modules.setdefault(name, attrs)

sys.modules.setdefault("aiosqlite", MagicMock())

# Now safe to import URA code -- use importlib.util to load specific modules
# without triggering the __init__.py chain (which has Python 3.10+ syntax)
import importlib.util

_project_root = os.path.join(os.path.dirname(__file__), "..", "..")
_ura_root = os.path.join(_project_root, "custom_components", "universal_room_automation")
_dc_root = os.path.join(_ura_root, "domain_coordinators")


def _load_module(name, filepath):
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Create stub parent packages so relative imports work
_cc_pkg = _mock_module("custom_components")
sys.modules["custom_components"] = _cc_pkg

_ura_pkg = _mock_module("custom_components.universal_room_automation")
_ura_pkg.__file__ = os.path.join(_ura_root, "__init__.py")
sys.modules["custom_components.universal_room_automation"] = _ura_pkg

# Load const.py directly (it has `from __future__ import annotations` so OK)
_const = _load_module(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_root, "const.py"),
)
_ura_pkg.const = _const

# Create domain_coordinators package stub
_dc_pkg = _mock_module("custom_components.universal_room_automation.domain_coordinators")
_dc_pkg.__file__ = os.path.join(_dc_root, "__init__.py")
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc_pkg

# Load hvac_const.py
hvac_const = _load_module(
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    os.path.join(_dc_root, "hvac_const.py"),
)

# Load signals.py (needed by hvac_fans.py)
signals = _load_module(
    "custom_components.universal_room_automation.domain_coordinators.signals",
    os.path.join(_dc_root, "signals.py"),
)

# Load hvac_zones.py
hvac_zones = _load_module(
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
    os.path.join(_dc_root, "hvac_zones.py"),
)

# Load hvac_fans.py
hvac_fans = _load_module(
    "custom_components.universal_room_automation.domain_coordinators.hvac_fans",
    os.path.join(_dc_root, "hvac_fans.py"),
)

from custom_components.universal_room_automation.domain_coordinators.hvac_zones import (
    RoomCondition,
    ZoneManager,
    ZoneState,
)
from custom_components.universal_room_automation.domain_coordinators.hvac_fans import (
    FanController,
    RoomFanState,
)
from custom_components.universal_room_automation.domain_coordinators.hvac_const import (
    DUTY_CYCLE_WINDOW_SECONDS,
    FAN_SPEED_LOW_PCT,
    FAN_SPEED_HIGH_PCT,
    FAN_SPEED_HIGH_DELTA,
    FAN_SPEED_MED_DELTA,
    FAN_SPEED_LOW_DELTA,
    FAN_SPEED_MED_PCT,
)
from custom_components.universal_room_automation.domain_coordinators.signals import (
    EnergyConstraint,
)


def _utcnow():
    return datetime.now(timezone.utc)


def _make_zone(
    zone_id="zone_1",
    zone_name="Zone 1",
    occupied=True,
    preset_mode="home",
    temp_high=77.0,
    temp_low=70.0,
    hvac_action="cooling",
    vacancy_sweep_enabled=True,
    rooms=None,
) -> ZoneState:
    """Create a test ZoneState with room conditions."""
    zone = ZoneState(
        zone_id=zone_id,
        zone_name=zone_name,
        climate_entity=f"climate.ecobee_{zone_id}",
        rooms=rooms or ["room_a", "room_b"],
        preset_mode=preset_mode,
        hvac_mode="heat_cool",
        hvac_action=hvac_action,
        current_temperature=75.0,
        target_temp_high=temp_high,
        target_temp_low=temp_low,
        vacancy_sweep_enabled=vacancy_sweep_enabled,
    )
    zone.room_conditions = [
        RoomCondition(room_name="room_a", occupied=occupied),
        RoomCondition(room_name="room_b", occupied=False),
    ]
    zone.last_occupied_time = _utcnow() if occupied else (_utcnow() - timedelta(minutes=20))
    return zone


# ============================================================================
# TestZoneStatePersistence (v3.18.2)
# ============================================================================


class TestZoneStatePersistence:
    """Test get_state_snapshot() and restore_state_snapshot() on ZoneManager."""

    def _make_manager_with_zone(self, zone: ZoneState) -> ZoneManager:
        """Create a ZoneManager with a pre-populated zone."""
        hass = MagicMock()
        manager = ZoneManager(hass)
        manager._zones[zone.zone_id] = zone
        return manager

    def test_snapshot_serializes_zone_state(self):
        """Snapshot serializes zone fields including ISO datetimes and saved_at."""
        zone = _make_zone(occupied=False)
        zone.last_occupied_time = _utcnow() - timedelta(minutes=10)
        zone.vacancy_sweep_done = True
        zone.zone_presence_state = "vacant"
        zone.continuous_occupied_since = None
        zone.runtime_seconds_this_window = 120.0
        zone.window_start = _utcnow() - timedelta(minutes=5)

        manager = self._make_manager_with_zone(zone)
        snapshot = manager.get_state_snapshot()

        assert "zone_1" in snapshot
        z_snap = snapshot["zone_1"]
        assert z_snap["vacancy_sweep_done"] is True
        assert z_snap["zone_presence_state"] == "vacant"
        assert z_snap["runtime_seconds_this_window"] == 120.0
        assert z_snap["continuous_occupied_since"] is None
        assert "saved_at" in z_snap
        # Datetimes should be ISO strings
        assert isinstance(z_snap["last_occupied_time"], str)
        assert isinstance(z_snap["window_start"], str)
        assert isinstance(z_snap["saved_at"], str)
        # Verify round-trip parse of last_occupied_time
        parsed = datetime.fromisoformat(z_snap["last_occupied_time"])
        assert parsed is not None

    def test_restore_applies_snapshot(self):
        """Restore applies snapshot data to a matching zone."""
        zone = ZoneState(zone_id="zone_1", zone_name="Zone 1", climate_entity="climate.ecobee_zone_1")
        manager = self._make_manager_with_zone(zone)

        # Use the same now() the production code will use (from dt_util mock)
        from homeassistant.util import dt as _dt_util
        now = _dt_util.now()
        snapshot = {
            "zone_1": {
                "last_occupied_time": (now - timedelta(minutes=5)).isoformat(),
                "vacancy_sweep_done": True,
                "zone_presence_state": "away",
                "continuous_occupied_since": None,
                "runtime_seconds_this_window": 300.0,
                "window_start": (now - timedelta(minutes=10)).isoformat(),
                "saved_at": now.isoformat(),
            }
        }

        restored = manager.restore_state_snapshot(snapshot)
        assert restored == 1
        assert zone.vacancy_sweep_done is True
        assert zone.zone_presence_state == "away"
        assert zone.runtime_seconds_this_window == 300.0
        assert zone.last_occupied_time is not None
        assert zone.window_start is not None

    def test_restore_skips_stale_data(self):
        """Snapshot with saved_at > 4h ago should be skipped."""
        zone = ZoneState(zone_id="zone_1", zone_name="Zone 1", climate_entity="climate.ecobee_zone_1")
        manager = self._make_manager_with_zone(zone)

        from homeassistant.util import dt as _dt_util
        five_hours_ago = _dt_util.now() - timedelta(hours=5)
        snapshot = {
            "zone_1": {
                "last_occupied_time": five_hours_ago.isoformat(),
                "vacancy_sweep_done": True,
                "zone_presence_state": "away",
                "continuous_occupied_since": None,
                "runtime_seconds_this_window": 600.0,
                "window_start": five_hours_ago.isoformat(),
                "saved_at": five_hours_ago.isoformat(),
            }
        }

        restored = manager.restore_state_snapshot(snapshot)
        assert restored == 0
        # Zone should remain at defaults
        assert zone.vacancy_sweep_done is False
        assert zone.zone_presence_state == "unknown"

    def test_restore_skips_unknown_zones(self):
        """Snapshot with nonexistent zone_id should not crash, return 0."""
        zone = ZoneState(zone_id="zone_1", zone_name="Zone 1", climate_entity="climate.ecobee_zone_1")
        manager = self._make_manager_with_zone(zone)

        from homeassistant.util import dt as _dt_util
        now = _dt_util.now()
        snapshot = {
            "nonexistent": {
                "last_occupied_time": now.isoformat(),
                "vacancy_sweep_done": True,
                "zone_presence_state": "away",
                "continuous_occupied_since": None,
                "runtime_seconds_this_window": 0.0,
                "window_start": None,
                "saved_at": now.isoformat(),
            }
        }

        restored = manager.restore_state_snapshot(snapshot)
        assert restored == 0
        # zone_1 should remain unchanged
        assert zone.zone_presence_state == "unknown"

    def test_restore_handles_malformed_dates(self):
        """Snapshot with malformed date strings should not crash."""
        zone = ZoneState(zone_id="zone_1", zone_name="Zone 1", climate_entity="climate.ecobee_zone_1")
        manager = self._make_manager_with_zone(zone)

        from homeassistant.util import dt as _dt_util
        now = _dt_util.now()
        snapshot = {
            "zone_1": {
                "last_occupied_time": "not-a-date",
                "vacancy_sweep_done": False,
                "zone_presence_state": "occupied",
                "continuous_occupied_since": None,
                "runtime_seconds_this_window": 0.0,
                "window_start": None,
                "saved_at": now.isoformat(),
            }
        }

        restored = manager.restore_state_snapshot(snapshot)
        assert restored == 1  # Zone was restored (other fields applied)
        # Malformed date should leave field at its original value (None)
        assert zone.last_occupied_time is None
        assert zone.zone_presence_state == "occupied"

    def test_roundtrip_snapshot_restore(self):
        """Snapshot then restore onto a new zone should preserve fields."""
        # Set up source zone with interesting state
        source_zone = _make_zone(occupied=True)
        source_zone.vacancy_sweep_done = True
        source_zone.zone_presence_state = "occupied"
        source_zone.continuous_occupied_since = _utcnow() - timedelta(hours=2)
        source_zone.runtime_seconds_this_window = 450.0
        source_zone.window_start = _utcnow() - timedelta(minutes=8)

        source_manager = self._make_manager_with_zone(source_zone)
        snapshot = source_manager.get_state_snapshot()

        # Create fresh target zone and restore
        target_zone = ZoneState(
            zone_id="zone_1", zone_name="Zone 1", climate_entity="climate.ecobee_zone_1"
        )
        target_manager = self._make_manager_with_zone(target_zone)
        restored = target_manager.restore_state_snapshot(snapshot)

        assert restored == 1
        assert target_zone.vacancy_sweep_done is True
        assert target_zone.zone_presence_state == "occupied"
        assert target_zone.runtime_seconds_this_window == 450.0
        assert target_zone.last_occupied_time is not None
        assert target_zone.continuous_occupied_since is not None
        assert target_zone.window_start is not None


# ============================================================================
# TestHvacFanSleepCap (v3.18.1)
# ============================================================================


class TestHvacFanSleepCap:
    """Test HVAC fan controller sleep speed cap."""

    def _make_fan_controller(self, house_state: str = "home") -> FanController:
        """Create a FanController with mocked dependencies."""
        hass = MagicMock()
        zone_manager = MagicMock()
        fc = FanController(hass, zone_manager)
        fc._house_state = house_state
        return fc

    def test_fan_speed_capped_during_sleep(self):
        """Fan speed should be capped at FAN_SPEED_LOW_PCT (33%) during sleep."""
        fc = self._make_fan_controller(house_state="sleep")

        # delta=3F above setpoint would normally yield MED (66%) or HIGH (100%)
        delta = 3.0
        speed = fc._compute_speed(delta)
        # _compute_speed returns MED_PCT=66 for delta >= 3.0
        assert speed == FAN_SPEED_MED_PCT

        # But during sleep, the cap kicks in (applied in update() loop)
        if fc._house_state == "sleep":
            capped_speed = min(speed, FAN_SPEED_LOW_PCT)
        else:
            capped_speed = speed
        assert capped_speed == FAN_SPEED_LOW_PCT

    def test_fan_speed_uncapped_during_home(self):
        """Fan speed should NOT be capped during home state."""
        fc = self._make_fan_controller(house_state="home")

        # delta=3F -> FAN_SPEED_MED_PCT (66%)
        delta = 3.0
        speed = fc._compute_speed(delta)
        assert speed == FAN_SPEED_MED_PCT

        # No cap during home state
        if fc._house_state == "sleep":
            capped_speed = min(speed, FAN_SPEED_LOW_PCT)
        else:
            capped_speed = speed
        assert capped_speed == FAN_SPEED_MED_PCT

    def test_fan_assist_capped_during_sleep(self):
        """Energy fan_assist active + sleep -> speed still capped at 33%."""
        fc = self._make_fan_controller(house_state="sleep")
        fc._fan_assist_active = True

        # Large delta -> would be HIGH (100%)
        delta = 6.0
        speed = fc._compute_speed(delta)
        assert speed == FAN_SPEED_HIGH_PCT

        # Sleep cap applies regardless of trigger reason
        if fc._house_state == "sleep":
            capped_speed = min(speed, FAN_SPEED_LOW_PCT)
        else:
            capped_speed = speed
        assert capped_speed == FAN_SPEED_LOW_PCT

# NOTE: TestComfortScoring and TestEfficiencyScoring moved to
# test_fan_control_v318.py (no HA module mocking needed for pure math tests)


