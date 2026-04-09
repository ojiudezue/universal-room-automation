# v4.0.3 — Fix: Room Coordinator Reload Performance

## Bug Fix

**Problem:** On every reload/restart, each room coordinator re-triggered full entry automation (lights on, fans on, covers open) because `_last_occupied_state` started as `False` on fresh coordinator creation. If the room was occupied, the first refresh saw a false occupancy transition and fired all entry actions — unnecessary service calls that congested the event loop and caused config flow saves to timeout with "unknown error."

**Root cause:** RestoreEntity state restoration in `OccupiedBinarySensor.async_added_to_hass()` runs AFTER `async_config_entry_first_refresh()`, which already triggered automation based on stale state.

**Fix — two-layer defense:**

1. **DB pre-restore (primary):** Before `async_config_entry_first_refresh()`, read the room's last known state from the `room_state` DB table. Restores `_last_occupied_state`, `_became_occupied_time`, and `_failsafe_fired`. This prevents the false transition entirely.

2. **`_skip_first_automation` flag (safety net):** Even if DB restore fails, the first coordinator update unconditionally skips automation execution and syncs state from live sensors. Cleared after one cycle.

**Impact:**
- Config flow saves should complete without "unknown error" (reload no longer fires 30+ rooms' entry automations)
- HA restarts are faster (no unnecessary service call storm)
- One missed automation cycle (~30s) after reload — acceptable trade-off vs false triggers on every restart

## Files Changed
- `__init__.py` — Pre-restore room state from DB before first refresh
- `coordinator.py` — `_skip_first_automation` flag in `__init__` + guard in `_async_update_data`

## Review
Single-review hotfix tier. 0 CRITICAL, 0 HIGH, 1 MEDIUM (pre-existing edge case), 2 LOW.
