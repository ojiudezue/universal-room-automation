# v3.6.17 — Automation Health Sensor

**Date:** 2026-03-02
**Cycle:** Enhancement — automation observability

---

## Summary

Adds a per-room `AutomationHealthSensor` that surfaces the internal decision-making state of the automation engine. Previously, room automation was opaque — only the last trigger, action, and time were visible. The new sensor exposes debounce state, stuck sensor detection, failsafe timers, grace periods, service call health, exit verification results, and sleep bypass counters.

## New Entity

**`sensor.ura_<room>_automation_health`** (diagnostic, per-room)

### Primary State (rollup)

| State | Meaning |
|-------|---------|
| `normal` | No active conditions — automation operating normally |
| `debouncing` | Motion detected but waiting for 2s confirmation |
| `grace_hold` | All sensors unavailable — holding previous occupancy state |
| `failsafe` | 4-hour failsafe has fired — room forcibly vacated |
| `stuck_sensor` | One or more sensors flagged as stuck (>4h continuous on) |

### Attributes

#### Tier 1 — Direct debugging

| Attribute | Type | Description |
|-----------|------|-------------|
| `session_duration_minutes` | float | Current occupancy session length |
| `failsafe_remaining_minutes` | float/null | Minutes until 4h failsafe fires |
| `failsafe_fired` | bool | Whether failsafe has triggered this session |
| `stuck_sensors` | list | Sensors flagged stuck with entity_id and on_hours |
| `stuck_sensor_count` | int | Count of stuck sensors |
| `debounce_active` | bool | Whether entry debounce is pending |
| `debounce_elapsed_seconds` | float/null | Seconds since motion first detected |
| `grace_active` | bool | Whether sensor unavailability grace is holding |
| `grace_remaining_seconds` | float/null | Grace period seconds remaining |

#### Tier 2 — Operational health

| Attribute | Type | Description |
|-----------|------|-------------|
| `sleep_bypass_count` | int | Motion count toward sleep mode bypass threshold |
| `service_calls_today` | int | Total service calls made today |
| `service_failures_today` | int | Failed service calls today (timeouts + errors) |
| `last_exit_verify_result` | str/null | Last exit verification outcome |
| `last_exit_verify_time` | str/null | ISO timestamp of last exit verification |

Exit verify results: `confirmed` (devices off), `retried` (devices were still on, retried), `skipped_reoccupied` (room re-occupied during delay), `retry_failed` (retry also failed).

## Changes

### `sensor.py`
- Added `AutomationHealthSensor` class
- Registered in room entity list

### `coordinator.py`
- Added `_last_exit_verify_result` and `_last_exit_verify_time` tracking variables
- `_delayed_exit_verify()` now records outcome for each run

### `automation.py`
- Added `_service_calls_today`, `_service_failures_today`, `_service_call_reset_date` tracking
- `_safe_service_call()` increments counters on each call and failure
- Daily counter reset on date change

## Tests

590 existing tests pass. No regressions.
