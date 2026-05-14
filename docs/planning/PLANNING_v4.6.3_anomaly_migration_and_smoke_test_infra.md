# PLANNING v4.6.3 — Anomaly Touchpoint Migration + Behavioral DB Smoke Test Infra

**Status:** Plan complete, ready to implement
**Tier:** Tier 2 (10 emit-site migrations + new test infrastructure across multiple coordinators)
**Predecessor:** v4.6.2.3 (review carry-overs)
**Soak interaction:** Touches multiple coordinators (safety, presence, energy, notification_manager). NOT soak-safe during a fresh v4.6.2 soak — schedule after v4.6.2 soak ends (~2026-05-20) OR after v4.6.2 + descendants are confirmed stable for 48-72 h. Confirm with user before deploying.

## Why

Two pieces folded into one cycle for a coherent narrative beat: every anomaly-emitting call site in URA goes through the canonical DAO, AND we get a real-schema test fixture that prevents the bug-class shape that caused v4.6.1.1 from recurring.

### Piece A — Migrate remaining anomaly emit sites through `save_anomaly_event()`

v4.6.1 introduced `database.save_anomaly_event()` as the canonical DAO for anomaly writes. v4.6.1.1 fixed the NOT NULL column gap in that DAO (lossy 0.0 sentinel defaults for AnomalyEvent-style emitters; payload-pack-unpack for legacy callers). v4.6.2 added the regime detector emitter on top of the same DAO.

**What's still NOT migrated** (per `docs/planning/ANOMALY_RECONCILIATION_SURVEY.md` + the v4.6.1 planning doc): ~10 call sites scattered across coordinators still route through the legacy `AnomalyDetector.store_anomaly()` wrapper. The wrapper itself routes through the new DAO since v4.6.1, BUT the call sites construct their payload in coordinator-specific ad-hoc shapes and would all benefit from speaking the canonical `AnomalyEvent` shape directly. Migration makes:

- Future schema migrations atomic (one DAO to update, not 10 call sites)
- Adding new fields (e.g., `type` column for regime_shift vs point_in_time) only needs DAO changes
- The legacy `store_anomaly()` wrapper can be deleted once all callers migrated

### Piece B — Behavioral DB smoke test infrastructure

**Process improvement directly from v4.6.1.1.** Both Tier 2 reviewers read the diff and missed the NOT NULL constraint mismatch because they read source, not live schema. A behavioral test that creates a real sqlite instance, applies the real `migrations/` SQL, and writes through the DAO would have caught it at build time.

**v4.6.3 = pioneer cycle for this pattern.** Subsequent cycles inherit the conftest fixture. Every DAO that writes to a NOT NULL column gets a behavioral test against real schema, not source-grep.

## Scope

### A. Anomaly emit sites to migrate

Per the survey + v4.6.1 planning doc:

1. **Safety hazards (3 emit sites)** — `domain_coordinators/safety.py` — three different hazard types (smoke, CO, leak) each emit through the legacy `store_anomaly()` wrapper today. Migrate to `save_anomaly_event(AnomalyEvent(...))` calls with the canonical payload shape.
2. **Person transitions / transit validator** — `domain_coordinators/presence.py` — invalid-transition rejections currently log via activity_logger but don't emit anomalies. Wire as `type=transition_anomaly` emit through the DAO.
3. **Circuit anomaly** — `domain_coordinators/energy_circuits.py` (implementation per the survey) — already feeds into `SIGNAL_SAFETY_HAZARD`; add an anomaly DAO write alongside.
4. **NM alerts** — `domain_coordinators/notification_manager.py` — when NM dispatches an alert based on an anomaly signal, also persist the anomaly correlation event. Avoids double-counting; this is a write of the alert dispatch decision, not a re-write of the original anomaly.
5. **Decision / compliance / outcome logs** — `domain_coordinators/hvac.py`, `presence.py`, `safety.py` — compliance/outcome logs currently write to `decision_log` and `compliance_log` tables. Audit which ones should also emit anomaly correlation events. (Decision: emit when the outcome was anomalous vs expected, not for every decision.)

