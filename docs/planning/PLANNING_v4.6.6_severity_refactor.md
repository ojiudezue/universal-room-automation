# PLANNING — v4.6.6 Anomaly Severity Vocabulary Refactor

**Cycle classification:** Tier 2-DB (touches `database.py` semantics +
payload shape of dispatched/persisted events + migrates ≥3 callers).
**Branch:** `feature/v4.6.6-severity-refactor` (this worktree) merges into
`develop` AFTER `v4.6.5.1` lands. **Single-user install** — no back-compat
shims required, but a one-shot DB row remap is needed (see Migration).

---

## Problem statement

`coordinator_diagnostics.AnomalySeverity` (StrEnum) emits a 4-bucket
classification driven by z-score:

| Bucket   | z-score band  | StrEnum value |
| -------- | ------------- | ------------- |
| NOMINAL  | < 2.0         | "nominal"     |
| ADVISORY | 2.0–3.0       | "advisory"    |
| ALERT    | 3.0–4.0       | "alert"       |
| CRITICAL | > 4.0         | "critical"    |

Every coordinator emit site collapses that 4-way result into the 2-bucket
`anomaly_event.AnomalySeverity` IntEnum with this idiom:

```python
severity=_NewSev.CRITICAL if anomaly.severity.value == "critical" else _NewSev.WARNING
```

Consequence: ADVISORY (z 2-3) and ALERT (z 3-4) BOTH persist as
`anomaly_log.severity = 1` (WARNING). Severity-grouped analytics, the
`URARecentAnomaliesSensor.by_severity` attribute, and downstream NM
threshold filters all see them as one bucket.

Reviewers **A-M2** and **B-M1** flagged this independently during the
v4.6.5 Tier 2-DB review.

---

## D0 (already shipped this branch): non-overlapping core changes

These three files were modified in this worktree because they do NOT
collide with v4.6.5.1 in flight:

| File | Change |
| ---- | ------ |
| `domain_coordinators/anomaly_event.py` | `AnomalySeverity` expanded from 3 → 5 members. New canonical scale: `INFO=0, WARNING=1, ADVISORY=2, ALERT=3, CRITICAL=4`. Sort order preserved. |
| `sensor.py` (`_SEVERITY_TO_ROUTINE_STATE`) | Extended the int→state map to cover values 2/3/4 in addition to the prior 0/1/2. CRITICAL is now key 4 (was 2). |
| `quality/tests/test_v466_severity_refactor.py` | New test file: enum-shape (5 tests), DB round-trip via `real_schema_db` (3 tests), `URARecentAnomaliesSensor.by_severity` aggregation (3 tests), DAO coupling guards (2 tests). 13 tests total. |

Three pre-existing tests had to be updated to reflect `CRITICAL=4`:

- `quality/tests/test_v461_severity_unification.py` — 2 assertions
- `quality/tests/test_v461_anomaly_event_dataclass.py` — 1 test body
- `quality/tests/test_v463_anomaly_migration.py` — 1 test body

`database.py:save_anomaly_event` was **inspected** but required **no code
change** — it already calls `int(event.severity)` on the way to the INSERT,
which works for any IntEnum value. Same for
`URARecentAnomaliesSensor._async_refresh`'s by-severity query: pure
`GROUP BY severity`, no hardcoded integer set, so new values surface
automatically.

### D0 Acceptance Criteria

- **Verify:** `AnomalySeverity` has exactly 5 members in canonical order.
- **Verify:** Each of the 5 severity values round-trips through the
  production-extracted INSERT SQL into `anomaly_log` and back as the same
  integer (validated against `real_schema_db`).
- **Verify:** `URARecentAnomaliesSensor.by_severity` aggregation returns
  all 5 keys when rows at each severity exist; missing severities don't
  appear as zero-count keys.
- **Test:** `test_v466_severity_refactor.py::test_severity_enum_has_five_members`
  + `::test_severity_roundtrips_for_every_bucket`
  + `::test_by_severity_aggregation_returns_all_five_keys`.

