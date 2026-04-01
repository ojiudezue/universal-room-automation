# v3.21.0 — Coordinator Hardening (Cycle D)

**Date:** 2026-03-31
**Tests:** 44 new
**Review tier:** Feature (2 adversarial reviews + fixes)

## What Changed

All 7 domain coordinators hardened for restart resilience, startup ordering,
sensor recovery, alert persistence, and per-room AI automation control.

### D1: Energy DB Restore with Timeout
- 11 sequential `_restore_*` methods now wrapped in `asyncio.wait_for(timeout=15s)`
- If DB is locked on restart, coordinator starts with defaults instead of hanging
- Sequential execution preserved (review fix: avoids concurrent DB contention)

### D2: Coordinator Startup Ordering
- Presence Coordinator sets `asyncio.Event` after initial house state inference
- HVAC waits for Presence ready event (10s timeout, falls back to default state)
- Eliminates race where HVAC reads uninitialized house state on restart

### D3: Safety Sensor Recovery
- When sensor transitions unavailable→available, hazard state is re-evaluated
  with the current reading (was only clearing rate history)
- Handles binary, numeric (CO/CO2/TVOC), temperature, and humidity sensors

### D4: NM Alert State Persistence
- `get_persistence_state()` / `restore_persistence_state()` on Notification Manager
- NMDiagnosticsSensor now has RestoreEntity to persist alert/cooldown/dedup state
- COOLDOWN state reset to IDLE on restore (tick task can't be restarted)
- RestoreEntity restore skipped if NM already recovered from DB (dual-path guard)

### D5: Security Expected Arrival Expiry
- Verified already handled: dict comprehension filters expired arrivals (`v > now`)
- No fix needed (false positive in review findings)

### D6: Energy Observation Mode RestoreEntity
- `EnergyObservationModeSwitch` now has RestoreEntity
- Observation mode state survives HA restarts

### D7: AI Automation Per-Room Toggle
- New `AiAutomationSwitch` per room (default: enabled, `mdi:robot` icon)
- When OFF, AI rules and automation chaining don't execute for that room
- Safety/security signal handlers always fire regardless of toggle (review fix)
- AI toggle also respects ManualMode (review fix)

## Review Findings Fixed
- 4 HIGH: sequential restore (not parallel), Event on loop, COOLDOWN→IDLE, NM dual-restore guard
- 3 MEDIUM: safety/security always fire, ready_event lifecycle, AI respects manual_mode

## Files Changed
- `domain_coordinators/energy.py` — restore timeout wrapper
- `domain_coordinators/presence.py` — ready event
- `domain_coordinators/hvac.py` — wait for presence
- `domain_coordinators/safety.py` — sensor recovery re-evaluation
- `domain_coordinators/notification_manager.py` — persistence methods
- `domain_coordinators/manager.py` — dependency comment
- `sensor.py` — RestoreEntity on NMDiagnosticsSensor
- `switch.py` — RestoreEntity on EnergyObservationMode + new AiAutomationSwitch
- `coordinator.py` — AI toggle method + gating
