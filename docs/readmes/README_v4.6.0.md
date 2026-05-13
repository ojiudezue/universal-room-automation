# v4.6.0 — Per-Person `likely_next_room` Accuracy Pipeline

**Date:** 2026-05-12 CDT
**Type:** Tier 2 feature cycle (2 independent reviews + live validation per CLAUDE.md)
**Predecessor:** v4.5.21.1 (HVAC Coordinator Enabled-switch ordering fix)
**Renumbered:** Original v4.6.0 plan (Routine Awareness B6/B7) slides to v4.6.1+ — accuracy infrastructure must ship before the features whose effects depend on accuracy measurement.

## Summary

URA has emitted per-person `*_likely_next_room` predictions since v4.0.0-B2 via `BayesianPredictor.predict_room()` and a `PatternLearner` frequency fallback. Until this cycle, those predictions were **computed and displayed but never scored**: no recording, no scorer, no accuracy sensor. We could not tell if the predictor was 80% accurate or a coin flip.

v4.6.0 ships the **measurement-only** layer (option α per design discussion). Six deliverables wire prediction recording, transition-time scoring, persistence, and per-person + house-aggregate accuracy sensors. No predictor changes, no feedback loop. That's deliberate — measurement first, intervention next.

This is the *other* prediction-accuracy pipeline: the v4.5.17 fix earlier this session restored room-occupancy Brier scoring; v4.6.0 covers the orthogonal per-person next-room surface.

## Architecture

### Six deliverables