**Final emit count: 10 sites across 5-6 files.**

### B. Delete legacy `store_anomaly()` wrapper

After all 10 sites migrated and tests pass, remove `AnomalyDetector.store_anomaly()` from `coordinator_diagnostics.py:797`. Verify zero remaining callers via grep before deletion.

### C. In-memory sqlite conftest fixture

New file `quality/tests/conftest_db.py` (or extend existing `conftest.py`) providing:

```python
@pytest.fixture
def real_schema_db():
    """In-memory sqlite with the real URA schema + migrations applied."""
    import sqlite3
    from custom_components.universal_room_automation.database import (
        _SCHEMA_VERSION, _apply_migrations, _initial_schema_sql
    )
    conn = sqlite3.connect(":memory:")
    conn.executescript(_initial_schema_sql())
    _apply_migrations(conn, from_version=0, to_version=_SCHEMA_VERSION)
    yield conn
    conn.close()
```

(Exact import paths verified against current code at build time. If `database.py` doesn't expose `_initial_schema_sql` and `_apply_migrations` as importable, refactor minimally to expose them — or read the SQL files directly from `migrations/` dir.)

### D. Behavioral tests per DAO

For every DAO function in `database.py` that writes to a NOT NULL column or has non-trivial INSERT logic, write a behavioral test:

- `test_save_anomaly_event_writes_all_not_null_columns` — verify row INSERT succeeds with realistic payload
- `test_save_anomaly_event_legacy_payload_unpacking` — verify v4.6.1.1's payload-extraction works for legacy-shape callers
- `test_save_anomaly_event_minimal_payload_uses_sentinels` — verify the 0.0 / 0 defaults apply when payload omits metric fields
- `test_save_anomaly_event_rejects_invalid_severity` — verify enum enforcement
- Similar coverage for other DAOs (`save_decision_log`, `save_compliance_log`, `save_outcome_log`, `save_room_state`, etc. — exact list determined at build time)

**Target: ≥1 behavioral test per write-DAO, with priority on NOT NULL-column DAOs.**

### E. Migrate v4.6.1 + v4.6.2 source-grep tests to behavioral

A few existing v4.6.x tests in `test_v461_store_event_writer.py` and `test_v462_routine_awareness.py` use source-grep patterns. Where behavioral tests against `real_schema_db` would be more authoritative, refactor — but only for tests that touch DAOs covered by the new fixture. Don't expand scope.

### Out of scope (deferred)

- **`anomaly_log` NOT NULL relaxation via table-rebuild dance** — listed as the next item in the active queue (separate cycle after v4.6.3). The smoke test infra here will make that migration safe.
- **`AnomalyType` enum discriminator column** — deferred to a future cycle. v4.6.2 regime detector already writes `type=regime_shift` via payload; adding a column is the next normalization step.
- **Anomaly cleanup / retention policy** — `anomaly_log` table has no scheduled cleanup. Separate concern; deferred.
- **Activity log behavioral coverage** — same conftest pattern would apply but out of scope here.

## Deliverables

### D1 — Conftest fixture for real-schema sqlite

Create the `real_schema_db` fixture as described in Section C. Verify it correctly applies the current schema version + all migrations.

**Acceptance Criteria**
- **Verify:** Test that uses the fixture can read `PRAGMA user_version` and see `_SCHEMA_VERSION`.
- **Verify:** Fixture-scoped DB has every URA table (anomaly_log, decision_log, compliance_log, outcome_log, room_state, person_visits, bayesian_observations, etc.) — list verified against current `database.py`.
- **Test:** `test_conftest_fixture_applies_full_schema`, `test_conftest_fixture_isolates_per_test`.

### D2 — Migrate Safety hazards (3 emit sites)

Replace each `store_anomaly()` call in `safety.py` with a `database.save_anomaly_event(AnomalyEvent(...))` call. Payload shape per the canonical event dataclass.

**Acceptance Criteria**
- **Verify:** Grep `store_anomaly\(` in `safety.py` returns 0 hits after migration.
- **Verify:** New behavioral test per hazard type confirms a real DB row is inserted via the new emit path.
- **Test:** `test_safety_smoke_hazard_emits_anomaly_event`, `test_safety_co_hazard_emits_anomaly_event`, `test_safety_leak_hazard_emits_anomaly_event`.
- **Live:** Post-deploy, simulate a smoke alarm test and verify `anomaly_log` row appears with `coordinator_id=safety, severity=critical, type=hazard.smoke`.

### D3 — Migrate person-transition anomalies

Wire transit-validator rejections in `presence.py` to emit through the DAO with `type=transition_anomaly`.

**Acceptance Criteria**
- **Verify:** Invalid-transition emit goes through `save_anomaly_event`, not just `activity_logger.log`.
- **Test:** `test_invalid_transition_emits_anomaly_event`.
- **Live:** Force an invalid transition (e.g., manual location override) and confirm an `anomaly_log` row appears.

### D4 — Migrate circuit anomaly

Add `save_anomaly_event` call in `energy_circuits.py` alongside the existing `SIGNAL_SAFETY_HAZARD` dispatch.

**Acceptance Criteria**
- **Verify:** Circuit anomalies generate both a SIGNAL_SAFETY_HAZARD dispatch AND an anomaly_log row.
- **Test:** `test_circuit_anomaly_emits_both_signal_and_anomaly_event`.

### D5 — Migrate NM alert dispatch correlation

In `notification_manager.py`, when an NM alert fires in response to an anomaly signal, write an anomaly-correlation event (NOT a re-write of the source anomaly — a distinct event for "alert dispatched").

**Acceptance Criteria**
- **Verify:** NM dispatching an alert produces an `anomaly_log` row of `type=nm_alert_dispatched` correlated by `payload.source_anomaly_id`.
- **Test:** `test_nm_alert_dispatch_emits_correlation_event`.

### D6 — Migrate decision/compliance/outcome logs (selective)

Audit decision/compliance/outcome log writes. Emit anomaly events only when the outcome was anomalous (e.g., compliance violation, decision contradicted by reality within N minutes).

**Acceptance Criteria**
- **Verify:** Decision-correlated anomaly emits only on outcome-was-wrong cases, not every decision.
- **Test:** `test_compliance_violation_emits_anomaly`, `test_normal_decision_does_not_emit_anomaly`.

### D7 — Delete legacy `store_anomaly()` wrapper

After D2–D6 are merged + tested, delete the wrapper from `coordinator_diagnostics.py`. Grep first to confirm zero remaining callers.

**Acceptance Criteria**
- **Verify:** `grep -n "store_anomaly\(" custom_components/universal_room_automation/` returns 0 hits (or only the deletion site in git history).
- **Test:** `test_store_anomaly_wrapper_deleted` — AST regression confirming the method no longer exists.

### D8 — Behavioral tests per write-DAO

Apply the conftest fixture to write at least one behavioral test per DAO that writes to a NOT NULL column. Catalog the DAOs first via grep, then write tests.

**Acceptance Criteria**
- **Verify:** Every DAO in `database.py` that writes to a NOT NULL column has at least one behavioral test using `real_schema_db`.
- **Test:** Catalog test `test_all_not_null_writing_daos_have_behavioral_tests` that AST-walks `database.py` and asserts coverage.

### D9 — Migrate select source-grep tests to behavioral

Refactor 3–5 source-grep tests in `test_v461_store_event_writer.py` and `test_v462_routine_awareness.py` to behavioral form using `real_schema_db`. Pick the ones with highest production-drift risk.

**Acceptance Criteria**
- **Test count:** delta between v4.6.2.3 and v4.6.3 should show ~5 tests migrated from source-grep → behavioral.

## Files touched

- `custom_components/universal_room_automation/domain_coordinators/safety.py` (~30 LoC)
- `custom_components/universal_room_automation/domain_coordinators/presence.py` (~20 LoC)
- `custom_components/universal_room_automation/domain_coordinators/energy_circuits.py` (~15 LoC)
- `custom_components/universal_room_automation/domain_coordinators/notification_manager.py` (~20 LoC)
- `custom_components/universal_room_automation/domain_coordinators/hvac.py` (~20 LoC) — outcome log audit
- `custom_components/universal_room_automation/domain_coordinators/coordinator_diagnostics.py` (~20 LoC, mostly deletion of `store_anomaly` wrapper)
- `custom_components/universal_room_automation/database.py` (~10 LoC if any DAO refactoring needed to expose schema/migrations cleanly)
- `quality/tests/conftest_db.py` or extension to `conftest.py` (~80 LoC)
- `quality/tests/test_v463_anomaly_migration.py` — new behavioral test file (~250 LoC, ~25 tests across emit sites)
- `quality/tests/test_v463_behavioral_dao.py` — new behavioral DAO test file (~200 LoC, ~15 tests across DAOs)
- `quality/tests/test_v461_store_event_writer.py` — refactor 3–5 tests to behavioral form (~50 LoC delta)

## Cost

- Production: ~600–700 LoC across 7 files
- Tests: ~500–600 LoC across 3 files (2 new, 1 refactor)
- **Tier 2 review (two independent staff-engineer passes + live validation).**

## Risks

1. **Schema/migration import path.** If `database.py` doesn't currently expose its schema + migrations as importable functions, D1 requires refactoring `database.py` to expose them. Mitigation: read SQL from `migrations/` dir directly in the fixture if refactoring is hard, but cite the directory path explicitly.
2. **Legacy `store_anomaly` callers in 3rd-party code.** Should be zero (URA is single-install), but verify via grep across `custom_components/`, `automations/`, `scripts/` before deletion.
3. **Double-emit risk in NM correlation (D5).** If both the original anomaly emit AND the NM correlation emit fire, anomaly_log row count doubles for every NM-dispatched alert. Mitigation: clearly distinguish `type` field and verify no analytics query sums both rows for the same source event.
4. **Test fixture startup cost.** Applying real schema + migrations per test could slow the test suite by 50-100ms × test count. Mitigation: use `scope="session"` fixture sparingly + `scope="function"` for tests that need isolation. Profile after the new tests land.
5. **Coordinator-specific payload shape divergence.** Each coordinator currently builds anomaly payloads ad-hoc. Migration to canonical `AnomalyEvent` shape may surface field-name inconsistencies (e.g., `value` vs `observed_value`). Mitigation: pin the canonical shape per the existing `AnomalyEvent` dataclass; document any per-coordinator extensions in payload JSON.
6. **Live validation step is significant.** Tier 2 requires post-deploy live validation. Smoke-test each migrated emit site (safety, presence, circuit, NM) by triggering a known anomaly condition in a controlled way and confirming an `anomaly_log` row appears with the expected shape.

## Review checklist

- [ ] All 10 emit sites use `save_anomaly_event` instead of `store_anomaly`
- [ ] No regression in existing anomaly behavior (anomalies still surface in sensors, NM hooks, dashboards)
- [ ] `real_schema_db` fixture works across pytest's parallel runner (no shared state leakage)
- [ ] Every NOT NULL-writing DAO has at least one behavioral test
- [ ] Legacy `store_anomaly` deletion verified with grep
- [ ] NM correlation emit distinct from source-anomaly emit (no double-counting)
- [ ] No new module-level imports introduced that could trigger Bug Class #34
- [ ] Tier 2: two independent reviews complete; live validation runs post-deploy

## Live validation post-deploy

1. **Per emit site, trigger a controlled anomaly** and verify an `anomaly_log` row appears:
   - Safety: smoke alarm test mode (~30 sec)
   - Presence: manually override a person to an impossible location for 30 sec
   - Circuit: pull a known breaker for 60 sec (if safe)
   - NM: trigger a synthetic alert
2. **Query the anomaly_log table** post-test:
   ```sql
   SELECT coordinator_id, type, severity, timestamp
   FROM anomaly_log
   WHERE timestamp >= datetime('now', '-1 hour')
   ORDER BY timestamp DESC LIMIT 20;
   ```
   Confirm rows for each migrated emit site.
3. **Verify legacy wrapper is truly gone:** runtime check via attribute lookup (should raise AttributeError or return None).
4. **24-h soak:** monitor for any silent test failures, anomaly_log table growth rate (expect modest increase due to new emit sites — should not be runaway).

## Plan completion tracking

After v4.6.3, the following items from the v4.6.x close-out narrative remain:

- `anomaly_log` NOT NULL relaxation via table-rebuild dance (queued as next cycle; smoke infra here makes it safe)
- v4.7.x Advanced Energy Mgt (still deferred; planning doc complete)

These remain in `docs/BACKLOG.md` and the v4.6.x roadmap memory.

---

## SCOPE EXPANSION (2026-05-14, user-directed)

After initial plan review, user requested adding configurability, observability, and standardized data shape into the same cycle. v4.6.3 ships **all-in-one** (no phasing) per user direction.

### D10 — Per-coordinator anomaly sensitivity (CONFIG + RECONFIG only, clear labels)

**Design constraint from user:** "limit to config and reconfig and use clear labels". So this is NOT a Number entity (those are technical/advanced). It's a single dropdown per coordinator in the options flow.

Add `CONF_<COORD>_ANOMALY_SENSITIVITY` per coordinator (HVAC, presence, energy, safety, security, music_following). Select dropdown with 5 named buckets:

| Selection | Multiplier applied to z-thresholds | Label + helper text |
|---|---|---|
| `very_quiet` | 2.0× (z=4/6/8) | "Very Quiet — only the loudest anomalies get flagged" |
| `quiet` | 1.5× (z=3/4.5/6) | "Quiet — fewer notifications, accepts more variability as normal" |
| `normal` | 1.0× (z=2/3/4, default) | "Normal — standard sensitivity, recommended for most homes" |
| `sensitive` | 0.75× (z=1.5/2.25/3) | "Sensitive — catches subtler anomalies, more notifications" |
| `very_sensitive` | 0.5× (z=1/1.5/2) | "Very Sensitive — flags small deviations; expect frequent advisories" |

Default `normal`. Internal mapping in `coordinator_diagnostics.AnomalyDetector.__init__` applies the multiplier to the default `(advisory=2, alert=3, critical=4)` z-thresholds. No runtime entity, no live tuning — set-it-and-forget-it via options flow.

**Acceptance Criteria**
- **Verify:** Each coordinator's options flow shows the new "Anomaly Sensitivity" dropdown with the 5 labeled options and the helper text.
- **Verify:** Selecting `sensitive` lowers z-thresholds to 1.5/2.25/3 for that coordinator. Confirm via direct read of `AnomalyDetector` instance after entry reload.
- **Test:** `test_anomaly_sensitivity_dropdown_labels_present`, `test_sensitivity_multiplier_applies_to_thresholds`.

### D11 — Standardize `context_json` keys (NO schema change)

For every anomaly emit, build `context_json` with a canonical key set:

```python
context = {
    "zone_id": <str | None>,
    "room_id": <str | None>,
    "person_id": <str | None>,
    "linked_event_id": <int | None>,  # FK into anomaly_log for correlations (D5)
    "source_signal": <str | None>,    # e.g. "SIGNAL_SAFETY_HAZARD"
    # ...plus coordinator-specific extra keys allowed under "extra": {...}
}
```

Document the canonical shape in `domain_coordinators/anomaly_event.py` (the `AnomalyEvent` dataclass docstring). No schema change required — JSON column accepts everything. Future cycle can promote these to first-class columns during the NOT NULL relaxation table-rebuild.

**Acceptance Criteria**
- **Verify:** Every migrated emit site (D2–D6) builds `context_json` containing applicable canonical keys.
- **Verify:** Behavioral test reads back a written row's `context_json`, parses JSON, asserts canonical keys present.
- **Test:** `test_context_json_canonical_shape_<emit_site>` per emit site.

### D12 — Reuse ActivityLogger for anomaly emit, add house-level "Recent Anomalies" sensor

**User direction:** "make sure this is well aligned with our activity stream work that plugged into HA if relevant. Mostly not trying to rebuild infra if we have it."

**ActivityLogger reuse (no new log infra):** Every anomaly emit site calls `activity_logger.log()` alongside `save_anomaly_event()`:

```python
await save_anomaly_event(event)
await self.activity_logger.log(
    coordinator=<coord_name>,
    action="anomaly",
    description=<short human-readable summary>,
    importance=<severity>,  # advisory/alert/critical maps to activity importance
    room=<room_name>,
    zone=<zone_name>,
    entity_id=<related_entity_id>,
    details={"type": <type>, "z_score": ..., "metric_name": ..., ...},
)
```

This automatically:
- Writes to `ura_activity_log` DB table via existing write queue (`activity_logger.py:88`)
- Fires `ura_action` HA event → visible in HA Logbook (`activity_logger.py:117`)
- Dispatches `SIGNAL_ACTIVITY_LOGGED` → existing activity-stream sensors update
- Dedup is handled by ActivityLogger's existing cache

**`sensor.ura_recent_anomalies` (new, house-level):**

| Aspect | Value |
|---|---|
| Entity | `sensor.ura_coordinator_manager_recent_anomalies` |
| State | Count of anomalies in last 24h (across all coordinators) |
| Attributes | `top_10` (list of recent events: timestamp, coord, severity, summary), `by_coordinator` (`{hvac: N, ...}`), `by_severity` (`{advisory: N, alert: N, critical: N}`), `by_type` (`{point_in_time: N, regime_shift: N, ...}`) |
| Source | Queries `anomaly_log` directly (uses existing `idx_anomaly_timestamp` index) |
| Refresh | On `SIGNAL_ACTIVITY_LOGGED` (so it picks up new anomalies immediately when ActivityLogger fires) |

**Acceptance Criteria**
- **Verify:** Every migrated emit site fires `activity_logger.log(action="anomaly", ...)`.
- **Verify:** `ura_action` events with `action="anomaly"` appear in HA Logbook after a synthetic anomaly emit.
- **Verify:** `sensor.ura_coordinator_manager_recent_anomalies` reports count + populated attributes.
- **Test:** `test_anomaly_emit_writes_activity_log`, `test_recent_anomalies_sensor_refresh_on_signal`, `test_recent_anomalies_sensor_distributions`.

### D13 — Anomaly subsystem diagnostic-dump button

Extends the existing HVAC diagnostic-dump pattern (`button.ura_hvac_coordinator_ac_ramp_diagnostic_dump`). New button:

| Aspect | Value |
|---|---|
| Entity | `button.ura_coordinator_manager_anomaly_diagnostic_dump` |
| Category | DIAGNOSTIC |
| On press | Builds a dump dict (recent 50 anomaly_log rows, per-coordinator baseline counts, write queue depth, ActivityLogger dedup cache size) and writes a single ERROR-level log line so it's grep-friendly + visible in Logbook |

Reuses the existing diagnostic-dump button pattern; no new infra.

**Acceptance Criteria**
- **Verify:** Button entity exists, category DIAGNOSTIC.
- **Verify:** Pressing it produces a log line containing recent anomalies + baselines.
- **Test:** `test_anomaly_diagnostic_dump_button_exists`, `test_diagnostic_dump_log_contents`.

### Cost adjustment for expanded scope

| Component | Production | Test |
|---|---|---|
| Existing D1–D9 | ~600 | ~500 |
| **D10 (5 select-dropdown fields)** | ~60 | ~30 |
| **D11 (canonical context_json)** | ~30 | ~30 |
| **D12 (ActivityLogger reuse + recent-anomalies sensor)** | ~110 | ~50 |
| **D13 (diagnostic dump button)** | ~50 | ~20 |
| **Total** | **~850** | **~630** |

Still Tier 2. ~1500 LoC total.

### Three targeted reviews (aligned to all-in-one risk profile)

- **Review A — Data integrity + DB architecture preservation.** Existing `anomaly_log` rows preserved. Write queue unchanged. Indexes still cover read paths. No silent data loss across migration. (User's stated #1 concern.)
- **Review B — Migration correctness + signal chain integrity.** Every emit site produces equivalent rows AND fires ActivityLogger AND preserves any existing signal/dispatch wiring (SIGNAL_SAFETY_HAZARD, NM dispatch, etc.). End-to-end trace per emit site.
- **Review C — New surfaces + configurability.** Sensitivity dropdowns save+restore through options flow; multiplier applies to live thresholds on reload; `sensor.ura_recent_anomalies` distribution attributes correct; diagnostic dump output well-formed; canonical `context_json` shape pinned by tests.

### Expanded post-deploy protocols

1. **Pre-deploy baseline:** `SELECT coordinator_id, severity, COUNT(*) FROM anomaly_log WHERE timestamp >= datetime('now', '-24 hours') GROUP BY 1,2` — save snapshot.
2. **Per emit-site smoke test:** safety (smoke alarm test mode), presence (force invalid transition), circuit (controlled), NM (synthetic). For each, verify (a) `anomaly_log` row appears with expected shape + canonical `context_json` keys, (b) corresponding `ura_action` event with `action="anomaly"` fires (visible in Logbook), (c) `sensor.ura_coordinator_manager_recent_anomalies` count increments.
3. **24h drift check:** re-query baseline. Each coordinator's row rate within ±25% of baseline. NM correlation rows = NM dispatch count ±1.
4. **DB write queue health:** depth + age metrics — no new contention. (Existing memory: ~10-min startup warmup is accepted; this should NOT extend it.)
5. **Sensor freshness sweep:** every anomaly-consuming sensor (HVAC anomaly, presence anomaly, MF anomaly, recent-anomalies, etc.) updates within one URA cycle of a synthetic emit.
6. **Runtime config verification:** open each coordinator's options flow; confirm "Anomaly Sensitivity" dropdown saves; flip one coordinator to `sensitive` and verify z-thresholds shift on next AnomalyDetector init.
7. **Diagnostic dump audit:** press the new button; confirm log line contains recent emits + baselines + queue depth.
8. **48h soak before declaring shipped:** monitor `sensor.ura_recent_anomalies` for any unexpected spike (>3× pre-deploy baseline) or coordinator absence (one of the migrated coords stops emitting entirely).

### Risks added by scope expansion

7. **Sensitivity multiplier interaction with existing baselines.** If a user has been running with z=2 advisory threshold and then dials to `sensitive` (z=1.5), historical baselines unchanged — but more new observations will flag as advisory. This is the INTENDED behavior; document in helper text.
8. **`sensor.ura_recent_anomalies` query performance.** If `anomaly_log` table is large (thousands of rows), the 24h LIMIT query must use the existing `idx_anomaly_timestamp` index. Verify EXPLAIN QUERY PLAN at build time.
9. **ActivityLogger dedup interaction with anomaly emit.** ActivityLogger dedups identical (coordinator, action, room, description, importance) within a window. Anomaly emits with identical descriptions across the dedup window will silently coalesce. Mitigation: include z_score or timestamp in description so descriptions remain unique.
