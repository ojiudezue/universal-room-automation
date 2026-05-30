# URA v4.7.12 — AnomalyType Discriminator

**Release date:** 2026-05-30
**Tier:** Tier 2-DB (three parallel staff-engineer reviews + Live Validation)
**Phase:** Phase B (sequenced AFTER Phase A — v4.7.10 Gitea + v4.7.9 Hygiene + v4.7.11 Egress are live)
**Scope:** Promote the existing `event_class` discriminator from a loose `str` into a typed `AnomalyType` StrEnum, fix three string-literal drift sites, rename the canonical DB column to `anomaly_type`, dual-write both columns during the transition window. No behavioral changes to emit timing or downstream consumers — pure typing + persistence hardening.

**Trigger:**
- v4.6.1 D0 added `event_class TEXT DEFAULT 'point_in_time'` and four module-level constants (`EVENT_CLASS_POINT_IN_TIME` / `EVENT_CLASS_REGIME_SHIFT` / `EVENT_CLASS_HAZARD` / `EVENT_CLASS_TRANSITION_INVALID`).
- Three of thirteen emit sites still passed RAW STRING literals (`binary_sensor.py:1913`, `energy.py:1588`, `regime_detector.py:560`) rather than the constants — drift detectable only by grep.
- v4.7.13+ regime-shift-aware consumer logic needs to import the canonical type without reaching into the dataclass module — `AnomalyType` is the import target.
- Canonical-naming alignment: the dataclass field, the DB column, and the StrEnum should all be `anomaly_type` for v5.0 cleanliness.

---

## Headline Changes

- **D1** — `AnomalyType` StrEnum (POINT_IN_TIME / REGIME_SHIFT / HAZARD / TRANSITION_INVALID) defined in `domain_coordinators/anomaly_event.py`. Legacy `EVENT_CLASS_*` constants become member aliases. `AnomalyEvent.__post_init__` coerces raw strings into typed members and raises `ValueError` on unknown values (drift caught at write time, not at downstream consumer time).
- **D1 (DB)** — Fresh-install CREATE TABLE adds `anomaly_type TEXT DEFAULT 'point_in_time'`. Upgrade-install ALTER TABLE adds the column via the v4.6.1 additive tuple-list. The v4.6.7 NULL-relaxation rebuild dance was updated to carry `anomaly_type` forward across the rebuild. v4.7.12 D1 backfill block (gated on `PRAGMA user_version=4712`) copies `event_class -> anomaly_type` once. `save_anomaly_event` dual-writes BOTH columns during the transition window.
- **D2** — All 13 emit sites migrated to `anomaly_type=AnomalyType.*` kwargs. Three drift-fix sites (`binary_sensor.py`, `energy.py:1588`, `regime_detector.py`) now use the typed enum instead of raw strings. `regime_detector.py` remains the SOLE `AnomalyType.REGIME_SHIFT` emit site.
- **D3** — `AnomalyType` exposed via `__all__` for v4.7.13+ consumer imports; legacy `EVENT_CLASS_*` aliases also exported for back-compat.
- **D4** — 16 new behavioral + AST drift-prevention tests in `quality/tests/test_v4712_anomaly_type_discriminator.py`. Existing anomaly tests updated to use the new kwarg.
- **D5** — This README + pre/post-deploy row-rate snapshot procedure.

**Out of scope (per plan §12):**
- No emitter migrated FROM `point_in_time` TO `regime_shift` — that's a v4.7.13+ cycle.
- `event_class` column NOT dropped — deferred to v5.0 alongside the legacy `EVENT_CLASS_*` constants.
- No new sensors, buttons, or composite indexes. Pure infra cycle.
- `AnomalyRecord` dataclass at `coordinator_diagnostics.py:113` is untouched — diagnostics-classifier internal type, NOT the persistence discriminator.

---

## Per-Deliverable Detail

### D1 — `AnomalyType` enum + dataclass field rename + DB migration

**Files:** `domain_coordinators/anomaly_event.py`, `database.py`.

