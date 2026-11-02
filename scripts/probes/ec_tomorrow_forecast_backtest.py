#!/usr/bin/env python3
"""EC-COST-AND-FORECAST-MATH-1 Build 2 D0 — tomorrow-forecast backtest (gate).

Read-only. Inputs come from the committed extract
``data/energy_fit/ec_forecast_daily_inputs.csv`` (produced on the HA host by
``ssh ha "python3 -" < scripts/probes/ec_forecast_daily_extract.py``), so a
reviewer re-running this script gets the same numbers.

Replays, for every target local date in the 45-day window ending 2026-10-31:
  Option A  net = consumption_arm(target, temp) - solcast_tomorrow(prev ~21:00)
                  + bias(trailing 14 clean days of (imp-exp) - (cons-solar))
  Option B  net = mean of (import - export) on the same weekday over the last
                  4 local weeks (the local-date-fixed historical model, D3b)
Actual net = import_kwh - export_kwh (energy_daily).
Forecast temperature is NOT recorded (the weather entity keeps no forecast
history), so the ACTUAL (high+low)/2 stands in, labelled: an upper bound on A.
Solcast IS the real evening-before forecast (recorder statistics state at the
end of the 20:00 local hour).

Consumption arms (MAE vs actual consumption on clean days): v1 (shipped
constants), v2 (the fit script's chosen variant), hvac_zone (per-zone AC +
trailing non-HVAC base), trailing14 (mean of last 14 clean days),
weekly_persistence (same weekday last week).

Gate (plan §6 D0): if A's net MAE >= B's, ship D3b and park A.
"""

from __future__ import annotations

import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "energy"))
import fit_consumption_regression_v2 as v2  # noqa: E402

WINDOW_END = dt.date(2026, 10, 31)
WINDOW_DAYS = 45
BIAS_DAYS = 14
HIST_WEEKS = 4


def main() -> int:
    rows = v2.load_rows()
    by = {r["date"]: r for r in rows}
    fit = v2.fit()
    c_v2 = fit["consts"]
    c_v1 = v2.v1_consts()
    hz = fit["hvac_zone"]
    ev = {d: r["ev_kwh"] for d, r in by.items() if r["ev_kwh"] is not None}
    clean_cons = {d: r["consumption_kwh"] for d, r in by.items() if v2.is_clean(r)}
    gap = {d: (r["import_kwh"] - r["export_kwh"])
           - (r["consumption_kwh"] - r["solar_kwh"])
           for d, r in by.items() if v2.is_clean(r)
           and r["import_kwh"] is not None and r["export_kwh"] is not None}
    indoor = {ind: {d: r[ind] for d, r in by.items() if r[ind] is not None}
              for _, ind in v2.ZONES}
    nonhvac = {d: r["consumption_kwh"] - sum(r[ac] for ac, _ in v2.ZONES)
               for d, r in by.items()
               if v2.is_clean(r) and all(r[ac] is not None for ac, _ in v2.ZONES)}

    def arm(name, d, t):
        if name == "v1":
            return v2.predict(c_v1, d, t)
        if name == "v2":
            extra = (v2.trailing_mean(ev, d, v2.EV_TRAILING_MEAN_DAYS) or 0.0
                     if c_v2.get("ev_variant") == "E2" else 0.0)
            return v2.predict(c_v2, d, t) + extra
        if name == "hvac_zone":
            tot = 0.0
            for (_, ind), b in zip(v2.ZONES, hz["coefs"]):
                tin = v2.trailing_mean(indoor[ind], d,
                                       v2.HVAC_ZONE_INDOOR_TRAILING_DAYS)
                if tin is None:
                    return None
                tot += b[0] + b[1] * max(t - tin, 0.0) + b[2] * max(tin - t, 0.0)
            base = v2.trailing_mean(nonhvac, d, v2.HVAC_BASE_TRAILING_DAYS)
            return None if base is None else tot + base
        if name == "trailing14":
            return v2.trailing_mean(clean_cons, d, 14)
        if name == "weekly_persistence":
            return clean_cons.get(d - dt.timedelta(days=7))
        raise ValueError(name)

    arms = ("v1", "v2", "hvac_zone", "trailing14", "weekly_persistence")
    start = WINDOW_END - dt.timedelta(days=WINDOW_DAYS - 1)
    cons_err = {a: [] for a in arms}
    net_a = {a: [] for a in arms}
    net_b = []
    n_days = 0
    for k in range(WINDOW_DAYS):
        d = start + dt.timedelta(days=k)
        r = by.get(d)
        if r is None or r["import_kwh"] is None or r["export_kwh"] is None:
            continue
        actual_net = r["import_kwh"] - r["export_kwh"]
        hist = [by[d - dt.timedelta(weeks=w)]
                for w in range(1, HIST_WEEKS + 1)
                if d - dt.timedelta(weeks=w) in by
                and by[d - dt.timedelta(weeks=w)]["import_kwh"] is not None]
        if not hist or r["temp_mid_f"] is None \
                or r["solcast_tomorrow_prev_eve_kwh"] is None:
            continue
        n_days += 1
        b_pred = sum(h["import_kwh"] - h["export_kwh"] for h in hist) / len(hist)
        net_b.append(abs(b_pred - actual_net))
        bias = v2.trailing_mean(gap, d, BIAS_DAYS) or 0.0
        for a in arms:
            cp = arm(a, d, r["temp_mid_f"])
            if cp is None:
                continue
            if v2.is_clean(r):
                cons_err[a].append(cp - r["consumption_kwh"])
            pred_net = cp - r["solcast_tomorrow_prev_eve_kwh"] + bias
            net_a[a].append(abs(pred_net - actual_net))

    def m(xs):
        return sum(xs) / len(xs) if xs else float("nan")

    print(f"# D0 backtest: targets {start}..{WINDOW_END}, n={n_days} days with "
          "import/export + Solcast-prev-evening + temp")
    print("# temp = ACTUAL (high+low)/2 (no forecast history): A is an upper bound")
    print(f"# Option B (same-weekday mean, last {HIST_WEEKS} local weeks): "
          f"net MAE = {m(net_b):.2f} kWh (n={len(net_b)})")
    for a in arms:
        e = cons_err[a]
        print(f"# Option A arm={a:18s} net MAE = {m(net_a[a]):6.2f} (n={len(net_a[a])})"
              f" | consumption MAE = {m([abs(x) for x in e]):6.2f}"
              f" bias(NMBE) = {m(e):+6.2f} (n={len(e)})")
    best_a = min(arms, key=lambda a: m(net_a[a]))
    gate = m(net_a["v1"]) < m(net_b)
    print(f"# GATE (A with the shipped arm v1 vs B): "
          f"{'A PASSES -> ship D3 Option A' if gate else 'A FAILS -> ship D3b'}"
          f"; best A arm = {best_a}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
