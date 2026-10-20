"""EC-BILL-PREDICTION-FORECAST-1 — bill predictor (D1, P3) + accuracy ledger (D2).

Plan: docs/planning/PLANNING_ec_bill_prediction_forecast.md (incl. §9 PLAN-REVIEW
amendments and "D0 RESULTS 2026-10-20").

Invariants anchored here:
  I1 service charge exactly once; I2 floor actual_to_date + svc + min(0, rem);
  I4 ledger scored from the utility block only, unscored after the deadline.
  (I3 display-only is a consumer-grep fact, recorded in the build report; a
  source grep would be a hollow test, Bug Class #62.)

Bug classes guarded: #53 computed-but-not-consumed (wire-in anchors on the
refresh path and the per-tick push), #63 coincidental equality (weekday vs
weekend fixtures discriminate P3 from a trailing mean; window-end lag
fixtures discriminate "from window end" vs "from today").

Oracles are hand-derived literals, never re-runs of the code under test.
"""
from __future__ import annotations

import asyncio
import json
import types
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from _energy_bootstrap import bootstrap_energy_imports  # noqa: E402

bootstrap_energy_imports()

from custom_components.universal_room_automation import sensor as sen  # noqa: E402
from custom_components.universal_room_automation.const import DOMAIN  # noqa: E402
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
IMP = "smarthub:imp"
SVC = 32.50  # PEC service availability, hand-written


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _tracker(cycle_day=24, tou=None):
    return eb.CostTracker(types.SimpleNamespace(), tou or et.TOURateEngine(),
                          bill_cycle_day=cycle_day)


def _now(y, m, d, h=9):
    return datetime(y, m, d, h, 0, tzinfo=TZ)


def _series(first: date, end_excl: date, fn) -> dict[str, float]:
    out = {}
    d = first
    while d < end_excl:
        out[d.isoformat()] = fn(d)
        d += timedelta(days=1)
    return out


def _cache(window_end: date | None, daily: dict, cur_net: float | None,
           cycle_start: date | None = None, today: date | None = None,
           newest_age_h: float = 20.0, now: datetime | None = None,
           stale: bool = False):
    """Coordinator cache shape (energy.py _compute_utility_comparison)."""
    cur = None
    if cur_net is not None and window_end is not None:
        cur_end = min(window_end, today) if today else window_end
        cur = {"window_start": cycle_start.isoformat(),
               "window_end": cur_end.isoformat(),
               "utility_net_cost": cur_net}
    newest = (now - timedelta(hours=newest_age_h)).isoformat() if now else None
    return {"current": cur, "last_cycle": None,
            "window_end": window_end.isoformat() if window_end else None,
            "daily_net": daily, "newest_hour": newest, "stale": stale}


def _predict(t, now, cache, configured=True):
    t.set_utility_forecast_inputs(configured, cache)
    t.refresh_prediction(now)
    return t.get_status()


# =============================================================================
# D1 — arithmetic, I1 / I2, P3 remainder
# =============================================================================


def test_bill_pred_svc_counted_once():
    """I1: predicted = actual_to_date + remainder + svc, svc exactly once.

    today 10-20 (cycle 09-24..10-24), window end 10-19 -> remaining 10-19..10-23
    = 5 days, flat $5/day history -> remainder 25.00. Actual to date 100.00.
    Oracle 100 + 25 + 32.50 = 157.50. A double svc would read 190.00.
    """
    now = _now(2026, 10, 20)
    daily = _series(date(2026, 8, 24), date(2026, 10, 19), lambda d: 5.0)
    st = _predict(_tracker(), now, _cache(date(2026, 10, 19), daily, 100.0,
                                          date(2026, 9, 24), now.date(), now=now))
    assert st["prediction_source"] == "utility"
    assert st["predicted_bill"] == 157.50
    assert st["actual_to_date"] == 100.00
    assert st["remainder_cost"] == 25.00
    assert st["fixed_charge"] == 32.50
    assert st["predicted_bill"] - st["fixed_charge"] - st["actual_to_date"] == pytest.approx(
        st["remainder_cost"], abs=0.005)


