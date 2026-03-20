"""Tests for v3.6.0 C1: Presence Coordinator.

Tests cover:
- StateInferenceEngine: time-based inference, sleep hours, transitions
- ZonePresenceTracker: mode derivation, override, auto-resume, sleep
- PresenceCoordinator: initialization, zone discovery, state transitions
- Zone presence signal tiers and graceful degradation
- House state override select backing logic
- New constants
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os
import types

# ---------------------------------------------------------------------------
# Mock homeassistant and its submodules before importing URA code.
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
        "utcnow": datetime.utcnow,
        "now": datetime.now,
        "as_local": lambda dt: dt,
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
            # Ensure all required attrs exist on the already-loaded module
            for k, v in attrs.items():
                if not hasattr(existing, k):
                    setattr(existing, k, v)
    else:
        sys.modules.setdefault(name, attrs)

sys.modules.setdefault("aiosqlite", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import importlib

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura

_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_const_mod = importlib.util.module_from_spec(_const_spec)
sys.modules["custom_components.universal_room_automation.const"] = _const_mod
_const_spec.loader.exec_module(_const_mod)
_ura.const = _const_mod

_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc
_ura.domain_coordinators = _dc

for _submod_name in ("signals", "house_state", "base", "coordinator_diagnostics", "manager", "presence"):
    _full_name = f"custom_components.universal_room_automation.domain_coordinators.{_submod_name}"
    _spec = importlib.util.spec_from_file_location(
        _full_name, os.path.join(_dc_path, f"{_submod_name}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full_name] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, _mod)

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from custom_components.universal_room_automation.domain_coordinators.presence import (
    PresenceCoordinator,
    StateInferenceEngine,
    ZonePresenceMode,
    ZonePresenceTracker,
    _CAMERA_OCCUPANCY_TIMEOUT_SECONDS,
    _UNAVAILABLE_STATES,
)
from custom_components.universal_room_automation.domain_coordinators.house_state import (
    HouseState,
    HouseStateMachine,
)
from custom_components.universal_room_automation.domain_coordinators.manager import (
    CoordinatorManager,
)
from custom_components.universal_room_automation.const import (
    CONF_SLEEP_START_HOUR,
    CONF_SLEEP_END_HOUR,
    DEFAULT_SLEEP_START_HOUR,
    DEFAULT_SLEEP_END_HOUR,
    HOUSE_STATE_OVERRIDE_OPTIONS,
    ZONE_PRESENCE_OVERRIDE_OPTIONS,
    ZONE_MODE_AWAY,
    ZONE_MODE_OCCUPIED,
    ZONE_MODE_SLEEP,
    ZONE_MODE_UNKNOWN,
    ZONE_MODE_AUTO,
)


# ============================================================================
# Helpers
# ============================================================================

def make_hass():
    hass = MagicMock()
    hass.data = {}
    hass.states = MagicMock()
    hass.states.async_all.return_value = []
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries.return_value = []
    return hass


# ============================================================================
# StateInferenceEngine Tests
# ============================================================================

class TestStateInferenceEngine:
    """Tests for the state inference engine."""

    def test_nobody_home_returns_away(self):
        engine = StateInferenceEngine()
        result = engine.infer(
            census_count=0,
            current_state=HouseState.HOME_DAY,
            any_zone_occupied=False,
            now=datetime(2026, 3, 1, 14, 0),
        )
        assert result == HouseState.AWAY

    def test_already_away_returns_none(self):
        engine = StateInferenceEngine()
        result = engine.infer(
            census_count=0,
            current_state=HouseState.AWAY,
            any_zone_occupied=False,
            now=datetime(2026, 3, 1, 14, 0),
        )
        assert result is None

    def test_people_arrive_from_away(self):
        engine = StateInferenceEngine()
        result = engine.infer(
            census_count=2,
            current_state=HouseState.AWAY,
            any_zone_occupied=False,
            now=datetime(2026, 3, 1, 14, 0),
        )
        assert result == HouseState.ARRIVING

    def test_arriving_to_home_day(self):
        engine = StateInferenceEngine()
        result = engine.infer(
            census_count=2,
            current_state=HouseState.ARRIVING,
            any_zone_occupied=True,
            now=datetime(2026, 3, 1, 14, 0),
        )
        assert result == HouseState.HOME_DAY

    def test_arriving_to_home_evening(self):
        engine = StateInferenceEngine()
        result = engine.infer(
            census_count=2,
            current_state=HouseState.ARRIVING,
            any_zone_occupied=True,
            now=datetime(2026, 3, 1, 19, 0),
        )
        assert result == HouseState.HOME_EVENING

    def test_home_day_to_home_evening(self):
        engine = StateInferenceEngine()
        result = engine.infer(
            census_count=2,
            current_state=HouseState.HOME_DAY,
            any_zone_occupied=True,
            now=datetime(2026, 3, 1, 19, 0),
        )
        assert result == HouseState.HOME_EVENING

    def test_home_evening_to_home_night(self):
        engine = StateInferenceEngine()
        result = engine.infer(
            census_count=2,
            current_state=HouseState.HOME_EVENING,
            any_zone_occupied=True,
            now=datetime(2026, 3, 1, 21, 30),
        )
        assert result == HouseState.HOME_NIGHT

    def test_sleep_hours_trigger_sleep(self):
        engine = StateInferenceEngine(sleep_start_hour=23, sleep_end_hour=6)
        result = engine.infer(
            census_count=2,
            current_state=HouseState.HOME_NIGHT,
            any_zone_occupied=True,
            now=datetime(2026, 3, 1, 23, 30),
        )
        assert result == HouseState.SLEEP

    def test_waking_from_sleep(self):
        engine = StateInferenceEngine(sleep_start_hour=23, sleep_end_hour=6)
        result = engine.infer(
            census_count=2,
            current_state=HouseState.SLEEP,
            any_zone_occupied=True,
            now=datetime(2026, 3, 1, 7, 0),
        )
        assert result == HouseState.WAKING

    def test_waking_to_home_day(self):
        engine = StateInferenceEngine()
        result = engine.infer(
            census_count=2,
            current_state=HouseState.WAKING,
            any_zone_occupied=True,
            now=datetime(2026, 3, 1, 7, 30),
        )
        assert result == HouseState.HOME_DAY

    def test_zone_occupied_alone_prevents_away(self):
        """Even with census=0, zone occupied keeps us home."""
        engine = StateInferenceEngine()
        result = engine.infer(
            census_count=0,
            current_state=HouseState.HOME_DAY,
            any_zone_occupied=True,
            now=datetime(2026, 3, 1, 14, 0),
        )
        # Should NOT go to AWAY because zone is occupied
        assert result != HouseState.AWAY

    def test_confidence_set(self):
        engine = StateInferenceEngine()
        engine.infer(
            census_count=2,
            current_state=HouseState.AWAY,
            any_zone_occupied=False,
            now=datetime(2026, 3, 1, 14, 0),
        )
        assert engine.confidence > 0

    def test_arriving_with_unidentified_transitions_to_home_not_guest(self):
        """Regression: ARRIVING + unidentified must go to HOME_* first, not GUEST.

        v3.15.1 guest detection included ARRIVING in the check, but GUEST is
        not a valid transition from ARRIVING → state machine deadlock. The fix:
        ARRIVING always transitions to HOME_*, guest detection fires next cycle.
        """
        engine = StateInferenceEngine()
        result = engine.infer(
            census_count=6,
            current_state=HouseState.ARRIVING,
            any_zone_occupied=True,
            now=datetime(2026, 3, 1, 14, 0),
            unidentified_count=2,
        )
        # Must NOT return GUEST (invalid transition from ARRIVING)
        assert result != HouseState.GUEST
        # Must return a valid HOME variant
        assert result == HouseState.HOME_DAY

    def test_home_with_unidentified_transitions_to_guest(self):
        """After ARRIVING→HOME_DAY, unidentified persons trigger GUEST."""
        engine = StateInferenceEngine()
        result = engine.infer(
            census_count=6,
            current_state=HouseState.HOME_DAY,
            any_zone_occupied=True,
            now=datetime(2026, 3, 1, 14, 0),
            unidentified_count=2,
        )
        assert result == HouseState.GUEST


# ============================================================================
# ZonePresenceTracker Tests
# ============================================================================

class TestZonePresenceTracker:

    def test_initial_unknown_no_sensors(self):
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Upstairs", ["Bedroom", "Bathroom"])
        assert tracker.mode == ZonePresenceMode.UNKNOWN

    def test_away_with_sensors(self):
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Upstairs", ["Bedroom"])
        tracker.mark_has_sensors()
        assert tracker.mode == ZonePresenceMode.AWAY

    def test_occupied_on_room_activity(self):
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Upstairs", ["Bedroom"])
        tracker.update_room_occupancy("Bedroom", True)
        assert tracker.mode == ZonePresenceMode.OCCUPIED

    def test_back_to_away_when_clear(self):
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Upstairs", ["Bedroom"])
        tracker.update_room_occupancy("Bedroom", True)
        assert tracker.mode == ZonePresenceMode.OCCUPIED
        tracker.update_room_occupancy("Bedroom", False)
        assert tracker.mode == ZonePresenceMode.AWAY

    def test_override_away(self):
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Upstairs", ["Bedroom"])
        tracker.update_room_occupancy("Bedroom", True)
        tracker.set_override(ZonePresenceMode.AWAY)
        assert tracker.mode == ZonePresenceMode.AWAY
        assert tracker.is_overridden

    def test_override_auto_clears(self):
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Upstairs", ["Bedroom"])
        tracker.set_override(ZonePresenceMode.AWAY)
        assert tracker.is_overridden
        tracker.set_override(ZonePresenceMode.AUTO)
        assert not tracker.is_overridden

    def test_auto_resume_on_presence(self):
        """Override AWAY should auto-clear when presence detected."""
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Upstairs", ["Bedroom"])
        tracker.set_override(ZonePresenceMode.AWAY)
        assert tracker.mode == ZonePresenceMode.AWAY
        # Motion detected in room
        tracker.update_room_occupancy("Bedroom", True)
        # Override should be cleared
        assert not tracker.is_overridden
        assert tracker.mode == ZonePresenceMode.OCCUPIED

    def test_sleep_mode(self):
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Bedrooms", ["Master"])
        tracker.mark_has_sensors()
        tracker.set_sleep(True)
        assert tracker.mode == ZonePresenceMode.SLEEP

    def test_sleep_clears_on_wake(self):
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Bedrooms", ["Master"])
        tracker.set_sleep(True)
        assert tracker.mode == ZonePresenceMode.SLEEP
        tracker.set_sleep(False)
        # Should revert to derived mode
        assert tracker.mode != ZonePresenceMode.SLEEP

    def test_sleep_does_not_override_manual(self):
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Bedrooms", ["Master"])
        tracker.set_override(ZonePresenceMode.OCCUPIED)
        tracker.set_sleep(True)
        # Manual override takes precedence
        assert tracker.mode == ZonePresenceMode.OCCUPIED

    def test_ignores_rooms_not_in_zone(self):
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Upstairs", ["Bedroom"])
        tracker.update_room_occupancy("Kitchen", True)
        # Kitchen not in zone, should not change state
        assert not tracker._has_sensors

    def test_to_dict(self):
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Upstairs", ["Bedroom"])
        tracker.update_room_occupancy("Bedroom", True)
        d = tracker.to_dict()
        assert d["zone_name"] == "Upstairs"
        assert d["mode"] == ZonePresenceMode.OCCUPIED
        assert d["rooms"]["Bedroom"] is True

    def test_multiple_rooms_any_occupied(self):
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Downstairs", ["Kitchen", "Living", "Dining"])
        tracker.update_room_occupancy("Kitchen", False)
        tracker.update_room_occupancy("Living", True)
        assert tracker.mode == ZonePresenceMode.OCCUPIED
        tracker.update_room_occupancy("Living", False)
        assert tracker.mode == ZonePresenceMode.AWAY


# ============================================================================
# PresenceCoordinator Tests
# ============================================================================

class TestPresenceCoordinator:

    def test_initialization(self):
        hass = make_hass()
        coord = PresenceCoordinator(hass, sleep_start_hour=23, sleep_end_hour=6)
        assert coord.coordinator_id == "presence"
        assert coord.priority == 60
        assert coord.name == "Presence Coordinator"

    def test_house_state_override_set_and_clear(self):
        hass = make_hass()
        manager = CoordinatorManager(hass)
        hass.data = {"universal_room_automation": {"coordinator_manager": manager}}

        coord = PresenceCoordinator(hass)
        manager.register_coordinator(coord)

        # Set override to GUEST
        coord.set_house_state_override("guest")
        assert manager.house_state_machine.is_overridden
        assert manager.house_state_machine.state.value == "guest"

        # Clear with auto
        coord.set_house_state_override("auto")
        assert not manager.house_state_machine.is_overridden

    def test_house_state_override_away_propagates_to_zones(self):
        hass = make_hass()
        manager = CoordinatorManager(hass)
        hass.data = {"universal_room_automation": {"coordinator_manager": manager}}

        coord = PresenceCoordinator(hass)
        manager.register_coordinator(coord)

        # Add a zone tracker manually
        tracker = ZonePresenceTracker(hass, "Upstairs", ["Bedroom"])
        tracker.update_room_occupancy("Bedroom", True)
        coord._zone_trackers["Upstairs"] = tracker

        assert tracker.mode == ZonePresenceMode.OCCUPIED

        # Override house to AWAY
        coord.set_house_state_override("away")
        assert tracker.mode == ZonePresenceMode.AWAY

    def test_get_house_state_override_auto(self):
        hass = make_hass()
        manager = CoordinatorManager(hass)
        hass.data = {"universal_room_automation": {"coordinator_manager": manager}}

        coord = PresenceCoordinator(hass)
        manager.register_coordinator(coord)

        assert coord.get_house_state_override() == "auto"

    def test_diagnostics_summary(self):
        hass = make_hass()
        coord = PresenceCoordinator(hass)
        summary = coord.get_diagnostics_summary()
        assert summary["coordinator_id"] == "presence"
        assert "census_count" in summary
        assert "zones" in summary

    def test_evaluate_returns_empty(self):
        """Presence coordinator doesn't generate actions."""
        hass = make_hass()
        coord = PresenceCoordinator(hass)
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            coord.evaluate([], {})
        )
        assert result == []


