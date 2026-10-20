# PLANNING: EC bill prediction = actual-to-date + forecast remainder, with an accuracy ledger

Status: PLAN (Tier 2, one adversarial plan review before build). Topic-named; no version.
Card: EC-BILL-PREDICTION-FORECAST-1 (mint on the board if absent).

Operator, verbatim (2026-10-20): "The idea was to find a good way to extrapolate within 1-2 weeks while still
tracking actual so we could see how accurate we are over time. Wasn't this some kind of bayesian learning? Fix it."

## 0. Answer to "wasn't this Bayesian learning?"

Verified, plainly:

- **No bill-level Bayesian or learning design was ever built.** `_update_prediction`
  (`domain_coordinators/energy_billing.py:651-682`) has been a straight line since v3.7.0 (`git log -S` → `007d0a2b9`,
  last touched by `75fa2e4ac` Emporia counters): `cost_this_cycle / days × cycle_days + PEC_FIXED_CHARGES["service_availability"]`.
  No ledger, no accuracy record, no correction.
- **The closest planned design was B3 "Bill Prediction Calibration"** (`docs/planning/PLANNING_UTILITY_METER_INTEGRATION.md:51-70`):
  a divergence-driven *source switch* (envoy ↔ utility meter, 10%/5% hysteresis). Not Bayesian, not accuracy-tracking. It was
  never shipped: B-Lite (divergence attributes only) shipped as v4.2.17 (`AUDIT_smarthub_bill_actual_2026_10_18.md` §2).
  `PLANNING_ec_bill_divergence_from_smarthub_stats.md:268` explicitly made "no calibration from utility" a non-goal.
- **What the operator remembers is the DAILY ENERGY forecast**: `DailyEnergyPredictor` + `AccuracyTracker`
  (`energy_forecast.py:50`, `:806`). Its docstring says "Bayesian adjustment factor" (`:126`, `:897`) but the code is a
  **damped mean-error multiplier**, not Bayesian: `1 + mean(last-7 pct_error)/100 × 0.3`, clamped [0.7, 1.3], needs ≥3
  samples (`energy_forecast.py:896-911`). The only genuinely Bayesian input is the occupancy blend from `bayesian_predictor`
  (`:410-423`), which weights consumption, not bills. So "Bayesian" in this domain is a naming overstatement; this plan
  does not repeat it.

## 1. Institutional context verified

Docs read: `ENERGY_COORDINATOR_MANUAL.md:465` (predicted_bill attrs), `PLANNING_ec_bill_divergence_from_smarthub_stats.md`
(full: D3 publish shape, :268 non-goals, :296 verification note), `AUDIT_smarthub_bill_actual_2026_10_18.md` (full),
`PLANNING_ec_billing_emporia_counters.md` (:136, :342, :477 frozen-on-gap semantics), `PLANNING_UTILITY_METER_INTEGRATION.md`
(B3), `PLANNING_forecast_accuracy_fix.md` (header; bounded pct-error metric). Code read: `energy_forecast.py:50-130, 240-423,
806-960`; `energy_billing.py:651-727`; `energy.py:11760-11945` (utility stats reader + publish); `aggregation.py:2520-2580`.
Not HVAC/presence; the mandatory state-of-play docs do not apply.

Grep set (every proposed piece) — `grep -rn` over `const.py`, `energy_const.py`, `config_flow.py`/`options_flow.py`,
`sensor.py`, `number.py`, `domain_coordinators/*`, `docs/planning/*` for `predicted_bill|bill_forecast|bill_accuracy|
ledger|mape|bias|calibrat|service_availability`:

