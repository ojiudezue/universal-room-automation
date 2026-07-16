"""R1 — Consumption regression v1 (EV-decomposed) tests.

Covers PLANNING_net_energy_program_R1_R7_R2.md § R1 acceptance:

- test_consumption_regression_backtest: fit-conformance test — recomputes a
  set of known days from the Enphase daily CSVs using the checked-in
  CONSUMPTION_REGRESSION_V1 constants and asserts per-day tolerance +
  holdout MAE ≤ 20 kWh (I-NE / R1 invariant). This is also the mutation
  anchor for the fit-conformance mutation (coefficient sign flip).
- test_dow_arm_removed_from_v1_path: v1 arm reads no per-DOW baseline.
- test_estimator_shadow_only_gates_consumer: shadow gate ON keeps the CONSUMED
  value on the legacy path AND still stashes the v1 shadow value.
- test_source_marker_v1_when_shadow_off: shadow OFF → source marker on the
  published prediction is `v1_regression`.
- test_source_marker_legacy_when_shadow_on: shadow ON → source marker is
  `dow_legacy` (or `fallback` when no history), NOT `v1_regression`.
- test_ev_era_gate_zero_before_start: v1 arm returns ev=0 before the
  ev_era_start date and ev=EV_TERM after.
- test_fit_script_reproducible: importing the fit script and calling
  fit_and_report() returns the exact byte-identical constants baked into
  CONSUMPTION_REGRESSION_V1.
"""

from __future__ import annotations

import csv
import datetime as dt
import importlib.util
import os
import sys
from unittest.mock import MagicMock

import pytest

# Reuse the mock-HA bootstrap from the existing consumption test module.
sys.path.insert(0, os.path.dirname(__file__))
# noqa: E402
import test_energy_consumption  # sets sys.modules for HA + URA packages

