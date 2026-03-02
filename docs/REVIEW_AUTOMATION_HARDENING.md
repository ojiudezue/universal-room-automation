# Automation Engine Hardening — Review Findings

**Date:** 2026-03-02
**Reviewer:** ura-reviewer (opus)
**Scope:** automation.py, coordinator.py, transitions.py, sensor.py, binary_sensor.py

## P0 — Must Fix

1. **TransitionDetector `@callback` on async functions** (transitions.py:94, 342) — `@callback` decorator on `async def` methods means coroutines are never awaited. Handlers silently do nothing. Entire transition detection pipeline non-functional.

2. **Database occupancy logging dead** (coordinator.py:718 vs :662) — `_last_occupied_state` comparison for DB logging runs AFTER state already updated at line 662. Values always equal. Occupancy events never reach database. Breaks predictions and historical analysis.

3. **Sleep protection bypass broken** (automation.py:218) — `should_execute_automation()` passes `STATE_OCCUPIED` (overall occupancy bool) as `motion_detected` param to `can_bypass_sleep_mode()`. Counter increments every refresh (~30s) instead of on actual motion events. Sleep protection bypassed in ~90s instead of 3 deliberate motions.

4. **Shared space auto-off has Bug Class #4** (automation.py:912-918, 882-906) — `_shared_space_turn_off_all()` and `_warning_flash()` call `light.*` services on mixed entity lists containing switches. Same bug fixed in `_control_lights_exit()` but not applied here.

5. **`_calculate_device_counts` NoneType crash** (coordinator.py:396-425) — `self.hass.states.get(light).state` crashes with AttributeError when entity removed from registry but still in area. Same for fans, switches, covers.

## P1 — Should Fix

6. **No entry automation debouncing** (coordinator.py:513) — Single spurious sensor `on` blip triggers full entry automation. No minimum dwell time, no cross-sensor validation. Root cause of bug report Dimension 1.

7. **`asyncio.sleep(3)` blocks coordinator** (coordinator.py:673) — RESILIENCE-003 retry blocks entire `_async_update_data()` for 3 seconds. Should be separate delayed task.

8. **All-sensors-unavailable → false vacancy** (coordinator.py:513) — Zigbee coordinator restart makes all sensors unavailable simultaneously. Room immediately starts vacancy countdown. Should hold state for grace period (~60s).

9. **No stuck-on sensor detection** — mmWave sensor stuck `on` bypasses 4-hour failsafe entirely. Failsafe only fires when no sensors actively on.

10. **Automation config stale after options change** (coordinator.py:150, automation.py:123) — `RoomAutomation` holds config snapshot from init. Options flow changes don't reach it until full reload.

11. **HA restart loses all occupancy state** (coordinator.py:105-108) — All state in memory. Restart causes false off→on cycle in every occupied room.

## P2 — Nice to Have

12. Temperature hysteresis tested but not implemented (automation.py:694)
13. Warning flash timing fragile — exact `minute == 55` match (automation.py:868)
14. No service call retry for critical operations
15. CRITICAL log level used for startup banners (coordinator.py:99, automation.py:127)