| Piece | Verdict |
|---|---|
| Actual-to-date (utility $) | **REUSE** `_utility_stats_cache["current"]["utility_net_cost"]` built at `energy.py:11885-11890`; published as `utility_cost` `:11939`. Priced by `price_hourly_utility_rows` (`energy_billing.py:1130`, TOU). **Excludes the service charge** — svc is added only to `last_cycle.utility_bill_estimate` (`energy.py:11898-11906`). |
| Staleness gate | **REUSE** `out["stale"]` / `UTILITY_STATS_STALE_H=48` (`energy_const.py:1461`, `energy.py:11914`). |
| Fallback actual-to-date | **REUSE** `_cost_this_cycle` (`energy_billing.py:688-691`) × learned ratio (below). |
| Fixed charge | **REUSE** `TOURateEngine.service_availability_monthly` (`energy_tou.py:535`), PEC constant only as fallback — same rule as A-M2 at `energy.py:11900-11904`. Today's predictor uses the constant directly (`energy_billing.py:681`): a latent drift if the rate file changes. Fixed here. |
| Cycle math | **REUSE** `_get_cycle_start` (`energy_billing.py:532`), the prev-cycle idiom at `energy.py:11800-11803`. Cycle-end = next `_get_cycle_start` — do NOT reuse the month+1 hand-roll at `energy_billing.py:665-675`. |
| Remaining-days forecast | **REUSE (candidate)** daily history in `energy_daily.net_cost` (`database.py:1475`) and the utility hourly rows already fetched. `DailyEnergyPredictor` only predicts today/tomorrow net kWh, and `PredictedCostTomorrowSensor` (`aggregation.py:2536`) prices it at a **flat** effective rate, not TOU. Neither covers days 2..N. Which remainder estimator wins is decided by D0, not asserted. |
| Accuracy/bias pattern | **REUSE pattern** of `AccuracyTracker` (rolling deque, restore from persisted rows, bounded pct error from `PLANNING_forecast_accuracy_fix.md`). New small class, not an extension: different unit (cycle, $) and horizon axis. |
| Persistence | **REUSE** `save_energy_state` / `restore_energy_state` kv (`database.py:5522-5552`), key `bill_forecast_ledger`, JSON. One write/day through the existing queue. **No schema change.** |
| Sensor | **REUSE** `EnergyPredictedBillSensor` (`sensor.py:11088-11260`); new attributes only. No new entity. |
| Knobs | **NEW** module constants in `energy_const.py` (no equivalent `BILL_*` found). |

## 2. Falsifiable invariants

- **I1 (no double fixed charge):** for every published value, the service-availability charge appears exactly once:
  `predicted = actual_to_date_variable + remainder_variable + svc`, where neither `actual_to_date_variable` nor
  `remainder_variable` contains svc. Breakable if someone feeds `utility_bill_estimate` (which includes svc) as actual-to-date.
- **I2 (floor):** `predicted_bill ≥ actual_to_date_variable + svc` whenever `remainder_variable ≥ 0`; if the remainder is
  negative (net-export days forecast), the prediction may fall below that floor only by the forecast export credit, and the
  attribute `remainder_cost` shows the sign. Concretely: predicted is never below actual-to-date + svc + min(0, remainder).
- **I3 (display-only):** no decision path reads `predicted_bill` or any new attribute. Verified today: consumers are only
  `sensor.py:11116/11203/11240`, `energy.py:11652`, `energy_billing.py:727` (diagnostics dict). Re-grep at build and in review.
- **I4 (ledger honesty):** each cycle's close row records the actual from the SmartHub-priced series for exactly
  `[cycle_start, next_cycle_start)` local, never from the EC fallback; if the stats are stale at close, the row is written
  `actual=None, status="unscored"` and excluded from MAPE and bias.

Note on "actual": SmartHub provides kWh only. "Actual" = SmartHub kWh × our TOU tariff + svc (the same number as
`last_cycle.utility_bill_estimate`). It is not the PEC invoice. Errors against the real invoice (riders, taxes) are out of
scope; the operator can compare one invoice by hand.

## 3. Producer / consumer

