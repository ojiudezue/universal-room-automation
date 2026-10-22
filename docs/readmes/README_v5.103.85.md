# v5.103.85: room forecasts and next-room predictions use the dwell model

Cards: PREDICT-MODEL-DWELL-MIGRATION-1 + PREDICT-SCORER-BASELINE-SKILL-1 (same release, operator Q2). Tier 2-DB: plan review (FIX-PLAN-FIRST, 13 findings dispositioned), reviews A (data integrity) SHIP, B (consumers + lifecycle) SHIP, C (per-site mutation, 73 sites) FIX-REQUIRED → fixed and drilled. Plan: `docs/planning/PLANNING_predict_dwell_migration.md`. Deploy risk: MEDIUM-LOW (display sensors + one new hourly writer + a wider nightly prune; every re-source has a kill switch).

## Problem
The 10-21 prediction audit found no prediction both useful and correct: the forecasts came from a Bayesian model of *arrivals*, not *dwell*. Next-room used the person's usual room except as a last fallback. Prune only removed one prediction type, so 177k `next_room` rows accumulated since May.

## Measured before build (D0, re-run 2026-10-21 against the live DB, read-only)
| Measure | Result |
|---|---|
| Room occupied, same samples (n=2,950) | dwell AUC 0.835 / Brier 0.069 vs Bayesian AUC 0.603 / Brier 0.087 (constant 0.087) |
| Room-hour share MSE (n=15,460) | dwell cell 0.0273 vs room constant 0.0299 vs global 0.040 |
| +1h blend, runtime alignment | w=0.5: 0.0205 vs 0.0273 (−25%); held-out second half 0.016 |
| Next-room top-1 (from current room vs usual-room baseline) | 38.3% vs 27.9% pooled (upper bound on agreement; live skip rate measured by D4) |
| Producer agreement (hourly fraction vs recorder) | max abs diff ≤ 0.106, 1 hour over 0.1 across 4 rooms |

## Changes
- **D1** `RoomDwellModel`: `trained_until_utc`, UTC-stepped `forecast` blend, `peak_cell`/`top_cells`.
- **D2** Room forecast + pattern sensors read the dwell model. Kill switch `FORECAST_DWELL_SOURCE_ENABLED` restores the Bayesian path unchanged.
- **D3** Hourly `dwell_share` producer: expected share frozen at the hour's first tick from a model trained before that hour; previous hour scored in one batched write (~47 rows/h, ~1,128/day); < 6 samples skipped; same-hour guard; cancelled on stop. This is also the input for OC vision §3b.
- **D4** `likely_next_room` predicts from the current room first; a prediction is scored only if made from the room the transition left. Per-person `scored_since_start`, `skipped_room_mismatch_since_start`, `skip_ratio`, `skip_ratio_ok` (bound `NEXT_ROOM_MAX_SKIP_RATIO` = 0.30).
- **D5** Prune covers every prediction type, `PREDICTION_RESULTS_RETENTION_DAYS` = 45. **First night deletes ~150k old `next_room` rows** (operator-approved Q4), in 1,000-row indexed batches in nightly maintenance.
- **D7** Optimization next-room finding fires when pooled top-1 is no better than the usual-room baseline (operator Q5), not a fixed 35%.
- **Scorer card** `prediction_skill.py`: baseline + skill attributes on the Bayesian, per-person and house accuracy sensors (raw and with 60 s flaps dropped, `NEXT_ROOM_FLAP_DEDUPE_S`).
- Review fix-ups: cache read before the first await in the transition scorer (B-L2); stale last-hour fraction cleared (B-L1); refresh→tick wiring test (C-HIGH); D7 sample gate and fallback stamp tests (C-MED); four C-LOWs.
- Not built: D7 hysteresis fallback (operator chose Q5). Energy forecast left on the old model (Q1); zone/house forecasts not built (Q3).

## Pre-deploy row counts (`prediction_results`, 2026-10-21)
`next_room` 177,291 (oldest 2026-05-13), `bayesian_occupancy` 6,195 (oldest 2026-09-21), `dwell_share` 0.

## Tests
New: `test_dwell_share_producer.py` and siblings; DB tests use the production schema (`make_real_db`). Reviewer C ran 73 single-site mutations; all load-bearing sites RED after fix-up. Orchestrator re-ran the C-HIGH drill (`trained_until_utc` dropped) → `test_real_refresh_then_tick_writes_row` FAILED; restored, clean.

## Live acceptance criteria (prospective)
- **Live:** within 2 h of restart, `prediction_results` has `dwell_share` rows with timestamps on the UTC hour, `confidence` ≥ 6, values in [0, 1]; ~47 per hour.
- **Live:** after the first nightly maintenance, `next_room` rows older than 45 days = 0 and `bayesian_occupancy` likewise; no write-queue backlog warnings in the log.
- **Live:** room forecast sensor for Study A at a weekday 18:00 equals the anomaly sensor's `expected_share` for that cell (same model).
- **Live:** each resident's next-room accuracy sensor shows `skip_ratio_ok: true` (≤ 0.30) once ≥ 30 transitions are scored — checked BEFORE reading accuracy.
- **Live:** next-room accuracy shows a baseline and a skill value; Optimization next-room finding present only if skill ≤ 0.
- **Live:** hourly read of the occupancy table measured 0.23 s on 2.6M rows (review A LOW); re-check if it exceeds 1 s.
- **Discriminator:** under a broken stamp (C-HIGH), 0 `dwell_share` rows ever; under a broken prune, `next_room` oldest stays 2026-05-13.