# ============================================================================
# Constants Tests
# ============================================================================

class TestPresenceConstants:

    def test_sleep_defaults(self):
        assert DEFAULT_SLEEP_START_HOUR == 23
        assert DEFAULT_SLEEP_END_HOUR == 6

    def test_house_state_override_options(self):
        assert "auto" in HOUSE_STATE_OVERRIDE_OPTIONS
        assert "away" in HOUSE_STATE_OVERRIDE_OPTIONS
        assert "sleep" in HOUSE_STATE_OVERRIDE_OPTIONS
        assert len(HOUSE_STATE_OVERRIDE_OPTIONS) == 10  # 9 states + auto

    def test_zone_presence_override_options(self):
        assert "auto" in ZONE_PRESENCE_OVERRIDE_OPTIONS
        assert "away" in ZONE_PRESENCE_OVERRIDE_OPTIONS
        assert "occupied" in ZONE_PRESENCE_OVERRIDE_OPTIONS
        assert "sleep" in ZONE_PRESENCE_OVERRIDE_OPTIONS
        assert len(ZONE_PRESENCE_OVERRIDE_OPTIONS) == 4

    def test_zone_mode_constants(self):
        assert ZONE_MODE_AWAY == "away"
        assert ZONE_MODE_OCCUPIED == "occupied"
        assert ZONE_MODE_SLEEP == "sleep"
        assert ZONE_MODE_UNKNOWN == "unknown"
        assert ZONE_MODE_AUTO == "auto"


