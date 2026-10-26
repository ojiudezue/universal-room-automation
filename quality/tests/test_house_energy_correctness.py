"""fix/house-energy-correctness (AUDIT_house_sensors_correctness_2026_10_25).

1. EC adjustment factor cannot be pinned by one poisoned energy_daily row
   (P8): guarded pct recomputed from (predicted, actual), implausible pairs
   skipped, the rest clamped.
2. WholeHouseCostTodaySensor mirrors EC cost_today, not lifetime x rate (H10).
3. predicted_cost_* does not add delivery on top of the EC rate (P5).
4. predict_energy excludes partial periods (P1/P3/P4).

Oracles are hand-computed literals (not re-derived from the constants).
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import tempfile
import types
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from test_energy_forecast_accuracy import _load_accuracy_tracker_ns

# ---------------------------------------------------------------------------
# 1. Adjustment factor guard
# ---------------------------------------------------------------------------


def _row(date, predicted, actual, stored_pct):
    return {
        "date": date,
        "predicted_consumption_kwh": predicted,
        "consumption_kwh": actual,
        "prediction_error_pct": stored_pct,
    }


def test_restore_poisoned_row_does_not_pin_factor():
    """Real 10-18 row: predicted 121.9, actual 79.2, stored pct +16,664.8.
    Six genuine -20 % days. Recomputed poison pct = -35.0287.
    mean = (-120 - 35.0287) / 7 = -22.1470 -> factor 1 - 0.066441 = 0.93356.
    The old verbatim mean would be +2363.5 % -> 1.3 (cap)."""
    T = _load_accuracy_tracker_ns()["AccuracyTracker"]
    t = T()
    rows = [_row(f"2026-10-{10+i:02d}", 100.0, 80.0, -20.0) for i in range(6)]
    rows.append(_row("2026-10-18", 121.9, 79.2, 16664.8))
    t.restore_from_db(rows)
    assert t.get_adjustment_factor() == pytest.approx(0.93356, abs=1e-4)


def test_in_band_error_is_clamped():
    """+100 % on one day (predicted 50, actual 100, both plausible) and six
    exact days: clamped to 60 -> mean 8.5714 -> factor 1.025714.
    Unclamped would be 100/7 -> 1.042857."""
    T = _load_accuracy_tracker_ns()["AccuracyTracker"]
    t = T()
    rows = [_row(f"2026-10-{10+i:02d}", 100.0, 100.0, 0.0) for i in range(6)]
    rows.append(_row("2026-10-18", 50.0, 100.0, 100.0))
    t.restore_from_db(rows)
    assert t.get_adjustment_factor() == pytest.approx(1.025714, abs=1e-5)


def test_implausible_prediction_is_skipped():
    """10-02 shape: predicted 1,204 kWh vs actual 90 -> pair skipped, the
    three exact days give factor exactly 1.0. If kept, the clamp -60 gives
    mean -15 -> 0.955."""
    T = _load_accuracy_tracker_ns()["AccuracyTracker"]
    t = T()
    rows = [_row(f"2026-10-{10+i:02d}", 100.0, 100.0, 0.0) for i in range(3)]
    rows.append(_row("2026-10-02", 1204.0, 90.0, -92.5))
    t.restore_from_db(rows)
    assert t.get_adjustment_factor() == pytest.approx(1.0, abs=1e-9)


def test_implausibly_small_actual_is_skipped():
    """Actual 5 kWh (counter artifact) is skipped: factor stays 1.0.
    If kept it would clamp to -60 -> 0.955."""
    T = _load_accuracy_tracker_ns()["AccuracyTracker"]
    t = T()
    for i in range(3):
        t.evaluate_accuracy(100.0, 100.0, f"2026-10-{10+i:02d}")
    t.evaluate_accuracy(100.0, 5.0, "2026-10-20")
    assert t.get_adjustment_factor() == pytest.approx(1.0, abs=1e-9)


def test_evaluate_path_feeds_guarded_pct():
    """Live evaluate path (the midnight setter): three -20 % days ->
    factor 0.94; then an evaluated actual of 20,400 kWh (the 10-18 poison
    as evaluated) is skipped and the factor stays 0.94."""
    T = _load_accuracy_tracker_ns()["AccuracyTracker"]
    t = T()
    for i in range(3):
        t.evaluate_accuracy(100.0, 80.0, f"2026-10-{10+i:02d}")
    assert t.get_adjustment_factor() == pytest.approx(0.94, abs=1e-9)
    res = t.evaluate_accuracy(121.9, 20400.0, "2026-10-18")
    # Return dict unchanged: raw pct still reported for the DAO / logs.
    assert res["pct_error"] == pytest.approx(16635.0, abs=0.1)
    assert t.get_adjustment_factor() == pytest.approx(0.94, abs=1e-9)


def test_fewer_than_three_usable_returns_one():
    T = _load_accuracy_tracker_ns()["AccuracyTracker"]
    t = T()
    t.evaluate_accuracy(100.0, 80.0, "2026-10-10")
    t.evaluate_accuracy(100.0, 80.0, "2026-10-11")
    t.evaluate_accuracy(1204.0, 80.0, "2026-10-12")
    assert t.get_adjustment_factor() == 1.0


# ---------------------------------------------------------------------------
# 2 + 3. aggregation sensors (real classes, HA stubs from test_data_pipeline)
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import test_data_pipeline  # noqa: F401,E402  (HA stub side effects)


def _agg():
    from custom_components.universal_room_automation import aggregation
    return aggregation


def _hass_with_ec(rate=0.128918, cost_today=4.75):
    hass = MagicMock()
    ec = MagicMock()
    ec.current_effective_rate = rate
    ec.cost_today = cost_today
    manager = MagicMock()
    manager.coordinators = {"energy": ec}
    hass.data = {"universal_room_automation": {"coordinator_manager": manager}}
    return hass


def _make(cls, hass, config):
    obj = cls.__new__(cls)
    obj.hass = hass
    obj._get_config = lambda key, default=None: config.get(key, default)
    obj._cached_value = None
    obj._cached_confidence = 0
    obj._cache_time = None
    obj._cached_raw_net_kwh = None
    obj._refresh_forecast_cache = _anoop
    obj._get_forecast_temp = lambda: 80.0
    obj._get_forecast_temp_tomorrow = lambda: 80.0
    return obj


async def _anoop():
    return None


def test_whole_house_cost_today_mirrors_ec_cost_today():
    """Lifetime counter 15,346 kWh configured: the sensor must report EC
    cost_today ($4.75), not 15,346 x 0.128918 = $1,978.38."""
    agg = _agg()
    hass = _hass_with_ec(cost_today=4.75)
    hass.states.get.return_value = MagicMock(
        state="15346", attributes={"unit_of_measurement": "kWh"})
    s = _make(agg.WholeHouseCostTodaySensor, hass,
              {agg.CONF_WHOLE_HOUSE_ENERGY_SENSORS: ["sensor.envoy_lifetime"]})
    assert s.native_value == pytest.approx(4.75, abs=1e-9)


def test_whole_house_cost_today_none_when_unconfigured_or_no_ec():
    agg = _agg()
    s = _make(agg.WholeHouseCostTodaySensor, _hass_with_ec(), {})
    assert s.native_value is None
    hass = MagicMock()
    hass.data = {"universal_room_automation": {}}
    s2 = _make(agg.WholeHouseCostTodaySensor, hass,
               {agg.CONF_WHOLE_HOUSE_ENERGY_SENSORS: ["sensor.x"]})
    assert s2.native_value is None


def _db_returning(kwh):
    db = MagicMock()

    async def _pe(period, temp):
        return (kwh, 50)
    db.predict_energy = _pe
    return db


@pytest.mark.parametrize("cls_name", [
    "PredictedCostTodaySensor", "PredictedCostTomorrowSensor",
    "PredictedCostWeekSensor", "PredictedCostMonthSensor",
])
def test_predicted_cost_does_not_double_count_delivery(cls_name):
    """EC rate 0.128918 already includes delivery: 48.3 kWh -> $6.23
    (48.3 x 0.128918 = 6.2267). The old path added 0.05 again -> $8.64."""
    agg = _agg()
    hass = _hass_with_ec(rate=0.128918)
    hass.data["universal_room_automation"]["database"] = _db_returning(48.3)
    s = _make(getattr(agg, cls_name), hass, {agg.CONF_DELIVERY_RATE: 0.05})
    asyncio.new_event_loop().run_until_complete(s.async_update())
    assert s._cached_value == pytest.approx(6.23, abs=1e-9)


def test_predicted_cost_static_rate_keeps_delivery():
    """No EC: static bare rate 0.10 + delivery 0.05 -> 10 kWh = $1.50."""
    agg = _agg()
    hass = MagicMock()
    integ = MagicMock()
    integ.options = {agg.CONF_ELECTRICITY_RATE: 0.10}
    integ.data = {}
    hass.data = {"universal_room_automation": {
        "integration": integ, "database": _db_returning(10.0)}}
    s = _make(agg.PredictedCostTodaySensor, hass, {agg.CONF_DELIVERY_RATE: 0.05})
    asyncio.new_event_loop().run_until_complete(s.async_update())
    assert s._cached_value == pytest.approx(1.50, abs=1e-9)


# ---------------------------------------------------------------------------
# 4. predict_energy partial periods (real schema)
# ---------------------------------------------------------------------------

from test_database_resilience import _make_db  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _seed_day(db_path, day_start, gi_kw, n=96, temp=80.0):
    conn = sqlite3.connect(db_path)
    for i in range(n):
        ts = day_start + timedelta(minutes=15 * i)
        conn.execute(
            "INSERT INTO energy_history (timestamp, grid_import, grid_import_2, "
            "solar_export, solar_production, outside_temp, rooms_occupied, "
            "day_of_week, hour_of_day, is_weekend) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ts.isoformat(), gi_kw, gi_kw, 0.0, 0.0, temp, 2,
             ts.weekday(), ts.hour, ts.weekday() >= 5),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_db(tmp)
        _run(d.initialize())
        yield d


def _freeze(monkeypatch, now):
    import custom_components.universal_room_automation.database as dbmod

    class _FakeDT(datetime):
        @classmethod
        def utcnow(cls):
            return now
    monkeypatch.setattr(dbmod, "datetime", _FakeDT)


def test_similar_days_excludes_today_partial(db, monkeypatch):
    """Mondays 09-28, 10-05, 10-12 at 4 kW (96 kWh) + today Mon 10-19 with
    only 8 samples (8 kWh) -> only the three full days are returned."""
    base = datetime(2026, 9, 28)
    for w in range(3):
        _seed_day(db.db_file, base + timedelta(days=7 * w), 4.0)
    _seed_day(db.db_file, datetime(2026, 10, 19), 4.0, n=8)
    _freeze(monkeypatch, datetime(2026, 10, 19, 2, 0, 0))
    out = _run(db.get_energy_for_similar_days(0, 70, 90, limit=10))
    assert sorted(r["date"] for r in out) == [
        "2026-09-28", "2026-10-05", "2026-10-12"]


def test_week_forecast_excludes_current_partial_week(db, monkeypatch):
    """Now Wed 10-21. Full weeks starting 09-21/09-28/10-05/10-12 at 1 kW
    (168 kWh each); current week has Mon+Tue at 1 kW (48 kWh). Mean of the
    four full weeks = 168. Including the partial week gave (48+168x3)/4=138."""
    for d in range(28):
        _seed_day(db.db_file, datetime(2026, 9, 21) + timedelta(days=d), 1.0)
    for d in range(2):
        _seed_day(db.db_file, datetime(2026, 10, 19) + timedelta(days=d), 1.0)
    _freeze(monkeypatch, datetime(2026, 10, 21, 12, 0, 0))

    async def _days():
        return 60
    db.get_days_of_energy_data = _days
    value, _c = _run(db.predict_energy("week"))
    # +0.25: the pre-existing inclusive BETWEEN counts the next period's
    # 00:00 sample once per window (168.25 -> round 168.2).
    assert value == pytest.approx(168.2, abs=0.05)


def test_month_forecast_excludes_current_partial_month(db, monkeypatch):
    """Now 10-03. Jul (31 d), Aug (31 d), Sep (30 d) at 1 kW -> 744, 744,
    720 kWh, mean 736. Oct partial (2 days, 48 kWh) must not be averaged
    in (old: mean(48, 720, 744) = 504)."""
    d = datetime(2026, 7, 1)
    while d < datetime(2026, 10, 3):
        _seed_day(db.db_file, d, 1.0)
        d += timedelta(days=1)
    _freeze(monkeypatch, datetime(2026, 10, 3, 12, 0, 0))

    async def _days():
        return 90
    db.get_days_of_energy_data = _days
    value, _c = _run(db.predict_energy("month"))
    # +0.25 inclusive-BETWEEN boundary sample, as in the week test.
    assert value == pytest.approx(736.2, abs=0.05)


def test_negative_error_is_clamped_low():
    """-80 % day (predicted 100, actual 20) + six exact days: clamped to -60
    -> mean -8.5714 -> factor 0.974286. Unclamped: -80/7 -> 0.965714."""
    T = _load_accuracy_tracker_ns()["AccuracyTracker"]
    t = T()
    rows = [_row(f"2026-10-{10+i:02d}", 100.0, 100.0, 0.0) for i in range(6)]
    rows.append(_row("2026-10-18", 100.0, 20.0, -80.0))
    t.restore_from_db(rows)
    assert t.get_adjustment_factor() == pytest.approx(0.974286, abs=1e-5)


def test_window_is_last_seven_usable():
    """One old -50 % day then seven exact days: only the last 7 count -> 1.0.
    An 8-wide window would give -50/8 -> 0.98125."""
    T = _load_accuracy_tracker_ns()["AccuracyTracker"]
    t = T()
    t.evaluate_accuracy(100.0, 50.0, "2026-10-01")
    for i in range(7):
        t.evaluate_accuracy(100.0, 100.0, f"2026-10-{10+i:02d}")
    assert t.get_adjustment_factor() == pytest.approx(1.0, abs=1e-9)
