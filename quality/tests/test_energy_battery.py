"""Tests for BatteryStrategy season-aware TOU logic.

Validates that determine_mode() uses the correct strategy per season:
- Summer mid-peak: hold charge for upcoming peak
- Shoulder/Winter mid-peak: discharge (mid-peak IS the highest rate)
- Peak: always discharge (summer only)
- Off-peak: always charge from solar
"""

import pytest
from datetime import datetime
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

# Import energy_const and energy_battery
for _submod_name in ("energy_const", "energy_battery"):
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

from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    BATTERY_MODE_SELF_CONSUMPTION,
    BATTERY_MODE_BACKUP,
    DEFAULT_BATTERY_SOC_ENTITY,
    DEFAULT_RESERVE_SOC,
    DEFAULT_RESERVE_SOC_ENTITY,
    DEFAULT_SOLAR_PRODUCTION_ENTITY,
    DEFAULT_NET_POWER_ENTITY,
    DEFAULT_STORAGE_MODE_ENTITY,
    DEFAULT_GRID_ENABLED_ENTITY,
    DEFAULT_CHARGE_FROM_GRID_ENTITY,
    DEFAULT_SOLCAST_TODAY_ENTITY,
    DEFAULT_WEATHER_ENTITY,
    DEFAULT_BATTERY_POWER_ENTITY,
)
from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
    BatteryStrategy,
)


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

# Initial reserve entity value differs from DEFAULT_RESERVE_SOC (20) so that
# reserve-level actions are actually emitted and assertions aren't dead code.
_HARNESS_INITIAL_RESERVE = 50


class _BatteryHarness:
    """Test harness for BatteryStrategy with pre-wired mock entities."""

    def __init__(self, soc=80.0, storage_mode="self_consumption", solar=5000.0):
        self.hass = MockHass()
        self.hass.set_state(DEFAULT_BATTERY_SOC_ENTITY, str(soc))
        self.hass.set_state(DEFAULT_STORAGE_MODE_ENTITY, storage_mode)
        self.hass.set_state(DEFAULT_SOLAR_PRODUCTION_ENTITY, str(solar))
        self.hass.set_state(DEFAULT_NET_POWER_ENTITY, "-500")
        self.hass.set_state(DEFAULT_BATTERY_POWER_ENTITY, "-200")
        self.hass.set_state(DEFAULT_GRID_ENABLED_ENTITY, "on")
        self.hass.set_state(DEFAULT_CHARGE_FROM_GRID_ENTITY, "off")
        self.hass.set_state(DEFAULT_RESERVE_SOC_ENTITY, str(_HARNESS_INITIAL_RESERVE))
        self.hass.set_state(DEFAULT_SOLCAST_TODAY_ENTITY, "90")
        self.hass.set_state(DEFAULT_WEATHER_ENTITY, "sunny")
        self.strategy = BatteryStrategy(self.hass, reserve_soc=DEFAULT_RESERVE_SOC)


def _get_reserve_actions(result):
    """Extract reserve-level actions from a decision result."""
    return [a for a in result["actions"] if "reserve" in a.get("target", "")]


# ── Summer mid-peak: hold for peak ──────────────────────────────────────────

class TestSummerMidPeak:
    """Summer mid-peak should hold charge for upcoming peak."""

    def test_summer_mid_peak_holds_charge(self):
        h = _BatteryHarness(soc=80)
        result = h.strategy.determine_mode("mid_peak", "summer")
        assert result["mode"] == BATTERY_MODE_SELF_CONSUMPTION
        assert "holding charge for peak" in result["reason"]
        assert "summer" in result["reason"]
        assert result["season"] == "summer"

    def test_summer_mid_peak_reserve_equals_soc(self):
        """Reserve should be set to current SOC to prevent discharge."""
        h = _BatteryHarness(soc=75)
        result = h.strategy.determine_mode("mid_peak", "summer")
        reserve_actions = _get_reserve_actions(result)
        assert len(reserve_actions) == 1
        assert reserve_actions[0]["data"]["value"] == 75


