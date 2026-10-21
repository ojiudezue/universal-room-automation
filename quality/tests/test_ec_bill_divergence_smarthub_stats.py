"""EC-BILL-UTILITY-DIVERGENCE-FROM-STATS-1 (Step 2) — behavioural tests.

Plan: docs/planning/PLANNING_ec_bill_divergence_from_smarthub_stats.md
(Rev 2 binding section supersedes the D1/D2/D3/INV-1 text).

Bug classes guarded: #53 computed-but-not-consumed (wire-in anchors on the
decision-cycle scheduling call and the teardown cancel), event-loop blocking
/ untracked background task (H1: the decision cycle never awaits the
refresh), coincidental-equality #63 (pricing fixture discriminates base-rate
vs effective-rate; window fixtures discriminate end-exclusive vs inclusive).

Oracles are hand-derived from the PEC 2026 rate table (energy_const
PEC_TOU_RATES / PEC_FIXED_CHARGES) written out as literals here, never by
re-running the code under test.
"""
from __future__ import annotations

import asyncio
import sys
import types
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from _energy_bootstrap import bootstrap_energy_imports  # noqa: E402

bootstrap_energy_imports()

from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy as em,
)
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy_billing as eb,
)
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy_tou as et,
)

TZ = ZoneInfo("America/Chicago")
IMP = "smarthub:smarthub_energy_sensor_1_2"
EXP = "smarthub:smarthub_energy_return_sensor_1_2"

# Hand-written PEC 2026 literals (independent of energy_const).
ADDERS = 0.022546 + 0.019930
OFF = 0.043481
SUMMER_MID = 0.093169
SUMMER_PEAK = 0.161843


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _hour_rows(day: date, kwh: float, last_hour: int | None = None) -> list[dict]:
    """One row per real local hour of ``day`` (23/24/25 on DST days).

    Steps in UTC from local midnight to the next local midnight so DST days
    get their true row count. ``last_hour`` truncates (partial day).
    """
    start = datetime(day.year, day.month, day.day, tzinfo=TZ).astimezone(timezone.utc)
    nxt = day + timedelta(days=1)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=TZ).astimezone(timezone.utc)
    rows = []
    t = start
    while t < end:
        if last_hour is not None and t.astimezone(TZ).hour > last_hour:
            break
        rows.append({"start": t.timestamp(), "end": (t + timedelta(hours=1)).timestamp(),
                     "change": kwh})
        t += timedelta(hours=1)
    return rows


def _days_rows(first: date, last_incl: date, kwh: float) -> list[dict]:
    rows = []
    d = first
    while d <= last_incl:
        rows += _hour_rows(d, kwh)
        d += timedelta(days=1)
    return rows


# =============================================================================
# D1 pure helper — pricing
# =============================================================================


def test_price_hourly_utility_rows_effective_rate():
    day = date(2026, 7, 15)  # summer
    rows_imp = _hour_rows(day, 1.0)
    rows_exp = _hour_rows(day, 0.5)
    priced = eb.price_hourly_utility_rows(rows_imp, rows_exp, et.TOURateEngine(), TZ)
    rec = priced[day]
    expected_imp = (
        17 * (0.043481 + 0.042476)
        + 3 * (0.093169 + 0.042476)
        + 4 * (0.161843 + 0.042476)
    )
    assert rec["imp_cost"] == pytest.approx(expected_imp, abs=1e-6)
    # Base-rate-only bug would be lower by 24 x 0.042476 = 1.019424.
    assert rec["imp_cost"] - (expected_imp - 24 * 0.042476) == pytest.approx(1.019424, abs=1e-6)
    assert rec["imp_kwh"] == pytest.approx(24.0)
    # Export priced at the export rate (no adders).
    assert rec["exp_credit"] == pytest.approx(
        0.5 * (17 * 0.043481 + 3 * 0.093169 + 4 * 0.161843), abs=1e-6,
    )
    assert rec["hours"] == 24
    assert rec["complete"] is True


