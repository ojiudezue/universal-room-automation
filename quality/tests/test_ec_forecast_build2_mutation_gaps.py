"""EC-COST-AND-FORECAST-MATH-1 Build 2 -- Review C mutation-gap tests.

Each test names the per-site source mutation that left the suite GREEN and
that it kills. Oracles are hand-derived literals (never the code under test).
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import homeassistant.util.dt as dt_util

from test_ec_forecast_build2 import (  # noqa: F401
    CHI, _DOMAIN, _FL, _FakeDB, _Services, _chicago, _daily, _ec, _entry,
    _real_db, _run, _sensor, _agg,
)
from test_ec_savings_money import _hass_for, _real_sensor_module

from custom_components.universal_room_automation.domain_coordinators import (
    energy_forecast_tomorrow as eft,
)
from custom_components.universal_room_automation.domain_coordinators.energy_tou import (
    TOURateEngine,
)

_FIXED = {"service_availability": 32.50, "delivery_per_kwh": 0.022546,
          "transmission_per_kwh": 0.019930}


def _engine2(off_import=0.043481, mid_import=0.086442, off_export=0.04,
             mid_export=0.10):
    """Shoulder-shaped table with DIFFERENT export rate per period."""
    season = {"months": list(range(1, 13)), "periods": {
        "off_peak": {"hours": [(0, 17), (21, 24)], "import_rate": off_import,
                     "export_rate": off_export},
        "mid_peak": {"hours": [(17, 21)], "import_rate": mid_import,
                     "export_rate": mid_export},
    }}
    return TOURateEngine(rate_table={"shoulder": season}, fixed_charges=dict(_FIXED))


DAY = date(2026, 11, 2)


# ---- D8 provider switch (kills D8g / D8h) --------------------------------

def test_provider_switch_inside_ttl_refetches_not_serves_old_provider():
    """Kills: dropping the `cache[0] != eid` provider check (async and the
    sync cached reader). Provider A's list must never answer for provider B."""
    c = _ec(forecasts=[_entry("2026-11-02T18:00:00+00:00", 80, 60)])
    assert _run(c.async_forecast_temps_for_date(DAY)) == (80.0, 60.0)
    c._weather_entity = "weather.y"
    c.hass.services = _Services([_entry("2026-11-02T18:00:00+00:00", 50, 40)],
                                eid="weather.y")
    # sync reader: cache belongs to weather.x -> nothing for weather.y
    assert c._cached_forecast_temps_for_date(DAY) is None
    # async: re-fetches immediately (no TTL wait) and returns B's values
    assert _run(c.async_forecast_temps_for_date(DAY)) == (50.0, 40.0)


# ---- D4 pricing (kills D4f, D4h, D4j, D4q) -------------------------------

def test_export_credit_uses_export_shares_and_period_rates():
    """Kills: pricing exports with the IMPORT shares (D4f).
    export mix all in mid_peak (rate 0.10): -20 x 0.10 = -2.0; the import
    shares (90/10 off/mid) would give -20 x (0.9x0.04 + 0.1x0.10) = -0.92."""
    mix = {"off_peak": {"import_kwh": 90.0, "export_kwh": 0.0},
           "mid_peak": {"import_kwh": 10.0, "export_kwh": 30.0}}
    cost, _ = eft.price_net_kwh(-20.0, mix, _engine2(), DAY, 3, 14)
    assert cost == pytest.approx(-2.0, abs=1e-9)


def test_fallback_export_is_hour_weighted_not_instant():
    """Kills: export fallback using one instant rate (D4h).
    (20 h x 0.04 + 4 h x 0.10)/24 = 0.05 -> -10 x 0.05 = -0.5 (instant 00:30
    off-peak would give -0.4)."""
    cost, meta = eft.price_net_kwh(-10.0, None, _engine2(), DAY, 3, 0)
    assert cost == pytest.approx(-0.5, abs=1e-9)
    assert meta["rate_source"] == "hour_weighted_day"


def test_period_absent_from_day_priced_at_hour_weighted_not_zero():
    """Kills: a history period missing from the day's schedule priced at 0
    (D4j). Import share 100% 'ghost': 10 x hour-weighted import
    (20 x 0.085957 + 4 x 0.128918)/24 = 0.9311717."""
    mix = {"ghost": {"import_kwh": 5.0, "export_kwh": 0.0}}
    cost, _ = eft.price_net_kwh(10.0, mix, _engine2(), DAY, 3, 14)
    assert cost == pytest.approx(0.9311717, abs=1e-6)


