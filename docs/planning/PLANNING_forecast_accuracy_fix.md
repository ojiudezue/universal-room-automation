# PLANNING — Forecast Accuracy Sensor Fix (Rev 3)

**Status:** Approved to build (operator, 2026-09-01). Rev 3 applies
plan-review Rev-2 fix-ups (M1/L1/L2/L3); the split-metric design of
Rev 2 was confirmed CLEAN (control path genuinely isolated via the
return-dict at `energy_forecast.py:862`; restore split sound; no
decision-path leak; no schema migration).
**Tier:** **Tier 1-2 — display fix.** With the control-path
`pct_error` held byte-identical (see D2), the change no longer touches
`adjustment_factor` or `_solar_forecast_error_baseline`. Two reviews
(A = correctness + discrimination + display arithmetic;
B = restore/scheduling/no-control-ripple) + live validation. Not
Tier 2-DB.
**Rationale for the tier drop from Rev 1:** Rev 1's D2 mutated the
denominator of `pct_error` at `energy_forecast.py:850`. The reviewer
correctly noted that field feeds BOTH the sensor
(`rolling_accuracy` at :887) AND the DP control path
(`get_adjustment_factor` at :875 → `_predictor._adjustment_factor` at
energy.py:1437/2829 → `_estimate_consumption` at
energy_forecast.py:410 → DP `house_load_kw` at energy.py:4337). A
denominator swap there asymmetrically damps the exact
under-prediction correction the adjustment factor exists to make,
and produces a boot-time >10% step in `house_load_kw` — breaching the
Rev-1 acceptance gate. Rev 2 preserves the field byte-identical and
introduces a parallel bounded metric consumed ONLY by the sensor.

Symptom: `sensor.ura_energy_coordinator_forecast_accuracy` = `unknown`
with 30 samples, status active, last_eval 2026-08-30.

---

## Institutional context verified

### Producer + Consumer map (Rev 2/3 — split into two metrics)

**Existing field — `pct_error` (control-path, UNTOUCHED in this cycle)**
- Produced at `energy_forecast.py:850`:
  `pct_error = (error / max(abs(predicted), 0.1)) * 100`.
- Stored per-row in `_daily_errors` (:857).
- Also returned to the caller in the result dict at
  `energy_forecast.py:862` — this is the isolation boundary the split
  relies on: `evaluate_accuracy`'s return contract exposes
  `{"error_kwh", "pct_error"}` and only that; the bounded value never
  leaves the tracker through the return path.
- Consumed by:
  - `AccuracyTracker.get_adjustment_factor()` at :875 (mean signed
    over last 7, `1.0 + avg/100 * 0.3`, clamped `[0.7, 1.3]`).
  - `_solar_forecast_error_baseline.update(abs(pct_error))` at
    `energy.py:2833` (reads the return-dict `pct_error`, not the
    deque).
  - DAO write `prediction_error_pct` at `energy.py:2845, 2853-2857`
    → `energy_daily` schema (`database.py:1841`) (also reads the
    return-dict `pct_error`).
- Downstream of `get_adjustment_factor` → `_predictor._adjustment_factor`
  (`energy.py:1437, 2829`) → `_estimate_consumption` (`energy_forecast.py:410`)
  → `_predicted_consumption_kwh` → DP `house_load_kw` (`energy.py:4337-4341`,
  `_dp_house_load_source = "max_span_r1"` default).
- **Cycle invariant:** every one of the above call sites reads the
  same field, computed by the same expression, storing the same
  rounded value in `energy_daily`. Rev 2/3 leaves every byte of this
  chain unchanged.

**NEW field — `pct_error_bounded` (display-only)**
- Computed alongside `pct_error` in `evaluate_accuracy`:
  ```
  denom = max(abs(predicted), abs(actual), MIN_DENOMINATOR_KWH)
  raw   = (error / denom) * 100
  bounded = max(-PCT_ERROR_BOUND, min(PCT_ERROR_BOUND, raw))
  ```
- Stored per-row in `_daily_errors` alongside `pct_error` (deque
  entries gain one more key; no schema change).
- Consumed **ONLY** by:
  - `AccuracyTracker.rolling_accuracy` (redirected from `pct_error` to
    `pct_error_bounded`).
  - `EnergyForecastAccuracySensor` attributes (indirectly, via
    `get_status()['rolling_accuracy_pct']`).
- **Not persisted to `energy_daily`.** Recomputable from
  `(predicted_consumption_kwh, consumption_kwh)` on restore, so the
  schema and every existing reader are untouched.
- **Not returned from `evaluate_accuracy`.** The return dict at
  `energy_forecast.py:860-863` MUST continue to expose only
  `{"error_kwh", "pct_error"}`; adding the bounded key to the return
  contract would risk a future caller consuming it as a control input.

**Full consumer map for `rolling_accuracy` (Rev 3 completion of L3)**
- `AccuracyTracker.rolling_accuracy` (`energy_forecast.py:882-888`) —
  the property being redirected in D2.
- `AccuracyTracker.get_status()['rolling_accuracy_pct']`
  (`energy_forecast.py:893`) — used by the sensor attrs path and by
  `get_energy_summary`.
