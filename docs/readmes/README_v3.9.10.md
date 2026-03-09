# URA v3.9.10 — HVAC Override Arrester Startup Audit + Zone Sensor Race Fix

## Overview
Fixes two race conditions in the HVAC subsystem: zone sensors showing unavailable after restart, and stale manual thermostat overrides surviving restarts undetected.

## Changes

### HVAC Override Arrester Startup Audit
- **Problem**: The arrester is purely event-driven — it only detects override *transitions*. On HA restart, all in-memory grace/compromise timers are lost. If a zone was overridden before restart, the arrester never fires again (no state change event).
- **Fix**: Added `async_startup_audit()` to OverrideArrester. On the first decision cycle (after climate entities have reported state), scans all zones for `preset_mode == "manual"` with setpoints outside seasonal tolerance.
- **Behavior**: Stale overrides get the severe grace period (2 min) since the user already had their original grace window. Uses seasonal defaults for the current house state as expected setpoints. Sends NM alert on detection.
- **Race condition mitigation**: Audit runs in the first `_async_decision_cycle()` (not `async_setup()`), after `update_all_zones()` has populated climate entity states. Avoids Bug Class #5 (startup race).

### HVAC Zone Sensor Race Fix (v3.9.9)
- **Problem**: Zone status and zone preset sensors showed "unavailable" after every restart. Sensor creation at startup depended on `coordinator_manager` being initialized first — a race condition between config entry setup order.
- **Fix**: Zone sensor creation now reads zone IDs directly from the Zone Manager config entry (static config data), no longer depends on the coordinator object being ready.

## Files Changed
- `domain_coordinators/hvac_override.py` — `async_startup_audit()` method (~75 lines)
- `domain_coordinators/hvac.py` — Deferred audit call in first decision cycle
- `sensor.py` — Zone sensor creation reads from config entry instead of coordinator

## Design Notes
- All overrides detected at startup use severe grace (2 min) regardless of delta magnitude, since the override already persisted through a restart
- The audit only fires once per startup (`_startup_audit_done` flag)
- Energy coast tolerance bonus is respected during the audit
- Lambda closures use default-argument binding (`z=zone, p=target_preset`) for correct loop capture
- `_cancel_zone_timers()` called before scheduling for defensive consistency
