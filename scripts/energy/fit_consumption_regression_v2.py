#!/usr/bin/env python3
"""v2 consumption regression + hvac_zone arm (EC-COST-AND-FORECAST-MATH-1 D9).

Invoked as ``fit_consumption_regression.py --version v2`` (or directly).
Deterministic pure OLS (normal equations from the v1 script), no seed.

Input: data/energy_fit/ec_forecast_daily_inputs.csv, extracted read-only by
scripts/probes/ec_forecast_daily_extract.py (URA energy_daily + recorder
hourly statistics; local dates, America/Chicago).

Temperature feature: (daily max + daily min) / 2 of the outdoor thermostat
sensor, the SAME proxy D8 feeds at run time ((forecast high + low) / 2).

energy_daily only begins 2026-03-06 (the plan's "on/after 2025-11-01" start
does not exist in the URA DB), so the fit window is every clean day from the
first clean row through 2026-09-30. Holdout = 2026-10 (never fit). There is
NO winter data in the window: spring (Mar-May) is the season baseline and
winter reuses it (season_winter = 0.0).

EV variants (AUDIT_forecast_inputs §2): E1 (default) = whole-house
consumption incl. EV, no EV term. E2 = fit on consumption - EV, run time adds
the trailing EV_TRAILING_MEAN_DAYS mean. E2 ships only if its holdout MAE
beats E1.

Per-HVAC-zone arm (`hvac_zone`): zone kWh (ac1 = zone 1, ac_2 = zone 2,
ac_3 = zone 3; operator-confirmed 2026-11-02) = a_z + b_z * max(out - in_z, 0)
(+ c_z * max(in_z - out, 0) when the fit has a positive heating slope);
in_z = zone thermostat (max+min)/2; tomorrow's in_z = trailing 7-day mean.
base_nonhvac = consumption - sum(ac) as a trailing mean or the v1-shape fit,
whichever wins on the holdout. Ships only if its holdout MAE beats v2 by
>= HVAC_ZONE_ARM_MIN_GAIN_KWH. Setpoint variant: thermostat setpoints are
not in recorder long-term statistics (AUDIT_forecast_inputs §3), so it
cannot be backtested and is not offered.
"""

from __future__ import annotations

import csv
import datetime as dt
import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fit_consumption_regression import (  # noqa: E402
    CDD_BASE_F,
    HDD_BASE_F,
    REPO_ROOT,
    mae,
    ols,
    season_of,
)

V2_INPUT_CSV = os.path.join(
    REPO_ROOT, "data", "energy_fit", "ec_forecast_daily_inputs.csv",
)
V2_TRAIN_END = dt.date(2026, 9, 30)
V2_HOLDOUT_START = dt.date(2026, 10, 1)
V2_HOLDOUT_END = dt.date(2026, 10, 31)
# Clean-day rules (ENERGY-CONSUMPTION-FORECAST-POISONED-1 + the 240 kWh
# energy_daily write clamp): plausible daily total, non-zero solar (a
# zero-solar day is the both-ends lifetime-counter glitch), and the poisoned
# dates in AUDIT_energy_consumption_forecast_poisoning_2026_09_29.
V2_MIN_PLAUSIBLE_KWH = 10.0
V2_MAX_PLAUSIBLE_KWH = 240.0
V2_POISONED_DATES = {
    dt.date(2026, 6, 19), dt.date(2026, 8, 20), dt.date(2026, 8, 28),
    dt.date(2026, 8, 30), dt.date(2026, 9, 24), dt.date(2026, 9, 25),
    dt.date(2026, 9, 29),
}
EV_TRAILING_MEAN_DAYS = 14
HVAC_ZONE_ARM_MIN_GAIN_KWH = 2.0
HVAC_ZONE_INDOOR_TRAILING_DAYS = 7
HVAC_BASE_TRAILING_DAYS = 14
ZONES = (("ac1_kwh", "in1_mid_f"), ("ac2_kwh", "in2_mid_f"),
         ("ac3_kwh", "in3_mid_f"))


