# v4.6.2 — Routine Awareness (B6 `away_typical` + B7 Regime Detector + B7 Sensors/Controls)

**Date:** 2026-05-13 CDT
**Type:** Tier 2 feature cycle (2 independent staff-engineer reviews + live validation)
**Predecessor:** v4.6.1.1 (anomaly reconciliation hotfix)
**Layered on:** v4.6.0 accuracy pipeline (consumed by D7) + v4.6.1 anomaly reconciliation (`save_anomaly_event` DAO is the single emit path)

## Summary

v4.6.2 ships the **features** layered on the v4.6.1 anomaly reconciliation foundation: B6 `away_typical` display when geofence-away cells lack data, B7 Jensen-Shannon divergence regime-shift detection running nightly, per-person + house-aggregate `routine_status` sensors, an acknowledge button, and notification controls (Select + Number entities on Coordinator Manager device, default `silent` so the detector runs without firing notifications until you opt in).

Bonus: D7 enhancement consumes v4.6.0's per-person accuracy data as a complementary regime-shift signal — if accuracy drops sharply for a `(person, time_bin, day_type)` cell, that triggers a regime-shift event alongside (or in absence of) the JS-divergence signal.

This is the largest URA cycle to date: ~1900 prod LOC, ~1800 test LOC, 5 deliverables, 7 review findings fixed, 145 v462 tests passing.

## Seven deliverables

### D3 — B6 `away_typical` display

`PersonLikelyNextRoomSensor.async_update` now returns `"away_typical"` (instead of falling through to the frequency learner) when:
- Person is geofence-away (`person_coordinator.location == "away"`) AND
- The Bayesian cell `(person, time_bin, day_type)` is empty OR has no `person_visits` observations in the configured staleness window (default 14 days)

New helper `is_cell_stale()` in `bayesian_predictor.py` queries `person_visits` via `_db_read()` (WAL-concurrent) with SQLite `strftime` time_bin filtering inlined into the SQL WHERE clause.

New entity: `number.ura_coordinator_manager_bayesian_cell_staleness_days` (default 14, range 7-90, on CM device).

### D4 — B7 Jensen-Shannon regime detector

New module `domain_coordinators/regime_detector.py` (~580 LOC).

For each `(person, time_bin, day_type)` cell, computes Jensen-Shannon divergence between room-frequency distributions:
- **P** = recent window (14d default, configurable via D6)
- **Q** = baseline window (56d, excluding the recent window, configurable via D6)
- `JS(P,Q) = 0.5*KL(P||M) + 0.5*KL(Q||M)` where `M = 0.5*(P+Q)`, log base 2, clamped [0,1]

Severity buckets:
- `JS < 0.3` → no event (stable)
- `0.3-0.5` → INFO (drifting)
- `0.5-0.7` → WARNING (shifted)
- `≥ 0.7` → CRITICAL (major_shift)

**Safety guards:**
- 2-consecutive-runs persistence guard via `regime_cell_state` table (`unacknowledged_consecutive` counter) — one-day excursions suppressed
- Vacation skip: if recent-window has zero person_visits (geofence-away proxy), skip AND reset counter to 0
- Min-obs floor: 10 per window for any event; 20 required for CRITICAL
- Min-obs floor on disjoint room sets handled correctly via union-of-rooms normalization

Emits via `database.save_anomaly_event()` (canonical writer from v4.6.1) with:
- `coordinator="bayesian"`, `type="bayesian.routine_shift"`, `event_class="regime_shift"`
- 365-day retention (per v4.6.1 D2 two-tier cleanup)

