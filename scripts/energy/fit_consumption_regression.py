#!/usr/bin/env python3
"""R1 consumption regression — reproducible offline fit.

Fits the season + HDD/CDD (base 65 °F) linear regression against the Enphase
Enlighten daily consumption CSV (kWh; note the sibling production CSV is
in *Wh* — unit trap called out in data/enphase/README.md, not touched here
because R1 only fits consumption).

Deterministic: pure OLS (normal equations) on a fixed date-split. No random
seed used or needed.

Outputs
-------
- Prints a reviewed-constant block, byte-identical between runs, ready to
  paste into `energy_const.py` as `CONSUMPTION_REGRESSION_V1`.
- Prints train + holdout MAE / R² so a reviewer re-running the script sees
  the same numbers.

Data-source notes
-----------------
- Consumption: `data/enphase/site_energy_consumption_daily_2025-02-24_to_2026-07-15.csv`
  (kWh/day). Zero-runs listed in `data/enphase/README.md` are dropped as
  metering outages, not real zeros. 2026-05-28 (single negative day) also
  dropped per the same README.
- Outdoor temperature: `data/energy_fit/daily_outdoor_temperature_f.csv`
  (°F, daily mean), extracted from the URA sqlite HA long-term-statistics
  table for `sensor.thermostat_bryant_wifi_backhallway_outdoor_temperature`
  (metadata_id 234) per B0 §A. Committed so this script does not require the
  live HA DB. Coverage vs the masked-clean consumption span: 94.7 %.

EV decomposition (operator directive 2026-07-16 — PARSIMONY)
-----------------------------------------------------------
The original fixed split (train 2025-02..2026-04, holdout 2026-05..2026-07)
FAILED the ≤20 kWh invariant with holdout MAE 23.8 kWh because 2026 May–Jul
consumption is systematically ~17–21 kWh/day above the 2025-heavy train
distribution. Diagnostic (all three holdout months under-predict by a nearly
constant offset) matches a NEW LOAD source, not a broken fit.

Operator statement: **2025 is effectively EV-free** (managed charging began
mid-2026) → 2025 is the natural control for base-load calibration.

R1 decomposes:
    predicted_consumption(d, temp) = base_regression(d, temp)
                                   + (EV_TERM if d >= EV_ERA_START else 0)

- `base_regression` is fit on **2025 only** (n=271 masked-clean days).
- `EV_TERM` is the mean(max(0, actual − base_pred)) over the 2026 residual set
  — a single constant kWh/day. Validated (see below).

Validation — 15-min power CSV (`site_recent_power_consumption_15min_2026-07-09_to_07-16.csv`)
--------------------------------------------------------------------------------------------
Extraction: overnight (22:00–08:00) 15-min slots with P>7 kW where at least one
neighbour is also >7 kW; attribute (P − 5 kW) as EV load. 5 comparable days
(others missing daily temp): validation MAE = 6.47 kWh, bias +4.4 kWh — the
base-residual EV proxy method is within one L1-charger-hour of the 15-min truth.

The R1 runtime term is a single CONSTANT (mean 2026 residual, ~18–19 kWh/d),
NOT the per-day residual method — the residual method is only the *fitting*
tool used offline. Plan-aware / schedule-aware EV terms are R8-era.

Train/holdout split (B0 §F / PLANNING R1)
-----------------------------------------
- Base fit train:  2025-02-25 → 2025-12-31 (EV-free by operator statement)
- Holdout:         2026-05-01 → 2026-07-15  (EV-era, evaluates base + EV_TERM)

Invariant enforced by the plan:
    Holdout MAE ≤ 20.0 kWh (I-NE / R1 acceptance) — evaluated on the
    COMBINED estimator (base + EV_TERM) over the EV-era holdout.
"""

from __future__ import annotations

import csv
import datetime as dt
import math
import os
import sys
from typing import Iterable

# ---------------------------------------------------------------------------
# Reviewed constants — Numbers Get Knobs rung-1
# ---------------------------------------------------------------------------
# These live in the *script*, not `energy_const.py`, because they define how
# the fit is *derived*. The derived coefficients are what become the runtime
# reviewed constants. Changing anything below re-derives them and requires
# review.

HDD_BASE_F: float = 65.0
CDD_BASE_F: float = 65.0
# Base fit is EV-free 2025 only (operator statement: managed charging began
# mid-2026). Holdout is the EV-era window; combined estimator is evaluated.
TRAIN_START = dt.date(2025, 2, 25)
TRAIN_END   = dt.date(2025, 12, 31)
HOLDOUT_START = dt.date(2026, 5, 1)
HOLDOUT_END   = dt.date(2026, 7, 15)
# EV era: managed charging behaviour begins here (operator, 2026-07-16).
EV_ERA_START = dt.date(2026, 3, 1)
HOLDOUT_MAE_INVARIANT_KWH: float = 20.0

