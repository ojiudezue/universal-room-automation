# v4.6.6 — AnomalySeverity Vocabulary Refactor (Tier 2-DB)

**Date:** 2026-05-16 CDT
**Tier:** Tier 2-DB (changes payload shape of persisted `anomaly_log.severity` column + migrates ≥3 emit sites + one-shot DB row remap)
**Predecessor:** v4.6.5.3 (polish bundle)

## Why

`coordinator_diagnostics.AnomalySeverity` (StrEnum) classifies anomalies into 4 z-score bands: NOMINAL (< 2.0), ADVISORY (2.0–3.0), ALERT (3.0–4.0), CRITICAL (> 4.0). Every coordinator emit site collapsed those 4 buckets into a 2-bucket persisted `AnomalyEvent.AnomalySeverity` IntEnum using the idiom:

```python
severity=_NewSev.CRITICAL if anomaly.severity.value == "critical" else _NewSev.WARNING
```

Consequence: ADVISORY (z 2-3) and ALERT (z 3-4) both persisted as `severity = 1` (WARNING). Severity-grouped analytics, `URARecentAnomaliesSensor.by_severity`, and notification thresholds all saw them as the same bucket. Reviewers A-M2 and B-M1 flagged this independently during v4.6.5 Tier 2-DB review.

## Deliverables

### D0 (already on branch from v4.6.5.x prep cycle): enum + reader updates

- `AnomalySeverity` IntEnum expanded from 3 to 5 members: `INFO=0, WARNING=1, ADVISORY=2, ALERT=3, CRITICAL=4`. **CRITICAL's integer value moved from 2 to 4.** Sort order preserved (higher = more severe).
- `sensor.py::_SEVERITY_TO_ROUTINE_STATE` extended to cover the new integer keys 2/3 (in addition to existing 0/1/4).
- 13 D0 tests in `test_v466_severity_refactor.py` (enum shape, DB round-trip via `real_schema_db`, by_severity aggregation, DAO coupling).
- 3 pre-existing tests updated for CRITICAL=4: `test_v461_severity_unification.py`, `test_v461_anomaly_event_dataclass.py`, `test_v463_anomaly_migration.py`.

### D1: coordinator emit-site migration

- New helper `map_diag_severity()` in `anomaly_event.py` — 1:1 mapping `{nominal→INFO, advisory→ADVISORY, alert→ALERT, critical→CRITICAL}`. Unknown classifier buckets fall back to WARNING **and log a WARNING** (v4.6.6 review B-M1) so future classifier vocabulary drift is surfaced rather than silently swallowed.
- 4 classifier-driven emit sites migrated from the 2-way ternary to `severity=map_diag_severity(anomaly.severity)`:
  - `presence.py` — `_count_transition` (transition_count_daily emit)
  - `hvac.py` — `_record_anomaly_observations` (override_frequency emit)
  - `security.py` — `_handle_entry_intent` (alert_trigger_frequency emit)
  - `music_following.py` — `_persist_mf_anomaly` (transfer_success_rate + cooldown_frequency emits)
- `safety.py` retains constant `_NewSev.WARNING` for `active_hazard_count` — intentionally not migrated (binary hazard, no z-score classifier input). Comment added.

### D2: one-shot DB row remap (gated via PRAGMA user_version=466)

Historic CRITICAL rows persisted before v4.6.6 store `severity = '2'`. Post-v4.6.6 the value 2 means ADVISORY. Without a remap, every historic CRITICAL row would silently read back as ADVISORY in sensors, analytics, and the StrEnum-keyed UI.

```sql
UPDATE anomaly_log SET severity = '4' WHERE severity = '2'
```

**Critical implementation detail (v4.6.6 review A-C1):** the migration is **gated via `PRAGMA user_version`**. Pre-v4.6.6 DBs start at user_version=0; the migration runs once and sets user_version=466. Subsequent restarts find user_version=466 and skip the UPDATE entirely. Without this gate, the second restart would rewrite legitimate post-v4.6.6 ADVISORY rows (which land at severity='2' via `map_diag_severity('advisory')`) as CRITICAL — a recurring data-corruption bug. Behavioral test exercises the gate logic explicitly.

### A-H1: legacy TEXT backfill alignment

`v4.6.1` backfill at `database.py` mapped `'critical' → '2'`. Updated to `'critical' → '4'` so any stale-DB import surfacing TEXT 'critical' rows AFTER the one-shot D2 remap window doesn't read back as ADVISORY. (The backfill itself runs idempotently every startup via its own WHERE clause on the legacy TEXT values, so no PRAGMA gate needed.)

### B-B1: RoutineEventMinSeverityNumber max bumped 2 → 4

User-facing Number entity that sets the notification severity floor was capped at 2. Pre-v4.6.6 value 2 = CRITICAL; post-v4.6.6 it means ADVISORY. A user who set the floor to "CRITICAL only" pre-v4.6.6 would silently begin receiving ADVISORY+ALERT+CRITICAL events (~5-10× notification volume increase).

Fix:
- `_attr_native_max_value = 4` (was 2), so CRITICAL is reachable on the new scale
- `__init__` runs a one-shot seed migration: if `entry.options["routine_event_min_severity"] == 2`, auto-promote to `4` via `async_update_entry`. Preserves original user intent.
- Docstring + `const.py` comment + helper text describe the full 5-bucket scale.

