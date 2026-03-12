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
    DEFAULT_SOLCAST_TOMORROW_ENTITY,
    DEFAULT_WEATHER_ENTITY,
    DEFAULT_BATTERY_POWER_ENTITY,
    DEFAULT_OFFPEAK_DRAIN_EXCELLENT,
    DEFAULT_OFFPEAK_DRAIN_GOOD,
    DEFAULT_OFFPEAK_DRAIN_MODERATE,
    DEFAULT_OFFPEAK_DRAIN_POOR,
    DEFAULT_OFFPEAK_DRAIN_UNKNOWN,
    DEFAULT_ARBITRAGE_SOC_TRIGGER,
    DEFAULT_ARBITRAGE_SOC_TARGET,
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

    def __init__(self, soc=80.0, storage_mode="self_consumption", solar=5000.0,
                 solcast_tomorrow="90", arbitrage_enabled=False):
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
        self.hass.set_state(DEFAULT_SOLCAST_TOMORROW_ENTITY, solcast_tomorrow)
        self.hass.set_state(DEFAULT_WEATHER_ENTITY, "sunny")
        self.strategy = BatteryStrategy(
            self.hass,
            reserve_soc=DEFAULT_RESERVE_SOC,
            arbitrage_enabled=arbitrage_enabled,
        )


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


# ── Off-peak: SOC-conditional drain ──────────────────────────────────────────

class TestOffPeak:
    """Off-peak uses SOC-conditional drain based on tomorrow's solar forecast."""

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

    def test_off_peak_drain_above_target(self):
        """SOC above drain target → reserve = drain target."""
        # Solcast tomorrow=90 → "good" → drain target 15
        h = _BatteryHarness(soc=50, solcast_tomorrow="90")
        result = h.strategy.determine_mode("off_peak", "shoulder")
        reserve_actions = _get_reserve_actions(result)
        assert len(reserve_actions) == 1
        assert reserve_actions[0]["data"]["value"] == DEFAULT_OFFPEAK_DRAIN_GOOD
        assert "drain" in result["reason"].lower()

    def test_off_peak_hold_below_target(self):
        """SOC at/below drain target → hold (reserve = SOC)."""
        # Solcast tomorrow=90 → "good" → drain target 15, SOC 10 < 15
        h = _BatteryHarness(soc=10, solcast_tomorrow="90")
        result = h.strategy.determine_mode("off_peak", "shoulder")
        reserve_actions = _get_reserve_actions(result)
        assert len(reserve_actions) == 1
        assert reserve_actions[0]["data"]["value"] == 10  # hold at SOC
        assert "hold" in result["reason"].lower()

    def test_off_peak_includes_tomorrow_class(self):
        """Decision result includes tomorrow_solar_class."""
        h = _BatteryHarness(soc=50)
        result = h.strategy.determine_mode("off_peak", "summer")
        assert "tomorrow_solar_class" in result


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


# ── v3.11.0 Phase A: Off-peak SOC-conditional drain ───────────────────────

