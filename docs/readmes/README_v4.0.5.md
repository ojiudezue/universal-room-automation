# v4.0.5 — Fix: Config Flow Save + Energy TOU Blocking I/O

## Bug Fixes

### 1. Config Flow Save "Unknown Error" (Bug #1 — long-standing)

**Problem:** Saving room/coordinator/zone options in the config flow showed "unknown error" on first attempt. Second attempt appeared to succeed, but changes never took effect on the running device — the coordinator kept using old config even though `entry.options` had the new values on disk.

**Root cause:** `_async_update_listener` did `await hass.config_entries.async_reload(entry.entry_id)` inline. With 93+ entities per room, the unload/setup cycle took 30-60+ seconds. The HA frontend API call timed out (~30s), the browser disconnected, and `aiohttp` cancelled the asyncio task mid-reload. The entry was left half-unloaded — `async_unload_entry` partially ran (deleting coordinator data) but `async_setup_entry` never ran (so no new coordinator was created with updated config).

**Fix:** Changed to `hass.async_create_task(hass.config_entries.async_reload(...))`. The OptionsFlow now returns immediately (UI shows success), and the reload completes independently in the background. HA serializes per-entry reloads, so rapid double-saves are safe.

**Files:** `__init__.py` (line 2203-2216)

### 2. Energy TOU Blocking I/O (Bug #2)

**Problem:** `TOURateEngine.from_json_file()` called `filepath.read_text()` synchronously on the event loop. HA 2026.x flags this as blocking I/O (`energy_tou.py:68`).

**Fix:** Split into three methods:
- `_read_json_file()` — pure blocking I/O, safe to run in executor
- `_from_parsed_data()` — pure parsing, no I/O
- `async_from_json_file()` — async wrapper using `hass.async_add_executor_job`

The call site in `__init__.py` now pre-loads the TOU engine async and passes it to `EnergyCoordinator(tou_engine=...)`. The sync `from_json_file` is preserved for test backward compatibility.

**Files:** `energy_tou.py`, `energy.py` (constructor), `__init__.py` (call site)

## Acceptance Criteria & Verification

### Bug 1 Verification
- **Verify:** Open Settings → Devices & Services → URA → any room entry → Configure
- **Verify:** Change a setting (e.g., occupancy timeout) → Submit → UI shows success (no "unknown error")
- **Verify:** Open the room device page → verify the changed setting is reflected
- **Verify:** Repeat for Coordinator Manager entry (change a coordinator setting)
- **Verify:** Repeat for Zone Manager entry
- **Live:** Check HA logs for `"Options changed for '<entry>', scheduling reload"` followed by successful reload (no errors/tracebacks)
- **Live:** No `asyncio.CancelledError` in logs after config saves
- **Test:** All 1670 existing tests pass (0 regressions)

### Bug 2 Verification
- **Verify:** No `Detected blocking call to open/read inside the event loop` warnings in HA logs related to `energy_tou.py`
- **Verify:** Energy Coordinator TOU sensors still show correct period/rate (unchanged behavior)
- **Live:** Check `sensor.ura_coordinator_manager_energy_tou_period` shows correct TOU period
- **Live:** Check `sensor.ura_coordinator_manager_energy_tou_rate` shows non-zero rate
- **Test:** All 19 `test_energy_tou.py` tests pass

## Review Summary
- Tier 1 hotfix review (single review)
- 0 CRITICAL, 0 HIGH, 3 MEDIUM (deferred), 3 LOW (cosmetic)
- Full report: reviewed against all 23 QUALITY_CONTEXT bug classes

## Files Changed
- `custom_components/universal_room_automation/__init__.py` — update listener + TOU pre-load
- `custom_components/universal_room_automation/domain_coordinators/energy_tou.py` — async refactor
- `custom_components/universal_room_automation/domain_coordinators/energy.py` — tou_engine constructor param