def test_price_hourly_utility_rows_dst_days():
    fall = date(2026, 11, 1)    # US fall-back: 25 local hours
    spring = date(2026, 3, 8)   # US spring-forward: 23 local hours
    rows = _hour_rows(fall, 1.0) + _hour_rows(spring, 1.0)
    priced = eb.price_hourly_utility_rows(rows, [], et.TOURateEngine(), TZ)
    assert priced[fall]["hours"] == 25
    assert priced[fall]["imp_kwh"] == pytest.approx(25.0)
    assert priced[fall]["complete"] is True
    assert priced[spring]["hours"] == 23
    assert priced[spring]["imp_kwh"] == pytest.approx(23.0)
    assert priced[spring]["complete"] is True
    assert eb.utility_window_end(priced) == date(2026, 11, 2)


def test_utility_partial_day_excluded():
    rows = _hour_rows(date(2026, 10, 17), 1.0) + _hour_rows(date(2026, 10, 18), 1.0, last_hour=15)
    priced = eb.price_hourly_utility_rows(rows, [], et.TOURateEngine(), TZ)
    assert priced[date(2026, 10, 18)]["complete"] is False
    # Newest COMPLETE day is the 17th, so the window ends (exclusive) on the 18th.
    assert eb.utility_window_end(priced) == date(2026, 10, 18)
    tot = eb.sum_utility_window(priced, date(2026, 10, 1), date(2026, 10, 18))
    assert tot["days"] == 1
    assert tot["import_kwh"] == pytest.approx(24.0)


# =============================================================================
# Coordinator harness (real EnergyCoordinator methods on a plain stub)
# =============================================================================


class _FakeDB:
    """energy_daily as {date: (import_kwh, import_cost, export_kwh, net_cost)}."""

    def __init__(self, rows: dict):
        self.rows = rows
        self.calls: list[tuple[str, str]] = []

    async def get_energy_daily_for_cycle(self, start: str, end: str) -> dict:
        self.calls.append((start, end))
        s, e = date.fromisoformat(start), date.fromisoformat(end)
        out = {"days": 0, "import_kwh": 0.0, "export_kwh": 0.0,
               "import_cost": 0.0, "export_credit": 0.0, "net_cost": 0.0}
        for d, (ik, ic, ek, nc) in self.rows.items():
            if s <= d < e:
                out["days"] += 1
                out["import_kwh"] += ik
                out["import_cost"] += ic
                out["export_kwh"] += ek
                out["net_cost"] += nc
        return out


class _Hass:
    def __init__(self, db=None, recorder=True):
        self.data = {"universal_room_automation": {"database": db}}
        self.config = types.SimpleNamespace(
            components={"recorder"} if recorder else set(),
        )
        self.states = MagicMock()
        self.tasks: list[asyncio.Task] = []

    def async_create_background_task(self, coro, name, eager_start=True):
        task = asyncio.get_event_loop().create_task(coro)
        self.tasks.append(task)
        return task


class _Stub:
    pass


def _bind(stub, name):
    setattr(stub, name, getattr(em.EnergyCoordinator, name).__get__(stub))


def _make(imp=IMP, exp=EXP, db=None, cycle_day=23, query=None, recorder=True):
    s = _Stub()
    s.hass = _Hass(db, recorder=recorder)
    s._tou = et.TOURateEngine()
    billing = types.SimpleNamespace(_bill_cycle_day=cycle_day)
    billing._get_cycle_start = eb.CostTracker._get_cycle_start.__get__(billing)
    s._billing = billing
    s._utility_import_stat_id = imp
    s._utility_export_stat_id = exp
    s._utility_meter_entity = None
    s._utility_stats_last_run = None
    s._utility_stats_inflight = False
    s._utility_stats_task = None
    s._utility_stats_cache = None
    s._utility_stats_error = None
    s._utility_stats_refreshed_at = None
    s._enabled = True
    s._cycle_in_flight = False
    s._tou_boundary_unsub = object()  # suppress re-arm in finally
    # EC-SHUTDOWN-SAVE-AFTER-WRITER-CLOSED-1: teardown reads these.
    s._stop_save_unsub = None
    s._stop_persist_done = False

    async def _noop_body():
        return None

    s._decision_cycle_body = _noop_body
    for n in ("_maybe_schedule_utility_refresh", "_cancel_utility_refresh",
              "_async_refresh_utility_stats", "_compute_utility_comparison",
              "_utility_statistics_divergence", "_async_decision_cycle",
              "_utility_stat_ids", "_current_utility_cache",
              "_push_bill_forecast_inputs", "_bill_forecast_after_refresh",
              "_async_persist_state", "_cancel_actuation_timers",
              "_cancel_dp_must_start_by_timer"):
        _bind(s, n)
    calls: list[tuple] = []

    async def _default_query(start_utc, ids):
        calls.append((start_utc, set(ids)))
        return {}

    s._query_utility_statistics = query or _default_query
    s.query_calls = calls
    return s