class TestOffPeakDrain:
    """Off-peak drain uses tomorrow's solar forecast to set reserve target."""

    def test_excellent_tomorrow_drains_to_10(self):
        """Excellent solar tomorrow → aggressive drain to 10%."""
        h = _BatteryHarness(soc=90, solcast_tomorrow="130")  # > P75 for any month
        result = h.strategy.determine_mode("off_peak", "summer")
        reserve_actions = _get_reserve_actions(result)
        assert len(reserve_actions) == 1
        assert reserve_actions[0]["data"]["value"] == DEFAULT_OFFPEAK_DRAIN_EXCELLENT
        assert result["tomorrow_solar_class"] == "excellent"

    def test_good_tomorrow_drains_to_15(self):
        """Good solar tomorrow → drain to 15%."""
        h = _BatteryHarness(soc=90, solcast_tomorrow="90")
        result = h.strategy.determine_mode("off_peak", "summer")
        reserve_actions = _get_reserve_actions(result)
        assert len(reserve_actions) == 1
        assert reserve_actions[0]["data"]["value"] == DEFAULT_OFFPEAK_DRAIN_GOOD

    def test_poor_tomorrow_drains_to_30(self):
        """Poor solar tomorrow → drain to 30%."""
        h = _BatteryHarness(soc=90, solcast_tomorrow="20")  # Below P25
        result = h.strategy.determine_mode("off_peak", "summer")
        reserve_actions = _get_reserve_actions(result)
        assert len(reserve_actions) == 1
        assert reserve_actions[0]["data"]["value"] == DEFAULT_OFFPEAK_DRAIN_POOR

    def test_soc_above_target_drains(self):
        """SOC above drain target → drain to target."""
        h = _BatteryHarness(soc=30, solcast_tomorrow="90")  # good→target 15, SOC 30>15→drains
        result = h.strategy.determine_mode("off_peak", "summer")
        # SOC 30 > target 15 → drains to 15
        reserve_actions = _get_reserve_actions(result)
        assert reserve_actions[0]["data"]["value"] == DEFAULT_OFFPEAK_DRAIN_GOOD

    def test_soc_at_target_holds(self):
        """SOC at drain target → hold."""
        h = _BatteryHarness(soc=15, solcast_tomorrow="90")  # good→target 15, SOC==target→hold
        result = h.strategy.determine_mode("off_peak", "summer")
        reserve_actions = _get_reserve_actions(result)
        assert reserve_actions[0]["data"]["value"] == 15  # hold at SOC
        assert "hold" in result["reason"].lower()

    def test_unknown_tomorrow_uses_conservative_40(self):
        """Unknown forecast → drain to 40% (conservative default)."""
        h = _BatteryHarness(soc=90)
        h.hass.set_state(DEFAULT_SOLCAST_TOMORROW_ENTITY, "unavailable")
        result = h.strategy.determine_mode("off_peak", "summer")
        reserve_actions = _get_reserve_actions(result)
        assert reserve_actions[0]["data"]["value"] == DEFAULT_OFFPEAK_DRAIN_UNKNOWN

    def test_custom_drain_targets(self):
        """Custom drain targets via config override defaults."""
        h = _BatteryHarness(soc=90, solcast_tomorrow="130")
        h.strategy._drain_targets["excellent"] = 25
        result = h.strategy.determine_mode("off_peak", "summer")
        reserve_actions = _get_reserve_actions(result)
        assert reserve_actions[0]["data"]["value"] == 25


# ── v3.11.0 Phase B: Grid charge arbitrage ────────────────────────────────

class TestArbitrage:
    """Grid charge arbitrage: poor tomorrow + low SOC → charge from grid overnight."""

    def test_arbitrage_poor_solar_low_soc(self):
        """Poor solar + SOC below trigger → charge from grid."""
        h = _BatteryHarness(soc=20, solcast_tomorrow="20", arbitrage_enabled=True)
        result = h.strategy.determine_mode("off_peak", "summer")
        assert "arbitrage" in result["reason"].lower()
        assert result["arbitrage_active"] is True
        # Should have charge_from_grid action
        charge_actions = [a for a in result["actions"] if "charge_from_grid" in a.get("target", "")]
        assert len(charge_actions) == 1
        assert charge_actions[0]["service"] == "switch.turn_on"

    def test_arbitrage_good_solar_no_trigger(self):
        """Good solar + low SOC → no arbitrage (solar covers tomorrow)."""
        h = _BatteryHarness(soc=20, solcast_tomorrow="90", arbitrage_enabled=True)
        result = h.strategy.determine_mode("off_peak", "summer")
        assert result.get("arbitrage_active", False) is False

    def test_arbitrage_poor_solar_high_soc_no_trigger(self):
        """Poor solar but SOC above trigger → no arbitrage."""
        h = _BatteryHarness(soc=60, solcast_tomorrow="20", arbitrage_enabled=True)
        result = h.strategy.determine_mode("off_peak", "summer")
        # SOC 60 > trigger 30 → no arbitrage
        assert result.get("arbitrage_active", False) is False

    def test_arbitrage_stops_at_target(self):
        """Arbitrage stops when SOC reaches target."""
        h = _BatteryHarness(soc=20, solcast_tomorrow="20", arbitrage_enabled=True)
        # First call activates arbitrage
        result1 = h.strategy.determine_mode("off_peak", "summer")
        assert result1["arbitrage_active"] is True

        # SOC climbs to target
        h.hass.set_state(DEFAULT_BATTERY_SOC_ENTITY, str(DEFAULT_ARBITRAGE_SOC_TARGET))
        result2 = h.strategy.determine_mode("off_peak", "summer")
        # Arbitrage should deactivate
        assert h.strategy._arbitrage_active is False

    def test_storm_overrides_arbitrage(self):
        """Storm forecast takes priority over arbitrage."""
        h = _BatteryHarness(soc=20, solcast_tomorrow="20", arbitrage_enabled=True)
        h.hass.set_state(DEFAULT_WEATHER_ENTITY, "lightning")
        result = h.strategy.determine_mode("off_peak", "summer")
        # Storm path should win — switches to backup mode
        assert "storm" in result["reason"].lower()

    def test_arbitrage_disabled_by_config(self):
        """Arbitrage disabled → normal off-peak behavior."""
        h = _BatteryHarness(soc=20, solcast_tomorrow="20", arbitrage_enabled=False)
        result = h.strategy.determine_mode("off_peak", "summer")
        assert result.get("arbitrage_active", False) is False


