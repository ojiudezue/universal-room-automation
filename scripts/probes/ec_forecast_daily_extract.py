#!/usr/bin/env python3
"""EC-COST-AND-FORECAST-MATH-1 Build 2 D0/D9 — daily input extract (read-only).

Run on the HA host:
    ssh ha "python3 -" < scripts/probes/ec_forecast_daily_extract.py \
        > data/energy_fit/ec_forecast_daily_inputs.csv

Emits one CSV row per LOCAL (America/Chicago) date with:
  energy_daily (URA DB): consumption, solar, import, export
  recorder long-term statistics (hourly):
    outdoor temp max/min  sensor.thermostat_bryant_wifi_backhallway_outdoor_temperature
      -> temp_mid = (max + min) / 2  (the SAME proxy D8 feeds at run time:
         (forecast high + forecast low) / 2)
    HVAC-zone thermostat temps (thermostat readings, NOT house-zone averages):
      sensor.office_b_zone_1_temperature, sensor.up_hallway_zone_2_temperature,
      sensor.back_hallway_zone_3_temperature  -> daily (max+min)/2
    AC circuit kWh (operator 2026-11-02: ac1 = zone 1, ac_2 = zone 2,
      ac_3 = zone 3)
    EV kWh: car_charger through 2026-10-12, garage_a_evse from 2026-10-13
      (garage_b rejected as junk, AUDIT_forecast_inputs §2)
    solcast_tomorrow_prev_eve: Solcast "forecast tomorrow" state at the end
      of the 20:00 local hour of the PREVIOUS local date (what a ~21:00
      forecast saw)
Read-only: both DBs are opened with mode=ro.
"""
import csv
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
REC = "file:/config/home-assistant_v2.db?mode=ro"
URA = "file:/config/universal_room_automation/data/universal_room_automation.db?mode=ro"
MIN_HOURS_FOR_TEMP = 20
MAX_WH_PER_HOUR = 20000  # a larger hourly delta is a counter reset/glitch
EV_SWITCH = date(2026, 10, 13)

TEMPS = {
    "out": "sensor.thermostat_bryant_wifi_backhallway_outdoor_temperature",
    "in1": "sensor.office_b_zone_1_temperature",
    "in2": "sensor.up_hallway_zone_2_temperature",
    "in3": "sensor.back_hallway_zone_3_temperature",
}
SUMS = {
    "ac1": "sensor.span_panel_ac1_consumed_energy",
    "ac2": "sensor.span_panel_ac_2_consumed_energy",
    "ac3": "sensor.span_panel_ac_3_consumed_energy",
    "ev_old": "sensor.span_panel_car_charger_consumed_energy",
    "ev_new": "sensor.span_panel_garage_a_evse_consumed_energy",
}
SOLCAST_TOMORROW = "sensor.solcast_pv_forecast_forecast_tomorrow"


def _local(ts):
    return datetime.fromtimestamp(ts, timezone.utc).astimezone(TZ)


def main():
    rec = sqlite3.connect(REC, uri=True)
    meta = dict(rec.execute("SELECT statistic_id, id FROM statistics_meta"))

    temps = {}
    out_mean = {}
    for key, sid in TEMPS.items():
        agg = defaultdict(lambda: [None, None, 0, 0.0])
        for start, mx, mn, me in rec.execute(
            "SELECT start_ts, max, min, mean FROM statistics "
            "WHERE metadata_id=? ORDER BY start_ts", (meta[sid],)):
            if mx is None or mn is None or me is None:
                continue
            a = agg[_local(start).date()]
            a[0] = mx if a[0] is None else max(a[0], mx)
            a[1] = mn if a[1] is None else min(a[1], mn)
            a[2] += 1
            a[3] += me
        temps[key] = {d: (v[0] + v[1]) / 2.0
                      for d, v in agg.items() if v[2] >= MIN_HOURS_FOR_TEMP}
        if key == "out":
            # mean of hourly means: the v1 fit's input (for the
            # window-vs-proxy discriminator only; not used at run time)
            out_mean = {d: v[3] / v[2]
                        for d, v in agg.items() if v[2] >= MIN_HOURS_FOR_TEMP}

    sums = {}
    for key, sid in SUMS.items():
        daily = defaultdict(float)
        hours = defaultdict(int)
        bad = set()
        prev = None
        for start, s in rec.execute(
            "SELECT start_ts, sum FROM statistics WHERE metadata_id=? "
            "ORDER BY start_ts", (meta[sid],)):
            if s is None:
                continue
            d = _local(start).date()
            if prev is not None:
                delta = s - prev
                if delta < 0 or delta > MAX_WH_PER_HOUR:
                    bad.add(d)
                else:
                    daily[d] += delta / 1000.0
                    hours[d] += 1
            prev = s
        sums[key] = {d: v for d, v in daily.items()
                     if d not in bad and hours[d] >= MIN_HOURS_FOR_TEMP}

    solcast = {}
    for start, st in rec.execute(
        "SELECT start_ts, state FROM statistics WHERE metadata_id=? "
        "ORDER BY start_ts", (meta[SOLCAST_TOMORROW],)):
        loc = _local(start)
        if loc.hour == 20 and st is not None:
            solcast[loc.date() + timedelta(days=1)] = st

    ura = sqlite3.connect(URA, uri=True)
    rows = ura.execute(
        "SELECT date, consumption_kwh, solar_production_kwh, import_kwh, "
        "export_kwh FROM energy_daily ORDER BY date").fetchall()

    w = csv.writer(sys.stdout)
    w.writerow(["date", "consumption_kwh", "solar_kwh", "import_kwh",
                "export_kwh", "temp_mid_f", "temp_mean_f", "in1_mid_f", "in2_mid_f",
                "in3_mid_f", "ac1_kwh", "ac2_kwh", "ac3_kwh", "ev_kwh",
                "solcast_tomorrow_prev_eve_kwh"])

    def f(v):
        return "" if v is None else f"{v:.4f}"

    for ds, cons, sol, imp, exp in rows:
        d = date.fromisoformat(ds)
        ev_src = "ev_old" if d < EV_SWITCH else "ev_new"
        w.writerow([ds, f(cons), f(sol), f(imp), f(exp),
                    f(temps["out"].get(d)), f(out_mean.get(d)),
                    f(temps["in1"].get(d)),
                    f(temps["in2"].get(d)), f(temps["in3"].get(d)),
                    f(sums["ac1"].get(d)), f(sums["ac2"].get(d)),
                    f(sums["ac3"].get(d)), f(sums[ev_src].get(d)),
                    f(solcast.get(d))])


main()