**Producer (new value `predicted_bill`):** inputs (1) utility_net_cost to date — healthy since v5.103.76, hourly, lag
measured in D0; (2) remainder estimator — depends on D0; (3) svc from the rate engine; (4) bias from the ledger.
Dependency health check: SmartHub monthly entity is dead since 06-02 (audit), but the hourly external statistic is alive;
this plan reads only the hourly series. EC cost runs 20-34% under utility, so the EC fallback must be ratio-corrected
(ratio = utility/EC over the last scored cycle(s), learned, default 1.0 until one exists).

**Consumers:** listed under I3. Dashboards (`dashboard/`, `dashboard-v3`) read the state only (per divergence plan :296).
The day-7 "Learning" gate goes away when utility actuals are available (the actual-to-date carries the information);
it stays for the EC-fallback path below `BILL_FORECAST_MIN_DAYS`.

## 4. Sites

All writes of `_predicted_bill` are in `energy_billing.py:_update_prediction` (`:659`, `:682`); the only reader is the
property `:700`. The utility cache is filled only in `_async_refresh_utility_stats` (`energy.py:~11795-11915`). The new
predictor must run after that cache refresh or read the cache as-is; it must not trigger its own stats query.
Builder: re-run `grep -rn "_predicted_bill\|predicted_bill" custom_components/` and paste the result in the PR.

## 5. Deliverables

### D0 — Backtest probe (read-only, go/no-go gate)
Script over the recorder (`smarthub:` hourly import/export statistics) + URA DB `energy_daily`, run via `ssh ha "python3 -"`.
For each complete cycle since net metering began (2026-05-26; expect ~4-5 cycles with cycle day 24), and each horizon
day d ∈ {3, 7, 10, 14, 21}, compute the prediction a predictor would have made with only data ≤ d, and score vs the
cycle's utility actual. Predictors:
- P0 straight line on EC cost (today).
- P1 straight line on utility cost to date (+svc).
- P2 utility to date + remaining_days × trailing-7-day mean utility daily cost.
- P3 P2 + day-of-week weighting.
- P4 P2 + bias EMA from prior cycles' horizon errors (leave-one-out).
Also report: SmartHub stats lag (hours behind now, distribution), how many cycles exist, and EC/utility ratio stability
across cycles (for the fallback).

Gate: ship the simplest predictor within 2 pp MAPE of the best at d=7 and d=14. If P1 already does that, D1 is P1 and the
"forecast remainder" machinery is not built. If ratio stdev across cycles > 10 pp, the EC fallback publishes
"Unavailable (utility stats stale)" instead of a corrected number.

- **Verify:** report table predictor × horizon MAPE + signed bias, appended to this plan as §D0-results.
- **Discriminates:** if utility data is too lagged or too few cycles (<3), the table says so and D3's bias is cut.
- **Live:** none (offline).

### D1 — Predictor rewrite (`energy_billing.py:_update_prediction`)
Implement the D0 winner. Inputs passed in by the coordinator (utility cache current block, stale flag, svc), not reached
for from the billing object. Order: actual_to_date → remainder → bias (D3) → + svc once → clamp per I2 → stamp. EC fallback
when stats stale or missing: `_cost_this_cycle × ratio` with `prediction_source="ec_corrected"`; else `"utility"`.
Cycle end via `_get_cycle_start` of the day after (replaces the month hand-roll).

- **Verify:** with utility cache present, `predicted_bill - svc - utility_cost` equals the `remainder_cost` attribute
  (I1 arithmetic visible). Under a double-count bug the difference would exceed remainder by exactly svc.
- **Verify:** stale cache → `prediction_source: ec_corrected`; a missing cache with < `BILL_FORECAST_MIN_DAYS` → "Learning".
- **Test:** `test_bill_pred_svc_counted_once`, `test_bill_pred_floor_actual_to_date`, `test_bill_pred_stale_falls_back_ratio`,
  `test_bill_pred_cycle_end_uses_cycle_helper` (cycle day 24, Feb and Dec boundaries), `test_bill_pred_svc_from_rate_engine`.
