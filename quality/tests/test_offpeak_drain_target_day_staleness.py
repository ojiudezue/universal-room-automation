"""DRAIN-TARGET-DAY-STALENESS-1 — Tier-3 build acceptance tests.

Cycle: `feature/midnight-drain-target`. Validates INV-DTDS-1..5:

* INV-DTDS-1 — pre-fix byte-identical where `_resolve_target_day` offset==1
  (both evening off-peak AND in-progress-peak with tomorrow's boundary).
* INV-DTDS-2 — offset==0 (target = TODAY): accessor / emitter drain-fallback
  / narration helpers ALL select TODAY's Solcast class, not tomorrow's.
* INV-DTDS-3 — pre-clamp parity across accessor + emitter drain-fallback +
  `_threshold_position` + `_next_action_estimate` on drain-fallback ticks.
* INV-DTDS-4 — multi-day max re-paired against resolver target-day+1, not
  hardcoded D+2.
* INV-DTDS-5 — offset >= 2 unreachable in production (untested by design).

Also covers H-1 (single-source shared helper), HIGH-2 (DP value-stamp
carries peak-anchored composed value) and framing-C mutation targets:
each load-bearing site is expected to become RED under a specific
production-source mutation (mutation drill re-runnable via
`mutate_and_run.py` on demand).
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# HA + package bootstrap (mirrors test_dp_drain_target_value_stamp.py)
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
for _submod_name in (
    "energy_const", "energy_tou", "inclement", "energy_battery",
):
    _full = (
        f"custom_components.universal_room_automation."
        f"domain_coordinators.{_submod_name}"
    )
    _spec = importlib.util.spec_from_file_location(
        _full, os.path.join(_dc_path, f"{_submod_name}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, _mod)

from conftest import MockHass  # noqa: E402

from custom_components.universal_room_automation.domain_coordinators.energy_const import (  # noqa: E402
    DEFAULT_RESERVE_SOC,
    DEFAULT_RESERVE_SOC_ENTITY,
    DEFAULT_STORAGE_MODE_ENTITY,
    DEFAULT_GRID_ENABLED_ENTITY,
    DEFAULT_CHARGE_FROM_GRID_ENTITY,
    DEFAULT_SOLCAST_TODAY_ENTITY,
    DEFAULT_SOLCAST_TOMORROW_ENTITY,
    DEFAULT_WEATHER_ENTITY,
    DEFAULT_OFFPEAK_DRAIN_UNKNOWN,
)
from custom_components.universal_room_automation.domain_coordinators.energy_battery import (  # noqa: E402
    BatteryStrategy,
)

_BATTERY_SOC = "sensor.test_envoy_battery"


class _FakeTOU:
    """Stub of the TOU engine exposing `get_next_high_rate_transition`.

    NOT a `None` fixture — the plan's C-framing hollow-anchor rule
    disallows `_tou = None` (routes to the pre-fix
    `classify_tomorrow_solar()` fallback and would leave the fix
    untested). Callers set `next_transition_dt` to control offset.
    """

    def __init__(self, next_transition_dt: datetime | None, period: str = "peak"):
        self._nxt = next_transition_dt
        self._period = period

    def get_next_high_rate_transition(self, now):
        if self._nxt is None:
            return None
        return (self._nxt, self._period)


def _make_battery(
    *,
    soc: float = 50.0,
    today_kwh: float = 40.0,
    tomorrow_kwh: float = 90.0,
    multi_day: bool = False,
    day3_kwh: float | None = None,
    tou_next_dt: datetime | None = None,
    tou_none: bool = False,
    drain_targets: dict[str, int] | None = None,
):
    """Build a BatteryStrategy with a controlled (today, tomorrow[, D+2])
    Solcast pair and a stubbed TOU engine (unless `tou_none=True`)."""
    hass = MockHass()
    hass.set_state(_BATTERY_SOC, str(soc))
    hass.set_state(DEFAULT_STORAGE_MODE_ENTITY, "self_consumption")
    hass.set_state(DEFAULT_GRID_ENABLED_ENTITY, "on")
    hass.set_state(DEFAULT_CHARGE_FROM_GRID_ENTITY, "off")
    hass.set_state(DEFAULT_RESERVE_SOC_ENTITY, "10")
    hass.set_state(DEFAULT_SOLCAST_TODAY_ENTITY, str(today_kwh))
    hass.set_state(DEFAULT_SOLCAST_TOMORROW_ENTITY, str(tomorrow_kwh))
    hass.set_state(DEFAULT_WEATHER_ENTITY, "sunny")
    # Custom absolute thresholds so class assignments are deterministic
    # across months (avoid Solcast monthly-percentile drift in tests).
    thresholds = {
        "excellent": 100.0,
        "good": 80.0,
        "moderate": 50.0,
        "poor": 30.0,
    }
    strat = BatteryStrategy(
        hass,
        reserve_soc=DEFAULT_RESERVE_SOC,
        entity_config={
            "battery_soc": _BATTERY_SOC,
            # solcast_day_3 wired for the multi-day tests via the D+2 kwh.
        },
        solar_classification_mode="custom",
        custom_solar_thresholds=thresholds,
    )
    strat._inclement_config_override = {}
    strat._multi_day_horizon_enabled = multi_day
    if drain_targets is not None:
        # Preserve DEFAULT_OFFPEAK_DRAIN_UNKNOWN under the "unknown" key
        # (see energy_battery.py:471) to keep _get_offpeak_drain_target
        # fallback stable.
        merged = {"unknown": DEFAULT_OFFPEAK_DRAIN_UNKNOWN}
        merged.update(drain_targets)
        strat._drain_targets = merged
    if day3_kwh is not None:
        # Register the day_3 entity + state so classify_solar_day_n(2)
        # returns a real class.
        _d3 = "sensor.test_solcast_day_3"
        hass.set_state(_d3, str(day3_kwh))
        strat._solcast_day_3_entity = _d3
    if tou_none:
        strat._tou = None
    else:
        strat._tou = _FakeTOU(tou_next_dt)
    return strat, hass


# ---------------------------------------------------------------------------
# D1: _resolve_target_day (offset arithmetic + fallbacks)
# ---------------------------------------------------------------------------


def test_resolve_target_day_offset_0_today_boundary():
    """Next high-rate transition is later today → (today's class, 0)."""
    now = datetime(2026, 6, 11, 2, 0, 0)
    strat, _ = _make_battery(
        today_kwh=60, tomorrow_kwh=110,
        tou_next_dt=datetime(2026, 6, 11, 14, 0, 0),
    )
    cls, offset = strat._resolve_target_day(now)
    assert offset == 0
    assert cls == "moderate"  # today=40 → moderate (30-50 window)


def test_resolve_target_day_offset_1_evening_offpeak():
    """Pre-midnight off-peak → next transition tomorrow → (tomorrow, 1)."""
    now = datetime(2026, 6, 11, 22, 30, 0)
    strat, _ = _make_battery(
        today_kwh=60, tomorrow_kwh=110,
        tou_next_dt=datetime(2026, 6, 12, 14, 0, 0),
    )
    cls, offset = strat._resolve_target_day(now)
    assert offset == 1
    assert cls == "excellent"


def test_resolve_target_day_offset_1_in_progress_peak():
    """M-2 scope: in-progress peak (no transition today) → offset==1."""
    now = datetime(2026, 6, 11, 16, 0, 0)  # summer peak 14-21 in progress
    strat, _ = _make_battery(
        today_kwh=60, tomorrow_kwh=110,
        tou_next_dt=datetime(2026, 6, 12, 14, 0, 0),
    )
    cls, offset = strat._resolve_target_day(now)
    assert offset == 1
    assert cls == "excellent"


def test_resolve_target_day_no_tou_fallback():
    """TOU unwired → (classify_tomorrow_solar(), 1) — INV-DTDS-1 fallback."""
    strat, _ = _make_battery(
        today_kwh=60, tomorrow_kwh=110, tou_none=True,
    )
    cls, offset = strat._resolve_target_day(datetime(2026, 6, 11, 2, 0, 0))
    assert offset == 1
    assert cls == "excellent"


def test_resolve_target_day_no_transition_fallback():
    """`get_next_high_rate_transition` returns None → same fallback shape."""
    strat, _ = _make_battery(
        today_kwh=60, tomorrow_kwh=110, tou_next_dt=None,
    )
    cls, offset = strat._resolve_target_day(datetime(2026, 6, 11, 2, 0, 0))
    assert offset == 1
    assert cls == "excellent"


def test_classify_target_day_delegates_to_resolver():
    """Backwards-compat: existing arbitrage callers of `_classify_target_day`
    read the same class the resolver returns at index 0."""
    now = datetime(2026, 6, 11, 2, 0, 0)
    strat, _ = _make_battery(
        today_kwh=60, tomorrow_kwh=110,
        tou_next_dt=datetime(2026, 6, 11, 14, 0, 0),
    )
    assert strat._classify_target_day(now) == strat._resolve_target_day(now)[0]


# ---------------------------------------------------------------------------
# D1b: _drain_target_for — single source of truth, multi-day max leg
# ---------------------------------------------------------------------------


def test_drain_target_for_offset_0_selects_today():
    """INV-DTDS-2: at offset==0, drain reads TODAY's class (not tomorrow)."""
    now = datetime(2026, 6, 11, 2, 0, 0)
    strat, _ = _make_battery(
        today_kwh=60, tomorrow_kwh=110,  # today=moderate, tomorrow=excellent
        tou_next_dt=datetime(2026, 6, 11, 14, 0, 0),
        drain_targets={"excellent": 10, "moderate": 25, "poor": 40},
    )
    # moderate → 25, NOT excellent → 10 (the pre-fix answer).
    assert strat._drain_target_for(now) == 25


def test_drain_target_for_multi_day_max_across_day1_day2():
    """H-1 6th-site guard / INV-DTDS-4: with multi_day_horizon_enabled and
    a today-excellent / D+1-poor pair at offset==0, `_drain_target_for`
    returns `max(d1=excellent=10, d2=poor=40) == 40`. Mutating the max
    leg to hard-return `d1_target` would drop this to 10 → this test
    (C-6th) goes RED."""
    now = datetime(2026, 6, 11, 2, 0, 0)
    strat, _ = _make_battery(
        today_kwh=110, tomorrow_kwh=25,   # today=excellent, D+1=poor
        multi_day=True, day3_kwh=25,
        tou_next_dt=datetime(2026, 6, 11, 14, 0, 0),
        drain_targets={"excellent": 10, "moderate": 25, "poor": 40},
    )
    assert strat._drain_target_for(now) == 40


def test_drain_target_for_multi_day_disabled_returns_d1_only():
    now = datetime(2026, 6, 11, 2, 0, 0)
    strat, _ = _make_battery(
        today_kwh=110, tomorrow_kwh=25, multi_day=False,
        tou_next_dt=datetime(2026, 6, 11, 14, 0, 0),
        drain_targets={"excellent": 10, "moderate": 25, "poor": 40},
    )
    assert strat._drain_target_for(now) == 10  # today=excellent → 10


# ---------------------------------------------------------------------------
# D2: accessor threads `now`, defaults to dt_util.now(), delegates
# ---------------------------------------------------------------------------


def test_current_offpeak_drain_target_no_arg_defaults_to_now(monkeypatch):
    """Accessor with no arg falls back to dt_util.now(); result equals
    `_drain_target_for(that_now)`."""
    fixed = datetime(2026, 6, 11, 2, 0, 0)
    strat, _ = _make_battery(
        today_kwh=60, tomorrow_kwh=110,
        tou_next_dt=datetime(2026, 6, 11, 14, 0, 0),
        drain_targets={"excellent": 10, "moderate": 25, "poor": 40},
    )
    # Patch the dt_util the accessor imports lazily.
    import homeassistant.util.dt as _dt
    monkeypatch.setattr(_dt, "now", lambda: fixed)
    assert strat.current_offpeak_drain_target() == strat._drain_target_for(fixed) == 25


def test_current_offpeak_drain_target_offset_1_byte_identical_to_pre_fix():
    """INV-DTDS-1: at offset==1 the accessor returns the same value the
    pre-fix `classify_tomorrow_solar()`-keyed accessor would have."""
    now = datetime(2026, 6, 11, 22, 30, 0)
    strat, _ = _make_battery(
        today_kwh=60, tomorrow_kwh=110,
        tou_next_dt=datetime(2026, 6, 12, 14, 0, 0),
        drain_targets={"excellent": 10, "moderate": 25, "poor": 40},
    )
    tomorrow_pre_fix = strat._get_offpeak_drain_target(strat.classify_tomorrow_solar())
    assert strat.current_offpeak_drain_target(now) == tomorrow_pre_fix == 10


def test_current_offpeak_drain_target_offset_1_in_progress_peak():
    """M-2: in-progress peak with tomorrow's boundary → offset==1 → tomorrow."""
    now = datetime(2026, 6, 11, 16, 0, 0)
    strat, _ = _make_battery(
        today_kwh=60, tomorrow_kwh=110,
        tou_next_dt=datetime(2026, 6, 12, 14, 0, 0),
        drain_targets={"excellent": 10, "moderate": 25, "poor": 40},
    )
    assert strat.current_offpeak_drain_target(now) == 10


def test_current_offpeak_drain_target_med1_fallback_on_tou_raise():
    """MED-1: if `_tou.get_next_high_rate_transition` raises, the resolver's
    guarded fallback returns (classify_tomorrow_solar(), 1); the exception
    does not propagate to the accessor."""
    now = datetime(2026, 6, 11, 2, 0, 0)
    strat, _ = _make_battery(
        today_kwh=60, tomorrow_kwh=110,
        tou_next_dt=datetime(2026, 6, 11, 14, 0, 0),
        drain_targets={"excellent": 10, "moderate": 25, "poor": 40},
    )
    class _Boom:
        def get_next_high_rate_transition(self, now):
            raise RuntimeError("boom")
    strat._tou = _Boom()
    # Resolver's try/except path returns tomorrow — matches pre-fix.
    # (Wrapping intent: accessor must not raise.)
    try:
        val = strat.current_offpeak_drain_target(now)
    except Exception as exc:
        raise AssertionError(f"accessor should not propagate: {exc}")
    # With multi_day off + tomorrow=excellent, expect 10.
    assert val == 10


# ---------------------------------------------------------------------------
# D3: emitter drain-fallback consumes _drain_target_for + DP value-stamp
# ---------------------------------------------------------------------------


def test_emitter_drain_fallback_selects_today_at_offset_0():
    """INV-DTDS-2: emitter's drain-fallback branch commands the target
    keyed on TODAY's class at offset==0."""
    now = datetime(2026, 6, 11, 2, 0, 0)
    strat, _ = _make_battery(
        soc=50, today_kwh=60, tomorrow_kwh=110,
        tou_next_dt=datetime(2026, 6, 11, 14, 0, 0),
        drain_targets={"excellent": 10, "moderate": 25, "poor": 40},
    )
    r = strat.determine_mode("off_peak", "summer", now=now)
    assert "Off-peak" in r["reason"], r["reason"]
    # DP stamp mirrors the composed target (post-clamp; no clamp here).
    # The stamp is the load-bearing observable — HIGH-2 anchor.
    assert strat._offpeak_drain_branch_target == 25


def test_dp_value_stamp_carries_peak_anchored_target():
    """HIGH-2 / framing-C 7th site: the DP value-stamp at
    `_offpeak_drain_branch_target` carries the peak-anchored composed
    target after D3, NOT the pre-fix `classify_tomorrow_solar()`-keyed
    value. Re-pointing the derivation to the OLD calendar-tomorrow lookup
    while leaving the stamp intact would drop this to 10 → this test
    goes RED under that mutation."""
    now = datetime(2026, 6, 11, 2, 0, 0)
    strat, _ = _make_battery(
        soc=50, today_kwh=60, tomorrow_kwh=110,
        tou_next_dt=datetime(2026, 6, 11, 14, 0, 0),
        drain_targets={"excellent": 10, "moderate": 25, "poor": 40},
    )
    strat.determine_mode("off_peak", "summer", now=now)
    assert strat._offpeak_drain_branch_target == 25  # peak-anchored (today)
    # Discriminating: pre-fix would have stamped 10 (tomorrow=excellent).
    assert strat._offpeak_drain_branch_target != 10


# ---------------------------------------------------------------------------
# H-1: single-source-of-truth parity across all four consumers
# ---------------------------------------------------------------------------


def test_drain_target_for_helper_is_single_source_of_truth():
    """H-1 mandate central proof: with multi_day_horizon_enabled and a
    today-excellent / D+1-poor pair at offset==0, accessor +
    `_threshold_position` derived drain + `_next_action_estimate` drain
    fallback + emitter pre-clamp `drain_target` ALL == `_drain_target_for`
    == max(10, 40) == 40."""
    now = datetime(2026, 6, 11, 2, 0, 0)
    strat, _ = _make_battery(
        soc=50, today_kwh=110, tomorrow_kwh=25, multi_day=True,
        day3_kwh=25,
        tou_next_dt=datetime(2026, 6, 11, 14, 0, 0),
        drain_targets={"excellent": 10, "moderate": 25, "poor": 40},
    )
    expected = 40
    assert strat._drain_target_for(now) == expected
    assert strat.current_offpeak_drain_target(now) == expected
    # Emitter drain-fallback branch: SOC=50, drain=40 → stamped 40.
    strat.determine_mode("off_peak", "summer", now=now)
    assert strat._offpeak_drain_branch_target == expected
    # Narration helpers cite the same drain.
    pos = strat._threshold_position(50.0, now)
    nxt = strat._next_action_estimate(50.0, now)
    assert f"{expected}%" in pos, pos
    # _next_action_estimate falls through to drain fallback only when
    # phase is not one of the arbitrage phases; default is "n/a".
    assert f"{expected}%" in nxt, nxt


def test_threshold_position_uses_shared_helper():
    """HIGH-1: `_threshold_position` narrates the shared-helper drain."""
    now = datetime(2026, 6, 11, 2, 0, 0)
    strat, _ = _make_battery(
        soc=60, today_kwh=60, tomorrow_kwh=110,
        tou_next_dt=datetime(2026, 6, 11, 14, 0, 0),
        drain_targets={"excellent": 10, "moderate": 25, "poor": 40},
    )
    s = strat._threshold_position(60.0, now)
    assert "25%" in s, s
    # target-class name cites TODAY's class, not tomorrow's.
    assert "target=moderate" in s, s


def test_next_action_estimate_uses_shared_helper():
    """HIGH-1: `_next_action_estimate` drain fallback cites shared helper."""
    now = datetime(2026, 6, 11, 2, 0, 0)
    strat, _ = _make_battery(
        soc=60, today_kwh=60, tomorrow_kwh=110,
        tou_next_dt=datetime(2026, 6, 11, 14, 0, 0),
        drain_targets={"excellent": 10, "moderate": 25, "poor": 40},
    )
    s = strat._next_action_estimate(60.0, now)
    assert "25%" in s, s
    assert "target=moderate" in s, s


def test_threshold_and_next_action_fallback_uses_default_constant():
    """HIGH-1 constant: with an empty `_drain_targets` map, drain fallback
    returns DEFAULT_OFFPEAK_DRAIN_UNKNOWN (not a bare 40 literal)."""
    now = datetime(2026, 6, 11, 2, 0, 0)
    strat, _ = _make_battery(
        soc=60, today_kwh=60, tomorrow_kwh=110,
        tou_next_dt=datetime(2026, 6, 11, 14, 0, 0),
        drain_targets={},
    )
    d = strat._drain_target_for(now)
    assert d == DEFAULT_OFFPEAK_DRAIN_UNKNOWN
    assert f"{DEFAULT_OFFPEAK_DRAIN_UNKNOWN}%" in strat._threshold_position(60.0, now)


# ---------------------------------------------------------------------------
# INV-DTDS-4: multi-day max repaired against resolver target day
# ---------------------------------------------------------------------------


def test_multi_day_max_repaired_across_midnight():
    """INV-DTDS-4: at offset==0 the multi-day max pair is (today, tomorrow)
    via `classify_solar_day_n(d1_offset + 1)`. Hardcoded D+2 would ignore
    the resolver's offset and pull `solcast_day_3` instead."""
    now = datetime(2026, 6, 11, 2, 0, 0)
    # today=excellent (10), tomorrow=poor (40), D+2=excellent (10). The
    # correct max keyed on (today, tomorrow) is 40. A hardcoded D+2 lookup
    # would return 10.
    strat, _ = _make_battery(
        today_kwh=110, tomorrow_kwh=25, multi_day=True,
        day3_kwh=110,
        tou_next_dt=datetime(2026, 6, 11, 14, 0, 0),
        drain_targets={"excellent": 10, "moderate": 25, "poor": 40},
    )
    assert strat._drain_target_for(now) == 40  # (today=10, tomorrow=40) max


def test_display_attr_tomorrow_solar_class_still_calendar_tomorrow():
    """INV-DTDS-1 display axis: the `tomorrow_solar_class` field the
    emitter surfaces stays keyed on calendar tomorrow (not target-day)."""
    now = datetime(2026, 6, 11, 2, 0, 0)
    strat, _ = _make_battery(
        soc=50, today_kwh=60, tomorrow_kwh=110,
        tou_next_dt=datetime(2026, 6, 11, 14, 0, 0),
        drain_targets={"excellent": 10, "moderate": 25, "poor": 40},
    )
    r = strat.determine_mode("off_peak", "summer", now=now)
    # tomorrow_solar_class in the result reflects the calendar-tomorrow
    # class (excellent), NOT today's (moderate).
    assert r.get("tomorrow_solar_class") == "excellent"


# ---------------------------------------------------------------------------
# Cross-midnight discriminating pair (probe-verified inversion 12-01/02)
# ---------------------------------------------------------------------------


def test_cross_midnight_selects_today_over_tomorrow():
    """Repro-exact using the shape of probe-verified class inversions
    (today=poor / tomorrow=excellent). At 02:00 with offset==0, the
    accessor MUST key TODAY (drain=40), not tomorrow (drain=10)."""
    now = datetime(2025, 12, 1, 2, 0, 0)
    strat, _ = _make_battery(
        today_kwh=40, tomorrow_kwh=110,  # today=poor, tomorrow=excellent
        tou_next_dt=datetime(2025, 12, 1, 17, 0, 0),  # winter afternoon peak
        drain_targets={"excellent": 10, "moderate": 25, "poor": 40},
    )
    assert strat.current_offpeak_drain_target(now) == 40
    strat.determine_mode("off_peak", "winter", now=now)
    assert strat._offpeak_drain_branch_target == 40  # SOC 50 > 40 → stamp 40