- `energy.py:9668-9670` — `EnergyCoordinator.forecast_accuracy`
  property (bare pass-through to `self._accuracy.rolling_accuracy`).
  DISPLAY hop; no decision consumer.
- `sensor.py:11372` — `EnergyForecastAccuracySensor.native_value`
  (reads `energy.forecast_accuracy`). DISPLAY.
- `sensor.py:11383` — `EnergyForecastAccuracySensor.extra_state_attributes`
  reads `energy._accuracy.get_status()`. DISPLAY.
- `energy.py:10296` — `EnergyCoordinator.get_energy_summary()`
  includes `"accuracy": self._accuracy.get_status()`. Downstream:
  `binary_sensor.py:2497` reads `summary` but only pulls
  `envoy_unavailable_count` and `envoy_last_available` — the
  `accuracy` sub-dict is IGNORED. **Benign, non-decision.** Named
  here so a future reviewer does not re-derive it.

**Daily-eval scheduling** — unchanged. `_maybe_reset_daily`
(`energy.py:2708`) runs from `_do_cycle` (`:5819`) every EC cycle;
`_last_eval_date` advances only on a successful evaluate (both
`predicted` and `actual` non-None). The 2-day stale window is
consistent with `actual_kwh` being dropped by the negative-delta
guard (`:2760`) or the ≤0 guard (`:2796`) on Envoy snapshot
hiccups — a data-availability event, not a scheduler regression.

### Greps + prior-art disposition (Rev 2/3)

- **REUSED — `AccuracyTracker`** at `energy_forecast.py:793` (extend
  in place; do not add a new tracker).
- **REUSED — `EnergyForecastAccuracySensor`** at `sensor.py:11344`
  (fix `native_value` + attrs; no new entity).
- **NEW — internal deque key `pct_error_bounded`** in
  `AccuracyTracker._daily_errors[*]`. Not a new public surface; no
  new CONF_*, DAO, sensor, or entity. Explicitly NOT added to the
  `evaluate_accuracy` return dict.
- **NEW module constants** (rung 1 — module constants; not exposed):
  - `PCT_ERROR_BOUND = 200.0` — hard cap on the bounded metric. This
    IS load-bearing: without it a single day with `predicted≈0` and a
    normal `actual` still exceeds the SMAPE ~100% mark by the sign
    convention chosen; the ±200 cap guarantees a single row moves the
    7-window mean by at most `200/7 ≈ 28.6` pp, well below the 100 pp
    needed to pin the sensor to 0.
  - `POOR_THRESHOLD_PCT = 50.0` — rolling_accuracy at or below which
    `status = "poor"`. `50.0` (not `0.0`) makes POOR reachable in
    practice under the bounded metric; `0.0` would render POOR
    nearly unreachable (Rev-1 reviewer catch).
  - `STALE_EVAL_DAYS = 2` — degrade `status` to `"stale"` when
    `eval_age_days >= STALE_EVAL_DAYS`. Comparison is `>=` (not `>`)
    so the observed 2-day gap (last_eval 08-30 on 09-01, age=2)
    trips the flag; a `>` bug was the reason this constant matters
    at all.
- **DROPPED as "load-bearing"** — `MIN_DENOMINATOR_KWH`. Kept as a
  belt-and-suspenders floor in the bounded metric denominator with
  value `5.0`, but not justified as the primary defense: the restore
  path already filters `consumption_kwh >= 10.0` at
  `energy.py:1432-1434`, and the bounded metric's outer clamp is the
  actual guard. Reviewer C would find no site whose neuter this
  constant uniquely detects. Documented as a defensive floor, not a
  load-bearing knob.

### Prior planning docs consulted
- `docs/planning/PLANNING_v4.7.x_advanced_energy_management.md` —
  origin of the forecaster-first thesis; LightGBM never wired
  (memory `project_advanced_energy_mgt_v47x`), so today's
  `AccuracyTracker` is what ships and its `adjustment_factor` IS the
  learning loop feeding DP. Confirms why the control-path field
  must not be perturbed by a display fix.
- `docs/user-manual/ENERGY_COORDINATOR.md` — sensor is diagnostic;
  operator semantics limited to "7-day rolling %".
- `docs/plans/ENERGY_COORDINATOR_PLAN.md` — Sub-Cycle E5 (accuracy +
  Bayesian adjustment).
- `docs/readmes/README_v3.7.9.md`, `README_v3.14.0.md`,
  `README_v3.14.6.md` — accuracy-sensor iterations; no prior fix to
  the `>0 else None` mask.

### Design docs read
- `docs/COORDINATOR_DIAGNOSTICS_FRAMEWORK_v2.md` — the discriminate
  "no data" vs "degraded" convention.

### Code locations surveyed
- `energy_forecast.py` full (1083 lines) — `AccuracyTracker`
  :793-897, `DailyEnergyPredictor` :43-790, `_estimate_consumption`
  :345-410.