# ============================================================================
# ZonePresenceMode Tests
# ============================================================================

class TestZonePresenceMode:

    def test_all_modes(self):
        assert ZonePresenceMode.AWAY == "away"
        assert ZonePresenceMode.OCCUPIED == "occupied"
        assert ZonePresenceMode.SLEEP == "sleep"
        assert ZonePresenceMode.UNKNOWN == "unknown"

    def test_override_options(self):
        assert ZonePresenceMode.AUTO in ZonePresenceMode.OVERRIDE_OPTIONS
        assert len(ZonePresenceMode.OVERRIDE_OPTIONS) == 4


# ============================================================================
# Camera Signal Tier Tests (Tier 2)
# ============================================================================

class TestZoneCameraSignals:
    """Tests for camera-based zone presence detection (Tier 2)."""

    def test_camera_detection_sets_occupied(self):
        """Camera person detection should set zone to occupied."""
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Downstairs", ["Living"])
        tracker.register_camera("binary_sensor.living_person_occupancy")
        tracker.update_camera_detection("binary_sensor.living_person_occupancy", True)
        assert tracker.mode == ZonePresenceMode.OCCUPIED

    def test_camera_detection_timeout(self):
        """Zone stays occupied for timeout duration after camera detection ends."""
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Downstairs", ["Living"])
        tracker.register_camera("binary_sensor.living_person_occupancy")

        # Person detected
        tracker.update_camera_detection("binary_sensor.living_person_occupancy", True)
        assert tracker.mode == ZonePresenceMode.OCCUPIED

        # Person goes away — but within timeout
        tracker.update_camera_detection("binary_sensor.living_person_occupancy", False)
        # Still occupied because last_seen is recent
        assert tracker.mode == ZonePresenceMode.OCCUPIED

    def test_camera_detection_timeout_expires(self):
        """Zone reverts to away after timeout expires."""
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Downstairs", ["Living"])
        tracker.register_camera("binary_sensor.living_person_occupancy")

        # Person detected
        tracker.update_camera_detection("binary_sensor.living_person_occupancy", True)
        # Manually set last_seen to the past
        past_time = datetime.utcnow() - timedelta(seconds=_CAMERA_OCCUPANCY_TIMEOUT_SECONDS + 60)
        tracker._camera_last_seen["binary_sensor.living_person_occupancy"] = past_time
        tracker._camera_occupied["binary_sensor.living_person_occupancy"] = False

        # Timeout expired — should be away (no room sensors either)
        assert tracker.mode == ZonePresenceMode.AWAY

    def test_camera_auto_resume_from_away_override(self):
        """Camera detection clears AWAY override (auto-resume)."""
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Downstairs", ["Living"])
        tracker.register_camera("binary_sensor.living_person_occupancy")
        tracker.set_override(ZonePresenceMode.AWAY)
        assert tracker.mode == ZonePresenceMode.AWAY

        tracker.update_camera_detection("binary_sensor.living_person_occupancy", True)
        assert not tracker.is_overridden
        assert tracker.mode == ZonePresenceMode.OCCUPIED

    def test_camera_signal_tier_tracking(self):
        """Camera registration correctly tracks has_camera_sensors."""
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Downstairs", ["Living"])
        assert not tracker._has_camera_sensors

        tracker.register_camera("binary_sensor.living_person_occupancy")
        assert tracker._has_camera_sensors
        assert tracker.has_sensors

    def test_to_dict_includes_cameras(self):
        """to_dict should include camera detection state."""
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Downstairs", ["Living"])
        tracker.register_camera("binary_sensor.living_person_occupancy")
        tracker.update_camera_detection("binary_sensor.living_person_occupancy", True)
        d = tracker.to_dict()
        assert "cameras" in d
        assert "binary_sensor.living_person_occupancy" in d["cameras"]
        assert d["cameras"]["binary_sensor.living_person_occupancy"]["detecting"] is True
        assert d["signal_tiers"]["camera_sensors"] is True


