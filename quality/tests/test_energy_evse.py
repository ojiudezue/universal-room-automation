"""Tests for v3.11.0 EVSE refinement — battery hold + excess solar charging.

Validates:
- C1: EVSE battery hold — battery reserve = SOC when EVSEs charge
- C2: Excess solar — turn on EVSEs when SOC >= threshold and forecast remaining >= kWh
"""

import pytest
from unittest.mock import MagicMock
import sys
import os
import types
import importlib

# ---------------------------------------------------------------------------
# Mock homeassistant before importing URA code (same pattern as other tests)
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
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": _mock_cls()},
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {},
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
        "utcnow": __import__("datetime").datetime.utcnow,
        "now": __import__("datetime").datetime.now,
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
    "homeassistant.components.button": {"ButtonEntity": type("ButtonEntity", (), {})},
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)

sys.modules.setdefault("aiosqlite", MagicMock())

# Add project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Build package hierarchy
_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura

# Import const.py
_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_const_mod = importlib.util.module_from_spec(_const_spec)
sys.modules["custom_components.universal_room_automation.const"] = _const_mod
_const_spec.loader.exec_module(_const_mod)
_ura.const = _const_mod

# Import domain_coordinators subpackage
_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc
_ura.domain_coordinators = _dc

# Import energy_const and energy_pool
for _submod_name in ("energy_const", "energy_pool"):
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

from conftest import MockHass, MockState

from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
    EVChargerController,
    DEFAULT_EVSE_ENTITIES,
)


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

class _EVSEHarness:
    """Test harness for EVChargerController."""

    def __init__(self, garage_a_on=False, garage_a_power=0.0,
                 garage_b_on=False, garage_b_power=0.0):
        self.hass = MockHass()
        # Set EVSE states
        self.hass.set_state("switch.garage_a", "on" if garage_a_on else "off")
        self.hass.set_state("sensor.garage_a_power_minute_average", str(garage_a_power))
        self.hass.set_state("sensor.garage_a_energy_today", "0")
        self.hass.set_state("sensor.garage_a_energy_this_month", "0")
        self.hass.set_state("switch.garage_b", "on" if garage_b_on else "off")
        self.hass.set_state("sensor.garage_b_power_minute_average", str(garage_b_power))
        self.hass.set_state("sensor.garage_b_energy_today", "0")
        self.hass.set_state("sensor.garage_b_energy_this_month", "0")
        self.ev = EVChargerController(self.hass)


# ── C1 checks (via direct state inspection) ──────────────────────────────

class TestEVSECharging:
    """EVChargerController._get_evse_state() correctly detects charging."""

    def test_evse_charging_detected(self):
        h = _EVSEHarness(garage_a_on=True, garage_a_power=5000.0)
        state = h.ev._get_evse_state("garage_a")
        assert state["charging"] is True

    def test_evse_not_charging_low_power(self):
        h = _EVSEHarness(garage_a_on=True, garage_a_power=50.0)
        state = h.ev._get_evse_state("garage_a")
        assert state["charging"] is False

    def test_evse_off_not_charging(self):
        h = _EVSEHarness(garage_a_on=False, garage_a_power=0.0)
        state = h.ev._get_evse_state("garage_a")
        assert state["charging"] is False


# ── C2: Excess solar EVSE charging ───────────────────────────────────────

class TestExcessSolar:
    """Excess solar charging: SOC >= threshold AND forecast remaining >= kWh."""

    def test_excess_solar_turns_on_evse(self):
        """SOC 96% + 6 kWh remaining → turn on."""
        h = _EVSEHarness(garage_a_on=False, garage_b_on=False)
        actions = h.ev.determine_excess_solar_actions(
            soc=96.0, remaining_forecast_kwh=6.0, tou_period="off_peak",
        )
        # Should turn on both EVSEs
        assert len(actions) == 2
        assert all(a["service"] == "switch.turn_on" for a in actions)
        assert len(h.ev._excess_solar_active) == 2

    def test_excess_solar_not_during_peak(self):
        """Never during peak — battery needed for home load."""
        h = _EVSEHarness(garage_a_on=False)
        actions = h.ev.determine_excess_solar_actions(
            soc=96.0, remaining_forecast_kwh=6.0, tou_period="peak",
        )
        assert len(actions) == 0

    def test_excess_solar_turns_off_when_conditions_drop(self):
        """Conditions met → activate, then conditions drop → deactivate."""
        h = _EVSEHarness(garage_a_on=False, garage_b_on=False)
        # Activate
        h.ev.determine_excess_solar_actions(
            soc=96.0, remaining_forecast_kwh=6.0, tou_period="off_peak",
        )
        assert len(h.ev._excess_solar_active) == 2

        # Simulate EVSEs now on
        h.hass.set_state("switch.garage_a", "on")
        h.hass.set_state("switch.garage_b", "on")

        # SOC drops below threshold
        actions = h.ev.determine_excess_solar_actions(
            soc=90.0, remaining_forecast_kwh=6.0, tou_period="off_peak",
        )
        assert len(actions) == 2
        assert all(a["service"] == "switch.turn_off" for a in actions)
        assert len(h.ev._excess_solar_active) == 0

    def test_excess_solar_low_forecast_no_activate(self):
        """High SOC but low remaining forecast → don't activate."""
        h = _EVSEHarness(garage_a_on=False)
        actions = h.ev.determine_excess_solar_actions(
            soc=96.0, remaining_forecast_kwh=3.0, tou_period="off_peak",
        )
        assert len(actions) == 0

    def test_excess_solar_custom_thresholds(self):
        """Custom thresholds: SOC 90 with threshold 88 should activate."""
        h = _EVSEHarness(garage_a_on=False, garage_b_on=False)
        actions = h.ev.determine_excess_solar_actions(
            soc=90.0, remaining_forecast_kwh=3.0, tou_period="off_peak",
            soc_threshold=88, kwh_threshold=2.0,
        )
        assert len(actions) == 2

    def test_excess_solar_only_turns_off_own_evses(self):
        """Only turn off EVSEs that excess solar turned on."""
        h = _EVSEHarness(garage_a_on=True, garage_b_on=False)
        # Only B is off, so excess solar only turns on B
        actions = h.ev.determine_excess_solar_actions(
            soc=96.0, remaining_forecast_kwh=6.0, tou_period="off_peak",
        )
        turned_on_ids = [a["target"] for a in actions]
        assert "switch.garage_b" in turned_on_ids
        assert "switch.garage_a" not in turned_on_ids  # Already on, not ours

    def test_excess_solar_peak_turns_off_active(self):
        """If excess solar EVSEs are active and we enter peak, turn them off."""
        h = _EVSEHarness(garage_a_on=False, garage_b_on=False)
        # Activate during off-peak
        h.ev.determine_excess_solar_actions(
            soc=96.0, remaining_forecast_kwh=6.0, tou_period="off_peak",
        )
        assert len(h.ev._excess_solar_active) == 2

        # Simulate EVSEs now on (as they would be after activation)
        h.hass.set_state("switch.garage_a", "on")
        h.hass.set_state("switch.garage_b", "on")

        # Peak period — should turn off
        actions = h.ev.determine_excess_solar_actions(
            soc=96.0, remaining_forecast_kwh=6.0, tou_period="peak",
        )
        assert len(actions) == 2
        assert all(a["service"] == "switch.turn_off" for a in actions)