- `class AnomalyType(StrEnum)` with exactly 4 members: `POINT_IN_TIME`, `REGIME_SHIFT`, `HAZARD`, `TRANSITION_INVALID`. `StrEnum` means `AnomalyType.POINT_IN_TIME == "point_in_time"` is True, so legacy string comparisons keep working.
- A Python 3.9 back-compat shim mirrors the pattern in `security.py:27-33` / `weather_manager.py:23-29` so test environments without 3.11 still import the module.
- Legacy `EVENT_CLASS_*` module-level constants are now `AnomalyType` member aliases. Any caller that imports them keeps working unchanged.
- `AnomalyEvent.event_class: str` → `AnomalyEvent.anomaly_type: AnomalyType`. The dataclass remains required (no default), so any silent omission at an emit site raises `TypeError` at construction.
- `AnomalyEvent.__post_init__` coerces a bare-string `anomaly_type=` to the matching enum member, and raises `ValueError` for unknown strings. Future drift detected at write time, never at the downstream consumer.
- A read-only `event.event_class` property aliases `anomaly_type` for the dual-write window so any legacy code that still reads `event.event_class` keeps working.
- DB:
  - Fresh-install `CREATE TABLE anomaly_log` adds `anomaly_type TEXT DEFAULT 'point_in_time'` (same default as the legacy `event_class` column, so post-migration both rows carry the same value).
  - v4.6.1 ALTER TABLE tuple-list grew by one entry — `("anomaly_type", "TEXT DEFAULT 'point_in_time'")`.
  - v4.6.7 rebuild dance now reads `PRAGMA table_info` to detect whether the source table already has `anomaly_type`; if yes, copies forward with `COALESCE(anomaly_type, event_class, 'point_in_time')`; if no, derives from `COALESCE(event_class, 'point_in_time')`.
  - v4.7.12 D1 backfill block runs once, gated on `PRAGMA user_version < 4712`. `UPDATE anomaly_log SET anomaly_type = COALESCE(event_class, 'point_in_time') WHERE anomaly_type IS NULL OR anomaly_type = 'point_in_time'`. Sets `PRAGMA user_version = 4712` on success.
- `save_anomaly_event` INSERT column list extended to 21 columns; resolution order prefers `event.anomaly_type` and falls back to `event.event_class`. Same string lands in BOTH columns during the dual-write window.

### D2 — Emit-site migration (13 sites)

**Files:** `binary_sensor.py`, `__init__.py`, `transitions.py`, plus 10 files under `domain_coordinators/`.

| File:line | Pre-cycle | Post-cycle |
|---|---|---|
| `binary_sensor.py:1913` | `event_class="point_in_time"` | `anomaly_type=AnomalyType.POINT_IN_TIME` |
| `__init__.py:2206` | `event_class=EVENT_CLASS_POINT_IN_TIME` | `anomaly_type=AnomalyType.POINT_IN_TIME` |
| `transitions.py:421` | `event_class=EVENT_CLASS_TRANSITION_INVALID` | `anomaly_type=AnomalyType.TRANSITION_INVALID` |
| `domain_coordinators/hvac.py:1816` | `event_class=EVENT_CLASS_POINT_IN_TIME` | `anomaly_type=AnomalyType.POINT_IN_TIME` |
| `domain_coordinators/energy.py:1588` | `event_class="point_in_time"` | `anomaly_type=AnomalyType.POINT_IN_TIME` |
| `domain_coordinators/energy.py:3334` | `event_class=EVENT_CLASS_POINT_IN_TIME` | `anomaly_type=AnomalyType.POINT_IN_TIME` |
| `domain_coordinators/regime_detector.py:560` | `event_class="regime_shift"` | `anomaly_type=AnomalyType.REGIME_SHIFT` |
| `domain_coordinators/coordinator_diagnostics.py:555` | `event_class=EVENT_CLASS_POINT_IN_TIME` | `anomaly_type=AnomalyType.POINT_IN_TIME` |
| `domain_coordinators/security.py:794` | `event_class=EVENT_CLASS_POINT_IN_TIME` | `anomaly_type=AnomalyType.POINT_IN_TIME` |
| `domain_coordinators/notification_manager.py:960` | `event_class=EVENT_CLASS_POINT_IN_TIME` | `anomaly_type=AnomalyType.POINT_IN_TIME` |
| `domain_coordinators/presence.py:2236` | `event_class=EVENT_CLASS_POINT_IN_TIME` | `anomaly_type=AnomalyType.POINT_IN_TIME` |
| `domain_coordinators/music_following.py:352` | `event_class=EVENT_CLASS_POINT_IN_TIME` | `anomaly_type=AnomalyType.POINT_IN_TIME` |
| `domain_coordinators/safety.py:1855` | `event_class=EVENT_CLASS_HAZARD` | `anomaly_type=AnomalyType.HAZARD` |