def test_bill_pred_svc_from_rate_engine():
    """Fixed charge from the loaded rate file (41.25), not the 32.50 constant."""
    now = _now(2026, 10, 20)
    daily = _series(date(2026, 8, 24), date(2026, 10, 19), lambda d: 5.0)
    tou = et.TOURateEngine(fixed_charges={"service_availability": 41.25,
                                          "delivery_per_kwh": 0.022546,
                                          "transmission_per_kwh": 0.019930})
    st = _predict(_tracker(tou=tou), now, _cache(date(2026, 10, 19), daily, 100.0,
                                                 date(2026, 9, 24), now.date(), now=now))
    assert st["fixed_charge"] == 41.25
    assert st["predicted_bill"] == 166.25


@pytest.mark.parametrize("per_day, actual", [(-3.0, 40.0), (0.0, 40.0), (4.0, 0.0), (-9.0, 10.0)])
def test_bill_pred_floor_actual_to_date(per_day, actual):
    """I2: predicted >= actual + svc + min(0, remainder); equality by construction.

    Negative per-day net (export days) may pull the prediction below
    actual + svc, but only by the forecast credit itself (5 days x per_day).
    """
    now = _now(2026, 10, 20)
    daily = _series(date(2026, 8, 24), date(2026, 10, 19), lambda d: per_day)
    st = _predict(_tracker(), now, _cache(date(2026, 10, 19), daily, actual,
                                          date(2026, 9, 24), now.date(), now=now))
    rem = round(5 * per_day, 2)
    assert st["remainder_cost"] == pytest.approx(rem)
    assert st["predicted_bill"] == pytest.approx(round(actual + rem + SVC, 2))
    assert st["predicted_bill"] >= actual + SVC + min(0.0, rem) - 1e-9
    if rem >= 0:
        assert st["predicted_bill"] >= actual + SVC


@pytest.mark.parametrize("lag_days, rem_days", [(0, 4), (1, 5), (2, 6)])
def test_bill_pred_remainder_counts_from_window_end(lag_days, rem_days):
    """R2: the remainder starts at the utility window end, not today.

    today 10-20; window end = today - lag. Remaining days to 10-24 are 4 + lag.
    $5/day -> remainder 5 x rem_days. Counting from today would give 4 days.
    """
    now = _now(2026, 10, 20)
    we = date(2026, 10, 20) - timedelta(days=lag_days)
    daily = _series(date(2026, 8, 24), we, lambda d: 5.0)
    st = _predict(_tracker(), now, _cache(we, daily, 100.0, date(2026, 9, 24),
                                          now.date(), now=now))
    assert st["remainder_days"] == rem_days
    assert st["remainder_cost"] == 5.0 * rem_days
    assert st["actual_window_end"] == we.isoformat()


def test_bill_pred_same_weekday_mean_not_trailing_mean():
    """P3: each remaining day priced at its weekday's mean over 4 weeks.

    History: weekdays $10, Sat/Sun $2. Remaining 10-18 (Sun) .. 10-23 (Fri):
    Sun 2 + Mon-Fri 5 x 10 = 52.00. A trailing-7 mean would give
    6 x (5x10 + 2x2)/7 = 46.29 (a full 7-day remainder would coincide, so the
    fixture deliberately leaves 6 days).
    """
    now = _now(2026, 10, 20)
    we = date(2026, 10, 18)  # Sunday
    daily = _series(date(2026, 8, 24), we,
                    lambda d: 2.0 if d.weekday() >= 5 else 10.0)
    st = _predict(_tracker(), now, _cache(we, daily, 100.0, date(2026, 9, 24),
                                          now.date(), now=now))
    assert st["remainder_days"] == 6
    assert st["remainder_cost"] == 52.00


def test_bill_pred_trailing_fallback_when_no_same_weekday():
    """A remaining day with no same-weekday history uses the trailing-7 mean.

    History only 10-16 (Fri) $12, 10-17 (Sat) $3, 10-18 (Sun) $9; window end
    10-19. Remaining 10-19 Mon .. 10-23 Fri. Mon-Thu have no same-weekday
    history -> trailing mean (12+3+9)/3 = 8 each = 32; Fri uses 10-16 = 12.
    Total 44.00 (all-trailing would be 40.00).
    """
    now = _now(2026, 10, 20)
    daily = {"2026-10-16": 12.0, "2026-10-17": 3.0, "2026-10-18": 9.0}
    st = _predict(_tracker(), now, _cache(date(2026, 10, 19), daily, 50.0,
                                          date(2026, 9, 24), now.date(), now=now))
    assert st["remainder_cost"] == 44.00