# ── EV Status includes new fields ────────────────────────────────────────

class TestEVStatusFields:
    """EV status should include excess solar fields."""

    def test_status_includes_excess_solar_fields(self):
        h = _EVSEHarness()
        status = h.ev.get_status()
        assert "excess_solar_active" in status
        assert "excess_solar_evses" in status
        assert status["excess_solar_active"] is False
        assert status["excess_solar_evses"] == []

    def test_status_excess_solar_when_active(self):
        h = _EVSEHarness(garage_a_on=False)
        h.ev.determine_excess_solar_actions(
            soc=96.0, remaining_forecast_kwh=6.0, tou_period="off_peak",
        )
        status = h.ev.get_status()
        assert status["excess_solar_active"] is True
        assert len(status["excess_solar_evses"]) > 0


# ── Additional coverage from review ───────────────────────────────────────

class TestExcessSolarNoneInputs:
    """Excess solar gracefully handles None SOC and forecast."""

    def test_none_soc_no_activate(self):
        h = _EVSEHarness(garage_a_on=False)
        actions = h.ev.determine_excess_solar_actions(
            soc=None, remaining_forecast_kwh=6.0, tou_period="off_peak",
        )
        assert len(actions) == 0

    def test_none_forecast_no_activate(self):
        h = _EVSEHarness(garage_a_on=False)
        actions = h.ev.determine_excess_solar_actions(
            soc=96.0, remaining_forecast_kwh=None, tou_period="off_peak",
        )
        assert len(actions) == 0


class TestExcessSolarTOUPauseInteraction:
    """Excess solar respects TOU-paused EVSEs."""

    def test_paused_evse_excluded_from_excess_solar(self):
        h = _EVSEHarness(garage_a_on=False, garage_b_on=False)
        # Simulate garage_a paused by TOU
        h.ev._paused_by_us.add("garage_a")
        actions = h.ev.determine_excess_solar_actions(
            soc=96.0, remaining_forecast_kwh=6.0, tou_period="off_peak",
        )
        # Only garage_b should be turned on
        turned_on = [a["target"] for a in actions]
        assert "switch.garage_a" not in turned_on
        assert "switch.garage_b" in turned_on
        assert "garage_a" not in h.ev._excess_solar_active


class TestExcessSolarDeactivation:
    """Only turns off EVSEs that excess solar turned on, not others."""

    def test_deactivation_skips_user_controlled_evse(self):
        """Garage A is on by user, only B by excess solar. Deactivation only touches B."""
        h = _EVSEHarness(garage_a_on=True, garage_b_on=False)
        # Excess solar only turns on B (A already on)
        h.ev.determine_excess_solar_actions(
            soc=96.0, remaining_forecast_kwh=6.0, tou_period="off_peak",
        )
        assert "garage_a" not in h.ev._excess_solar_active
        assert "garage_b" in h.ev._excess_solar_active

        # Simulate B now on
        h.hass.set_state("switch.garage_b", "on")

        # Conditions drop → deactivate
        actions = h.ev.determine_excess_solar_actions(
            soc=90.0, remaining_forecast_kwh=6.0, tou_period="off_peak",
        )
        targets = [a["target"] for a in actions]
        assert "switch.garage_b" in targets  # We turned it on
        assert "switch.garage_a" not in targets  # Not ours


class TestPeakTurnOffChecksState:
    """Peak turn-off should check if EVSE is already off."""

    def test_peak_skips_already_off_evse(self):
        h = _EVSEHarness(garage_a_on=False, garage_b_on=False)
        # Manually mark as excess solar active
        h.ev._excess_solar_active.add("garage_a")
        h.ev._excess_solar_active.add("garage_b")
        # Both are already off — peak turn-off should not issue actions
        actions = h.ev.determine_excess_solar_actions(
            soc=96.0, remaining_forecast_kwh=6.0, tou_period="peak",
        )
        assert len(actions) == 0
        assert len(h.ev._excess_solar_active) == 0  # Still cleared