- **Live:** `sensor.ura_energy_coordinator_predicted_bill` attributes `prediction_source: utility`, `actual_to_date`
  ≈ `utility_cost` (same value), `remainder_cost`, `fixed_charge` = rate-engine svc. State within the D0 day-N error band of
  last cycle's `utility_bill_estimate` scaled by days, NOT ~20-34% below it (the straight-line signature).

### D2 — Accuracy ledger + attributes
New `BillForecastLedger` (in `energy_billing.py`, beside the predictor). Once per local day, after the daily rollover,
append `{cycle_start, day_of_cycle, predicted}` for the current cycle; persist the whole ledger (bounded to
`BILL_LEDGER_MAX_CYCLES`) via `save_energy_state("bill_forecast_ledger", json)`. At cycle close (first refresh where
`last_cycle` block is non-stale and its window equals the closed cycle), write `actual` and per-horizon errors for
d ∈ `BILL_ACCURACY_HORIZONS`. Restore at setup via `restore_energy_state`. Byte-identical no-op: no write when the day's
snapshot already exists.

Attributes: `accuracy_mape_by_horizon` ({7: x, 14: y, 21: z} over scored cycles), `accuracy_cycles_scored`,
`last_cycle_actual`, `last_cycle_error_by_horizon`, `ledger_days_this_cycle`.

- **Verify:** restart mid-cycle preserves snapshots (count unchanged, no duplicate day).
- **Verify:** stale stats at close → row `status: unscored`, MAPE unaffected (I4). Under a bug that scored from EC
  fallback, MAPE would move on that cycle.
- **Test:** `test_ledger_one_snapshot_per_day`, `test_ledger_restore_roundtrip`, `test_ledger_close_scores_from_utility_only`,
  `test_ledger_unscored_when_stale`, `test_ledger_bounded`.
- **Live:** day after deploy, `ledger_days_this_cycle ≥ 1`; `restore_energy_state('bill_forecast_ledger')` row exists in
  `energy_state`. First scored cycle: after 2026-11-24 close, `accuracy_cycles_scored = 1` (disposed by one-shot query then).

### D3 — Bias correction (gated by D0)
Per horizon bucket, `bias_h ← (1-α)·bias_h + α·err_h` (signed fractional error), applied as
`remainder × (1 + bias_h)` — to the remainder only, never to actual-to-date or svc. Clamp |bias| ≤ `BILL_BIAS_MAX`.
Pushback: with ~12 cycles/year, a normal-normal "Bayesian" shrinkage toward 0 with prior weight k is algebraically a
weighted mean of errors; an EMA with α≈0.3 is indistinguishable at this sample size. Ship the EMA, call it a bias EMA.
If D0 shows |P4 − P2| < 2 pp, D3 is **not built**; the ledger still reports error, and D3 parks with trigger
"≥4 scored cycles show signed bias of one sign > 5%".

- **Verify:** bias never touches actual-to-date (test perturbs bias to ±max, actual_to_date attr unchanged).
- **Test:** `test_bias_applies_to_remainder_only`, `test_bias_clamped`, `test_bias_zero_kill_switch`.
- **Live:** `bias_by_horizon` attribute present; 0.0 until a cycle is scored.

## 6. Knobs (rung 1, `energy_const.py`; display-only feature, change should be reviewed)
- `BILL_FORECAST_MIN_DAYS = 3` — fallback-path learning gate (was a literal 7). 
- `BILL_FORECAST_TRAILING_DAYS = 7` — remainder window (if D0 picks P2/P3).
- `BILL_ACCURACY_HORIZONS = (7, 14, 21)`.
- `BILL_LEDGER_MAX_CYCLES = 12`.
- `BILL_BIAS_ALPHA = 0.3`; `0` = kill switch (bias stays 0).
- `BILL_BIAS_MAX = 0.25`.
No Number entities: nobody tunes these by observation; a config-flow field would be clutter.