def _f(v: str | None) -> float | None:
    v = (v or "").strip()
    return float(v) if v else None


def load_rows(path: str = V2_INPUT_CSV) -> list[dict]:
    out = []
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            row = {k: _f(v) for k, v in r.items() if k != "date"}
            row["date"] = dt.date.fromisoformat(r["date"])
            out.append(row)
    return out


def is_clean(r: dict) -> bool:
    c, s = r.get("consumption_kwh"), r.get("solar_kwh")
    return (
        c is not None and V2_MIN_PLAUSIBLE_KWH <= c <= V2_MAX_PLAUSIBLE_KWH
        and s is not None and s > 0
        and r["date"] not in V2_POISONED_DATES
    )


def encode(d: dt.date, temp_f: float) -> list[float]:
    s = season_of(d)
    return [1.0, max(temp_f - CDD_BASE_F, 0.0), max(HDD_BASE_F - temp_f, 0.0),
            1.0 if s == "summer" else 0.0, 1.0 if s == "fall" else 0.0]


def to_consts(beta: list[float], meta: dict) -> dict:
    """Coefficients in the runtime shape read by
    energy_forecast.compute_consumption_regression."""
    out = {
        "base": round(beta[0], 4),
        "cdd_coeff": round(beta[1], 4),
        "hdd_coeff": round(beta[2], 4),
        "season_spring": 0.0,
        "season_summer": round(beta[3], 4),
        "season_fall": round(beta[4], 4),
        "season_winter": 0.0,
        "hdd_base_f": HDD_BASE_F,
        "cdd_base_f": CDD_BASE_F,
        "ev_term_kwh": 0.0,
        "ev_era_start": "2026-03-01",
    }
    out.update(meta)
    return out


def predict(c: dict, d: dt.date, temp_f: float) -> float:
    """Independent re-implementation of the runtime formula (this script is
    the oracle the runtime function is diffed against)."""
    ev_era = dt.date.fromisoformat(c["ev_era_start"])
    return (c["base"] + c["cdd_coeff"] * max(temp_f - c["cdd_base_f"], 0.0)
            + c["hdd_coeff"] * max(c["hdd_base_f"] - temp_f, 0.0)
            + c["season_" + season_of(d)]
            + (c["ev_term_kwh"] if d >= ev_era else 0.0))


def trailing_mean(series: dict, d: dt.date, days: int) -> float | None:
    vals = [series[d - dt.timedelta(days=k)] for k in range(1, days + 1)
            if series.get(d - dt.timedelta(days=k)) is not None]
    return sum(vals) / len(vals) if vals else None


