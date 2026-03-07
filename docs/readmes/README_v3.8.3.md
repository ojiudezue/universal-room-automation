# v3.8.3 — Override Arrester + AC Reset (H2)

## What Ships

### Override Arrester
Event-driven detection of manual thermostat overrides via `async_track_state_change_event` on all zone climate entities. Detects when preset changes to "manual" (Bryant WiFi thermostats set this when someone adjusts temperature at the thermostat or via the app).

**Two-tier severity response:**
- **Severe (>3F deviation):** 2-minute grace period, then immediate revert to original preset
- **Normal (1-3F deviation):** 5-minute grace period, then 30-minute compromise (halfway between override and original), then full revert

**Key design decisions:**
- Compares override against actual old setpoints from the state change event, not hardcoded seasonal defaults
- Energy-aware: widens tolerance by 1F during energy "coast" mode
- Sends Notification Manager alerts for both severity tiers
- All timers properly cancelled on teardown and on re-override

### AC Reset
Polling-based stuck cycle detection, checked every 5 minutes in the HVAC decision cycle:
- Detects when HVAC is actively cooling/heating but temperature hasn't reached setpoint
- After 10 minutes of stuck operation: off -> 60s wait -> restore original mode
- Max 2 resets per zone per day
- Skips zones with active overrides
- NM alert on each reset

### New Sensor
`sensor.ura_hvac_coordinator_override_frequency` — diagnostic sensor showing:
- `overrides_today`: total override count across all zones
- `ac_resets_today`: total AC reset count
- `active_overrides`: currently active override count
- `active_compromises`: zones currently in compromise period

### Bug Fix
Fixed `hvac_zones.py` legacy path logging bug: `len(rooms)` referenced undefined variable `rooms` instead of `room_names`.

## New Files
- `domain_coordinators/hvac_override.py` — `OverrideArrester` class (~620 lines)

## Modified Files
- `domain_coordinators/hvac_const.py` — override/reset constants
- `domain_coordinators/hvac_zones.py` — `last_override_direction`, `last_stuck_detected` fields + legacy log fix
- `domain_coordinators/hvac.py` — OverrideArrester integration (setup, teardown, decision cycle)
- `sensor.py` — `HVACOverrideFrequencySensor`
- `const.py` — version bump to 3.8.3