---

## D1 (DEFERRED — follow-up session after v4.6.5.1 merges): coordinator emit-site migration

Each emit site below currently uses the 2-way collapse idiom. Update each
to a 4-way mapping that preserves the classifier output. **Apply ONE PR**
covering all sites; landing them piecemeal leaves the persisted enum
inconsistent across coordinators.

### Replacement helper (add to `domain_coordinators/anomaly_event.py`)

```python
# v4.6.6 D1: classifier-output → persisted-severity 1:1 mapping.
# Coordinator emit sites call this instead of the 2-way ternary.
_DIAG_TO_EVENT_SEVERITY = {
    # keys: coordinator_diagnostics.AnomalySeverity StrEnum string values
    "nominal":  AnomalySeverity.INFO,
    "advisory": AnomalySeverity.ADVISORY,
    "alert":    AnomalySeverity.ALERT,
    "critical": AnomalySeverity.CRITICAL,
}

def map_diag_severity(diag_sev) -> AnomalySeverity:
    """Map a coordinator_diagnostics.AnomalySeverity to the persisted IntEnum.

    Accepts either the StrEnum instance or its .value string. Anything not
    in the table falls back to WARNING — same defensive default the prior
    2-way idiom produced for non-CRITICAL inputs.
    """
    key = getattr(diag_sev, "value", diag_sev)
    return _DIAG_TO_EVENT_SEVERITY.get(key, AnomalySeverity.WARNING)
```

### Emit sites to migrate

| File | Line (as of develop @ v4.6.5) | Current code | Replacement |
| ---- | -----------------------------: | ------------ | ----------- |
| `domain_coordinators/presence.py` | 1740 | `severity=_NewSev.CRITICAL if anomaly.severity.value == "critical" else _NewSev.WARNING,` | `severity=map_diag_severity(anomaly.severity),` |
| `domain_coordinators/safety.py` | 1670 | same idiom | `severity=map_diag_severity(anomaly.severity),` |
| `domain_coordinators/safety.py` | 1719 | `severity=_NewSev.WARNING,` (constant, no classifier input) | Leave as `AnomalySeverity.WARNING` — this is a binary hazard with no z-score classification. Add comment. |
| `domain_coordinators/hvac.py` | (audit before edit) | If any emit uses the 2-way ternary | Same `map_diag_severity` migration |
| `domain_coordinators/security.py` | (audit before edit) | If any emit uses the 2-way ternary | Same migration |
| `domain_coordinators/music_following.py` | (audit before edit) | If any emit uses the 2-way ternary | Same migration |

The v4.6.5.1 cycle is editing these same coordinator files, so the audit must be redone after `v4.6.5.1` merges to `develop`. Run:

```bash
git grep -nE '_NewSev\.CRITICAL if .* else _NewSev\.WARNING' custom_components/universal_room_automation/domain_coordinators/
git grep -nE 'severity=.*anomaly\.severity\.value' custom_components/universal_room_automation/domain_coordinators/
```

### D1 Acceptance Criteria

- **Verify:** No remaining occurrences of the 2-way ternary in any coordinator file. `git grep -nE '_NewSev\.CRITICAL if .* else _NewSev\.WARNING' custom_components/` returns empty.
- **Verify:** Each migrated emit site, when fed an `AnomalyRecord` with `severity == ADVISORY`, calls `save_anomaly_event` with an `AnomalyEvent` whose `severity == AnomalySeverity.ADVISORY` (value 2).
- **Sensor:** `sensor.ura_coordinator_manager_recent_anomalies.attributes.by_severity` shows keys `"2"` and/or `"3"` post-restart (proves ADVISORY/ALERT rows are landing under their own keys).
- **Test:** Add `test_v466_emit_site_severity_mapping.py` in the follow-up session: parametrize each coordinator's emit code path with a fake `AnomalyRecord(severity=...)` for each of the 4 classifier buckets, assert the resulting `AnomalyEvent.severity` matches the mapping table.
- **Live:** After deploy + 60 minutes of activity, query
  `SELECT severity, COUNT(*) FROM anomaly_log WHERE timestamp >= datetime('now', '-1 hour') GROUP BY severity;`
  on the production DB. ADVISORY (severity=2) AND/OR ALERT (severity=3)
  rows must appear if any z-scores in the 2.0–4.0 band occurred. If only
  severity 1 and 4 rows appear, an emit site was missed.