`energy.py:3297` had a local variable named `anomaly_type` that shadowed the new import; renamed to `anomaly_subtype` to avoid the clash. The variable still encodes the circuit-anomaly subtype (`"tripped_breaker"` / `"undercurrent"` / etc.) — only the local name changed.

### D3 — Module export surface

`__all__` in `domain_coordinators/anomaly_event.py` exposes:
- `AnomalySeverity` (existing)
- `AnomalyType` (new, v4.7.12 D3)
- `AnomalyEvent`
- `build_context_json`
- `map_diag_severity`
- All four legacy `EVENT_CLASS_*` aliases

v4.7.13+ regime-shift consumers import via `from custom_components.universal_room_automation.domain_coordinators.anomaly_event import AnomalyType`. No re-export added in `domain_coordinators/__init__.py` because that file does not currently re-export anomaly symbols.

### D4 — Tests

**New file:** `quality/tests/test_v4712_anomaly_type_discriminator.py` (16 functions, all passing).

Coverage:
- Enum surface (4 members, no extras; `AnomalyType` is both Enum and str subclass)
- Legacy `EVENT_CLASS_*` aliases (`is` AnomalyType members; `==` raw string values)
- `__post_init__` accepts raw strings, rejects unknowns with `ValueError`
- `AnomalyEvent` requires `anomaly_type` kwarg (no default → `TypeError`)
- `__all__` exports
- Fresh-schema fixture has BOTH `event_class` and `anomaly_type` columns
- Backfill migration copies `event_class -> anomaly_type` exactly once
- Migration is idempotent under `PRAGMA user_version=4712` gate
- `save_anomaly_event` dual-writes both columns with the same value
- Resolution order prefers `event.anomaly_type` over `event.event_class`
- AST scans: every `AnomalyEvent(...)` call uses `anomaly_type=` (not `event_class=`)
- AST scans: every `anomaly_type=` RHS is a `Name` or `Attribute`, never a raw string
- `regime_detector.py` is the SOLE `AnomalyType.REGIME_SHIFT` emit site

**Schema-extractor hygiene** (also v4.7.12):
- `quality/tests/conftest_db.py::_extract_alter_table_statements` backward-window widened from 800 to 2000 chars. The v4.6.1 anomaly_log tuple list grew with each cycle that added a column; 800 chars was no longer enough to reach the first entry (`event_class`). Symptom would have been: the fresh-schema fixture silently drops legacy columns and behavioral DAO tests pass against a stale schema. Caught by the v4.7.12 D4 schema-extraction test.

**Existing tests touched** (kwarg rename + dual-write tuple length):
- `test_v461_anomaly_event_dataclass.py`
- `test_v461_canary_migrations.py`
- `test_v462_d4_regime_detector.py`
- `test_v463_behavioral_dao.py` (`_FakeAnomalyEvent` accepts both kwargs; `_insert_anomaly` value tuple grows to 21)
- `test_v463_anomaly_migration.py` (6 `_ANOMALY_INSERT_SQL` call sites updated)
- `test_v466_severity_refactor.py` (the `_insert_anomaly_row` helper updated to 21-tuple)
- `test_v4_6_11_d3_persistence_and_dispatch.py`

---

## D5 — Pre/Post-Deploy Row-Rate Snapshot

Tier 2-DB protocol (`CLAUDE.md § Tier 2-DB`) requires a pre-deploy row-rate snapshot to compare against 1h and 24h post-deploy rates. If any `(coordinator_id, severity)` bucket changes by more than ±25%, that's a HIGH finding — phantom emits or lost emits.

### Pre-deploy snapshot procedure

Run via MCP `ura-sqlite` against the live HA DB (`/Users/ojiudezue/ha-config/universal_room_automation/data/universal_room_automation.db`) **immediately before** invoking `./scripts/deploy.sh`:

