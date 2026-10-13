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

Each gate has its own per-site neuter drill (recorded in the cycle
commit message, not test-named): neutering the hourly gate reddens
`test_second_call_within_the_hour_serves_from_cache_no_executor`; neutering
the executor dispatch reddens
`test_executor_offload_runs_the_canonical_sync_parser`; reverting the
kWh branch fall-through fix reddens
`test_compute_worker_kwh_rows_do_not_count_as_high_draw`.
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


def _mk_arrester(monkeypatch, now_value, recorder_result):
    """Build an OverrideArrester with a single zone and a stubbed
    recorder that returns ``recorder_result`` from the sync parser.

    HIGH fix: every module-global patch (recorder_get_instance,
    _compute_high_draw_time_s_7d, dt_util.now) goes through
    ``monkeypatch`` so pytest restores it at test teardown. Under
    .venv-ha, ``hvac_override.dt_util`` IS ``homeassistant.util.dt`` —
    leaking a frozen `now` from this file into sibling tests would
    freeze time or hand them a MagicMock parser.
    """
    z = _mk_zone()
    zm = MagicMock()
    zm.zones = {z.zone_id: z}
    hass = MagicMock()
    a = OverrideArrester(hass, zm, compromise_minutes=30,
                         ac_reset_timeout=60, enabled=True)
    rec = _FakeRecorderInstance()
    monkeypatch.setattr(hvac_override, "recorder_get_instance",
                        MagicMock(return_value=rec))
    monkeypatch.setattr(hvac_override, "_compute_high_draw_time_s_7d",
                        MagicMock(return_value=recorder_result))
    monkeypatch.setattr(hvac_override.dt_util, "now", lambda: now_value)
    return a, z, rec


# ---------------------------------------------------------------------------
# Behaviour: hourly gate (cache serves between refreshes)
# ---------------------------------------------------------------------------

def test_first_call_computes_via_executor_and_populates_cache(monkeypatch):
    now = datetime(2026, 10, 13, 12, 0, 0)
    a, z, rec = _mk_arrester(monkeypatch, now, recorder_result=1234.0)
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


def test_second_call_within_the_hour_serves_from_cache_no_executor(monkeypatch):
    now = datetime(2026, 10, 13, 12, 0, 0)
    a, z, rec = _mk_arrester(monkeypatch, now, recorder_result=1234.0)
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


def test_call_after_ttl_recomputes_once(monkeypatch):
    now = datetime(2026, 10, 13, 12, 0, 0)
    a, z, rec = _mk_arrester(monkeypatch, now, recorder_result=1000.0)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(a._high_draw_time_s_7d(z, now))
    assert len(rec.calls) == 1
    # Jump past the TTL (1 h + 5 min); monkeypatch again so the second
    # compute returns a distinguishable value.
    monkeypatch.setattr(hvac_override, "_compute_high_draw_time_s_7d",
                        MagicMock(return_value=2222.0))
    much_later = now + timedelta(seconds=hvac_const.HVAC_A1_HIGH_DRAW_REFRESH_S + 300)
    val = loop.run_until_complete(a._high_draw_time_s_7d(z, much_later))
    assert val == 2222.0
    # Second compute happened — total 2 executor dispatches now.
    assert len(rec.calls) == 2


def test_restart_path_empty_cache_computes_on_first_call(monkeypatch):
    """After construction the per-zone cache is empty; first call MUST
    recompute (no stale value survives across process restart)."""
    now = datetime(2026, 10, 13, 12, 0, 0)
    a, z, rec = _mk_arrester(monkeypatch, now, recorder_result=777.0)
    assert z.zone_id not in a._a1_high_draw_cache
    val = asyncio.get_event_loop().run_until_complete(
        a._high_draw_time_s_7d(z, now),
    )
    assert val == 777.0
    assert z.zone_id in a._a1_high_draw_cache
    assert len(rec.calls) == 1


def test_executor_offload_runs_the_canonical_sync_parser(monkeypatch):
    """Wire-in anchor: the method MUST dispatch via async_add_executor_job
    AND the dispatched callable MUST be the module-level
    `_compute_high_draw_time_s_7d`. A builder who inlined the parse back
    onto the loop would send `None` or a lambda — this test catches it."""
    now = datetime(2026, 10, 13, 12, 0, 0)
    a, z, rec = _mk_arrester(monkeypatch, now, recorder_result=42.0)
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