---

## D2 (DEFERRED — same follow-up session): one-shot DB row remap

Existing `anomaly_log` rows persisted before v4.6.6 store the OLD
`CRITICAL = 2`. Post-v4.6.6, the integer 2 means ADVISORY. Without a
remap, every historic CRITICAL row will read back as ADVISORY in the
sensor, in analytics, and via the StrEnum lookup the UI uses.

Single-user install — no migration cycle scaffolding needed; a one-shot
ALTER-style backfill in `database.py` is fine.

### Proposed migration (place in `database.py` v4.6.6 migration block)

```python
# v4.6.6 — Remap historic anomaly_log.severity values to the new IntEnum.
# Pre-v4.6.6 schema: severity ∈ {0, 1, 2} where 2 = CRITICAL.
# Post-v4.6.6 schema: severity ∈ {0, 1, 2, 3, 4} where 4 = CRITICAL.
#
# Rows persisted before v4.6.6 cannot distinguish ADVISORY/ALERT (both
# collapsed to 1 = WARNING), so the only remap needed is 2 → 4 to move
# historic CRITICAL rows into the new CRITICAL value. ADVISORY/ALERT will
# start appearing only for rows written by v4.6.6+ emit sites.
#
# Idempotent: a second run sees no rows with severity='2' since the first
# run remapped them; the legacy backfill at line ~1206 has already turned
# any remaining string severities into numeric strings, so we only need to
# touch the integer-string '2' values.
try:
    cursor = await db.execute(
        """UPDATE anomaly_log
           SET severity = '4'
           WHERE severity = '2'"""
    )
    await db.commit()
    if cursor.rowcount > 0:
        _LOGGER.info(
            "v4.6.6 severity remap: rewrote %d historic CRITICAL rows from "
            "'2' to '4' to match new AnomalySeverity.CRITICAL value",
            cursor.rowcount,
        )
except Exception as e:
    _LOGGER.warning("v4.6.6 anomaly_log severity remap failed: %s", e)
```

### D2 Acceptance Criteria

- **Verify:** Pre-deploy, snapshot
  `SELECT severity, COUNT(*) FROM anomaly_log GROUP BY severity` and save
  the counts to `docs/reviews/code-review/v4.6.6_pre_deploy_severity_snapshot.txt`.
- **Verify:** Post-deploy, the count of rows with severity='2' is zero,
  and the count of rows with severity='4' equals (pre-deploy count of '2')
  + (any new v4.6.6 CRITICAL rows written since restart).
- **Live:** No rows exist with `severity NOT IN ('0','1','2','3','4')` —
  the schema column is TEXT so a typo'd remap could leave a row with a
  non-numeric string. Use `SELECT DISTINCT severity FROM anomaly_log` to
  confirm.

---

## Discovered concerns — call out before D1/D2 ship

1. **Two enums with the same name.** `coordinator_diagnostics.AnomalySeverity`
   (StrEnum) and `anomaly_event.AnomalySeverity` (IntEnum) coexist. Any
   `from .anomaly_event import AnomalySeverity` and
   `from .coordinator_diagnostics import AnomalySeverity` in the same
   coordinator file silently shadows. Search the migration site for
   `import AnomalySeverity` to confirm exactly which one is in scope
   before applying `map_diag_severity`.

