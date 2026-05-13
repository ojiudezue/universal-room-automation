# v4.6.1 — Anomaly Reconciliation Foundation (D0 + D1 + D2)

**Date:** 2026-05-13 CDT
**Type:** Tier 2 feature cycle (2 independent staff-engineer reviews + live validation)
**Predecessor:** v4.6.0 (per-person likely_next_room accuracy pipeline)
**Ships silent** — no user-visible feature change. Validates the unified `AnomalyEvent` shape before v4.6.2 layers B6/B7 features on top.

## Summary

URA's anomaly infrastructure was fragmented across 12 touchpoints with 8 severity vocabularies, inconsistent recovery semantics, and an `anomaly_log` table that grew indefinitely (no cleanup). The `ANOMALY_RECONCILIATION_SURVEY.md` (2026-05-06) catalogued the mess. v4.6.1 lands the foundation: one dataclass, one severity enum, one canonical write path, one nightly cleanup with two-tier retention.

Two canary emitters migrate to prove the unified shape works. The remaining 10 touchpoints stay untouched this cycle — bounds risk, lets v4.6.2 carry the feature work.

Bonus: a small UX fix bundles with this cycle — v4.6.0's `*_next_room_accuracy` sensors now carry `PERCENTAGE` unit so they render as `22.2%` not bare `22.2`.

## Three deliverables

### D0 — Unified `AnomalyEvent` schema + DB migration + canonical writer

- **New module:** `domain_coordinators/anomaly_event.py` — `AnomalySeverity(IntEnum)` (INFO=0, WARNING=1, CRITICAL=2) + `AnomalyEvent` dataclass + `event_class` literal set (`point_in_time`, `regime_shift`, `hazard`, `transition_invalid`)
- **`anomaly_log` migration:** idempotent ALTER TABLE ADD COLUMN × 6 — `event_class TEXT DEFAULT 'point_in_time'`, `recovery_at`, `correlation_id`, `entity_id`, `room_id`, `person_id`. PRAGMA-checked, single transaction.
- **Canonical writer:** `database.save_anomaly_event(event)` is the single INSERT path. `AnomalyDetector.store_event(event)` delegates to it. Legacy `store_anomaly(record)` wraps as a thin adapter for the ~6 existing call sites in HVAC/Safety/Security/Energy/Presence.

### D1 — Severity vocab unification

8 severity scales → 3:
- `AnomalySeverity.NOMINAL` → `INFO` (z below advisory threshold)
- `AnomalySeverity.ADVISORY` → `WARNING` (z≥2)
- `AnomalySeverity.ALERT` → `WARNING` (z≥3 — collapsed; CRITICAL reserved for z≥4)
- `AnomalySeverity.CRITICAL` → `CRITICAL`
- ActivityLogger 3-level (`info` / `notable` / `critical`) → INFO / WARNING / CRITICAL
- NM 4-level → INFO / WARNING / CRITICAL per survey §2

**Backfill migration (review fix F3):** legacy `anomaly_log` rows had TEXT severities (`'nominal'`/`'advisory'`/`'alert'`/`'critical'`). New rows via DAO store `int(severity)` (numeric strings via TEXT affinity). Without backfill, v4.6.2 D5 queries with `severity >= 1` would coerce non-numeric TEXT to 0 and silently exclude legacy rows. Migration runs idempotent `UPDATE … CASE … WHERE severity IN (4 legacy values)`.

### D2 — Nightly cleanup of orphaned anomalies