| D | What | File |
|---|---|---|
| D1 | NextRoomPredictionCache — in-memory dict keyed by `person_id`, written by `PersonLikelyNextRoomSensor.async_update` whenever a prediction is computed | `sensor.py:2480-2510` |
| D2 | `_score_prediction()` hook fired from inside `TransitionDetector._log_transition` try-block — looks up cached prediction, computes top-1 / top-3 / Brier, calls D3 helper, dispatches signal | `transitions.py:402-475` |
| D3 | `save_next_room_prediction_result()` DB helper + idempotent ALTER TABLE adding `person_id TEXT` column to `prediction_results` | `database.py:1155-1170, 4036-4076` |
| D4 | `PersonNextRoomAccuracySensor` (per-person, on Coordinator Manager device) — state = top-1 hit rate %, attrs include top-3 / Brier / predictions_7d / predictions_24h | `sensor.py:9158-9358` |
| D5 | `HouseNextRoomAccuracySensor` (aggregate, on Coordinator Manager device) — state = `sum(hits)/sum(predictions)` across all persons | `sensor.py:9360-9550` |
| D6 | `SIGNAL_NEXT_ROOM_PREDICTION_UPDATE` constant + subscriptions in D4/D5 via `async_on_remove(async_dispatcher_connect(...))` (Bug Class #38 prevention) | `signals.py:38-43` |

### Recording mechanism — event-driven, not timer-driven

The writer fires inside `TransitionDetector._log_transition()` **after the successful `room_transitions` insert and inside the same try-block**. If the insert fails, scoring is skipped — prevents orphan accuracy rows referencing transitions that never persisted (Tier 2 review fix B2).

Cache staleness: predictions older than 30 minutes are skipped. Avoids scoring against stale predictions on slow households.

### Schema

Reuses existing `prediction_results` table with `prediction_type = "next_room"`. ALTER TABLE adds `person_id TEXT` column (idempotent — checks `PRAGMA table_info` first). Existing `bayesian_occupancy` rows keep NULL `person_id`; D4/D5 filter by `prediction_type` so the two surfaces don't cross-contaminate.

### Row shape

```
prediction_results row (prediction_type='next_room'):
  room_id              = predicted top room
  prediction_timestamp = when prediction was emitted (NOT score time)
  predicted_value      = JSON {top, alternatives: [str,str], source}
  confidence           = top-room probability
  actual_value         = the room the person actually transitioned to
  error_value          = (confidence - top1_hit)^2  (Brier component)
  person_id            = (NEW column, NULL for legacy rows)
```

### Top-3 semantics

Top-3 hit = `predicted_top` is the actual destination, OR `actual` ∈ alternatives. Cache stores 2 alternatives. Top-3 = `top + 2 alts = 3 rooms total`. Unified across scorer + D4 + D5 after review fix B5/A#3.

### Read pool vs write queue

D4 + D5 use `database._db_read()` (WAL-concurrent transient connections) NOT `_db()` (single-worker write queue). Tier 2 review fix B1 — CRITICAL. Using the write queue for sensor reads would have serialized read traffic through the write channel and starved every transition/energy/prediction insert on the system.

### Refresh signal

`SIGNAL_NEXT_ROOM_PREDICTION_UPDATE` dispatched on every score event. D4 filters by `person_id`; D5 refreshes on any person. Both subscribe via `async_on_remove(async_dispatcher_connect(...))` for clean teardown.

`_handle_update` callbacks use **synchronous** `self.async_schedule_update_ha_state(force_refresh=True)` — HA's canonical primitive for sync callbacks. NOT `hass.async_create_task(async_update_ha_state(...))` which would spawn untracked tasks (Tier 2 review fix B3 — HIGH). 30-sec query cache on top of that prevents DB hammering during rapid-transition bursts.

## Tier 2 Review

Two independent staff-engineer reviews ran in parallel against `pre-review-v4.6.0` tag. Both APPROVE WITH FIXES; findings substantially overlapped.

**Core A (domain logic):**
- A#1 HIGH → matches B3 (async task pattern)
- A#2 MED → matches B5 (top-3 inconsistency)
- A#3 MED → cache `[:3]` vs `[:2]` shape consistency
- A#4 LOW → matches B2 (Core B correctly upgraded to HIGH — phantom-row pollution)
- Plus positive verifications: cache shape consistency, Brier math, JSON exception coverage, aggregate math correctness, signal subscription cleanup, no double-counting

**Core B (lifecycle + concurrency):**
- B1 CRITICAL — `_db()` write queue used for reads (Core A missed)
- B2 HIGH — score-outside-try phantom-row pollution
- B3 HIGH — untracked `async_create_task`
- B4 MED — `setdefault().setdefault()` shadow-dict risk
- B5 MED — top-3 inconsistency
- Plus positive verifications: schema migration ordering safe, signal dispatch semantics correct, `_cm_device_info` thread-safe

**All 5 actionable findings fixed (B1+B2+B3+B4+B5), 5 new regression-guard tests added.** Final verdict: APPROVED.

## Test count

- v4.5.21.1: 539 v460-set baseline shape (different test corpus)
- **v4.6.0: 2693 passing** (+86 from this cycle: 45 backbone + 36 observability + 5 review-fix guards)
- Same 56 pre-existing failures + 14 errors (all HA-import-dependent test files unrelated to this cycle)

New test files:
- `test_v460_next_room_cache_write.py` (10 tests)
- `test_v460_score_on_transition.py` (14 tests — includes review-fix B2 guard pinning score-inside-try)
- `test_v460_db_migration.py` (5 tests)
- `test_v460_save_next_room_helper.py` (12 tests, includes pure-Python Brier math)
- `test_v460_signal_constant.py` (5 tests)
- `test_v460_person_accuracy_sensor.py` (17 tests — includes B1/B3 guards)
- `test_v460_house_accuracy_sensor.py` (15 tests — includes B1/B3 guards)
- `test_v460_d4_d5_registration.py` (8 tests)

## Live validation plan (post-restart)

1. **Verify migration ran:** check HA logs for `Added person_id column to prediction_results` on first boot post-upgrade.
2. **Verify cache populates:** after 5 minutes, `hass.data[DOMAIN]["next_room_predictions"]` should have entries for each tracked person whose `*_likely_next_room` sensor has a valid prediction (not `insufficient_data`).
3. **Verify scoring fires:** trigger a real transition (walk between rooms). Within seconds, expect a new row: `SELECT count(*) FROM prediction_results WHERE prediction_type='next_room'`. Should grow with each transition.
4. **Verify D4/D5 sensors come online:**
   - `sensor.ura_person_oji_udezue_next_room_accuracy` (and per-person for each tracked person) — Coordinator Manager device. Initial state may be `unknown` until ≥1 prediction has been scored.
   - `sensor.ura_coordinator_manager_house_next_room_accuracy` — single house-aggregate.
5. **Verify signal-driven refresh:** transitions should cause D4/D5 to refresh attrs without polling.
6. **7-day soak:** after one week, both sensor types should report numeric states (not unknown). House aggregate should show `sum(hits)/sum(predictions)` not mean of per-person rates.

## What's NOT in this cycle

- **No auto-re-prior or feedback loop.** Measurement only. If predictions degrade, this cycle will SHOW it but won't fix it. The fix is v4.6.1+ work (regime-shift detection, observation decay, algorithm tuning — all gated on having measurement first).
- **No backfill.** 7-day rolling window populates naturally. Historical data is unrecoverable; we never logged it.
- **No behavioral integration test** mocking transition end-to-end (cache write → score → row → signal → sensor refresh). Source-grep / AST tests cover the static contracts; a behavioral test is recommended for v4.6.1 (Core A gap).
- **No accuracy improvement.** Explicitly out of scope. Per design discussion option α.

## Deploy notes

- 5 files modified (sensor.py, transitions.py, database.py, signals.py, aggregation.py)
- 8 new test files
- HACS download required
- HA restart required
- Migration runs at integration setup (first boot post-upgrade), idempotent

## Documents

- `docs/planning/PLANNING_v4.6.0_likely_next_room_accuracy.md` — locked plan with acceptance criteria
- `docs/BACKLOG.md:318-349` — original investigation spike (rehydrated by this cycle)

## Next

- **v4.6.0 7-day soak** — confirm DB rows accumulate, sensor states populate
- **v4.6.1 (TBD)** — Routine Awareness B6/B7 (regime shift detection), now reading v4.6.0's accuracy signal as the regime-change tripwire
- **v4.6.x — winter morning peak strategy** (separate cycle, options A/B/C/D pending; Enphase TOU investigation pending)