```sql
-- Snapshot 1: 7-day baseline rates, grouped by (coordinator_id, severity, event_class)
SELECT
    coordinator_id,
    severity,
    event_class,
    COUNT(*) AS row_count,
    MIN(timestamp) AS earliest,
    MAX(timestamp) AS latest
FROM anomaly_log
WHERE timestamp >= datetime('now', '-7 days')
GROUP BY coordinator_id, severity, event_class
ORDER BY row_count DESC;

-- Snapshot 2: 1h + 24h windows for the ±25% comparison
SELECT
    coordinator_id,
    severity,
    event_class,
    SUM(CASE WHEN timestamp >= datetime('now', '-1 hour')  THEN 1 ELSE 0 END) AS rows_1h,
    SUM(CASE WHEN timestamp >= datetime('now', '-24 hours') THEN 1 ELSE 0 END) AS rows_24h
FROM anomaly_log
WHERE timestamp >= datetime('now', '-7 days')
GROUP BY coordinator_id, severity, event_class
ORDER BY rows_24h DESC;
```

### Pre-deploy snapshot table

**TO BE FILLED AT DEPLOY TIME** — run the queries above and paste the output. Operator must populate this section before `./scripts/deploy.sh` is invoked.

| coordinator_id | severity | event_class | rows_1h | rows_24h | rows_7d |
|---|---|---|---|---|---|
| _(populate from query output)_ | | | | | |

### Post-deploy comparison procedure

After `./scripts/deploy.sh 4.7.12 ...` completes AND HACS installs the version AND HA restarts cleanly:

**1 hour post-restart:** re-run the same queries against the new column name:

```sql
SELECT
    coordinator_id,
    severity,
    anomaly_type,
    SUM(CASE WHEN timestamp >= datetime('now', '-1 hour')  THEN 1 ELSE 0 END) AS rows_1h_post,
    SUM(CASE WHEN timestamp >= datetime('now', '-24 hours') THEN 1 ELSE 0 END) AS rows_24h_post
FROM anomaly_log
WHERE timestamp >= datetime('now', '-7 days')
GROUP BY coordinator_id, severity, anomaly_type
ORDER BY rows_24h_post DESC;
```

**24 hours post-restart:** same query again. Compare each `(coordinator_id, severity)` bucket against the pre-deploy 24h rate.

### Pass criterion

Every `(coordinator_id, severity)` bucket must be within ±25% of the pre-deploy 24h rate. Any bucket outside that band is a HIGH finding and triggers Tier 2-DB rollback review.

Additional post-deploy verification (Review D / Live Validation):

| Check | Tool | Pass criterion |
|---|---|---|
| Schema rename landed | `PRAGMA table_info(anomaly_log)` | Both `event_class` and `anomaly_type` present |
| Migration gate set | `PRAGMA user_version` | Returns `4712` |
| Backfill copied historical rows | `SELECT COUNT(*) FROM anomaly_log WHERE event_class != anomaly_type` | `0` |
| Real values flow through | `SELECT DISTINCT anomaly_type FROM anomaly_log WHERE timestamp >= datetime('now', '-1 hour')` | Subset of `{point_in_time, regime_shift, hazard, transition_invalid}` |
| Dual-write integrity | `SELECT COUNT(*) FROM anomaly_log WHERE timestamp >= datetime('now', '-1 hour') AND event_class != anomaly_type` | `0` |
| No `__post_init__` rejections | `ha-mcp get_logs source=system_service slug=core` | Zero lines matching `"AnomalyEvent.anomaly_type must be a member of AnomalyType"` |
| Sentinel-free emit shape | `SELECT COUNT(*) FROM anomaly_log WHERE timestamp >= datetime('now', '-1 hour') AND observed_value = 0.0 AND expected_mean = 0.0` | 0 unless a legitimate binary-event row landed |

If ANY check fails: HOLD. Do not proceed to v4.7.13.

### Post-deploy snapshot results

**TO BE FILLED 1 HOUR AND 24 HOURS POST-RESTART.**

#### 1h post-restart
| coordinator_id | severity | anomaly_type | rows_1h_post | Delta vs pre-deploy 1h |
|---|---|---|---|---|
| _(populate from query output)_ | | | | |