# ── v3.11.0: Result dict has new fields ───────────────────────────────────

class TestNewResultFields:
    """New v3.11.0 fields in decision result dict."""

    def test_tomorrow_solar_class_in_result(self):
        h = _BatteryHarness(soc=80)
        result = h.strategy.determine_mode("off_peak", "summer")
        assert "tomorrow_solar_class" in result

    def test_arbitrage_active_in_result(self):
        h = _BatteryHarness(soc=80)
        result = h.strategy.determine_mode("off_peak", "summer")
        assert "arbitrage_active" in result

    def test_get_status_includes_new_fields(self):
        h = _BatteryHarness(soc=80)
        h.strategy.determine_mode("off_peak", "summer")
        status = h.strategy.get_status()
        assert "tomorrow_solar_class" in status
        assert "arbitrage_active" in status
        assert "arbitrage_enabled" in status

    def test_arbitrage_enabled_in_result(self):
        """arbitrage_enabled should be in every decision result."""
        h = _BatteryHarness(soc=80, arbitrage_enabled=True)
        result = h.strategy.determine_mode("off_peak", "summer")
        assert "arbitrage_enabled" in result
        assert result["arbitrage_enabled"] is True

    def test_arbitrage_enabled_false_in_result(self):
        h = _BatteryHarness(soc=80, arbitrage_enabled=False)
        result = h.strategy.determine_mode("peak", "summer")
        assert result["arbitrage_enabled"] is False


# ── Additional coverage: moderate + very_poor + grid disconnect + storm ────

class TestModerateDrain:
    """Moderate solar tomorrow → drain to 20%."""

    def test_moderate_tomorrow_drains_to_20(self):
        """Solar between P25 and P50 → moderate → drain to 20%."""
        # classify_tomorrow_solar uses (now+1day).month for threshold lookup.
        # Use custom thresholds to avoid date dependency.
        h = _BatteryHarness(soc=90, solcast_tomorrow="70")
        h.strategy._solar_classification_mode = "custom"
        h.strategy._custom_solar_thresholds = {
            "excellent": 100.0, "good": 80.0, "moderate": 50.0, "poor": 30.0,
        }
        result = h.strategy.determine_mode("off_peak", "summer")
        reserve_actions = _get_reserve_actions(result)
        assert len(reserve_actions) == 1
        assert reserve_actions[0]["data"]["value"] == DEFAULT_OFFPEAK_DRAIN_MODERATE
        assert result["tomorrow_solar_class"] == "moderate"