# ============================================================================
# BLE Signal Tier Tests (Tier 3)
# ============================================================================

class TestZoneBleSignals:
    """Tests for BLE-based zone presence detection (Tier 3)."""

    def test_ble_presence_sets_occupied(self):
        """BLE person presence should set zone to occupied."""
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Upstairs", ["Bedroom"])
        tracker.update_ble_presence(True)
        assert tracker.mode == ZonePresenceMode.OCCUPIED

    def test_ble_presence_clears(self):
        """BLE person leaving should allow zone to return to away."""
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Upstairs", ["Bedroom"])
        tracker.mark_has_sensors()
        tracker.update_ble_presence(True)
        assert tracker.mode == ZonePresenceMode.OCCUPIED
        tracker.update_ble_presence(False)
        assert tracker.mode == ZonePresenceMode.AWAY

    def test_ble_auto_resume_from_away_override(self):
        """BLE detection clears AWAY override."""
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Upstairs", ["Bedroom"])
        tracker.set_override(ZonePresenceMode.AWAY)
        tracker.update_ble_presence(True)
        assert not tracker.is_overridden
        assert tracker.mode == ZonePresenceMode.OCCUPIED


# ============================================================================
# Multi-Tier Signal Tests
# ============================================================================

class TestMultiTierSignals:
    """Tests for interaction between multiple signal tiers."""

    def test_any_tier_sufficient_for_occupied(self):
        """Any single tier detecting presence → occupied."""
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Downstairs", ["Living", "Kitchen"])

        # Tier 1: room sensor
        tracker.update_room_occupancy("Living", True)
        assert tracker.mode == ZonePresenceMode.OCCUPIED
        tracker.update_room_occupancy("Living", False)

        # Tier 2: camera
        tracker.register_camera("binary_sensor.cam_person")
        tracker.update_camera_detection("binary_sensor.cam_person", True)
        assert tracker.mode == ZonePresenceMode.OCCUPIED
        # Force clear camera for next test
        tracker._camera_occupied["binary_sensor.cam_person"] = False
        tracker._camera_last_seen.clear()

        # Tier 3: BLE
        tracker.update_ble_presence(True)
        assert tracker.mode == ZonePresenceMode.OCCUPIED

    def test_all_tiers_off_returns_away(self):
        """When all tiers report no presence → away."""
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Downstairs", ["Living"])
        tracker.mark_has_sensors()
        tracker.register_camera("binary_sensor.cam_person")

        # All tiers off
        tracker.update_room_occupancy("Living", False)
        tracker.update_ble_presence(False)
        # No camera detection history
        assert tracker.mode == ZonePresenceMode.AWAY

    def test_signal_tier_diagnostics(self):
        """to_dict should report which signal tiers are available."""
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Downstairs", ["Living"])
        tracker.register_entity("binary_sensor.living_motion", "Living")
        tracker.register_camera("binary_sensor.cam_person")
        tracker.update_ble_presence(True)

        d = tracker.to_dict()
        assert d["signal_tiers"]["room_sensors"] is True
        assert d["signal_tiers"]["camera_sensors"] is True
        assert d["signal_tiers"]["ble_sensors"] is True