@pytest.fixture
def aware_now(monkeypatch):
    """dt_util.now() -> a fixed tz-aware local datetime (restored after)."""
    from homeassistant.util import dt as dt_util
    fixed = datetime(2026, 10, 19, 9, 0, tzinfo=TZ)
    monkeypatch.setattr(dt_util, "now", lambda *a, **k: fixed)
    return fixed


# =============================================================================
# D1 — kill switch, single-flight, interval, wire-in, non-blocking, unload
# =============================================================================


def test_utility_stats_disabled_when_ids_blank(aware_now):
    s = _make(imp="", exp="")

    async def _go():
        for _ in range(3):
            await s._async_decision_cycle()
        await asyncio.sleep(0)

    _run(_go())
    assert s.query_calls == []
    assert s.hass.tasks == []
    assert s._utility_stats_last_run is None


def test_utility_stats_single_flight_and_interval():
    t0 = datetime(2026, 10, 19, 9, 0, tzinfo=TZ)
    s = _make()

    async def _go():
        s._maybe_schedule_utility_refresh(t0)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        s._maybe_schedule_utility_refresh(t0 + timedelta(minutes=59))
        await asyncio.sleep(0)
        n_59 = len(s.query_calls)
        s._maybe_schedule_utility_refresh(t0 + timedelta(minutes=60))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        n_60 = len(s.query_calls)
        return n_59, n_60

    n_59, n_60 = _run(_go())
    assert n_59 == 1, "59 min after the last run must not re-query"
    assert n_60 == 2, "60 min after the last run must re-query"

    # Two overlapping invocations (refresh still in flight) -> one query.
    gate = None
    calls = []

    async def _blocked(start_utc, ids):
        calls.append(ids)
        await gate.wait()
        return {}

    s2 = _make(query=_blocked)

    async def _go2():
        nonlocal gate
        gate = asyncio.Event()
        s2._maybe_schedule_utility_refresh(t0)
        await asyncio.sleep(0)
        # Interval elapsed but in flight -> skipped.
        s2._maybe_schedule_utility_refresh(t0 + timedelta(hours=3))
        await asyncio.sleep(0)
        n = len(calls)
        gate.set()
        await asyncio.gather(*s2.hass.tasks)
        return n

    assert _run(_go2()) == 1
    assert s2._utility_stats_inflight is False


def test_decision_cycle_calls_utility_refresh(aware_now):
    """Wire-in anchor: deleting the scheduling call in _async_decision_cycle
    leaves zero queries -> RED."""
    s = _make()

    async def _go():
        await s._async_decision_cycle()
        await asyncio.gather(*s.hass.tasks)

    _run(_go())
    assert len(s.query_calls) == 1
    assert s.query_calls[0][1] == {IMP, EXP}