- `energy.py`: `_maybe_reset_daily` :2708-2880 (evaluate call at
  :2816, adjustment feedback at :2829, solar-error baseline at
  :2833, DAO write at :2848-2858); restore-from-DB :1420-1446; DP
  house-load estimator :4320-4352; `forecast_accuracy` property
  :9667-9670; `get_energy_summary` accuracy sub-dict :10296.
- `sensor.py`: `EnergyForecastAccuracySensor` :11344-11390.
- `binary_sensor.py:2490-2501` — the `get_energy_summary` consumer
  that reads only envoy counts (confirms L3 benign).
- `database.py`: `energy_daily` schema :1830-1850; restore query
  :4430-4445.

### Memory bodies pulled
- `project_advanced_energy_mgt_v47x` — forecaster/LightGBM not wired;
  AccuracyTracker is the shipping mechanism.
- `feedback_coincidental_equality_masks_concept_split` — the
  `>0 else None` mask conflates NO-DATA and POOR into one rendered
  state; the exact concept-split this cycle discriminates.
- `feedback_falsify_before_asserting` — DISCRIMINATING acceptance
  criteria (see below).
- `feedback_marginal_benefit_pushback` — Rev 2/3 is the marginal-benefit
  answer: the display defect is fixable without touching the control
  loop; do the smaller fix.
- `feedback_hollow_test_anchors` — motivates M1: an invariant must
  be anchored by a test that drives the PRODUCTION computation, not
  a test that seeds the deque directly.

---

## Falsifiable invariant

> **(a) Discrimination:** The sensor
> `ura_energy_coordinator_forecast_accuracy` renders four states with
> distinct **(value, status)** signatures; no two states share the
> same **signature** (value + status attribute together — STALE
> deliberately overlays the same numeric value that HEALTHY/POOR
> would render, and is discriminated by `status == "stale"` and the
> `eval_age_days` attribute):
> 1. **NO-DATA** — samples < 3 → native `unknown`,
>    `status = "learning"`, `adjustment_factor = 1.000`.
> 2. **HEALTHY** — samples ≥ 3 AND `rolling_accuracy > POOR_THRESHOLD_PCT`
>    AND `eval_age_days < STALE_EVAL_DAYS` → native is a numeric
>    value in `(POOR_THRESHOLD_PCT, 100.0]`, `status = "active"`.
> 3. **POOR** — samples ≥ 3 AND `rolling_accuracy <= POOR_THRESHOLD_PCT`
>    AND `eval_age_days < STALE_EVAL_DAYS` → native is a real numeric
>    in `[0.0, POOR_THRESHOLD_PCT]` (**including 0.0, NOT `unknown`**),
>    `status = "poor"`.
> 4. **STALE overlay** — samples ≥ 3 AND
>    `eval_age_days >= STALE_EVAL_DAYS` → native is the last known
>    numeric rolling accuracy (NOT nulled), `status = "stale"`,
>    `eval_age_days` present in attrs. Discriminated from HEALTHY /
>    POOR by the status attribute, not by value.
>
> **(b) Control-path byte-identity:** For any sequence of
> `(predicted, actual, date)` inputs driven through the PRODUCTION
> `AccuracyTracker.evaluate_accuracy` call (not a hand-seeded deque),
> the value returned in the result dict's `pct_error` key, the value
> stored in `_daily_errors[*]["pct_error"]`, the value returned by
> `AccuracyTracker.get_adjustment_factor()`, the value written to
> `energy_daily.prediction_error_pct`, and the value fed to
> `_solar_forecast_error_baseline` are BYTE-IDENTICAL to their pre-fix
> equivalents. Anchored by a production-drive test (D4 test 8) that
> makes the exact call `evaluate_accuracy(0.1, 45.0, <date>)` and
> asserts `pct_error == 44900.0` in BOTH the return dict AND the
> deque entry while `pct_error_bounded == 200.0` in the deque. This
> test goes RED if `energy_forecast.py:850`'s denominator is ever
> mutated.

Any observation that shows two of {NO-DATA, HEALTHY, POOR, STALE}
sharing the same **(value, status)** signature, OR any observation
that shows the production `evaluate_accuracy` returning a different
`pct_error` for the same `(predicted, actual)` inputs, falsifies the
invariant.

---

## Diagnosis

**D-real, high confidence — display mask (defect A).**
`sensor.py:11373`: `return accuracy if accuracy > 0 else None`.
`rolling_accuracy` is floored at 0 by `max(0, 100 - avg_abs_error)`
(`energy_forecast.py:888`). A single unbounded pct_error row is
enough to drag the 7-window mean above 100 → sensor pinned to
`unknown` (NO-DATA / POOR conflation).

**D-real, mechanism verified — pct_error blowup (defect B).**
`pct_error = error / max(abs(predicted), 0.1) * 100` at
`energy_forecast.py:850`. With `predicted=0.1, actual=45`,
`pct_error = 44 900%`. One such row poisons the 7-window mean for a
week. Rev 2/3 does **not** fix this at the source (that's a control-loop
change); instead it adds a parallel bounded metric that the sensor
consumes, and leaves the control path to see the unchanged value
that `get_adjustment_factor` was designed around.