# ── Shoulder mid-peak: discharge ─────────────────────────────────────────────

class TestShoulderMidPeak:
    """Shoulder mid-peak should discharge — it's the highest rate window."""

    def test_shoulder_mid_peak_discharges(self):
        h = _BatteryHarness(soc=80)
        result = h.strategy.determine_mode("mid_peak", "shoulder")
        assert result["mode"] == BATTERY_MODE_SELF_CONSUMPTION
        assert "discharging" in result["reason"]
        assert "shoulder" in result["reason"]
        assert "best rate" in result["reason"]
        assert result["season"] == "shoulder"

    def test_shoulder_mid_peak_uses_low_reserve(self):
        """Reserve should drop to configured minimum to allow full discharge."""
        h = _BatteryHarness(soc=80)
        result = h.strategy.determine_mode("mid_peak", "shoulder")
        reserve_actions = _get_reserve_actions(result)
        assert len(reserve_actions) == 1
        assert reserve_actions[0]["data"]["value"] == DEFAULT_RESERVE_SOC

    def test_shoulder_mid_peak_low_soc(self):
        """Low SOC in shoulder mid-peak should still allow minimal discharge."""
        h = _BatteryHarness(soc=15)
        result = h.strategy.determine_mode("mid_peak", "shoulder")
        assert result["mode"] == BATTERY_MODE_SELF_CONSUMPTION
        assert "low" in result["reason"].lower()
        assert "shoulder" in result["reason"]


# ── Winter mid-peak: discharge (same as shoulder) ────────────────────────────

class TestWinterMidPeak:
    """Winter mid-peak should also discharge — no peak exists."""

    def test_winter_mid_peak_discharges(self):
        h = _BatteryHarness(soc=80)
        result = h.strategy.determine_mode("mid_peak", "winter")
        assert result["mode"] == BATTERY_MODE_SELF_CONSUMPTION
        assert "discharging" in result["reason"]
        assert "winter" in result["reason"]
        assert result["season"] == "winter"

    def test_winter_mid_peak_low_soc(self):
        h = _BatteryHarness(soc=10)
        result = h.strategy.determine_mode("mid_peak", "winter")
        assert result["mode"] == BATTERY_MODE_SELF_CONSUMPTION
        assert "low" in result["reason"].lower()


# ── Off-peak: charge in all seasons ──────────────────────────────────────────

class TestOffPeak:
    """Off-peak should charge from solar in every season."""

    def test_off_peak_summer(self):
        h = _BatteryHarness(soc=50)
        result = h.strategy.determine_mode("off_peak", "summer")
        assert result["mode"] == BATTERY_MODE_SELF_CONSUMPTION
        assert "off-peak" in result["reason"].lower()

    def test_off_peak_shoulder(self):
        h = _BatteryHarness(soc=50)
        result = h.strategy.determine_mode("off_peak", "shoulder")
        assert result["mode"] == BATTERY_MODE_SELF_CONSUMPTION
        assert "off-peak" in result["reason"].lower()

    def test_off_peak_winter(self):
        h = _BatteryHarness(soc=50)
        result = h.strategy.determine_mode("off_peak", "winter")
        assert result["mode"] == BATTERY_MODE_SELF_CONSUMPTION
        assert "off-peak" in result["reason"].lower()

    def test_off_peak_uses_low_reserve(self):
        """Off-peak reserve allows full charging (low reserve)."""
        h = _BatteryHarness(soc=50)
        result = h.strategy.determine_mode("off_peak", "shoulder")
        reserve_actions = _get_reserve_actions(result)
        assert len(reserve_actions) == 1
        assert reserve_actions[0]["data"]["value"] == DEFAULT_RESERVE_SOC


