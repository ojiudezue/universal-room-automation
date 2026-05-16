# v4.6.7 — anomaly_log NOT NULL relaxation

**Date:** 2026-05-16 CDT (same day as v4.6.3.3 / v4.6.4 / v4.6.5 / v4.6.5.1 / v4.6.5.2 / v4.6.5.3 / v4.6.6 — seven-deploy day pre-v4.6.7)
**Tier:** Tier 1 (single review) — gated schema change with table-rebuild dance
**Predecessor:** v4.6.6 (severity vocabulary refactor)

## Why

Pre-v4.6.7 the `anomaly_log` table declared 5 metric columns as NOT NULL:
- `observed_value REAL NOT NULL`
- `expected_mean REAL NOT NULL`
- `expected_std REAL NOT NULL`
- `z_score REAL NOT NULL`
- `sample_size INTEGER NOT NULL`

When an emit fired before the AnomalyDetector baseline had any samples (or when a legacy caller didn't populate the fields), the DAO synthesized 0.0/0 sentinels to satisfy the constraint (v4.6.1.1 hotfix). v4.6.3 review B1 caught this as **silently masking the difference between "baseline not yet learned" and "legitimate 0.0 observation."** Analytics looking at `observed_value=0.0` rows can't tell whether the metric was genuinely zero or whether the row was a baseline-warmup artifact.

v4.6.7 relaxes the schema so NULL is permitted, and simplifies the DAO so `None` passes through honestly.

## Changes

### Schema relaxation

`CREATE TABLE IF NOT EXISTS anomaly_log` updated to allow NULL on the 5 metric columns. Fresh DBs use the relaxed schema directly. Identity columns (`timestamp`, `coordinator_id`, `scope`, `metric_name`, `severity`) remain NOT NULL — regression test guards against accidental over-relaxation.

### Migration (table-rebuild dance, gated)

SQLite can't `ALTER COLUMN` to remove NOT NULL, so existing DBs go through the standard rebuild dance:

```sql
BEGIN;
CREATE TABLE anomaly_log_v467 (... relaxed schema ...);
INSERT INTO anomaly_log_v467 (col1, col2, ...) SELECT col1, col2, ... FROM anomaly_log;
DROP TABLE anomaly_log;
ALTER TABLE anomaly_log_v467 RENAME TO anomaly_log;
CREATE INDEX idx_anomaly_timestamp ON anomaly_log(timestamp);
CREATE INDEX idx_anomaly_coordinator ON anomaly_log(coordinator_id);
CREATE INDEX idx_anomaly_scope ON anomaly_log(scope);
CREATE INDEX idx_anomaly_severity ON anomaly_log(severity);
PRAGMA user_version = 467;
COMMIT;
```

Critical implementation details:
- **PRAGMA user_version=467 gate.** The rebuild runs once per DB; subsequent restarts find `user_version >= 467` and skip. Same one-shot pattern as v4.6.6 D2 (which uses sentinel 466).
- **Explicit column list** in `INSERT INTO ... SELECT` (NOT `SELECT *`). The v4.6.1 ALTER TABLE appended 6 columns at the end (`event_class`, `recovery_at`, `correlation_id`, `entity_id`, `room_id`, `person_id`) which would have caused silent data loss with `SELECT *`.
- **Fresh-DB fast path.** When `PRAGMA table_info` shows the metric columns already lack NOT NULL (fresh DB created with v4.6.7 DDL), the migration block skips the rebuild and just bumps `user_version`.
- **Rollback on exception (review H1).** If any step fails, `await db.rollback()` closes the failed transaction so downstream migration blocks (regime_cell_state, etc.) don't leak into a half-built rebuild transaction. The orphan `anomaly_log_v467` table (if it exists post-failure) is named in the error message so operators can DROP it manually.

### DAO simplification

`save_anomaly_event` replaces 5 manual fallback chains with a single `_resolve_metric` helper. The pre-v4.6.7 code had per-field logic like:

```python
observed_value = (
    _ev_observed_value
    if (_ev_observed_value is not None and _ev_observed_value != 0.0)
    else (payload_dict.get("observed_value") or _payload_extra.get("observed_value") or 0.0)
)
```

The legacy v4.6.3 B1 fallback chain (dataclass field → payload top-level → payload['extra']) is preserved for callers that bury values in payload — but the trailing `or 0.0` sentinel synthesis is removed. NULL now reaches the column honestly.

## Tier 1 review fixes applied

| Finding | Fix |
|---|---|
| **H1** | `await db.rollback()` in migration exception handler — prevents transaction leak into downstream migration blocks |
| **H2** | New behavioral test `test_v467_rebuild_dance_preserves_rows_and_indexes_and_allows_null` — builds pre-v4.6.7 schema in isolated sqlite, runs the rebuild SQL, asserts row count + value round-trip + all 4 indexes recreated + NULL writability + PRAGMA sentinel. Closes the C-H2 gap pattern v4.6.6 surfaced. |
| **M1** | Removed dead `zero_default` parameter from `_resolve_metric` (was unused after sentinel synthesis removed) |
| **M2** | Corrected misleading "SELECT *" comment — code uses explicit column list (and must — column-order brittleness) |

## Files changed

- `custom_components/universal_room_automation/database.py` — CREATE TABLE DDL relaxed (5 cols NULL) + new v4.6.7 migration block (rebuild dance + PRAGMA gate + rollback) + `save_anomaly_event` DAO simplified via `_resolve_metric` helper
- `quality/tests/test_v467_anomaly_log_null_relaxation.py` — new (8 tests: schema check, identity-NOT-NULL preservation, DAO simplification, NULL round-trip, real-values round-trip, migration-block structure, explicit-column-list check, behavioral rebuild-dance test)
- `quality/tests/test_v461_store_event_writer.py` — 1 test inverted (`test_save_anomaly_event_handles_legacy_not_null_columns` → `test_save_anomaly_event_legacy_payload_fallback_preserved` with v4.6.7 semantics)
- `docs/readmes/README_v4.6.7.md` — new

## Test count

- v4.6.6: 3156 passing
- **v4.6.7: 3164 passing** (+8 new tests, 0 regressions)
- Pre-existing 56 failures + 14 errors unchanged

## Live validation plan

1. **Post-restart log check:** look for `v4.6.7 anomaly_log NULL relaxation: rebuilt table with NULL on observed_value/expected_mean/expected_std/z_score/sample_size. Copied N rows, recreated 4 indexes. user_version → 467.` On a fresh DB, instead see DEBUG-level `v4.6.7: anomaly_log NULL columns already relaxed (fresh DB). user_version → 467.`
2. **Idempotency check:** second restart must log `v4.6.7 anomaly_log NULL relaxation: user_version=N ≥ 467, skipping (already relaxed).` at DEBUG level — proves the gate works.
3. **Direct DB query:** `PRAGMA table_info(anomaly_log)` should show `notnull=0` for `observed_value`, `expected_mean`, `expected_std`, `z_score`, `sample_size`; `notnull=1` for `timestamp`, `coordinator_id`, `scope`, `metric_name`, `severity`.
4. **Index check:** `PRAGMA index_list(anomaly_log)` should show all 4 original indexes (`idx_anomaly_timestamp`, `idx_anomaly_coordinator`, `idx_anomaly_scope`, `idx_anomaly_severity`).
5. **Row count preservation:** compare row count immediately before deploy (snapshot the user's DB count) to row count immediately after — must match exactly.

## What this is NOT

- Not a back-compat break — existing rows preserved, existing readers (URARecentAnomaliesSensor, NM correlation) handle NULL via SQL's natural NULL semantics.
- Not a v4.6.6 dependency — v4.6.6's `user_version=466` sentinel is preserved; v4.6.7's `user_version=467` only runs after v4.6.6 has bumped through 466.
- Not a behavioral change to how anomalies are detected — `AnomalyDetector` still emits when z-score thresholds fire; what changes is what gets written when the metric values genuinely don't exist (no baseline yet → NULL instead of 0.0 sentinel).
- Not the end of the cycle — should soak alongside v4.6.6 for ~24h. If `by_severity` distribution looks healthy and no rebuild-dance errors appear in logs, the doctrine cycle is closed for this stretch.
