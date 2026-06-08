"""Tests for day-boundary-blind TOU decision fix.

Covers:
- D1: TOURateEngine.peak_ahead_before_offpeak — bracketed-period
      pre/post-peak discrimination, season/midnight safety.
- D2: BatteryStrategy summer mid_peak gate — hold pre-peak, discharge
      post-peak (off_peak imminent).
- D3: TOURateEngine.get_next_transition — season-wrap correctness on
      a season-boundary day; intra-day path unchanged.

Schedule is sourced from energy_const.PEC_TOU_RATES (no hand-copied
hours) per Bug Class #44 fixture authority.
"""

from __future__ import annotations

import calendar
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock
import sys
import os
import types
import importlib

# ---------------------------------------------------------------------------
# Mock homeassistant (same pattern as sibling tests)
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
    "homeassistant.helpers.event": {},
    "homeassistant.helpers.dispatcher": {},
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls, "UpdateFailed": Exception,
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

sys.modules.setdefault("aiosqlite", MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules.setdefault("custom_components.universal_room_automation", _ura)

_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_const_mod = importlib.util.module_from_spec(_const_spec)
sys.modules.setdefault("custom_components.universal_room_automation.const", _const_mod)
_const_spec.loader.exec_module(_const_mod)
_ura.const = _const_mod

_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules.setdefault(
    "custom_components.universal_room_automation.domain_coordinators", _dc,
)
_ura.domain_coordinators = _dc

for _submod_name in ("energy_const", "energy_tou", "energy_battery"):
    _full_name = f"custom_components.universal_room_automation.domain_coordinators.{_submod_name}"
    if _full_name in sys.modules:
        continue
    _spec = importlib.util.spec_from_file_location(
        _full_name, os.path.join(_dc_path, f"{_submod_name}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full_name] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, _mod)


from conftest import MockHass

from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    BATTERY_MODE_SELF_CONSUMPTION,
    DEFAULT_RESERVE_SOC,
    DEFAULT_RESERVE_SOC_ENTITY,
    DEFAULT_STORAGE_MODE_ENTITY,
    DEFAULT_GRID_ENABLED_ENTITY,
    DEFAULT_CHARGE_FROM_GRID_ENTITY,
    DEFAULT_SOLCAST_TODAY_ENTITY,
    DEFAULT_SOLCAST_TOMORROW_ENTITY,
    DEFAULT_WEATHER_ENTITY,
    PEC_TOU_RATES,
)
from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
    BatteryStrategy,
)
from custom_components.universal_room_automation.domain_coordinators.energy_tou import (
    TOURateEngine,
)


# ---------------------------------------------------------------------------
# Schedule-driven helpers — read hours from PEC_TOU_RATES (no hand-copies).
# Bug Class #44 fixture authority.
# ---------------------------------------------------------------------------

def _periods_for_season(season: str) -> dict[str, list[tuple[int, int]]]:
    return {
        name: [tuple(h) for h in data["hours"]]
        for name, data in PEC_TOU_RATES[season]["periods"].items()
    }


def _summer_month() -> int:
    return PEC_TOU_RATES["summer"]["months"][0]  # June


def _shoulder_month() -> int:
    return PEC_TOU_RATES["shoulder"]["months"][0]


def _winter_month() -> int:
    return PEC_TOU_RATES["winter"]["months"][0]


def _last_summer_month() -> int:
    return PEC_TOU_RATES["summer"]["months"][-1]


def _last_day_of(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _first_hour_in(period_hours: list[tuple[int, int]]) -> int:
    """First hour-of-day where the period begins, deterministic."""
    return min(start for start, _end in period_hours)


# ---------------------------------------------------------------------------
# D1: peak_ahead_before_offpeak
# ---------------------------------------------------------------------------

class TestPeakAheadBeforeOffpeak:
    """Bracketed-period pre/post-peak discrimination."""

    def setup_method(self):
        self.engine = TOURateEngine()
        self.summer = _periods_for_season("summer")
        self.shoulder = _periods_for_season("shoulder")
        self.winter = _periods_for_season("winter")
        # Sanity: confirm summer schedule has two-window mid_peak + a peak.
        assert "peak" in self.summer
        assert len(self.summer["mid_peak"]) == 2

    def test_summer_pre_peak_midpeak_returns_true(self):
        # Inside the FIRST summer mid_peak window (e.g. 15:00); peak follows.
        pre_window = self.summer["mid_peak"][0]  # (14, 16)
        now = datetime(2026, _summer_month(), 15, pre_window[0] + 1, 0)
        assert self.engine.get_current_period(now) == "mid_peak"
        assert self.engine.peak_ahead_before_offpeak(now=now) is True

    def test_summer_post_peak_midpeak_returns_false(self):
        # Inside the SECOND summer mid_peak window (e.g. 20:30); off_peak follows.
        post_window = self.summer["mid_peak"][1]  # (20, 21)
        now = datetime(2026, _summer_month(), 15, post_window[0], 30)
        assert self.engine.get_current_period(now) == "mid_peak"
        assert self.engine.peak_ahead_before_offpeak(now=now) is False

    def test_summer_offpeak_with_peak_later_today_returns_true(self):
        # 13:00 — still off_peak, but peak starts at 16:00 same day.
        peak_start = _first_hour_in(self.summer["peak"])  # 16
        now = datetime(2026, _summer_month(), 15, peak_start - 3, 0)
        assert self.engine.get_current_period(now) == "off_peak"
        assert self.engine.peak_ahead_before_offpeak(now=now) is True

    def test_shoulder_midpeak_returns_false_no_peak_in_schedule(self):
        # Shoulder has no "peak" period — should always be False from mid_peak.
        shoulder_mid = self.shoulder["mid_peak"][0]
        now = datetime(2026, _shoulder_month(), 15, shoulder_mid[0], 30)
        assert self.engine.get_current_period(now) == "mid_peak"
        assert self.engine.peak_ahead_before_offpeak(now=now) is False

    def test_winter_midpeak_returns_false_no_peak_in_schedule(self):
        winter_mid = self.winter["mid_peak"][0]  # (5, 9)
        now = datetime(2026, _winter_month(), 15, winter_mid[0], 30)
        assert self.engine.get_current_period(now) == "mid_peak"
        assert self.engine.peak_ahead_before_offpeak(now=now) is False

    def test_summer_late_night_offpeak_returns_false(self):
        # 23:30 — off_peak. Per the documented contract the walk returns False
        # on the first off_peak hour (00:00 is still off_peak). This is never a
        # real call site (the helper is only invoked from a mid_peak tick); the
        # case exists to prove the midnight-crossing math doesn't misfire into
        # a spurious True.
        now = datetime(2026, _summer_month(), 15, 23, 30)
        assert self.engine.get_current_period(now) == "off_peak"
        assert self.engine.peak_ahead_before_offpeak(now=now) is False

    def test_season_boundary_day_sane(self):
        # Last summer day at 23:30 → tomorrow is shoulder (no peak).
        # The walk crosses both midnight AND a season boundary. Result must
        # not crash and must return a sane bool. Shoulder has no peak, so
        # off_peak hits first → False.
        last_summer_month = _last_summer_month()
        last_day = _last_day_of(2026, last_summer_month)
        now = datetime(2026, last_summer_month, last_day, 23, 30)
        assert self.engine.get_current_period(now) == "off_peak"
        result = self.engine.peak_ahead_before_offpeak(now=now, lookahead_hours=24)
        assert isinstance(result, bool)
        # In the next 24h, hour 0 (next day) is shoulder off_peak → returns False.
        assert result is False


# ---------------------------------------------------------------------------
# D2: BatteryStrategy summer mid_peak gate
# ---------------------------------------------------------------------------

# Reuse the same fixture entity IDs the sibling test uses.
_BATT_SOC = "sensor.test_envoy_battery"
_BATT_POWER = "sensor.test_envoy_battery_power"
_SOLAR = "sensor.test_envoy_solar_production"
_NET = "sensor.test_envoy_net_power"


def _make_strategy(soc: float = 80.0, with_tou_engine: bool = True) -> BatteryStrategy:
    """Build a BatteryStrategy.

    By default wires a TOU engine (required for the D2 gate). Pass
    ``with_tou_engine=False`` to exercise the legacy/non-arbitrage fallback
    branch where the strategy cannot discriminate pre/post-peak.
    """
    hass = MockHass()
    hass.set_state(_BATT_SOC, str(soc))
    hass.set_state(DEFAULT_STORAGE_MODE_ENTITY, "self_consumption")
    hass.set_state(_SOLAR, "5000.0")
    hass.set_state(_NET, "-500", attributes={"unit_of_measurement": "W"})
    hass.set_state(_BATT_POWER, "-200")
    hass.set_state(DEFAULT_GRID_ENABLED_ENTITY, "on")
    hass.set_state(DEFAULT_CHARGE_FROM_GRID_ENTITY, "off")
    hass.set_state(DEFAULT_RESERVE_SOC_ENTITY, "50")
    hass.set_state(DEFAULT_SOLCAST_TODAY_ENTITY, "90")
    hass.set_state(DEFAULT_SOLCAST_TOMORROW_ENTITY, "90")
    hass.set_state(DEFAULT_WEATHER_ENTITY, "sunny")
    entity_config = {
        "battery_soc": _BATT_SOC,
        "battery_power": _BATT_POWER,
        "solar_production": _SOLAR,
        "net_power": _NET,
    }
    return BatteryStrategy(
        hass,
        reserve_soc=DEFAULT_RESERVE_SOC,
        arbitrage_enabled=False,
        entity_config=entity_config,
        solar_classification_mode="custom",
        custom_solar_thresholds={
            "excellent": 100.0, "good": 80.0, "moderate": 50.0, "poor": 30.0,
        },
        tou_engine=TOURateEngine() if with_tou_engine else None,
    )


def _reserve_actions(result):
    return [a for a in result["actions"] if "reserve" in a.get("target", "")]


class TestSummerMidPeakGate:
    """D2 — gated summer mid_peak hold."""

    def test_summer_pre_peak_holds_charge(self):
        # 15:00 inside first mid_peak window — peak still ahead → HOLD.
        strategy = _make_strategy(soc=80)
        now = datetime(2026, _summer_month(), 15, 15, 0)
        result = strategy.determine_mode("mid_peak", "summer", now=now)
        assert result["mode"] == BATTERY_MODE_SELF_CONSUMPTION
        assert "holding charge for peak" in result["reason"]
        actions = _reserve_actions(result)
        assert len(actions) == 1
        assert actions[0]["data"]["value"] == 80  # reserve == SOC

    def test_summer_post_peak_discharges(self):
        # 20:30 inside second mid_peak window — off_peak imminent → DISCHARGE.
        strategy = _make_strategy(soc=80)
        now = datetime(2026, _summer_month(), 15, 20, 30)
        result = strategy.determine_mode("mid_peak", "summer", now=now)
        assert result["mode"] == BATTERY_MODE_SELF_CONSUMPTION
        assert "discharging" in result["reason"]
        assert "post-peak" in result["reason"]
        actions = _reserve_actions(result)
        assert len(actions) == 1
        assert actions[0]["data"]["value"] == DEFAULT_RESERVE_SOC

    def test_summer_no_tou_engine_legacy_fallback_holds(self):
        # Legacy harness — no TOU engine wired. The summer mid_peak branch
        # MUST preserve the prior "always hold for peak" behavior because
        # there's no engine to discriminate pre/post-peak.
        # 20:30 (post-peak in real time) still gets a HOLD — the entire
        # point of the fallback. Reason wording is the pre-fix "holding
        # charge for peak" string.
        strategy = _make_strategy(soc=80, with_tou_engine=False)
        now = datetime(2026, _summer_month(), 15, 20, 30)
        result = strategy.determine_mode("mid_peak", "summer", now=now)
        assert result["mode"] == BATTERY_MODE_SELF_CONSUMPTION
        assert "holding charge for peak" in result["reason"]
        actions = _reserve_actions(result)
        assert len(actions) == 1
        # Hold reserve equals current SOC (preserve full battery).
        assert actions[0]["data"]["value"] == 80

    def test_summer_post_peak_soc_at_reserve_minimal_discharge(self):
        # SOC sitting exactly at reserve — `soc > reserve_soc` is False, so
        # the post-peak branch falls through to the low-SOC minimal-discharge
        # arm. Reason must include both "summer, post-peak" and "minimal
        # discharge" markers; reserve_level uses max(soc-5, reserve_soc)
        # which clamps to reserve_soc.
        strategy = _make_strategy(soc=DEFAULT_RESERVE_SOC)
        now = datetime(2026, _summer_month(), 15, 20, 30)
        result = strategy.determine_mode("mid_peak", "summer", now=now)
        assert result["mode"] == BATTERY_MODE_SELF_CONSUMPTION
        assert "summer, post-peak" in result["reason"]
        assert "minimal discharge" in result["reason"]
        actions = _reserve_actions(result)
        assert len(actions) == 1
        assert actions[0]["data"]["value"] == DEFAULT_RESERVE_SOC


class TestPeakAheadBoundaryHours:
    """Pin behavior at exact summer schedule boundary hours.

    All hours are derived from PEC_TOU_RATES — never literals — so a future
    schedule edit is forced through these assertions.
    """

    def setup_method(self):
        self.engine = TOURateEngine()
        self.summer = _periods_for_season("summer")
        # Schedule sanity: (14,16) pre-peak mid_peak, (16,20) peak,
        # (20,21) post-peak mid_peak, (21,24) off_peak.
        self.pre_mid_start = self.summer["mid_peak"][0][0]   # 14
        self.peak_start = self.summer["peak"][0][0]           # 16
        self.post_mid_start = self.summer["mid_peak"][1][0]   # 20
        # off_peak has two ranges in summer: (0,14) and (21,24). Pick the
        # one that starts after peak.
        self.offpeak_after_peak_start = next(
            start for start, _end in self.summer["off_peak"] if start >= self.post_mid_start
        )  # 21

    def test_pre_mid_peak_start_hour_true(self):
        # 14:00 sharp — first hour of pre-peak mid_peak. Peak is ahead.
        now = datetime(2026, _summer_month(), 15, self.pre_mid_start, 0)
        assert self.engine.get_current_period(now) == "mid_peak"
        assert self.engine.peak_ahead_before_offpeak(now=now) is True

    def test_peak_start_hour_true(self):
        # 16:00 sharp — peak starts. The walk starts at NEXT top-of-hour
        # (17:00) which is still peak → True.
        now = datetime(2026, _summer_month(), 15, self.peak_start, 0)
        assert self.engine.get_current_period(now) == "peak"
        assert self.engine.peak_ahead_before_offpeak(now=now) is True

    def test_post_peak_mid_start_hour_false(self):
        # 20:00 sharp — first post-peak mid_peak hour. The walk starts at
        # 21:00 (off_peak) → False.
        now = datetime(2026, _summer_month(), 15, self.post_mid_start, 0)
        assert self.engine.get_current_period(now) == "mid_peak"
        assert self.engine.peak_ahead_before_offpeak(now=now) is False

    def test_offpeak_after_peak_start_hour_false(self):
        # 21:00 sharp — off_peak resumes. The walk starts at 22:00 (still
        # off_peak) → False.
        now = datetime(2026, _summer_month(), 15, self.offpeak_after_peak_start, 0)
        assert self.engine.get_current_period(now) == "off_peak"
        assert self.engine.peak_ahead_before_offpeak(now=now) is False


# ---------------------------------------------------------------------------
# D3: get_next_transition season-wrap
# ---------------------------------------------------------------------------

class TestGetNextTransitionSeasonWrap:
    """D3 — wrap-to-next-day must use next day's season table."""

    def setup_method(self):
        self.engine = TOURateEngine()

    def test_season_boundary_returns_next_day_season(self):
        # Last summer day at 22:00 — currently off_peak (>=21:00).
        # Wrap should use the NEXT day's season (shoulder) for the first
        # transition.
        last_summer_month = _last_summer_month()
        last_day = _last_day_of(2026, last_summer_month)
        now = datetime(2026, last_summer_month, last_day, 22, 0)
        assert self.engine.get_season(now) == "summer"
        assert self.engine.get_current_period(now) == "off_peak"
        result = self.engine.get_next_transition(now)
        # Shoulder's first non-off_peak transition is mid_peak.
        # The summer table would have produced mid_peak at a distinct hour.
        shoulder_periods = _periods_for_season("shoulder")
        shoulder_first_mid = _first_hour_in(shoulder_periods["mid_peak"])
        assert result["transition_hour"] == shoulder_first_mid
        assert result["hours_until"] == (24 - 22) + shoulder_first_mid
        assert result["next_period"] == "mid_peak"

    def test_intra_day_unchanged(self):
        # Mid-summer 10:00 — well inside today; intra-day path, no wrap.
        now = datetime(2026, _summer_month(), 15, 10, 0)
        result = self.engine.get_next_transition(now)
        summer_periods = _periods_for_season("summer")
        first_mid = _first_hour_in(summer_periods["mid_peak"])  # 14
        assert result["transition_hour"] == first_mid
        assert result["hours_until"] == first_mid - 10
        assert result["next_period"] == "mid_peak"
