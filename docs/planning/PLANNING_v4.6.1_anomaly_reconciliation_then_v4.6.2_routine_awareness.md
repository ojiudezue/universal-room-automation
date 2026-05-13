# PLANNING v4.6.0 — Routine Awareness (B6 + B7)

**Status:** Planned, not started
**Tier:** Feature cycle (Tier 2 — 2 reviews + live validation per CLAUDE.md)
**Predecessor:** v4.5.0 Battery Strategy v2 Overlay; `docs/planning/ANOMALY_RECONCILIATION_SURVEY.md` survey
**Renumbered:** Originally planned as v4.5.0 (2026-05-06). Reshuffled 2026-05-06 to v4.6.0 to make room for Battery Strategy v2 Overlay at v4.5.0.
**Effort estimate:** 2-3 cycles (Phase 1 silent + Phase 2 notification, plus the D0 reconciliation precondition)

## Context

This release ships two related capabilities:

- **B6 — `away_typical` display**: when the Bayesian model has no useful data for the current `(person, time_bin, day_type)` cell AND geofence says away, surface `"away_typical"` instead of `"unknown"` for `*_likely_next_room` sensors. Handles school/work-day cells, summer↔school transitions, retirement etc.
- **B7 — Regime change detection**: nightly batch detection of household routine shifts using Jensen-Shannon divergence on per-cell room distributions. Surfaces `routine_status` sensors per-person and house-level. Optional opt-in notifications.

**Critical change from earlier specs:** rather than building parallel infrastructure for B7's anomalies, this release **first reconciles existing anomaly mechanisms** (D0) and then layers B6/B7 on top. This decision is driven by the 2026-05-06 anomaly reconciliation survey at `docs/planning/ANOMALY_RECONCILIATION_SURVEY.md`, which inventoried 12 anomaly touchpoints across the codebase with 8 different severity vocabularies and inconsistent recovery semantics.

User direction (2026-05-06): "First reconcile with our anomaly work on coordinators instead of building a new thing."

## Why now

- B6 + B7 require persistence + sensor + notification surfaces. We already have all three across multiple coordinators in inconsistent shapes. Building yet-another would compound the debt.
- v4.3.0 added `_envoy_data_anomaly_at` as a per-coordinator instance flag — exemplary of the inconsistency. Folding it into the unified shape is one of the canary migrations in D0.
- B7's natural fit is the existing `AnomalyDetector` infrastructure with a `type` discriminator added. The survey confirmed savings: **B7 ships ~100 production lines lighter** by reusing.

## Goals

1. Unify anomaly persistence + severity + recovery semantics across coordinators (D0–D2).
2. Make `unknown` cells behave correctly when geofence says "away" (B6).
3. Detect routine regime shifts and surface them as sensors / opt-in notifications (B7).
4. Establish `AnomalyEvent` as the cross-coordinator communication protocol for future features.

## Non-goals (deferred)

- Cross-system anomaly correlation engine (multi-coordinator events with policy logic) — needs its own cycle.
- Anomaly ML models (ARIMA, Prophet, change-point detection beyond JS divergence) — out of v4.6.0 scope.
- Real-time streaming to external dashboards — query-on-demand only.
- Privacy-sensitive filtering of anomaly events — current sensor-attribute model is sufficient.
- Migration of every legacy touchpoint to `AnomalyEvent` — D0 is bounded; full migration is opportunistic via later cycles.
- Auto-correction policies (system reacts to anomaly automatically) — sensor-only output.
- B7 root-cause inference (why the regime shifted) — only detects, doesn't diagnose.

## Survey-driven preconditions (D0–D2 ship FIRST)

Before B6/B7 features can be built cleanly, three reconciliation deliverables ship as a foundation. They are small, pure refactors with measurable risk; do them as one early commit before D3+ feature work begins.

### D0 — Unified `AnomalyEvent` schema + DB migration

**File:** `domain_coordinators/anomaly_event.py` (new), `database.py` (schema migration)