def test_bill_pred_unpriceable_day_is_unavailable():
    """No history at all: the remainder cannot be priced -> unavailable."""
    now = _now(2026, 10, 20)
    st = _predict(_tracker(), now, _cache(date(2026, 10, 19), {}, 50.0,
                                          date(2026, 9, 24), now.date(), now=now))
    assert st["predicted_bill"] is None
    assert st["prediction_source"] == "unavailable"


# =============================================================================
# D1 — gating: learning, stale, missing, not configured, cycle-start gap
# =============================================================================


@pytest.mark.parametrize("day, predicts", [(0, False), (1, False), (2, False), (3, True)])
def test_bill_pred_learning_gate_three_days(day, predicts):
    now = _now(2026, 10, 24) + timedelta(days=day)
    we = now.date() - timedelta(days=1)
    daily = _series(date(2026, 8, 24), we, lambda d: 5.0)
    cur = 5.0 * (we - date(2026, 10, 24)).days if we > date(2026, 10, 24) else None
    st = _predict(_tracker(), now, _cache(we, daily, cur, date(2026, 10, 24),
                                          now.date(), now=now))
    if predicts:
        assert st["prediction_source"] == "utility"
        assert st["predicted_bill"] is not None
        assert st["prediction_label"] is None
    else:
        assert st["predicted_bill"] is None
        assert st["prediction_source"] == "learning"
        assert st["prediction_label"] == f"Learning ({day} days)"


def test_bill_pred_cycle_start_gap_forecasts_whole_cycle():
    """R3: fresh stats but the window has not reached the cycle start
    (current block None): actual 0, the whole cycle is forecast.

    Cycle 10-24..11-24 (31 days), today 10-27 (day 3), window end 10-24
    (lag 3 days, newest hour 10-23 23:00 = 34 h old: fresh). $4/day ->
    remainder 31 x 4 = 124.00, predicted 156.50.
    """
    now = _now(2026, 10, 27)
    daily = _series(date(2026, 9, 1), date(2026, 10, 24), lambda d: 4.0)
    st = _predict(_tracker(), now, _cache(date(2026, 10, 24), daily, None,
                                          date(2026, 10, 24), now.date(), now=now,
                                          newest_age_h=34.0))
    assert st["prediction_source"] == "utility"
    assert st["actual_to_date"] == 0.0
    assert st["remainder_days"] == 31
    assert st["remainder_cost"] == 124.00
    assert st["predicted_bill"] == 156.50


@pytest.mark.parametrize("age_h, fresh", [(47.0, True), (48.0, True), (49.0, False)])
def test_bill_pred_staleness_reevaluated_from_newest_hour(age_h, fresh):
    """The cache's own stale flag says fresh, but the predictor re-ages the
    newest hour against now (a refresh that keeps failing keeps the cache)."""
    now = _now(2026, 10, 20)
    daily = _series(date(2026, 8, 24), date(2026, 10, 19), lambda d: 5.0)
    st = _predict(_tracker(), now, _cache(date(2026, 10, 19), daily, 100.0,
                                          date(2026, 9, 24), now.date(), now=now,
                                          newest_age_h=age_h))
    assert (st["prediction_source"] == "utility") is fresh
    assert (st["predicted_bill"] == 157.50) is fresh


def test_bill_pred_stale_flag_unavailable_no_ec_fallback():
    """D0: configured + stale -> unavailable, never an EC-derived number."""
    now = _now(2026, 10, 20)
    t = _tracker()
    t._cost_this_cycle = 90.0
    t._days_in_cycle = 26
    daily = _series(date(2026, 8, 24), date(2026, 10, 19), lambda d: 5.0)
    st = _predict(t, now, _cache(date(2026, 10, 19), daily, 100.0, date(2026, 9, 24),
                                 now.date(), now=now, stale=True))
    assert st["predicted_bill"] is None
    assert st["prediction_source"] == "unavailable"
    assert st["prediction_label"] == "Unavailable (utility stats stale)"
    st2 = _predict(t, now, None)
    assert st2["prediction_source"] == "unavailable"
    assert st2["predicted_bill"] is None


