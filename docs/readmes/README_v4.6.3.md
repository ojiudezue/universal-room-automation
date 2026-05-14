# v4.6.3 — Anomaly Touchpoint Migration + Behavioral DB Smoke Test Infrastructure

**Date:** 2026-05-14 CDT
**Type:** Tier 2 cycle (13 deliverables, all-in-one ship per user direction)
**Predecessor:** v4.6.2.3 (review carry-overs)
**Reviews:** 3 targeted Tier 2 (A: data integrity, B: migration correctness, C: new surfaces) — all consolidated findings fixed before ship

## Problem

Two intertwined goals:

1. **Migration:** 10 anomaly emit sites across URA's coordinators routed through a deleted-this-cycle legacy `AnomalyDetector.store_anomaly()` wrapper that built coordinator-specific ad-hoc payloads. v4.6.1 introduced `database.save_anomaly_event()` as the canonical DAO; v4.6.2 added the regime detector on top. v4.6.3 finishes the job — every emit site speaks the canonical `AnomalyEvent` shape directly, the wrapper is deleted, future DAO changes are one-touch.
2. **Smoke-test infrastructure:** v4.6.1.1 was a hotfix because two Tier 2 reviewers read the diff but missed a NOT NULL constraint mismatch — they read source, not live schema. v4.6.3 pioneers a `real_schema_db` conftest fixture that extracts schema directly from `database.py` source at runtime, applies it to in-memory sqlite, and routes behavioral tests through the production DAO. Schema drift between fixture and prod becomes impossible without breaking the parse.

## Fix

### D1 — `real_schema_db` conftest fixture
`quality/tests/conftest_db.py` parses CREATE TABLE statements from `database.py` source at runtime (regex over triple-quoted strings), applies them to in-memory sqlite, runs ALTER TABLE migrations. **No hand-typed DDL.** Re-run-safe per-test via function-scoped fixture; session-scoped variant for read-only batches. Documented in module docstring.

### D2 — Safety hazards migrated
3 emit sites in `safety.py` (smoke, CO, leak) routed through `save_anomaly_event(AnomalyEvent(...))`. `SIGNAL_SAFETY_HAZARD` dispatch preserved alongside.

### D3 — Person-transition anomalies
Invalid transit detector emits via DAO + ActivityLogger. Lives in `transitions.py` (new file) and `presence.py`.

### D4 — Circuit anomaly migrated
`energy.py` emits the anomaly event alongside the existing `SIGNAL_SAFETY_HAZARD` dispatch. Confirmed no double-counting via signal chain trace.

### D5 — NM alert dispatch correlation
`notification_manager.py::async_notify` accepts `source_anomaly_id` kwarg; when NM dispatches in response to an anomaly, writes a `type=nm.alert_dispatched` correlation row with `linked_event_id=<source_id>` in `context_json`. Distinct from the source anomaly — no double-counting in analytics queries.

### D6 — Decision/compliance/outcome (selective emit)
`coordinator_diagnostics.ComplianceTracker._emit_compliance_violation_anomaly()` emits only when `not compliant and override_detected`. Will NOT flood the table on routine successful decisions.

### D7 — Legacy `store_anomaly()` deleted
Method removed from `coordinator_diagnostics.py`. Grep confirms 0 hits in production code.

### D8 — Behavioral DAO tests
`quality/tests/test_v463_behavioral_dao.py` — 29 tests against `real_schema_db`. All INSERT-based; mirror the production DAO's metric-field priority chain. 4 `pytest.raises` negative-path tests.

### D9 — Source-grep migration
`test_v461_store_event_writer.py` and `test_v461_severity_unification.py` refactored: legacy `store_anomaly` existence assertions replaced with deletion confirmations. `test_v463_anomaly_migration.py` includes 12 new behavioral tests; 6 redundant source-grep pairs merged.

### D10 — Per-coordinator anomaly sensitivity
**User-directed scope:** config-flow + options-flow ONLY (no Number entities). Select dropdown per coordinator (HVAC, presence, safety, security, music_following) with 5 named buckets:

| Selection | Multiplier on z-thresholds |
|---|---|
| `very_quiet` | 2.0× (z=4/6/8) |
| `quiet` | 1.5× (z=3/4.5/6) |
| `normal` (default) | 1.0× (z=2/3/4) |
| `sensitive` | 0.75× (z=1.5/2.25/3) |
| `very_sensitive` | 0.5× (z=1/1.5/2) |

`AnomalyDetector.__init__` accepts `sensitivity_multiplier: float = 1.0` kwarg. Applied at coordinator instantiation; bucket change takes effect on entry reload. Energy coordinator's `CONF_ENERGY_ANOMALY_SENSITIVITY` was removed before ship (energy uses cross-check anomaly detection, not z-score AnomalyDetector — would have been a dead config).

### D11 — Canonical `context_json` shape
`build_context_json()` helper in `anomaly_event.py` produces a dict with canonical keys: `zone_id`, `room_id`, `person_id`, `linked_event_id`, `source_signal`. None values omitted. Coordinator-specific extras go under `"extra"`. **Metric fields (observed_value, z_score, etc.) do NOT live in context_json** — they're explicit top-level `AnomalyEvent` dataclass fields (CRITICAL fix from Review B/A).

### D12 — ActivityLogger reuse + recent-anomalies sensor
Every anomaly emit calls `activity_logger.log(action="anomaly", importance=<severity>, ...)` alongside the DAO write — automatically writes to `ura_activity_log` + fires `ura_action` HA event (visible in Logbook) + dispatches `SIGNAL_ACTIVITY_LOGGED`. No new logging infra.