2. **`notification_manager.py:1961`** uses `severity >= threshold` for
   alert filtering. Today, thresholds were set assuming CRITICAL=2.
   If anyone configured an integer threshold (e.g. `>= 2`), the
   post-v4.6.6 meaning shifts (>= 2 now includes ADVISORY/ALERT/CRITICAL,
   not just CRITICAL). Audit the threshold construction site —
   `_severity_map` and any user-configurable threshold settings — to
   confirm thresholds are derived from enum members, not raw ints.

3. **`manager.py:628`** has a `severity_order` dict keyed on the
   **StrEnum** `AnomalySeverity` (NOMINAL/ADVISORY/ALERT/CRITICAL), not
   the IntEnum. Not affected by this cycle.

4. **`sensor.py:_SEVERITY_TO_ROUTINE_STATE`** — extended in D0 to cover
   integers 0–4. Note that ADVISORY (2) and ALERT (3) both map to
   `"shifted"` (same human-readable state as WARNING). If product wants
   per-bucket UX, add new state strings (`"early_shift"`, `"escalating"`)
   and update the routine status sensor's docstring + downstream NM
   templates. NOT in scope for v4.6.6 itself.

5. **Database backfill at line 1206-1225** maps legacy
   `'advisory'`/`'alert'` strings → `'1'`. That migration is one-shot;
   any rows it touched are already collapsed. The D2 remap deliberately
   leaves them at '1' (WARNING) — we cannot reconstruct the lost ADVISORY/
   ALERT distinction from historic strings. Document this in the deploy notes.

6. **Existing analytics queries** that filter by `severity = 2` are now
   selecting historic CRITICAL rows (pre-remap) OR ADVISORY rows
   (post-v4.6.6, after the remap renumbers CRITICAL to 4). Audit before
   shipping:
   ```bash
   git grep -nE "severity\s*=\s*'?2'?" custom_components/ scripts/
   ```

---

## Plan Completion Tracking

After this branch lands + the follow-up D1/D2 session ships, document:

- **D0 (this branch):** Enum expansion + sensor mapping + test infra — DONE.
- **D1 (follow-up):** Coordinator emit-site migration to `map_diag_severity` — TODO.
- **D2 (follow-up):** One-shot DB row remap (2 → 4) — TODO.
- **Out of scope (deliberately deferred):** UX-level per-bucket routine state strings (`"early_shift"`, `"escalating"`). Track in BACKLOG.md under "v4.6.x severity UX polish".

---

## Tier 2-DB review framing (for the follow-up session)

When the follow-up session opens its three parallel reviews:

- **Review A — Data integrity / DB architecture preservation.** Confirm the D2 remap touches only `severity = '2'` rows, no other columns. Confirm `idx_anomaly_severity` still covers post-remap queries. Confirm no analytics SQL elsewhere in the codebase encodes integer 2 as CRITICAL.
- **Review B — Migration correctness / signal chain integrity.** For each migrated emit site, trace one synthetic `AnomalyRecord(severity=ADVISORY)` through the coordinator code path and confirm an `AnomalyEvent` with `severity = ADVISORY` (value 2) is what reaches `save_anomaly_event`. Field-by-field compare against the pre-migration emit.
- **Review C — New surfaces / test fixture authority.** Confirm `map_diag_severity` has a test that covers all 4 inputs + the fallback. Confirm `_SEVERITY_TO_ROUTINE_STATE` covers integers 0-4. Confirm the new test file extracts INSERT SQL from production (already done in D0 — verify no copy-paste regression).

**Pre-deploy snapshot of affected table:**
`SELECT coordinator_id, severity, COUNT(*) FROM anomaly_log WHERE timestamp >= datetime('now', '-7 days') GROUP BY coordinator_id, severity;`

**Live Validation (Review D, post-restart):** Within 60 minutes of restart, at least one `anomaly_log` row must exist with `severity IN ('2', '3')` AND non-zero `z_score` AND non-zero `expected_std`. If the only severities present are '0', '1', '4' the migration is incomplete (an emit site is still using the 2-way ternary).
