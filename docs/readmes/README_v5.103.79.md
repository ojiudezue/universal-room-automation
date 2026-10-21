# v5.103.79: bill prediction uses SmartHub cost and tracks its own accuracy

Card: EC-BILL-UTILITY-DIVERGENCE-FROM-STATS-1 (residual: bill prediction). Plan: `docs/planning/PLANNING_ec_bill_prediction_forecast.md` (one plan review, D0 backtest). Tier 2, two reviews (A arithmetic/invariants/cycle boundaries: SHIP; B lifecycle/restore/ordering: SHIP with one MEDIUM, fixed). Deploy risk: LOW (display only; nothing decides from `predicted_bill`).

## Problem

`sensor.ura_energy_coordinator_predicted_bill` was a straight line on URA's own cost (`cost_this_cycle / days × cycle_days + $32.50`), which runs 20-34% under the utility. Last cycle the real bill was ~$323 vs ~$225 implied. No accuracy was ever tracked; there was never a Bayesian bill design (the daily forecast's "Bayesian factor" is a damped 7-day mean error; comments corrected).

## Fix

- **Prediction (P3, D0 winner):** SmartHub-priced utility cost to date + remaining days from the end of SmartHub data to next cycle start, each priced at the same-weekday mean over the trailing 4 weeks (7-day mean fallback) + service charge once from the rate engine.
- Shows "Learning" before day 3; "Unavailable (utility stats stale)" when configured stats are older than 48 h. No URA-cost fallback (D0: ratio too unstable, 1.30-1.60). Installs without utility stats keep the old straight line, labelled `ec_uncorrected`.
- `prediction_source` has one producer (`utility` / `unavailable` / `learning` / `ec_uncorrected`); the hardcoded "envoy" is gone. Counterfactual attributes use the same cycle end.
- **Accuracy ledger (D2):** one snapshot per day in `energy_state` (`bill_forecast_ledger`), scored at cycle close against SmartHub's actual; unscored after next cycle start + 7 days; `no_horizons` cycles excluded. Attributes: `accuracy_mape_by_horizon` (7/14/21), `accuracy_cycles_scored`, `last_cycle_actual`, `last_cycle_error_by_horizon`, `ledger_days_this_cycle`, plus `actual_to_date`, `remainder_cost`, `remainder_days`, `fixed_charge`, `actual_window_end`, `cycle_end`, `days_remaining`.
- Bias correction (D3) parked: no gain in the backtest.

## Backtest (D0, 4 complete cycles; mean abs error %)

| Day | Old straight line | Utility straight line | Chosen (P3) |
|---|---|---|---|
| 7 | 43.1 | 31.7 | 14.8 |
| 14 | 37.6 | 21.3 | 14.9 |

## Tests

- `test_ec_bill_prediction_forecast.py` (58 tests); 39 mutation drills all RED. Cycle days 1/24/28, Feb/leap/Dec-Jan, lag 0/1/2, stale stats.
- Full-suite name-diff vs develop: CLEAN, 12 = 12, 0 new / 0 gone (with URA_SOURCE_MUTATION=1).

## Validated 2026-10-20 (restart ~17:49 CDT)

| Criterion | Result | Evidence |
|---|---|---|
| Uses SmartHub cost | PASS | `sensor.ura_energy_coordinator_predicted_bill` = 238.44, `prediction_source: utility` |
| Arithmetic matches the independent check | PASS | `actual_to_date` 176.71 + `remainder_cost` 29.23 (4 days) + `fixed_charge` 32.5 = 238.44; review A's hand calculation from SmartHub hourly data gave ≈ $238 |
| Cycle bounds | PASS | `cycle_start_date` 2026-09-24, `cycle_end` 2026-10-24, `actual_window_end` 2026-10-20, `days_remaining` 4 |
| Ledger persisted | PASS | URA DB `energy_state` key `bill_forecast_ledger` (212 bytes); `ledger_days_this_cycle` 1, `accuracy_cycles_scored` 0 (first scoring at the 10-24 close; first full cycle 11-24) |
| Load | PASS | manifest v5.103.79; no URA ERROR after the restart (one BlueBubbles send failure at 17:40 was before it and unrelated) |

Not provable live yet: cycle scoring and MAPE (needs a cycle close).
