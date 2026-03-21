# v3.17.0 — HVAC Zone Intelligence

**Date:** 2026-03-20
**Tests:** 1169 passed (53 new)
**Planning:** `docs/PLANNING_v3.17.0_HVAC_ZONE_INTELLIGENCE.md`

---

## Summary

Makes HVAC zone-aware, person-aware, and solar-aware. Unoccupied zones get `away` preset after a grace period. Excess solar is banked as thermal mass. Arriving persons trigger per-zone pre-conditioning. Runtime is duty-cycle limited during energy constraints. A toggleable switch lets users disable Zone Intelligence for system-managed ramp control.

## Deliverables

### D1: Zone Vacancy Management
- Two-tier grace period: 15 min normal, 5 min energy constrained
- Vacant zones overridden to `away` preset (only from `home` — sleep/away/vacation unaffected)
- Vacancy sweep turns off URA-configured lights and fans
- Manual preset bypass for vacant zones (RH3 fix)

### D2: Zone-Specific Pre-Conditioning
- **Weather pre-cool** (existing, now zone-aware): occupied zones only
- **Solar banking** (new): SOC >= 95%, net-exporting > 500W, forecast >= 85F, off-peak 10-14h. Banks ALL zones. Floor protection: max(72F, target_temp_low + 2F deadband)
- **Pre-arrival** (new): person-routed via geofence. Fans activated as comfort bridge. 30-min timeout with fan cleanup

### D3: Person-to-Zone Mapping
- Config-based `CONF_PERSON_PREFERRED_ZONES` dict
- Geofence arrival dispatches `SIGNAL_PERSON_ARRIVING`
- HVAC maps person -> preferred zones for pre-arrival conditioning
- BLE confirmation clears pre-arrival state

### D4: Zone Presence State Machine
7 states with priority ordering: `sleep` > `runtime_limited` > `pre_arrival` > `pre_conditioning` > `occupied` > `vacant` > `away`

### D5: Duty Cycle Enforcement
- Rolling 20-min window with actual elapsed time tracking
- Coast mode: 75% max runtime. Shed mode: 50% max runtime
- Skip during sleep (RH4). Reset only on normal -> constrained transition

### D6: Max-Occupancy-Duration Failsafe
- 8-hour continuous occupancy -> treat as stale sensor -> force away
- Skip during sleep (RH4). Resets when zone goes vacant

### D7: Diagnostic Sensors
- `sensor.ura_hvac_zone_intelligence`: count of away zones, per-zone state breakdown, vacancy sweeps today
- Extended zone status attributes: `zone_presence_state`, `runtime_duty_cycle_pct`, `continuous_occupied_hours`

## Zone Intelligence Toggle
- **Entity:** `switch.ura_hvac_zone_intelligence`
- **ON (default):** Full Zone Intelligence — vacancy, duty cycle, failsafe, solar banking, pre-arrival
- **OFF:** System-managed — thermostats control their own ramp, URA only sets presets from house state. Weather pre-cool stays active
- Persists across restarts (RestoreEntity)

## Review Fixes Applied
- Re-entrancy guard on decision cycle (asyncio.Lock)
- Actual elapsed time for runtime accumulation (was hardcoded 300s)
- Pre-arrival fan cleanup on timeout
- Solar banking fires every cycle while conditions met (was one-shot per day)
- Duty cycle percentage clamped to 100% with fixed window denominator
- Fire-and-forget task tracking + teardown cancellation
- Duty cycle reset only on normal -> constrained (not coast <-> shed bounce)
- `async_schedule_update_ha_state` for thread safety
- manifest.json version sync

## Files Changed
- `domain_coordinators/hvac_const.py` — new constants (D1-D6)
- `domain_coordinators/hvac_zones.py` — ZoneState fields + timestamp tracking
- `domain_coordinators/hvac.py` — vacancy, duty cycle, failsafe, person arriving, state machine, ZI toggle
- `domain_coordinators/hvac_predict.py` — zone-specific pre-conditioning, solar banking
- `domain_coordinators/signals.py` — SIGNAL_PERSON_ARRIVING
- `domain_coordinators/presence.py` — dispatches person arriving signal
- `__init__.py` — constructor wiring for new params
- `sensor.py` — HVACZoneIntelligenceSensor
- `switch.py` — HVACZoneIntelligenceSwitch
- `const.py` + `manifest.json` — version 3.17.0
- `quality/tests/test_hvac_zone_intelligence.py` — 53 tests