**D-real, correctness — stale-eval visibility (defect D).**
`_maybe_reset_daily` runs every cycle; `_last_eval_date` advances
only on a successful evaluate. Two-day stale window with
`samples = 30` (restored from DB) is a data-availability event, not
a scheduler bug. Visibility fix only: expose `eval_age_days`,
`status = "stale"` at `eval_age_days >= STALE_EVAL_DAYS` (comparison
matters — see below).

**Rev-1 comparison bug caught in re-review** — a `>` comparison with
`STALE_EVAL_DAYS = 2` would NOT trip on the observed
`08-30 → 09-01` (age = 2) case that motivated the deliverable. Rev
2/3 uses `>=` (and would still trip at `STALE_EVAL_DAYS = 1` if a
future tuning wanted a tighter window).

**Not a defect right now — the producer.** `_estimate_consumption`
returns `max(0.1, adjusted * _adjustment_factor)` (:410). Producer
degeneracy IS possible in extreme edge cases (v1 arm with no
CDD/HDD, EV term off, small season dummy) but the legacy fallback
baseline is 45.0. The D0 probe measures whether any historical
`predicted_consumption_kwh` was near zero; if it was, that is a
scope-B cycle. This cycle prevents the display observability from
being broken by such rows.

---

## Deliverables

### D0 — Read-only probe (BEFORE code changes)

Verify (i) the live entity_id and (ii) the historical pct_error
distribution.

**Entity-id verify.** `sensor.py:11360` sets
`unique_id = "{DOMAIN}_energy_forecast_accuracy"`. HA composes the
entity_id from `has_entity_name = True` + the device name (from
`_energy_device_info()` → "URA: Energy Coordinator") + the entity
name ("Forecast Accuracy"), yielding
`sensor.ura_energy_coordinator_forecast_accuracy`. The
`energy_forecast.py:1` docstring's mention of
`sensor.ura_energy_forecast_accuracy` is legacy prose. **Confirm on
the live instance** via MCP `ha_get_state` before build; whichever
form the live instance actually publishes is the acceptance target.

**DB probe.** One `ssh ha sqlite3` query:

```sql
SELECT date, consumption_kwh, predicted_consumption_kwh,
       prediction_error_pct, adjustment_factor
FROM energy_daily
ORDER BY date DESC LIMIT 30;
```

Record in "Probe results" (bottom). Gate: if every row has
`abs(prediction_error_pct) < 100` AND the live sensor is still
`unknown`, defect B is not the active cause — reopen diagnosis. If
any row is ≥100%, defects A + B are live and D1 + D2 both ship.

### D1 — Sensor mask fix (defect A)

**File:** `sensor.py`, `EnergyForecastAccuracySensor` (~:11364-11390).

- `native_value`: return the numeric `rolling_accuracy` whenever
  `samples >= 3`; return `None` (unknown) **only** when
  `samples < 3`. Do NOT mask `0.0` as unknown.
- `extra_state_attributes`: add `eval_age_days` (int days from
  `last_eval_date` to today; see L1 note below), and set `status`
  per the invariant. **The evaluation order is load-bearing** —
  `samples < 3` MUST be checked FIRST because it shields the
  `eval_age_days >= STALE_EVAL_DAYS` comparison from a `None`
  operand (`None >= 2` is a `TypeError` in Python 3). Both writers
  of `_last_eval_date` (:820 restore path and :848 evaluate path)
  set a non-empty string before appending to `_daily_errors`, so
  `samples >= 3` implies `_last_eval_date` is a non-empty string —
  the ordering makes the `TypeError` unreachable in practice, and
  the plan calls it out so the builder does not reorder the branch:
  - `samples < 3` → `"learning"`
  - `eval_age_days is None` OR `eval_age_days >= STALE_EVAL_DAYS`
    → `"stale"` (overrides active/poor). `None` here can only arise
    from an unparseable `_last_eval_date`; see next bullet.
  - `rolling_accuracy <= POOR_THRESHOLD_PCT` → `"poor"`
  - else → `"active"`
- **Unparseable `_last_eval_date` handling (L1).** `_last_eval_date`
  is a bare `str` field defaulted to `""` (`energy_forecast.py:803`),
  populated verbatim from DB rows (`:816, :826`) and from
  `evaluate_accuracy`'s `prediction_date` argument (`:848`) with no
  format validation. The `get_status()` `eval_age_days` computation
  MUST tolerate:
  - `""` (default, no eval ever recorded and samples < 3) →
    `eval_age_days = None`. Only reachable via NO-DATA, which
    short-circuits on `samples < 3` before the STALE check.
  - a non-ISO string (defensive; not observed in code today, but the
    field has no schema guard) → catch `ValueError`/`TypeError`
    from `date.fromisoformat`, log at DEBUG, return
    `eval_age_days = None`, and treat as `"stale"` in the D1 status
    ladder so an unparseable date is visible rather than silently
    treated as HEALTHY.
- Existing `adjustment_factor`, `samples`, `last_eval_date` attrs
  retained unchanged.