`sensor.ura_coordinator_manager_recent_anomalies` (new):
- State = count last 24h
- Attributes: `top_10` event list (with `metric` key, not `type`), `by_coordinator`, `by_severity`, `by_type` distributions
- Refreshes on `SIGNAL_ACTIVITY_LOGGED` with in-flight + pending guard (burst of N → ≤ 2 refreshes)
- Query uses `idx_anomaly_timestamp` index

### D13 — Diagnostic-dump button
`button.ura_coordinator_manager_anomaly_diagnostic_dump` (DIAGNOSTIC category). Press emits an ERROR-level log line containing recent anomalies + per-coordinator baselines + write queue depth + ActivityLogger dedup cache size. Matches existing HVAC diagnostic-dump pattern.

## Files changed

21 files, +4007 / -124 across:
- Production: `anomaly_event.py`, `coordinator_diagnostics.py`, `database.py`, `safety.py`, `presence.py`, `hvac.py`, `security.py`, `music_following.py`, `energy.py`, `notification_manager.py`, `transitions.py`, `sensor.py`, `button.py`, `config_flow.py`, `const.py`
- Tests: `conftest.py`, `conftest_db.py` (new), `test_v463_behavioral_dao.py` (new, 29 tests), `test_v463_anomaly_migration.py` (new, 60 tests), `test_v461_store_event_writer.py` (refactor), `test_v461_severity_unification.py` (refactor)

## Test count

- v4.6.2.3: 3004 passing
- **v4.6.3: 3093 passing** (+89 new tests across D8/D9 + supplemental coverage)
- Pre-existing 56 failures + 14 errors unchanged (sys.modules cross-contamination in `test_metric_baseline_integration.py`, `test_runtime_smoke.py`, `test_v4511_ac_energy_aware_ramp_down.py`, `test_activity_logger.py`)

## Tier 2 review verdicts

3 targeted parallel reviewers + 2 parallel fix-up agents, then re-verify:

- **Review A — Data integrity + DB architecture:** SHIP WITH FIXES → all 8 findings closed
- **Review B — Migration correctness:** HOLD (1 CRITICAL: payload shape mismatch) → fixed via `AnomalyEvent` dataclass refactor with priority-chain DAO reads
- **Review C — New surfaces + configurability:** HOLD (5 CRITICAL: test infrastructure hand-typed schema) → fixed via runtime extraction from `database.py` source

Review docs persisted in `docs/reviews/code-review/`.

## What's preserved

- **No `anomaly_log` schema changes.** Existing rows readable, indexes unchanged.
- **No write queue architecture change.** Same `database.save_anomaly_event` → `write_queue.add` path.
- **All existing signal chains** (`SIGNAL_SAFETY_HAZARD`, NM dispatch, SIGNAL_ACTIVITY_LOGGED) preserved.
- **Existing anomaly-consuming sensors** (HVAC, presence, MF, etc.) read unchanged column-set.
- **`get_anomaly_count(days)`** unchanged.

## What's NOT done in this cycle

Deferred to v4.6.4 or future cycles:

- `anomaly_log` NOT NULL relaxation via table-rebuild dance (queued; smoke infra here makes it safe)
- `AnomalyType` enum discriminator column promotion (currently in payload top-level)
- Per-metric z-threshold customization (just per-coordinator sensitivity buckets)
- Quiet-hours / scheduled anomaly suppression
- Energy coordinator's own AnomalyDetector (currently uses cross-check anomaly detection)
- LOW findings from reviews (B4, B5, B6, C10-C13): label externalization to translations, test count framing, "decision contradicted within N min" path in D6, etc.

Plus the active v4.6.2 routine awareness soak (Day 1 of 7) continues independently.

## Live validation plan (expanded post-deploy)

Per user direction "additional post deploy checking protocols":

1. **Pre-deploy baseline (captured just before deploy):**
   ```sql
   SELECT coordinator_id, severity, COUNT(*)
   FROM anomaly_log
   WHERE timestamp >= datetime('now', '-24 hours')
   GROUP BY 1, 2;
   ```
2. **Per emit-site controlled trigger:** simulate one anomaly for each migrated coordinator; verify (a) `anomaly_log` row appears with non-zero metric values in the NOT NULL columns (B1 fix), (b) `ura_action` event with `action="anomaly"` fires (visible in HA Logbook), (c) `sensor.ura_coordinator_manager_recent_anomalies` count increments.
3. **24h drift check:** re-run baseline query; per-coordinator row rate within ±25% of baseline (modulo expected new emit types from D4/D5/D6).
4. **DB write queue health:** depth + age metrics — no new contention; startup warmup should NOT extend beyond the existing ~10 min.
5. **Sensor freshness sweep:** every anomaly-consuming sensor updates within one URA cycle of a synthetic emit.
6. **Runtime config verification:** open each coordinator's options flow; confirm "Anomaly Sensitivity" dropdown saves; flip one to `sensitive`, reload, verify z-thresholds shifted (logs).
7. **Diagnostic dump audit:** press the new button; confirm ERROR log line + Logbook entry contain recent anomalies + baselines.
8. **48h soak before declaring shipped:** monitor `sensor.ura_coordinator_manager_recent_anomalies` for unexpected spike (>3× baseline) or coordinator absence.

## New bug classes proposed for QUALITY_CONTEXT.md

From Review A:
- **Schema mirror drift in test fixtures** — never hand-copy production DDL into tests; extract or AST-couple.
- **Dedup-mask via low-cardinality description** — dedup keys built from `coordinator:action:room:description` require descriptions to carry an event-unique numeric/ID distinguisher.

Both already applied in v4.6.3 via the fix-up commits.