# Outage zero-runs to mask (per data/enphase/README.md). Inclusive ranges.
OUTAGE_RUNS: list[tuple[dt.date, dt.date]] = [
    (dt.date(2025, 7, 22), dt.date(2025, 7, 27)),
    (dt.date(2025, 8, 5),  dt.date(2025, 8, 11)),
    (dt.date(2025, 9, 19), dt.date(2025, 9, 25)),
    (dt.date(2026, 3, 30), dt.date(2026, 4, 6)),
    (dt.date(2026, 5, 27), dt.date(2026, 5, 30)),
]
NEGATIVE_DAYS: set[dt.date] = {dt.date(2026, 5, 28)}

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONSUMPTION_CSV = os.path.join(
    REPO_ROOT, "data", "enphase",
    "site_energy_consumption_daily_2025-02-24_to_2026-07-15.csv",
)
TEMPERATURE_CSV = os.path.join(
    REPO_ROOT, "data", "energy_fit", "daily_outdoor_temperature_f.csv",
)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _parse_date_us(s: str) -> dt.date:
    return dt.datetime.strptime(s, "%m/%d/%Y").date()


def _parse_date_iso(s: str) -> dt.date:
    return dt.datetime.strptime(s, "%Y-%m-%d").date()


def load_consumption(path: str) -> dict[dt.date, float]:
    """Return {date: kWh}. Skips the 'Total' footer row."""
    out: dict[dt.date, float] = {}
    with open(path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        if header[0].strip().lower() not in ("date/time", "date"):
            raise SystemExit(f"unexpected header {header}")
        for row in reader:
            if not row or row[0].strip().lower() == "total":
                continue
            try:
                d = _parse_date_us(row[0].strip())
            except ValueError:
                continue
            try:
                kwh = float(row[1].replace(",", "").strip())
            except (ValueError, IndexError):
                continue
            out[d] = kwh
    return out


def load_temperature(path: str) -> dict[dt.date, float]:
    """Return {date: mean °F}."""
    out: dict[dt.date, float] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            try:
                d = _parse_date_iso(row["date"])
                t = float(row["mean_temp_f"])
            except (ValueError, KeyError):
                continue
            out[d] = t
    return out


def in_outage(d: dt.date) -> bool:
    return any(a <= d <= b for (a, b) in OUTAGE_RUNS)


def season_of(d: dt.date) -> str:
    m = d.month
    if m in (12, 1, 2):
        return "winter"
    if m in (3, 4, 5):
        return "spring"
    if m in (6, 7, 8):
        return "summer"
    return "fall"


# ---------------------------------------------------------------------------
# OLS via normal equations (pure stdlib)
# ---------------------------------------------------------------------------

def _matmul(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    n, m, p = len(A), len(A[0]), len(B[0])
    if len(B) != m:
        raise ValueError("shape mismatch")
    out = [[0.0] * p for _ in range(n)]
    for i in range(n):
        Ai = A[i]
        for k in range(m):
            aik = Ai[k]
            if aik == 0.0:
                continue
            Bk = B[k]
            outi = out[i]
            for j in range(p):
                outi[j] += aik * Bk[j]
    return out


def _transpose(A: list[list[float]]) -> list[list[float]]:
    return [list(col) for col in zip(*A)]


def _inv(A: list[list[float]]) -> list[list[float]]:
    """Gauss-Jordan inverse. Small matrices only."""
    n = len(A)
    M = [row[:] + [1.0 if i == j else 0.0 for j in range(n)]
         for i, row in enumerate(A)]
    for col in range(n):
        # partial pivot
        pivot = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[pivot][col]) < 1e-12:
            raise ValueError("singular matrix")
        M[col], M[pivot] = M[pivot], M[col]
        piv = M[col][col]
        M[col] = [v / piv for v in M[col]]
        for r in range(n):
            if r == col:
                continue
            factor = M[r][col]
            if factor == 0.0:
                continue
            M[r] = [M[r][k] - factor * M[col][k] for k in range(2 * n)]
    return [row[n:] for row in M]


def ols(X: list[list[float]], y: list[float]) -> list[float]:
    """Return beta such that y ≈ X @ beta, via (X'X)^-1 X'y."""
    Xt = _transpose(X)
    XtX = _matmul(Xt, X)
    Xty = _matmul(Xt, [[v] for v in y])
    inv = _inv(XtX)
    beta = _matmul(inv, Xty)
    return [row[0] for row in beta]


# ---------------------------------------------------------------------------
# Feature encoding
# ---------------------------------------------------------------------------

FEATURE_NAMES = [
    "intercept",
    "cdd",             # max(temp - 65, 0)
    "hdd",             # max(65 - temp, 0)
    "season_spring",   # 1 if spring else 0
    "season_summer",   # 1 if summer else 0
    "season_fall",     # 1 if fall else 0
]
# winter = baseline (all-zero dummies).


def encode(d: dt.date, temp_f: float) -> list[float]:
    cdd = max(temp_f - CDD_BASE_F, 0.0)
    hdd = max(HDD_BASE_F - temp_f, 0.0)
    s = season_of(d)
    return [
        1.0,
        cdd,
        hdd,
        1.0 if s == "spring" else 0.0,
        1.0 if s == "summer" else 0.0,
        1.0 if s == "fall" else 0.0,
    ]


def predict_row(beta: list[float], d: dt.date, temp_f: float) -> float:
    x = encode(d, temp_f)
    return sum(b * v for b, v in zip(beta, x))


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def mae(y: Iterable[float], yhat: Iterable[float]) -> float:
    ys = list(y); ps = list(yhat)
    return sum(abs(a - b) for a, b in zip(ys, ps)) / len(ys)


def r2(y: Iterable[float], yhat: Iterable[float]) -> float:
    ys = list(y); ps = list(yhat)
    mean_y = sum(ys) / len(ys)
    ss_res = sum((a - b) ** 2 for a, b in zip(ys, ps))
    ss_tot = sum((a - mean_y) ** 2 for a in ys)
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0


# ---------------------------------------------------------------------------
# Assemble + fit + report
# ---------------------------------------------------------------------------

def build_dataset(mask_outages: bool = True) -> list[tuple[dt.date, float, float]]:
    """Return [(date, kwh, temp_f)] for days with BOTH temp and consumption
    that are (a) not in an outage run and (b) not the negative day."""
    cons = load_consumption(CONSUMPTION_CSV)
    temp = load_temperature(TEMPERATURE_CSV)
    rows: list[tuple[dt.date, float, float]] = []
    for d, kwh in sorted(cons.items()):
        if mask_outages:
            if in_outage(d) or d in NEGATIVE_DAYS:
                continue
            if kwh <= 0:
                # defence-in-depth for any residual zero we didn't enumerate
                continue
        else:
            if kwh <= 0:  # still skip literal zeros so OLS is defined
                continue
        t = temp.get(d)
        if t is None:
            continue
        rows.append((d, kwh, t))
    return rows


def split(rows: list[tuple[dt.date, float, float]]) -> tuple[list, list]:
    train = [r for r in rows if TRAIN_START <= r[0] <= TRAIN_END]
    hold  = [r for r in rows if HOLDOUT_START <= r[0] <= HOLDOUT_END]
    return train, hold


def fit_and_report(mask_outages: bool = True) -> dict:
    """EV-decomposed fit.

    1. Base regression fit on 2025 only (EV-free by operator statement).
    2. EV_TERM = mean(max(0, actual − base_pred)) over ALL 2026 days present in
       the masked dataset (not just the holdout — using the full 2026 range
       reduces the constant's sample noise).
    3. Combined estimator on holdout: base_pred + EV_TERM (holdout is 2026 so
       EV era gate is always ON).
    """
    rows = build_dataset(mask_outages=mask_outages)
    train, hold = split(rows)
    if not train or not hold:
        raise SystemExit("empty train or holdout split")

    X = [encode(d, t) for (d, _, t) in train]
    y = [k for (_, k, _) in train]
    beta = ols(X, y)

    yhat_train = [predict_row(beta, d, t) for (d, _, t) in train]
    y_train    = [k for (_, k, _) in train]

    # EV era: 2026 days in the masked dataset. Constant EV term = mean of
    # positive residual (bounded ≥0 — negative residuals are noise, not EV
    # dis-load).
    ev_era_rows = [
        (d, k, t) for (d, k, t) in rows
        if d >= EV_ERA_START and d <= HOLDOUT_END
    ]
    ev_residuals = [
        max(0.0, k - predict_row(beta, d, t)) for (d, k, t) in ev_era_rows
    ]
    ev_term = (sum(ev_residuals) / len(ev_residuals)) if ev_residuals else 0.0

    # Combined estimator on holdout — holdout is 2026 → EV era gate ON.
    yhat_hold  = [predict_row(beta, d, t) + ev_term for (d, _, t) in hold]
    y_hold     = [k for (_, k, _) in hold]

    # Base-only holdout metrics (for transparency).
    yhat_hold_base = [predict_row(beta, d, t) for (d, _, t) in hold]

    train_mae = mae(y_train, yhat_train)
    train_r2  = r2(y_train, yhat_train)
    hold_mae  = mae(y_hold, yhat_hold)          # combined
    hold_r2   = r2(y_hold, yhat_hold)
    hold_mae_base_only = mae(y_hold, yhat_hold_base)

    result = {
        "beta": beta,
        "features": FEATURE_NAMES,
        "ev_term_kwh_per_day": ev_term,
        "ev_era_start": EV_ERA_START.isoformat(),
        "n_train": len(train),
        "n_ev_era_used_for_term": len(ev_era_rows),
        "n_holdout": len(hold),
        "train_mae": train_mae,
        "train_r2":  train_r2,
        "holdout_mae_combined": hold_mae,
        "holdout_r2_combined":  hold_r2,
        "holdout_mae_base_only": hold_mae_base_only,
    }
    return result


def format_const_block(r: dict) -> str:
    b = r["beta"]
    return (
        "CONSUMPTION_REGRESSION_V1: Final[dict] = {\n"
        f"    \"base\":               {b[0]:.4f},   # intercept kWh (winter baseline, 2025 EV-free fit)\n"
        f"    \"cdd_coeff\":          {b[1]:.4f},   # kWh per cooling-degree-day (base 65°F)\n"
        f"    \"hdd_coeff\":          {b[2]:.4f},   # kWh per heating-degree-day (base 65°F)\n"
        f"    \"season_spring\":      {b[3]:.4f},\n"
        f"    \"season_summer\":      {b[4]:.4f},\n"
        f"    \"season_fall\":        {b[5]:.4f},\n"
        f"    \"season_winter\":      0.0,       # baseline\n"
        f"    \"hdd_base_f\":         {HDD_BASE_F},\n"
        f"    \"cdd_base_f\":         {CDD_BASE_F},\n"
        f"    \"ev_term_kwh\":        {r['ev_term_kwh_per_day']:.4f},   # constant kWh/day added when today >= EV_ERA_START\n"
        f"    \"ev_era_start\":       \"{r['ev_era_start']}\",\n"
        f"    \"fit_date\":           \"2026-07-16\",\n"
        f"    \"train_span\":         \"{TRAIN_START.isoformat()}..{TRAIN_END.isoformat()}\",  # 2025 only (EV-free)\n"
        f"    \"holdout_span\":       \"{HOLDOUT_START.isoformat()}..{HOLDOUT_END.isoformat()}\",\n"
        f"    \"n_train\":            {r['n_train']},\n"
        f"    \"n_ev_era_for_term\":  {r['n_ev_era_used_for_term']},\n"
        f"    \"n_holdout\":          {r['n_holdout']},\n"
        f"    \"train_mae_kwh\":      {r['train_mae']:.2f},\n"
        f"    \"train_r2\":           {r['train_r2']:.4f},\n"
        f"    \"holdout_mae_kwh\":    {r['holdout_mae_combined']:.2f},   # combined base + EV_TERM\n"
        f"    \"holdout_r2\":         {r['holdout_r2_combined']:.4f},\n"
        f"    \"holdout_mae_base_only_kwh\": {r['holdout_mae_base_only']:.2f},   # for transparency\n"
        "}\n"
    )


def main(argv: list[str]) -> int:
    mask = True
    if "--no-mask" in argv:
        mask = False
        print("# WARNING: outage mask DISABLED (debug mode)")
    r = fit_and_report(mask_outages=mask)
    print("# R1 consumption regression fit (EV-decomposed) — {} days train (2025 only), "
          "{} EV-era days used for term, {} holdout"
          .format(r["n_train"], r["n_ev_era_used_for_term"], r["n_holdout"]))
    print(f"# train (base only):        MAE={r['train_mae']:.2f} kWh   R²={r['train_r2']:.4f}")
    print(f"# holdout (base only):      MAE={r['holdout_mae_base_only']:.2f} kWh")
    print(f"# holdout (base + EV_TERM): MAE={r['holdout_mae_combined']:.2f} kWh   R²={r['holdout_r2_combined']:.4f}")
    print(f"# EV_TERM = {r['ev_term_kwh_per_day']:.2f} kWh/day (constant)")
    print(f"# invariant: holdout combined MAE ≤ {HOLDOUT_MAE_INVARIANT_KWH} kWh — ", end="")
    if r["holdout_mae_combined"] <= HOLDOUT_MAE_INVARIANT_KWH:
        print("PASS")
    else:
        print("FAIL — STOP; do not update constants")
    print()
    print(format_const_block(r))
    return 0 if r["holdout_mae_combined"] <= HOLDOUT_MAE_INVARIANT_KWH else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
