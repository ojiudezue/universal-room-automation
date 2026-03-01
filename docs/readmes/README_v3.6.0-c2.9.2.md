# Universal Room Automation v3.6.0-c2.9.2 — Fix Database Init + Duplicate Entity ID

**Release Date:** 2026-02-28
**Internal Reference:** C2.9.2
**Previous Release:** v3.6.0-c2.9.1
**Minimum HA Version:** 2024.1+

---

## Summary

Database initialization was failing with "no such column: scope" on existing installations. This cascading failure prevented the database from being stored in `hass.data`, which caused multiple downstream errors including transition logging failures and PersonLikelyNextRoomSensor crashes.

Also fixed a duplicate unique_id collision between the room-level and coordinator-level safety alert binary sensors.

---

## Root Cause: Database "no such column: scope"

The `decision_log` and `compliance_log` tables were originally created without a `scope` column (pre-c0.4). The c0.4 release added:

1. `scope` column in the `CREATE TABLE IF NOT EXISTS` statement (for new installs)
2. `ALTER TABLE ADD COLUMN scope` migration (for existing installs)
3. `CREATE INDEX idx_decision_scope ON decision_log(scope)`

**The problem:** Step 3 (index creation) ran BEFORE step 2 (migration). Since `CREATE TABLE IF NOT EXISTS` is a no-op for existing tables, the old table had no `scope` column when the index tried to reference it.

```
CREATE TABLE IF NOT EXISTS decision_log (... scope ...)  -- no-op, table exists
CREATE INDEX IF NOT EXISTS idx_decision_scope ON decision_log(scope)  -- FAILS: no such column
...
ALTER TABLE decision_log ADD COLUMN scope  -- never reached
```

**The fix:** Moved the `ALTER TABLE` migrations to run immediately after each `CREATE TABLE` and before any `CREATE INDEX` that references the new column.

---

## Cascading Effects of Database Failure

When `database.initialize()` returned `False`, `hass.data[DOMAIN]["database"]` was never set. This caused:

| Error | Root Cause |
|-------|-----------|
| `PersonLikelyNextRoomSensor: 'NoneType' object has no attribute 'get_transitions'` | PatternLearner initialized with `database=None` |
| `Failed to log transition: 'NoneType' object has no attribute 'log_transition'` | TransitionTracker's database reference was None |
| Zone presence "unknown" | Zone aggregation sensors depend on working database for transition data |

---

## Duplicate Entity ID: safety_alert

Two binary sensors had the same unique_id `universal_room_automation_safety_alert`:

| Class | File | Purpose |
|-------|------|---------|
| `SafetyAlertBinarySensor` (aggregation.py:787) | Room-level | Aggregates per-room safety alerts |
| `SafetyAlertBinarySensor` (binary_sensor.py:1009) | Coordinator-level | Reports coordinator hazard state |

**Fix:** Changed the coordinator-level sensor's unique_id to `universal_room_automation_safety_coordinator_safety_alert`.

---

## Files Changed

| File | Change |
|------|--------|
| `database.py` | Move scope column migrations before index creation; remove duplicate migration block |
| `binary_sensor.py` | Change coordinator safety_alert unique_id to avoid collision |

---

## How to Verify

1. After restart, check logs — "Error initializing database: no such column: scope" should be gone
2. "Database initialized successfully" should appear in logs
3. PersonLikelyNextRoomSensor errors should stop
4. Transition logging errors should stop
5. `binary_sensor.universal_room_automation_safety_coordinator_safety_alert` should appear without duplicate ID warning

---

## Version Mapping

| Version | Cycle | Description |
|---------|-------|-------------|
| 3.6.0-c0 - c0.4 | C0 | Domain coordinator infrastructure + diagnostics |
| 3.6.0-c1 | C1 | Presence Coordinator |
| 3.6.0-c2 - c2.6 | C2 | Safety Coordinator + deployment fixes |
| 3.6.0-c2.7 | C2.7 | Fix toggle switches not appearing |
| 3.6.0-c2.8 | C2.8 | Fix unsafe entity_id "all" in safety response |
| 3.6.0-c2.9 | C2.9 | Wire up anomaly detectors for Presence and Safety |
| 3.6.0-c2.9.1 | C2.9.1 | Fix c2.9 regression + test alignment |
| **3.6.0-c2.9.2** | **C2.9.2** | **Fix database init + duplicate entity ID** |