#### 24h post-restart
| coordinator_id | severity | anomaly_type | rows_24h_post | Delta vs pre-deploy 24h |
|---|---|---|---|---|
| _(populate from query output)_ | | | | |

---

## Bug Class Coverage

| Class | Surface | Mitigation |
|---|---|---|
| #7 (stale data source) | Test fixture vs production schema | `conftest_db._extract_alter_table_statements` parses production source; D4 test verifies the parser finds the new tuple |
| #22 (enum mismatch) | `AnomalyType` StrEnum surface | StrEnum equality with string literals preserves back-compat; `__post_init__` validates unknown values |
| #44 (test-infra schema authority) | Test fixtures | All tests use `real_schema_db` fixture; AST scan for kwarg name; no hand-copied DDL |
| v4.7.12 specific — rename-time field skew | DAO read path | Dual-column write during the transition window; resolution order prefers `anomaly_type` with `event_class` fallback |
| v4.7.12 specific — migration re-run on rollback-then-reapply | Backfill UPDATE | PRAGMA `user_version=4712` gate; idempotent UPDATE is a no-op on second run |
| v4.7.12 specific — caller passes None for `anomaly_type` | Dataclass `__post_init__` | TypeError raised by required-without-default field |
| v4.7.12 specific — schema-extractor window too narrow | `conftest_db` regex | Backward window widened 800 -> 2000 chars |

---

## Test Results

- **Cycle tests:** 16/16 passing (`PYTHONPATH=quality python3 -m pytest quality/tests/test_v4712_anomaly_type_discriminator.py -v`).
- **Anomaly regression band:** 0 new failures across `test_v461_*`, `test_v462_*`, `test_v463_*`, `test_v466_*`, `test_v4_6_11_*` vs the v4.7.11 baseline.
- **Full suite delta vs baseline:** within noise band (`test_v462_d3_away_typical::test_staleness_number_registered_in_cm_setup` was already failing pre-cycle).
- **5 pre-deploy zero-bugs gates:**
  1. Conflict markers: zero (`grep -rn '<<<<<<<\|=======\|>>>>>>>' custom_components/universal_room_automation/ quality/tests/`).
  2. `py_compile` of all changed `.py` files: clean.
  3. Cycle test suite: pass.
  4. Anomaly regression tests: pass.
  5. Full-suite baseline diff: no unexpected regressions.

---

## Files Changed

Production:
- `custom_components/universal_room_automation/domain_coordinators/anomaly_event.py`
- `custom_components/universal_room_automation/database.py`
- `custom_components/universal_room_automation/binary_sensor.py`
- `custom_components/universal_room_automation/__init__.py`
- `custom_components/universal_room_automation/transitions.py`
- `custom_components/universal_room_automation/domain_coordinators/hvac.py`
- `custom_components/universal_room_automation/domain_coordinators/energy.py`
- `custom_components/universal_room_automation/domain_coordinators/regime_detector.py`
- `custom_components/universal_room_automation/domain_coordinators/coordinator_diagnostics.py`
- `custom_components/universal_room_automation/domain_coordinators/security.py`
- `custom_components/universal_room_automation/domain_coordinators/notification_manager.py`
- `custom_components/universal_room_automation/domain_coordinators/presence.py`
- `custom_components/universal_room_automation/domain_coordinators/music_following.py`
- `custom_components/universal_room_automation/domain_coordinators/safety.py`

Tests:
- `quality/tests/test_v4712_anomaly_type_discriminator.py` (new — 16 tests)
- `quality/tests/conftest_db.py` (backward-window widened)
- `quality/tests/test_v461_anomaly_event_dataclass.py`
- `quality/tests/test_v461_canary_migrations.py`
- `quality/tests/test_v462_d4_regime_detector.py`
- `quality/tests/test_v463_behavioral_dao.py`
- `quality/tests/test_v463_anomaly_migration.py`
- `quality/tests/test_v466_severity_refactor.py`
- `quality/tests/test_v4_6_11_d3_persistence_and_dispatch.py`

Docs:
- `docs/readmes/README_v4.7.12.md` (this file)
- `docs/planning/PLANNING_v4.7.12_anomaly_type_discriminator.md` (cycle plan)