def v1_consts() -> dict:
    path = os.path.join(REPO_ROOT, "custom_components",
                        "universal_room_automation", "domain_coordinators",
                        "energy_const.py")
    spec = importlib.util.spec_from_file_location("_ec_const_v1", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return dict(mod.CONSUMPTION_REGRESSION_V1)


def split(rows):
    clean = [r for r in rows if is_clean(r) and r["temp_mid_f"] is not None]
    train = [r for r in clean if r["date"] <= V2_TRAIN_END]
    hold = [r for r in clean if V2_HOLDOUT_START <= r["date"] <= V2_HOLDOUT_END]
    return train, hold


def fit() -> dict:
    rows = load_rows()
    by_date = {r["date"]: r for r in rows}
    train, hold = split(rows)
    y_h = [r["consumption_kwh"] for r in hold]
    meta = {
        "fit_date": "2026-11-02",
        "train_span": f"{train[0]['date'].isoformat()}..{V2_TRAIN_END.isoformat()}",
        "holdout_span": f"{V2_HOLDOUT_START.isoformat()}..{V2_HOLDOUT_END.isoformat()}",
        "temp_feature": "(daily_high + daily_low) / 2",
        "n_train": len(train),
        "n_holdout": len(hold),
    }

    # E1: whole-house consumption, no EV term.
    c_e1 = to_consts(ols([encode(r["date"], r["temp_mid_f"]) for r in train],
                         [r["consumption_kwh"] for r in train]),
                     dict(meta, ev_variant="E1"))
    p_e1 = [predict(c_e1, r["date"], r["temp_mid_f"]) for r in hold]

    # E2: base on consumption - EV, + trailing EV mean at run time.
    ev = {d: r["ev_kwh"] for d, r in by_date.items() if r["ev_kwh"] is not None}
    tr2 = [r for r in train if r["ev_kwh"] is not None]
    c_e2 = to_consts(ols([encode(r["date"], r["temp_mid_f"]) for r in tr2],
                         [r["consumption_kwh"] - r["ev_kwh"] for r in tr2]),
                     dict(meta, ev_variant="E2"))
    p_e2 = [predict(c_e2, r["date"], r["temp_mid_f"])
            + (trailing_mean(ev, r["date"], EV_TRAILING_MEAN_DAYS) or 0.0)
            for r in hold]

    # v1 shipped constants, and a v1-shape refit on this window with the
    # hourly-MEAN temp (discriminates window change vs temp-proxy change).
    p_v1 = [predict(v1_consts(), r["date"], r["temp_mid_f"]) for r in hold]
    trm = [r for r in train if r["temp_mean_f"] is not None]
    c_mean = to_consts(ols([encode(r["date"], r["temp_mean_f"]) for r in trm],
                           [r["consumption_kwh"] for r in trm]), meta)
    p_mean = [predict(c_mean, r["date"], r["temp_mean_f"] or r["temp_mid_f"])
              for r in hold]

    mae_e1, mae_e2 = mae(y_h, p_e1), mae(y_h, p_e2)
    chosen_name = "E1" if mae_e1 <= mae_e2 else "E2"
    mae_v1_pre = mae(y_h, [predict(v1_consts(), r["date"], r["temp_mid_f"])
                           for r in hold])
    if min(mae_e1, mae_e2) >= mae_v1_pre:
        # v2 FAILS its ship gate: it is only a logged record arm, so the
        # simpler E1 (no EV input; E2 would need a new per-house EV
        # statistic role key) is emitted. Both MAEs are printed.
        chosen_name = "E1"
    chosen = c_e1 if chosen_name == "E1" else c_e2
    p_chosen = p_e1 if chosen_name == "E1" else p_e2
    mae_v2 = mae_e1 if chosen_name == "E1" else mae_e2
    mae_v1 = mae(y_h, p_v1)
    chosen = dict(
        chosen,
        train_mae_kwh=round(mae([r["consumption_kwh"] for r in train],
                                [predict(chosen, r["date"], r["temp_mid_f"])
                                 for r in train]), 2),
        holdout_mae_kwh=round(mae_v2, 2),
        v1_holdout_mae_kwh=round(mae_v1, 2),
    )
    return {
        "consts": chosen, "chosen": chosen_name,
        "mae_v1": mae_v1, "mae_e1": mae_e1, "mae_e2": mae_e2,
        "mae_v1shape_meantemp": mae(y_h, p_mean),
        "ship_v2": mae_v2 < mae_v1,
        "hvac_zone": fit_hvac_zone(by_date, train, hold),
        "holdout": [(r["date"], r["temp_mid_f"], p) for r, p in zip(hold, p_chosen)],
    }


def fit_hvac_zone(by_date, train, hold) -> dict:
    coefs = []
    for ac, ind in ZONES:
        tr = [r for r in train if r[ac] is not None and r[ind] is not None]
        X = [[1.0, max(r["temp_mid_f"] - r[ind], 0.0),
              max(r[ind] - r["temp_mid_f"], 0.0)] for r in tr]
        b = ols(X, [r[ac] for r in tr])
        if b[2] <= 0:  # no heating slope: drop the term and refit
            b = ols([x[:2] for x in X], [r[ac] for r in tr]) + [0.0]
        coefs.append(b)
    indoor = {ind: {d: r[ind] for d, r in by_date.items() if r[ind] is not None}
              for _, ind in ZONES}
    nonhvac = {d: r["consumption_kwh"] - sum(r[ac] for ac, _ in ZONES)
               for d, r in by_date.items()
               if is_clean(r) and all(r[ac] is not None for ac, _ in ZONES)}
    tr_nh = [r for r in train if r["date"] in nonhvac]
    b_nh = ols([encode(r["date"], r["temp_mid_f"]) for r in tr_nh],
               [nonhvac[r["date"]] for r in tr_nh])

    def zone_sum(r):
        tot = 0.0
        for (_, ind), b in zip(ZONES, coefs):
            tin = trailing_mean(indoor[ind], r["date"],
                                HVAC_ZONE_INDOOR_TRAILING_DAYS)
            if tin is None:
                return None
            tot += (b[0] + b[1] * max(r["temp_mid_f"] - tin, 0.0)
                    + b[2] * max(tin - r["temp_mid_f"], 0.0))
        return tot

    by_base = {}
    for name in ("trailing", "fit"):
        ys, ps = [], []
        for r in hold:
            zs = zone_sum(r)
            if name == "trailing":
                base = trailing_mean(nonhvac, r["date"], HVAC_BASE_TRAILING_DAYS)
            else:
                base = sum(b * x for b, x in zip(
                    b_nh, encode(r["date"], r["temp_mid_f"])))
            if zs is None or base is None:
                continue
            ys.append(r["consumption_kwh"])
            ps.append(zs + base)
        by_base[name] = (mae(ys, ps) if ys else None, len(ys))
    best = min((k for k in by_base if by_base[k][0] is not None),
               key=lambda k: by_base[k][0], default=None)
    return {"coefs": coefs, "base_fit": b_nh, "by_base": by_base, "best": best}


def main() -> int:
    r = fit()
    hz = r["hvac_zone"]
    c = r["consts"]
    print(f"# v2 fit: n_train={c['n_train']} ({c['train_span']}), "
          f"n_holdout={c['n_holdout']} ({c['holdout_span']})")
    print(f"# holdout MAE v1 (shipped consts, mid temp)        = {r['mae_v1']:.2f}")
    print(f"# holdout MAE v2 E1 (no EV term)                   = {r['mae_e1']:.2f}")
    print(f"# holdout MAE v2 E2 (EV split + trailing EV mean)  = {r['mae_e2']:.2f}")
    print(f"# holdout MAE v1-shape refit, hourly-mean temp     = "
          f"{r['mae_v1shape_meantemp']:.2f}")
    print(f"# emitted EV variant: {r['chosen']} (E1 when v2 fails its gate); "
          f"ship v2 (beats v1): {r['ship_v2']}")
    for k, (m, n) in hz["by_base"].items():
        print(f"# hvac_zone base={k}: holdout MAE = "
              f"{'n/a' if m is None else f'{m:.2f}'} over n={n}")
    best = hz["best"]
    v2m = r["consts"]["holdout_mae_kwh"]
    gain = (v2m - hz["by_base"][best][0]) if best else None
    verdict = ("SHIP" if gain is not None and gain >= HVAC_ZONE_ARM_MIN_GAIN_KWH
               else "DO NOT SHIP")
    print(f"# hvac_zone best base={best}; gain vs v2 = "
          f"{'n/a' if gain is None else f'{gain:.2f}'} kWh "
          f"(gate >= {HVAC_ZONE_ARM_MIN_GAIN_KWH}) -> {verdict}")
    for i, b in enumerate(hz["coefs"], 1):
        print(f"#   zone {i}: a={b[0]:.4f} b_cool={b[1]:.4f} c_heat={b[2]:.4f}")
    print("# first three holdout predictions (date, temp_mid, kWh):")
    for d, t, p in r["holdout"][:3]:
        print(f"#   {d} {t:.4f} {p:.4f}")
    print()
    print("CONSUMPTION_REGRESSION_V2: Final[dict] = {")
    for k, v in c.items():
        val = f'"{v}"' if isinstance(v, str) else repr(v)
        print(f'    "{k}": {val},')
    print("}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
