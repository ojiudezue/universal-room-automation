# v4.0.6 — Diagnostic: Event-Driven Listener Verification

## Problem
Room automations responding with 7-26 second delays (matching the 30s poll cycle) instead of sub-second event-driven response. Confirmed via temperature sensor timestamp comparison: hardware sensor updates 26 seconds before URA sensor — proving rooms are on polling fallback instead of event-driven mode.

## Changes
Added WARNING-level diagnostic logging to `coordinator.py` to capture:
1. **Listener setup**: What sensors are tracked, whether `async_track_state_change_event` returns a valid unsub
2. **Callback invocation**: Whether the `sensor_state_changed` callback actually fires when hardware sensors change state

These diagnostics will appear in HA logs regardless of logging configuration and will definitively show whether:
- Event listeners are being set up during `async_config_entry_first_refresh`
- The callbacks are firing on sensor state changes
- Or rooms are silently falling back to 30s polling

## Verification
- **Live:** Check HA System Log after restart for `"sensors to track"` and `"Event-driven mode active"` WARNING messages for each room
- **Live:** Trigger a sensor (walk into a room) and check for `"EVENT-DRIVEN callback fired"` WARNING messages
- **If callbacks fire:** Problem is downstream (refresh mechanism)
- **If callbacks don't fire:** Problem is in listener registration or HA event system
- **If no setup messages:** `async_config_entry_first_refresh` is not completing

## Temporary
This is a diagnostic release. WARNING-level logs will be removed once the root cause is identified and fixed.