def test_bill_pred_not_configured_ec_straight_line_labelled():
    """No utility statistic id: legacy straight line, labelled ec_uncorrected.

    $90 over 9 DB days, cycle 10-24..11-24 = 31 days -> 310 + 32.50 = 342.50.
    """
    now = _now(2026, 11, 2)
    t = _tracker()
    t._cost_this_cycle = 90.0
    t._db_days_in_cycle = 9
    st = _predict(t, now, None, configured=False)
    assert st["prediction_source"] == "ec_uncorrected"
    assert st["predicted_bill"] == 342.50


# =============================================================================
# D1 — cycle math via the cycle helper (month lengths, Feb, Dec, cycle days)
# =============================================================================


@pytest.mark.parametrize("cycle_day, now, start, end, remaining", [
    (24, _now(2026, 1, 30), "2026-01-24", "2026-02-24", 25),
    (24, _now(2026, 2, 28), "2026-02-24", "2026-03-24", 24),   # 28-day Feb cycle
    (24, _now(2028, 2, 26), "2028-02-24", "2028-03-24", 27),   # leap: 29 days
    (24, _now(2026, 12, 27), "2026-12-24", "2027-01-24", 28),  # Dec -> Jan
    (24, _now(2026, 1, 5), "2025-12-24", "2026-01-24", 19),
    (1, _now(2026, 2, 10), "2026-02-01", "2026-03-01", 19),
    (28, _now(2026, 3, 2), "2026-02-28", "2026-03-28", 26),
])
def test_bill_pred_cycle_end_uses_cycle_helper(cycle_day, now, start, end, remaining):
    t = _tracker(cycle_day=cycle_day)
    t._check_cycle_reset(now)
    st = _predict(t, now, None, configured=False)
    assert st["cycle_start_date"] == start
    assert st["cycle_end"] == end
    assert st["days_remaining"] == remaining


def test_bill_pred_feb_cycle_ec_line_uses_28_days():
    """Feb 24 -> Mar 24 = 28 days (the old month hand-roll agreed here; a
    fixed 30 would read 300 + svc). $10/day x 28 = 280 + 32.50."""
    now = _now(2026, 3, 3)
    t = _tracker()
    t._cost_this_cycle = 70.0
    t._db_days_in_cycle = 7
    st = _predict(t, now, None, configured=False)
    assert st["predicted_bill"] == 312.50


# =============================================================================
# D1 — single producer of prediction_source (R1) + counterfactual (R5)
# =============================================================================


class _St:
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}


class _FakeEnergy:
    """Real coordinator divergence producer + real CostTracker status."""

    def __init__(self, tracker, imp_id, cache):
        self.hass = types.SimpleNamespace(states=types.SimpleNamespace(
            get=lambda eid: _St("500", {})))
        self._utility_meter_entity = "sensor.smarthub_monthly"
        self._utility_import_stat_id = imp_id
        self._utility_export_stat_id = ""
        self._utility_stats_cache = cache
        self._utility_stats_refreshed_at = None
        self._utility_stats_error = None
        self._billing = tracker
        self.arbitrage_status = {"cycle": {"savings": 0.0},
                                 "pace": {"avg_savings_per_day": 1.0}}
        self.peak_avoidance_status = {}

    @property
    def billing_status(self):
        return self._billing.get_status()

    @property
    def predicted_bill(self):
        return self._billing.predicted_bill

    def _utility_stat_ids(self):
        return em.EnergyCoordinator._utility_stat_ids(self)

    def _current_utility_cache(self):
        return em.EnergyCoordinator._current_utility_cache(self)

    def _utility_statistics_divergence(self):
        return em.EnergyCoordinator._utility_statistics_divergence(self)

    @property
    def utility_meter_divergence(self):
        return em.EnergyCoordinator.utility_meter_divergence.fget(self)


def _attrs(energy):
    s = sen.EnergyPredictedBillSensor.__new__(sen.EnergyPredictedBillSensor)
    s.hass = types.SimpleNamespace(data={DOMAIN: {"coordinator_manager":
                                                  types.SimpleNamespace(coordinators={"energy": energy})}})
    return s.extra_state_attributes