# ============================================================================
# Unavailability Guard Tests
# ============================================================================

class TestUnavailabilityGuards:
    """Tests for entity unavailability handling (lessons from camera_census)."""

    def test_unavailable_states_constant(self):
        """Verify the unavailable states set."""
        assert "unavailable" in _UNAVAILABLE_STATES
        assert "unknown" in _UNAVAILABLE_STATES

    def test_camera_timeout_constant(self):
        """Verify camera timeout is reasonable."""
        assert _CAMERA_OCCUPANCY_TIMEOUT_SECONDS >= 60
        assert _CAMERA_OCCUPANCY_TIMEOUT_SECONDS <= 600

    def test_entity_registration_on_tracker(self):
        """register_entity creates entity→room mapping."""
        hass = make_hass()
        tracker = ZonePresenceTracker(hass, "Upstairs", ["Bedroom"])
        tracker.register_entity("binary_sensor.bedroom_motion", "Bedroom")
        assert tracker._entity_to_room["binary_sensor.bedroom_motion"] == "Bedroom"
        assert tracker._has_room_sensors


# ============================================================================
# Outcome Measurement Tests
# ============================================================================

class TestOutcomeMeasurement:
    """Tests for detection accuracy tracking."""

    def test_initial_accuracy_is_perfect(self):
        hass = make_hass()
        coord = PresenceCoordinator(hass)
        assert coord.detection_accuracy == 1.0
        assert coord.false_positive_rate == 0.0

    def test_true_positive_counted(self):
        hass = make_hass()
        coord = PresenceCoordinator(hass)
        # Simulate a transition that lasted more than 2 minutes
        coord._last_transition_state = HouseState.AWAY
        coord._last_transition_time = datetime.utcnow() - timedelta(minutes=5)
        coord._record_outcome(HouseState.AWAY, HouseState.ARRIVING, "census")
        assert coord._outcome_true_positives == 1
        assert coord._outcome_false_positives == 0

    def test_false_positive_detected(self):
        hass = make_hass()
        coord = PresenceCoordinator(hass)
        # Simulate a transition that was contradicted within 2 minutes
        coord._last_transition_state = HouseState.ARRIVING
        coord._last_transition_time = datetime.utcnow() - timedelta(seconds=30)
        coord._record_outcome(HouseState.ARRIVING, HouseState.AWAY, "census")
        assert coord._outcome_false_positives == 1
        assert coord._outcome_true_positives == 0
        assert coord.false_positive_rate == 1.0

    def test_diagnostics_includes_outcomes(self):
        hass = make_hass()
        coord = PresenceCoordinator(hass)
        summary = coord.get_diagnostics_summary()
        assert "detection_accuracy" in summary
        assert "false_positive_rate" in summary
        assert "outcome_stats" in summary


