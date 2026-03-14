# v3.15.2: Hotfix — Thread Safety, isoformat, DB Type Annotations

**Date:** 2026-03-13
**Branch:** develop -> main
**Tests:** 1063 passed (no regressions)

## Bugs Fixed

### 1. Census sensor thread safety (`sensor.py:2562`)
**3661 occurrences** — `_handle_census_update` called `async_write_ha_state()` directly from a dispatcher callback. HA 2026 / Python 3.14 now enforces that `async_write_ha_state` must be called from the event loop thread, raising `RuntimeError` on violation.

**Fix:** Changed to `async_schedule_update_ha_state()` which safely schedules the state write.

### 2. `isoformat()` on string (`aggregation.py:3004`)
`ZoneLastOccupantSensor.extra_state_attributes` called `.isoformat()` on `_last_occupant_time`, but the DB returns this value as a string. The sibling `ZoneLastOccupantTimeSensor` already had an `isinstance` check.

**Fix:** Added `isinstance(t, str)` guard — use as-is if string, call `.isoformat()` if datetime.

### 3. `database.py` — Missing `from __future__ import annotations`
54 uses of `str | None` PEP 604 union syntax worked on HA's Python 3.14 but broke test collection on Python 3.9 (local dev).

**Fix:** Added `from __future__ import annotations` import.

## Files Changed

| File | Changes |
|------|---------|
| `sensor.py` | `async_write_ha_state()` → `async_schedule_update_ha_state()` in census handler |
| `aggregation.py` | `isinstance` guard on `_last_occupant_time` before `.isoformat()` |
| `database.py` | Added `from __future__ import annotations` |