def test_decision_cycle_not_blocked_by_utility_refresh(aware_now):
    """H1: the refresh is held on an un-set Event; two decision cycles still
    complete and no second refresh starts. A direct ``await`` of the refresh
    in the decision cycle hangs cycle 1 -> wait_for times out -> RED."""
    calls = []
    gate_box = {}

    async def _blocked(start_utc, ids):
        calls.append(ids)
        await gate_box["gate"].wait()
        return {}

    s = _make(query=_blocked)

    async def _go():
        gate_box["gate"] = asyncio.Event()
        await asyncio.wait_for(s._async_decision_cycle(), timeout=1.0)
        await asyncio.sleep(0)
        assert len(calls) == 1
        await asyncio.wait_for(s._async_decision_cycle(), timeout=1.0)
        await asyncio.sleep(0)
        n_calls = len(calls)
        still_blocked = s._utility_stats_inflight
        gate_box["gate"].set()
        await asyncio.gather(*s.hass.tasks)
        return n_calls, still_blocked

    n_calls, still_blocked = _run(_go())
    assert n_calls == 1
    assert still_blocked is True
    assert s._utility_stats_inflight is False


def test_utility_refresh_task_cancelled_on_unload(aware_now):
    """L3: EnergyCoordinator.async_teardown cancels the in-flight refresh."""
    gate_box = {}

    async def _blocked(start_utc, ids):
        await gate_box["gate"].wait()
        return {}

    s = _make(query=_blocked)
    # async_teardown touches many collaborators; give it harmless ones.
    s._decision_timer_unsub = None
    s._outage_ledger = None
    s._solar_follow_timer_unsub = None
    s._solar_follow = None
    s._tou_boundary_unsub = None
    s._peak_import_history = []
    for n in ("_save_evse_state", "_save_circuit_state", "_save_energy_baselines",
              "_save_envoy_cache", "_save_midnight_snapshot",
              "_save_load_shedding_level", "_save_peak_import_history",
              "_save_power_profiles"):
        setattr(s, n, AsyncMock())
    s._write_verifier = None
    s._dp_eval_last_task = None
    s._cancel_listeners = lambda: None
    s._optimizer_intent_unsub = None

    async def _go():
        gate_box["gate"] = asyncio.Event()
        s._maybe_schedule_utility_refresh()
        await asyncio.sleep(0)
        task = s.hass.tasks[0]
        assert not task.done()
        await em.EnergyCoordinator.async_teardown(s)
        await asyncio.sleep(0)
        return task

    task = _run(_go())
    assert task.cancelled()
    assert s._utility_stats_task is None


def test_utility_stats_recorder_exception_keeps_cache():
    t0 = datetime(2026, 10, 19, 9, 0, tzinfo=TZ)

    async def _boom(start_utc, ids):
        raise RuntimeError("recorder busy")

    s = _make(query=_boom)
    sentinel = {"current": {"utility_import_kwh": 1.0}, "last_cycle": None}
    s._utility_stats_cache = sentinel

    async def _go():
        s._maybe_schedule_utility_refresh(t0)
        await asyncio.gather(*s.hass.tasks)

    _run(_go())
    assert s._utility_stats_cache is sentinel
    assert s._utility_stats_error == "RuntimeError: recorder busy"
    assert s._utility_stats_inflight is False
    assert s._utility_stats_last_run == t0  # stamped before the await


def test_utility_stats_skipped_when_recorder_not_loaded():
    t0 = datetime(2026, 10, 19, 9, 0, tzinfo=TZ)
    s = _make(recorder=False)

    async def _go():
        s._maybe_schedule_utility_refresh(t0)
        await asyncio.gather(*s.hass.tasks)

    _run(_go())
    assert s.query_calls == []
    assert s._utility_stats_inflight is False


