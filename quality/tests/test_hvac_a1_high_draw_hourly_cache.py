"""HVAC-A1-HIGHDRAW-PER-TICK-SCAN-1 — behavioural tests.

Tier 1. The A1 "high draw time 7d" diagnostic (display-only, consumed
only by `sensor.py:18555` as an attribute) was re-scanning ~90k raw
recorder rows per zone every 5-min tick, parsing the states on the
event loop and causing ~2 s stalls. This cycle:

  (1) refreshes the per-zone cache at most once per
      HVAC_A1_HIGH_DRAW_REFRESH_S (1 h) across many ticks;
  (2) runs the recorder read AND all per-state parsing/summation in
      the recorder executor via `async_add_executor_job`, so the
      event loop never walks the states list;
  (3) serves the cached value between refreshes;
  (4) survives restart (empty cache → one compute on the first tick).

Each gate has its own per-site neuter drill: see
`test_drill_hourly_gate_neutered_breaks_the_cache_test` /
`test_drill_executor_offload_neutered_breaks_the_executor_test` for the
mutation-anchored discipline from the Tier-1 build rules.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


def _mock_module(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": MagicMock, "Event": MagicMock,
        "CALLBACK_TYPE": object, "callback": lambda f: f,
    },
    "homeassistant.helpers": {},
    "homeassistant.helpers.event": {
        "async_call_later": MagicMock(return_value=lambda: None),
        "async_track_state_change_event": MagicMock(return_value=lambda: None),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_send": MagicMock(),
    },
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.now(timezone.utc),
        "now": lambda: datetime.now(),
        "as_local": lambda dt: dt,
        "UTC": timezone.utc,
    },
    "homeassistant.components": {},
    "homeassistant.components.recorder": {"get_instance": MagicMock()},
    "homeassistant.components.recorder.history": {
        "get_significant_states": MagicMock(),
    },
}
for _n, _a in _mods.items():
    sys.modules.setdefault(_n, _mock_module(_n, **_a))

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_HERE, "..", ".."))
_URA_PATH = os.path.join(_HERE, "..", "..", "custom_components",
                         "universal_room_automation")
_DC_PATH = os.path.join(_URA_PATH, "domain_coordinators")

if "custom_components" not in sys.modules:
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [os.path.join(_HERE, "..", "..", "custom_components")]
    sys.modules["custom_components"] = _cc
if "custom_components.universal_room_automation" not in sys.modules:
    _ura = types.ModuleType("custom_components.universal_room_automation")
    _ura.__path__ = [_URA_PATH]
    sys.modules["custom_components.universal_room_automation"] = _ura


def _load(modname, relpath):
    cached = sys.modules.get(modname)
    if cached is not None and getattr(cached, "__file__", None):
        return cached
    spec = importlib.util.spec_from_file_location(
        modname, os.path.join(_URA_PATH, relpath),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


_load("custom_components.universal_room_automation.const", "const.py")
if "custom_components.universal_room_automation.domain_coordinators" not in sys.modules:
    _dc = types.ModuleType(
        "custom_components.universal_room_automation.domain_coordinators"
    )
    _dc.__path__ = [_DC_PATH]
    sys.modules[
        "custom_components.universal_room_automation.domain_coordinators"
    ] = _dc

_load("custom_components.universal_room_automation.domain_coordinators.hvac_const",
      "domain_coordinators/hvac_const.py")
_load("custom_components.universal_room_automation.domain_coordinators.hvac_zones",
      "domain_coordinators/hvac_zones.py")
_load("custom_components.universal_room_automation.domain_coordinators.hvac_setpoint",
      "domain_coordinators/hvac_setpoint.py")
hvac_override = _load(
    "custom_components.universal_room_automation.domain_coordinators.hvac_override",
    "domain_coordinators/hvac_override.py",
)
hvac_zones = sys.modules[
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones"
]
hvac_const = sys.modules[
    "custom_components.universal_room_automation.domain_coordinators.hvac_const"
]

OverrideArrester = hvac_override.OverrideArrester
ZoneState = hvac_zones.ZoneState


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

def _mk_zone(zone_id="zone_a"):
    z = ZoneState(zone_id=zone_id, zone_name=f"Zone {zone_id}",
                  climate_entity=f"climate.{zone_id}")
    z.ac_load_sensor = f"sensor.{zone_id}_kw"
    return z


class _FakeRecorderInstance:
    """Captures every executor-offload call and records whether the
    function it was asked to run was `_compute_high_draw_time_s_7d`."""

    def __init__(self, result=None):
        self.result = result
        self.calls: list[tuple] = []

    async def async_add_executor_job(self, fn, *args):
        self.calls.append((fn, args))
        # Call the function synchronously here (so we mirror what the
        # executor would do), but we have ALREADY proved via the
        # recording that it was dispatched off the loop.
        try:
            return fn(*args)
        except Exception:
            raise


def _mk_arrester(now_value, recorder_result):
    """Build an OverrideArrester with a single zone and a stubbed
    recorder that returns ``recorder_result`` from the sync parser."""
    z = _mk_zone()
    zm = MagicMock()
    zm.zones = {z.zone_id: z}
    hass = MagicMock()
    a = OverrideArrester(hass, zm, compromise_minutes=30,
                         ac_reset_timeout=60, enabled=True)
    # Patch the recorder instance accessor used by the method.
    rec = _FakeRecorderInstance()
    hvac_override.recorder_get_instance = MagicMock(return_value=rec)
    # Patch the sync parser to return a deterministic value, so we test
    # the surrounding plumbing (cache + executor dispatch), not the
    # row-walking logic.
    hvac_override._compute_high_draw_time_s_7d = MagicMock(
        return_value=recorder_result,
    )
    hvac_override.dt_util.now = lambda: now_value
    return a, z, rec


# ---------------------------------------------------------------------------
# Behaviour: hourly gate (cache serves between refreshes)
# ---------------------------------------------------------------------------

def test_first_call_computes_via_executor_and_populates_cache():
    now = datetime(2026, 10, 13, 12, 0, 0)
    a, z, rec = _mk_arrester(now, recorder_result=1234.0)
    val = asyncio.get_event_loop().run_until_complete(
        a._high_draw_time_s_7d(z, now),
    )
    assert val == 1234.0
    # Dispatched exactly once to the executor.
    assert len(rec.calls) == 1
    fn, _ = rec.calls[0]
    assert fn is hvac_override._compute_high_draw_time_s_7d
    # Cache populated with (value, computed_at).
    cached = a._a1_high_draw_cache[z.zone_id]
    assert cached == (1234.0, now)


def test_second_call_within_the_hour_serves_from_cache_no_executor():
    now = datetime(2026, 10, 13, 12, 0, 0)
    a, z, rec = _mk_arrester(now, recorder_result=1234.0)
    loop = asyncio.get_event_loop()
    # First call seeds the cache.
    loop.run_until_complete(a._high_draw_time_s_7d(z, now))
    assert len(rec.calls) == 1
    # Simulate several more 5-min ticks within the hour.
    later = now + timedelta(minutes=5)
    for _ in range(11):  # 11 * 5min = 55 min — still inside the TTL
        val = loop.run_until_complete(a._high_draw_time_s_7d(z, later))
        assert val == 1234.0
        later += timedelta(minutes=5)
    # Still exactly ONE executor dispatch across all those ticks.
    assert len(rec.calls) == 1


def test_call_after_ttl_recomputes_once():
    now = datetime(2026, 10, 13, 12, 0, 0)
    a, z, rec = _mk_arrester(now, recorder_result=1000.0)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(a._high_draw_time_s_7d(z, now))
    assert len(rec.calls) == 1
    # Jump past the TTL (1 h + 5 min).
    hvac_override._compute_high_draw_time_s_7d = MagicMock(
        return_value=2222.0,
    )
    much_later = now + timedelta(seconds=hvac_const.HVAC_A1_HIGH_DRAW_REFRESH_S + 300)
    val = loop.run_until_complete(a._high_draw_time_s_7d(z, much_later))
    assert val == 2222.0
    # Second compute happened — total 2 executor dispatches now.
    assert len(rec.calls) == 2


def test_restart_path_empty_cache_computes_on_first_call():
    """After construction the per-zone cache is empty; first call MUST
    recompute (no stale value survives across process restart)."""
    now = datetime(2026, 10, 13, 12, 0, 0)
    a, z, rec = _mk_arrester(now, recorder_result=777.0)
    assert z.zone_id not in a._a1_high_draw_cache
    val = asyncio.get_event_loop().run_until_complete(
        a._high_draw_time_s_7d(z, now),
    )
    assert val == 777.0
    assert z.zone_id in a._a1_high_draw_cache
    assert len(rec.calls) == 1


def test_executor_offload_runs_the_canonical_sync_parser():
    """Wire-in anchor: the method MUST dispatch via async_add_executor_job
    AND the dispatched callable MUST be the module-level
    `_compute_high_draw_time_s_7d`. A builder who inlined the parse back
    onto the loop would send `None` or a lambda — this test catches it."""
    now = datetime(2026, 10, 13, 12, 0, 0)
    a, z, rec = _mk_arrester(now, recorder_result=42.0)
    asyncio.get_event_loop().run_until_complete(
        a._high_draw_time_s_7d(z, now),
    )
    assert len(rec.calls) == 1
    fn, args = rec.calls[0]
    assert fn is hvac_override._compute_high_draw_time_s_7d
    # args: (hass, entity_id, start_dt, now)
    assert len(args) == 4
    assert args[1] == z.ac_load_sensor
    assert args[3] == now


def test_const_rung_1_is_one_hour():
    """Rung-1 module constant: the value stays 3600 unless a reviewed
    code change moves it. A dashboard-tunable slider would be the wrong
    rung for this diagnostic cost bound."""
    assert hvac_const.HVAC_A1_HIGH_DRAW_REFRESH_S == 3600
