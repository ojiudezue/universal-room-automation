"""EC-COST-AND-FORECAST-MATH-1 Build 2 — forecast maths.

Spec: docs/planning/PLANNING_ec_savings_and_tomorrow_forecast.md rev 5,
Build 2 (D8, D9, D3, D4, D5; D0 is the committed probe + fit scripts).

Every test drives production code (real TOURateEngine, real EC methods,
real DailyEnergyPredictor, real UniversalRoomDatabase for D5). Oracles are
hand-derived from literal coefficients / rates written below, never by
re-running the code under test.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

import homeassistant.util.dt as dt_util

from custom_components.universal_room_automation.domain_coordinators import (
    energy_forecast as ef,
)
from custom_components.universal_room_automation.domain_coordinators import (
    energy_forecast_tomorrow as eft,
)
from custom_components.universal_room_automation.domain_coordinators.energy import (
    EnergyCoordinator,
)
from custom_components.universal_room_automation.domain_coordinators.energy_tou import (
    TOURateEngine,
)

_DOMAIN = "universal_room_automation"
CHI = ZoneInfo("America/Chicago")


@pytest.fixture(autouse=True)
def _chicago():
    """Local time = America/Chicago for every test; restored after."""
    prev = dt_util.get_default_time_zone()
    dt_util.set_default_time_zone(CHI)
    try:
        yield
    finally:
        dt_util.set_default_time_zone(prev)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# Shoulder-shaped literal table (same as test_ec_savings_money):
#   off_peak eff 0.043481 + 0.042476 = 0.085957 ; mid_peak eff 0.128918
#   export 0.043481 both periods ; mid_peak = 17:00-21:00 local.
_FIXED = {"service_availability": 32.50, "delivery_per_kwh": 0.022546,
          "transmission_per_kwh": 0.019930}


def _engine(off_import=0.043481, mid_import=0.086442, export=0.043481):
    season = {"months": list(range(1, 13)), "periods": {
        "off_peak": {"hours": [(0, 17), (21, 24)], "import_rate": off_import,
                     "export_rate": export},
        "mid_peak": {"hours": [(17, 21)], "import_rate": mid_import,
                     "export_rate": export},
    }}
    return TOURateEngine(rate_table={"shoulder": season}, fixed_charges=dict(_FIXED))


def _entry(day_iso_utc_noonish, hi, lo):
    return {"datetime": day_iso_utc_noonish, "temperature": hi, "templow": lo,
            "condition": "sunny"}


# ===========================================================================
# D8 — forecast entry by LOCAL date, no fallback
# ===========================================================================


def test_forecast_temps_for_date_selects_by_local_date():
    """Provider dropped today after sunset: first entry is tomorrow ->
    for_date(tomorrow) is that entry, for_date(today) is None (index-1 would
    have returned the day AFTER tomorrow). List starting today: both."""
    tomorrow_first = [_entry("2026-11-02T18:00:00+00:00", 80, 60),
                      _entry("2026-11-03T18:00:00+00:00", 70, 50)]
    assert eft.select_forecast_for_date(tomorrow_first, date(2026, 11, 2)) == (80.0, 60.0)
    assert eft.select_forecast_for_date(tomorrow_first, date(2026, 11, 1)) is None
    today_first = [_entry("2026-11-01T18:00:00+00:00", 75, 55)] + tomorrow_first
    assert eft.select_forecast_for_date(today_first, date(2026, 11, 1)) == (75.0, 55.0)
    assert eft.select_forecast_for_date(today_first, date(2026, 11, 2)) == (80.0, 60.0)


def test_forecast_temps_for_date_no_fallback():
    fl = [_entry("2026-11-01T18:00:00+00:00", 75, 55)]
    assert eft.select_forecast_for_date(fl, date(2026, 11, 5)) is None
    # missing low -> None (never half a pair)
    assert eft.select_forecast_for_date(
        [{"datetime": "2026-11-05T18:00:00+00:00", "temperature": 70}],
        date(2026, 11, 5)) is None
    assert eft.select_forecast_for_date([], date(2026, 11, 5)) is None
    assert eft.select_forecast_for_date(None, date(2026, 11, 5)) is None


def test_forecast_temps_for_date_dst_day():
    """DST end 2026-11-01: 05:00Z = 00:00 CDT (11-01), 06:00Z next day =
    00:00 CST (11-02). A UTC-date selector would mis-assign the first."""
    fl = [_entry("2026-11-01T05:00:00+00:00", 70, 50),
          _entry("2026-11-02T06:00:00+00:00", 72, 52)]
    assert eft.select_forecast_for_date(fl, date(2026, 11, 1)) == (70.0, 50.0)
    assert eft.select_forecast_for_date(fl, date(2026, 11, 2)) == (72.0, 52.0)
    # 2026-11-02T03:00Z is 21:00 CST on 11-01 -> local date 11-01
    assert eft.select_forecast_for_date(
        [_entry("2026-11-02T03:00:00+00:00", 66, 44)], date(2026, 11, 1)) == (66.0, 44.0)


def test_temp_feature_is_high_low_midpoint():
    assert eft.temp_feature((80.0, 61.0)) == 70.5
    assert eft.temp_feature(None) is None


class _Services:
    def __init__(self, forecasts, eid="weather.x"):
        self.calls = []
        self._f = forecasts
        self._eid = eid

    async def async_call(self, domain, service, data, blocking=False,
                         return_response=False):
        self.calls.append((domain, service, data))
        return {self._eid: {"forecast": self._f}}


def _ec(db=None, forecasts=None, solcast=68.2, tou=None):
    c = EnergyCoordinator.__new__(EnergyCoordinator)
    c.hass = SimpleNamespace(
        data={_DOMAIN: {"database": db}},
        services=_Services(forecasts or []),
        config=SimpleNamespace(components=set()),
    )
    c._weather_entity = "weather.x"
    c._tou = tou or _engine()
    c._battery = SimpleNamespace(solcast_tomorrow=solcast)
    p = ef.DailyEnergyPredictor(MagicMock())
    p.hass.states.get = MagicMock(return_value=None)
    c._predictor = p
    return c


def test_ec_forecast_temps_for_date_fetches_full_list_once_per_ttl():
    """The EC method resolves ANY date from one full-list fetch (the WPM
    keeps only forecasts[0]) and re-fetches only after the TTL."""
    fl = [_entry("2026-11-01T18:00:00+00:00", 75, 55),
          _entry("2026-11-02T18:00:00+00:00", 80, 60)]
    c = _ec(forecasts=fl)
    assert _run(c.async_forecast_temps_for_date(date(2026, 11, 2))) == (80.0, 60.0)
    assert _run(c.async_forecast_temps_for_date(date(2026, 11, 1))) == (75.0, 55.0)
    assert len(c.hass.services.calls) == 1
    assert c.hass.services.calls[0] == (
        "weather", "get_forecasts", {"entity_id": "weather.x", "type": "daily"})
    assert _run(c.async_forecast_temps_for_date(date(2026, 11, 9))) is None


def test_set_predictor_shadow_temp_feeds_today_forecast():
    fl = [_entry("2026-11-02T18:00:00+00:00", 80, 61)]
    c = _ec(forecasts=fl)
    _run(c._set_predictor_shadow_temp(datetime(2026, 11, 2, 9, 0, tzinfo=CHI)))
    assert c._predictor._shadow_temp == 70.5
    # no entry for today -> None (no fallback to the current temperature)
    _run(c._set_predictor_shadow_temp(datetime(2026, 11, 4, 9, 0, tzinfo=CHI)))
    assert c._predictor._shadow_temp is None


# --- INV-SHADOW-1 -----------------------------------------------------------


def _predictor_with_states(current_temp=88.0):
    states = {
        "weather.w": SimpleNamespace(state="sunny", attributes={"temperature": current_temp}),
        "sensor.solcast_today": SimpleNamespace(state="60.0", attributes={}),
    }
    hass = MagicMock()
    hass.states.get = lambda eid: states.get(eid)
    p = ef.DailyEnergyPredictor(
        hass, solcast_today_entity="sensor.solcast_today", weather_entity="weather.w")
    for d in range(7):
        p._consumption_history[d].extend([150.0, 130.0])
    return p


def test_shadow_on_consumed_value_byte_identical(monkeypatch):
    """Shadow ON: the consumed prediction, its temperature and the net are
    identical whether D8 supplies a shadow temp or not; only shadow_* move."""
    monkeypatch.setattr(ef, "CONF_R1_ESTIMATOR_SHADOW_ONLY", True)
    now = datetime(2026, 11, 2, 7, 0, tzinfo=CHI)
    a = _predictor_with_states()
    a._do_prediction(now)
    b = _predictor_with_states()
    b.set_shadow_temp(45.0)
    b._do_prediction(now)
    pa, pb = a._get_current_prediction(), b._get_current_prediction()
    for k in ("predicted_consumption_kwh", "predicted_net_kwh",
              "predicted_production_kwh", "battery_full_time",
              "predicted_consumption_source", "adjustment_factor"):
        assert pa[k] == pb[k], k
    assert a._prediction_temperature == b._prediction_temperature == 88.0
    # legacy DOW 140 x temp factor 1.15 (85 < 88 <= 95) = 161.0 consumed
    assert pa["predicted_consumption_kwh"] == 161.0
    assert pa["shadow_predicted_consumption_kwh"] is None
    assert pa["shadow_missing_input"] == "forecast_temp"
    # V1 fall, 45 F: hdd 20 -> 92.4181 + 0.4981*20 + 2.0104 + 18.5788 = 122.9693
    assert pb["shadow_predicted_consumption_kwh"] == pytest.approx(122.97, abs=0.01)
    assert pb["shadow_temp_used"] == 45.0 and pb["shadow_model_arm"] == "v1"


def test_shadow_temp_not_passed_to_legacy_arm(monkeypatch):
    """Legacy (temp regression) follows the CURRENT temp only: base 100,
    coeff 2, current 90, history 140 -> (100 + 2*18)*0.7 + 140*0.3 = 137.2,
    for any shadow temp."""
    monkeypatch.setattr(ef, "CONF_R1_ESTIMATOR_SHADOW_ONLY", True)
    now = datetime(2026, 11, 2, 7, 0, tzinfo=CHI)
    out = []
    for shadow in (None, 50.0, 99.0):
        p = _predictor_with_states(current_temp=90.0)
        p.set_temp_regression(100.0, 2.0)
        p.set_shadow_temp(shadow)
        p._do_prediction(now)
        out.append((p._predicted_consumption_kwh, p._prediction_temperature))
    assert out == [(137.2, 90.0)] * 3


# --- wire-in: the decision-cycle body calls the forecast tick ----------------


class _Stop(Exception):
    pass


def test_decision_cycle_body_calls_forecast_tick():
    """Enclosing-method anchor: the REAL _decision_cycle_body reaches
    _forecast_tick, which runs BOTH hooks. Deleting the call -> RED."""
    c = EnergyCoordinator.__new__(EnergyCoordinator)
    c.hass = SimpleNamespace(data={})
    c._maybe_reset_daily = lambda: None
    c._tou = SimpleNamespace(get_current_period=lambda *a: "off_peak",
                             get_season=lambda *a: "shoulder",
                             check_period_transition=lambda: None)
    c._ev = SimpleNamespace(current_charging_load_w=lambda: 0)
    c._battery = SimpleNamespace(determine_mode=lambda *a, **k: {"actions": []},
                                 _offpeak_drain_branch_target=None)
    c._soc_untrusted_from_battery = lambda: False
    c._stamp_ev_start_soc_verdict = lambda v: None
    c._ev_start_hold_label = lambda **k: None
    for n in ("_outage_ledger_tick", "_inclement_rows_tick",
              "_storm_guard_tick", "_grid_buy_notify_tick"):
        setattr(c, n, lambda: None)

    async def _noop(*a, **k):
        return None
    c._account_arbitrage_cycle = _noop
    c._refresh_arbitrage_status_cache = _noop
    seen = []

    async def _shadow(now):
        seen.append("shadow")

    async def _tomorrow(now):
        seen.append("tomorrow")
    c._set_predictor_shadow_temp = _shadow
    c._async_refresh_tomorrow_forecast = _tomorrow

    def _halt():
        raise _Stop
    c._is_any_evse_charging = _halt
    with contextlib.suppress(_Stop):
        _run(c._decision_cycle_body())
    assert seen == ["shadow", "tomorrow"]


def test_forecast_tick_isolates_failures():
    c = EnergyCoordinator.__new__(EnergyCoordinator)
    seen = []

    async def _boom(now):
        raise RuntimeError("x")

    async def _ok(now):
        seen.append(now)
    c._set_predictor_shadow_temp = _boom
    c._async_refresh_tomorrow_forecast = _ok
    _run(c._forecast_tick(1))
    assert seen == [1]


# ===========================================================================
# D9 — regression (pure function, selector, v2, hvac_zone)
# ===========================================================================


def test_consumption_model_parity_with_compute_v1():
    """_compute_v1 is a thin wrapper. Oracle (V1, July 15, 82 F): cdd 17 ->
    92.4181 + 2.1976*17 + 18.3129 + 18.5788 = 166.669."""
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        CONSUMPTION_REGRESSION_V1,
    )
    p = ef.DailyEnergyPredictor(MagicMock())
    for now, temp in ((datetime(2026, 7, 15, 12, tzinfo=CHI), 82.0),
                      (datetime(2026, 1, 9, 8, tzinfo=CHI), 40.0),
                      (datetime(2026, 4, 1, 23, tzinfo=CHI), 66.0)):
        assert p._compute_v1(now, temp) == ef.compute_consumption_regression(
            now.date(), temp, CONSUMPTION_REGRESSION_V1)
    tot, base, ev, src = p._compute_v1(datetime(2026, 7, 15, 12, tzinfo=CHI), 82.0)
    assert tot == pytest.approx(166.669, abs=1e-4)
    assert ev == pytest.approx(18.5788)
    assert p._compute_v1(datetime(2026, 7, 15, tzinfo=CHI), None)[0] is None


def test_consumption_model_season_from_target_date():
    """Now = Nov 30 evening, target Dec 1 -> WINTER coefficients. V1 at 60 F:
    Nov 30 (fall) 115.4978, Dec 1 (winter) 113.4874."""
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        CONSUMPTION_REGRESSION_V1 as V1,
    )
    assert ef.compute_consumption_regression(date(2026, 11, 30), 60.0, V1)[0] == \
        pytest.approx(115.4978, abs=1e-4)
    assert ef.compute_consumption_regression(date(2026, 12, 1), 60.0, V1)[0] == \
        pytest.approx(113.4874, abs=1e-4)


def test_consumption_regression_v2_shape():
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_const as c,
    )
    v2 = c.CONSUMPTION_REGRESSION_V2
    for k in ("base", "cdd_coeff", "hdd_coeff", "season_spring", "season_summer",
              "season_fall", "season_winter", "hdd_base_f", "cdd_base_f",
              "ev_term_kwh", "ev_era_start"):
        assert k in v2, k
    assert v2["ev_term_kwh"] == 0.0           # EV double count dropped
    assert v2["holdout_mae_kwh"] > v2["v1_holdout_mae_kwh"]   # gate failed
    assert c.CONSUMPTION_REGRESSION_ACTIVE == "v1"            # so v1 stays


def test_v2_runtime_matches_fit_script_predictions():
    """Three Oct holdout days printed by `fit_consumption_regression.py
    --version v2` (date, (high+low)/2, kWh)."""
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        CONSUMPTION_REGRESSION_V2 as V2,
    )
    for d, t, kwh in ((date(2026, 10, 1), 78.5, 163.3496),
                      (date(2026, 10, 2), 74.5, 152.7772),
                      (date(2026, 10, 4), 74.0, 151.4557)):
        assert ef.compute_consumption_regression(d, t, V2)[0] == pytest.approx(kwh, abs=0.01)


def test_consumption_model_selector_v1_rollback(monkeypatch):
    """The shadow arm follows CONSUMPTION_REGRESSION_ACTIVE (Nov 2, 70 F)."""
    p = ef.DailyEnergyPredictor(MagicMock())
    p.set_shadow_temp(70.0)
    now = datetime(2026, 11, 2, 7, tzinfo=CHI)
    monkeypatch.setattr(ef, "CONSUMPTION_REGRESSION_ACTIVE", "v2")
    # V2 fall: 84.932 + 2.6431*5 + 42.7358 = 140.8833
    assert p._compute_shadow_arm(now)[0] == pytest.approx(140.8833, abs=1e-4)
    monkeypatch.setattr(ef, "CONSUMPTION_REGRESSION_ACTIVE", "v1")
    # V1 fall: 92.4181 + 2.1976*5 + 2.0104 + 18.5788 = 123.9953
    assert p._compute_shadow_arm(now)[0] == pytest.approx(123.9953, abs=1e-4)


_HZ = {"zones": (
    {"energy": "e1", "indoor": "i1", "a": 10.4088, "b_cool": 1.8013, "c_heat": 0.0},
    {"energy": "e2", "indoor": "i2", "a": 8.1831, "b_cool": 1.4297, "c_heat": 0.0},
    {"energy": "e3", "indoor": "i3", "a": 3.7732, "b_cool": 1.0803, "c_heat": 0.5},
), "indoor_trailing_days": 7, "base_trailing_days": 14}


def test_hvac_zone_arm_sums_zones_plus_base():
    """85 F, indoor 76/77/78, base 60: 26.6205 + 19.6207 + 11.3353 + 60."""
    assert eft.hvac_zone_consumption(_HZ, 85.0, [76.0, 77.0, 78.0], 60.0) == \
        pytest.approx(117.5765, abs=1e-4)
    # 70 F under zone 3's 78 F: heating term 0.5*8 = 4 on zone 3 only:
    # 10.4088 + 8.1831 + 3.7732 + 4.0 + 60 = 86.3651
    assert eft.hvac_zone_consumption(_HZ, 70.0, [76.0, 77.0, 78.0], 60.0) == \
        pytest.approx(86.3651, abs=1e-4)


def test_hvac_zone_missing_input_is_none():
    assert eft.hvac_zone_consumption(_HZ, None, [76.0, 77.0, 78.0], 60.0) is None
    assert eft.hvac_zone_consumption(_HZ, 85.0, [76.0, None, 78.0], 60.0) is None
    assert eft.hvac_zone_consumption(_HZ, 85.0, [76.0, 77.0, 78.0], None) is None


def test_hvac_zone_constants_are_hvac_zone_thermostats():
    """House zones != HVAC zones: the indoor inputs are the three zone
    THERMOSTAT readings, and ac1/ac_2/ac_3 map to zones 1/2/3 (operator
    2026-11-02)."""
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        HVAC_ZONE_REGRESSION_V1 as H,
    )
    pairs = [(z["energy"], z["indoor"]) for z in H["zones"]]
    assert pairs == [
        ("sensor.span_panel_ac1_consumed_energy", "sensor.office_b_zone_1_temperature"),
        ("sensor.span_panel_ac_2_consumed_energy", "sensor.up_hallway_zone_2_temperature"),
        ("sensor.span_panel_ac_3_consumed_energy", "sensor.back_hallway_zone_3_temperature"),
    ]


def test_bucket_forecast_inputs_local_days_and_partial_drop():
    """kWh = sum of hourly change by LOCAL date; temp = (max+min)/2; a day
    with < 20 hourly rows is dropped."""
    c = EnergyCoordinator.__new__(EnergyCoordinator)
    start = datetime(2026, 10, 20, 5, 0, tzinfo=timezone.utc)   # 00:00 CDT
    e_rows = [{"start": start + timedelta(hours=h), "change": 1.5} for h in range(24)]
    e_rows += [{"start": start + timedelta(days=1, hours=h), "change": 1.0}
               for h in range(10)]                               # partial day
    t_rows = [{"start": start + timedelta(hours=h), "max": 70 + h % 5, "min": 66}
              for h in range(24)]
    out = c._bucket_forecast_inputs({
        "sensor.span_panel_ac1_consumed_energy": e_rows,
        "sensor.office_b_zone_1_temperature": t_rows,
    })
    assert out["sensor.span_panel_ac1_consumed_energy"] == {date(2026, 10, 20): 36.0}
    assert out["sensor.office_b_zone_1_temperature"] == {date(2026, 10, 20): 70.0}


# ===========================================================================
# D3 — Option A net tomorrow
# ===========================================================================


class _FakeDB:
    def __init__(self, daily=None, eh=None):
        self.daily = list(daily or [])
        self.eh = list(eh or [])
        self.batches: list[list[tuple]] = []

    async def get_energy_daily_balance_recent(self, days=30):
        return self.daily[-days:]

    async def get_energy_history_kwh_rows(self, since):
        self.since = since
        return list(self.eh)

    async def log_forecast_batch(self, rows):
        self.batches.append(list(rows))
        return len(rows)

    async def get_forecast_log_joined(self, since):
        return []


def _daily(n=14, end=date(2026, 11, 1)):
    # each day: (imp 50 - exp 10) - (cons 100 - solar 65) = +5 kWh gap
    return [{"date": (end - timedelta(days=k)).isoformat(), "consumption_kwh": 100.0,
             "solar_production_kwh": 65.0, "import_kwh": 50.0, "export_kwh": 10.0}
            for k in range(n - 1, -1, -1)]


_FL = [_entry("2026-11-02T18:00:00+00:00", 80, 60),
       _entry("2026-11-03T18:00:00+00:00", 80, 60),
       _entry("2026-03-09T17:00:00+00:00", 80, 60)]


def _tomorrow(now, solcast=68.2, forecasts=_FL, daily=None):
    c = _ec(db=_FakeDB(daily=_daily() if daily is None else daily),
            forecasts=forecasts, solcast=solcast)
    _run(c._async_refresh_tomorrow_forecast(now))
    return c


def test_net_tomorrow_local_date_after_1800():
    """19:30 CST Sunday 11-01 -> target Monday 11-02 (UTC is already 11-02,
    so a UTC target would be 11-03). V1 fall at 70 F = 123.9953; net =
    123.9953 - 68.2 + 5 = 60.7953."""
    c = _tomorrow(datetime(2026, 11, 1, 19, 30, tzinfo=CHI))
    f = c.tomorrow_forecast
    assert f["target_date"] == "2026-11-02"
    assert f["temp_used"] == 70.0 and f["model_arm"] == "v1"
    assert f["consumption_kwh"] == 124.0
    assert f["bias_kwh"] == 5.0
    assert f["raw_net_kwh"] == pytest.approx(60.8)
    assert f["solar_kwh"] == 68.2 and f["missing_input"] is None


def test_net_tomorrow_dst_boundary():
    c = _tomorrow(datetime(2026, 3, 8, 23, 30, tzinfo=CHI))
    assert c.tomorrow_forecast["target_date"] == "2026-03-09"


def test_net_tomorrow_solcast_sensitivity():
    now = datetime(2026, 11, 1, 19, 30, tzinfo=CHI)
    lo = _tomorrow(now, solcast=20.0).tomorrow_forecast["raw_net_kwh"]
    hi = _tomorrow(now, solcast=90.0).tomorrow_forecast["raw_net_kwh"]
    assert lo - hi == pytest.approx(70.0, abs=0.11)


def test_net_tomorrow_missing_forecast_temp_is_none():
    now = datetime(2026, 11, 1, 19, 30, tzinfo=CHI)
    f = _tomorrow(now, forecasts=[_entry("2026-11-01T18:00:00+00:00", 80, 60)]).tomorrow_forecast
    assert f["raw_net_kwh"] is None and f["missing_input"] == "forecast_temp"
    f2 = _tomorrow(now, solcast=None).tomorrow_forecast
    assert f2["raw_net_kwh"] is None and f2["missing_input"] == "solcast"


def test_net_bias_trailing_window_and_kill_switch():
    rows = _daily(20)
    rows[-1] = dict(rows[-1], import_kwh=80.0)   # newest gap = 35
    # newest 14: 13 x 5 + 35 = 100 -> 7.142857
    assert eft.net_bias(rows, 14) == pytest.approx(100 / 14)
    assert eft.net_bias(rows, 0) == 0.0
    assert eft.net_bias([{"date": "x", "import_kwh": None}], 14) == 0.0


def test_tomorrow_forecast_rate_limited():
    c = _ec(db=_FakeDB(daily=_daily()), forecasts=_FL)
    t0 = datetime(2026, 11, 1, 10, 0, tzinfo=CHI)
    _run(c._async_refresh_tomorrow_forecast(t0))
    c._battery.solcast_tomorrow = 10.0
    _run(c._async_refresh_tomorrow_forecast(t0 + timedelta(seconds=899)))
    assert c.tomorrow_forecast["solar_kwh"] == 68.2
    _run(c._async_refresh_tomorrow_forecast(t0 + timedelta(seconds=900)))
    assert c.tomorrow_forecast["solar_kwh"] == 10.0


def _agg():
    from custom_components.universal_room_automation import aggregation
    return aggregation


def _sensor(cls, ec, db=None):
    s = cls.__new__(cls)
    s.hass = SimpleNamespace(data={_DOMAIN: {
        "database": db or MagicMock(),
        "coordinator_manager": SimpleNamespace(coordinators={"energy": ec})}})
    s._get_config = lambda k, d=None: d
    s._cached_value = None
    s._cached_confidence = 0
    s._cache_time = None
    s._cached_raw_net_kwh = None
    s._cached_forecast_temp = None
    return s


def test_tomorrow_sensor_reads_ec_option_a_snapshot():
    agg = _agg()
    ec = SimpleNamespace(tomorrow_forecast={
        "raw_net_kwh": 60.8, "target_date": "2026-11-02", "consumption_kwh": 124.0,
        "solar_kwh": 68.2, "bias_kwh": 5.0, "temp_used": 70.0, "model_arm": "v1",
        "method": "v1_solcast", "missing_input": None})
    s = _sensor(agg.PredictedEnergyTomorrowSensor, ec)
    _run(s.async_update())
    a = s.extra_state_attributes
    assert s.native_value == 60.8 and a["raw_net_kwh"] == 60.8
    assert a["target_date"] == "2026-11-02" and a["solar_kwh"] == 68.2
    assert a["method"] == "v1_solcast" and "confidence" not in a


# ===========================================================================
# D4 — per-period kWh shares x live TOU rates
# ===========================================================================

_MIX = {"off_peak": {"import_kwh": 90.0, "export_kwh": 30.0},
        "mid_peak": {"import_kwh": 10.0, "export_kwh": 0.0}}


def test_predicted_cost_mix_oracle():
    """50 x (0.9 x 0.085957 + 0.1 x 0.128918) = 4.512655."""
    cost, meta = eft.price_net_kwh(50.0, _MIX, _engine(), date(2026, 11, 2), 3, 14)
    assert cost == pytest.approx(4.512655, abs=1e-6)
    assert meta["rate_source"] == "period_mix_14d"
    assert sum(meta["import_shares"].values()) == pytest.approx(1.0)


def test_predicted_cost_follows_tou_rate_change():
    """Off-peak effective -> 0.10 (base 0.057524): 50 x (0.09 + 0.0128918)."""
    cost, _ = eft.price_net_kwh(50.0, _MIX, _engine(off_import=0.057524),
                                date(2026, 11, 2), 3, 14)
    assert cost == pytest.approx(5.14459, abs=1e-5)


def test_predicted_cost_export_uses_engine_rate():
    """Net -20, export shares {off_peak: 1.0} -> -20 x 0.043481; with an
    engine export of 0.05 it follows (-1.0) — never a config constant."""
    cost, _ = eft.price_net_kwh(-20.0, _MIX, _engine(), date(2026, 11, 2), 3, 14)
    assert cost == pytest.approx(-0.86962, abs=1e-6)
    cost2, _ = eft.price_net_kwh(-20.0, _MIX, _engine(export=0.05), date(2026, 11, 2), 3, 14)
    assert cost2 == pytest.approx(-1.0, abs=1e-9)


def test_predicted_cost_fallback_hour_weighted_not_instant():
    """< 3 days of mix: the day's hour-weighted rate (20 h off, 4 h mid):
    10 x (20 x 0.085957 + 4 x 0.128918) / 24 = 0.9311717."""
    cost, meta = eft.price_net_kwh(10.0, _MIX, _engine(), date(2026, 11, 2), 3, 2)
    assert cost == pytest.approx(0.9311717, abs=1e-6)
    assert meta["rate_source"] == "hour_weighted_day"


def test_predicted_cost_not_instant_rate():
    """Identical inputs at 16:59 and 17:01 local -> identical cost."""
    a = _tomorrow(datetime(2026, 11, 1, 16, 59, tzinfo=CHI)).tomorrow_forecast
    b = _tomorrow(datetime(2026, 11, 1, 17, 1, tzinfo=CHI)).tomorrow_forecast
    assert a["cost"] is not None and a["cost"] == b["cost"]
    # no mix -> hour-weighted on the TARGET day: 60.7953 x 0.09311717 = 5.66
    assert a["cost"] == pytest.approx(5.66, abs=0.005)


def test_period_kwh_mix_from_energy_history_local_buckets():
    """23:30Z on 11-02 is 17:30 CST -> mid_peak; 22:30Z is 16:30 -> off_peak.
    kWh = kW x dt_h."""
    rows = [("2026-11-02T23:30:00", 4.0, 0.0, 0.25),
            ("2026-11-02T22:30:00", 2.0, 1.0, 0.25),
            ("2026-11-03T05:30:00", 1.0, 0.0, 0.5)]   # 23:30 CST 11-02
    mix, days = eft.bucket_period_mix(rows, _engine())
    assert mix["mid_peak"] == {"import_kwh": 1.0, "export_kwh": 0.0}
    assert mix["off_peak"] == {"import_kwh": 1.0, "export_kwh": 0.25}
    assert days == 1


def test_refresh_period_mix_reads_whole_local_days():
    db = _FakeDB(eh=[("2026-10-25T23:30:00", 4.0, 0.0, 0.25),
                     ("2026-11-02T07:00:00", 9.0, 0.0, 0.25)])   # today (local 11-02 01:00)
    c = _ec(db=db)
    _run(c._refresh_period_mix(datetime(2026, 11, 2, 9, 0, tzinfo=CHI)))
    # since = local midnight 10-19 (CDT) = 05:00Z; today's row excluded
    assert db.since == "2026-10-19T05:00:00"
    assert c._period_mix == {"mid_peak": {"import_kwh": 1.0, "export_kwh": 0.0}}
    assert c._period_mix_days == 1


def test_predicted_today_reads_ec_forecast():
    """Today = -(EC predicted_net_kwh) (EC: + = export) priced by the EC."""
    agg = _agg()
    ec = SimpleNamespace(forecast_today={"predicted_net_kwh": -30.0},
                         price_net_kwh=lambda net, day: (net * 0.1, {"rate_source": "x"}))
    e = _sensor(agg.PredictedEnergyTodaySensor, ec)
    _run(e.async_update())
    assert e.extra_state_attributes["raw_net_kwh"] == 30.0
    assert e.extra_state_attributes["method"] == "ec_forecast_today"
    cs = _sensor(agg.PredictedCostTodaySensor, ec)
    _run(cs.async_update())
    assert cs._cached_value == 3.0
    assert cs.extra_state_attributes["rate_source"] == "x"


def test_predicted_cost_tomorrow_prices_target_day():
    agg = _agg()
    seen = []

    def _price(net, day):
        seen.append(day)
        return net * 0.2, {}
    # a target far from the wall clock (never coincides with today+1)
    ec = SimpleNamespace(tomorrow_forecast={"raw_net_kwh": 10.0,
                                            "target_date": "2031-06-15"},
                         price_net_kwh=_price)
    s = _sensor(agg.PredictedCostTomorrowSensor, ec)
    _run(s.async_update())
    assert s._cached_value == 2.0 and seen == [date(2031, 6, 15)]


# ===========================================================================
# D5 — prediction log
# ===========================================================================


def test_forecast_log_one_row_per_day_per_arm():
    """Before 21:00 nothing is logged; at/after 21:00 one batch with every
    arm, exactly one consumed=1 (dow_legacy, shadow on); no re-log the same
    day; the next day logs its own target."""
    db = _FakeDB(daily=_daily())
    c = _ec(db=db, forecasts=_FL)
    _run(c._async_refresh_tomorrow_forecast(datetime(2026, 11, 1, 20, 50, tzinfo=CHI)))
    assert db.batches == []
    _run(c._async_refresh_tomorrow_forecast(datetime(2026, 11, 1, 21, 5, tzinfo=CHI)))
    _run(c._async_refresh_tomorrow_forecast(datetime(2026, 11, 1, 21, 25, tzinfo=CHI)))
    _run(c._async_refresh_tomorrow_forecast(datetime(2026, 11, 2, 21, 5, tzinfo=CHI)))
    assert len(db.batches) == 2
    for batch, target in zip(db.batches, ("2026-11-02", "2026-11-03")):
        assert {r[0] for r in batch} == {target}
        assert sorted(r[1] for r in batch) == [
            "dow_legacy", "hvac_zone", "v1", "v2", "weekly_persistence"]
        assert [r[1] for r in batch if r[8] == 1] == ["dow_legacy"]
    v1 = next(r for r in db.batches[0] if r[1] == "v1")
    assert v1[3] == pytest.approx(123.9953, abs=1e-4) and v1[7] == 70.0


async def _real_db(tmp_path):
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    from runtime_harness import StubHass
    db = UniversalRoomDatabase(StubHass(config_dir=str(tmp_path)))
    assert await db.initialize()
    await db.start_write_worker()
    return db


@pytest.mark.asyncio
async def test_forecast_log_table_ddl_from_production(tmp_path):
    """The production init creates the table; the PK keeps one row per
    (target_date, arm) under INSERT OR REPLACE."""
    db = await _real_db(tmp_path)
    try:
        assert await db.log_forecast_batch([
            ("2026-11-02", "v1", "t1", 120.0, 60.0, 65.0, 6.0, 70.0, 0)]) == 1
        assert await db.log_forecast_batch([
            ("2026-11-02", "v1", "t2", 121.0, 60.0, 66.0, 6.1, 70.0, 0)]) == 1
        con = sqlite3.connect(db.db_file)
        rows = con.execute("SELECT target_date, arm, made_at FROM energy_forecast_log").fetchall()
        con.close()
        assert rows == [("2026-11-02", "v1", "t2")]
    finally:
        await db.stop_write_worker()


@pytest.mark.asyncio
async def test_forecast_log_single_batch_write(tmp_path):
    db = await _real_db(tmp_path)
    try:
        n_before = db._write_queue.qsize()
        acquisitions = []
        orig = db._db

        def _counting():
            acquisitions.append(1)
            return orig()
        db._db = _counting
        rows = [("2026-11-02", a, "t", 1.0, 2.0, 3.0, 0.3, 70.0, int(a == "dow_legacy"))
                for a in ("v1", "v2", "hvac_zone", "dow_legacy", "weekly_persistence")]
        assert await db.log_forecast_batch(rows) == 5
        assert acquisitions == [1] and n_before == 0
    finally:
        await db.stop_write_worker()


@pytest.mark.asyncio
async def test_forecast_log_accuracy_join_per_arm(tmp_path):
    db = await _real_db(tmp_path)
    try:
        await db.log_forecast_batch([
            ("2026-10-30", "v1", "t", 110.0, 50.0, 60.0, 5.0, 70.0, 0),
            ("2026-10-31", "v1", "t", 90.0, 50.0, 40.0, 4.0, 70.0, 0),
            ("2026-10-31", "dow_legacy", "t", 150.0, 50.0, 100.0, 9.0, 70.0, 1),
        ])
        con = sqlite3.connect(db.db_file)
        con.execute("INSERT INTO energy_daily (date, consumption_kwh, import_kwh, "
                    "export_kwh, net_cost) VALUES ('2026-10-30', 100, 70, 10, 6.0)")
        con.execute("INSERT INTO energy_daily (date, consumption_kwh, import_kwh, "
                    "export_kwh, net_cost) VALUES ('2026-10-31', 100, 60, 10, 5.0)")
        con.commit()
        con.close()
        rows = await db.get_forecast_log_joined("2026-10-01")
    finally:
        await db.stop_write_worker()
    acc = eft.forecast_accuracy(rows, date(2026, 11, 2), "v1")
    # v1 errors: +10, -10 -> MAE 10, bias 0; net: 60-60=0, 40-50=-10 -> 5;
    # cost: 5-6=-1, 4-5=-1 -> 1
    assert acc["v1"] == {"mae_7d_kwh": 10.0, "mae_30d_kwh": 10.0,
                         "bias_30d_kwh": 0.0, "net_mae_30d_kwh": 5.0,
                         "cost_mae_30d": 1.0, "log_rows": 2}
    assert acc["dow_legacy"] == {"mae_7d_kwh": 50.0, "mae_30d_kwh": 50.0,
                                 "bias_30d_kwh": 50.0}


def test_forecast_accuracy_excludes_today_and_unscored():
    rows = [{"arm": "v1", "target_date": "2026-11-02", "pred_consumption_kwh": 1.0,
             "consumption_kwh": 100.0},
            {"arm": "v1", "target_date": "2026-11-01", "pred_consumption_kwh": 1.0,
             "consumption_kwh": None}]
    acc = eft.forecast_accuracy(rows, date(2026, 11, 2), "v2")
    assert acc["v1"]["mae_30d_kwh"] is None


def test_consumption_arms_values():
    """Arms for target 11-02 at 70 F (shadow-on house):
    v1 123.9953; v2 84.932 + 2.6431*5 + 42.7358 = 140.8833;
    dow_legacy: empty history -> 45 x 0.9 (55 < 70 <= 75) x adj 1.0 = 40.5;
    weekly_persistence = consumption on 10-26 (123.0, other days 100);
    hvac_zone None without recorder inputs."""
    c = _ec(db=_FakeDB())
    daily = [dict(r, consumption_kwh=123.0) if r["date"] == "2026-10-26" else r
             for r in _daily()]
    arms = c._consumption_arms(date(2026, 11, 2), 70.0, daily)
    assert arms["v1"]["kwh"] == pytest.approx(123.9953, abs=1e-4)
    assert arms["v2"]["kwh"] == pytest.approx(140.8833, abs=1e-4)
    assert arms["dow_legacy"]["kwh"] == pytest.approx(40.5)
    assert arms["weekly_persistence"]["kwh"] == 123.0
    assert arms["hvac_zone"] == {"kwh": None, "missing": "hvac_zone_history"}


def test_consumption_arms_hvac_zone_from_recorder_inputs():
    """Recorder inputs: indoor 76/77/78 every day, AC 10/8/2 kWh/day,
    consumption 100 -> base_nonhvac 80. 85 F: zones (constants
    HVAC_ZONE_REGRESSION_V1) 26.6205 + 19.6207 + 11.3353 = 57.5765 + 80."""
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        HVAC_ZONE_REGRESSION_V1 as H,
    )
    days = [date(2026, 11, 1) - timedelta(days=k) for k in range(14)]
    z = H["zones"]
    c = _ec(db=_FakeDB())
    c._forecast_daily_inputs = {
        z[0]["indoor"]: {d: 76.0 for d in days}, z[1]["indoor"]: {d: 77.0 for d in days},
        z[2]["indoor"]: {d: 78.0 for d in days},
        z[0]["energy"]: {d: 10.0 for d in days}, z[1]["energy"]: {d: 8.0 for d in days},
        z[2]["energy"]: {d: 2.0 for d in days},
    }
    arms = c._consumption_arms(date(2026, 11, 2), 85.0, _daily())
    assert arms["hvac_zone"]["kwh"] == pytest.approx(137.5765, abs=1e-4)


def test_tomorrow_refresh_schedules_recorder_inputs_task():
    """Wire-in: the tomorrow refresh schedules ONE background recorder
    query (recorder loaded) whose result lands, bucketed, in
    _forecast_daily_inputs; a second refresh inside the interval does not
    re-query."""
    c = _ec(db=_FakeDB(daily=_daily()), forecasts=_FL)
    c.hass.config.components = {"recorder"}
    tasks, queries = [], []

    def _bg(coro, name):
        t = asyncio.ensure_future(coro)
        tasks.append(t)
        return t
    c.hass.async_create_background_task = _bg
    start = datetime(2026, 10, 31, 5, 0, tzinfo=timezone.utc)

    async def _q(start_utc):
        queries.append(start_utc)
        return {"sensor.span_panel_ac1_consumed_energy": [
            {"start": start + timedelta(hours=h), "change": 0.5} for h in range(24)]}
    c._query_forecast_input_statistics = _q

    async def _go():
        await c._async_refresh_tomorrow_forecast(datetime(2026, 11, 1, 10, tzinfo=CHI))
        await asyncio.gather(*tasks)
        c._tomorrow_forecast_last = None
        await c._async_refresh_tomorrow_forecast(datetime(2026, 11, 1, 10, 30, tzinfo=CHI))
        await asyncio.gather(*tasks)
    _run(_go())
    assert len(queries) == 1
    assert c._forecast_daily_inputs["sensor.span_panel_ac1_consumed_energy"] == {
        date(2026, 10, 31): 12.0}
    assert c._forecast_inputs_inflight is False