# ── Peak: discharge (summer only has peak, but code handles any season) ──────

class TestPeak:
    """Peak period discharges battery to cover load."""

    def test_peak_discharges_with_good_soc(self):
        h = _BatteryHarness(soc=80)
        result = h.strategy.determine_mode("peak", "summer")
        assert result["mode"] == BATTERY_MODE_SELF_CONSUMPTION
        assert "battery covers load" in result["reason"].lower()

    def test_peak_low_soc(self):
        h = _BatteryHarness(soc=15)
        result = h.strategy.determine_mode("peak", "summer")
        assert result["mode"] == BATTERY_MODE_SELF_CONSUMPTION
        assert "low" in result["reason"].lower()

    def test_peak_in_non_summer_still_discharges(self):
        """Peak period in non-summer (shouldn't happen, but should be safe)."""
        h = _BatteryHarness(soc=80)
        result = h.strategy.determine_mode("peak", "shoulder")
        assert result["mode"] == BATTERY_MODE_SELF_CONSUMPTION
        assert "battery covers load" in result["reason"].lower()


# ── Season default (backward compat) ────────────────────────────────────────

class TestSeasonDefault:
    """If season is not passed, default to summer (backward compat)."""

    def test_default_season_is_summer(self):
        h = _BatteryHarness(soc=80)
        result = h.strategy.determine_mode("mid_peak")
        # Should use summer behavior (hold for peak)
        assert "holding charge for peak" in result["reason"]
        assert result["season"] == "summer"


# ── Mode is always self_consumption ──────────────────────────────────────────

class TestSelfConsumptionOnly:
    """Battery should always stay in self_consumption (Enphase codicil)."""

    def test_all_seasons_mid_peak_self_consumption(self):
        for season in ("summer", "shoulder", "winter"):
            h = _BatteryHarness(soc=80)
            result = h.strategy.determine_mode("mid_peak", season)
            assert result["mode"] == BATTERY_MODE_SELF_CONSUMPTION, (
                f"{season} mid_peak mode should be self_consumption"
            )

    def test_all_periods_self_consumption(self):
        for period in ("off_peak", "mid_peak", "peak"):
            h = _BatteryHarness(soc=80)
            result = h.strategy.determine_mode(period, "summer")
            assert result["mode"] == BATTERY_MODE_SELF_CONSUMPTION, (
                f"{period} mode should be self_consumption"
            )


# ── Season in return dict ────────────────────────────────────────────────────

class TestSeasonInResult:
    """Season should be included in the decision result for sensor display."""

    def test_season_in_result_shoulder(self):
        h = _BatteryHarness(soc=80)
        result = h.strategy.determine_mode("mid_peak", "shoulder")
        assert "season" in result
        assert result["season"] == "shoulder"

    def test_season_in_result_off_peak(self):
        h = _BatteryHarness(soc=80)
        result = h.strategy.determine_mode("off_peak", "winter")
        assert result["season"] == "winter"


# ── Envoy unavailable ───────────────────────────────────────────────────────

class TestEnvoyUnavailable:
    """Envoy-unavailable path should include season and not crash."""

    def test_envoy_unavailable_includes_season(self):
        h = _BatteryHarness(soc=80)
        # Make SOC entity unavailable to trigger envoy_available=False
        h.hass.set_state(DEFAULT_BATTERY_SOC_ENTITY, "unavailable")
        result = h.strategy.determine_mode("mid_peak", "shoulder")
        assert result["envoy_available"] is False
        assert "season" in result
        assert result["season"] == "shoulder"

    def test_envoy_unavailable_holds_state(self):
        h = _BatteryHarness(soc=80)
        h.hass.set_state(DEFAULT_STORAGE_MODE_ENTITY, "unavailable")
        result = h.strategy.determine_mode("off_peak", "winter")
        assert result["envoy_available"] is False
        assert result["actions"] == []
        assert result["season"] == "winter"
