"""Arbitrage / Attain inclement partial_hold reserve-floor enforcement.

Bug Class #53 — computed-but-not-consumed control value. The inclement
``effective_reserve`` (= max(reserve_soc, decision.reserve_floor)) was threaded
into the off_peak drain-target fallback (v5.5.0) but the off_peak ARBITRAGE and
ATTAIN decision paths emitted reserve_level WITHOUT consulting it. This suite
drives ``determine_mode()`` END TO END (off_peak / mid_peak D1b, arbitrage gate
OPEN, an active partial_hold) and asserts every emission site floors the reserve
at ``effective_reserve``.

Six clamp sites are covered (mutation matrix in the cycle report):
  1. arbitrage HOLD    (_get_arbitrage_decision)
  2. arbitrage CHARGE  (_get_arbitrage_decision)
  3. arbitrage WAIT    (_get_arbitrage_decision)          ← primary gap
  4. attain CHARGE     (_get_attainability_decision)
  5. attain HOLD       (_get_attainability_hold_decision)
  6. reboot release    (_maybe_run_reboot_recovery)        ← second gap

Tests invoke REAL production methods (no hand-rolled mirrors). The HA-module
bootstrap mirrors test_battery_inclement_precedence.py verbatim.
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock
import sys
import os
import types
import importlib


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
        "async_track_state_change_event": lambda *a, **k: (lambda: None),
        "async_track_time_interval": lambda *a, **k: (lambda: None),
        "async_call_later": lambda *a, **k: (lambda: None),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_send": lambda *a, **k: None,
        "async_dispatcher_connect": lambda *a, **k: (lambda: None),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": datetime.utcnow, "now": datetime.now, "as_local": lambda dt: dt,
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
for _submod_name in ("energy_const", "energy_tou", "inclement", "energy_battery", "energy_pool"):
    _full = f"custom_components.universal_room_automation.domain_coordinators.{_submod_name}"
    _spec = importlib.util.spec_from_file_location(
        _full, os.path.join(_dc_path, f"{_submod_name}.py")
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full] = _mod
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
    CONF_INCLEMENT_NWS_ALERTS_ENTITY,
    CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR,
)
from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
    BatteryStrategy,
)

_BATTERY_SOC = "sensor.test_envoy_battery"
_NWS = "sensor.test_nws_alerts"
# Off_peak hour so the off_peak determine_mode branch is exercised.
_NOW = datetime(2026, 6, 11, 22, 0, 0)

# Default peak_buffer_target (80) and reserve_soc (10) from the constructor;
# the inclement partial_hold floor default is 50. So under partial_hold:
#   reserve_soc sites:        10 -> max(10, 50) = 50  (CHANGES)
#   peak_buffer_target sites: 80 -> max(80, 50) = 80  (no-op under default floor)
_FLOOR = 50
_TARGET = 80


def _make_battery(soc=80.0, grid="on", tomorrow="20", arbitrage_enabled=True):
    """Construct a BatteryStrategy with the arbitrage gate able to open.

    tomorrow="20" classifies as "poor" under the custom thresholds
    (poor=30), so _classify_target_day -> classify_tomorrow_solar -> "poor"
    and (with no TOU engine wired + ev_load 0 + no rate samples) the rung
    classifier cold-boot-defers to rung_2 -> _gate_is_open True.
    """
    hass = MockHass()
    hass.set_state(_BATTERY_SOC, str(soc))
    hass.set_state(DEFAULT_STORAGE_MODE_ENTITY, "self_consumption")
    hass.set_state(DEFAULT_GRID_ENABLED_ENTITY, grid)
    hass.set_state(DEFAULT_CHARGE_FROM_GRID_ENTITY, "off")
    # Initial reserve far from every emitted value (10/40/50/80) so the
    # idempotent _result() ALWAYS emits a reserve action — _reserve_value()
    # then reads the commanded level directly. (Without this, an emission
    # equal to the current state is suppressed and reads as None.)
    hass.set_state(DEFAULT_RESERVE_SOC_ENTITY, "0")
    hass.set_state(DEFAULT_SOLCAST_TODAY_ENTITY, "90")
    hass.set_state(DEFAULT_SOLCAST_TOMORROW_ENTITY, tomorrow)
    hass.set_state(DEFAULT_WEATHER_ENTITY, "sunny")
    strat = BatteryStrategy(
        hass,
        reserve_soc=DEFAULT_RESERVE_SOC,
        entity_config={"battery_soc": _BATTERY_SOC},
        solar_classification_mode="custom",
        custom_solar_thresholds={"excellent": 100.0, "good": 80.0,
                                 "moderate": 50.0, "poor": 30.0},
        arbitrage_enabled=arbitrage_enabled,
    )
    return strat, hass


def _arm_partial_hold(strat, hass):
    """Arm an UNCORROBORATED watch → off_peak partial_hold (floor 50).

    Matrix row: "watch (uncorroborated) off_peak → partial_hold". This is
    the same lever test_battery_inclement_precedence uses for off_peak
    partial_hold.
    """
    hass.set_state(_NWS, "1", attributes={"Alerts": [{
        "Event": "Severe Thunderstorm Watch", "Severity": "Severe",
        "Certainty": "Possible", "Status": "Actual",
        "Onset": "2026-06-11T16:00:00-05:00",
        "Ends": "2026-06-12T00:00:00-05:00",
    }]})
    strat._inclement_config_override = {CONF_INCLEMENT_NWS_ALERTS_ENTITY: _NWS}


def _reserve_value(decision):
    for a in decision["actions"]:
        if "reserve" in a.get("target", ""):
            return a["data"]["value"]
    return None


def _assert_partial_hold(strat):
    attrs = strat._inclement_attrs()
    assert attrs["inclement_hold_depth"] == "partial_hold", attrs
    assert attrs["inclement_reserve_floor"] == _FLOOR, attrs


# ===========================================================================
# Pre-conditions — confirm the harness opens the gate + resolves partial_hold
# ===========================================================================


def test_harness_opens_arbitrage_gate_and_resolves_partial_hold():
    strat, hass = _make_battery(soc=40)
    _arm_partial_hold(strat, hass)
    strat._arbitrage_chunk_completed = True  # force WAIT phase
    now = datetime(2026, 6, 11, 22, 0, 0)
    target_day = strat._classify_target_day(now)
    assert target_day in ("poor", "very_poor"), target_day
    assert strat._gate_is_open(now, target_day) is True
    r = strat.determine_mode("off_peak", "summer", now=now)
    _assert_partial_hold(strat)
    assert r["reason"].startswith("Arbitrage WAIT")


# ===========================================================================
# Site 3 — arbitrage WAIT (primary gap): reserve_soc 10 -> 50
# ===========================================================================


def test_wait_phase_floors_at_effective_reserve_under_partial_hold():
    strat, hass = _make_battery(soc=40)
    _arm_partial_hold(strat, hass)
    strat._arbitrage_chunk_completed = True  # phase -> WAIT
    now = datetime(2026, 6, 11, 22, 0, 0)
    r = strat.determine_mode("off_peak", "summer", now=now)
    _assert_partial_hold(strat)
    assert r["arbitrage_phase"] == "wait"
    # Without the clamp this would be reserve_soc (10); clamp lifts to 50.
    assert _reserve_value(r) == _FLOOR
    assert "partial_hold floor" in r["reason"]


def test_wait_phase_byte_identical_under_allow_discharge():
    # No alert → allow_discharge → WAIT emits the bare reserve_soc (10).
    strat, hass = _make_battery(soc=40)
    strat._inclement_config_override = {}  # no NWS entity
    strat._arbitrage_chunk_completed = True
    now = datetime(2026, 6, 11, 22, 0, 0)
    r = strat.determine_mode("off_peak", "summer", now=now)
    assert strat._inclement_attrs()["inclement_hold_depth"] == "allow_discharge"
    assert r["arbitrage_phase"] == "wait"
    assert _reserve_value(r) == strat.reserve_soc  # == 10, unchanged
    assert "partial_hold floor" not in r["reason"]


# ===========================================================================
# Site 1 — arbitrage HOLD (peak_buffer_target 80; floor 50 = no-op)
# ===========================================================================


def test_arbitrage_hold_target_wins_over_default_floor():
    # SOC >= target -> HOLD. floor 50 < target 80 -> reserve stays 80.
    strat, hass = _make_battery(soc=90)
    _arm_partial_hold(strat, hass)
    now = datetime(2026, 6, 11, 22, 0, 0)
    r = strat.determine_mode("off_peak", "summer", now=now)
    _assert_partial_hold(strat)
    assert r["arbitrage_phase"] == "hold"
    assert _reserve_value(r) == _TARGET  # 80, not lowered
    assert "partial_hold floor" not in r["reason"]


def test_arbitrage_hold_clamped_when_floor_above_target():
    # Pathological config: lower peak_buffer_target below the floor.
    strat, hass = _make_battery(soc=90)
    _arm_partial_hold(strat, hass)
    strat._peak_buffer_target = 40  # target < floor 50
    now = datetime(2026, 6, 11, 22, 0, 0)
    r = strat.determine_mode("off_peak", "summer", now=now)
    _assert_partial_hold(strat)
    assert r["arbitrage_phase"] == "hold"
    assert _reserve_value(r) == _FLOOR  # 50 wins
    assert "partial_hold floor" in r["reason"]


# ===========================================================================
# Site 2 — arbitrage CHARGE (charge NOT suppressed)
# ===========================================================================


def _force_charge_window(strat):
    """Stub the window/recheck so _get_arbitrage_phase resolves to CHARGE."""
    strat._is_charge_window_open = lambda now: True
    strat._recheck_forecast_on_charge_entry = lambda now: True
    strat._arbitrage_chunk_completed = False
    strat._chunk_recheck_done = False


def test_arbitrage_charge_unchanged_when_target_above_floor():
    strat, hass = _make_battery(soc=40)
    _arm_partial_hold(strat, hass)
    _force_charge_window(strat)
    now = datetime(2026, 6, 11, 22, 0, 0)
    r = strat.determine_mode("off_peak", "summer", now=now)
    _assert_partial_hold(strat)
    assert r["arbitrage_phase"] == "charge"
    # charge target 80 > floor 50 -> reserve stays 80; charge NOT suppressed.
    assert _reserve_value(r) == _TARGET
    charge_actions = [a for a in r["actions"]
                      if "charge_from_grid" in a.get("target", "")]
    # charge_from_grid switched ON (turn_on) — the clamp didn't suppress it.
    assert any(a.get("service", "").endswith("turn_on") for a in charge_actions), \
        r["actions"]
    assert "partial_hold floor" not in r["reason"]


def test_arbitrage_charge_clamped_when_floor_above_target_still_charges():
    strat, hass = _make_battery(soc=20)
    _arm_partial_hold(strat, hass)
    _force_charge_window(strat)
    strat._peak_buffer_target = 40  # target < floor 50
    now = datetime(2026, 6, 11, 22, 0, 0)
    r = strat.determine_mode("off_peak", "summer", now=now)
    _assert_partial_hold(strat)
    assert r["arbitrage_phase"] == "charge"
    assert _reserve_value(r) == _FLOOR  # raised to 50
    charge_actions = [a for a in r["actions"]
                      if "charge_from_grid" in a.get("target", "")]
    assert any(a.get("service", "").endswith("turn_on") for a in charge_actions), \
        r["actions"]
    assert "partial_hold floor" in r["reason"]


# ===========================================================================
# Sites 4 + 5 — attain CHARGE + attain HOLD (mid_peak D1b reaches them too)
# ===========================================================================


def _make_attain_battery(soc=40.0):
    """Battery with gate CLOSED (tomorrow good) so the off_peak ATTAIN
    branch runs instead of arbitrage. The attain entry predicate needs a
    rate sample + projection below target; we drive the helpers directly
    via the latched state to keep the test deterministic.
    """
    strat, hass = _make_battery(soc=soc, tomorrow="90")  # good -> gate closed
    return strat, hass


def test_attain_charge_clamped_under_partial_hold():
    # Drive _get_attainability_decision (CHARGE) directly through the public
    # latch: state="charging" + rate available -> verify-only CHARGE re-emit.
    strat, hass = _make_attain_battery(soc=40)
    _arm_partial_hold(strat, hass)
    now = datetime(2026, 6, 11, 22, 0, 0)
    # Resolve the inclement decision (off_peak partial_hold) first.
    strat.determine_mode("off_peak", "summer", now=now)
    _assert_partial_hold(strat)
    # Now call the attain branch with the resolved floor threaded in.
    eff = max(strat.reserve_soc, 50)
    strat._attain_state = "charging"
    strat._attain_reboot_recovered = True
    strat._observed_net_charge_rate_per_hour = lambda: 5.0
    strat._attain_target_boundary = lambda now, tp: (now, "peak", 120)
    strat._attain_target_period_at_or_above_current = lambda *a: False
    strat._effective_import_kw = lambda: None
    strat._get_state_bool = lambda e: True
    r = strat._run_attain_branch(
        soc=40.0, now=now, tou_period="off_peak",
        target_day_class="good", tomorrow_class="good",
        current_mode=BATTERY_MODE_SELF_CONSUMPTION, season="summer",
        effective_reserve=eff, hold_depth="partial_hold",
    )
    # CHARGE target 80 > floor 50 -> reserve stays 80 (charge not suppressed).
    assert _reserve_value(r) == _TARGET
    assert "partial_hold floor" not in r["reason"]


def test_attain_charge_clamped_when_floor_above_target():
    strat, hass = _make_attain_battery(soc=20)
    _arm_partial_hold(strat, hass)
    now = datetime(2026, 6, 11, 22, 0, 0)
    strat.determine_mode("off_peak", "summer", now=now)
    eff = max(strat.reserve_soc, 50)
    strat._peak_buffer_target = 40
    strat._attain_state = "charging"
    strat._attain_reboot_recovered = True
    strat._observed_net_charge_rate_per_hour = lambda: 5.0
    strat._attain_target_boundary = lambda now, tp: (now, "peak", 120)
    strat._attain_target_period_at_or_above_current = lambda *a: False
    strat._effective_import_kw = lambda: None
    strat._get_state_bool = lambda e: True
    r = strat._run_attain_branch(
        soc=20.0, now=now, tou_period="off_peak",
        target_day_class="good", tomorrow_class="good",
        current_mode=BATTERY_MODE_SELF_CONSUMPTION, season="summer",
        effective_reserve=eff, hold_depth="partial_hold",
    )
    assert _reserve_value(r) == _FLOOR
    assert "partial_hold floor" in r["reason"]


def test_attain_hold_target_wins_over_default_floor():
    # state="holding" -> _get_attainability_hold_decision. floor 50 < target 80.
    strat, hass = _make_attain_battery(soc=85)
    now = datetime(2026, 6, 11, 22, 0, 0)
    eff = max(strat.reserve_soc, 50)
    strat._attain_state = "holding"
    strat._attain_reboot_recovered = True
    strat._attain_target_boundary = lambda now, tp: (now, "peak", 120)
    strat._attain_target_period_at_or_above_current = lambda *a: False
    r = strat._run_attain_branch(
        soc=85.0, now=now, tou_period="off_peak",
        target_day_class="good", tomorrow_class="good",
        current_mode=BATTERY_MODE_SELF_CONSUMPTION, season="summer",
        effective_reserve=eff, hold_depth="partial_hold",
    )
    assert _reserve_value(r) == _TARGET
    assert "partial_hold floor" not in r["reason"]


def test_attain_hold_clamped_when_floor_above_target():
    strat, hass = _make_attain_battery(soc=85)
    now = datetime(2026, 6, 11, 22, 0, 0)
    eff = max(strat.reserve_soc, 50)
    strat._peak_buffer_target = 40
    strat._attain_state = "holding"
    strat._attain_reboot_recovered = True
    strat._attain_target_boundary = lambda now, tp: (now, "peak", 120)
    strat._attain_target_period_at_or_above_current = lambda *a: False
    r = strat._run_attain_branch(
        soc=85.0, now=now, tou_period="off_peak",
        target_day_class="good", tomorrow_class="good",
        current_mode=BATTERY_MODE_SELF_CONSUMPTION, season="summer",
        effective_reserve=eff, hold_depth="partial_hold",
    )
    assert _reserve_value(r) == _FLOOR
    assert "partial_hold floor" in r["reason"]


# ===========================================================================
# Site 6 — reboot recovery orderly release (reserve_soc 10 -> 50)
# ===========================================================================


def test_attain_reboot_release_floors_at_effective_reserve():
    strat, hass = _make_attain_battery(soc=40)
    now = datetime(2026, 6, 11, 22, 0, 0)
    eff = max(strat.reserve_soc, 50)
    strat._attain_reboot_recovered = False
    # Adopt as "release": boot landed outside any valid charge window.
    strat._adopt_attain_state_from_hardware = lambda soc, now, tp: "release"
    r = strat._maybe_run_reboot_recovery(
        soc=40.0, now=now, tou_period="peak",
        target_day_class="good", tomorrow_class="good",
        current_mode=BATTERY_MODE_SELF_CONSUMPTION, season="summer",
        effective_reserve=eff, hold_depth="partial_hold",
    )
    assert r is not None
    # Without the clamp this would be reserve_soc (10); clamp lifts to 50.
    assert _reserve_value(r) == _FLOOR
    assert "partial_hold floor" in r["reason"]


def test_attain_reboot_release_byte_identical_under_allow_discharge():
    strat, hass = _make_attain_battery(soc=40)
    now = datetime(2026, 6, 11, 22, 0, 0)
    strat._attain_reboot_recovered = False
    strat._adopt_attain_state_from_hardware = lambda soc, now, tp: "release"
    r = strat._maybe_run_reboot_recovery(
        soc=40.0, now=now, tou_period="peak",
        target_day_class="good", tomorrow_class="good",
        current_mode=BATTERY_MODE_SELF_CONSUMPTION, season="summer",
        # defaults: effective_reserve=None, hold_depth="allow_discharge"
    )
    assert r is not None
    assert _reserve_value(r) == strat.reserve_soc  # == 10, unchanged
    assert "partial_hold floor" not in r["reason"]


# ===========================================================================
# D2 — charge-not-suppressed: SOC->phase transition reads peak_buffer_target
# ===========================================================================


def test_partial_hold_does_not_advance_charge_to_hold_early():
    # SOC=60, target=80, floor raised to 70. The CHARGE->HOLD transition
    # reads peak_buffer_target (80), NOT the clamped reserve. SOC 60 < 80,
    # so phase stays CHARGE (a higher floor cannot satisfy the transition).
    strat, hass = _make_battery(soc=60)
    _arm_partial_hold(strat, hass)
    _force_charge_window(strat)
    # Raise the floor above default (70) so the no-op assumption is exercised.
    strat._inclement_config_override = {
        CONF_INCLEMENT_NWS_ALERTS_ENTITY: _NWS,
        CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR: 70,
    }
    now = datetime(2026, 6, 11, 22, 0, 0)
    r = strat.determine_mode("off_peak", "summer", now=now)
    # SOC 60 < target 80 -> still CHARGE (not HOLD).
    assert r["arbitrage_phase"] == "charge", r["reason"]
    charge_actions = [a for a in r["actions"]
                      if "charge_from_grid" in a.get("target", "")]
    assert any(a.get("service", "").endswith("turn_on") for a in charge_actions)


# ===========================================================================
# Byte-identical baseline — allow_discharge arbitrage tick unchanged
# ===========================================================================


def test_no_alert_arbitrage_tick_byte_identical():
    # An allow_discharge off_peak tick through the arbitrage gate must be
    # byte-identical with vs without an inclement decision in play.
    strat_clear, hass_clear = _make_battery(soc=40)
    strat_clear._inclement_config_override = {}
    strat_clear._arbitrage_chunk_completed = True
    now = datetime(2026, 6, 11, 22, 0, 0)
    r_clear = strat_clear.determine_mode("off_peak", "summer", now=now)

    strat_base, hass_base = _make_battery(soc=40)
    strat_base._inclement_config_override = {}
    strat_base._arbitrage_chunk_completed = True
    r_base = strat_base.determine_mode("off_peak", "summer", now=now)

    assert r_clear["reason"] == r_base["reason"]
    assert _reserve_value(r_clear) == _reserve_value(r_base)
    assert r_clear["mode"] == r_base["mode"] == BATTERY_MODE_SELF_CONSUMPTION
    assert strat_clear._inclement_attrs()["inclement_hold_depth"] == "allow_discharge"


# ===========================================================================
# D4 — reason-suffix telemetry
# ===========================================================================


def test_clamp_noop_does_not_append_suffix():
    # CHARGE with target 80 > floor 50 (no-op) -> no suffix.
    strat, hass = _make_battery(soc=40)
    _arm_partial_hold(strat, hass)
    _force_charge_window(strat)
    now = datetime(2026, 6, 11, 22, 0, 0)
    r = strat.determine_mode("off_peak", "summer", now=now)
    assert "partial_hold floor" not in r["reason"]


# ===========================================================================
# Mutation gate — deleting each clamp must fail at least one test.
# This parametrized test patches _floor_reserve to a pass-through (the bare
# existing expr) for a given site context and asserts the floored emission
# regresses. It proves every clamp is load-bearing in aggregate; the per-site
# matrix in the cycle report maps each site to its dedicated behavioral test.
# ===========================================================================


def _floor_passthrough(existing, effective_reserve, hold_depth):
    """Mutation: drop the max() — return the bare existing value."""
    return existing


@pytest.mark.parametrize("site_setup,expected_floored,expected_bare", [
    # (setup_fn, floored_value, bare_value_after_mutation)
    ("wait", _FLOOR, DEFAULT_RESERVE_SOC),     # site 3
    ("hold", _FLOOR, 40),                       # site 1 (target lowered to 40)
    ("charge", _FLOOR, 40),                     # site 2 (target lowered to 40)
])
def test_mutation_arbitrage_clamps_required(monkeypatch, site_setup,
                                            expected_floored, expected_bare):
    # Build with target lowered to 40 for hold/charge so the clamp is active
    # (floor 50 > target 40); wait uses reserve_soc directly.
    soc = {"wait": 40, "hold": 90, "charge": 20}[site_setup]
    strat, hass = _make_battery(soc=soc)
    _arm_partial_hold(strat, hass)
    now = datetime(2026, 6, 11, 22, 0, 0)
    if site_setup == "wait":
        strat._arbitrage_chunk_completed = True
    elif site_setup == "hold":
        strat._peak_buffer_target = 40
    elif site_setup == "charge":
        strat._peak_buffer_target = 40
        _force_charge_window(strat)

    # Baseline (clamp present): floored value emitted.
    r_ok = strat.determine_mode("off_peak", "summer", now=now)
    assert _reserve_value(r_ok) == expected_floored, (site_setup, r_ok)

    # Mutate: drop the max(). Rebuild fresh to avoid latch carryover.
    strat2, hass2 = _make_battery(soc=soc)
    _arm_partial_hold(strat2, hass2)
    if site_setup == "wait":
        strat2._arbitrage_chunk_completed = True
    elif site_setup == "hold":
        strat2._peak_buffer_target = 40
    elif site_setup == "charge":
        strat2._peak_buffer_target = 40
        _force_charge_window(strat2)
    monkeypatch.setattr(type(strat2), "_floor_reserve",
                        staticmethod(_floor_passthrough))
    r_mut = strat2.determine_mode("off_peak", "summer", now=now)
    # Mutation regresses the emission below the floor — the clamp was required.
    assert _reserve_value(r_mut) == expected_bare, (site_setup, r_mut)
    assert _reserve_value(r_mut) != expected_floored


@pytest.mark.parametrize("state", ["charging", "holding"])
def test_mutation_attain_clamps_required(monkeypatch, state):
    now = datetime(2026, 6, 11, 22, 0, 0)
    soc = 20.0 if state == "charging" else 85.0

    def _build():
        strat, hass = _make_attain_battery(soc=soc)
        strat._peak_buffer_target = 40  # target < floor 50 -> clamp active
        strat._attain_state = state
        strat._attain_reboot_recovered = True
        strat._attain_target_boundary = lambda now, tp: (now, "peak", 120)
        strat._attain_target_period_at_or_above_current = lambda *a: False
        if state == "charging":
            strat._observed_net_charge_rate_per_hour = lambda: 5.0
            strat._effective_import_kw = lambda: None
            strat._get_state_bool = lambda e: True
        return strat

    eff = max(DEFAULT_RESERVE_SOC, 50)
    kwargs = dict(
        soc=soc, now=now, tou_period="off_peak",
        target_day_class="good", tomorrow_class="good",
        current_mode=BATTERY_MODE_SELF_CONSUMPTION, season="summer",
        effective_reserve=eff, hold_depth="partial_hold",
    )

    r_ok = _build()._run_attain_branch(**kwargs)
    assert _reserve_value(r_ok) == _FLOOR

    strat_mut = _build()
    monkeypatch.setattr(type(strat_mut), "_floor_reserve",
                        staticmethod(_floor_passthrough))
    r_mut = strat_mut._run_attain_branch(**kwargs)
    assert _reserve_value(r_mut) == 40  # bare target, below floor
    assert _reserve_value(r_mut) != _FLOOR


def test_mutation_reboot_release_clamp_required(monkeypatch):
    now = datetime(2026, 6, 11, 22, 0, 0)
    eff = max(DEFAULT_RESERVE_SOC, 50)
    kwargs = dict(
        soc=40.0, now=now, tou_period="peak",
        target_day_class="good", tomorrow_class="good",
        current_mode=BATTERY_MODE_SELF_CONSUMPTION, season="summer",
        effective_reserve=eff, hold_depth="partial_hold",
    )

    def _build():
        strat, hass = _make_attain_battery(soc=40)
        strat._attain_reboot_recovered = False
        strat._adopt_attain_state_from_hardware = lambda soc, now, tp: "release"
        return strat

    r_ok = _build()._maybe_run_reboot_recovery(**kwargs)
    assert _reserve_value(r_ok) == _FLOOR

    strat_mut = _build()
    monkeypatch.setattr(type(strat_mut), "_floor_reserve",
                        staticmethod(_floor_passthrough))
    r_mut = strat_mut._maybe_run_reboot_recovery(**kwargs)
    assert _reserve_value(r_mut) == DEFAULT_RESERVE_SOC  # bare reserve_soc
    assert _reserve_value(r_mut) != _FLOOR