@pytest.mark.parametrize("imp_id", [IMP, ""])
def test_bill_pred_prediction_source_single_producer(imp_id):
    """R1: stale cache -> attr is the predictor's value, never 'envoy', on both
    the statistics path and the legacy utility-meter-entity path."""
    now = _now(2026, 10, 20)
    t = _tracker()
    t._check_cycle_reset(now)
    cache = _cache(date(2026, 10, 19), {}, 100.0, date(2026, 9, 24), now.date(),
                   now=now, stale=True)
    t.set_utility_forecast_inputs(bool(imp_id), cache)
    t.refresh_prediction(now)
    attrs = _attrs(_FakeEnergy(t, imp_id, cache))
    assert attrs["prediction_source"] == ("unavailable" if imp_id else "ec_uncorrected")
    assert attrs["prediction_source"] != "envoy"
    assert "prediction_source" not in (em.EnergyCoordinator.utility_meter_divergence.fget(
        _FakeEnergy(t, imp_id, cache)) or {})


def test_bill_pred_sensor_publishes_breakdown_attrs():
    now = _now(2026, 10, 20)
    t = _tracker()
    t._check_cycle_reset(now)
    daily = _series(date(2026, 8, 24), date(2026, 10, 19), lambda d: 5.0)
    cache = _cache(date(2026, 10, 19), daily, 100.0, date(2026, 9, 24), now.date(), now=now)
    t.set_utility_forecast_inputs(True, cache)
    t.refresh_prediction(now)
    attrs = _attrs(_FakeEnergy(t, IMP, cache))
    assert attrs["prediction_source"] == "utility"
    assert attrs["actual_to_date"] == 100.00
    assert attrs["utility_cost"] == 100.00  # same value, one producer
    assert attrs["remainder_cost"] == 25.00
    assert attrs["fixed_charge"] == 32.50
    assert attrs["actual_window_end"] == "2026-10-19"
    assert attrs["cycle_end"] == "2026-10-24"
    assert attrs["days_remaining"] == 4
    assert attrs["accuracy_cycles_scored"] == 0


def test_counterfactual_uses_billing_days_remaining():
    """R5: arbitrage projection uses the billing status's days_remaining.

    For day-24 cycles the legacy relativedelta length agrees with the cycle
    helper, so the value is detached (set to 3) to prove the sensor reads it:
    avg 1.0/day x 3 days + 0 accrued = 3.00 (legacy path would give 4.00).
    """
    now = _now(2026, 10, 20)
    t = _tracker()
    t._check_cycle_reset(now)
    t.set_utility_forecast_inputs(False, None)
    t._cost_this_cycle = 52.0
    t._db_days_in_cycle = 26
    t.refresh_prediction(now)
    t._days_remaining = 3  # detach the value: the sensor must read it
    attrs = _attrs(_FakeEnergy(t, "", None))
    # avg 1.0/day x 3 days + 0 accrued = 3.00
    assert attrs["arbitrage_savings_projected_cycle_total"] == 3.00


# =============================================================================
# Coordinator wire-in: refresh path + per-tick push
# =============================================================================


def _hour_rows(day: date, kwh: float) -> list[dict]:
    start = datetime(day.year, day.month, day.day, tzinfo=TZ).astimezone(timezone.utc)
    nxt = day + timedelta(days=1)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=TZ).astimezone(timezone.utc)
    rows, t = [], start
    while t < end:
        rows.append({"start": t.timestamp(), "change": kwh})
        t += timedelta(hours=1)
    return rows


def _days_rows(first: date, last_incl: date, kwh: float) -> list[dict]:
    rows, d = [], first
    while d <= last_incl:
        rows += _hour_rows(d, kwh)
        d += timedelta(days=1)
    return rows


class _KV:
    def __init__(self, store=None):
        self.store = dict(store or {})
        self.saves: list[tuple[str, str]] = []

    async def save_energy_state(self, key, value):
        self.saves.append((key, value))
        self.store[key] = value

    async def restore_energy_state(self, key):
        return self.store.get(key)

    async def get_energy_daily_for_cycle(self, start, end):
        return {"days": 0}


class _Hass:
    def __init__(self, db):
        self.data = {"universal_room_automation": {"database": db}}
        self.config = types.SimpleNamespace(components={"recorder"})
        self.states = MagicMock()
        self.tasks: list = []

    def async_create_background_task(self, coro, name, eager_start=True):
        task = asyncio.get_event_loop().create_task(coro)
        self.tasks.append(task)
        return task


