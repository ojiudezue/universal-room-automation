# PLANNING v4.6.0 — Per-Person `likely_next_room` Accuracy Pipeline

**Decisions locked 2026-05-12 (user signoff "A. lets go!"):**
- Q1: ALTER TABLE `prediction_results` to add `person_id TEXT` column (single-user, no back-compat needed)
- Q2: Score against immediate next transition (Option X)
- Q4: This cycle ships as **v4.6.0**; previously-planned Routine Awareness slides to v4.6.1+
- Q5: Accuracy sensors land on **Coordinator Manager device** (matches existing `BayesianPredictionAccuracySensor` precedent)
- Scope: **measurement only** (Option α) — no auto-re-prior or feedback loop in this cycle

**Date:** 2026-05-12
**Type:** Tier 2 feature cycle (promotion from BACKLOG minor — see Promotion below)
**Predecessor:** v4.5.21.1 (HC device-page Enabled fix); separately v4.5.17 (room-occupancy Bayesian eval `dt_util` fix)
**Rehydrates:** BACKLOG entry "v4.5.17 — Bayesian prediction-scoring pipeline investigation" (`docs/BACKLOG.md:318-349`) — name reused for unrelated NameError fix; this work was deferred

## Problem Statement

URA emits per-person next-room predictions today via `PersonLikelyNextRoomSensor` (`sensor.py:2405`), drawing from `BayesianPredictor.predict_room()` (`bayesian_predictor.py:407-464`) with `PatternLearner.predict_next_room()` as a fallback. The predictions are **computed and exposed but never scored**. Truth signal (actual transitions) IS logged to the `room_transitions` table by `TransitionDetector._log_transition()` (`transitions.py:384`) and was hardened by v4.5.19's listener-leak fix, but the prediction side is never written back for verification.

Result: we have no idea whether `*_likely_next_room` is accurate. The diagnostic-cluster sensor `BayesianPredictionAccuracySensor` (`sensor.py:9066-9124`) reads `prediction_results` with `prediction_type = "bayesian_occupancy"` — that's a **different prediction surface** (room-occupancy probability, scored by v4.5.17's eval closure at 6 daily bin boundaries). Per-person next-room is unscored.

## Existing-State Map (from 2026-05-12 investigation)

| Component | Status | Path |
|---|---|---|
| Bayesian per-person next-room model | ✅ Live | `bayesian_predictor.py:407-464` (`predict_room`) |
| Frequency fallback (no time segmentation) | ✅ Live | `pattern_learner.py` (`predict_next_room`) |
| `PersonLikelyNextRoomSensor` per-person entity | ✅ Live (disabled by default) | `sensor.py:2405-2523` |
| Actual transitions written to DB | ✅ Live | `transitions.py:384` → `room_transitions` table |
| `record_prediction()` for room-occupancy | ✅ Live (NOT a stub) | `bayesian_predictor.py:877-899` |
| Room-occupancy eval closure (6/day) | ✅ Live (v4.5.17 fix) | `__init__.py:1160-1259` |
| `BayesianPredictionAccuracySensor` for occupancy | ✅ Live | `sensor.py:9066-9124` |
| **Per-person next-room prediction logging** | ❌ MISSING | (nowhere — no method, no table) |
| **Per-person next-room scoring loop** | ❌ MISSING | (no closure, no scheduler) |
| **Per-person next-room accuracy sensors** | ❌ MISSING | (no class) |

## Design Goals

1. **Score predictions against transitions, not against occupancy.** A "next-room" prediction is naturally scored at the moment the next transition fires — there's no need for a polling clock.
2. **Reuse `prediction_results` table** via a new `prediction_type = "next_room"` rather than introducing a separate table. Keeps the accuracy-sensor SQL surface minimal.
3. **Score multiple metrics**: top-1 hit, top-3 hit, and Brier across the predicted-room's stated confidence. Different consumers care about different metrics (UI vs. arbitration logic vs. self-tuning).
4. **Survive HA restart.** Pending predictions (emitted but not yet resolved by a transition) must persist or be rebuildable — otherwise restart loops mask the accuracy signal.
5. **Per-person accuracy sensors + house-aggregate sensor.** Per-person is the unit users care about ("how well do we know Oji?"); house-aggregate is the regression signal.
6. **No backfill.** A 7-day rolling window populates naturally. Don't waste a cycle on historical reconstruction.
7. **Don't degrade the predictor.** Recording must be a side-effect of the existing prediction call path, not gating it on a DB write.