Runs nightly via `entry.async_create_background_task` (Bug Class #19 — tracked, cancellable on entry unload).

### D5 — B7 routine_status sensors + acknowledge button

**Per-person:** `sensor.ura_coordinator_manager_{person}_routine_status` × N
- State: `stable` | `drifting` | `shifted` | `major_shift` (mapped from worst unacknowledged severity in `anomaly_log`)
- Attributes: `unacknowledged_events`, `max_magnitude`, `max_magnitude_cell`, `top_changes`, `last_check_at`

**House aggregate:** `sensor.ura_coordinator_manager_household_routine_status`
- State: worst-case across persons
- Attributes: per-person breakdown

Both subscribe to `SIGNAL_ROUTINE_STATUS_UPDATE` via `async_on_remove(async_dispatcher_connect(...))` (Bug Class #38). 30-sec query cache.

**Acknowledge button:** `button.ura_coordinator_manager_acknowledge_routine_changes` — single global ack across all persons. Press → UPDATE `anomaly_log` SET `recovery_at=now()` for all unack regime-shift events → dispatch refresh signal.

### D6 — Select + Number control entities (default silent)

All on Coordinator Manager device (per locked decision — discoverable, not hidden in config_flow):

- `select.ura_coordinator_manager_routine_change_notification_mode` — `silent` (default) | `weekly_digest` | `event`
- `number.ura_coordinator_manager_routine_event_cooldown_days` — default 30, range 1-365
- `number.ura_coordinator_manager_routine_event_min_severity` — default 1 (WARNING), range 0-2
- `number.ura_coordinator_manager_routine_regime_baseline_window_days` — default 56, advanced (`entity_registry_enabled_default=False`)
- `number.ura_coordinator_manager_routine_regime_recent_window_days` — default 14, advanced

**Ships in `silent` mode by default** — regime detector runs nightly and emits events to `anomaly_log` + updates D5 sensors, but **no notifications fire** until you flip the Select to `weekly_digest` or `event`. This respects the "I'll forget to ship a follow-up cycle" feedback by getting the notification infrastructure live now while keeping it dormant until validated.

Notification copy is neutral: `"Routine pattern shift detected for {person} in {time_bin} {day_type}. Severity: {severity_name}."` No diagnostic detail leaks into user-facing text; that lives in sensor attributes.

### D7 — v4.6.0 accuracy data as complementary regime-shift signal

Inside `RegimeDetector._compute_cell_accuracy_drop`:
- Reads `prediction_results` WHERE `prediction_type='next_room'` AND `person_id=?` over two non-overlapping windows: recent 7d, baseline 30d (days 7-37)
- If recent top-1 hit rate drops ≥ 30pp from baseline AND both windows have ≥5 predictions, emits as `accuracy_drop` signal
- Severity tiers: 30-45pp → INFO, 45-60pp → WARNING, ≥60pp → CRITICAL
- Combined cell severity = `max(js_divergence_severity, accuracy_drop_severity)` — never additive
- Payload `source` field documents `"js_divergence"` | `"accuracy_drop"` | `"combined"`

### New tables

| Table | Purpose |
|---|---|
| `regime_cell_state` | Per-cell consecutive counter for the 2-run persistence guard |
| `regime_event_notification_log` | Per-cell cooldown tracker for event-mode notifications |
| `regime_weekly_digest_queue` | Queue for weekly_digest mode, FK to `anomaly_log.id` |

All idempotent PRAGMA-checked migrations.

### New DAOs (in database.py)

`get_regime_cell_state`, `upsert_regime_cell_state`, `acknowledge_all_routine_shifts`, `get_regime_last_notified`, `upsert_regime_last_notified`, `enqueue_regime_weekly_digest_queue`, `flush_regime_weekly_digest_queue`.

## Tier 2 Review

Two independent staff-engineer reviews ran in parallel against `pre-review-v4.6.2` tag. Both APPROVE WITH FIXES; findings substantially overlapped.

| ID | Sev | Issue | Fix |
|---|---|---|---|
| B#1 / A#2 | **CRITICAL** | `anomaly_log_id` missing from `SIGNAL_REGIME_EVENT_EMITTED` payload → `regime_weekly_digest_queue.anomaly_log_id` always 0 → latent FK integrity violation | Thread `row_id` (return value of `save_anomaly_event`) into signal payload |
| B#2 / A#1 | HIGH | `RegimeDetector` instantiated without `entry` arg → `_window_days()` always fell through to hardcoded 56/14 → D6 Number tunables were dead config | Pass `entry` as 4th constructor arg |
| B#3 | HIGH | D3 staleness Number (RestoreEntity, URA Mirror Pattern) doesn't write to entry.options, but reader read entry.options → user changes never apply. Same architectural mismatch applied to D6 cooldown/severity/window Numbers read by NM | All consumers read live `hass.states.get()` instead of entry.options |
| B#4 | HIGH | `save_anomaly_event` returns None on failure (swallows internally), but signals still fired → phantom row references downstream | `if row_id is None: return` guard before signal dispatch |
| B#5 | MED | Weekly digest flush used `hass.async_create_background_task` (untracked, Bug Class #19) | Use `cm_entry.async_create_background_task` |
| A#3 | MED | Vacation-cell skip didn't reset the consecutive counter → persistence guard partially bypassed after returning from vacation | Call `_persist_state(..., "stable")` before returning False from vacation branch |
| A#4 | MED | `_is_vacation_cell` hardcoded `recent_days=14` → D6 recent-window slider had no effect on vacation check | Pass `recent_days` from `_window_days()[1]` |

**Pre-review fix (caught before Tier 2 spawned):** Phase 2 builder added `PersonNextRoomAccuracySensor`/`HouseNextRoomAccuracySensor`/`PersonRoutineStatusSensor`/`HouseRoutineStatusSensor` to `sensor.py:async_setup_entry` while they were already registered in `aggregation.py`. Double-registration risk. Fixed: single registration site in `aggregation.py` (the established convention). 5-test regression guard (`test_v462_single_registration_invariant.py`).

8 new review-fix regression-guard tests added pinning each fix.

**Deferred (low-priority, filed for future):**
- B#6 — Sensors access `database._db_read()` directly (private API). Pre-existing pattern across v4.6.0/v4.6.1.
- B#7 — f-string SQL with code-controlled values. Pre-existing pattern across the codebase.
- B#8 / A#7 — Redundant `__init__` in Number subclasses. Code hygiene only.
- Behavioral DB smoke test infrastructure (process improvement from v4.6.1.1 lesson) — needs separate cycle.

## Test count

- v4.6.1.1 baseline: 2775 passing
- **v4.6.2: 2920 passing** (+145: 132 builds + 5 dedupe + 8 review-fix guards)
- Same 56 pre-existing HA-import-dependent failures + 14 errors (unrelated)

New test files (13):
- D3: `test_v462_d3_away_typical.py` (13 tests)
- D4 math: `test_v462_d4_js_divergence_math.py` (10 tests, pure Python)
- D4 detector: `test_v462_d4_regime_detector.py` (20 tests)
- D4 schema: `test_v462_d4_schema_migration.py` (8 tests)
- D7: `test_v462_d7_accuracy_consumer.py` (12 tests)
- D5 sensors: `test_v462_d5_routine_status_sensors.py` (12 tests)
- D5 button: `test_v462_d5_acknowledge_button.py` (5 tests)
- D6 select: `test_v462_d6_select.py` (7 tests)
- D6 numbers: `test_v462_d6_number_entities.py` (13 tests)
- D6 notification: `test_v462_d6_notification_dispatch.py` (8 tests)
- D6 schema: `test_v462_d6_schema.py` (10 tests)
- Signals + review fixes: `test_v462_regime_detector_dispatches_signals.py` (16 tests including 8 review-fix guards)
- Registration invariant: `test_v462_single_registration_invariant.py` (5 tests)

## Live validation plan (post-restart)

1. **Verify D3 cell-staleness Number entity online:** `number.ura_coordinator_manager_bayesian_cell_staleness_days` should read 14 by default. Move slider; reload sensor; confirm `*_likely_next_room` reads the new value.

2. **Verify away_typical surfaces for kids' weekday afternoons:**
   - Jaya / Ziri while at school weekday MIDDAY/AFTERNOON
   - `sensor.ura_person_jaya_likely_next_room.state` should show `"away_typical"` (instead of `"unknown"` or some random frequency-fallback prediction) once their person.location flips to `not_home`.

3. **Verify regime_detector nightly run (2:30 AM):** check for INFO log `RegimeDetector: starting run_nightly` post-2:30 AM. After 1 night of data, `regime_cell_state` table should have rows for every (person, time_bin, day_type) cell with sufficient observations. After 2 nights with continued drift, expect first regime_shift events in `anomaly_log` for affected cells.

4. **Verify D5 sensors come online:** 4 per-person `routine_status` sensors on CM device. Initial state: `stable` (no events yet). Attributes: `unacknowledged_events: 0`.

5. **Verify D6 controls visible on CM device page** under CONFIG cluster: `Routine Change Notification Mode` Select (silent), `Routine Event Cooldown Days` Number, `Routine Event Min Severity` Number. The two regime-window advanced Numbers are disabled-by-default but appear in the entity list if you enable them.

6. **No notification noise:** Select stays on `silent` default. Even if regime events fire in `anomaly_log`, NO HA notifications. Flip Select to `weekly_digest` or `event` when ready.

7. **Verify D7 accuracy consumer:** check `anomaly_log` for any rows with `payload.source = 'accuracy_drop'` or `'combined'` — those came from v4.6.0 accuracy-shift detection, not just JS divergence.

## What's NOT in this cycle

- **Notification copy localization** — strings are English only
- **Per-person ack button** — single global button (matches plan simplification)
- **Schema modernization** — NOT NULL relaxation on `anomaly_log.observed_value` deferred again. v4.6.1.1 sentinel approach still in use.
- **`anomaly_log_id` threading TEST coverage** — pinned in source-grep; behavioral integration test deferred to future cycle with proper DB test infra.
- **10 remaining legacy anomaly touchpoints** still un-migrated (per v4.6.1 plan).

## Deploy notes

- 11 prod files modified + 1 new file (`regime_detector.py`)
- 13 new test files
- 3 new tables via idempotent PRAGMA-checked migrations
- HACS download required
- HA restart required
- Pre-review-v4.6.2 tag in place — diff = `git diff pre-review-v4.6.2..HEAD`

## Next

- 7-day soak: confirm regime_detector emits zero events on stable household (sanity), regime_cell_state table populates correctly
- After soak: decide whether to flip notification Select to `weekly_digest` for a calibration period
- Future: v4.6.3 — migrate remaining 10 anomaly touchpoints through unified `save_anomaly_event` DAO
- Future: schema modernization to relax NOT NULL constraints via table-rebuild
- Future: behavioral DB smoke test infrastructure cycle
- Parked: winter morning peak strategy (Enphase TOU investigation + A/B/C/D option choice)