def _coord(db, imp=IMP, ready=True):
    s = types.SimpleNamespace()
    s.hass = _Hass(db)
    s._tou = et.TOURateEngine()
    s._billing = _tracker()
    s._utility_import_stat_id = imp
    s._utility_export_stat_id = ""
    s._utility_meter_entity = None
    s._utility_stats_last_run = None
    s._utility_stats_inflight = False
    s._utility_stats_task = None
    s._utility_stats_cache = None
    s._utility_stats_error = None
    s._utility_stats_refreshed_at = None
    s._enabled = True
    s._bill_ledger_ready = ready
    for n in ("_maybe_schedule_utility_refresh", "_async_refresh_utility_stats",
              "_compute_utility_comparison", "_utility_stat_ids",
              "_current_utility_cache", "_push_bill_forecast_inputs",
              "_bill_forecast_after_refresh", "_restore_bill_forecast_ledger",
              "_utility_statistics_divergence"):
        setattr(s, n, getattr(em.EnergyCoordinator, n).__get__(s))
    return s


def _refresh(s, now, rows):
    async def _q(start_utc, ids):
        return {IMP: rows}

    s._query_utility_statistics = _q

    async def _go():
        s._utility_stats_last_run = None
        s._maybe_schedule_utility_refresh(now)
        await asyncio.gather(*s.hass.tasks)
        s.hass.tasks.clear()

    _run(_go())
    assert s._utility_stats_error is None, s._utility_stats_error


def test_refresh_wires_prediction_from_utility_series():
    """Wire-in anchor: `_async_refresh_utility_stats` -> `_bill_forecast_after_refresh`.

    Uniform 1 kWh/h series inside one season (spring 2027 shoulder, no DST
    day in the windows used): every covered day costs the same, so the
    remainder must be remainder_days x (actual / covered days). Today
    2027-04-20, rows through 04-18 complete -> window end 04-19, 26 covered
    days (03-24..04-18), remainder 04-19..04-23 = 5 days.
    """
    now = _now(2027, 4, 20)
    s = _coord(_KV())
    s._billing._check_cycle_reset(now)
    _refresh(s, now, _days_rows(date(2027, 2, 24), date(2027, 4, 18), 1.0))
    st = s._billing.get_status()
    assert st["prediction_source"] == "utility"
    cur = s._utility_stats_cache["current"]
    assert st["actual_to_date"] == cur["utility_net_cost"]
    assert st["remainder_days"] == 5
    assert st["remainder_cost"] == pytest.approx(5 * cur["utility_net_cost"] / 26, abs=0.02)
    assert st["predicted_bill"] == pytest.approx(
        st["actual_to_date"] + st["remainder_cost"] + SVC, abs=0.005)


def test_per_tick_push_switches_predictor_off_utility_when_id_blanked():
    """Wire-in anchor: `_maybe_schedule_utility_refresh` pushes the live config
    every decision cycle, including when the id is blank (kill switch)."""
    now = _now(2026, 10, 20)
    s = _coord(_KV())
    s._billing._check_cycle_reset(now)
    _refresh(s, now, _days_rows(date(2026, 8, 24), date(2026, 10, 18), 1.0))
    assert s._billing.get_status()["prediction_source"] == "utility"
    s._utility_import_stat_id = ""
    s._maybe_schedule_utility_refresh(now)
    s._billing.refresh_prediction(now)
    assert s._billing.get_status()["prediction_source"] == "ec_uncorrected"


# =============================================================================
# D2 — ledger
# =============================================================================


def test_ledger_one_snapshot_per_day():
    """Two refreshes on the same day: one snapshot, one write (no-op second)."""
    now = _now(2026, 10, 20)
    db = _KV()
    s = _coord(db)
    s._billing._check_cycle_reset(now)
    rows = _days_rows(date(2026, 8, 24), date(2026, 10, 18), 1.0)
    _refresh(s, now, rows)
    _refresh(s, now + timedelta(hours=2), rows)
    assert len(db.saves) == 1
    payload = json.loads(db.store["bill_forecast_ledger"])
    (cyc,) = payload["cycles"]
    assert cyc["cycle_start"] == "2026-09-24"
    assert cyc["next_cycle_start"] == "2026-10-24"
    assert list(cyc["snapshots"]) == ["26"]
    assert cyc["snapshots"]["26"]["actual_window_end"] == "2026-10-19"
    assert s._billing.get_status()["ledger_days_this_cycle"] == 1
    # Next day: a second snapshot and a second write.
    _refresh(s, now + timedelta(days=1), rows + _days_rows(date(2026, 10, 19), date(2026, 10, 19), 1.0))
    assert len(db.saves) == 2
    assert s._billing.get_status()["ledger_days_this_cycle"] == 2