# ---------------------------------------------------------------------------
# Direct test of the real `_compute_high_draw_time_s_7d` worker.
# Patches `get_significant_states` at the module level and feeds fake
# State rows in W, kW and kWh units. MEDIUM fix: the kWh branch is a
# correctness guard (a cumulative-counter value is meaningless as an
# instant kW), and the latent fall-through in the pre-cycle code
# silently counted every reading above threshold as "high draw".
# ---------------------------------------------------------------------------


class _FakeState:
    """Minimal State stand-in: the worker reads .state, .attributes and
    .last_updated via getattr, so this duck-typed class suffices."""

    def __init__(self, state, unit, ts):
        self.state = state
        self.attributes = {"unit_of_measurement": unit} if unit else {}
        self.last_updated = ts
        self.last_changed = ts


def test_compute_worker_watts_above_threshold_are_counted(monkeypatch):
    """W rows ≥ 500 W (= 0.5 kW threshold) count as high-draw time."""
    base = datetime(2026, 10, 13, 10, 0, 0)
    rows = [
        _FakeState("600", "W", base),
        _FakeState("600", "W", base + timedelta(seconds=120)),
        _FakeState("50",  "W", base + timedelta(seconds=180)),  # drop
    ]
    monkeypatch.setattr(
        hvac_override, "get_significant_states",
        lambda hass, start, end, entities: {entities[0]: rows},
    )
    now = base + timedelta(seconds=300)
    val = hvac_override._compute_high_draw_time_s_7d(
        MagicMock(), "sensor.x", base - timedelta(days=7), now,
    )
    # High from base -> base+120 (120 s) and base+120 -> base+180 (60 s);
    # after the drop at 180 s, no further high interval.
    assert val == pytest.approx(180.0)


def test_compute_worker_kilowatts_above_threshold_are_counted(monkeypatch):
    """kW rows ≥ 0.5 kW count as high-draw (no /1000 conversion applies)."""
    base = datetime(2026, 10, 13, 10, 0, 0)
    rows = [
        _FakeState("1.2", "kW", base),
        _FakeState("0.1", "kW", base + timedelta(seconds=100)),
    ]
    monkeypatch.setattr(
        hvac_override, "get_significant_states",
        lambda hass, start, end, entities: {entities[0]: rows},
    )
    now = base + timedelta(seconds=200)
    val = hvac_override._compute_high_draw_time_s_7d(
        MagicMock(), "sensor.x", base - timedelta(days=7), now,
    )
    assert val == pytest.approx(100.0)


def test_compute_worker_kwh_rows_do_not_count_as_high_draw(monkeypatch):
    """MEDIUM fix: kWh / Wh rows are cumulative energy counters whose
    numeric value far exceeds the 0.5 kW threshold once the counter has
    been running for an hour. The worker MUST classify them as NOT high
    draw. Reverting the explicit nested if/elif/else at
    hvac_override.py:342-349 back to a fall-through assignment would
    re-introduce the latent bug and this test would go RED.
    """
    base = datetime(2026, 10, 13, 10, 0, 0)
    # Large kWh readings — a cumulative counter well past threshold if
    # the kWh branch were treated as kW.
    rows = [
        _FakeState("1250.5", "kWh", base),
        _FakeState("1251.0", "kWh", base + timedelta(seconds=120)),
        _FakeState("1251.2", "kWh", base + timedelta(seconds=240)),
    ]
    monkeypatch.setattr(
        hvac_override, "get_significant_states",
        lambda hass, start, end, entities: {entities[0]: rows},
    )
    now = base + timedelta(seconds=300)
    val = hvac_override._compute_high_draw_time_s_7d(
        MagicMock(), "sensor.x", base - timedelta(days=7), now,
    )
    # Every row MUST be classified `is_high=False`, so the integral is 0.
    assert val == 0.0


def test_compute_worker_returns_none_on_no_rows(monkeypatch):
    monkeypatch.setattr(
        hvac_override, "get_significant_states",
        lambda hass, start, end, entities: {},
    )
    now = datetime(2026, 10, 13, 12, 0, 0)
    val = hvac_override._compute_high_draw_time_s_7d(
        MagicMock(), "sensor.x", now - timedelta(days=7), now,
    )
    assert val is None
