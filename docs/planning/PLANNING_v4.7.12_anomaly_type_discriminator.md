# PLANNING v4.7.12 — AnomalyType Discriminator

**Status:** Plan ready for build
**Tier:** Tier 2-DB (three parallel staff-engineer reviews, different framings)
**Phase:** Phase B (sequenced AFTER Phase A — v4.7.10 Gitea + v4.7.9 Hygiene + v4.7.11 Egress are live as of 2026-05-30)
**Predecessor:** v4.7.11 (Egress Window HVAC Pause)
**Filed:** 2026-05-30
**Recall:** "Plan v4.7.12 anomaly type discriminator" / "Resume v4.7.12"

---

## 1. Goal + Why

Formalize the existing `event_class` discriminator on `anomaly_log` into a typed `AnomalyType` surface so a future cycle (v4.7.13+) can land `regime_shift`-aware consumer logic without re-touching every emit site.

**Why Phase B now:** v4.7.11 shipped the `egress_state` table migration. Sequencing the AnomalyType cycle AFTER that migration removes any same-cycle DB schema collision risk. v4.7.10 Gitea + v4.7.9 Hygiene closed cleanly, so develop is unobstructed.

**The shape that actually exists today (verified at planning time — `database.py:1191`, `anomaly_event.py:91-94`):**

- The DB column is already named `event_class TEXT DEFAULT 'point_in_time'` (added v4.6.1 D0).
- Module-level string constants `EVENT_CLASS_POINT_IN_TIME` / `EVENT_CLASS_REGIME_SHIFT` / `EVENT_CLASS_HAZARD` / `EVENT_CLASS_TRANSITION_INVALID` already exist in `domain_coordinators/anomaly_event.py`.
- The `AnomalyEvent` dataclass field `event_class: str` accepts any string — no validation.
- 13 emit sites pass `event_class=` explicitly. THREE drift sites still pass raw string literals instead of the constants (verified via grep — see §3 audit).

**So the user-described "column rename" is in fact already partially done.** This cycle's REAL job is:

1. **Promote the discriminator from `str` to a typed `AnomalyType` `StrEnum`** so the type system enforces the closed value set instead of relying on grep + reviewer vigilance.
2. **Fix the three string-literal drift sites** so all callers use the typed enum.
3. **Defensively validate at the DAO boundary** (`save_anomaly_event`) so any future caller passing an unknown value gets caught at write time, not at read time when a `regime_shift` consumer fails to match.
4. **Expose `AnomalyType` at the module level** as the canonical import target for v4.7.13+ consumers.
5. **Rename the column from `event_class` to `anomaly_type`** to align persistence with the new dataclass field. This is the canonical-naming cleanup the user asked for in the cycle brief.

**Explicit non-scope:** no emitter is migrated FROM `point_in_time` TO `regime_shift` in this cycle. The taxonomy `regime_detector.py:560` already uses `regime_shift` — that one site stays. v4.7.13+ chooses which other sites become `regime_shift` based on downstream consumer requirements that don't yet exist.

**Why Tier 2-DB:** triggers (per `CLAUDE.md`) → touches `database.py` DAO definitions (column rename in CREATE TABLE + migration); changes the payload shape of a dispatched/persisted record (the `event_class` field name changes); sets up infrastructure for a planned migration in a later cycle (v4.7.13 regime-shift consumers). Three of the five trigger criteria fire.

---

## 2. Tier Classification

Tier 2-DB. Three parallel reviewers, different framings, locked at planning (see §10).

| Tier 2-DB trigger | Hit? |
|---|---|
| Touches `database.py` DAO definitions | YES — CREATE TABLE + ALTER TABLE migration |
| Migrates ≥3 callers to a new DAO | YES — 13 emit sites updated (typed enum + 3 drift fixes) |
| Changes dispatched-payload shape | YES — `AnomalyEvent.event_class: str` → `AnomalyEvent.anomaly_type: AnomalyType` (field rename + type change) |
| Adds behavioral test infra against real schemas | YES — round-trip test through `real_schema_db` fixture |
| Followed within 1-2 versions by a planned schema migration | YES — v4.7.13+ regime-shift consumers depend on this infra |

All five triggers fire.

---

## 3. Discovery — Read Before Build

### 3.1 Files to read