def test_ledger_waits_for_restore():
    """Before the restore has run, ledger ops neither snapshot nor write."""
    now = _now(2026, 10, 20)
    db = _KV()
    s = _coord(db, ready=False)
    s._billing._check_cycle_reset(now)
    _refresh(s, now, _days_rows(date(2026, 8, 24), date(2026, 10, 18), 1.0))
    assert db.saves == []
    assert s._billing.get_status()["prediction_source"] == "utility"


def test_ledger_restore_roundtrip():
    """Restart mid-cycle: restored snapshots kept, same day not duplicated."""
    now = _now(2026, 10, 20)
    db = _KV()
    s = _coord(db)
    s._billing._check_cycle_reset(now)
    rows = _days_rows(date(2026, 8, 24), date(2026, 10, 18), 1.0)
    _refresh(s, now, rows)
    saved = db.store["bill_forecast_ledger"]
    s2 = _coord(db, ready=False)
    s2._billing._check_cycle_reset(now)
    _run(s2._restore_bill_forecast_ledger())
    assert s2._bill_ledger_ready is True
    assert s2._billing.ledger.to_json() == saved
    _refresh(s2, now + timedelta(hours=3), rows)
    assert len(db.saves) == 1  # same day after restart: no new write
    assert s2._billing.get_status()["ledger_days_this_cycle"] == 1


def test_ledger_restore_bad_payload_is_empty_and_ready():
    s = _coord(_KV({"bill_forecast_ledger": "{not json"}), ready=False)
    _run(s._restore_bill_forecast_ledger())
    assert s._billing.ledger.cycles == []
    assert s._bill_ledger_ready is True


def _ledger_with(cycle_start="2026-09-24", nxt="2026-10-24", preds=None):
    led = eb.BillForecastLedger()
    for day, p in (preds or {7: 180.0, 14: 190.0, 21: 205.0, 26: 200.0}).items():
        led.record_snapshot(date.fromisoformat(cycle_start), date.fromisoformat(nxt),
                            day, p, None)
    return led


def _block(start="2026-09-24", end="2026-10-24", bill=200.0, ec=120.0):
    return {"window_start": start, "window_end": end, "utility_net_cost": bill - SVC,
            "utility_bill_estimate": bill, "ec_net_cost": ec}


def test_ledger_close_scores_from_utility_only():
    """I4: actual = utility_bill_estimate of the exact window; errors per horizon.

    Predictions 180 / 190 / 205 vs actual 200 -> -10.0 / -5.0 / +2.5 %.
    The EC side (120) is recorded but never the actual.
    """
    led = _ledger_with()
    assert led.try_close(date(2026, 10, 25), _block()) is True
    (c,) = led.cycles
    assert c["status"] == "scored"
    assert c["actual"] == 200.0
    assert c["errors"] == {"7": -10.0, "14": -5.0, "21": 2.5}
    a = led.attributes(None)
    assert a["accuracy_mape_by_horizon"] == {7: 10.0, 14: 5.0, 21: 2.5}
    assert a["accuracy_cycles_scored"] == 1
    assert a["last_cycle_actual"] == 200.0
    assert a["last_cycle_error_by_horizon"] == {7: -10.0, 14: -5.0, 21: 2.5}


@pytest.mark.parametrize("start, end", [("2026-09-23", "2026-10-24"),
                                        ("2026-09-24", "2026-10-23")])
def test_ledger_close_rejects_other_window(start, end):
    led = _ledger_with()
    assert led.try_close(date(2026, 10, 25), _block(start, end)) is False
    assert led.cycles[0]["status"] == "open"


def test_ledger_not_closed_before_cycle_end():
    led = _ledger_with()
    assert led.try_close(date(2026, 10, 23), _block()) is False
    assert led.cycles[0]["status"] == "open"


