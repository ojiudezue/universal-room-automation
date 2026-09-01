# v5.92.2 — forecast_accuracy unmasked (split display metric; control path untouched)

**Card:** `FORECAST-ACCURACY-UNKNOWN-MASK-1`
**Tier:** 1-2 display fix (plan-review + confirm-review + 2 framing-disjoint build-reviews + validator name-diff + live). Control path proven byte-identical.
**Merge:** `feature/forecast-accuracy-unmask` → develop.

## Problem

`sensor.ura_energy_coordinator_forecast_accuracy` read **`unknown`** while it actually had 30 samples and was active — the value was *hidden*, not missing. Two defects:
1. **Mask conflated NO-DATA with POOR.** `native_value` returned `None` whenever accuracy ≤ 0 (`return accuracy if accuracy > 0 else None`), so "no forecast yet" and "the forecaster is badly inaccurate" both rendered identically as `unknown`. Since `rolling_accuracy = max(0, 100 − avg_abs_pct_error)`, any window whose mean absolute percent error ≥ 100% pinned the sensor to `unknown`.
2. **Percent-error blow-up.** `pct_error = error / max(|predicted|, 0.1) * 100` produces ~44,900% for a near-zero prediction (predicted 0.1, actual 45) — one such row poisons the 7-window mean for a week.

## Solution — split the display metric from the control metric

The key finding (caught in plan-review): `pct_error` feeds **both** the sensor **and** `adjustment_factor`, which multiplies `_predicted_consumption_kwh` consumed by the DP house-load estimator. Changing its denominator would have been a **control-loop change**, not a display fix. So Rev 2 **splits** the metric:

- **`pct_error` is byte-identical** (`energy_forecast.py:866`) — the control path (`get_adjustment_factor`, `_solar_forecast_error_baseline.update`, the `energy_daily.prediction_error_pct` payload) is untouched. `energy.py` is not in the diff.
- A **new `pct_error_bounded`** (SMAPE-style: denom `max(|pred|, |actual|, MIN_DENOMINATOR_KWH=5.0)`, then `±PCT_ERROR_BOUND=200`) is consumed **only** by `rolling_accuracy` and the sensor. `restore_from_db` recomputes it from stored `(predicted, actual)` — no schema migration.
- **Sensor renders three discriminated states** that never share a `(value, status)` signature: `learning` (samples < 3 → `None`), `active` (healthy), `poor` (`rolling_accuracy ≤ POOR_THRESHOLD_PCT=50`, numeric — no longer masked), plus a **`stale`** overlay (`eval_age_days ≥ STALE_EVAL_DAYS` via a new `eval_age_days` attribute; defensive `date.fromisoformat`).

**Knobs (module const rung):** `MIN_DENOMINATOR_KWH=5.0`, `PCT_ERROR_BOUND=200.0`, `POOR_THRESHOLD_PCT=50.0`, `STALE_EVAL_DAYS=2`.

## Reviews

Plan-review = FIX-REQUIRED (caught the display-vs-control conflation) → split-metric adopted → dropped from Tier 2-DB to Tier 1-2. Confirm-review = clean (control path isolated via the return-dict channel `energy_forecast.py:862`). Build-review **B (control-path)** = SHIP — byte-identity confirmed against the real diff. Build-review **A (correctness)** = FIX-REQUIRED, one HIGH: the sensor mask fix had zero test coverage (hollow anchor) → fixed by adding 5 sensor-level tests. **14 tests total**; two RED drills confirmed (neuter `if samples<3: return None` → RED; reorder the status ladder → RED); the `pct_error` mutation at `:866` turns `test_evaluate_accuracy_production_call_preserves_pct_error` RED. Validator full-suite name-diff: see below.

### Acceptance criteria
- **Verify:** `forecast_accuracy` renders a numeric POOR value (not `unknown`) when the forecaster is inaccurate; `learning`/`stale`/`poor`/`active` never share a `(value, status)` pair.
- **Verify:** the energy control path is byte-identical — `adjustment_factor` and DP `house_load_kw` unchanged (no measurable shift).
- **Test:** 14 tests incl. `test_evaluate_accuracy_production_call_preserves_pct_error` (byte-identity anchor) + the 5 sensor-signature tests.
- **Live:** post-restart, `sensor.ura_energy_coordinator_forecast_accuracy` shows a numeric value with a `status` attribute (not bare `unknown`); `eval_age_days` present; no new URA ERRORs; DP house-load behavior unchanged.

## Pre-deploy gate
0 conflict markers; py_compile clean; 14 cycle tests pass; full-suite name-diff vs develop = (recorded below).

## Validated <date> (post-restart)
_(to be filled after deploy + HA restart)_
