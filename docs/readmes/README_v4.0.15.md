# v4.0.15 — HVAC FanController Toggle + Occupancy Gate

**Date:** 2026-04-12

## Summary

Adds `switch.ura_hvac_coordinator_fan_control` toggle to enable/disable temperature-based ceiling fan management. Fixes bug where fans activated in empty rooms by moving the occupancy gate before temperature triggers.

## Problem

HVAC FanController turned on ceiling fans based purely on temperature delta from thermostat setpoint, with no occupancy check on activation. This caused fans to run in empty rooms, wasting electricity and conflicting with external HA automations (e.g., Office Leave Automation turning off Study A fan, then FanController re-enabling it every 5 minutes).

Additionally, FanController was the only HVAC sub-feature without a dedicated enable/disable toggle.

## Changes

### Fan Control Toggle
- New switch: `switch.ura_hvac_coordinator_fan_control` (default ON, backward compatible)
- Config flow boolean in HVAC Coordinator step
- Gates `FanController.update()` — when OFF, `turn_off_all_managed()` turns off any running fans
- RestoreEntity with deferred retry for startup race
- Observable via `fan_control_enabled` attribute on HVAC mode sensor

### Occupancy Gate
- Moved occupancy check BEFORE temperature/fan_assist triggers in `_evaluate_temp_fan()`
- Unoccupied + fan off → stays off (no activation in empty rooms)
- Unoccupied + fan on → vacancy hold (600s) then off
- Occupied → proceeds to temperature triggers as before

### State Sync
- Each update cycle syncs internal `room_fan.is_on` with actual HA entity state
- Prevents stale tracking if external automations changed fan state

## Review Findings Fixed
- **CRITICAL**: Dead code (unreachable return) after occupancy gate refactor
- **HIGH**: Missing `translations/en.json` entry for config flow label
- **HIGH**: Fans left running when toggle disabled — added `turn_off_all_managed()` cleanup
- **MEDIUM**: Startup race — added deferred restore with 5s retry
- **LOW**: Pre-arrival fan bridge bypass documented at predictor call site
- **LOW**: State drift on re-enable — added entity state sync at top of update loop

## Files Modified (9)
- `domain_coordinators/hvac_const.py`
- `domain_coordinators/hvac.py`
- `domain_coordinators/hvac_fans.py`
- `switch.py`
- `config_flow.py`
- `__init__.py`
- `strings.json`
- `translations/en.json`
- `quality/tests/test_hvac_fan_control.py` (6 tests)

## Tests
- 6 new tests: occupancy gate, vacancy hold, occupied activation, toggle default
- Full suite: 1684 passed (pre-existing failures unchanged)