def test_ec_price_net_kwh_passes_real_mix_days_to_min_days_gate():
    """Kills: EC wrapper hard-wiring the mix-day count (D4q). 2 days of mix
    (< 3) must fall back to the hour-weighted day rate."""
    c = _ec(tou=_engine2())
    c._period_mix = {"mid_peak": {"import_kwh": 10.0, "export_kwh": 0.0}}
    c._period_mix_days = 2
    cost, meta = c.price_net_kwh(10.0, DAY)
    assert meta["rate_source"] == "hour_weighted_day"
    assert cost == pytest.approx(0.9311717, abs=1e-6)
    c._period_mix_days = 5
    cost5, meta5 = c.price_net_kwh(10.0, DAY)
    assert meta5["rate_source"] == "period_mix_5d"
    assert cost5 == pytest.approx(1.28918, abs=1e-6)


def test_predicted_cost_today_prices_today_not_other_day():
    """Kills: Cost-Today sensor pricing a wrong local day (D4n)."""
    agg = _agg()
    seen = []
    ec = SimpleNamespace(forecast_today={"predicted_net_kwh": -30.0},
                         price_net_kwh=lambda n, d: (seen.append(d) or (n * 0.1, {})))
    s = _sensor(agg.PredictedCostTodaySensor, ec)
    _run(s.async_update())
    assert seen == [dt_util.now().date()]


def test_price_predicted_no_ec_export_has_no_rate():
    """Kills: no-EC export priced with an import rate (D4p)."""
    agg = _agg()
    hass = SimpleNamespace(data={_DOMAIN: {}})
    val, meta = agg._price_predicted(hass, -5.0, DAY, lambda k, d=None: d)
    assert val is None and meta == {"rate_source": "no_export_rate"}


# ---- D5 log / accuracy (kills D5d, D5m, D5n) -----------------------------

class _FailOnceDB(_FakeDB):
    async def log_forecast_batch(self, rows):
        self.batches.append(list(rows))
        return 0 if len(self.batches) == 1 else len(rows)


def test_failed_log_write_is_retried_not_marked_logged():
    """Kills: marking the day logged when the DB write returned 0 (D5d)."""
    db = _FailOnceDB(daily=_daily())
    c = _ec(db=db, forecasts=_FL)
    _run(c._async_refresh_tomorrow_forecast(datetime(2026, 11, 1, 21, 5, tzinfo=CHI)))
    assert getattr(c, "_forecast_logged_for", None) is None
    _run(c._async_refresh_tomorrow_forecast(datetime(2026, 11, 1, 21, 25, tzinfo=CHI)))
    assert len(db.batches) == 2
    assert c._forecast_logged_for == date(2026, 11, 2)
    _run(c._async_refresh_tomorrow_forecast(datetime(2026, 11, 1, 21, 45, tzinfo=CHI)))
    assert len(db.batches) == 2


def test_refresh_populates_accuracy_attrs_from_joined_log():
    """Kills: dropping the accuracy refresh from the tomorrow refresh (D5m)."""
    class _DB(_FakeDB):
        async def get_forecast_log_joined(self, since):
            self.joined_since = since
            return [{"arm": "v1", "target_date": "2026-10-31",
                     "pred_consumption_kwh": 110.0, "consumption_kwh": 100.0,
                     "pred_net_kwh": 5.0, "import_kwh": 20.0, "export_kwh": 10.0,
                     "pred_cost": 1.0, "net_cost": 1.0}]
    db = _DB(daily=_daily())
    c = _ec(db=db, forecasts=_FL)
    _run(c._async_refresh_tomorrow_forecast(datetime(2026, 11, 1, 10, 0, tzinfo=CHI)))
    acc = c.tomorrow_forecast["accuracy"]
    assert acc["v1"]["mae_30d_kwh"] == 10.0 and acc["v1"]["bias_30d_kwh"] == 10.0
    assert db.joined_since == "2026-10-02"