def test_utility_query_runs_on_recorder_executor(monkeypatch):
    """The recorder call goes through get_instance(hass).async_add_executor_job
    with statistics_during_period, period "hour", types {"change"}."""
    seen = {}

    def _sdp(*args):
        return {"x": []}

    class _Inst:
        async def async_add_executor_job(self, fn, *args):
            seen["fn"] = fn
            seen["args"] = args
            return fn(*args)

    rec = types.ModuleType("homeassistant.components.recorder")
    rec.get_instance = lambda hass: _Inst()
    stats = types.ModuleType("homeassistant.components.recorder.statistics")
    stats.statistics_during_period = _sdp
    monkeypatch.setitem(sys.modules, "homeassistant.components.recorder", rec)
    monkeypatch.setitem(sys.modules, "homeassistant.components.recorder.statistics", stats)
    s = _make()
    _bind(s, "_query_utility_statistics")
    start = datetime(2026, 9, 23, 5, tzinfo=timezone.utc)
    out = _run(s._query_utility_statistics(start, {IMP, EXP}))
    assert out == {"x": []}
    assert seen["fn"] is _sdp
    hass, st, end, ids, period, units, types_ = seen["args"]
    assert hass is s.hass and st == start and end is None
    assert ids == {IMP, EXP} and period == "hour" and units is None
    assert types_ == {"change"}


def test_previous_cycle_start_reuses_cycle_helper():
    """M1: query start = local midnight of the PREVIOUS cycle start, across a
    year boundary (now 2026-01-05, day 23 -> cycle 2025-12-23, prev 2025-11-23)."""
    now = datetime(2026, 1, 5, 9, 0, tzinfo=TZ)
    s = _make()

    async def _go():
        s._maybe_schedule_utility_refresh(now)
        await asyncio.gather(*s.hass.tasks)

    _run(_go())
    start_utc = s.query_calls[0][0]
    # 2025-11-23 00:00 CST (UTC-6) = 06:00 UTC.
    assert start_utc == datetime(2025, 11, 23, 6, 0, tzinfo=timezone.utc)


# =============================================================================
# D2 — same-window comparison (INV-1) + M2 underpriced days
# =============================================================================


def _refresh_with(s, now, rows_imp, rows_exp=None):
    async def _q(start_utc, ids):
        out = {IMP: rows_imp}
        if rows_exp is not None:
            out[EXP] = rows_exp
        return out

    s._query_utility_statistics = _q

    async def _go():
        s._maybe_schedule_utility_refresh(now)
        await asyncio.gather(*s.hass.tasks)

    _run(_go())
    assert s._utility_stats_error is None, s._utility_stats_error


def test_utility_window_empty_publishes_no_divergence():
    # Cycle day 23; today 10-24; utility complete only through 10-22.
    now = datetime(2026, 10, 24, 10, 0, tzinfo=TZ)
    db = _FakeDB({date(2026, 10, 23): (40.0, 4.0, 0.0, 4.0)})
    s = _make(db=db)
    _refresh_with(s, now, _days_rows(date(2026, 9, 23), date(2026, 10, 22), 1.0))
    div = em.EnergyCoordinator.utility_meter_divergence.fget(s)
    assert div["utility_source"] == "statistics"
    for k in ("divergence_pct", "divergence_cost_pct", "utility_kwh", "envoy_kwh"):
        assert div[k] is None, (k, div[k])
        assert div[k] not in (0, 0.0, 100, 100.0)
    # The completed previous cycle IS published (window_end == cycle_start).
    assert div["last_cycle"]["window_start"] == "2026-09-23"
    assert div["last_cycle"]["window_end"] == "2026-10-23"
    assert div["last_cycle"]["utility_days"] == 30
    assert div["last_cycle"]["utility_import_kwh"] == pytest.approx(720.0)