# ============================================================================
# Zone Decision Logging Tests
# ============================================================================

class TestZoneDecisionLogging:
    """Tests for zone-scoped decision logging."""

    def test_log_zone_mode_change(self):
        """Zone mode changes should be loggable."""
        import asyncio
        hass = make_hass()
        coord = PresenceCoordinator(hass)

        # Mock decision logger
        mock_logger = MagicMock()
        mock_logger.log_decision = AsyncMock()
        coord.decision_logger = mock_logger

        asyncio.get_event_loop().run_until_complete(
            coord._log_zone_mode_change("Upstairs", "away", "occupied", "occupancy_change")
        )
        mock_logger.log_decision.assert_called_once()
        logged = mock_logger.log_decision.call_args[0][0]
        assert logged.scope == "zone:Upstairs"
        assert logged.decision_type == "zone_mode_change"
        assert logged.situation_classified == "occupied"


# ============================================================================
# Geofence Handler Tests
# ============================================================================

class TestGeofenceHandler:
    """Tests for the geofence signal handler and wiring."""

    def test_geofence_arrive_triggers_inference(self):
        hass = make_hass()
        manager = CoordinatorManager(hass)
        hass.data = {"universal_room_automation": {"coordinator_manager": manager}}
        coord = PresenceCoordinator(hass)
        manager.register_coordinator(coord)

        coord.handle_geofence_event("person.alice", "home")
        hass.async_create_task.assert_called()

    def test_geofence_leave_triggers_inference(self):
        hass = make_hass()
        manager = CoordinatorManager(hass)
        hass.data = {"universal_room_automation": {"coordinator_manager": manager}}
        coord = PresenceCoordinator(hass)

        coord.handle_geofence_event("person.alice", "not_home")
        hass.async_create_task.assert_called()

    def test_handle_geofence_change_home_arrival(self):
        """State change callback correctly routes home arrival."""
        hass = make_hass()
        manager = CoordinatorManager(hass)
        hass.data = {"universal_room_automation": {"coordinator_manager": manager}}
        coord = PresenceCoordinator(hass)
        manager.register_coordinator(coord)

        old_state = MagicMock()
        old_state.state = "not_home"
        new_state = MagicMock()
        new_state.state = "home"
        event = MagicMock()
        event.data = {
            "entity_id": "person.alice",
            "old_state": old_state,
            "new_state": new_state,
        }
        coord._handle_geofence_change(event)
        hass.async_create_task.assert_called()

    def test_handle_geofence_change_departure(self):
        """State change callback correctly routes departure."""
        hass = make_hass()
        coord = PresenceCoordinator(hass)

        old_state = MagicMock()
        old_state.state = "home"
        new_state = MagicMock()
        new_state.state = "not_home"
        event = MagicMock()
        event.data = {
            "entity_id": "person.bob",
            "old_state": old_state,
            "new_state": new_state,
        }
        coord._handle_geofence_change(event)
        hass.async_create_task.assert_called()

    def test_handle_geofence_ignores_unavailable(self):
        """Unavailable person entity should be ignored."""
        hass = make_hass()
        coord = PresenceCoordinator(hass)

        new_state = MagicMock()
        new_state.state = "unavailable"
        event = MagicMock()
        event.data = {
            "entity_id": "person.alice",
            "old_state": MagicMock(state="home"),
            "new_state": new_state,
        }
        coord._handle_geofence_change(event)
        hass.async_create_task.assert_not_called()

    def test_handle_geofence_ignores_zone_to_zone(self):
        """Zone-to-zone transition (not home/not_home) should be ignored."""
        hass = make_hass()
        coord = PresenceCoordinator(hass)

        old_state = MagicMock()
        old_state.state = "work"
        new_state = MagicMock()
        new_state.state = "gym"
        event = MagicMock()
        event.data = {
            "entity_id": "person.alice",
            "old_state": old_state,
            "new_state": new_state,
        }
        coord._handle_geofence_change(event)
        hass.async_create_task.assert_not_called()


# ============================================================================
# House State Value Format Tests
# ============================================================================

class TestHouseStateValueFormat:
    """Tests that house state values are plain strings, not enum repr."""

    def test_get_house_state_override_returns_value(self):
        hass = make_hass()
        manager = CoordinatorManager(hass)
        hass.data = {"universal_room_automation": {"coordinator_manager": manager}}
        coord = PresenceCoordinator(hass)
        manager.register_coordinator(coord)

        coord.set_house_state_override("guest")
        result = coord.get_house_state_override()
        assert result == "guest"
        # Must NOT be "HouseState.GUEST"
        assert "HouseState" not in result

    def test_house_state_property_returns_value(self):
        hass = make_hass()
        manager = CoordinatorManager(hass)
        hass.data = {"universal_room_automation": {"coordinator_manager": manager}}
        coord = PresenceCoordinator(hass)
        manager.register_coordinator(coord)

        state = coord.house_state
        assert state == "away"
        assert "HouseState" not in state