### D2 — Add `pct_error_bounded` (parallel to `pct_error`, display-only)

**File:** `energy_forecast.py`.

- In `evaluate_accuracy` (~:833-863): compute `pct_error` **exactly
  as today** (:850, byte-identical — do not touch that line). Then
  additionally compute:
  ```python
  denom = max(abs(predicted_kwh), abs(actual_kwh), MIN_DENOMINATOR_KWH)
  raw_bounded = (error / denom) * 100
  pct_error_bounded = max(-PCT_ERROR_BOUND, min(PCT_ERROR_BOUND, raw_bounded))
  ```
  and store it in the deque entry alongside `pct_error`:
  ```python
  self._daily_errors.append({
      "date": prediction_date,
      "predicted": predicted_kwh,
      "actual": actual_kwh,
      "error": round(error, 2),
      "pct_error": round(pct_error, 1),              # UNCHANGED
      "pct_error_bounded": round(pct_error_bounded, 1),  # NEW
  })
  ```
  Return value of `evaluate_accuracy` is UNCHANGED (still
  `{"error_kwh", "pct_error"}` at :860-863). The bounded value is
  DELIBERATELY NOT added to the return contract — the return dict
  is the isolation boundary between the display path and the
  control path.
- `rolling_accuracy` (~:882-888): read
  `e["pct_error_bounded"]` instead of `e["pct_error"]`. This is the
  only reader migration. `get_adjustment_factor` (~:865-879) is
  UNTOUCHED and continues to read `pct_error`.
- `restore_from_db` (~:805-831): when the DB row has both
  `consumption_kwh` and `predicted_consumption_kwh` (which it must
  to have been included per :817), **recompute**
  `pct_error_bounded` from `(predicted, actual)` at restore time
  rather than relying on any stored value. This gives a homogeneous
  deque without schema migration. The stored `prediction_error_pct`
  from DB continues to populate `pct_error` verbatim (control path
  byte-identity across restart).