def test_utility_window_matches_ec_dates():
    # today 10-19, cycle 09-23..; utility complete through 10-17 (10-18 partial).
    now = datetime(2026, 10, 19, 9, 0, tzinfo=TZ)
    rows = (_days_rows(date(2026, 8, 23), date(2026, 10, 17), 1.0)
            + _hour_rows(date(2026, 10, 18), 1.0, last_hour=3))
    ec_rows = {}
    d = date(2026, 9, 23)
    while d <= date(2026, 10, 18):  # EC also has 10-18 (outside the window)
        ec_rows[d] = (20.0, 2.0, 0.0, 2.0)
        d += timedelta(days=1)
    del ec_rows[date(2026, 10, 1)]  # one missing energy_daily row
    db = _FakeDB(ec_rows)
    s = _make(db=db, exp="")
    _refresh_with(s, now, rows)
    cur = s._utility_stats_cache["current"]
    assert (cur["window_start"], cur["window_end"]) == ("2026-09-23", "2026-10-18")
    # The EC window query used EXACTLY the same [start, end).
    assert ("2026-09-23", "2026-10-18") in db.calls
    assert cur["utility_days"] == 25
    assert cur["ec_days"] == 24  # published anyway, ec_days reported
    assert cur["utility_import_kwh"] == pytest.approx(600.0)
    assert cur["ec_import_kwh"] == pytest.approx(480.0)  # 10-18 NOT included
    assert cur["divergence_kwh"] == pytest.approx(120.0)
    assert cur["divergence_kwh_pct"] == pytest.approx(20.0)
    assert "utility_export_kwh" not in cur  # export id blank
    div = em.EnergyCoordinator.utility_meter_divergence.fget(s)
    assert div["utility_kwh"] == pytest.approx(600.0)
    assert div["envoy_kwh"] == pytest.approx(480.0)
    assert div["divergence_pct"] == pytest.approx(20.0)
    assert div["window"] == "2026-09-23..2026-10-18"


def test_last_cycle_absent_until_complete():
    # Utility complete only through 10-21 -> previous cycle not covered.
    now = datetime(2026, 10, 24, 10, 0, tzinfo=TZ)
    s = _make(db=_FakeDB({}))
    _refresh_with(s, now, _days_rows(date(2026, 9, 23), date(2026, 10, 21), 1.0))
    assert s._utility_stats_cache["last_cycle"] is None
    assert s._utility_stats_cache["current"] is None


def test_last_cycle_bill_estimate_and_export():
    # Previous cycle 08-23..09-23 (summer+Sept): import 1 kWh/h, export 0.5.
    now = datetime(2026, 9, 25, 10, 0, tzinfo=TZ)
    rows_i = _days_rows(date(2026, 8, 23), date(2026, 9, 24), 1.0)
    rows_e = _days_rows(date(2026, 8, 23), date(2026, 9, 24), 0.5)
    s = _make(db=_FakeDB({}))
    _refresh_with(s, now, rows_i, rows_e)
    last = s._utility_stats_cache["last_cycle"]
    per_day_imp = (17 * (0.043481 + 0.042476) + 3 * (0.093169 + 0.042476)
                   + 4 * (0.161843 + 0.042476))
    per_day_exp = 0.5 * (17 * 0.043481 + 3 * 0.093169 + 4 * 0.161843)
    net = 31 * (per_day_imp - per_day_exp)  # 31 summer days 08-23..09-22
    assert last["utility_days"] == 31
    assert last["utility_net_cost"] == pytest.approx(round(net, 2), abs=0.011)
    assert last["utility_bill_estimate"] == pytest.approx(round(net + 32.50, 2), abs=0.011)
    assert last["utility_export_kwh"] == pytest.approx(31 * 12.0)


def test_ec_underpriced_days_counts():
    # October = shoulder; floor = 0.043481 + 0.042476 = 0.085957 $/kWh.
    now = datetime(2026, 10, 19, 9, 0, tzinfo=TZ)
    ec_rows = {
        date(2026, 9, 23): (100.0, 6.58, 0.0, 6.58),      # 0.0658 -> under (Sept: summer floor same)
        date(2026, 9, 24): (100.0, 8.5957, 0.0, 8.5957),  # exactly floor -> not
        date(2026, 9, 25): (100.0, 9.0, 0.0, 9.0),        # above -> not
        date(2026, 10, 2): (50.0, 4.0, 0.0, 4.0),         # 0.080 -> under
        date(2026, 10, 3): (0.0, 0.0, 0.0, 0.0),          # no import -> not
        date(2026, 10, 5): (50.0, 3.5, 0.0, 3.5),         # 0.070 -> under
    }
    # Review C (2026-10-19): 3 under vs 2 at/above, so a flipped comparison
    # (which would count the at-floor + above days = 2) cannot pass.
    s = _make(db=_FakeDB(ec_rows))
    _refresh_with(s, now, _days_rows(date(2026, 8, 23), date(2026, 10, 17), 1.0))
    assert s._utility_stats_cache["current"]["ec_underpriced_days"] == 3
    div = em.EnergyCoordinator.utility_meter_divergence.fget(s)
    assert div["current"]["ec_underpriced_days"] == 3


