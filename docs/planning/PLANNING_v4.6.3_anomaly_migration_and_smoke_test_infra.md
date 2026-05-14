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
