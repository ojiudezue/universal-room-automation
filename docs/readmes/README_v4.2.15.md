# v4.2.15 — Fix Memory Delta NameError + DB Write Worker Blocking Startup

**Date:** 2026-04-30

## Summary

Fixes two bugs: (1) NameError crash in memory delta sensor every 30s (stale variable from v4.2.11 rewrite), (2) DB write worker blocking HA startup completion by using `async_create_background_task` instead of `async_create_task`.

## Bugs Fixed

### 1. NameError in URAMemoryDeltaSensor (sensor.py:8471)
`self._prev_count = total` — `total` variable doesn't exist in the RSS-based rewrite (v4.2.12). Leftover from the items-based v4.2.11 version. Crashed 29 times per boot, every 30s update cycle.

**Fix:** Removed the stale line.

### 2. DB write worker blocking HA startup (database.py:64)
`hass.async_create_task()` registers the task for startup tracking. Since the write worker runs forever (`while True`), HA waits indefinitely for it to complete, then logs "Something is blocking Home Assistant from wrapping up the start up phase" with `ura_db_write_worker` as the culprit.

**Fix:** Changed to `hass.async_create_background_task()` which is designed for long-running tasks that shouldn't block startup or `async_block_till_done()`.

## Known Cosmetic Issue (not fixed)
Recorder statistics unit mismatch warnings for memory sensors (KB → items/MB). Fix via HA Developer Tools → Statistics. Not a crash, just suppresses long-term stat generation for those two sensors.

## Review: Tier 1 (hotfix, 2 files, 3 lines changed)

## Files Modified (2)
- `sensor.py` — Remove stale `self._prev_count = total` line
- `database.py` — `async_create_task` → `async_create_background_task`