## 7. Non-goals
- No change to `cost_this_cycle`, `cost_today`, `energy_daily`, accrual, or the divergence attributes.
- No PEC invoice ingestion; "actual" is SmartHub kWh priced by our tariff.
- No new entity, no schema migration, no control consumer.
- No changes to `DailyEnergyPredictor` / `AccuracyTracker` (renaming the "Bayesian" docstring is a one-line comment fix, in-cycle LOW).
- No multi-week weather-driven forecast; parked with trigger "D0 shows P2 day-7 MAPE > 15% and residuals track temperature".

## 8. Tier
**Tier 2** (one adversarial plan review, two framing-disjoint code reviews: A arithmetic/I1/I2/cycle boundaries;
B restore/lifecycle/ordering against the stats refresh). Display-only (I3), no schema, one owner of the value. Not Tier 2-DB:
kv persistence through the existing queue, one write/day. Elevate if the builder finds any decision consumer.

Config-first: no setting fixes this (cycle day and stats ids are already set; the formula is code).

## 9. PLAN-REVIEW 2026-10-20 (adversarial, Tier 2) — binding amendments for the builder

Verdict at review: NEEDS-CHANGES → resolved by the amendments below (plan text above stands except where amended here).

- **R1 (HIGH) `prediction_source` already exists.** `sensor.py:11137` publishes `prediction_source` from the divergence
  dict, hardcoded `"envoy"` at `energy.py:11933` (statistics path) and `energy.py:12014` (legacy utility-meter path). D1's
  `utility`/`ec_corrected` values must REPLACE that source (one producer: the billing predictor's status), and both
  hardcoded `"envoy"` sites must stop feeding the attribute. Do not publish a second key with the same meaning. Test:
  `test_bill_pred_prediction_source_single_producer` (stale cache → attr is `ec_corrected`, never `envoy`).
- **R2 (HIGH) remainder days start at the utility window end, not "now".** `out["current"]` covers
  `[cycle_start, cur_end)` with `cur_end = min(utility_window_end(priced), today)` (`energy.py:11885`,
  `energy_billing.py:1192-1201`); `utility_window_end` lags ≥1 day and never includes a partial day. So
  `remainder_days = (next_cycle_start - cur_end).days`. Counting from today silently drops the 1-2 lag days
  (systematic under-prediction ≈ 1-2 × daily cost). Expose `actual_window_end` attr. Test:
  `test_bill_pred_remainder_counts_from_window_end` (window_end = today-2 → remainder covers 2 extra days).
- **R3 (MEDIUM) cycle-start gap.** `out["current"]` is None until `cur_end > cycle_start` (first ~1-2 days of each
  cycle) even when stats are fresh. That case is "utility, zero actual-to-date", not "stale": predict
  `remainder over [cycle_start, next) + svc` if the D0 winner has a remainder estimator, else fall to the EC path /
  Learning. State which in D1; test at cycle day 0 and day 1.
- **R4 (MEDIUM) I4 close needs a scoring rule that can't be poisoned by lag or freeze forever.** `last_cycle` is only
  built when `window_end >= cycle_start` (`energy.py:11891`), i.e. the closed cycle is fully covered — that, not
  `stale is False`, is the score condition. If not covered within `BILL_LEDGER_SCORE_DEADLINE_DAYS = 7` (new, rung 1:
  one-week tolerance for SmartHub outages) after `next_cycle_start`, write `status="unscored"`. Never mark unscored at
  the first stale refresh (a 1-day lag would then permanently lose the score). Test: `test_ledger_scores_late_arrival`.
- **R5 (MEDIUM) counterfactual attrs.** `predicted_bill_without_arbitrage` (`sensor.py:11203`) and
  `predicted_bill_without_solar_battery` (`:11240`) are `predicted + projected savings`; they shift with the new
  predictor (coherent, additive), but their `days_remaining` uses a `relativedelta(months=1)` cycle length and EC
  `days_in_cycle` (`:11175-11190`). D1 must expose `cycle_end`/`days_remaining` from the billing status and the sensor
  must use them, so one sensor never shows two cycle lengths. Not doing so is a non-goal only if stated; prefer aligning.
- **R6 (LOW) EC→utility ratio persistence.** The learned ratio lives in the ledger JSON (per scored cycle:
  `utility_net_cost`, `ec_net_cost`); ratio = last scored cycle (or mean of last N≤3). Default 1.0 publishes with
  `prediction_source="ec_uncorrected"` so the known 20-34% under-read is labelled, not hidden.
- **R7 (LOW) horizon definition.** `day_of_cycle` = local calendar days since `cycle_start` at snapshot time (not
  utility-covered days); the snapshot also stores `actual_window_end` so D0-vs-live comparisons use the same axis.
- **R8 (LOW) I3 re-verified 2026-10-20:** Python consumers = `energy_billing.py:659/682/700/727`, `energy.py:11652`,
  `sensor.py:11116/11203/11240`. Dashboards: `dashboard/src/types/entities.ts:18` (entity id only),
  `dashboard-v3` archive only; `~/Code/ura-dashboard-pwa` has no reference. No decision consumer.
- **R9 (LOW) knobs:** `BILL_LEDGER_SCORE_DEADLINE_DAYS` added (R4). D0's 2 pp gate, 10 pp ratio-stdev gate and the
  48h staleness are review-time constants of this plan (D0 gate) or REUSED (`UTILITY_STATS_STALE_H`) — fine.
- **Confirmed holds:** svc excluded from `utility_net_cost` (only added at `energy.py:11898-11906`);
  `service_availability_monthly` is a property (`energy_tou.py:534-535`); `save/restore_energy_state` exist
  (`database.py:5522/5535`); month hand-roll at `energy_billing.py:665-675` as stated.

## D0 RESULTS 2026-10-20

Probe run 2026-10-20 16:14-16:30 CDT, read-only. Script: `/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/bt.py`
(inputs `st.csv` = recorder `statistics` rows for metadata_id 4699 import / 6396 export, `ed.csv` = URA DB `energy_daily`, `tou.json` = live `/config/universal_room_automation/tou_rates.json`).

**Pricing, exactly as URA** (`energy_billing.py:1130-1183` `price_hourly_utility_rows`): hourly `change` = diff of `sum`, local-hour bucketed
(America/Chicago); import $ = kWh x `get_effective_import_rate` = base period rate + 0.022546 + 0.019930 (`energy_tou.py:554-558`);
export credit = kWh x `get_export_rate` = period rate only, no delivery/transmission (`energy_tou.py:546-552`); seasons/periods from
the live file (summer Jun-Sep, shoulder Mar-May/Oct-Nov, winter Dec-Feb). Bill = net + svc 32.50 (`energy.py:11898-11906`). Cycle windows
= local dates [24th, next 24th). Reimplemented offline (not the production module), same arithmetic.

**Cycles available: 4 complete** (cycle start 05-24, 06-24, 07-24, 08-24). 09-24 is in progress (day 26 of 30). Export statistics begin
2026-05-26, so the 05-24 cycle misses 2 days of export credit (small, flagged). Import series has no gaps since 2026-05-24 and no negative
`change` rows since then (146 negative diffs exist, all before 2026-05-24, irrelevant). Below the <3 cycles threshold? No (4), but n=4 is thin: treat MAPE as indicative.

### Actuals and EC/utility ratio (per cycle)
| cycle | N | utility bill (net+svc) | EC net | util/EC net | util/EC bill (both +svc) |
|---|---|---|---|---|---|
| 05-24 | 31 | 187.53 | 119.03 | 1.302 | 1.238 |
| 06-24 | 30 | 225.28 | 120.59 | 1.599 | 1.472 |
| 07-24 | 31 | 204.16 | 128.32 | 1.338 | 1.270 |
| 08-24 | 31 | 322.98 | 192.54 | 1.509 | 1.435 |
Ratio stdev: net-only 0.141 (14.1 pp), with-svc 0.117 (11.7 pp). Mean 1.44 / 1.35. Current cycle to 10-19: utility net 176.71 vs EC 136.43 (1.295).

### Signed error %, (pred - actual)/actual, per cycle
(P4c = causal bias EMA from prior cycles only, P4l = leave-one-out incl. later cycles, alpha 0.3, clamp 0.25; first cycle has bias 0 in causal mode)
| cycle | d | P0 | P1 | P2 | P3 | P4c | P4l |
|---|---|---|---|---|---|---|---|
| 05-24 | 3 | -19.3 | +7.6 | +7.8 | +3.7 | +7.8 | +28.3 |
| | 7 | -25.2 | -16.8 | -16.8 | -6.4 | -16.8 | -4.1 |
| | 10 | -30.9 | -20.8 | -29.1 | -13.3 | -29.1 | -37.5 |
| | 14 | -27.9 | -16.3 | -16.0 | -11.5 | -16.0 | -6.8 |
| | 21 | -27.4 | -8.6 | -3.6 | -7.4 | -3.6 | -0.2 |
| 06-24 | 3 | -47.0 | -40.7 | -28.6 | -20.1 | -33.6 | -31.3 |
| | 7 | -42.7 | -34.7 | -34.7 | -23.9 | -24.9 | -24.9 |
| | 10 | -47.7 | -21.6 | -16.2 | -17.0 | -4.2 | -28.2 |
| | 14 | -44.2 | -16.8 | -7.3 | -14.2 | +4.3 | +4.3 |
| | 21 | -37.4 | -10.5 | -6.7 | -11.0 | -3.4 | -5.2 |
| 07-24 | 3 | -31.3 | -20.1 | +9.2 | +16.7 | +17.6 | +16.5 |
| | 7 | -80.6 | -72.9 | -72.9 | -23.6 | -70.8 | -70.8 |
| | 10 | -79.7 | -74.7 | -90.6 | -38.6 | -92.9 | -92.9 |
| | 14 | -59.7 | -49.2 | -36.1 | -33.6 | -28.1 | -28.8 |
| | 21 | -41.5 | -22.0 | -4.5 | -20.8 | +1.7 | -1.3 |
| 08-24 | 3 | -25.6 | -11.1 | -4.4 | -12.0 | -1.6 | -1.6 |
| | 7 | -24.0 | +2.6 | +2.6 | -5.1 | +20.5 | +20.5 |
| | 10 | -19.2 | +3.0 | +7.2 | -0.4 | -9.6 | -9.6 |
| | 14 | -18.6 | +2.8 | +2.9 | -0.2 | +15.7 | +15.7 |
| | 21 | -16.0 | +3.0 | +3.1 | +1.2 | +7.6 | +7.6 |

### MAPE (signed bias) by horizon, mean over the 4 cycles, %
| d | P0 EC line | P1 util line | P2 util+7d trail | P3 +DOW (4 wk) | P4 causal | P4 LOO |
|---|---|---|---|---|---|---|
| 3 | 30.8 (-30.8) | 19.9 (-16.1) | 12.5 (-4.0) | 13.1 (-2.9) | 15.1 (-2.5) | 19.4 (+3.0) |
| 7 | 43.1 (-43.1) | 31.7 (-30.5) | 31.7 (-30.5) | **14.8 (-14.8)** | 33.2 (-23.0) | 30.1 (-19.8) |
| 10 | 44.4 (-44.4) | 30.1 (-28.5) | 35.8 (-32.2) | **17.3 (-17.3)** | 33.9 (-33.9) | 42.1 (-42.1) |
| 14 | 37.6 (-37.6) | 21.3 (-19.9) | 15.6 (-14.1) | 14.9 (-14.9) | 16.0 (-6.0) | **13.9 (-3.9)** |
| 21 | 30.6 (-30.6) | 11.0 (-9.5) | 4.5 (-2.9) | 10.1 (-9.5) | 4.1 (+0.6) | **3.6 (+0.2)** |

Mean abs error excluding the 07-24 cycle (an away/export week, days 4-10 daily net were -2.0 to 0.2 against a cycle norm of 6-10): P1 d=7 about 18%, P3 d=7 about 12%; so the d=7/10 failures of P1/P2 are largely that one cycle, but P0 is wrong by 19-48% in EVERY cycle and every horizon.

### SmartHub stats lag
Newest import hour 2026-10-19 23:00 CDT at probe 2026-10-20 16:14 CDT: lag 17.3 h (the series ends at end of the previous local day; `UTILITY_DAY_COMPLETE_LAST_HOUR` window logic means today is always partial). Only a point observation: the recorder keeps no per-row ingest time, so a historical lag distribution is NOT derivable (unknown). Staleness gate 48 h (`energy_const.py:1461`) is comfortable against 17 h. Zero hourly gaps since 2026-05-24.

### Decision rule applied
- Gate "simplest predictor within 2 pp of the best at d=7 AND d=14": at d=7 only P3 is near best (14.8; P1/P2 31.7, off by 17 pp); at d=14 P2 (15.6), P3 (14.9) and P4 are within 2 pp of best (13.9, a leaky number). **P1 fails, P2 fails d=7, P3 passes both. Winner: P3** (utility to date + remaining days x same-weekday mean, trailing 4 weeks, falling back to the trailing-7 mean). Caveat: n=4 cycles, one of which is an outlier; P2 is the simpler fallback if the DOW term is judged unearned (it wins at d=3 and d=21, loses at d=7/10 mostly due to 07-24).
- **Forecast machinery IS needed**: P1 (straight line on utility) is 20-32% MAPE at d=7-14 and P0 (today's behavior) is 31-44%, always biased LOW (-31 to -44%), matching the 20-34% EC-under-utility signature.
- **D3 bias EMA NOT built**: |P4 - P2| is under 2 pp only at d=14 (0.4) and d=21 (0.4); elsewhere P4 is equal or WORSE (d=7 +1.5, d=10 -1.9 to +6.3, d=3 +2.6 to +6.9) and causal P4 gets worse at d=14 on 08-24 (+15.7 vs +2.9). A bias EMA on 4 cycles chases noise. Park with the plan's trigger (>=4 scored cycles with same-sign bias > 5%). Note P3 remains biased low (-15% at d=7..14); that is within-cycle growth, a ledger observation, not a D3 case.
- **EC fallback**: ratio stdev 14.1 pp (net) / 11.7 pp (with svc) > 10 pp, so per the rule the EC fallback publishes "Unavailable (utility stats stale)" rather than a ratio-corrected number. D1's `ec_corrected` path should be dropped.
- Min learning gate: P3 at d=3 is 13.1% MAPE (comparable to d=7), so `BILL_FORECAST_MIN_DAYS = 3` is supportable; the trailing window needs the prior-cycle days (data exists, no gate needed).

### Falsification attempt
Disconfirmer for "P0 is badly biased": EC vs utility ratio within +/-5% in any cycle. Observed min 1.24 (with svc); not disproved. Disconfirmer for "P3 wins": P3 not best-or-within-2pp at d=7 on a majority of cycles; P3 is best or second at d=7 in 3 of 4 cycles (not best on 08-24 where P1/P2 +2.6 vs P3 -5.1), so holds but thinly. Re-run when the 09-24 cycle closes (2026-10-24) to add a 5th point.