**New module** defining a single dataclass:
```python
@dataclass
class AnomalyEvent:
    coordinator: str          # "energy" | "person" | "safety" | "hvac" | "bayesian" | "circuit" | "transit"
    type: str                 # namespaced, e.g. "energy.crosscheck_divergence", "person.routine_shift"
    severity: AnomalySeverity # INFO | WARNING | CRITICAL — single enum (D1)
    event_class: str          # "point_in_time" | "regime_shift" | "hazard" | "transition_invalid"
    detected_at: str          # UTC ISO
    recovery_at: str | None   # UTC ISO; null while active
    payload: dict             # JSON-encoded, structured per type
    entity_id: str | None     # HA entity if applicable
    room_id: str | None
    person_id: str | None
    correlation_id: str | None
```

**DB migration**: add columns to existing `anomaly_log` table:
- `event_class TEXT` (default `'point_in_time'` for backward-compat with existing rows)
- `recovery_at TEXT NULL`
- `correlation_id TEXT NULL`
- `entity_id TEXT NULL`
- `room_id TEXT NULL`
- `person_id TEXT NULL`

Existing `anomaly_log` rows get `event_class = 'point_in_time'` and remain queryable.

**Single writer**: `AnomalyDetector.store_event(AnomalyEvent)` becomes the canonical entry point. Existing `store_anomaly()` is retained as a thin wrapper for backward compatibility through one release cycle, then removed in v4.6.

### Acceptance criteria
- **Verify**: `grep` shows zero ad-hoc anomaly DB writes outside `AnomalyDetector`
- **Verify**: existing `anomaly_log` rows survive migration with default `event_class='point_in_time'`
- **Test**: `test_anomaly_event_round_trip` — round-trip dataclass through DB
- **Test**: `test_anomaly_event_recovery_clears_correctly`
- **Test**: `test_legacy_anomaly_log_rows_have_default_event_class`
- **Live**: post-deploy, query `SELECT event_class, COUNT(*) FROM anomaly_log GROUP BY event_class` returns rows for all expected classes

### D1 — Severity vocabulary unification

**File:** `domain_coordinators/anomaly_event.py` (single `AnomalySeverity` enum), all coordinators that emit anomalies (touch sites — internal, no API change).

Survey found 8 different severity scales. v4.6.0 picks **one** enum used everywhere:
```python
class AnomalySeverity(IntEnum):
    INFO = 0       # observation worth recording but not alerting
    WARNING = 1    # caller should act on this; cleanable
    CRITICAL = 2   # urgent; usually wires NM notification
```

All existing anomaly callsites mapped:
- `coordinator_diagnostics.py:AnomalySeverity` (INFO/WARN/CRITICAL) → already aligned, just promote module
- NM 4-level severity → collapses to 3 (the rarely-used 4th tier maps to CRITICAL or INFO depending on context — survey lists case-by-case in §2)
- ActivityLogger 3-level (info/notable/critical) → 1:1 alignment, just rename `notable → WARNING`
- Implicit warnings via `_LOGGER.warning(...)` calls without sensor surface → not changed (still log-only)
- Boolean-only flags (`is_anomalous: True`) → caller must pick a severity at the emission site

### Acceptance criteria
- **Verify**: a single `AnomalySeverity` import path; old enums removed/aliased
- **Test**: `test_severity_round_trip_db` — INTs persist correctly
- **Test**: `test_legacy_severity_strings_map_correctly` — old `'warn'`, `'warning'`, `'alarm'` strings normalize
- **Live**: every sensor with `severity` attribute uses the new vocab post-restart

### D2 — Nightly cleanup of orphaned anomalies (Bug Class #27 prevention)

**File:** `database.py` (new DAO), `domain_coordinators/coordinator_diagnostics.py` (registration)

Survey identified **HIGH risk**: `anomaly_log` rows with `resolved=0` are never auto-deleted. Today there's no cleanup path; rows accumulate indefinitely.