- **`database.cleanup_anomaly_log(retention_days_point_in_time=90, retention_days_regime_shift=365)`** — two retention windows, branched on `event_class`. Regime-shift events worth keeping a year for retrospective context; point-in-time events are noisy and prune at 90 days.
- **NULL-safe via COALESCE (review fix F2):** the branch uses `COALESCE(event_class, 'point_in_time') != 'regime_shift'`. Raw `event_class != 'regime_shift'` is SQLite-NULL-unsafe — `NULL != 'X'` evaluates to NULL (falsy), so a row with NULL `event_class` would accumulate forever.
- Batched: `LIMIT 1000` per pass with `asyncio.sleep(0.1)` between batches (matches `cleanup_room_energy_baselines` pattern). Each batch is its own transaction.
- **Registered in BOTH `_cleanup_ops` AND `_cleanup_ops_d`** (Bug Class #27 prevention added in v4.2.28).

## Canary migrations

Two emitters now route through `database.save_anomaly_event()`:

1. **Energy crosscheck divergence** (`energy.py`) — when `|Envoy_today − our_lifetime_delta| / reference > 15%`, emit `AnomalyEvent(coordinator='energy', type='energy.crosscheck_divergence', severity=WARNING, event_class='point_in_time')`. Parallel to the existing `_envoy_data_anomaly_at` in-memory flag (sensor's stale-derivation logic unaffected).
2. **Bayesian prediction anomaly** (`binary_sensor.py:_fire_anomaly_alert`) — on rising edge (new anomaly detected, not on every poll), emit `AnomalyEvent(coordinator='bayesian', type='bayesian.prediction_anomaly', severity=WARNING, event_class='point_in_time', room_id=...)`. Existing NM + signal paths preserved.

Other 10 touchpoints (safety hazards, person transitions, transit validator, circuit anomaly, NM alerts, decision/compliance/outcome logs) — **untouched this cycle**. Opportunistic migration in v4.6.2+.

## Bundled UX fix

`PersonNextRoomAccuracySensor` + `HouseNextRoomAccuracySensor` now carry `_attr_native_unit_of_measurement = PERCENTAGE`. Live deploy showed bare `22.2` on the CM device page; now renders `22.2%`. 2 lines + 2 regression-guard tests.

## Tier 2 Review

Two independent staff-engineer passes against `pre-review-v4.6.1` tag. Both APPROVE WITH FIXES; findings substantially overlapped.

| ID | Sev | Issue | Fix applied |
|---|---|---|---|
| B2 / F1 | HIGH | Canaries bypass `store_event()` with copy-paste raw INSERT SQL (3 sites) — defeats D0's "single write path" promise | Extract DAO `database.save_anomaly_event(event)`; route `store_event` + both canaries through it. Zero raw INSERT outside DAO. |
| F2 | MEDIUM | Cleanup SQL `event_class != 'regime_shift'` is NULL-unsafe in SQLite | `COALESCE(event_class, 'point_in_time') != 'regime_shift'` |
| F3 | MEDIUM | Severity column type drift (old TEXT vs new INT-as-TEXT) — v4.6.2 `severity >= 1` queries would silently exclude legacy rows | Idempotent backfill UPDATE in migration block: legacy 4 TEXT values → '0'/'1'/'2' |
| — | — | Missing acceptance test for `recovery_at` field | Added |
| B3 | MEDIUM | Dead `_AnomalyEvent` alias import in `store_event` | Killed when `store_event` was simplified to delegator |
| B1 / F4 | LOW | Energy canary uses `hass.async_create_task` (untracked) per pre-existing energy.py pattern (7+ sites) | Documented as pre-existing debt; not amplified by this change |
| F5 | LOW | `event_class` as string literals, not StrEnum | Acceptable for v4.6.1; formalize when v4.6.2 regime detector adds `regime_shift` events |

5 review-fix regression-guard tests added pinning the fixes.

## Test count

- v4.6.0 baseline: 2693 passing
- **v4.6.1: 2774 passing** (+81: 76 v461 + 5 review-fix guards. v460 also gained 2 % unit guards = +83 total)
- Same 56 pre-existing failures + 14 errors (all HA-import-dependent test files unrelated to this cycle)

New test files:
- `test_v461_anomaly_event_dataclass.py` (12 tests)
- `test_v461_db_migration.py` (10 tests → 12 with F3 + recovery_at)
- `test_v461_store_event_writer.py` (11 tests, refactored for delegator + DAO split)
- `test_v461_severity_unification.py` (10 tests)
- `test_v461_cleanup_anomaly_log.py` (12 tests → 13 with F2 guard)
- `test_v461_canary_migrations.py` (18 tests, refactored to assert DAO routing)

## Live validation plan (post-restart)

1. **Verify migrations ran** — check INFO logs for `anomaly_log v4.6.1 columns verified/added` and `Backfilled N legacy TEXT severity values to numeric IntEnum` (if any legacy rows existed).
2. **Trigger Energy crosscheck:** if Envoy reports divergence > 15%, expect a new `anomaly_log` row with `coordinator='energy'`, `type='energy.crosscheck_divergence'`, `event_class='point_in_time'`, `severity=1`.
3. **Trigger Bayesian anomaly:** wait for a real bayesian anomaly transition (rising edge). Expect a new row with `coordinator='bayesian'`, `type='bayesian.prediction_anomaly'`, `room_id=<room>`.
4. **Verify cleanup registration:** check that `cleanup_anomaly_log` appears in both `_cleanup_ops` and `_cleanup_ops_d` lists (Bug Class #27 prevention).
5. **Verify % unit on D4/D5 sensors:** `sensor.ura_coordinator_manager_oji_udezue_next_room_accuracy` renders state as `22.2%` not bare `22.2`.

## What's NOT in this cycle

- **10 other anomaly touchpoints** — not migrated. Stay in their current shape until needed.
- **Removal of `store_anomaly()` wrapper** — kept through v4.6.2; removed in v4.6.3+ once all legacy callers migrate naturally.
- **`store_anomaly_event_dispatched` signal** — no signal coupling on the write path (kept simple).
- **Behavioral integration tests** — source-grep tests verify static contracts. Behavioral tests with a mock DB are recommended for v4.6.2.
- **Bug Class #19 audit** — flagged as pre-existing debt across EnergyCoordinator's 7+ untracked `async_create_task` sites; not in scope.

## Deploy notes

- 6 files modified (database.py, coordinator_diagnostics.py, energy.py, binary_sensor.py, __init__.py, sensor.py)
- 1 file added (anomaly_event.py)
- 6 new test files
- HACS download required
- HA restart required
- Two migrations run on first boot: column adds (idempotent) + severity backfill (idempotent)

## Documents

- `docs/planning/PLANNING_v4.6.1_anomaly_reconciliation_then_v4.6.2_routine_awareness.md` — locked plan with calibration decisions and D6 control-surface lock (Select entity, not config_flow option)
- `docs/planning/ANOMALY_RECONCILIATION_SURVEY.md` — 12-touchpoint inventory (700 lines)

## Next

- **v4.6.2 — Routine Awareness features (D3 + D4 + D5 + D6 bundled).** B6 `away_typical` display + B7 JS-divergence regime detector + per-person/house `routine_status` sensors + acknowledge button + Select-entity notification control (silent / weekly_digest / event modes). D6 ships in `silent` mode by default — user opts in when ready.
- D7 enhancement: regime detector consumes v4.6.0 accuracy data as a complementary regime-shift signal.
- Backlog: full migration of remaining 10 anomaly touchpoints (opportunistic).