- `get_status` (~:890-897): add `eval_age_days` (computed from
  `_last_eval_date` per D1's parse rules); leave the other three
  keys unchanged.

New module constants at the top of `energy_forecast.py` (near
`ACCURACY_WINDOW_DAYS`):
- `MIN_DENOMINATOR_KWH = 5.0` — defensive floor in the bounded
  denominator. NOT load-bearing (the outer ±200 clamp is the actual
  guard; `energy.py:1432` restore filter drops `<10 kWh` rows). Kept
  for clarity + belt-and-suspenders.
- `PCT_ERROR_BOUND = 200.0` — hard cap on any single-day bounded
  error; ensures one row moves the 7-window mean by ≤ 28.6 pp.
- `POOR_THRESHOLD_PCT = 50.0` — rolling accuracy at or below which
  `status = "poor"`. `50.0` makes the state reachable in practice.
- `STALE_EVAL_DAYS = 2` — `status = "stale"` when
  `eval_age_days >= STALE_EVAL_DAYS`.

### D3 — Stale-eval visibility (defect D, comparison-correct)

Already folded into D1 (sensor attr + status overlay) and D2 (`get_status`
adds `eval_age_days`). Explicit call-out here because the comparison
detail matters: `>=` (not `>`), so the observed 2-day gap
(`last_eval = 08-30`, today = `09-01` → age = 2) actually flags.

### D4 — Tests (behavioral, per-site-neuter verifiable)

**File:** `quality/tests/test_energy_forecast_accuracy.py` (new;
there are ZERO existing tests for `AccuracyTracker`, so every
anchor in this file is the sole guard for its production site).

1. `test_no_data_returns_unknown` — 0 samples → `native_value is
   None`, `status == "learning"`, `adjustment_factor == 1.0`.
2. `test_healthy_reports_numeric` — 5 samples with `pct_error ∈
   [-10, 10]` → sensor in `(POOR_THRESHOLD_PCT, 100]`,
   `status == "active"`.
3. `test_poor_reports_numeric_not_unknown` — 7 samples all with
   bounded pct_error at `-PCT_ERROR_BOUND` → sensor is a real
   numeric `<= POOR_THRESHOLD_PCT` (including 0.0),
   `status == "poor"`. **Anchors D1 mask fix.**
4. `test_single_near_zero_prediction_does_not_pin_to_zero` — one
   row `(predicted=0.05, actual=45)` + six benign rows; assert
   `rolling_accuracy > 50`. **Anchors D2 bounded metric behavior.**
5. `test_restore_recomputes_bounded_from_predicted_actual` —
   restore a legacy row with stored `prediction_error_pct = -44900`
   but `(predicted, actual)` present; assert the deque entry has
   `pct_error == -44900.0` (control-path byte-identity, restored
   verbatim) AND `pct_error_bounded ∈ [-PCT_ERROR_BOUND, PCT_ERROR_BOUND]`
   (recomputed from predicted/actual). **Anchors D2 restore split.**
6. `test_stale_eval_reports_stale_status_at_exact_boundary` —
   set `_last_eval_date` to exactly `STALE_EVAL_DAYS` days ago;
   assert `status == "stale"` (guards the `>=` vs `>` bug).
7. `test_bounded_path_isolation_when_rolling_accuracy_neutered` —
   isolation check: build a deque of mixed rows including one
   44900% row. Snapshot `get_adjustment_factor()`,
   `energy_daily.prediction_error_pct` write payload, and the
   `_solar_forecast_error_baseline.update()` argument. Then in-test
   MONKEY-ROUTE `rolling_accuracy` back to `e["pct_error"]` and
   REPLAY the same inputs; assert the three control-path outputs
   are bit-for-bit unchanged. This proves the display-path reader
   swap did not leak into control readers — but note (M1) that it
   does NOT prove `energy_forecast.py:850` is still byte-identical
   because both baseline and replay would use the same seeded
   deque. The byte-identity proof is test 8.
8. **`test_evaluate_accuracy_production_call_preserves_pct_error`
   (M1 — the invariant-(b) anchor).** Call the PRODUCTION method
   directly: `result = tracker.evaluate_accuracy(predicted_kwh=0.1,
   actual_kwh=45.0, prediction_date="2026-09-01")`. Assert:
   - `result["pct_error"] == 44900.0` — the return-dict value from
     `energy_forecast.py:862` (matches the pre-fix arithmetic at
     :850 byte-for-byte).
   - `tracker._daily_errors[-1]["pct_error"] == 44900.0` — the
     stored deque value from :857.
   - `tracker._daily_errors[-1]["pct_error_bounded"] == 200.0` —
     the bounded metric hit the `+PCT_ERROR_BOUND` clamp
     (`44 · 100 / max(0.1, 45.0, 5.0) = 44·100/45 ≈ 97.78`,
     denominator becomes 45.0; NB re-verify with the exact
     arithmetic during build — if the SMAPE-form bounded value
     lands at ~97.8 rather than 200.0, adjust the assertion to
     that value and to a smaller `(predicted=0.01)` input so the
     bound-hit remains observable).
   - Also assert `result` does NOT contain a `"pct_error_bounded"`
     key (return-dict isolation).
   This is the RED-on-`:850`-mutation test: swap the denominator
   `max(abs(predicted_kwh), 0.1)` for `max(abs(predicted_kwh),
   abs(actual_kwh), 5.0)` in production and this test's first two
   assertions fail. Tests 5/7 stay green under the same mutation
   because they seed the deque directly and never exercise :850.
9. `test_adjustment_factor_clamp_unchanged` — verify
   `get_adjustment_factor()` result on a fixed set of pre-fix
   `pct_error` values equals a golden value captured from the
   pre-fix implementation. Secondary guard on control-path
   byte-identity (arithmetic downstream of :850).
10. `test_unparseable_last_eval_date_reports_stale` — set
    `_last_eval_date = "not-a-date"`, deque with ≥ 3 rows; assert
    `eval_age_days is None` in `get_status()` output and sensor
    `status == "stale"` (guards the L1 defensive parse).

Reviewer A (correctness) must run per-site source mutation to
verify each test fails when its anchored production site is
neutered, then restore. Reviewer B must verify tests 5, 7, 8, and
10 by actually running them (test 8 is the invariant-(b) proof;
test 7 is the isolation check, not the byte-identity proof).

---

## Acceptance criteria (DISCRIMINATING)

- **Verify — NO-DATA discriminated:** Cleared deque →
  `sensor.<verified-id>` is `unknown`, `attributes.status ==
  "learning"`, `attributes.samples < 3`.
- **Verify — HEALTHY discriminated:** ≥3 samples with mean abs
  bounded pct_error < POOR_THRESHOLD_PCT → sensor numeric in
  `(POOR_THRESHOLD_PCT, 100]`, `attributes.status == "active"`.
- **Verify — POOR discriminated (the primary differentiator):** ≥3
  samples with mean abs bounded pct_error ≥ POOR_THRESHOLD_PCT →
  sensor is a real numeric in `[0.0, POOR_THRESHOLD_PCT]` (state
  string `"0.0"` or higher, **NOT `"unknown"`**),
  `attributes.status == "poor"`. **NO-DATA and POOR MUST NOT share
  the same (value, status) signature.**
- **Verify — STALE overlay discriminated by status:**
  `eval_age_days >= STALE_EVAL_DAYS` → sensor value is the last
  known numeric rolling_accuracy, `attributes.status == "stale"`,
  `attributes.eval_age_days == observed_age`. Boundary case
  (`age == STALE_EVAL_DAYS`) MUST trip (`>=` not `>`). STALE and
  HEALTHY/POOR may share a numeric value; discrimination is via
  the status attribute.
- **Verify — near-zero-prediction robustness:** A single day with
  `predicted_consumption_kwh = 0.1` and `actual = 45` does NOT drag
  `rolling_accuracy` below 50 on its own.
- **Verify — control-path byte-identity (M1):** The production
  call `evaluate_accuracy(0.1, 45.0, <date>)` returns a dict with
  `pct_error == 44900.0` and stores `pct_error == 44900.0` in the
  deque. `energy_daily.prediction_error_pct` payload for the same
  inputs is byte-identical to the pre-fix value.
  `_solar_forecast_error_baseline.update()` argument sequence is
  byte-identical. Proven by test 8 (primary) + test 9 (downstream
  arithmetic guard).
- **Sensor:** `sensor.<verified-id>` renders a real number in all
  of {HEALTHY, POOR, STALE}; only NO-DATA renders `unknown`. Attrs
  always include `{samples, status, adjustment_factor,
  last_eval_date, eval_age_days}`.
- **Test:** all ten tests in `test_energy_forecast_accuracy.py`
  pass; tests 8 and 10 in particular pass (they anchor the two
  Rev-3 fixes).
- **Live (post-restart):** MCP `ha_get_state` on
  `sensor.ura_energy_coordinator_forecast_accuracy` (or the
  verified id) returns a numeric value; `attributes.samples == 30`
  (or current DB count); `attributes.status ∈ {"active", "poor",
  "stale"}` (whichever the data warrants);
  `attributes.adjustment_factor ∈ [0.7, 1.3]`.
- **Live — DP invariant:** `sensor.ura_energy_dp_house_load_kw` (or
  equivalent DP debug surface) does not shift measurably pre/post
  deploy for the same conditions. Under Rev 2/3 the expected shift
  is ZERO (control path byte-identical); any observable shift means
  D2 leaked into the control path and is a blocker.

---

## Non-goals

- **Not changing `pct_error` (the control-path field).** Deliberate,
  per Rev 2/3. If the operator later wants to migrate the control
  path to a bounded metric, that is a Tier 2-DB cycle in its own
  right (adjustment_factor recalibration, DP `house_load_kw` step,
  etc.).
- **Not adding `pct_error_bounded` to `evaluate_accuracy`'s return
  dict.** The return-dict contract at `energy_forecast.py:860-863`
  IS the isolation boundary; extending it would risk a future
  caller consuming the bounded value as a control input.
- **Not migrating historical `energy_daily.prediction_error_pct`.**
  Restore reads it verbatim into `pct_error`; `pct_error_bounded` is
  recomputed from `(predicted, actual)` on restore.
- **Not fixing the producer** (near-zero `predicted_consumption_kwh`).
  D0 probe determines whether that is a real cycle; if so, card it.
- **Not fixing `actual_kwh` availability at midnight rollover.** The
  STALE overlay exposes when eval lags; the Envoy-snapshot question
  is separate.
- **Not touching `BatteryStrategy`.** It does not read
  `predicted_consumption_kwh` directly (verified by grep).
- **Not exposing `POOR_THRESHOLD_PCT`, `STALE_EVAL_DAYS`,
  `PCT_ERROR_BOUND`, or `MIN_DENOMINATOR_KWH` to the operator.**
  Rung 1 module constants. Promote to rung 2/3 only with evidence
  of legitimate observation-driven tuning need.
- **Not adding a new sensor or entity.** Extend the existing sensor
  in place.

---

## Review protocol — Tier 1-2 (two reviews + live validation)

The control-path byte-identity dissolves the Rev-1 rationale for
Tier 2-DB. Two framing-disjoint reviews suffice; Review A + B run
in parallel.

- **Review A — correctness + discrimination + display arithmetic.**
  Confirm the four states render distinct **(value, status)**
  signatures per the invariant (STALE deliberately shares the
  numeric with HEALTHY/POOR and is discriminated by status).
  Confirm the bounded-metric arithmetic (denom = max(|pred|,
  |actual|, MIN_DENOMINATOR_KWH); clamp to ±PCT_ERROR_BOUND).
  Confirm `POOR_THRESHOLD_PCT = 50.0` renders POOR reachable.
  Confirm the stale comparison is `>=`. Confirm the D1 status
  ladder checks `samples < 3` FIRST so `None >= STALE_EVAL_DAYS`
  cannot fire. Grep every reader of
  `_daily_errors[*]["pct_error"]` and every reader of
  `_daily_errors[*]["pct_error_bounded"]`; assert exactly ONE
  writer for each and exactly the intended readers (control-path
  readers must see only `pct_error`; display-path readers must see
  only `pct_error_bounded`). Grep `evaluate_accuracy` return-dict
  keys and assert exactly `{"error_kwh", "pct_error"}` — no
  bounded leak into the return path. Run per-site source mutation
  on each test anchor.
- **Review B — restore + scheduling + no-control-ripple.**
  End-to-end trace: DB row →
  `AccuracyTracker.restore_from_db` → deque entry (verify both keys
  set, `pct_error_bounded` recomputed from predicted/actual, not
  read from DB) → `rolling_accuracy` (reads bounded) →
  `get_adjustment_factor` (reads unbounded). **Actually run test 8**
  (the production-drive byte-identity proof) and test 7 (the
  isolation check) — this is the load-bearing reviewer check for
  Rev 3. Verify `_maybe_reset_daily` scheduling is untouched.
  Verify the `energy_daily` DAO write payload at
  `energy.py:2848-2858` is byte-identical (still writes the
  unbounded `pct_error`). Verify the full `rolling_accuracy`
  consumer map (L3): `energy.py:9668-9670` forecast_accuracy
  property, `sensor.py:11372/11383`, and
  `energy.py:10296` → `binary_sensor.py:2497` (the last one is a
  benign read that ignores the accuracy sub-dict; document, do not
  gate on).
- **Live Validation (Review C-live).** Post-restart: MCP-read the
  sensor across the three achievable states given current data;
  observe `eval_age_days`, `adjustment_factor`. Confirm DP
  `house_load_kw` shows ZERO measurable shift. Write results into
  the README per the standing rule.

Pre-review baseline tag per standing policy:
`git tag pre-review-v<version>`.

---

## Diff summary

### Rev 1 → Rev 2

- **Tier:** Tier 2-DB (3 framing-disjoint) → **Tier 1-2** (2 reviews
  + live). Rationale: control-path byte-identity dissolves the
  DP/adjustment-factor ripple that motivated Tier 2-DB in Rev 1.
- **Metric strategy:** REPLACE `pct_error` denominator → **SPLIT**
  into unchanged `pct_error` (control path) + new
  `pct_error_bounded` (display only). `energy_forecast.py:850`
  becomes byte-identical to today. `rolling_accuracy` (`:887`)
  switches its read to the bounded key.
- **Consumers touched:** Rev 1 rippled through
  `get_adjustment_factor`, `_solar_forecast_error_baseline`, DP
  `house_load_kw`. Rev 2 touches ONLY `rolling_accuracy` and the
  sensor. Consumer map simplified accordingly.
- **Restore path:** Rev 1 clamped stored `prediction_error_pct` on
  restore. **Rev 2 recomputes** `pct_error_bounded` from
  `(predicted, actual)` (both present in the DB row), leaving the
  restored `pct_error` byte-identical. Homogeneous deque, no schema
  migration.
- **`STALE_EVAL_DAYS` comparison:** Rev 1's implicit `>` would have
  missed the observed 2-day gap. **Rev 2 uses `>=`.**
- **`POOR_THRESHOLD_PCT`:** `0.0` → **`50.0`** so POOR is reachable
  in practice under the bounded metric.
- **`MIN_DENOMINATOR_KWH`:** dropped from "load-bearing knob"
  framing to defensive floor with explicit justification.
- **Entity id:** added D0 step to VERIFY the live entity id.
- **Falsifiable invariant:** was (a) discrimination only. Now
  **(a) discrimination + (b) control-path byte-identity**.
- **Tests:** Rev 1 had 7 tests. **Rev 2 has 8**, adding a
  neuter-the-bounded-path test.
- **DP invariant acceptance:** Rev 1 permitted <10% DP shift.
  **Rev 2 requires ZERO measurable shift.**
- **Non-goals:** added "not changing `pct_error`" explicitly.

### Rev 2 → Rev 3 (this revision)

- **M1 (BLOCKING, small) — invariant (b) is now actually anchored.**
  Rev-2 test 7 (neuter the bounded path) is an ISOLATION check, not
  a byte-identity proof: it stays green if a builder mutates
  `energy_forecast.py:850` in place because baseline and replay
  become equally wrong. Rev-2 test 8 seeded `pct_error` directly
  into the deque, so it never exercised :850 either. Rev 3 adds
  **new test 8 (`test_evaluate_accuracy_production_call_preserves_pct_error`)**
  which drives the PRODUCTION `evaluate_accuracy(0.1, 45.0, ...)`
  call and asserts `pct_error == 44900.0` in both the return dict
  and the deque, while `pct_error_bounded` reflects the SMAPE clamp
  (exact value to re-verify at build; the arithmetic point is a
  bound-hit). This is the RED-on-`:850`-mutation test. Old test 7
  is retained AS an isolation check, and the plan now names it as
  such (not the byte-identity proof).
- **L1 — `None` operand safety in the D1 status ladder.** Rev 3
  states the branch ordering (`samples < 3` first) as load-bearing
  and specifies behavior for an unparseable `_last_eval_date`
  (defensive parse → `eval_age_days = None` → status `"stale"`),
  plus a new test 10 anchoring the defensive parse.
- **L2 — invariant (a) wording.** "no two states share the rendered
  VALUE" → "no two states share the rendered **SIGNATURE (value,
  status)**". STALE deliberately overlays HEALTHY/POOR's numeric
  and is discriminated by status; the value-only wording read as a
  self-inflicted leak.
- **L3 — completed `rolling_accuracy` consumer map.** Added the
  `energy.py:9668-9670` forecast_accuracy hop,
  `sensor.py:11383` (`get_status` attrs path), and the
  `energy.py:10296` → `binary_sensor.py:2497` path (called out as
  BENIGN: consumer reads only envoy counts). Review B's grep
  checklist expanded to include these sites.
- **Test count:** Rev 2 = 8 tests. **Rev 3 = 10 tests** (added
  production-drive M1 anchor + unparseable-date L1 anchor).

---

## Probe results (fill in during D0, before D1/D2 build)

_(To be populated by the builder from the live `energy_daily` query
and the live `ha_get_state` entity-id check.)_