## Tier 2-DB ceremony

Three parallel reviews (A: data integrity, B: migration correctness, C: new surfaces + test fixture authority). All pre-deploy HIGH/CRITICAL findings applied:

| ID | Reviewer | Finding | Fix applied |
|---|---|---|---|
| **A-C1** | A | D2 non-idempotent across restarts | PRAGMA user_version=466 gate |
| **A-C2 / B-B1** | A, B (convergent) | Number max_value=2 silently broken | Bump to 4 + seed migration |
| **A-H1** | A | v4.6.1 backfill 'critical' → '2' stale | Update to → '4' |
| **B-M1** | B | `map_diag_severity` fallback silent | Log WARNING on unknown bucket |
| **C-H2** | C | D2 test was self-validating | Test now exercises PRAGMA gate logic + injects post-deploy ADVISORY row to prove gate works |
| **C-H1** | C | D1/D2 work uncommitted | Committed in same cycle |

C-M1/M2/M3/M4 (tests can miss flipped-operand variants, missing AST-walked forward-compat meta-test, D2 idempotency comment language, ADVISORY/ALERT historical data-loss acknowledgement) filed for future polish — not blocking.

## Files changed

- `custom_components/universal_room_automation/domain_coordinators/anomaly_event.py` — `map_diag_severity` helper + WARNING-on-fallback log
- `custom_components/universal_room_automation/domain_coordinators/hvac.py` — emit site migrated
- `custom_components/universal_room_automation/domain_coordinators/security.py` — emit site migrated
- `custom_components/universal_room_automation/domain_coordinators/music_following.py` — emit site migrated
- `custom_components/universal_room_automation/domain_coordinators/presence.py` — emit site migrated
- `custom_components/universal_room_automation/domain_coordinators/safety.py` — comment added (no code change — intentional constant WARNING)
- `custom_components/universal_room_automation/database.py` — D2 gated migration + A-H1 backfill alignment
- `custom_components/universal_room_automation/number.py` — `RoutineEventMinSeverityNumber` max=4 + seed migration
- `custom_components/universal_room_automation/const.py` — comment updated for 5-bucket scale
- `quality/tests/test_v466_severity_refactor.py` — 22 tests (13 D0 + 4 D1/D2 + 5 review-fix coverage)
- `docs/readmes/README_v4.6.6.md` — new

## Test count

- v4.6.5.3: 3134 passing
- **v4.6.6: 3156 passing** (+22 new tests, 0 regressions)
- Pre-existing 56 failures + 14 errors unchanged

## Live validation plan (Review D — Tier 2-DB requirement)

1. **Post-restart log check:** look for `v4.6.6 D2 severity remap: rewrote N historic CRITICAL rows from '2' to '4'` in `home-assistant.log`. On a DB with no historic CRITICAL rows, instead see `v4.6.6 D2 severity remap: no historic CRITICAL rows to rewrite`.
2. **Idempotency live check:** second restart must log `v4.6.6 D2 severity remap: user_version=466 ≥ 466, skipping` at DEBUG level — proves the gate works in production.
3. **`sensor.ura_coordinator_manager_recent_anomalies.by_severity` post-deploy distribution:** within 1 hour of activity, keys `"2"` (ADVISORY) and/or `"3"` (ALERT) MUST appear if any z-scores in the 2.0–4.0 band occurred. If only `"1"` and `"4"` appear, an emit site was missed.
4. **Live SQL spot-check (1 hour post-deploy):** `SELECT severity, COUNT(*) FROM anomaly_log WHERE timestamp >= datetime('now', '-1 hour') GROUP BY severity;` — expect rows under 1, 2, 3, and/or 4 (proves the new vocabulary is landing).
5. **Number entity check:** `number.ura_coordinator_manager_routine_event_min_severity` should show max=4 in the HA UI. If the entity had a stored value of 2 pre-deploy, it should now read 4 (auto-promoted) and `_LOGGER` should NOT contain any seed-migration errors.

## What this is NOT

- Not a deletion of the legacy 2-bucket meaning — INFO/WARNING positions and values are preserved (only CRITICAL's value moved, and ADVISORY+ALERT are new).
- Not an attempt to recover historical ADVISORY/ALERT data — the v4.6.1 backfill already collapsed those TEXT values to WARNING (value 1), and there's no signal to recover. ADVISORY/ALERT will only appear in rows written by v4.6.6+ emit sites going forward.
- Not a frontend / Lovelace card change — the existing card consumes integers and renders them through the unchanged enum. Verify your dashboard handles severity keys "2" and "3" if you have custom severity badges; otherwise no UX change.

## What's next

- Soak v4.6.6 for ~24h. Check the by_severity distribution. If only WARNING and CRITICAL appear, file as v4.6.6.1 audit (an emit site might still be using the legacy collapse pattern that the source-grep test missed — extend to AST-walk forward-compat).
- **v4.6.7+:** `anomaly_log` NOT NULL relaxation cycle queued (~100 prod + 80 test LoC, safe thanks to v4.6.3 smoke infra). Independent of this cycle.