def test_tou_import_rate_floor_from_engine():
    assert eb.tou_import_rate_floor(et.TOURateEngine(), date(2026, 10, 5), TZ) == pytest.approx(
        0.085957, abs=1e-9,
    )


# =============================================================================
# D3 — precedence
# =============================================================================


def test_predicted_bill_attrs_statistics_precedence():
    s = _make()
    s._utility_meter_entity = "sensor.smarthub_monthly"
    st = MagicMock()
    st.state = "500"
    st.attributes = {}
    s.hass.states.get = lambda eid: st
    div = em.EnergyCoordinator.utility_meter_divergence.fget(s)
    assert div["utility_source"] == "statistics"
    assert div["utility_kwh"] is None  # no cache yet; NOT the entity's 500
    assert "utility_entity" not in div


# =============================================================================
# Review fix-ups (A-M1, A-M2, B-M1, B-L3)
# =============================================================================


def test_ec_side_without_rows_publishes_no_divergence():
    """A-M1: db None -> EC side has 0 days; the utility side has complete
    days >= cycle_start. Divergence must be None, never +/-100."""
    now = datetime(2026, 10, 19, 9, 0, tzinfo=TZ)
    s = _make(db=None)
    _refresh_with(s, now, _days_rows(date(2026, 8, 23), date(2026, 10, 17), 1.0))
    cur = s._utility_stats_cache["current"]
    assert cur["ec_days"] == 0
    assert cur["utility_import_kwh"] == pytest.approx(600.0)  # utility side kept
    for k in ("divergence_kwh", "divergence_kwh_pct",
              "divergence_cost", "divergence_cost_pct"):
        assert cur[k] is None, (k, cur[k])
    last = s._utility_stats_cache["last_cycle"]
    assert last["divergence_kwh_pct"] is None
    div = em.EnergyCoordinator.utility_meter_divergence.fget(s)
    for k in ("divergence_pct", "divergence_cost", "divergence_cost_pct"):
        assert div[k] is None, (k, div[k])
        assert div[k] not in (100, 100.0, -100, -100.0)
    # Same with a DB that has no energy_daily rows in the window.
    s2 = _make(db=_FakeDB({}))
    _refresh_with(s2, now, _days_rows(date(2026, 8, 23), date(2026, 10, 17), 1.0))
    assert s2._utility_stats_cache["current"]["divergence_kwh_pct"] is None


def test_last_cycle_bill_estimate_uses_rate_file_service_charge():
    """A-M2: the service charge comes from the LOADED rate file (41.25 here),
    not the PEC constant 32.50."""
    now = datetime(2026, 9, 25, 10, 0, tzinfo=TZ)
    rows_i = _days_rows(date(2026, 8, 23), date(2026, 9, 24), 1.0)
    s = _make(db=_FakeDB({}), exp="")
    s._tou = et.TOURateEngine(fixed_charges={
        "service_availability": 41.25,
        "delivery_per_kwh": 0.022546,
        "transmission_per_kwh": 0.019930,
    })
    _refresh_with(s, now, rows_i)
    last = s._utility_stats_cache["last_cycle"]
    per_day_imp = (17 * (0.043481 + 0.042476) + 3 * (0.093169 + 0.042476)
                   + 4 * (0.161843 + 0.042476))
    assert last["utility_bill_estimate"] == pytest.approx(
        round(31 * per_day_imp + 41.25, 2), abs=0.011,
    )
    # Discriminates against the constant: 8.75 apart.
    assert abs(last["utility_bill_estimate"] - (round(31 * per_day_imp, 2) + 32.50)) > 8.0


