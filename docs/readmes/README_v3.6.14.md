# v3.6.14 — Automation Engine Hardening

**Date:** 2026-03-02
**Cycle:** Bug fix — automation hardening
**Cross-ref:** `docs/URA_Bug_Report_Motion_Network_2026-01-14.md`, `docs/REVIEW_AUTOMATION_HARDENING.md`

---

## Summary

Addresses 20 findings from the automation hardening review, cross-referenced against the January 2026 bug report on spurious motion activations and failed auto-shutoffs. Fixes span the three oldest files in the codebase: coordinator.py, automation.py, and transitions.py.

## Changes by File

### coordinator.py (13 fixes)
- **Stuck sensor detection** — Tracks per-sensor continuous-on duration. Sensors on >4 hours are flagged and excluded from occupancy detection. Prevents the failsafe bypass that kept rooms permanently occupied.
- **Entry debounce (time-based)** — Sensors must be active for 2+ seconds before confirming new entry. Works with both event-driven and polled updates. Prevents spurious single-blip activations.
- **Sensor unavailability grace** — When all sensors go unavailable simultaneously (Zigbee restart), holds previous occupancy state for 60s instead of triggering false vacancy.
- **Failsafe uses `_became_occupied_time`** — Failsafe timer tracks session start, not last motion event. Legitimate motion no longer resets the 4-hour failsafe timer.
- **Camera override respects failsafe** — Camera person sensor cannot re-assert occupancy after failsafe fires. Prevents stuck Frigate/UniFi sensors from defeating the failsafe.
- **`_calculate_device_counts` NoneType guard** — All entity state lookups guard against None (removed entity in registry).
- **DB occupancy logging fixed** — `was_occupied` captured before `_last_occupied_state` update. Occupancy events now reach the database.
- **RESILIENCE-003 non-blocking** — Exit verification moved to `async_create_task` with 3s delay. No longer blocks the coordinator update cycle.
- **Exit verify respects leave-on action** — Only retries when exit action is TURN_OFF. Skips retry if room re-occupied during delay. Uses fresh coordinator data.
- **Energy accumulator timing** — Uses actual elapsed time instead of hardcoded 30s.
- **Config refresh for periodic automation** — `_refresh_config()` called before periodic tasks (fan control, shared space) so options flow changes take effect without reload.
- **State tracking when automation disabled** — `_last_occupied_state` updated even when automation switch is off.
- **Startup log level** — Changed CRITICAL banners to INFO.

### automation.py (7 fixes)
- **Sleep bypass fix** — Passes `STATE_MOTION_DETECTED` instead of `STATE_OCCUPIED` to `can_bypass_sleep_mode()`. Counter now increments only on actual motion events.
- **`_refresh_config()`** — Merges `entry.data` + `entry.options` on each occupancy change + periodic cycle. Options flow changes take effect without reload.
- **Bug Class #4 in shared space** — `_shared_space_turn_off_all()` separates light.*/switch.* domains. `_warning_flash()` only targets light.* entities.
- **Service call retry** — `_safe_service_call()` accepts `max_retries` param with exponential backoff (1s, 2s). Default 0 (fire-and-forget) preserves existing behavior.
- **Temperature hysteresis** — 2°F dead band prevents rapid fan cycling at threshold boundary.
- **Warning flash dedup** — Tracks `_last_warning_date_hour` to prevent multiple triggers within the same minute window.
- **Startup log level** — Changed CRITICAL banners to INFO.

### transitions.py (1 fix)
- **Removed `@callback` from async functions** — `_on_location_change` and `_async_cleanup_history` were silently producing unawaited coroutines. Entire transition detection pipeline was non-functional.

## Bug Report Status

| January Bug Report Item | Status |
|---|---|
| Spurious motion activations (Dimension 1) | Fixed: entry debounce, stuck sensor filtering |
| Failed auto-shutoff (Dimension 2) | Fixed: failsafe bypass, camera override guard |
| Sensor unavailability false vacancy | Fixed: 60s grace period |
| State reconciliation | Improved: non-blocking exit verify with re-check |
| Service call retry | Added: optional exponential backoff |
| HA restart state persistence | Not addressed (larger refactor needed) |

## Tests

590 existing tests pass. No regressions.