class TestVeryPoorDrain:
    """Very poor solar tomorrow uses poor drain target."""

    def test_very_poor_classification(self):
        """Solar well below P25 → poor classification (no 'very_poor' from monthly thresholds)."""
        h = _BatteryHarness(soc=90, solcast_tomorrow="5")  # Far below any P25
        result = h.strategy.determine_mode("off_peak", "summer")
        assert result["tomorrow_solar_class"] == "poor"
        reserve_actions = _get_reserve_actions(result)
        assert reserve_actions[0]["data"]["value"] == DEFAULT_OFFPEAK_DRAIN_POOR


class TestGridDisconnected:
    """Grid disconnect → backup mode."""

    def test_grid_disconnected_uses_backup(self):
        h = _BatteryHarness(soc=80)
        h.hass.set_state(DEFAULT_GRID_ENABLED_ENTITY, "off")
        result = h.strategy.determine_mode("off_peak", "summer")
        assert result["mode"] == BATTERY_MODE_BACKUP
        assert "grid disconnected" in result["reason"].lower()

    def test_grid_disconnected_during_peak(self):
        h = _BatteryHarness(soc=80)
        h.hass.set_state(DEFAULT_GRID_ENABLED_ENTITY, "off")
        result = h.strategy.determine_mode("peak", "summer")
        assert result["mode"] == BATTERY_MODE_BACKUP


class TestStormPaths:
    """Storm forecast paths — pre-charge and hold."""

    def test_storm_low_soc_pre_charges(self):
        """Storm + low SOC → charge from grid."""
        h = _BatteryHarness(soc=50)
        h.hass.set_state(DEFAULT_WEATHER_ENTITY, "lightning")
        result = h.strategy.determine_mode("off_peak", "summer")
        assert "storm" in result["reason"].lower()
        assert "pre-charging" in result["reason"].lower()
        charge_actions = [a for a in result["actions"] if "charge_from_grid" in a.get("target", "")]
        assert len(charge_actions) == 1

    def test_storm_high_soc_holds_backup(self):
        """Storm + high SOC → switch to backup mode."""
        h = _BatteryHarness(soc=95)
        h.hass.set_state(DEFAULT_WEATHER_ENTITY, "tornado")
        result = h.strategy.determine_mode("off_peak", "summer")
        assert result["mode"] == BATTERY_MODE_BACKUP
        assert "holding charge" in result["reason"].lower()


class TestArbitrageContinuing:
    """Arbitrage mid-charge should continue until target reached."""

    def test_arbitrage_continues_mid_charge(self):
        """SOC between trigger and target during active arbitrage → continue charging."""
        h = _BatteryHarness(soc=20, solcast_tomorrow="20", arbitrage_enabled=True)
        # First call activates arbitrage
        result1 = h.strategy.determine_mode("off_peak", "summer")
        assert result1["arbitrage_active"] is True

        # SOC climbs to 50 (between trigger 30 and target 80) → should continue
        h.hass.set_state(DEFAULT_BATTERY_SOC_ENTITY, "50")
        result2 = h.strategy.determine_mode("off_peak", "summer")
        assert result2["arbitrage_active"] is True
        assert "continuing" in result2["reason"].lower()

    def test_arbitrage_continues_at_trigger(self):
        """SOC exactly at trigger during active arbitrage → continue (not re-enter)."""
        h = _BatteryHarness(soc=20, solcast_tomorrow="20", arbitrage_enabled=True)
        h.strategy.determine_mode("off_peak", "summer")  # activate

        h.hass.set_state(DEFAULT_BATTERY_SOC_ENTITY, str(DEFAULT_ARBITRAGE_SOC_TRIGGER))
        result = h.strategy.determine_mode("off_peak", "summer")
        assert result["arbitrage_active"] is True


class TestEnvoyUnavailableNewFields:
    """Envoy-unavailable path should include all v3.11.0 fields."""

    def test_envoy_unavailable_has_tomorrow_class(self):
        h = _BatteryHarness(soc=80)
        h.hass.set_state(DEFAULT_BATTERY_SOC_ENTITY, "unavailable")
        result = h.strategy.determine_mode("off_peak", "summer")
        assert result["envoy_available"] is False
        assert result["tomorrow_solar_class"] == "unknown"
        assert result["arbitrage_active"] is False
        assert "arbitrage_enabled" in result
        assert "reserve_soc" in result