def test_tou_service_availability_falls_back_to_constant():
    eng = et.TOURateEngine(fixed_charges={"delivery_per_kwh": 0.02,
                                          "transmission_per_kwh": 0.02})
    assert eng.service_availability_monthly == pytest.approx(32.50)


def test_utility_ids_read_live_from_cm_options():
    """B-M1: ids come from the CM options at each refresh; a changed id is
    used by the NEXT refresh with no reload and without waiting the
    interval. The cached comparison of the old ids is not published."""
    t0 = datetime(2026, 10, 19, 9, 0, tzinfo=TZ)
    s = _make(imp="smarthub:boot_import", exp="")
    opts = {"energy_utility_import_statistic_id": "smarthub:a_import"}
    s._get_cm_options = lambda: dict(opts)
    s._utility_stats_cache = {"current": {"utility_import_kwh": 1.0}}

    async def _go():
        s._maybe_schedule_utility_refresh(t0)
        await asyncio.gather(*s.hass.tasks)
        opts["energy_utility_import_statistic_id"] = "smarthub:b_import"
        opts["energy_utility_export_statistic_id"] = "smarthub:b_export"
        # Before the next refresh runs, the stale cache is not published.
        s._utility_stats_cache = {"current": {"utility_import_kwh": 7.0,
                                              "window_start": "x", "window_end": "y"}}
        stale = em.EnergyCoordinator.utility_meter_divergence.fget(s)["utility_kwh"]
        s._maybe_schedule_utility_refresh(t0 + timedelta(minutes=5))
        await asyncio.gather(*s.hass.tasks)
        return stale

    stale = _run(_go())
    assert [c[1] for c in s.query_calls] == [
        {"smarthub:a_import"}, {"smarthub:b_import", "smarthub:b_export"},
    ]
    assert stale is None
    # Cleared in the live options -> feature off.
    opts.clear()
    opts["unrelated"] = 1
    assert em.EnergyCoordinator.utility_meter_divergence.fget(s) is None


def test_no_utility_refresh_when_disabled_or_closed():
    """B-L3: no task is scheduled once EC is disabled or teardown began."""
    t0 = datetime(2026, 10, 19, 9, 0, tzinfo=TZ)
    s = _make()
    s._enabled = False

    async def _go(stub):
        stub._maybe_schedule_utility_refresh(t0)
        await asyncio.sleep(0)

    _run(_go(s))
    assert s.hass.tasks == [] and s.query_calls == []
    s2 = _make()
    s2._utility_stats_closed = True
    _run(_go(s2))
    assert s2.hass.tasks == [] and s2.query_calls == []
    # Control: same stub, flags clear -> it does schedule.
    s3 = _make()
    _run(_go(s3))
    assert len(s3.hass.tasks) == 1


def test_teardown_sets_closed_before_awaits(aware_now):
    """B-L3: a decision cycle finishing during teardown's awaits schedules
    nothing (async_teardown sets the closed flag first)."""
    s = _make()
    s._decision_timer_unsub = None
    s._outage_ledger = None
    s._solar_follow_timer_unsub = None
    s._solar_follow = None
    s._tou_boundary_unsub = None
    s._peak_import_history = []
    s._write_verifier = None
    s._dp_eval_last_task = None
    s._cancel_listeners = lambda: None
    s._optimizer_intent_unsub = None
    s._arm_tou_boundary_listener = lambda: None

    async def _cycle_during_save():
        await s._async_decision_cycle()

    for n in ("_save_circuit_state", "_save_energy_baselines",
              "_save_envoy_cache", "_save_midnight_snapshot",
              "_save_load_shedding_level", "_save_peak_import_history",
              "_save_power_profiles"):
        setattr(s, n, AsyncMock())
    s._save_evse_state = _cycle_during_save

    async def _go():
        await em.EnergyCoordinator.async_teardown(s)
        await asyncio.sleep(0)

    _run(_go())
    assert s.hass.tasks == []
    assert s.query_calls == []