def test_backtest_mae_attr_needs_seven_log_rows():
    """Kills: removing the >=7 log-row gate on backtest_mae_kwh (D5n)."""
    agg = _agg()

    def _attrs(rows):
        ec = SimpleNamespace(tomorrow_forecast={
            "raw_net_kwh": 10.0, "target_date": "2026-11-02", "model_arm": "v1",
            "accuracy": {"v1": {"log_rows": rows, "net_mae_30d_kwh": 4.2}}})
        s = _sensor(agg.PredictedEnergyTomorrowSensor, ec)
        _run(s.async_update())
        return s.extra_state_attributes
    assert _attrs(7)["backtest_mae_kwh"] == 4.2
    assert "backtest_mae_kwh" not in _attrs(6)


# ---- Background scheduling (kills B7, B11) -------------------------------

def test_forecast_inputs_single_flight_when_interval_elapsed():
    """Kills: dropping the inputs in-flight guard (B7). Interval long
    elapsed but the previous query is still running -> no 2nd task."""
    c = _ec()
    c.hass.config.components = {"recorder"}
    made = []
    c.hass.async_create_background_task = lambda coro, name: made.append(
        coro.close() or name)
    c._forecast_inputs_inflight = True
    c._schedule_forecast_inputs_refresh(dt_util.now())
    assert made == []


def test_schedule_failure_closes_coroutine_and_resets_inflight():
    """Kills: leaking the in-flight flag / un-awaited coroutine when task
    creation raises (B11) -- the refresh would be wedged forever."""
    c = _ec()
    c.hass.config.components = {"recorder"}
    captured = []

    def _boom(coro, name):
        captured.append(coro)
        raise RuntimeError("loop closed")
    c.hass.async_create_background_task = _boom
    with pytest.raises(RuntimeError):
        c._maybe_schedule_forecast_refresh(dt_util.now())
    assert c._forecast_tick_inflight is False
    assert captured[0].cr_frame is None          # closed, never awaited
    captured.clear()
    with pytest.raises(RuntimeError):
        c._schedule_forecast_inputs_refresh(dt_util.now())
    assert c._forecast_inputs_inflight is False
    assert captured[0].cr_frame is None


# ---- D9 / bucketing (kills B13, D9c, D9f) --------------------------------

def test_bucket_drops_negative_change_rows():
    """Kills: counting a negative `change` (meter reset) into the day (B13).
    23 x 1.0 kWh + one -5 row -> 23.0 (the bad row is dropped, not summed)."""
    c = _ec()
    start = datetime(2026, 10, 20, 5, 0, tzinfo=timezone.utc)
    rows = [{"start": start + timedelta(hours=h), "change": 1.0} for h in range(23)]
    rows.append({"start": start + timedelta(hours=23), "change": -5.0})
    out = c._bucket_forecast_inputs({"sensor.span_panel_ac1_consumed_energy": rows})
    assert out["sensor.span_panel_ac1_consumed_energy"] == {date(2026, 10, 20): 23.0}


def test_trailing_mean_excludes_target_day():
    """Kills: the trailing window including the target day itself (D9c)."""
    t = date(2026, 11, 2)
    s = {t: 1000.0, t - timedelta(days=1): 10.0, t - timedelta(days=2): 20.0}
    assert eft.trailing_mean(s, t, 3) == pytest.approx(15.0)


def test_dow_legacy_arm_applies_adjustment_factor():
    """Kills: dow_legacy arm ignoring the EC's adjustment factor (D9f).
    Empty history 45 x 0.9 (55<70<=75) = 40.5 x 1.2 = 48.6."""
    c = _ec(db=_FakeDB())
    c._predictor._adjustment_factor = 1.2
    arms = c._consumption_arms(DAY, 70.0, _daily())
    assert arms["dow_legacy"]["kwh"] == pytest.approx(48.6)


# ---- DB5: period-mix query against the real schema -----------------------

