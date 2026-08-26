"""ARBITRAGE-GATE-D2-OFFBYONE-1 — Tier 2-DB build acceptance tests.

Cycle: `feature/arbitrage-gate-d2-offbyone`.

The bug: the arbitrage gate pairs the peak-anchored target day
(`_classify_target_day` -> `_resolve_target_day`) with a HARDCODED
`classify_solar_day_n(2)` for the multi-day broadening leg. When the
target day is TODAY (offset 0, in the cross-midnight window), the gate
compares today against the day-AFTER-tomorrow and SKIPS the actual next
day (tomorrow).

The fix (mirrors DRAIN-TARGET-DAY-STALENESS-1 at energy_battery.py:5463):
derive the second day as `target_offset + 1` from `_resolve_target_day`.
On the pre-midnight (offset==1) path, `target_offset + 1 == 2` — the fix
is byte-identical there.

Discriminator: set today=moderate, tomorrow=excellent, day_3=poor. With
target_day=TODAY (offset 0) and multi_day enabled:
  * Pre-fix code queries n=2 -> "poor"      -> gate opens (WRONG).
  * Post-fix code queries n=1 (tomorrow)    -> "excellent" -> stays
    closed (CORRECT — the actual next day is sunny).

Mutation drill: reverting `target_offset + 1` back to a literal `2` at
_gate_is_open and _check_arbitrage_gate makes the corresponding tests
here go RED.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import types
from datetime import datetime
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# HA + package bootstrap (mirrors test_offpeak_drain_target_day_staleness.py)
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
for _submod_name in ("energy_const", "energy_tou", "inclement", "energy_battery"):
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
)
from custom_components.universal_room_automation.domain_coordinators.energy_battery import (  # noqa: E402
    BatteryStrategy,
)


_BATTERY_SOC = "sensor.test_envoy_battery"


class _FakeTOU:
    def __init__(self, next_transition_dt, period="peak"):
        self._nxt = next_transition_dt
        self._period = period

    def get_next_high_rate_transition(self, now):
        if self._nxt is None:
            return None
        return (self._nxt, self._period)


def _make_battery(*, today_kwh, tomorrow_kwh, day3_kwh, tou_next_dt):
    hass = MockHass()
    hass.set_state(_BATTERY_SOC, "50")
    hass.set_state(DEFAULT_STORAGE_MODE_ENTITY, "self_consumption")
    hass.set_state(DEFAULT_GRID_ENABLED_ENTITY, "on")
    hass.set_state(DEFAULT_CHARGE_FROM_GRID_ENTITY, "off")
    hass.set_state(DEFAULT_RESERVE_SOC_ENTITY, "10")
    hass.set_state(DEFAULT_SOLCAST_TODAY_ENTITY, str(today_kwh))
    hass.set_state(DEFAULT_SOLCAST_TOMORROW_ENTITY, str(tomorrow_kwh))
    hass.set_state(DEFAULT_WEATHER_ENTITY, "sunny")
    thresholds = {"excellent": 100.0, "good": 80.0, "moderate": 50.0, "poor": 30.0}
    strat = BatteryStrategy(
        hass,
        reserve_soc=DEFAULT_RESERVE_SOC,
        entity_config={"battery_soc": _BATTERY_SOC},
        solar_classification_mode="custom",
        custom_solar_thresholds=thresholds,
    )
    strat._inclement_config_override = {}
    strat._multi_day_horizon_enabled = True
    strat._arbitrage_enabled = True
    _d3 = "sensor.test_solcast_day_3"
    hass.set_state(_d3, str(day3_kwh))
    strat._solcast_day_3_entity = _d3
    strat._tou = _FakeTOU(tou_next_dt)
    return strat, hass


def _spy_classify_calls(strat):
    """Record every argument passed to classify_solar_day_n."""
    calls = []
    orig = strat.classify_solar_day_n

    def _spy(n, now=None):
        calls.append(n)
        return orig(n, now=now)

    strat.classify_solar_day_n = _spy  # type: ignore[assignment]
    return calls


# ---------------------------------------------------------------------------
# Discriminator: gate must pair TODAY (offset 0) with TOMORROW (n=1),
# NOT day_3 (n=2). Pre-fix code (hardcoded n=2) would call n=2 here.
# ---------------------------------------------------------------------------


def test_gate_is_open_offset0_pairs_today_with_tomorrow_not_day3():
    """INV: _gate_is_open at offset==0 queries n=1 (tomorrow), never n=2.

    Setup: today=moderate (40 kWh), tomorrow=excellent (110 kWh),
    day_3=poor (20 kWh). Next high-rate transition is later TODAY ->
    _resolve_target_day returns (target_class="moderate", offset=0).

    Pre-fix (hardcoded n=2): gate would read day_3=poor -> open (BUG:
    tomorrow is sunny; we should not be arbitrage-charging).
    Post-fix (target_offset+1==1): gate reads tomorrow=excellent ->
    stays closed.
    """
    now = datetime(2026, 6, 11, 2, 0, 0)
    strat, _ = _make_battery(
        today_kwh=60, tomorrow_kwh=110, day3_kwh=20,
        tou_next_dt=datetime(2026, 6, 11, 14, 0, 0),
    )
    _, offset = strat._resolve_target_day(now)
    assert offset == 0

    calls = _spy_classify_calls(strat)
    opened = strat._gate_is_open(now, "moderate")

    assert opened is False, (
        "Gate must stay closed when target=today=moderate and "
        "tomorrow=excellent. Pre-fix code paired today with day_3=poor "
        "(offbyone) and opened the gate incorrectly."
    )
    assert 1 in calls and 2 not in calls, (
        f"Gate must query n=target_offset+1==1 at offset==0, not the "
        f"hardcoded n=2. Actual classify_solar_day_n calls: {calls}"
    )


def test_recheck_forecast_on_charge_entry_offset0_pairs_tomorrow():
    """Site 1 (_recheck_forecast_on_charge_entry) — same invariant.

    At offset==0 the WAIT->CHARGE re-check must consult tomorrow (n=1),
    not day_3 (n=2). Setup mirrors the offset==0 discriminator: today
    moderate, tomorrow excellent, day_3 poor. Pre-fix code queried n=2
    (poor) and re-authorized CHARGE incorrectly; post-fix queries n=1
    (excellent) and legitimately declines to re-authorize.
    """
    now = datetime(2026, 6, 11, 2, 0, 0)
    strat, _ = _make_battery(
        today_kwh=60, tomorrow_kwh=110, day3_kwh=20,
        tou_next_dt=datetime(2026, 6, 11, 14, 0, 0),
    )
    _, offset = strat._resolve_target_day(now)
    assert offset == 0
    calls = _spy_classify_calls(strat)
    keep_wait = strat._recheck_forecast_on_charge_entry(now)
    assert keep_wait is False, (
        "Re-check must return False (target=today=moderate, tomorrow="
        "excellent) so caller does NOT re-authorize CHARGE. Pre-fix "
        "code returned True by mis-consulting day_3=poor."
    )
    assert 1 in calls and 2 not in calls, (
        f"Re-check must query n=target_offset+1==1 at offset==0. "
        f"Actual classify_solar_day_n calls: {calls}"
    )


# ---------------------------------------------------------------------------
# Byte-identical on the pre-midnight (offset==1) path.
# ---------------------------------------------------------------------------


def test_gate_is_open_offset1_byte_identical_evening():
    """At offset==1, target_offset+1==2 -> same value the pre-fix used.

    Setup: today=excellent, tomorrow=moderate, day_3=poor. Evening now;
    next transition is TOMORROW peak -> offset==1. Gate should open
    because day_3=poor (n=2) matches the multi-day broadening.
    """
    now = datetime(2026, 6, 11, 22, 30, 0)
    strat, _ = _make_battery(
        today_kwh=120, tomorrow_kwh=60, day3_kwh=20,
        tou_next_dt=datetime(2026, 6, 12, 14, 0, 0),
    )
    _, offset = strat._resolve_target_day(now)
    assert offset == 1
    calls = _spy_classify_calls(strat)
    opened = strat._gate_is_open(now, "moderate")
    assert opened is True
    assert 2 in calls and 1 not in calls, (
        f"At offset==1, gate should query n=2 (target_offset+1). "
        f"Calls: {calls}"
    )


# ---------------------------------------------------------------------------
# Site 3 anchor: get_status d2_class display attr at energy_battery.py:6119.
# get_status resolves its OWN `dt_util.now()` (energy_battery.py:6096), so
# we patch the module-level `now` on the mocked homeassistant.util.dt to
# pin the offset-0 datetime rather than passing it in.
# ---------------------------------------------------------------------------


def test_get_status_d2_class_offset0_tracks_tomorrow_not_day3():
    """INV: get_status()['d2_class'] at offset==0 reflects tomorrow (n=1),
    not day_3 (n=2). Fixture mirrors the offset-0 gate test's discriminator:
    today=moderate, tomorrow=excellent, day_3=poor.

    Mutation drill: reverting `classify_solar_day_n(_target_day_offset + 1)`
    at energy_battery.py:~6119 back to `classify_solar_day_n(2)` turns this
    test RED (d2_class becomes "poor").
    """
    import homeassistant.util.dt as _dt_mod

    pinned = datetime(2026, 6, 11, 2, 0, 0)
    strat, _ = _make_battery(
        today_kwh=60, tomorrow_kwh=110, day3_kwh=20,
        tou_next_dt=datetime(2026, 6, 11, 14, 0, 0),
    )

    # Sanity — resolver returns offset==0 at this pinned wall-clock.
    _, offset = strat._resolve_target_day(pinned)
    assert offset == 0

    orig_now = getattr(_dt_mod, "now", None)
    _dt_mod.now = lambda: pinned  # type: ignore[assignment]
    try:
        status = strat.get_status()
    finally:
        _dt_mod.now = orig_now  # type: ignore[assignment]

    assert status["forecast_outlook"]["d2_class"] == "excellent", (
        f"get_status d2_class must reflect tomorrow (n=target_offset+1==1) "
        f"at offset==0, not day_3 (n=2). Got: {status['forecast_outlook']['d2_class']}"
    )
