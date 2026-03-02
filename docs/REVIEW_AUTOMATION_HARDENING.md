# Automation Engine Hardening — Review Findings

**Date:** 2026-03-02 (updated)
**Reviewer:** ura-reviewer (opus)
**Scope:** automation.py, coordinator.py, transitions.py, sensor.py, binary_sensor.py
**Cross-ref:** `docs/URA_Bug_Report_Motion_Network_2026-01-14.md`

---

## Bug Report Cross-Reference

The January 2026 bug report identified two dimensions of failure: spurious motion activations and failed auto-shutoffs. Status of each proposed solution against current code:

| Bug Report Item | Status | Notes |
|---|---|---|
| Maximum active duration failsafe | Partial | RESILIENCE-001 exists (coordinator.py:553) but stuck sensors bypass it (see #9) |
| Motion sensor debouncing | Unaddressed | Single sensor blip triggers entry (see #6) |
| Multi-sensor confirmation | Unaddressed | OR logic at coordinator.py:473 |
| State reconciliation loop | Partial | RESILIENCE-003 one-shot retry (coordinator.py:671), not periodic |
| Reliable service call with retry | Partial | `_safe_service_call` has timeout but zero retries (see #14) |
| Sensor unavailability grace period | Unaddressed | All-unavail → false vacancy (see #8) |
| Stuck-on sensor detection | Unaddressed | See #9 |
| HA restart state persistence | Unaddressed | See #11 |
| Digest alert mode | Unaddressed | Not yet implemented |
| Network health monitoring | Unaddressed | No congestion detection or adaptive timeouts |

---

## P0 — Must Fix

1. **TransitionDetector `@callback` on async functions** (transitions.py:94, 342) — `@callback` decorator on `async def` methods means coroutines are never awaited. Handlers silently do nothing. Entire transition detection pipeline non-functional.

2. **Database occupancy logging dead** (coordinator.py:718 vs :662) — `_last_occupied_state` is updated at line 662, then the DB logging block at line 718 compares `data[STATE_OCCUPIED] != self._last_occupied_state` which is always False. Occupancy events never reach the database. Breaks predictions, occupancy percentages, and all historical analysis. Fix: use saved `was_occupied` variable or move logging inside the first conditional block.

3. **Sleep protection bypass broken** (automation.py:218) — `should_execute_automation()` passes `STATE_OCCUPIED` (a bool that's True for the entire occupancy duration) as `motion_detected` param to `can_bypass_sleep_mode()`. Counter increments every refresh (~30s) instead of on actual motion events. Sleep protection bypassed in ~90s instead of 3 deliberate motions. Fix: pass `STATE_MOTION_DETECTED` instead of `STATE_OCCUPIED`.

4. **Shared space auto-off has Bug Class #4** (automation.py:912-918, 882-906) — `_shared_space_turn_off_all()` and `_warning_flash()` call `light.*` services on mixed entity lists containing switches. Same bug fixed in `_control_lights_exit()` but not applied here. Fix: add domain separation like `_control_lights_exit()`.

5. **`_calculate_device_counts` NoneType crash** (coordinator.py:396-425) — `self.hass.states.get(light).state` crashes with AttributeError when entity removed from registry but still in area. Same for fans (403), switches (408), covers (421-424). Fix: add `state is not None` guard.

6. **No entry automation debouncing** (coordinator.py:473-513) — Single spurious sensor `on` blip triggers full entry automation. No minimum dwell time, no cross-sensor validation, no rapid on/off filtering. Root cause of bug report "Dimension 1: Spurious Motion Triggers." This is the #1 real-world reliability problem. Fix: add configurable debounce window (e.g., sensor must be on for 2+ consecutive update cycles or 5+ seconds).

7. **4-hour failsafe bypassed by stuck sensors** (coordinator.py:553-567) — RESILIENCE-001 requires `not motion_detected and not presence_detected and not occupancy_detected`. A single mmWave sensor stuck "on" prevents the failsafe from ever firing. This is the most common real-world sensor failure mode and is the root cause of bug report "Dimension 2: Unreliable Shutoff." Promoted from P1 → P0.

8. **Camera person-sensor override defeats failsafe** (coordinator.py:569-591) — *NEW*. The v3.5.0 camera integration reads existing Frigate/UniFi person detection binary sensors (e.g., `binary_sensor.kitchen_person_detected`) to extend room occupancy. This check runs AFTER the 4-hour failsafe clears occupancy. If a camera person sensor is stuck on (common with Frigate false positives), it immediately re-asserts `data[STATE_OCCUPIED] = True`, defeating the failsafe every cycle. Fix: camera override should respect the failsafe (skip if failsafe just fired), or add stuck-sensor detection for camera person sensors too.

## P1 — Should Fix

9. **`asyncio.sleep(3)` blocks coordinator** (coordinator.py:673) — RESILIENCE-003 retry blocks entire `_async_update_data()` for 3 seconds on every vacancy transition. Delays all sensor updates, environmental logging, and energy calculations. Fix: use `self.hass.async_create_task()` with delayed callback.

10. **All-sensors-unavailable → false vacancy** (coordinator.py:333-345, 472-513) — Zigbee coordinator restart makes all sensors unavailable simultaneously. `_is_sensor_on()` returns False for unavailable, room immediately starts vacancy countdown. No grace period. Fix: if all sensors in a room transition to unavailable within the same cycle, hold previous occupancy state for 60s.

11. **Automation config stale after options change** (coordinator.py:150, automation.py:132) — `RoomAutomation` captures config dict at init. Options flow changes update `entry.options` but automation's `self.config` is a stale snapshot. Light lists, fan lists, sleep settings, shared space settings all stale until full reload. Fix: make automation read from entry.options directly, or rebuild on options update.

12. **HA restart loses all occupancy state** (coordinator.py:105-108) — `_last_motion_time`, `_last_occupied_state`, `_became_occupied_time` all in-memory. Restart causes false off→on cycle in every occupied room. Fix: persist critical state to HA's restore state infrastructure or query URA database for recent occupancy on startup.

13. **No service call retry for critical operations** (automation.py:142-173) — `_safe_service_call` wraps with timeout and error handling but never retries. Return value is never checked by any caller (fire-and-forget). Bug report requested "exponential backoff" and "guaranteed delivery for critical calls." Fix: add retry loop with backoff for critical ops; callers should check return value. Promoted from P2 → P1.

14. **RESILIENCE-003 retry doesn't account for leave-on exit action** (coordinator.py:672-692) — *NEW*. Post-exit verification checks if lights/switches/fans are still on and retries exit automation. But if `CONF_EXIT_LIGHT_ACTION` is `LIGHT_ACTION_LEAVE_ON`, lights are intentionally left on. The retry fires `handle_occupancy_change(False)` again unnecessarily. Fix: check exit light action before retry.

15. **Energy accumulator hardcoded 30s interval** (coordinator.py:634-637) — *NEW*. `elapsed_hours = 30 / 3600` assumes exactly 30-second update cycles. Event-driven sensor changes can trigger updates at 1-2s intervals during active use, or longer during idle. Energy readings drift. Fix: calculate actual elapsed time from last reading.

## P2 — Nice to Have

16. **Temperature hysteresis not implemented** (automation.py:694) — Fan turns on at threshold, off at threshold-0.1. No dead band → rapid cycling. Fix: configurable hysteresis band (e.g., on at 80, off at 78).

17. **Warning flash timing fragile** (automation.py:868) — Exact `minute == 55` match. If update cycles straddle the minute boundary, warning either fires multiple times or is missed entirely. Fix: track "already warned" flag per warning period.

18. **CRITICAL log level for startup banners** (coordinator.py:99, automation.py:127) — Informational messages using CRITICAL. Pollutes error monitoring. Fix: use INFO.

19. **`_turn_on_regular_lights` domain separation gap** (automation.py:314-320) — *NEW*. `_control_lights_entry()` computes `actual_lights` and `switches_as_lights` at lines 314-317 but only uses them for logging. These filtered lists are not passed to `_turn_on_regular_lights()`. If the helper doesn't do its own separation, this is another Bug Class #4 on the entry path.

20. **No concurrent `_async_update_data` protection** (coordinator.py) — *NEW*. The `asyncio.sleep(3)` yields control. If a sensor state change fires during those 3 seconds, `async_refresh()` may start a concurrent update, racing on `_last_occupied_state` and automation logic. Verify HA's DataUpdateCoordinator serializes refreshes; if not, add a guard.

---

## Priority Summary

| Priority | Count | Impact |
|---|---|---|
| P0 | 8 | System broken: stuck rooms, dead transitions, bypass bugs, crashes |
| P1 | 7 | Reliability: false vacancy, stale config, no retry, state loss |
| P2 | 5 | Polish: hysteresis, timing, log levels, edge cases |
| **Total** | **20** | |

## Recommended Fix Order

1. **#2 + #3** (DB logging + sleep bypass) — One-line fixes, immediate correctness improvement
2. **#5** (NoneType crash) — Crash prevention, simple guard
3. **#1** (transitions @callback) — Remove decorator, restore transition pipeline
4. **#4 + #19** (Bug Class #4) — Domain separation audit across all service call sites
5. **#6** (debounce) — Root cause of spurious motion (bug report Dimension 1)
6. **#7 + #8** (failsafe bypasses) — Root cause of stuck rooms (bug report Dimension 2)
7. **#9** (sleep(3) blocking) — Move to async task
8. **#10** (unavailable grace period) — Zigbee restart resilience
9. **#13** (service call retry) — Network resilience layer
10. **#11 + #12** (config staleness, state persistence) — Larger refactors