@pytest.mark.asyncio
async def test_history_kwh_rows_returns_interval_rows_since(tmp_path):
    """Kills: get_energy_history_kwh_rows returning nothing / ignoring the
    cutoff (DB5). Real schema; dt_h from the shared CTE."""
    db = await _real_db(tmp_path)
    try:
        con = sqlite3.connect(db.db_file)
        for ts, gi, ex in (("2026-11-01T10:00:00", 4.0, 0.0),
                           ("2026-11-01T10:15:00", 2.0, 1.0),
                           ("2026-10-01T10:00:00", 9.0, 9.0)):
            con.execute(
                "INSERT INTO energy_history (timestamp, grid_import, grid_import_2,"
                " solar_export, solar_production, outside_temp, rooms_occupied,"
                " day_of_week, hour_of_day, is_weekend) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (ts, gi, gi, ex, 0.0, 70.0, 1, 6, 10, 1))
        con.commit()
        con.close()
        rows = await db.get_energy_history_kwh_rows("2026-10-15T00:00:00")
    finally:
        await db.stop_write_worker()
    assert [(r[0], r[1], r[2], round(r[3], 4)) for r in rows] == [
        ("2026-11-01T10:00:00", 4.0, 0.0, 0.25),
        ("2026-11-01T10:15:00", 2.0, 1.0, 0.25)]


# ---- Signed savings through the REAL table (replaces the hollow prune test)

@pytest.mark.asyncio
async def test_signed_savings_flow_through_real_table_to_lifetime_sensor(tmp_path):
    """Replaces the hollow test_lifetime_survives_row_prune (it re-implemented
    max(baseline, live) on literals). Real arbitrage_cycles table: a +3.00
    and a -5.00 discharge row -> lifetime = -2.00 (table SUM, signed) even
    with a seeded baseline of +1.00; empty table -> baseline fallback."""
    db = await _real_db(tmp_path)
    try:
        await db.save_arbitrage_cycle(
            "2026-11-01T20:00:00+00:00", 80.0, 70.0, 0.0, 0.05, 0.13, 0.9,
            3.0, "shoulder", accrual="discharge", kwh_discharged=1.0,
            basis_source="inventory")
        await db.save_arbitrage_cycle(
            "2026-11-01T21:00:00+00:00", 70.0, 60.0, 0.0, 0.12, 0.10, 0.9,
            -5.0, "shoulder", accrual="discharge", kwh_discharged=1.0,
            basis_source="inventory")
        total = await db.query_arbitrage_savings_total()
        since = await db.query_arbitrage_savings_since("2026-11-01T00:00:00+00:00")
        empty_db_total = {"savings": 0.0, "rows": 0}
    finally:
        await db.stop_write_worker()
    assert total["savings"] == pytest.approx(-2.0) and total["rows"] == 2
    assert since["savings"] == pytest.approx(-2.0)
    energy = SimpleNamespace(
        arbitrage_status={"total": total},
        savings_baselines={"arbitrage": {"baseline_usd": 1.0},
                           "peak_avoidance": {"baseline_usd": 0.0}},
        peak_avoidance_status={"peak_avoidance_lifetime_delta": 0.0})
    with _real_sensor_module() as sm:
        s = sm.EnergySavingsTotalLifetimeSensor.__new__(
            sm.EnergySavingsTotalLifetimeSensor)
        s.hass = _hass_for(energy)
        assert s._arb_lifetime() == pytest.approx(-2.0)
        energy.arbitrage_status = {"total": empty_db_total}
        assert s._arb_lifetime() == pytest.approx(1.0)


# ---- Behavioural replacement for the narrowed source-grep test -----------

@pytest.mark.parametrize("cls_name", [
    "PredictedEnergyWeekSensor", "PredictedEnergyMonthSensor",
    "PredictedCostWeekSensor", "PredictedCostMonthSensor",
    "PredictedCoolingNeedSensor", "PredictedHeatingNeedSensor",
])
def test_predicted_async_update_refreshes_forecast_cache_behaviourally(cls_name):
    """Replaces test_forecast_service_migration.py::
    test_predicted_async_updates_call_refresh (a `"await self._refresh_..."
    in source` grep, bug class #62). Runs the real async_update and counts
    the cache refresh."""
    from unittest.mock import MagicMock
    agg = _agg()
    cls = getattr(agg, cls_name)
    s = cls.__new__(cls)
    db = MagicMock()

    async def _pe(period, temp):
        return (10.0, 50)
    db.predict_energy = _pe
    s.hass = SimpleNamespace(data={_DOMAIN: {"database": db}})
    s._get_config = lambda k, d=None: d
    s._cached_value = None
    s._cached_confidence = 0
    s._cache_time = None
    s._cached_raw_net_kwh = None
    n = []

    async def _refresh():
        n.append(1)
    s._refresh_forecast_cache = _refresh
    s._get_forecast_temp = lambda: 80.0
    _run(s.async_update())
    assert n == [1]
