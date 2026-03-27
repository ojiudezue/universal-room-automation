# v3.18.1–v3.18.4 — Production Hotfixes

**Date:** 2026-03-26
**Tests:** 1166 passing (54 pre-existing)
**Review:** Post-hoc (hotfixes deployed for production urgency, reviewed after)

---

## v3.18.1 — @callback on 15 Signal Handlers

**Root cause:** HA runs non-`@callback` handlers in executor thread pool. 15 signal handlers (census, person tracking, egress events, midnight resets) were missing the decorator. Every state write from these handlers raised `RuntimeError` — **2,310 occurrences** per restart on HA 2026.3/Python 3.14.

**Fix:** Added `@callback` to 9 handlers in sensor.py and 6 in aggregation.py.

**Files:** `sensor.py`, `aggregation.py`

---

## v3.18.2 — _find_zone_manager_entry on OptionsFlow

**Root cause:** `_find_zone_manager_entry()` was defined on ConfigFlow (line 287) but not OptionsFlow. The Climate & HVAC sub-menu called it, raising `AttributeError` — making HVAC settings impossible to save. Pre-existing bug preserved by v3.18.0 refactoring.

**Fix:** Added the method to `UniversalRoomAutomationOptionsFlow`.

**Files:** `config_flow.py`

---

## v3.18.3 — Diagnostic Logging for Config Flow Saves

**Purpose:** Added `try/except` with `_LOGGER.exception()` to `async_step_automation_behavior` and `async_step_basic_setup` save paths. Captures the actual exception when "Unknown error occurred" appears on room config saves. Temporary diagnostic — remove after root cause found.

**Files:** `config_flow.py`

---

## v3.18.4 — DB Locked, Energy Jitter, Sensor Log Spam

### Database locked on startup
- New `_db()` async context manager in `database.py` wraps ALL 69 connections with `timeout=30.0` + `PRAGMA busy_timeout=30000`
- Previously 30 of 47 logging methods lacked timeout — failed immediately when 25+ rooms wrote concurrently at startup

### Energy sensor not strictly increasing
- `round(current, 4)` in `EnergyTodaySensor.native_value` eliminates float jitter (0.1 Wh resolution)
- Prevents HA "not strictly increasing" warnings for `state_class=TOTAL_INCREASING` sensors

### Sensor unavailability log spam
- Per-sensor "is unavailable" messages downgraded from WARNING to DEBUG
- "All N sensors unavailable" remains at WARNING (genuinely significant)
- Reduces 134+ warning lines per hour to near zero in normal operation

**Files:** `database.py`, `sensor.py`, `coordinator.py`

---

## Deferred Items

| Item | Status | Notes |
|------|--------|-------|
| Config flow "first save error" on non-HVAC sub-menus | INVESTIGATING | v3.18.3 diagnostic logging deployed, awaiting debug log with traceback |
| Remove diagnostic logging from config_flow.py | PENDING | Remove after config flow root cause found |
| Bug Class #22 added to QUALITY_CONTEXT.md | NOT DONE | @callback on signal handlers — add in next cycle |
| Extend Bug Class #1 for OptionsFlow method verification | NOT DONE | Add in next cycle |
| Post-hoc review of all 4 hotfixes | DONE | `docs/reviews/code-review/v3.18.1-v3.18.4_hotfixes.md` |

## Process Notes

4 hotfixes in one day indicates insufficient pre-deploy testing for the v3.18.0 mega-release. Key lessons:
1. Thread-safety audit (v3.18.3/v3.18.0) changed the wrong layer — should have checked `@callback` on handlers, not just which state-write method to call
2. Code refactoring in OptionsFlow must verify all `self.*` calls resolve on the OptionsFlow class
3. DB connection configuration must be centralized (single factory method), not scattered across 47 methods