**New DAO**: `cleanup_anomaly_log(retention_days: int = 90) -> int`. Same batched pattern as `cleanup_room_energy_baselines` (LIMIT 1000 + `asyncio.sleep(0.1)`). Removes rows where `detected_at < (now - retention_days)`.

**Registration**: register in `_cleanup_ops` AND `_cleanup_ops_d` lists (per Bug Class #27 prevention added in v4.2.28).

### Acceptance criteria
- **Verify**: `grep` confirms cleanup registered in both nightly maintenance lists
- **Test**: `test_anomaly_log_cleanup_batched` — 5000-row table prunes correctly
- **Test**: `test_anomaly_log_cleanup_respects_retention_days`
- **Live**: run cleanup manually post-deploy, verify row count drops; subsequent nightly maintenance leaves it stable

## Feature deliverables (D3 → D6, all use D0/D1/D2 infrastructure)

### D3 — B6: `away_typical` display

**File:** `sensor.py` (the 5 `*_likely_next_room` sensors — currently at line ~2400)

**Logic** (mirrors BACKLOG.md:42-67):
```python
geofence_away = (state(person.<name>) == "not_home")
pred = bayesian.predict(person_id, time_bin, day_type)

# Cell empty (insufficient data)
if pred.status == LearningStatus.INSUFFICIENT_DATA:
    return "away_typical" if geofence_away else "unknown"

# Cell stale (no obs in cell within bayesian_cell_staleness_days, default 14)
if cell_stale(person_id, time_bin, day_type, days=staleness_days) and geofence_away:
    return "away_typical"

return pred.top_room
```

**Helper**: `is_cell_stale(person_id, time_bin, day_type, days)` queries `person_visits` for any obs in the (person, time_bin, day_type) within last `days` days. Returns True if zero obs.

**Config option**: `bayesian_cell_staleness_days`, default 14, range 7-90, surfaced as Number entity in CM Configuration section (mirrors v4.3.0 D2 ArbitrageSOCNumber pattern).

### Acceptance criteria
- **Verify**: `*_likely_next_room` returns `"away_typical"` when person is geofence-away and cell is empty/stale
- **Test**: `test_away_typical_when_cell_empty_and_away`
- **Test**: `test_unknown_when_cell_empty_and_home` (honest "we don't know")
- **Test**: `test_real_prediction_when_cell_active_and_home`
- **Test**: `test_away_typical_when_cell_stale_and_away` (school-resumption case)
- **Test**: `test_real_prediction_when_cell_active_and_away_but_recent_obs` (school-year weekend home)
- **Live**: kids' weekday MIDDAY/AFTERNOON cells display `"away_typical"` while at school

### D4 — B7 algorithm: Jensen-Shannon divergence regime detector

**File:** `domain_coordinators/regime_detector.py` (new)

**Per-cell** `(person, time_bin, day_type)`:
1. Compute room-frequency distribution `P` over a recent window (default 14 days) from `person_visits`
2. Compute room-frequency distribution `Q` over a baseline window (default 56 days, excluding the recent window)
3. Compute Jensen-Shannon divergence: `JS(P, Q) = 0.5 * KL(P || M) + 0.5 * KL(Q || M)` where `M = 0.5 * (P + Q)`
4. Magnitude buckets:
   - `JS < 0.3` → stable (no event emitted)
   - `0.3 ≤ JS < 0.5` → INFO (drifting)
   - `0.5 ≤ JS < 0.7` → WARNING (shifted)
   - `JS ≥ 0.7` → CRITICAL (major shift)

**Persistence guard**: only emit when JS ≥ threshold for **2 consecutive nightly runs** (cell `unacknowledged_consecutive` counter). One-day excursions (vacation, sick day) suppressed.

**Vacation skip**: skip cells where geofence-away >50% of recent window. Reuses cell-staleness infra from D3.

**Min observations**: `min_obs=10` in both windows. `min_obs=20` required for CRITICAL severity.

**Output**: `regime_detector.run_nightly()` calls `AnomalyDetector.store_event(AnomalyEvent(coordinator="bayesian", type="bayesian.routine_shift", event_class="regime_shift", severity=..., payload={cell, magnitude, top_movers, ...}))`. **No B7-specific table or storage.**

### Acceptance criteria
- **Verify**: regime shift events appear in `anomaly_log` with `event_class='regime_shift'`
- **Test**: `test_js_divergence_math_values_match_known_cases`
- **Test**: `test_regime_detector_emits_only_on_two_consecutive_runs`
- **Test**: `test_regime_detector_skips_vacation_cells`
- **Test**: `test_regime_detector_min_obs_floor`
- **Live**: synthetic test run on user's `person_visits` produces zero events on stable households (sanity)

### D5 — B7 sensor surface

**File:** `sensor.py`

**Per-person:**
```
sensor.universal_room_automation_<person>_routine_status
  state: "stable" | "drifting" | "shifted" | "major_shift"
  attributes:
    cells_evaluated_last_run, cells_with_recent_data, max_magnitude, max_magnitude_cell,
    top_changes (list of {cell, magnitude, top_movers}), unacknowledged_events, last_check_at
```

State derives from the highest-severity unacknowledged event (queries `AnomalyDetector` filtered by `coordinator='bayesian' AND event_class='regime_shift' AND person_id=<X> AND recovery_at IS NULL`).

**House aggregate:**
```
sensor.universal_room_automation_household_routine_status
  state: worst-case across persons
  attributes: persons_stable/drifting/shifted/major_shift, total_unacknowledged_events
```

**Acknowledge button:**
```
button.universal_room_automation_acknowledge_routine_changes
```
Press → marks all current unacknowledged events for that person as `recovery_at=now()`. Enables the user to clear the sensor after they've reviewed.

### Acceptance criteria
- **Verify**: per-person sensors exist post-deploy
- **Test**: `test_routine_status_aggregates_correctly`
- **Test**: `test_acknowledge_button_clears_unack_events`
- **Live**: 4-6 weeks of `silent` mode produces stable readings on baseline household

### D6 — B7 notification surface (Phase 2, opt-in)

**File:** `domain_coordinators/notification_manager.py`, `select.py`, `number.py`

**LOCKED 2026-05-13: Select + Number entities on CM device, NOT config_flow option.** Discoverability wins; user feedback was "I will forget in those timeframes" if it's hidden behind ⋮ Configure on the integration card.

- `select.ura_coordinator_manager_routine_change_notification_mode` — options `silent` (default) | `weekly_digest` | `event`
- `number.ura_coordinator_manager_routine_event_cooldown_days` — default 30 (event-mode per-cell cooldown)
- `number.ura_coordinator_manager_routine_event_min_severity` — default 1 (1=WARNING floor, 2=CRITICAL floor)
- Two advanced tunables (`entity_registry_enabled_default=False`) for D4 calibration:
  - `number.ura_coordinator_manager_regime_baseline_window_days` (default 56)
  - `number.ura_coordinator_manager_regime_recent_window_days` (default 14)

All on Coordinator Manager device, matches v4.6.0 accuracy-sensor placement precedent.

**Privacy**: notification copy is neutral ("routine pattern shift detected for {person} in {time_bin}"). Not alarming. Not diagnostic.

**Ship default `silent`** and gate the `event`/`weekly_digest` modes behind a documented warm-up period (4-6 weeks of observation) so the user can validate the detector isn't false-positive on their household pattern.

### Acceptance criteria
- **Verify**: silent mode is default; no notifications in absence of opt-in
- **Test**: `test_event_mode_respects_per_cell_cooldown`
- **Test**: `test_weekly_digest_aggregates_per_week`
- **Live**: post-warm-up, weekly_digest produces a sensible report after one week of stable data

## Open questions — CLOSED 2026-05-13

1. **`bayesian_cell_staleness_days`** default — **CLOSED: 14 days, single global config** (Number entity on CM Configuration cluster). 2 weeks captures school/work routine staleness; per-person is over-engineering for a single-user household.
2. **D2 retention period** — **CLOSED: 90 days for point-in-time; 365 days for `event_class='regime_shift'`.** D2 cleanup query branches on event_class. Regime shifts are rare + historically interesting (multi-month context); year-long retention is cheap.
3. **D4 baseline window 56d vs recent 14d** — **CLOSED: ship 56/14 defaults; surface BOTH as Number entities** with `entity_registry_enabled_default=False` (advanced tunables). Academic JS-divergence defaults are reasonable starting point; tunable without code change post-soak.

## Renumbering and ship sequence — UPDATED 2026-05-13

Original plan said "Phases 1+2 ship as v4.6.0, Phase 3 as v4.6.1." v4.6.0 was used by the **per-person `likely_next_room` accuracy pipeline** (separate cycle, shipped 2026-05-12). Routine Awareness reshuffled:

- **v4.6.1 — D0/D1/D2 reconciliation only.** ~260 prod / ~150 test LOC. Ships silent (no user-visible change). Validates `AnomalyEvent` unified shape via two canary migrations.
- **v4.6.2 — D3 + D4 + D5 + D6 features bundled.** ~630 prod / ~430 test LOC. D6 defaults to `silent` mode — notifications shipped-but-dormant until user opts in. This avoids the multi-week calibration gate that risks being forgotten.

D7 add-in (NEW, 2026-05-13): the v4.6.0 accuracy data is now a complementary regime-shift signal. D4 SHOULD also fire on sharp accuracy drops (e.g., 7-day rolling top-1 hit rate drops > 30 pp from 30-day baseline) per `(person, time_bin, day_type)` cell where computable. Estimate +50 prod / +30 test LOC folded into v4.6.2.

## Schema citations closed

- `person_visits` table: `database.py:472-487`. Has `person_id`, `room_id`, `entry_time`. `time_bin` / `day_type` derived in Python via `bayesian_predictor._hour_to_time_bin()` + `_day_type()` (existing helpers). No new migration needed.
- `prediction_results` table: `database.py:1018+`. `person_id TEXT` column added by v4.6.0. D7 reads `prediction_type='next_room'` rows to compute accuracy delta.

## Migration of legacy anomaly touchpoints (canaries)

Survey lists 12 touchpoints. v4.6.0 D0 migrates **two canaries** to the new shape; full migration of the remaining 10 is opportunistic in later cycles:

1. **Energy `_envoy_data_anomaly_at`** (added v4.3.0 D6) — collapse the per-instance flag to an `AnomalyEvent(coordinator="energy", type="energy.crosscheck_divergence", event_class="point_in_time", ...)`. The sensor's "stale" derivation logic stays in `EnvoyStatusSensor`; only the storage migrates.
2. **Bayesian anomaly score** (existing) — store each scoring run as an `AnomalyEvent(coordinator="bayesian", type="bayesian.prediction_anomaly", event_class="point_in_time", ...)`. Verifies the unified shape works for an existing-and-frequent emitter.

Other 10 touchpoints (safety hazards, person transitions, transit validator, circuit anomaly, NM alerts, decision/compliance/outcome logs) are **not migrated in v4.6.0** — they keep their current shape until needed for a feature. This bounds the risk and lets v4.6.0 ship.

## Tier 2 Review Plan

### Review 1 (Core A): Domain logic
Focus: D0 schema correctness (backward compat with existing `anomaly_log` rows), D1 vocab mapping (no semantic loss), D4 JS divergence math, D5 sensor aggregation.

### Review 2 (Core B): Lifecycle + integration
Focus: D2 cleanup batching + Bug Class #27 prevention, D4 nightly batch scheduling (Bug Class #19 — tracked via `entry.async_create_background_task`), D5 sensor → DB query patterns (Bug Class #25 — bounded queries), schema-migration safety, restart resilience.

### Live Validation (Review 3)
- D0: row count in `anomaly_log` after first nightly maintenance
- D2: cleanup runs without DB lock; row count stays bounded
- D3: kids' afternoon cells display `"away_typical"`
- D4: nightly batch produces ZERO events on a baseline-stable household (sanity)
- D5: per-person sensor reflects acknowledged state correctly after button press

## Out of Scope (Future Cycles)

- **Migrate remaining 10 anomaly touchpoints** to unified shape (v4.6+ opportunistic)
- **Cross-system correlation** (multi-coordinator events with policy) — own cycle
- **Anomaly ML models** beyond JS divergence — own cycle
- **Auto-correction** based on anomaly events — own cycle
- **Privacy filtering** of anomaly events — sensor-attribute model sufficient for now

## Cost (revised after survey)

| Component | Production | Test |
|---|---|---|
| D0: `AnomalyEvent` dataclass + DB schema migration + canonical writer | ~120 | ~80 |
| D1: severity vocab consolidation across coordinators | ~80 (mostly find-replace) | ~20 |
| D2: `cleanup_anomaly_log` + registration | ~60 | ~50 |
| D3: B6 `away_typical` (sensor logic + cell-staleness helper + config) | ~110 | ~80 |
| D4: B7 regime detector (algorithm + persistence guards + vacation skip) | ~250 | ~200 |
| D5: B7 sensor surface (per-person + house + ack button) | ~140 | ~80 |
| D6: B7 notification surface (silent / weekly / event modes) | ~80 | ~40 |
| Canary migrations (2 touchpoints, energy + bayesian) | ~50 | ~30 |
| **Total** | **~890** | **~580** |

Survey-claimed savings (~100 lines lighter for B7) are realized by D4 reusing D0's persistence + D1's severity vocab + D2's cleanup. Original estimate (BACKLOG.md) of 640 prod / 410 test for B7-only is preserved at the feature level; the D0-D2 reconciliation costs are folded into v4.6.0 as up-front infrastructure investment that other future cycles will amortize.

## Ship plan

**Phase 1 — Reconciliation foundation (D0-D2)**: ship as the first commit of the cycle. Migrates schema, unifies vocab, adds cleanup. ~260 prod / ~150 test. Ships silently (no user-visible change). Validates the unified shape works.

**Phase 2 — B6 + B7 Phase 1 (D3-D5)**: feature work on top of foundation. ~500 prod / ~360 test. Sensors only; no notifications. Run silent for 4-6 weeks of calibration.

**Phase 3 — B7 Phase 2 (D6)**: notification surface. ~80 prod / ~40 test. Default `silent`; user-driven opt-in to `weekly_digest` or `event` modes.

Phases 1 + 2 ship as v4.6.0. Phase 3 ships as v4.6.1 after the silent calibration period — gates on the user being satisfied that the detector is false-positive-free for their household.

## Dependencies / preconditions

- `docs/planning/ANOMALY_RECONCILIATION_SURVEY.md` (2026-05-06) — ✅ shipped
- v4.3.0 — ✅ shipped (this is the predecessor)
- v4.7.x B5 (Appliance Scheduler) — **NOT a dependency**, can ship in either order
- Architectural #0 (test baseline cleanup) — **NOT a hard dependency**, but a clean test net would catch regressions in the canary migrations more reliably. Worth doing first if scheduling allows.

## Acceptance criteria summary

The release is "done" when:
- `anomaly_log` rows post-deploy have `event_class` populated for all new events
- Severity vocabulary is uniform across all coordinator anomaly emitters
- Cleanup runs nightly without unbounded growth (1-week observation post-deploy)
- `*_likely_next_room` sensors return `"away_typical"` for empty/stale away cells
- `routine_status` sensors per-person reflect a steady-state baseline (zero CRITICAL events on a stable household after 4-6 weeks)
- Notifications stay silent by default; opt-in modes work after warm-up period