## Architecture

### Recording mechanism — event-driven, not timer-driven

The cleanest write trigger is **inside `TransitionDetector._log_transition()`**: at the moment we record the actual transition, we ALSO read whatever the most-recent `*_likely_next_room` prediction was for that person and score it as a row.

Flow:
1. Person moves: `person_coordinator` fires `ura_person_location_change`
2. `TransitionDetector._on_location_change` (transitions.py:154) handles it
3. `_log_transition()` writes the transition row
4. **NEW:** `_score_prediction()` looks up the cached last prediction for `person_id`, computes the metrics, and inserts a `prediction_results` row with `prediction_type = "next_room"`

To support step 4, the `PersonLikelyNextRoomSensor` (or a small `NextRoomPredictionCache`) needs to expose the **last emitted prediction** per person — top room, alternatives (top-3), confidence, timestamp, source. Cache lives in `hass.data[DOMAIN]["next_room_predictions"]` keyed by `person_id`, written every time the sensor recomputes.

### Schema (additive — no migration)

Reuse existing `prediction_results` table:

| Column | Meaning for `next_room` rows |
|---|---|
| `prediction_type` | `"next_room"` |
| `room_id` | Predicted top room (the model's bet) |
| `prediction_timestamp` | When the prediction was emitted |
| `predicted_value` | JSON: `{"top": "Master Bedroom", "alternatives": [{"room": "...", "p": 0.18}, ...], "source": "bayesian"}` |
| `confidence` | Top-room probability |
| `actual_value` | The room the person actually transitioned TO |
| `error_value` | Brier component: `(1.0 - confidence)^2` if hit, `(0.0 - confidence)^2` if miss (matches existing convention) |

No schema migration — `prediction_results` already supports arbitrary `prediction_type` strings.

### Pending-prediction persistence

Predictions are emitted whenever the sensor recomputes (state-change-driven). Between emit time and resolution (next transition), the prediction lives in:
- In-memory cache (`hass.data[DOMAIN]["next_room_predictions"][person_id]`) for fast read at scoring time
- No DB write yet — we don't know the actual until the transition fires
- On HA restart: cache is empty. The first transition post-restart doesn't get scored. That's fine — `BayesianPredictor.predict_room()` is deterministic given inputs; the lost scoring opportunity is acceptable (no compounding error).

### Scoring metrics

Three metrics per row, computed at insert time:

1. **Top-1 hit:** `1.0 if predicted_top == actual else 0.0`
2. **Top-3 hit:** `1.0 if actual in {top, alt1, alt2} else 0.0`
3. **Brier (against top-1 confidence):** `(confidence - hit_indicator)^2`

All three roll up into the new accuracy sensors over a 7-day window.

### Accuracy sensors

- **`PersonNextRoomAccuracySensor`** (per-person) — entity_id `sensor.ura_person_{person_id}_next_room_accuracy`
  - State: top-1 hit rate (7-day, percent)
  - Attributes: `top3_hit_rate_pct`, `brier_score`, `predictions_7d`, `predictions_24h`, `learning_status` mirror
- **`HouseNextRoomAccuracySensor`** (aggregate) — entity_id `sensor.ura_coordinator_manager_house_next_room_accuracy`
  - State: house-wide top-1 hit rate (7-day)
  - Attributes: per-person breakdown, total predictions, oldest prediction timestamp

Both are diagnostic, entity_category=`DIAGNOSTIC`, disabled-by-default — same convention as `BayesianPredictionAccuracySensor`.

### Refresh signal

Following the v4.5.20 pattern: introduce `SIGNAL_NEXT_ROOM_PREDICTION_UPDATE` dispatched from `_score_prediction()` so accuracy sensors refresh attrs on every score event, not on a polling timer.

## Deliverables

### D1: NextRoomPredictionCache (in-memory)

Add a small cache structure to `hass.data[DOMAIN]["next_room_predictions"]` written by `PersonLikelyNextRoomSensor._async_update` whenever it computes a prediction. Holds `{person_id: {top, alternatives, confidence, timestamp, source}}`.

**Acceptance Criteria**
- **Verify:** `PersonLikelyNextRoomSensor` writes to cache on every `_async_update` call (instrumented test)
- **Verify:** Cache survives sensor unloads only as long as the integration is loaded (cleared on `async_unload_entry`)
- **Test:** `test_v46x_next_room_cache_write_on_update`, `test_v46x_next_room_cache_cleared_on_unload`
- **Live:** `hass.data[DOMAIN]["next_room_predictions"]` populated within 5 sec of person sensor state change

### D2: Score-on-transition in TransitionDetector

Add `_score_prediction()` method called from inside `_log_transition()`. Reads the cache, computes the three metrics, inserts a row to `prediction_results` with `prediction_type = "next_room"`.

**Acceptance Criteria**
- **Verify:** Every transition with a cached prediction yields exactly one `prediction_results` insert with `prediction_type = "next_room"`
- **Verify:** Transitions WITHOUT a cached prediction (e.g., first transition post-restart) do not write a row and do not raise
- **Verify:** Score insertion failures don't block transition logging (try/except with WARNING-level escalation per v4.5.20 pattern)
- **Test:** `test_v46x_score_on_transition_writes_row`, `test_v46x_score_no_cache_no_write`, `test_v46x_score_write_failure_does_not_block_transition`
- **Live:** After 24 hr, `SELECT count(*) FROM prediction_results WHERE prediction_type='next_room'` > 0 with non-NULL `actual_value` rows

### D3: Schema + DB helper for `next_room` rows

Add `save_next_room_prediction_result()` to `database.py` (mirrors `save_prediction_result()` but JSON-encodes the alternatives into `predicted_value`).

**Acceptance Criteria**
- **Verify:** JSON in `predicted_value` is valid and round-trips through `json.loads`
- **Verify:** `error_value` is non-NULL and finite for every row
- **Test:** `test_v46x_save_next_room_db_helper_roundtrip`, `test_v46x_save_next_room_brier_calculation`

### D4: PersonNextRoomAccuracySensor (per-person)

New sensor class in `sensor.py`. Reads `prediction_results` WHERE `prediction_type='next_room'` AND (person_id derivable from row context — see open question Q1). 7-day window, top-1 hit-rate as state.

**Acceptance Criteria**
- **Verify:** State updates within 5 sec of dispatch on `SIGNAL_NEXT_ROOM_PREDICTION_UPDATE`
- **Verify:** Attribute `predictions_7d` matches `SELECT count(*) FROM prediction_results WHERE prediction_type='next_room' AND prediction_timestamp >= datetime('now','-7 days')` filtered to this person
- **Verify:** Sensor returns `unknown` (not 0) when `predictions_7d == 0` — avoids "0% accuracy" misread during initial learning window
- **Test:** `test_v46x_person_accuracy_sensor_state`, `test_v46x_person_accuracy_unknown_no_data`, `test_v46x_person_accuracy_signal_refresh`
- **Live:** After 7 days, each tracked person's sensor state is in [0, 100] and `predictions_7d > 0`

### D5: HouseNextRoomAccuracySensor (aggregate)

Reads across all persons, aggregates top-1 hit rate, exposes per-person breakdown as attribute.

**Acceptance Criteria**
- **Verify:** Per-person breakdown attribute keys match the configured tracked-persons list
- **Verify:** Aggregate matches `(sum of hits) / (sum of predictions)` not mean of per-person rates (avoids small-n bias)
- **Test:** `test_v46x_house_accuracy_aggregate_math`, `test_v46x_house_accuracy_per_person_attrs`
- **Live:** House sensor state is in [0, 100] post-7-day window

### D6: Signal infrastructure

Add `SIGNAL_NEXT_ROOM_PREDICTION_UPDATE` constant to `signals.py`. Dispatched from `_score_prediction()`. Sensors in D4/D5 subscribe via `async_dispatcher_connect` with `async_on_remove` wrapper (Bug Class #38 pattern).

**Acceptance Criteria**
- **Verify:** Signal constant exists at module level in `signals.py`
- **Verify:** D4/D5 sensors subscribe via `async_added_to_hass` with `async_on_remove`
- **Test:** `test_v46x_next_room_signal_constant`, `test_v46x_accuracy_sensors_subscribe_with_unsub`

## Open Questions / Decisions Needed Before Build

**Q1. Where does `person_id` live in a `prediction_results` row?**
Existing schema has no `person_id` column. Options:
- (a) Add a `person_id` column via migration (cleanest; schema change)
- (b) Embed `person_id` in `predicted_value` JSON and filter in Python (no migration; slower)
- (c) Use a separate `next_room_predictions` table with the right columns (no migration impact on existing data; doubles the surface area)

Recommendation: **(a) migration** — single ALTER TABLE, the column is genuinely missing for this use case. Migration is single-user (per `feedback_single_user_no_backcompat.md` memory), no back-compat needed.

**Q2. What's the "next room" horizon?**
- Option X: score against the **immediate next transition** (simplest, lowest latency, but noisy for short hops)
- Option Y: score against the **first transition after a 5-minute settle window** (filters short-hop noise, but harder to define)
- Option Z: score against the **next room the person was in for > 60 sec** (most semantically meaningful, complex)

Recommendation: **Option X** for v4.6.x. Refinements available later as a v4.6.y enhancement once we have 4 weeks of data to compare metric stability.

**Q3. Top-3 alternatives — does `BayesianPredictor.predict_room()` already return them?**
Yes (per investigation, returns top 4 in `alternatives`). Frequency fallback also returns multi-step path. So we can populate the top-3 hit metric without changing the predictor.

**Q4. Does v4.6.x land BEFORE or AFTER v4.6.0 Routine Awareness?**
v4.6.0 Routine Awareness has its own planning doc (`docs/planning/PLANNING_v4.6.0_routine_awareness.md`) and may share infrastructure (regime-shift, time-bin model). Need to read v4.6.0 plan and determine sequencing.

Recommendation: **read v4.6.0 plan, decide sequencing, name this cycle accordingly** (likely v4.6.1 if v4.6.0 runs first, or v4.6.0 if this runs first and routine awareness slides to v4.6.1).

## Non-goals

- **Backfilling historical predictions** — none exist; 7-day window populates naturally
- **Tuning the predictor** — we're MEASURING accuracy, not improving it. Tuning is a separate cycle once we have data.
- **Real-time UX for "currently wrong" predictions** — that's a v4.7.x routine-awareness display problem, not accuracy infrastructure
- **Cross-person prediction (group movement)** — out of scope; we predict per-person independently

## Promotion: minor → Tier 2 feature

The original BACKLOG entry estimated "minor cycle (~80 LoC + 25 tests)" IF investigation showed the path partially existed. Investigation showed **the entire path is missing for this surface** (no logging, no schema for person_id, no scorer, no sensor). Per BACKLOG promotion criteria, this escalates to Tier 2 feature cycle:

> *"The logging path doesn't exist at all (have to design persistence schema + writer + scorer from scratch)"*

Tier 2 means: 2 independent staff-engineer reviews + live validation per CLAUDE.md.

## Test plan summary

- ~20-25 unit tests across D1-D6
- Integration test: mock person transition → assert prediction_results row written
- DB roundtrip: write/read 5 sample `next_room` rows, verify JSON parses, error_value finite
- Live validation: 7-day soak before declaring cycle complete

## Sequence

1. **Read `PLANNING_v4.6.0_routine_awareness.md`** + decide cycle numbering
2. **User signoff** on Q1 (migration approach), Q2 (horizon choice), Q4 (sequencing)
3. **Build D1-D3** (cache + scorer + DB helper) — backbone
4. **Build D4-D6** (sensors + signal) — observability
5. **Tier 2 review** (2 independent passes)
6. **Deploy + 7-day live soak** before declaring success

## References

- `docs/BACKLOG.md:318-349` — original investigation spike (rehydrated by this doc)
- `bayesian_predictor.py:407-464` — `predict_room()`
- `bayesian_predictor.py:877-899` — existing `record_prediction()` (occupancy, NOT next-room)
- `sensor.py:2405-2523` — `PersonLikelyNextRoomSensor`
- `sensor.py:9066-9124` — `BayesianPredictionAccuracySensor` (occupancy accuracy, model for next-room version)
- `transitions.py:384` — `_log_transition()` (where scoring hook lands)
- `database.py:1018-1034` — `prediction_results` table schema
- `__init__.py:1160-1259` — v4.5.17 Bayesian-occupancy eval closure (model for next-room eval architecture)