| File | Lines | Why |
|---|---|---|
| `custom_components/universal_room_automation/database.py` | 676-702 | `anomaly_log` CREATE TABLE — current schema. Column rename touches here for FRESH installs. |
| `custom_components/universal_room_automation/database.py` | 1184-1206 | v4.6.1 D0 ALTER TABLE migration that added `event_class TEXT DEFAULT 'point_in_time'`. Extension point for v4.7.12 column rename via additive ADD COLUMN + backfill (NOT `ALTER COLUMN RENAME` — see §6.1). |
| `custom_components/universal_room_automation/database.py` | 4585-4688 | `save_anomaly_event` DAO — INSERT path. Reads `event.event_class` (line 4669) and writes to `event_class` column (line 4652). Both references must move to `anomaly_type` atomically. Also: error-log line 4684 reads `event_class` via `getattr`. |
| `custom_components/universal_room_automation/database.py` | 4013-4058 | `cleanup_anomaly_log` — uses retention windows. Verify no reference to `event_class` (or if there is, update). |
| `custom_components/universal_room_automation/domain_coordinators/anomaly_event.py` | 1-228 | Whole file. Defines `EVENT_CLASS_*` constants, `AnomalyEvent` dataclass, `build_context_json`. Primary surface for the new `AnomalyType` enum. |
| `custom_components/universal_room_automation/domain_coordinators/coordinator_diagnostics.py` | 113-129 | `AnomalyRecord` dataclass — diagnostics-local concept, NOT the DB-persisted shape. Confirm the new `AnomalyType` enum does NOT collide with `AnomalyRecord` semantically (it doesn't; AnomalyRecord is the diagnostics-classifier output, AnomalyType is the persistence discriminator). |
| `custom_components/universal_room_automation/domain_coordinators/coordinator_diagnostics.py` | 530-565, 980-1000 | Two emit sites — one passes `EVENT_CLASS_POINT_IN_TIME`, one routes through `store_event(AnomalyEvent(...))`. |
| `custom_components/universal_room_automation/domain_coordinators/regime_detector.py` | 545-580 | Sole `regime_shift` emitter today. Currently passes the raw string `"regime_shift"` at L560 — drift fix target. |
| `custom_components/universal_room_automation/domain_coordinators/energy.py` | 1572-1595 | Drift fix target — `event_class="point_in_time"` raw string at L1582. |
| `custom_components/universal_room_automation/binary_sensor.py` | 1885-1905 | Drift fix target — `event_class="point_in_time"` raw string at L1892. |
| `custom_components/universal_room_automation/__init__.py` | 2150-2200 | Already uses `EVENT_CLASS_POINT_IN_TIME` constant. Field-rename touchpoint only. |
| `custom_components/universal_room_automation/transitions.py` | 395-430 | Already uses `EVENT_CLASS_TRANSITION_INVALID` constant. Field-rename touchpoint only. |
| `custom_components/universal_room_automation/domain_coordinators/safety.py` | 1820-1860 | Already uses `EVENT_CLASS_HAZARD` constant. Field-rename touchpoint only. |
| `custom_components/universal_room_automation/domain_coordinators/notification_manager.py` | 920-970 | Already uses `EVENT_CLASS_POINT_IN_TIME` constant. Field-rename touchpoint only. |
| `custom_components/universal_room_automation/domain_coordinators/presence.py` | 2215-2240 | Already uses `EVENT_CLASS_POINT_IN_TIME` constant. Field-rename touchpoint only. |
| `custom_components/universal_room_automation/domain_coordinators/security.py` | 775-800 | Already uses `EVENT_CLASS_POINT_IN_TIME` constant. Field-rename touchpoint only. |
| `custom_components/universal_room_automation/domain_coordinators/music_following.py` | 335-355 | Already uses `EVENT_CLASS_POINT_IN_TIME` constant. Field-rename touchpoint only. |
| `custom_components/universal_room_automation/domain_coordinators/hvac.py` | 1690-1720 | Already uses `EVENT_CLASS_POINT_IN_TIME` constant. Field-rename touchpoint only. |
| `custom_components/universal_room_automation/domain_coordinators/energy.py` | 3270-3305 | Already uses `EVENT_CLASS_POINT_IN_TIME` constant. Field-rename touchpoint only. |
| `quality/tests/conftest_db.py` | 75-130 | `_extract_alter_table_statements` — extracts schema from production source (Bug Class #44 lesson). Verify the f-string tuple-list parser still finds the new `anomaly_type` column tuple if we keep that pattern. |
| `quality/tests/test_v463_behavioral_dao.py` | 100-700 | Behavioral DAO tests for `save_anomaly_event`. ALL `event_class=` references must rename to `anomaly_type=`. |
| `quality/tests/test_v463_anomaly_migration.py` | 130-1545 | Tier 2-DB migration tests. `event_class` referenced in 9 assertions + 3 INSERT statements + 1 column-list test. Bulk rename + add NEW v4.7.12 tests. |
| `quality/tests/test_v462_d4_regime_detector.py` | 200-210 | `test_event_class_is_regime_shift` — rename + assert against `AnomalyType.regime_shift`. |
| `quality/tests/test_v461_anomaly_event_dataclass.py` | 80-130 | Dataclass field-set test. Add `anomaly_type` to the required-fields tuple at L85. |
| `docs/QUALITY_CONTEXT.md` | Bug Classes #22, #38, #44, #45, #46 | #22 enum mismatch (directly applicable — the StrEnum surface), #44 test-infra schema authority, #46 lazy derivation lessons. |

### 3.2 Emit-site audit (verified via `grep -n` at planning time)

13 emit sites of `AnomalyEvent(...)` discovered:

| File:line | Current `event_class=` value | Drift? | Cycle action |
|---|---|---|---|
| `transitions.py:421` | `EVENT_CLASS_TRANSITION_INVALID` (constant) | No | Rename kwarg to `anomaly_type=`; rebind RHS to `AnomalyType.transition_invalid` |
| `binary_sensor.py:1892` | `"point_in_time"` (RAW STRING) | YES | Fix to `AnomalyType.point_in_time` |
| `__init__.py:2184` | `EVENT_CLASS_POINT_IN_TIME` (constant) | No | Rename kwarg + rebind RHS |
| `energy.py:1582` | `"point_in_time"` (RAW STRING) | YES | Fix to `AnomalyType.point_in_time` |
| `energy.py:3297` | `EVENT_CLASS_POINT_IN_TIME` (constant) | No | Rename kwarg + rebind RHS |
| `coordinator_diagnostics.py:555` | `EVENT_CLASS_POINT_IN_TIME` (constant) | No | Rename kwarg + rebind RHS |
| `presence.py:2236` | `EVENT_CLASS_POINT_IN_TIME` (constant) | No | Rename kwarg + rebind RHS |
| `security.py:794` | `EVENT_CLASS_POINT_IN_TIME` (constant) | No | Rename kwarg + rebind RHS |
| `notification_manager.py:960` | `EVENT_CLASS_POINT_IN_TIME` (constant) | No | Rename kwarg + rebind RHS |
| `music_following.py:352` | `EVENT_CLASS_POINT_IN_TIME` (constant) | No | Rename kwarg + rebind RHS |
| `hvac.py:1716` | `EVENT_CLASS_POINT_IN_TIME` (constant) | No | Rename kwarg + rebind RHS |
| `safety.py:1855` | `EVENT_CLASS_HAZARD` (constant) | No | Rename kwarg + rebind RHS |
| `regime_detector.py:560` | `"regime_shift"` (RAW STRING) | YES | Fix to `AnomalyType.regime_shift` |

**Drift count:** 3 sites pass raw strings instead of the constants. v4.7.12 fixes all 3 as part of the rebind sweep — this is the proximate justification for replacing `str` with a typed enum.

---

## 4. Pre-Deploy Row-Rate Snapshot (Tier 2-DB requirement)

Per CLAUDE.md § Tier 2-DB: **"Pre-deploy snapshot of affected table row rates by `(coordinator, severity, type)` (or analogous shape for non-anomaly cycles)."**

For this cycle the analogous shape is `(coordinator_id, severity, event_class)`. Capture the snapshot during planning AND copy it into `docs/readmes/README_v4.7.12.md` so the post-deploy ±25% comparison has a baseline.

### 4.1 Snapshot procedure (builder runs this BEFORE deploy.sh)

```sql
-- Run via MCP ura-sqlite (verify --db-path is live Samba mount, not ~/.cache/ura/)
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
```

Also capture the 1-hour and 24-hour rates separately so the post-deploy comparison can normalize:

```sql
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

### 4.2 Snapshot acceptance criterion

The README must include a table of the form:

| coordinator_id | severity | anomaly_type (pre-deploy: event_class) | rows_1h | rows_24h | rows_7d |
|---|---|---|---|---|---|
| (filled by builder) | | | | | |

**Post-deploy ±25% delta check (Review D / Live Validation):** repeat the SAME query 1 hour AND 24 hours after deploy with the new column name (`anomaly_type`). If any `(coordinator_id, severity)` bucket's row rate has changed by more than ±25%, that's a HIGH finding (lost emits OR phantom emits).

---

## 5. Deliverables

### D1 — `AnomalyType` enum + DAO + migration

#### Files

- `custom_components/universal_room_automation/domain_coordinators/anomaly_event.py`
- `custom_components/universal_room_automation/database.py`

#### Spec

**1. Add `AnomalyType` StrEnum to `anomaly_event.py`** (next to `AnomalySeverity`, ~L40-86 region):

```python
from enum import StrEnum  # Python 3.11+, present in HA-core min version


class AnomalyType(StrEnum):
    """Discriminator for the anomaly_log.anomaly_type column (v4.7.12 D1).

    Replaces the loose `EVENT_CLASS_*` string constants. Same persisted
    string values — only the type at the dataclass / DAO boundary changes,
    so old TEXT rows still round-trip after the v4.7.12 column rename.

    Members:
        POINT_IN_TIME — single-instant anomaly emission (default / today's
            behavior). All 11 existing point_in_time emitters land here.
        REGIME_SHIFT — sustained-state change; downstream consumers (planned
            v4.7.13+) treat this differently from point-in-time events.
        HAZARD — safety-domain anomaly with notification routing.
        TRANSITION_INVALID — house-state transition rule violation.

    StrEnum means `AnomalyType.POINT_IN_TIME == "point_in_time"` is True,
    so legacy code paths that compare strings continue to work. Migration
    from raw strings to typed enums is mechanical at every emit site.

    DO NOT add new members in v4.7.12. v4.7.13+ owns the next member.
    """

    POINT_IN_TIME = "point_in_time"
    REGIME_SHIFT = "regime_shift"
    HAZARD = "hazard"
    TRANSITION_INVALID = "transition_invalid"
```

**2. Keep legacy `EVENT_CLASS_*` string constants AS ALIASES** to the StrEnum so anything not migrated in this cycle (or any plugin extension downstream) doesn't break:

```python
# v4.7.12: legacy aliases — point to AnomalyType members. Existing callers
# that import EVENT_CLASS_POINT_IN_TIME continue to work because StrEnum
# members are also strings. Slated for deletion in v5.0.
EVENT_CLASS_POINT_IN_TIME = AnomalyType.POINT_IN_TIME
EVENT_CLASS_REGIME_SHIFT = AnomalyType.REGIME_SHIFT
EVENT_CLASS_HAZARD = AnomalyType.HAZARD
EVENT_CLASS_TRANSITION_INVALID = AnomalyType.TRANSITION_INVALID
```

**3. Rename dataclass field** in the `AnomalyEvent` dataclass:

```python
@dataclass
class AnomalyEvent:
    ...
    anomaly_type: AnomalyType  # v4.7.12: was `event_class: str`
    """Discriminator for the anomaly_log row. v4.7.12 renamed from
    `event_class` to align with the database column. Type narrowed from
    str to AnomalyType (StrEnum) for type-safety. Legacy callers that
    pass a raw string still work because StrEnum accepts string literals
    that match a member value — but new code should use the enum."""
    ...
```

**Defensive coercion:** the `__post_init__` (or a small validator) accepts both `AnomalyType` members and bare string literals matching member `.value`s:

```python
def __post_init__(self) -> None:
    # v4.7.12 D1: defensive coercion. Accept legacy string emitters
    # transparently; raise on unknown values so future drift is caught
    # at write time rather than at downstream consumer time.
    if isinstance(self.anomaly_type, str) and not isinstance(self.anomaly_type, AnomalyType):
        try:
            self.anomaly_type = AnomalyType(self.anomaly_type)
        except ValueError as e:
            raise ValueError(
                f"AnomalyEvent.anomaly_type must be a member of AnomalyType "
                f"or one of {[t.value for t in AnomalyType]!r}; "
                f"got {self.anomaly_type!r}"
            ) from e
```

**4. DB schema rename — additive migration, NOT `ALTER COLUMN RENAME`.** SQLite versions older than 3.25 do not support `ALTER TABLE ... RENAME COLUMN`. HA's bundled `sqlite3` is ≥ 3.31 (verified — HA min Python 3.13 ships SQLite 3.40+ on macOS/Linux distros), so `RENAME COLUMN` is actually safe. BUT — to preserve the v4.6.7 rebuild-dance precedent and avoid an irrecoverable rename in a Tier 2-DB cycle, this cycle uses the **additive-then-deprecate** pattern:

   1. ADD a new column `anomaly_type TEXT DEFAULT 'point_in_time'`.
   2. Copy values: `UPDATE anomaly_log SET anomaly_type = event_class WHERE anomaly_type IS NULL OR anomaly_type = 'point_in_time'`.
   3. Gate the migration with a new `PRAGMA user_version=4712` sentinel so it does not re-run after success.
   4. Leave `event_class` column in place for one cycle for rollback safety; mark it deprecated in code comments. Drop in v5.0 alongside the legacy `EVENT_CLASS_*` constants.

The CREATE TABLE for fresh installs still creates BOTH columns (so the schema is consistent across upgrade vs fresh-install paths — Reviewer A's data-integrity check).

```python
# database.py — add to the FRESH install CREATE TABLE at L676-692:
"""CREATE TABLE IF NOT EXISTS anomaly_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    coordinator_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    observed_value REAL,
    expected_mean REAL,
    expected_std REAL,
    z_score REAL,
    severity TEXT NOT NULL,
    sample_size INTEGER,
    house_state TEXT,
    context_json TEXT,
    resolved BOOLEAN NOT NULL DEFAULT 0,
    resolution_notes TEXT,
    -- v4.7.12: anomaly_type replaces event_class as the canonical
    -- discriminator. event_class kept as deprecated alias for one
    -- cycle so rollback to v4.7.11 can still read pre-rename rows.
    -- Both columns carry the same value during the transition window.
    -- v5.0 drops event_class.
    anomaly_type TEXT DEFAULT 'point_in_time'
)"""
```

The v4.6.1 ALTER TABLE tuple-list (L1190-1197) gets `anomaly_type` added to it. The existing `event_class` tuple stays (newly-fresh-installs will get both columns from the CREATE TABLE; legacy DBs that already have `event_class` get the new `anomaly_type` column added by ALTER TABLE).

**5. Backfill migration block** added after the existing v4.6.7 NOT-NULL relaxation block (~L1303):

```python
# v4.7.12 D1: anomaly_type discriminator. Backfill new anomaly_type
# column from existing event_class values. Gated on PRAGMA
# user_version=4712 so the UPDATE does not re-run (would otherwise
# clobber any v4.7.13+ emits that set anomaly_type independently of
# event_class — though no such caller exists yet, the gate keeps the
# migration idempotent for the rollback-and-reapply case).
try:
    cursor = await db.execute("PRAGMA user_version")
    row = await cursor.fetchone()
    current_user_version = row[0] if row else 0
    if current_user_version < 4712:
        cursor = await db.execute(
            """UPDATE anomaly_log
               SET anomaly_type = event_class
               WHERE anomaly_type IS NULL OR anomaly_type = 'point_in_time'"""
        )
        backfilled = cursor.rowcount
        await db.execute("PRAGMA user_version = 4712")
        await db.commit()
        _LOGGER.info(
            "v4.7.12 D1 anomaly_type backfill: copied event_class -> "
            "anomaly_type on %d rows. user_version=4712.",
            backfilled,
        )
    else:
        _LOGGER.debug(
            "v4.7.12 D1 anomaly_type backfill: user_version=%d >= 4712, "
            "skipping (already migrated).",
            current_user_version,
        )
except Exception as e:
    _LOGGER.warning("v4.7.12 D1 anomaly_type backfill failed: %s", e)
```

**6. DAO update — `save_anomaly_event`** at `database.py:4585-4688`:

   - INSERT statement: write to BOTH `anomaly_type` AND `event_class` columns during the transition window. The same value goes into both so any consumer reading from either column sees consistent data.
   - Resolution order: prefer `event.anomaly_type`; fall back to `event.event_class` (legacy attr) if the caller hasn't migrated. Both end up as the same value because `__post_init__` populates one from the other.
   - Error log at L4684 reads `event_class` via `getattr` — change to `getattr(event, "anomaly_type", getattr(event, "event_class", "?"))`.

#### Acceptance Criteria

- **Verify:** `AnomalyType` StrEnum exists in `anomaly_event.py` with exactly 4 members (POINT_IN_TIME, REGIME_SHIFT, HAZARD, TRANSITION_INVALID) — no new members in this cycle.
- **Verify:** Legacy `EVENT_CLASS_*` constants resolve to `AnomalyType` members (`EVENT_CLASS_POINT_IN_TIME is AnomalyType.POINT_IN_TIME` is True).
- **Verify:** `AnomalyEvent.__post_init__` raises `ValueError` when given an unknown anomaly_type string.
- **Verify:** Fresh-install CREATE TABLE produces both `event_class` AND `anomaly_type` columns.
- **Verify:** Upgrade-install ALTER TABLE adds `anomaly_type` to legacy DBs that only had `event_class`.
- **Verify:** Backfill UPDATE copies `event_class → anomaly_type` exactly once (PRAGMA user_version=4712 gates re-run).
- **Verify:** `save_anomaly_event` writes the same value to BOTH columns (dual-write window).
- **Sensor:** `sensor.ura_diagnostics_coordinator_anomaly_log_summary` (if exists; verify in graphify) shows non-zero counts under each `anomaly_type` bucket consistent with the pre-deploy snapshot.
- **Test:** `test_v4712_anomaly_type_enum_members` (asserts exactly 4 members, asserts string equality).
- **Test:** `test_v4712_anomaly_event_post_init_accepts_string` (legacy raw-string caller still works).
- **Test:** `test_v4712_anomaly_event_post_init_rejects_unknown` (ValueError on unknown string).
- **Test:** `test_v4712_legacy_event_class_constants_alias_to_enum` (`EVENT_CLASS_POINT_IN_TIME is AnomalyType.POINT_IN_TIME`).
- **Test:** `test_v4712_fresh_schema_has_both_columns` (uses `real_schema_db` fixture; PRAGMA table_info shows both `event_class` and `anomaly_type`).
- **Test:** `test_v4712_migration_backfill_copies_event_class_to_anomaly_type` (insert legacy row → run migration → both columns equal).
- **Test:** `test_v4712_migration_idempotent_under_user_version_gate` (run migration twice → second run is no-op; user_version stays at 4712).
- **Test:** `test_v4712_save_anomaly_event_dual_writes_both_columns` (round-trip via `save_anomaly_event` → SELECT shows same value in both columns).
- **Live:** Within 1 hour of restart, at least one `anomaly_log` row has `anomaly_type IS NOT NULL` and `anomaly_type = event_class` for the same row.
- **Live:** PRAGMA `user_version` = 4712 (verified once post-restart via MCP ura-sqlite).
- **Live:** Row-rate ±25% check (§4) — every `(coordinator_id, severity)` bucket within ±25% of pre-deploy 24h rate.

---

### D2 — All emit sites explicitly pass `anomaly_type=AnomalyType.POINT_IN_TIME`

#### Files

- `custom_components/universal_room_automation/binary_sensor.py` (drift fix — raw string)
- `custom_components/universal_room_automation/domain_coordinators/energy.py` (drift fix — raw string at L1582 + rename rebind at L3297)
- `custom_components/universal_room_automation/domain_coordinators/regime_detector.py` (drift fix — raw string `"regime_shift"`)
- `custom_components/universal_room_automation/__init__.py`
- `custom_components/universal_room_automation/transitions.py`
- `custom_components/universal_room_automation/domain_coordinators/coordinator_diagnostics.py`
- `custom_components/universal_room_automation/domain_coordinators/presence.py`
- `custom_components/universal_room_automation/domain_coordinators/security.py`
- `custom_components/universal_room_automation/domain_coordinators/notification_manager.py`
- `custom_components/universal_room_automation/domain_coordinators/music_following.py`
- `custom_components/universal_room_automation/domain_coordinators/hvac.py`
- `custom_components/universal_room_automation/domain_coordinators/safety.py`

#### Spec

For each of the 13 sites in §3.2:

1. Rename the kwarg `event_class=` → `anomaly_type=`.
2. Rebind the RHS:
   - Constant call sites (`EVENT_CLASS_POINT_IN_TIME` etc.): change to `AnomalyType.POINT_IN_TIME`. The legacy constant still works (it IS the enum member) but new code should use the canonical name.
   - Raw string call sites (3 drift sites): change to the typed `AnomalyType.*` member.
3. **Defensive — never rely on the default.** The cycle brief says "never rely on the default." The `AnomalyEvent` dataclass field MUST therefore lose its default value — or keep a default but require all current callers to pass explicitly. Current dataclass spec shows `event_class: str` is required (no default — verified at `anomaly_event.py:132`). KEEP it required after rename. Builder verifies during code-fix that no caller is dropping the kwarg under the rename.

#### Acceptance Criteria

- **Verify:** Every `AnomalyEvent(...)` invocation in `custom_components/universal_room_automation/` passes `anomaly_type=` explicitly (zero `event_class=` references and zero `AnomalyEvent` calls without an `anomaly_type` kwarg).
- **Verify:** Every `anomaly_type=` RHS is either `AnomalyType.*` directly or the legacy `EVENT_CLASS_*` alias (which dereferences to an `AnomalyType` member).
- **Verify:** Zero raw string literals `"point_in_time"` / `"regime_shift"` / `"hazard"` / `"transition_invalid"` appear as `anomaly_type=` RHS values across the production code.
- **Verify:** `regime_detector.py:560` is the SOLE site that emits `AnomalyType.REGIME_SHIFT` post-cycle.
- **Test:** `test_v4712_all_anomaly_event_callers_use_anomaly_type_kwarg` (AST scan of `custom_components/`; asserts every `Call(func=Name("AnomalyEvent"))` has a keyword named `anomaly_type` and none has a keyword named `event_class`).
- **Test:** `test_v4712_no_raw_string_anomaly_type_in_production` (AST scan; asserts every `anomaly_type` keyword value is a `Name` (constant ref) or `Attribute` of `AnomalyType`, never a `Constant(value=str)`).
- **Test:** `test_v4712_regime_shift_sole_emitter_unchanged` (asserts `regime_detector.py` is the only file in `custom_components/` that emits `AnomalyType.REGIME_SHIFT`; protects v4.7.13+ scoping).
- **Live:** Within 1 hour of restart, query `SELECT DISTINCT anomaly_type FROM anomaly_log WHERE timestamp >= datetime('now', '-1 hour')`. Result is a subset of `{'point_in_time', 'regime_shift', 'hazard', 'transition_invalid'}`.
- **Live:** Zero `home-assistant.log` warnings of shape `"AnomalyEvent.anomaly_type must be a member of AnomalyType ..."` (the `__post_init__` rejection path).

---

### D3 — `AnomalyType` exposed at module level for v4.7.13+ consumers

#### Files

- `custom_components/universal_room_automation/domain_coordinators/anomaly_event.py`
- `custom_components/universal_room_automation/domain_coordinators/__init__.py` (if it re-exports — verify)

#### Spec

Re-export `AnomalyType` from the public module surface so v4.7.13+ regime-shift consumers can import without reaching into the dataclass module:

```python
# anomaly_event.py top of module:
__all__ = [
    "AnomalySeverity",
    "AnomalyType",            # v4.7.12 D3
    "AnomalyEvent",
    "build_context_json",
    "map_diag_severity",
    # Legacy aliases — slated for removal in v5.0
    "EVENT_CLASS_POINT_IN_TIME",
    "EVENT_CLASS_REGIME_SHIFT",
    "EVENT_CLASS_HAZARD",
    "EVENT_CLASS_TRANSITION_INVALID",
]
```

If `domain_coordinators/__init__.py` re-exports anomaly symbols, verify `AnomalyType` is added to that re-export.

**Non-goal:** do NOT change the import paths used by existing callers. They keep importing from `domain_coordinators.anomaly_event`. The `__all__` is for IDE / wildcard-import / Sphinx hygiene.

#### Acceptance Criteria

- **Verify:** `from custom_components.universal_room_automation.domain_coordinators.anomaly_event import AnomalyType` works.
- **Verify:** `AnomalyType` appears in `__all__`.
- **Verify:** Legacy `EVENT_CLASS_*` aliases also appear in `__all__` (back-compat for any extension consumer).
- **Test:** `test_v4712_anomaly_type_in_module_all` (asserts `"AnomalyType" in anomaly_event.__all__`).
- **Test:** `test_v4712_anomaly_type_importable_from_public_path` (does the import and asserts it's a StrEnum subclass).
- **Live:** N/A — pure import-surface deliverable; D1 + D2 live checks cover the user-visible behavior.

---

### D4 — Tests: back-compat default behavior + explicit pass-through + value validation

#### Files

- `quality/tests/test_v4712_anomaly_type_discriminator.py` (new file — all v4.7.12 unit + behavioral tests live here)
- `quality/tests/test_v463_behavioral_dao.py` (rename `event_class=` → `anomaly_type=` everywhere)
- `quality/tests/test_v463_anomaly_migration.py` (rename + add ONE new test that asserts both columns are present in fresh schema)
- `quality/tests/test_v462_d4_regime_detector.py` (rename + assert against `AnomalyType.REGIME_SHIFT`)
- `quality/tests/test_v461_anomaly_event_dataclass.py` (rename + add `anomaly_type` to the required-fields tuple at L85)

#### Spec — minimum new test set

1. **Round-trip via real schema** — extract DDL from `database.py` via `conftest_db._extract_alter_table_statements` and `_create_table_statements`. Insert a row via `save_anomaly_event(AnomalyEvent(anomaly_type=AnomalyType.POINT_IN_TIME, ...))`. SELECT both `event_class` and `anomaly_type` from the row; assert both equal `"point_in_time"`.
2. **Schema extraction (Bug Class #44)** — assert tests load the column tuples from `database.py` source, NOT a hand-copied DDL. The `conftest_db._extract_alter_table_statements` parser at L75-130 already handles the f-string tuple-list pattern that v4.6.1 used; verify it still finds the new `anomaly_type` tuple AND the legacy `event_class` tuple after the cycle's ADD COLUMN entry is added.
3. **Migration idempotency** — apply the v4.7.12 backfill twice in the same test; assert the second invocation is a no-op (rowcount=0) and user_version stays at 4712.
4. **Migration recovery** — apply the v4.6.1 ALTER TABLE migration first, insert a row with `event_class='regime_shift'` and `anomaly_type IS NULL`, run v4.7.12 backfill, assert `anomaly_type = 'regime_shift'`.
5. **Caller rename round-trip** — for every emit site in §3.2, the corresponding behavioral test in `test_v463_anomaly_migration.py` is updated to read back both columns and assert equality.
6. **Drift-prevention AST test** — D2 acceptance criterion #2 is the AST scan. Captured here as a test.
7. **Default behavior** — instantiate `AnomalyEvent` without `anomaly_type=`; assert it raises `TypeError` (dataclass missing-required-field). This enforces the cycle brief's "never rely on the default."

#### Acceptance Criteria

- **Verify:** All renamed tests pass against the post-cycle schema.
- **Verify:** All NEW v4.7.12 tests pass.
- **Verify:** AST drift-prevention tests fail if a hypothetical regression re-introduces `event_class=` or a raw string `anomaly_type=`.
- **Test:** Full new-test list (filenames + functions):
  - `quality/tests/test_v4712_anomaly_type_discriminator.py::test_anomaly_type_enum_members`
  - `quality/tests/test_v4712_anomaly_type_discriminator.py::test_legacy_event_class_constants_alias_to_enum`
  - `quality/tests/test_v4712_anomaly_type_discriminator.py::test_anomaly_event_post_init_accepts_string`
  - `quality/tests/test_v4712_anomaly_type_discriminator.py::test_anomaly_event_post_init_rejects_unknown`
  - `quality/tests/test_v4712_anomaly_type_discriminator.py::test_anomaly_event_requires_anomaly_type_kwarg`
  - `quality/tests/test_v4712_anomaly_type_discriminator.py::test_anomaly_type_in_module_all`
  - `quality/tests/test_v4712_anomaly_type_discriminator.py::test_anomaly_type_importable_from_public_path`
  - `quality/tests/test_v4712_anomaly_type_discriminator.py::test_fresh_schema_has_both_columns`
  - `quality/tests/test_v4712_anomaly_type_discriminator.py::test_migration_backfill_copies_event_class_to_anomaly_type`
  - `quality/tests/test_v4712_anomaly_type_discriminator.py::test_migration_idempotent_under_user_version_gate`
  - `quality/tests/test_v4712_anomaly_type_discriminator.py::test_save_anomaly_event_dual_writes_both_columns`
  - `quality/tests/test_v4712_anomaly_type_discriminator.py::test_save_anomaly_event_resolution_prefers_anomaly_type_over_event_class`
  - `quality/tests/test_v4712_anomaly_type_discriminator.py::test_all_anomaly_event_callers_use_anomaly_type_kwarg`
  - `quality/tests/test_v4712_anomaly_type_discriminator.py::test_no_raw_string_anomaly_type_in_production`
  - `quality/tests/test_v4712_anomaly_type_discriminator.py::test_regime_shift_sole_emitter_unchanged`
  - `quality/tests/test_v4712_anomaly_type_discriminator.py::test_schema_extraction_finds_anomaly_type_alter_tuple`
- **Live:** N/A — tests are CI-only; live behavior is covered by D1/D2 Live lines.

---

### D5 — Pre/post row-rate snapshot in README

#### Files

- `docs/readmes/README_v4.7.12.md` (created before deploy; rate snapshot embedded)

#### Spec

The README MUST include:

1. **§ Pre-deploy snapshot.** Output of the queries in §4.1 — tables for 1h, 24h, 7d row counts grouped by `(coordinator_id, severity, event_class)`.
2. **§ Post-deploy comparison procedure.** Same queries with the new column name (`anomaly_type`) run at 1h and 24h post-restart. Embedded as runbook prose, not just SQL.
3. **§ Pass criterion.** Every `(coordinator_id, severity)` bucket within ±25% of the pre-deploy 24h rate. Any bucket outside that band is a HIGH finding and triggers Tier 2-DB rollback review.

#### Acceptance Criteria

- **Verify:** README has all three sections.
- **Verify:** Pre-deploy snapshot table is populated with REAL numbers (not placeholders).
- **Verify:** Post-deploy comparison query uses `anomaly_type` column.
- **Test:** None — documentation deliverable.
- **Live:** Post-deploy snapshot run + ±25% check completed; results appended to README at the bottom; if any bucket failed the check, an action item is filed against v4.7.13 with the relevant `(coordinator_id, severity)` tuple.

---

## 6. Constants Inventory

| Constant | Module | Type | Value | Status |
|---|---|---|---|---|
| `AnomalyType` | `domain_coordinators/anomaly_event.py` | `StrEnum` | 4 members | NEW |
| `AnomalyType.POINT_IN_TIME` | `domain_coordinators/anomaly_event.py` | `AnomalyType` | `"point_in_time"` | NEW |
| `AnomalyType.REGIME_SHIFT` | `domain_coordinators/anomaly_event.py` | `AnomalyType` | `"regime_shift"` | NEW |
| `AnomalyType.HAZARD` | `domain_coordinators/anomaly_event.py` | `AnomalyType` | `"hazard"` | NEW |
| `AnomalyType.TRANSITION_INVALID` | `domain_coordinators/anomaly_event.py` | `AnomalyType` | `"transition_invalid"` | NEW |
| `EVENT_CLASS_POINT_IN_TIME` | `domain_coordinators/anomaly_event.py` | `AnomalyType` (alias) | `AnomalyType.POINT_IN_TIME` | EXISTING — semantics narrowed |
| `EVENT_CLASS_REGIME_SHIFT` | `domain_coordinators/anomaly_event.py` | `AnomalyType` (alias) | `AnomalyType.REGIME_SHIFT` | EXISTING — semantics narrowed |
| `EVENT_CLASS_HAZARD` | `domain_coordinators/anomaly_event.py` | `AnomalyType` (alias) | `AnomalyType.HAZARD` | EXISTING — semantics narrowed |
| `EVENT_CLASS_TRANSITION_INVALID` | `domain_coordinators/anomaly_event.py` | `AnomalyType` (alias) | `AnomalyType.TRANSITION_INVALID` | EXISTING — semantics narrowed |

### 6.1 SQL Schema Changes

| Change | Type | Statement |
|---|---|---|
| New CREATE TABLE column (fresh installs) | additive | `anomaly_type TEXT DEFAULT 'point_in_time'` |
| New ALTER TABLE column (upgrade installs) | additive | `ALTER TABLE anomaly_log ADD COLUMN anomaly_type TEXT DEFAULT 'point_in_time'` |
| Backfill UPDATE | one-shot, gated | `UPDATE anomaly_log SET anomaly_type = event_class WHERE anomaly_type IS NULL OR anomaly_type = 'point_in_time'` |
| PRAGMA gate | sentinel | `PRAGMA user_version = 4712` |

**NOT done in this cycle:** column drop of `event_class`. Deferred to v5.0 alongside the legacy constant cleanup, to preserve rollback to v4.7.11 within a single cycle.

No new tables. No index changes (the existing `idx_anomaly_severity` / `idx_anomaly_scope` / `idx_anomaly_coordinator` cover the new column's query patterns; v4.7.13+ may add a `(anomaly_type, coordinator_id)` composite if real workload data justifies).

---

## 7. Bug Class Coverage

| Class | Surface | Mitigation |
|---|---|---|
| #7 (stale data source) | Test fixture vs production schema | `conftest_db._extract_alter_table_statements` parses production source; D4 test #2 verifies the parser finds the new tuple |
| #22 (enum mismatch) | `AnomalyType` StrEnum surface | StrEnum equality with string literals preserves back-compat; `__post_init__` validates unknown values |
| #38 (untracked dispatcher unsub) | N/A — no new dispatcher subscriptions | — |
| #42 (lambda + async_create_task) | N/A — no new scheduler callbacks | — |
| #44 (test-infra schema authority) | Test fixtures | All tests use `real_schema_db` fixture; AST scan of production sources for kwarg name; no hand-copied DDL |
| #45 (lambda closure over loop vars) | N/A | — |
| #46 (config-entry write inside setup) | N/A — no `async_update_entry` calls | — |
| v4.7.12 specific — rename-time field skew | DAO read path + sensor.py readers | Dual-column write during the transition window; D1 reads from `anomaly_type` with `event_class` fallback; old code paths and new code paths both see consistent data |
| v4.7.12 specific — migration re-run on rollback-then-reapply | Backfill UPDATE | PRAGMA user_version=4712 gate; idempotent UPDATE is a no-op on second run |
| v4.7.12 specific — caller passes None for `anomaly_type` | Dataclass `__post_init__` | TypeError raised by required-without-default field (D2 verify line); reviewed at code-fix time |

---

## 8. Parallel-Merge-Risk Discipline (Phase B)

Phase B is a single cycle (v4.7.12) with no parallel siblings. The Phase A merges (Gitea + Hygiene + Egress) are all on develop already as of 2026-05-30.

**Files touched that other in-flight cycles might also want:**

| File | v4.7.12 touch | Risk |
|---|---|---|
| `database.py` | New ALTER TABLE migration block; CREATE TABLE column addition; DAO INSERT update | LOW (single cycle; no other in-flight cycle plans to touch `anomaly_log` schema). Schema-sensitive — Reviewer A vetoes any speculative additions outside this cycle's scope. |
| `domain_coordinators/anomaly_event.py` | New enum + `__post_init__` + `__all__` | LOW (single source-of-truth file). |
| 13 emit-site files | Kwarg rename | LOW per file; HIGH-coupling cycle-wide. Builder uses scripted find-replace (verified by AST test #1), not manual edit. |

No git-merge conflicts expected.

---

## 9. Pre-Deploy Zero-Bugs Gates (5)

Standard 5-gate checklist (user-coined post-v4.7.4.3 incident, MANDATORY per CLAUDE.md). All five MUST pass before `./scripts/deploy.sh` is invoked.

| Gate | Command | Pass criterion |
|---|---|---|
| 1 — Conflict markers | `grep -rn '<<<<<<<\|=======\|>>>>>>>' custom_components/universal_room_automation/ quality/tests/` | Zero matches |
| 2 — Syntax (py_compile changed files) | `python3 -m py_compile custom_components/universal_room_automation/database.py custom_components/universal_room_automation/domain_coordinators/anomaly_event.py custom_components/universal_room_automation/binary_sensor.py custom_components/universal_room_automation/__init__.py custom_components/universal_room_automation/transitions.py custom_components/universal_room_automation/domain_coordinators/coordinator_diagnostics.py custom_components/universal_room_automation/domain_coordinators/energy.py custom_components/universal_room_automation/domain_coordinators/regime_detector.py custom_components/universal_room_automation/domain_coordinators/presence.py custom_components/universal_room_automation/domain_coordinators/security.py custom_components/universal_room_automation/domain_coordinators/notification_manager.py custom_components/universal_room_automation/domain_coordinators/music_following.py custom_components/universal_room_automation/domain_coordinators/hvac.py custom_components/universal_room_automation/domain_coordinators/safety.py` | Zero errors |
| 3 — Cycle test suite | `PYTHONPATH=quality python3 -m pytest quality/tests/test_v4712_*.py -v` | All tests pass |
| 4 — Anomaly regression tests | `PYTHONPATH=quality python3 -m pytest quality/tests/test_v461_*.py quality/tests/test_v462_*.py quality/tests/test_v463_*.py -v` | All tests pass (catches downstream behavioral / DAO regressions from the rename) |
| 5 — Suite baseline diff | `PYTHONPATH=quality python3 -m pytest quality/tests/ -v 2>&1 \| tail -50` against `pre-review-v4.7.12` tag | No regression in pass count |

---

## 10. Tier 2-DB Review Framings (locked at planning)

Three parallel reviewers, different framings. No reviewer sees another's report before submitting their own.

### Reviewer A — Data integrity + DB architecture preservation

**Focus:** Existing rows preserved, no schema regression, write queue unchanged, indexes still cover, existing readers unaffected, existing analytics queries return the same shape post-deploy.

**Checklist:**
- v4.6.1 D0 migration is NOT re-run; v4.7.12 backfill is gated on `PRAGMA user_version=4712`. Verify both gates compose (one runs once, the other runs once, neither re-runs in the same boot).
- Fresh-install CREATE TABLE produces a row layout identical to an upgrade-installed table after both migrations run. Field-by-field PRAGMA `table_info` comparison.
- The backfill UPDATE's WHERE clause (`anomaly_type IS NULL OR anomaly_type = 'point_in_time'`) does NOT clobber any pre-existing `anomaly_type` value that's NOT `'point_in_time'`. (Today, no pre-existing values exist because the column is new; the gate handles the rollback-then-reapply edge case where v4.7.13 emits land with `regime_shift` and v4.7.12 backfill re-runs.)
- Existing reader queries — anything that does `SELECT ... FROM anomaly_log` — still works. The column-list `SELECT *` consumers are most at risk; grep for any caller that relies on column ordinal index. Particular focus: `coordinator_diagnostics.py:986` (`row_id = await database.save_anomaly_event(event)` path), any sensor.py reader, any analytics SELECT.
- Indexes `idx_anomaly_severity` / `idx_anomaly_scope` / `idx_anomaly_coordinator` still cover the typical post-cycle filter combinations. The new `anomaly_type` column is unindexed; verify no critical query path requires an index on it (if so, add to D1 spec before code-fix; if not, defer to v4.7.13+).
- Write queue (DBManager `_queued_write` pattern) is unchanged. The DAO INSERT is still in `save_anomaly_event` and still goes through `async with self._db()`.
- The dual-write (both `event_class` and `anomaly_type` columns) is consistent — no path writes one without the other.

**Output:** CRITICAL / HIGH / MEDIUM / LOW findings with file:line refs and proposed fixes.

---

### Reviewer B — Migration correctness + signal chain integrity

**Focus:** Every migrated call site produces equivalent rows AND fires any downstream signals/dispatches AND no double-emit risk. End-to-end trace per migrated site. Field-by-field shape comparison vs the pre-migration emit.

**Checklist:**
- For each of the 13 emit sites in §3.2, trace: `AnomalyEvent(anomaly_type=...)` → `save_anomaly_event` → SELECT readback. Confirm the row has the same shape pre-cycle vs post-cycle.
- `regime_detector.py:560` is the SOLE `REGIME_SHIFT` emitter; v4.7.13+ depends on this. If any other code path accidentally emits `REGIME_SHIFT` (e.g., a fallback in `save_anomaly_event` or a deserializer that round-trips through `AnomalyEvent.__post_init__` and picks up a typo), Reviewer B catches it.
- `save_anomaly_event` error log path (L4684): the `getattr` fallback returns `"?"` if neither `anomaly_type` nor `event_class` is present. Verify no caller relies on the error-log line for sentinel detection.
- Signal chain — `save_anomaly_event` returns a `row_id` that downstream code (e.g., `regime_detector.py:567`) uses for `SIGNAL_REGIME_SHIFT_DETECTED` dispatch payload. Verify the rename does NOT skip the row_id return path on any call site.
- `coordinator_diagnostics.py:986` — `row_id = await database.save_anomaly_event(event)` — verify the event passed has `anomaly_type=` (not `event_class=`) under the v4.7.12 dataclass shape.
- `notification_manager.py:925-969` — verify the event_class → anomaly_type rename in `notification_manager._dispatch_anomaly` path does not break the NM router's branching on `anomaly_type`.
- `binary_sensor.py:1885-1905` — verify the raw-string drift fix at L1892 does not subtly change the emit timing (the line was previously a literal, so AST equivalence is fine, but Reviewer B re-reads the surrounding control flow).
- `__post_init__` coercion does NOT silently mask a real bug. If a caller passes `None` instead of an `AnomalyType` member, the dataclass should raise (no default value preserves the raise).
- Field-by-field SELECT after a real emit: assert `anomaly_type = event_class` for every new row during the transition window.

**Output:** CRITICAL / HIGH / MEDIUM / LOW findings with file:line refs.

---

### Reviewer C — New surfaces + test fixture authority

**Focus:** New sensors / buttons / config knobs round-trip through options flow + RestoreEntity. Behavioral test fixtures extract schema from production source (never hand-copy DDL). Tests drive production code paths, not their own INSERT/UPDATE/DELETE.

**Checklist:**
- `AnomalyType` enum surface: imported by tests AND by production callers via the same path. Confirm `domain_coordinators/anomaly_event.AnomalyType` is the single source of truth — no shadowed local copies in tests or in `coordinator_diagnostics.py`.
- Test fixture `conftest_db._extract_alter_table_statements` parses the new `anomaly_type` tuple from `database.py` source. If the parser misses the new tuple, the fixture's schema is INCOMPLETE and the round-trip test passes against a stale schema (Bug Class #44 / v4.6.3 lesson). REQUIRED: Reviewer C runs the parser manually against the post-edit `database.py` and confirms the tuple is found.
- AST drift-prevention tests (D2 test list, items 1-3) — confirm they FAIL when given a hypothetical regression file (Reviewer C may construct a one-line synthetic regression to validate the test catches it).
- `__all__` in `anomaly_event.py` — verify both `AnomalyType` and the legacy aliases are exported (preserves any extension consumer / wildcard import).
- Module-import paths used by production are also used by tests (no `import_module(...)` redirection or sys.path tricks). Builder uses `from custom_components.universal_room_automation.domain_coordinators.anomaly_event import AnomalyType` in every test.
- Migration tests use `real_schema_db` fixture, not hand-crafted `CREATE TABLE` strings. Spot-check 3 random tests in `test_v4712_anomaly_type_discriminator.py` against this.
- All new tests INSERT via `save_anomaly_event` (the production DAO), NOT via `db.execute("INSERT INTO anomaly_log ...")`. The one exception is the migration backfill test, which must INSERT a legacy-shape row to simulate a pre-cycle DB — that one INSERT is acceptable because it's the test's setup, not the assertion path.
- README has the pre-deploy snapshot table populated with REAL numbers, not placeholders.
- Sensor reader paths — if any sensor in `sensor.py` reads `event_class` from anomaly_log rows, confirm it also (or instead) reads `anomaly_type`. Builder lists every sensor reader at code-fix time; Reviewer C verifies the list is complete.

**Output:** CRITICAL / HIGH / MEDIUM / LOW findings with file:line refs.

---

## 11. Live Validation (Review D — post-deploy)

After `./scripts/deploy.sh 4.7.12 ...` completes AND HACS installs the version AND HA restarts cleanly:

| Check | Tool | Pass criterion |
|---|---|---|
| Schema rename landed | `ha-mcp` SSH or MCP ura-sqlite — `PRAGMA table_info(anomaly_log)` | Both `event_class` and `anomaly_type` columns present |
| Migration gate set | MCP ura-sqlite — `PRAGMA user_version` | Returns `4712` |
| Backfill copied historical rows | `SELECT COUNT(*) FROM anomaly_log WHERE event_class != anomaly_type` | Returns `0` |
| Real values flow through | `SELECT anomaly_type, COUNT(*) FROM anomaly_log WHERE timestamp >= datetime('now', '-1 hour') GROUP BY anomaly_type` | At least one row exists; all `anomaly_type` values are in `{point_in_time, regime_shift, hazard, transition_invalid}` |
| Dual-write integrity | `SELECT COUNT(*) FROM anomaly_log WHERE timestamp >= datetime('now', '-1 hour') AND event_class != anomaly_type` | Returns `0` |
| No __post_init__ rejections | `ha-mcp get_logs source=system_service slug=core` | Zero lines matching `"AnomalyEvent.anomaly_type must be a member of AnomalyType"` |
| Row-rate ±25% check (per §4) | `ha-mcp` SSH or MCP ura-sqlite — re-run snapshot queries from §4.1 | Every `(coordinator_id, severity)` bucket within ±25% of pre-deploy 24h rate |
| No frame-helper warnings | `ha-mcp get_logs source=system_service slug=core` | Zero new frame-helper warnings vs pre-v4.7.12 baseline |
| Sentinel-free emit shape | `SELECT COUNT(*) FROM anomaly_log WHERE timestamp >= datetime('now', '-1 hour') AND observed_value = 0.0 AND expected_mean = 0.0` | Sentinels-only = payload shape broken (the v4.6.1.1 / v4.6.3 lesson). Acceptable count: 0 unless a legitimate binary-event row landed (verify by inspection). |

If ANY check fails: HOLD; root-cause before next cycle; do NOT proceed to v4.7.13.

---

## 12. Explicit Non-Goals

- Do NOT migrate any emitter FROM `point_in_time` TO `regime_shift` in this cycle. The `regime_detector.py:560` site that already emits `regime_shift` stays. New regime_shift sites are v4.7.13+.
- Do NOT drop the `event_class` column in v4.7.12. Deferred to v5.0 for rollback safety.
- Do NOT delete the legacy `EVENT_CLASS_*` constants. They become StrEnum aliases. v5.0 deletion alongside `event_class` column drop.
- Do NOT add new `AnomalyType` members. The 4 existing ones (point_in_time / regime_shift / hazard / transition_invalid) are the complete set for v4.7.12. v4.7.13+ may add (e.g., `boundary_violation`, `correlation_anomaly`) but must do so in its own cycle.
- Do NOT add a composite index on `(anomaly_type, coordinator_id)`. The existing single-column indexes cover today's queries; if v4.7.13 workload analysis justifies a composite, it's a separate planning doc.
- Do NOT change `notification_manager._dispatch_anomaly` routing logic. Field rename only at that site.
- Do NOT introduce `anomaly_type` to any signal payload that didn't already carry `event_class`. No new signal channels in this cycle.
- Do NOT touch the `AnomalyRecord` dataclass at `coordinator_diagnostics.py:113`. It's a diagnostics-classifier internal type; it is NOT the persistence discriminator and should NOT be renamed in this cycle (the user's brief used `AnomalyRecord` as a shorthand; the actual target is `AnomalyEvent.event_class` / `anomaly_log.event_class`).
- Do NOT add a new `anomaly_type`-filtered sensor or button. Pure infra cycle; UI surfaces are v4.7.13+.

---

## 13. Size Estimate

| Surface | Production LoC | Test LoC |
|---|---|---|
| D1 — `AnomalyType` enum + `__post_init__` + `__all__` | ~30 | (covered in D4) |
| D1 — `database.py` schema (CREATE TABLE + ALTER TABLE entry) | ~5 | (covered in D4) |
| D1 — `database.py` backfill migration block | ~30 | (covered in D4) |
| D1 — `save_anomaly_event` DAO update (dual-write + resolution order) | ~15 | (covered in D4) |
| D2 — 13 emit-site renames (kwarg + RHS) | ~26 (2 lines per site avg) | (covered in D4) |
| D3 — `__all__` extension | ~10 | (covered in D4) |
| D4 — new test file (16 functions, ~5-15 lines each) | (test code) | ~180 |
| D4 — renamed test edits (5 existing files) | (test code) | ~40 (rename diff) |
| D5 — README v4.7.12 with snapshot tables | (no code) | (no code) |
| **Total** | **~80–120 LoC production** | **~180–220 LoC tests** |

The user-specified envelope (~50 LoC production + ~40 LoC tests) is too tight for a Tier 2-DB cycle with a column rename + 13-site migration + dual-write window. Realistic envelope is ~100 LoC production + ~200 LoC tests. If the budget is hard-capped, builder cuts D3 down (the `__all__` extension is cosmetic) and/or batches the 13 emit-site renames as a scripted find-replace (counts as ~1 LoC of "real" work per site).

---

## 14. Plan Completion Tracking

To be filled out at end of cycle (MANDATORY per CLAUDE.md). Template:

| Planned item | Status | Notes |
|---|---|---|
| D1 — `AnomalyType` StrEnum + `__post_init__` | (built / partial / deferred) | |
| D1 — Fresh-install CREATE TABLE column | (built / partial / deferred) | |
| D1 — ALTER TABLE migration entry | (built / partial / deferred) | |
| D1 — Backfill UPDATE block + PRAGMA gate | (built / partial / deferred) | |
| D1 — `save_anomaly_event` dual-write | (built / partial / deferred) | |
| D2 — 13 emit-site rename | (built / partial / deferred) | Per-site count. |
| D2 — 3 drift-fix sites (binary_sensor / energy:1582 / regime_detector) | (built / partial / deferred) | Track separately because they're the proximate motivation. |
| D3 — `__all__` extension | (built / partial / deferred) | |
| D4 — new test file (16 functions) | (built / partial / deferred) | |
| D4 — 5 renamed test files | (built / partial / deferred) | |
| D5 — README v4.7.12 with pre-deploy snapshot | (built / partial / deferred) | Must include REAL numbers. |
| 5 pre-deploy zero-bugs gates | (passed / failed / skipped) | |
| Tier 2-DB review pass A (data integrity) | (clean / fixed N findings) | |
| Tier 2-DB review pass B (migration + signal chain) | (clean / fixed N findings) | |
| Tier 2-DB review pass C (new surfaces + test fixture authority) | (clean / fixed N findings) | |
| Live validation (Review D) | (clean / failed N checks) | |
| Row-rate ±25% post-deploy check | (passed / failed) | Captured 24h after restart. |

---

## 15. References

- v4.6.1 D0 — original `event_class` column addition: `database.py:1184-1206`
- v4.6.3 D11 — canonical context_json helper: `domain_coordinators/anomaly_event.py:180-228`
- v4.6.5 D1 — HVAC continuous-metric AnomalyEvent persistence
- v4.6.6 D1 — severity vocabulary expansion (precedent for additive PRAGMA-gated migration)
- v4.6.7 — NOT NULL relaxation rebuild dance (`database.py:1303-1452`) — reference pattern for in-place schema changes under SQLite constraints
- v4.6.3 Tier 2-DB review history — origin of the 3-reviewer-different-framings rule
- CLAUDE.md § Review Protocol § Tier 2-DB
- CLAUDE.md § Pre-Deploy Zero-Bugs Gate
- QUALITY_CONTEXT.md Bug Classes #7, #22, #38, #44, #45, #46
- Phase A close-out memos: `~/.claude/projects/-Users-okosisi-Code-universal-room-automation/memory/project_phase_a_shipped.md`