from custom_components.universal_room_automation.domain_coordinators.energy_const import (  # noqa: E402
    CONF_R1_ESTIMATOR_SHADOW_ONLY,
    CONSUMPTION_REGRESSION_V1,
    PRED_CONSUMPTION_SOURCE_DOW_LEGACY,
    PRED_CONSUMPTION_SOURCE_FALLBACK,
    PRED_CONSUMPTION_SOURCE_V1_REGRESSION,
)
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy_forecast as _ef,
)
from custom_components.universal_room_automation.domain_coordinators.energy_forecast import (  # noqa: E402
    DailyEnergyPredictor,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONSUMPTION_CSV = os.path.join(
    REPO_ROOT, "data", "enphase",
    "site_energy_consumption_daily_2025-02-24_to_2026-07-15.csv",
)
TEMP_CSV = os.path.join(
    REPO_ROOT, "data", "energy_fit", "daily_outdoor_temperature_f.csv",
)


# ============================================================================
# Helpers
# ============================================================================

def _load_consumption() -> dict[dt.date, float]:
    out: dict[dt.date, float] = {}
    with open(CONSUMPTION_CSV, newline="") as f:
        r = csv.reader(f)
        next(r)
        for row in r:
            if not row or row[0].strip().lower() == "total":
                continue
            try:
                d = dt.datetime.strptime(row[0].strip(), "%m/%d/%Y").date()
                out[d] = float(row[1].replace(",", "").strip())
            except (ValueError, IndexError):
                continue
    return out


def _load_temp() -> dict[dt.date, float]:
    out: dict[dt.date, float] = {}
    with open(TEMP_CSV, newline="") as f:
        for row in csv.DictReader(f):
            try:
                out[dt.datetime.strptime(row["date"], "%Y-%m-%d").date()] = float(
                    row["mean_temp_f"]
                )
            except (ValueError, KeyError):
                continue
    return out


# Outage runs + negative day (mirror of the fit-script masks — kept explicit
# here so the test is a durable check independent of the script).
_OUTAGE_RUNS = [
    (dt.date(2025, 7, 22), dt.date(2025, 7, 27)),
    (dt.date(2025, 8, 5),  dt.date(2025, 8, 11)),
    (dt.date(2025, 9, 19), dt.date(2025, 9, 25)),
    (dt.date(2026, 3, 30), dt.date(2026, 4, 6)),
    (dt.date(2026, 5, 27), dt.date(2026, 5, 30)),
]
_NEGATIVE_DAYS = {dt.date(2026, 5, 28)}


def _in_outage(d: dt.date) -> bool:
    return any(a <= d <= b for (a, b) in _OUTAGE_RUNS)


def _predict(d: dt.date, temp: float) -> float:
    """Recreate the runtime v1 formula from the checked-in constants."""
    c = CONSUMPTION_REGRESSION_V1
    cdd = max(temp - c["cdd_base_f"], 0.0)
    hdd = max(c["hdd_base_f"] - temp, 0.0)
    m = d.month
    if m in (12, 1, 2):
        season = c["season_winter"]
    elif m in (3, 4, 5):
        season = c["season_spring"]
    elif m in (6, 7, 8):
        season = c["season_summer"]
    else:
        season = c["season_fall"]
    base = c["base"] + c["cdd_coeff"] * cdd + c["hdd_coeff"] * hdd + season
    ev_era = dt.datetime.strptime(c["ev_era_start"], "%Y-%m-%d").date()
    ev = c["ev_term_kwh"] if d >= ev_era else 0.0
    return base + ev


# ============================================================================
# Test A — fit-conformance / backtest (mutation anchor for coefficient tampering)
# ============================================================================

def test_consumption_regression_backtest():
    """Holdout MAE ≤ 20 kWh (I-NE / R1 invariant) + a handful of spot-check
    days must be within a per-day sanity tolerance.

    This test is red under any of:
      - coefficient sign flip / any coefficient off by more than the tolerance
      - ev_term_kwh mis-baked
      - ev_era_start mis-dated
    """
    cons = _load_consumption()
    temp = _load_temp()

    holdout_start = dt.date(2026, 5, 1)
    holdout_end = dt.date(2026, 7, 15)

    errors: list[float] = []
    for d, actual in sorted(cons.items()):
        if not (holdout_start <= d <= holdout_end):
            continue
        if _in_outage(d) or d in _NEGATIVE_DAYS or actual <= 0:
            continue
        t = temp.get(d)
        if t is None:
            continue
        pred = _predict(d, t)
        errors.append(abs(actual - pred))

    assert errors, "no holdout days evaluated — check CSV paths"
    mae = sum(errors) / len(errors)
    # R1 invariant.
    assert mae <= 20.0, (
        f"holdout MAE {mae:.2f} kWh exceeds R1 invariant (20.0). "
        "Coefficients likely tampered / re-fit needed."
    )
    # Per-day: no day should be *hopelessly* far off. 110 kWh caps genuine
    # outlier days (single observed worst = 91 kWh on a real load-event day)
    # while still failing on grossly tampered coefficients (a sign flip on
    # cdd_coeff blows this ceiling away in summer — the mutation-anchor).
    worst = max(errors)
    assert worst <= 110.0, (
        f"worst-case daily error {worst:.2f} kWh exceeds sanity ceiling. "
        "Coefficients likely tampered."
    )


# ============================================================================
# Test B — DOW arm not consulted by v1 path (parity claim)
# ============================================================================

def _make_predictor() -> DailyEnergyPredictor:
    hass = MagicMock()
    # weather entity returns a fixed temp attribute
    hass.states.get = MagicMock(return_value=None)
    p = DailyEnergyPredictor(hass)
    return p


def test_dow_arm_removed_from_v1_path():
    """v1 arm output must be independent of the consumption_history[dow] deque.

    B0 §E: day-of-week R² = 0.01 → dead signal. Plan says removed. During
    shadow the DOW arm is still present as the CONSUMED path — this test
    proves the v1 arm output itself does NOT read the DOW history.
    """
    p = _make_predictor()
    now = dt.datetime(2026, 7, 15, 12, 0)
    temp = 82.0

    v1_no_history, base_no, ev_no, src_no = p._compute_v1(now, temp)
    assert src_no == PRED_CONSUMPTION_SOURCE_V1_REGRESSION

    # Poison the DOW deque with a huge value; v1 output must NOT budge.
    for dow_i in range(7):
        p._consumption_history[dow_i].extend([9999.0] * 8)
    v1_with_poison, base_p, ev_p, src_p = p._compute_v1(now, temp)

    assert v1_with_poison == pytest.approx(v1_no_history, abs=1e-6)
    assert base_p == pytest.approx(base_no, abs=1e-6)
    assert ev_p == pytest.approx(ev_no, abs=1e-6)


# ============================================================================
# Test C — shadow gate isolates the consumer path
# ============================================================================

def test_estimator_shadow_only_gates_consumer(monkeypatch):
    """Shadow gate ON → CONSUMED value is the legacy DOW baseline, NOT the
    v1 number. Shadow values still populate for observability + R2 gate.
    """
    monkeypatch.setattr(_ef, "CONF_R1_ESTIMATOR_SHADOW_ONLY", True)

    p = _make_predictor()
    # Load a distinctive DOW baseline so we can tell it apart from v1.
    for dow_i in range(7):
        p._consumption_history[dow_i].extend([200.0])
    now = dt.datetime(2026, 7, 15, 12, 0)
    temp = 82.0

    consumed = p._estimate_consumption(now, temp)
    v1_expected, _, _, _ = p._compute_v1(now, temp)

    # Legacy DOW baseline 200 → adjusted ≈ 200 (temp>75 factor 1.0), factor 1.0.
    assert consumed == pytest.approx(200.0, rel=0.02), (
        f"shadow=True must publish the legacy value, got {consumed}"
    )
    assert consumed != pytest.approx(v1_expected, rel=0.02), (
        "shadow gate leaked: consumed value equals the v1 number"
    )
    # v1 stashed as shadow.
    assert p._shadow_predicted_consumption_kwh == pytest.approx(v1_expected, abs=0.02)
    assert p._predicted_consumption_source in (
        PRED_CONSUMPTION_SOURCE_DOW_LEGACY,
        PRED_CONSUMPTION_SOURCE_FALLBACK,
    )


def test_source_marker_v1_when_shadow_off(monkeypatch):
    monkeypatch.setattr(_ef, "CONF_R1_ESTIMATOR_SHADOW_ONLY", False)

    p = _make_predictor()
    now = dt.datetime(2026, 7, 15, 12, 0)
    temp = 82.0

    consumed = p._estimate_consumption(now, temp)
    v1_expected, _, _, _ = p._compute_v1(now, temp)

    assert p._predicted_consumption_source == PRED_CONSUMPTION_SOURCE_V1_REGRESSION
    assert consumed == pytest.approx(v1_expected, abs=0.02)


def test_source_marker_legacy_when_shadow_on(monkeypatch):
    monkeypatch.setattr(_ef, "CONF_R1_ESTIMATOR_SHADOW_ONLY", True)

    p = _make_predictor()
    for dow_i in range(7):
        p._consumption_history[dow_i].extend([150.0])
    now = dt.datetime(2026, 7, 15, 12, 0)
    temp = 82.0

    p._estimate_consumption(now, temp)
    # Source must NEVER be v1_regression while the shadow gate is on —
    # this is the runtime side of I-NE5.
    assert p._predicted_consumption_source != PRED_CONSUMPTION_SOURCE_V1_REGRESSION


# ============================================================================
# Test D — EV era gate
# ============================================================================

def test_ev_era_gate_zero_before_start():
    p = _make_predictor()
    ev_era = dt.datetime.strptime(
        CONSUMPTION_REGRESSION_V1["ev_era_start"], "%Y-%m-%d"
    ).date()
    before = dt.datetime.combine(ev_era - dt.timedelta(days=1), dt.time(12))
    on     = dt.datetime.combine(ev_era, dt.time(12))
    temp = 75.0

    _, base_b, ev_b, _ = p._compute_v1(before, temp)
    _, base_o, ev_o, _ = p._compute_v1(on, temp)

    assert ev_b == 0.0
    assert ev_o == pytest.approx(CONSUMPTION_REGRESSION_V1["ev_term_kwh"], abs=1e-6)
    # base changes only via season dummy at the winter/spring boundary
    # (both dates are within same month in practice, but do not assert
    # equality — only that ev-era term is 0 vs constant).


# ============================================================================
# Test E — fit script is reproducible + agrees with baked constants
# ============================================================================

def test_fit_script_reproducible():
    """Import scripts/energy/fit_consumption_regression.py, run
    fit_and_report(), and assert the resulting coefficients + ev_term match
    the checked-in CONSUMPTION_REGRESSION_V1 to 4 decimals.

    Also asserts the holdout MAE reported by the script is ≤ 20 kWh — the
    R1 invariant, evaluated on the exact split the constants were fit
    against.
    """
    spec = importlib.util.spec_from_file_location(
        "_r1_fit_script",
        os.path.join(REPO_ROOT, "scripts", "energy", "fit_consumption_regression.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    r = mod.fit_and_report()
    beta = r["beta"]
    c = CONSUMPTION_REGRESSION_V1

    assert round(beta[0], 4) == c["base"]
    assert round(beta[1], 4) == c["cdd_coeff"]
    assert round(beta[2], 4) == c["hdd_coeff"]
    assert round(beta[3], 4) == c["season_spring"]
    assert round(beta[4], 4) == c["season_summer"]
    assert round(beta[5], 4) == c["season_fall"]
    assert round(r["ev_term_kwh_per_day"], 4) == c["ev_term_kwh"]

    assert r["holdout_mae_combined"] <= mod.HOLDOUT_MAE_INVARIANT_KWH
