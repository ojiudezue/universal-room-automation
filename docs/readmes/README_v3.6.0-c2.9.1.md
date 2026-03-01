# Universal Room Automation v3.6.0-c2.9.1 — Fix C2.9 Regression + Test Alignment

**Release Date:** 2026-02-28
**Internal Reference:** C2.9.1
**Previous Release:** v3.6.0-c2.9
**Minimum HA Version:** 2024.1+

---

## Summary

C2.9 wired up anomaly detectors but introduced a regression: if `load_baselines()` threw an exception during `async_setup()`, the entire Presence Coordinator setup would crash. This prevented census seeding and initial inference from running, causing house state to revert to "away" and zones to show "unknown".

This release wraps `load_baselines()` in try/except in both coordinators, and aligns all safety tests with the c2.6 threshold changes.

---

## Root Cause

The Presence Coordinator's `async_setup()` calls `await self.anomaly_detector.load_baselines()`. Although `load_baselines()` has its own internal try/except for DB errors, certain failure modes (e.g., database not yet in `hass.data`) could propagate an unhandled exception. This killed `async_setup()` entirely — everything after that line (census seeding, initial inference, listener registration) never ran.

The Coordinator Manager's `async_start()` catches per-coordinator `async_setup()` failures, so the Safety Coordinator still initialized. But the Presence Coordinator was dead, resulting in:
- House state stuck at "away"
- All zones showing "unknown"

---

## Changes

### Presence Coordinator (`presence.py`)

Wrapped `load_baselines()` in try/except:

```python
try:
    await self.anomaly_detector.load_baselines()
except Exception:
    _LOGGER.debug("Could not load presence anomaly baselines (non-fatal)", exc_info=True)
```

### Safety Coordinator (`safety.py`)

Same defensive wrapper added:

```python
try:
    await self.anomaly_detector.load_baselines()
except Exception:
    _LOGGER.debug("Could not load safety anomaly baselines", exc_info=True)
```

### Test Alignment (`test_safety_coordinator.py`)

Updated 9 tests to match c2.6 threshold changes and c2.8 behavior changes:

| Test | Change |
|------|--------|
| `test_humidity_normal_room_thresholds` | Updated for raised thresholds: 92% = HIGH, 82% = MEDIUM; added one-shot reset |
| `test_humidity_bathroom_thresholds` | Added `_humidity_hazard_fired.discard()` between severity checks |
| `test_critical_response_has_lights` | Added `_emergency_lights` setup (no longer uses entity_id "all") |
| `test_critical_co_response_has_ventilation` | Changed to assert fan actions == 0 (CO fan blast removed in c2.8) |
| `test_co_thresholds_exist` | CO LOW: 10 -> 25 |
| `test_classify_severity_co` | CO LOW test: 15 -> 30, None test: 5 -> 20 |
| `test_basement_55_triggers_low` | Value: 56 -> 66 (basement LOW: 55 -> 65) |
| `test_basement_66_triggers_medium` | Value: 66 -> 76 (basement MEDIUM: 65 -> 75) |
| `test_basement_76_triggers_high` | Value: 76 -> 86 (basement HIGH: 75 -> 85) |
| `test_humidity_fires_after_sustained_window` | Expected severity: HIGH -> MEDIUM (82% is now MEDIUM) |
| `test_normal_room_thresholds` | Constant assertions: 60/70/80 -> 70/80/90 |
| `test_basement_thresholds` | Constant assertions: 55/65/75 -> 65/75/85 |

---

## Database Initialization Audit

Verified the database initialization path is robust:

1. **Table creation**: `metric_baselines` and `anomaly_log` use `CREATE TABLE IF NOT EXISTS` in `database.py`
2. **Execution order**: Database initializes before coordinators in the Integration entry setup
3. **Null safety**: `_database` property returns `None` if DB missing; all DB methods check for this
4. **3-layer error protection**: Internal try/except in `load_baselines()`, coordinator-level try/except, and `CoordinatorManager.async_start()` try/except

---

## Test Results

**590 passed, 0 failed** (up from 506 in c2.9 due to test counting methodology)

---

## Files Changed

| File | Change |
|------|--------|
| `domain_coordinators/presence.py` | Wrap `load_baselines()` in try/except |
| `domain_coordinators/safety.py` | Wrap `load_baselines()` in try/except |
| `quality/tests/test_safety_coordinator.py` | Align 12 tests with c2.6/c2.8 changes |

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
| **3.6.0-c2.9.1** | **C2.9.1** | **Fix c2.9 regression + test alignment** |
