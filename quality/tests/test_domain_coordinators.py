"""Tests for v3.6.0 C0: Domain Coordinator base infrastructure.

Tests cover:
- HouseState enum and HouseStateMachine transitions/hysteresis
- BaseCoordinator abstract interface
- Intent and CoordinatorAction data classes
- ConflictResolver priority-based resolution
- CoordinatorManager intent queue and batch processing
- Severity scoring and effective priority calculation
- Signal data classes
- New constants
- Database schema additions
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os
import types

# ---------------------------------------------------------------------------
# Mock homeassistant and its submodules before importing URA code.
# The quality test suite runs without a real HA installation.
# ---------------------------------------------------------------------------

def _mock_module(name, **attrs):
    """Create a mock module with given attributes."""
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


# Build a comprehensive mock of homeassistant and all submodules.
# This is needed because importing `custom_components.universal_room_automation`
# triggers the full __init__.py import chain.
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
    # homeassistant.const uses MagicMock directly so that any attribute
    # access (STATE_ON, STATE_OFF, etc.) auto-creates a mock value.
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
        "async_call_later": lambda hass, delay, cb: _mock_cls(),
    },
    "homeassistant.helpers.dispatcher": {},
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
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        # attrs is already a mock (e.g., selector)
        sys.modules.setdefault(name, attrs)

# Also mock aiosqlite so database.py can import
sys.modules.setdefault("aiosqlite", MagicMock())

# Now add the project root so custom_components is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Pre-populate the parent package and URA package in sys.modules so that
# importing domain_coordinators submodules with relative imports (from ..const)
# works without triggering the full __init__.py import chain (which fails on
# Python 3.9 due to PEP 604 type unions in automation.py).
import importlib

# Create the package hierarchy manually
_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura

# Import const.py directly (it has no HA dependencies beyond typing)
_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_const_mod = importlib.util.module_from_spec(_const_spec)
sys.modules["custom_components.universal_room_automation.const"] = _const_mod
_const_spec.loader.exec_module(_const_mod)
_ura.const = _const_mod

# Now import the domain_coordinators subpackage
_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc
_ura.domain_coordinators = _dc

# Import each submodule explicitly
for _submod_name in ("signals", "house_state", "base", "manager"):
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

from custom_components.universal_room_automation.domain_coordinators.house_state import (
    HouseState,
    HouseStateMachine,
    VALID_TRANSITIONS,
    DEFAULT_HYSTERESIS,
)
from custom_components.universal_room_automation.domain_coordinators.base import (
    BaseCoordinator,
    CoordinatorAction,
    ConstraintAction,
    Intent,
    NotificationAction,
    ServiceCallAction,
    Severity,
    ActionType,
    SEVERITY_FACTORS,
)
from custom_components.universal_room_automation.domain_coordinators.manager import (
    ConflictResolver,
    CoordinatorManager,
)
from custom_components.universal_room_automation.domain_coordinators.signals import (
    SIGNAL_HOUSE_STATE_CHANGED,
    SIGNAL_ENERGY_CONSTRAINT,
    SIGNAL_COMFORT_REQUEST,
    SIGNAL_CENSUS_UPDATED,
    SIGNAL_SAFETY_HAZARD,
    HouseStateChange,
    EnergyConstraint,
    ComfortRequest,
    SafetyHazard,
)
from custom_components.universal_room_automation.const import (
    CONF_DOMAIN_COORDINATORS_ENABLED,
    RETENTION_DECISION_LOG,
    RETENTION_COMPLIANCE_LOG,
    RETENTION_HOUSE_STATE_LOG,
)


# ============================================================================
# House State Machine Tests
# ============================================================================


class TestHouseState:
    """Test HouseState enum values."""

    def test_all_states_defined(self):
        states = list(HouseState)
        assert len(states) == 9
        assert HouseState.AWAY in states
        assert HouseState.SLEEP in states
        assert HouseState.VACATION in states

    def test_state_string_values(self):
        assert HouseState.AWAY == "away"
        assert HouseState.HOME_DAY == "home_day"
        assert HouseState.SLEEP == "sleep"


class TestHouseStateMachine:
    """Test HouseStateMachine transition logic."""

    def _no_hysteresis(self):
        return {s: 0 for s in HouseState}

    def test_initial_state(self):
        sm = HouseStateMachine(initial_state=HouseState.AWAY)
        assert sm.state == HouseState.AWAY
        assert sm.previous_state is None
        assert not sm.is_overridden

    def test_valid_transition(self):
        sm = HouseStateMachine(HouseState.AWAY, self._no_hysteresis())
        assert sm.transition(HouseState.ARRIVING, trigger="geofence")
        assert sm.state == HouseState.ARRIVING
        assert sm.previous_state == HouseState.AWAY

    def test_invalid_transition_rejected(self):
        sm = HouseStateMachine(HouseState.AWAY, self._no_hysteresis())
        assert not sm.transition(HouseState.SLEEP)
        assert sm.state == HouseState.AWAY

    def test_same_state_rejected(self):
        sm = HouseStateMachine(HouseState.AWAY, self._no_hysteresis())
        assert not sm.transition(HouseState.AWAY)

    def test_hysteresis_blocks_rapid_transition(self):
        sm = HouseStateMachine(HouseState.AWAY, {HouseState.AWAY: 9999})
        assert not sm.transition(HouseState.ARRIVING)

    def test_override_sets_state(self):
        sm = HouseStateMachine(initial_state=HouseState.AWAY)
        sm.set_override(HouseState.SLEEP)
        assert sm.state == HouseState.SLEEP
        assert sm.is_overridden

    def test_clear_override(self):
        sm = HouseStateMachine(initial_state=HouseState.AWAY)
        sm.set_override(HouseState.SLEEP)
        sm.clear_override()
        assert sm.state == HouseState.AWAY
        assert not sm.is_overridden

    def test_force_state_bypasses_all(self):
        sm = HouseStateMachine(HouseState.AWAY, {s: 9999 for s in HouseState})
        sm.force_state(HouseState.SLEEP, trigger="emergency")
        assert sm.state == HouseState.SLEEP
        assert sm.previous_state == HouseState.AWAY

    def test_transition_clears_override(self):
        sm = HouseStateMachine(HouseState.HOME_NIGHT, self._no_hysteresis())
        sm.set_override(HouseState.GUEST)
        assert sm.is_overridden
        sm.transition(HouseState.SLEEP)
        assert not sm.is_overridden
        assert sm.state == HouseState.SLEEP

    def test_to_dict(self):
        sm = HouseStateMachine(initial_state=HouseState.AWAY)
        d = sm.to_dict()
        assert d["state"] == HouseState.AWAY
        assert d["is_overridden"] is False
        assert "state_since" in d
        assert "dwell_seconds" in d

    def test_valid_transitions_completeness(self):
        for state in HouseState:
            assert state in VALID_TRANSITIONS, f"Missing transitions for {state}"

    def test_can_transition(self):
        sm = HouseStateMachine(HouseState.AWAY, self._no_hysteresis())
        assert sm.can_transition(HouseState.ARRIVING)
        assert not sm.can_transition(HouseState.SLEEP)
        assert not sm.can_transition(HouseState.AWAY)

    def test_full_day_cycle(self):
        sm = HouseStateMachine(HouseState.AWAY, self._no_hysteresis())
        for target in [
            HouseState.ARRIVING,
            HouseState.HOME_DAY,
            HouseState.HOME_EVENING,
            HouseState.HOME_NIGHT,
            HouseState.SLEEP,
            HouseState.WAKING,
            HouseState.HOME_DAY,
        ]:
            assert sm.transition(target), f"Failed: {sm.state} -> {target}"
        assert sm.state == HouseState.HOME_DAY

    def test_dwell_seconds_positive(self):
        sm = HouseStateMachine(initial_state=HouseState.AWAY)
        assert sm.dwell_seconds >= 0


# ============================================================================
# Data Class Tests
# ============================================================================


class TestIntent:
    def test_create_intent(self):
        intent = Intent(source="state_change", entity_id="binary_sensor.motion")
        assert intent.source == "state_change"
        assert intent.coordinator_id == ""
        assert isinstance(intent.data, dict)

    def test_intent_with_target(self):
        intent = Intent(source="census", coordinator_id="presence")
        assert intent.coordinator_id == "presence"


class TestCoordinatorAction:
    def test_effective_priority_critical(self):
        action = CoordinatorAction("safety", ActionType.LOG_ONLY, "", Severity.CRITICAL, 1.0)
        assert action.effective_priority == SEVERITY_FACTORS[Severity.CRITICAL]

    def test_effective_priority_low_confidence(self):
        action = CoordinatorAction("comfort", ActionType.LOG_ONLY, "", Severity.LOW, 0.5)
        assert action.effective_priority == SEVERITY_FACTORS[Severity.LOW] * 0.5

    def test_service_call_action(self):
        action = ServiceCallAction(
            coordinator_id="hvac",
            target_device="climate.zone_1",
            severity=Severity.MEDIUM,
            service="climate.set_temperature",
            service_data={"temperature": 72},
        )
        assert action.action_type == ActionType.SERVICE_CALL
        assert action.service == "climate.set_temperature"

    def test_notification_action(self):
        action = NotificationAction(
            coordinator_id="safety",
            target_device="",
            severity=Severity.CRITICAL,
            message="Smoke detected!",
            channels=["imessage", "tts"],
        )
        assert action.action_type == ActionType.NOTIFICATION
        assert "imessage" in action.channels

    def test_constraint_action(self):
        action = ConstraintAction(
            coordinator_id="energy",
            target_device="",
            severity=Severity.MEDIUM,
            constraint_type="hvac_setback",
            constraint_data={"offset": 3},
        )
        assert action.action_type == ActionType.CONSTRAINT
        assert action.constraint_data["offset"] == 3


class TestSeverity:
    def test_ordering(self):
        assert Severity.LOW < Severity.MEDIUM < Severity.HIGH < Severity.CRITICAL

    def test_factors_ordered(self):
        assert SEVERITY_FACTORS[Severity.CRITICAL] > SEVERITY_FACTORS[Severity.HIGH]
        assert SEVERITY_FACTORS[Severity.HIGH] > SEVERITY_FACTORS[Severity.MEDIUM]
        assert SEVERITY_FACTORS[Severity.MEDIUM] > SEVERITY_FACTORS[Severity.LOW]


# ============================================================================
# Conflict Resolver Tests
# ============================================================================


class _MockCoordinator(BaseCoordinator):
    """Concrete coordinator for testing."""

    async def async_setup(self):
        pass

    async def evaluate(self, intents, context):
        return []

    async def async_teardown(self):
        pass


class TestConflictResolver:
    def test_no_conflict_single_action(self):
        resolver = ConflictResolver()
        coord = _MockCoordinator(MagicMock(), "safety", "Safety", 100)
        action = CoordinatorAction("safety", ActionType.SERVICE_CALL, "light.kitchen", Severity.CRITICAL)
        result = resolver.resolve([(coord, action)])
        assert len(result) == 1

    def test_higher_priority_wins(self):
        resolver = ConflictResolver()
        safety = _MockCoordinator(MagicMock(), "safety", "Safety", 100)
        comfort = _MockCoordinator(MagicMock(), "comfort", "Comfort", 20)

        safety_action = CoordinatorAction("safety", ActionType.SERVICE_CALL, "light.lr", Severity.CRITICAL)
        comfort_action = CoordinatorAction("comfort", ActionType.SERVICE_CALL, "light.lr", Severity.LOW)

        result = resolver.resolve([(safety, safety_action), (comfort, comfort_action)])
        assert len(result) == 1
        assert result[0][0].coordinator_id == "safety"

    def test_different_devices_no_conflict(self):
        resolver = ConflictResolver()
        hvac = _MockCoordinator(MagicMock(), "hvac", "HVAC", 30)
        comfort = _MockCoordinator(MagicMock(), "comfort", "Comfort", 20)

        result = resolver.resolve([
            (hvac, CoordinatorAction("hvac", ActionType.SERVICE_CALL, "climate.z1", Severity.MEDIUM)),
            (comfort, CoordinatorAction("comfort", ActionType.SERVICE_CALL, "fan.bed", Severity.MEDIUM)),
        ])
        assert len(result) == 2

    def test_non_device_actions_pass_through(self):
        resolver = ConflictResolver()
        safety = _MockCoordinator(MagicMock(), "safety", "Safety", 100)
        energy = _MockCoordinator(MagicMock(), "energy", "Energy", 40)

        notif = NotificationAction("safety", "", Severity.CRITICAL, message="Alert")
        constraint = ConstraintAction("energy", "", Severity.MEDIUM, constraint_type="setback")

        result = resolver.resolve([(safety, notif), (energy, constraint)])
        assert len(result) == 2

    def test_empty_actions(self):
        assert ConflictResolver().resolve([]) == []

    def test_three_way_conflict(self):
        resolver = ConflictResolver()
        safety = _MockCoordinator(MagicMock(), "safety", "Safety", 100)
        security = _MockCoordinator(MagicMock(), "security", "Security", 80)
        comfort = _MockCoordinator(MagicMock(), "comfort", "Comfort", 20)

        target = "light.hallway"
        result = resolver.resolve([
            (safety, CoordinatorAction("safety", ActionType.SERVICE_CALL, target, Severity.HIGH)),
            (security, CoordinatorAction("security", ActionType.SERVICE_CALL, target, Severity.HIGH)),
            (comfort, CoordinatorAction("comfort", ActionType.SERVICE_CALL, target, Severity.LOW)),
        ])
        assert len(result) == 1
        assert result[0][0].coordinator_id == "safety"

    def test_mixed_device_and_non_device(self):
        resolver = ConflictResolver()
        safety = _MockCoordinator(MagicMock(), "safety", "Safety", 100)
        comfort = _MockCoordinator(MagicMock(), "comfort", "Comfort", 20)

        device_action = CoordinatorAction("safety", ActionType.SERVICE_CALL, "light.a", Severity.HIGH)
        non_device = NotificationAction("comfort", "", Severity.LOW, message="info")

        result = resolver.resolve([(safety, device_action), (comfort, non_device)])
        assert len(result) == 2


# ============================================================================
# Signal Data Class Tests
# ============================================================================


class TestSignalConstants:
    def test_signal_strings(self):
        assert SIGNAL_HOUSE_STATE_CHANGED == "ura_house_state_changed"
        assert SIGNAL_ENERGY_CONSTRAINT == "ura_energy_constraint"
        assert SIGNAL_COMFORT_REQUEST == "ura_comfort_request"
        assert SIGNAL_CENSUS_UPDATED == "ura_census_updated"
        assert SIGNAL_SAFETY_HAZARD == "ura_safety_hazard"


class TestSignalDataClasses:
    def test_house_state_change(self):
        p = HouseStateChange("away", "arriving", 0.95, "geofence")
        assert p.new_state == "arriving"
        assert p.confidence == 0.95

    def test_energy_constraint_defaults(self):
        p = EnergyConstraint(mode="coast", setpoint_offset=3.0)
        assert p.occupied_only is True
        assert p.fan_assist is False
        assert p.max_runtime_minutes is None

    def test_comfort_request(self):
        p = ComfortRequest("kitchen", "main_floor", "zone_adjustment", 74.0)
        assert p.zone == "main_floor"

    def test_safety_hazard(self):
        p = SafetyHazard("smoke", "critical", "binary_sensor.kitchen_smoke")
        assert p.severity == "critical"


# ============================================================================
# Coordinator Manager Tests
# ============================================================================


class TestCoordinatorManager:
    def _make_manager(self):
        hass = MagicMock()
        hass.data = {}
        hass.services = MagicMock()
        return CoordinatorManager(hass), hass

    def test_register_coordinator(self):
        manager, hass = self._make_manager()
        coord = _MockCoordinator(hass, "presence", "Presence", 60)
        manager.register_coordinator(coord)
        assert "presence" in manager.coordinators
        assert manager.coordinators["presence"].priority == 60

    def test_unregister_coordinator(self):
        manager, hass = self._make_manager()
        coord = _MockCoordinator(hass, "presence", "Presence", 60)
        manager.register_coordinator(coord)
        manager.unregister_coordinator("presence")
        assert "presence" not in manager.coordinators

    def test_initial_house_state(self):
        manager, _ = self._make_manager()
        assert manager.house_state == HouseState.AWAY

    def test_get_summary_empty(self):
        manager, _ = self._make_manager()
        summary = manager.get_summary()
        assert summary["coordinators_registered"] == 0
        assert summary["decisions_today"] == 0
        assert "away" in str(summary["house_state"]).lower()

    def test_get_overall_status_not_running(self):
        manager, _ = self._make_manager()
        assert manager.get_overall_status() == "stopped"

    def test_queue_intent_when_not_running(self):
        manager, _ = self._make_manager()
        manager.queue_intent(Intent(source="test"))
        assert len(manager._intent_queue) == 0

    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        manager, hass = self._make_manager()
        coord = _MockCoordinator(hass, "test", "Test", 50)
        coord.async_setup = AsyncMock()
        coord.async_teardown = AsyncMock()
        manager.register_coordinator(coord)

        await manager.async_start()
        assert manager.is_running
        coord.async_setup.assert_called_once()

        await manager.async_stop()
        assert not manager.is_running
        coord.async_teardown.assert_called_once()

    def test_get_summary_with_coordinator(self):
        manager, hass = self._make_manager()
        coord = _MockCoordinator(hass, "safety", "Safety", 100)
        manager.register_coordinator(coord)
        summary = manager.get_summary()
        assert summary["coordinators_registered"] == 1
        assert "safety" in summary

    def test_house_state_machine_accessible(self):
        manager, _ = self._make_manager()
        hsm = manager.house_state_machine
        assert hsm is not None
        assert hasattr(hsm, "transition")
        assert hasattr(hsm, "set_override")

    def test_device_info_identifiers(self):
        manager, _ = self._make_manager()
        info = manager.device_info
        assert ("universal_room_automation", "coordinator_manager") in info.get("identifiers", set())


# ============================================================================
# Const Tests
# ============================================================================


class TestNewConstants:
    def test_domain_coordinators_enabled_const(self):
        assert CONF_DOMAIN_COORDINATORS_ENABLED == "domain_coordinators_enabled"
        assert RETENTION_DECISION_LOG == 90
        assert RETENTION_COMPLIANCE_LOG == 90
        assert RETENTION_HOUSE_STATE_LOG == 365


# ============================================================================
# BaseCoordinator Tests
# ============================================================================


class TestBaseCoordinator:
    def test_mock_coordinator_properties(self):
        hass = MagicMock()
        coord = _MockCoordinator(hass, "safety", "Safety", 100)
        assert coord.coordinator_id == "safety"
        assert coord.name == "Safety"
        assert coord.priority == 100
        assert coord.enabled is True

    def test_disable_coordinator(self):
        coord = _MockCoordinator(MagicMock(), "test", "Test", 50)
        coord.enabled = False
        assert coord.enabled is False

    def test_device_info(self):
        coord = _MockCoordinator(MagicMock(), "safety", "Safety", 100)
        info = coord.device_info
        assert ("universal_room_automation", "coordinator_safety") in info.get("identifiers", set())