@pytest.mark.parametrize("days_after, status", [(6, "open"), (7, "unscored"), (8, "unscored")])
def test_ledger_unscored_when_stale(days_after, status):
    """R4/I4: no covering block -> open until next_start + 7 days, then unscored;
    MAPE is unaffected by an unscored cycle."""
    led = _ledger_with()
    led.try_close(date(2026, 10, 24) + timedelta(days=days_after), None)
    assert led.cycles[0]["status"] == status
    assert led.cycles[0]["actual"] is None
    assert led.attributes(None)["accuracy_mape_by_horizon"] == {}
    assert led.attributes(None)["accuracy_cycles_scored"] == 0


def test_ledger_scores_late_arrival():
    """R4: stale for 3 days after close, then the block arrives -> scored."""
    led = _ledger_with()
    for d in (24, 25, 26):
        led.try_close(date(2026, 10, d), None)
    assert led.cycles[0]["status"] == "open"
    assert led.try_close(date(2026, 10, 27), _block()) is True
    assert led.cycles[0]["status"] == "scored"


def test_ledger_mape_over_two_cycles():
    """Cycle A errors -10/-5/+2.5; cycle B preds 110/90/100 vs 100 -> +10/-10/0.
    MAPE 7: (10+10)/2 = 10.0; 14: (5+10)/2 = 7.5; 21: (2.5+0)/2 = 1.2 (round 1.25)."""
    led = _ledger_with()
    led.try_close(date(2026, 10, 25), _block())
    for day, p in {7: 110.0, 14: 90.0, 21: 100.0}.items():
        led.record_snapshot(date(2026, 10, 24), date(2026, 11, 24), day, p, None)
    led.try_close(date(2026, 11, 25), _block("2026-10-24", "2026-11-24", bill=100.0))
    m = led.attributes(None)["accuracy_mape_by_horizon"]
    assert m[7] == 10.0 and m[14] == 7.5
    assert m[21] == pytest.approx(1.2, abs=0.051)


def test_ledger_bounded():
    led = eb.BillForecastLedger()
    start = date(2025, 1, 24)
    for i in range(14):
        cs = date(start.year + (start.month - 1 + i) // 12, (start.month - 1 + i) % 12 + 1, 24)
        led.record_snapshot(cs, cs + timedelta(days=30), 3, 100.0, None)
    assert len(led.cycles) == 12
    assert led.cycles[0]["cycle_start"] == "2025-03-24"
    assert led.cycles[-1]["cycle_start"] == "2026-02-24"


def test_ledger_no_snapshot_when_unavailable():
    """Only a utility-sourced prediction is snapshotted."""
    now = _now(2026, 10, 20)
    t = _tracker()
    t._check_cycle_reset(now)
    t.set_utility_forecast_inputs(True, None)
    t.refresh_prediction(now)
    assert t.ledger_tick(now, None) is False
    assert t.ledger.cycles == []


def test_ledger_no_snapshot_for_ec_uncorrected():
    """A not-configured (EC straight line) prediction is never snapshotted."""
    now = _now(2026, 10, 20)
    t = _tracker()
    t._check_cycle_reset(now)
    t._cost_this_cycle = 52.0
    t._db_days_in_cycle = 26
    t.set_utility_forecast_inputs(False, None)
    t.refresh_prediction(now)
    assert t.predicted_bill is not None
    assert t.ledger_tick(now, None) is False
    assert t.ledger.cycles == []


def test_restore_all_sequential_restores_ledger():
    """Wire-in anchor: setup's sequential restore runs the ledger restore."""
    db = _KV({"bill_forecast_ledger": _ledger_with().to_json()})
    s = _coord(db, ready=False)

    async def _noop(*a, **k):
        return None

    for n in ("_restore_cycle_from_db", "_restore_accuracy_from_db",
              "_restore_peak_import_history", "_fit_temp_regression",
              "_restore_evse_state", "_restore_circuit_state",
              "_restore_energy_baselines", "_restore_consumption_history",
              "_restore_power_profiles", "_restore_midnight_snapshot",
              "_restore_envoy_cache", "_restore_load_shedding_level",
              "_restore_solar_follow_state"):
        setattr(s, n, _noop)
    s._restore_all_sequential = em.EnergyCoordinator._restore_all_sequential.__get__(s)
    _run(s._restore_all_sequential(_now(2026, 10, 20)))
    assert s._bill_ledger_ready is True
    assert len(s._billing.ledger.cycles) == 1
    assert sorted(s._billing.ledger.cycles[0]["snapshots"]) == ["14", "21", "26", "7"]
