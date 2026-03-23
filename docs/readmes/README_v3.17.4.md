# v3.17.4 — HVAC Restart Resilience

## Changes

### Skip preset changes during "arriving" state
- HVAC coordinator now returns early from `_apply_house_state_presets()` while house state is "arriving"
- "Arriving" is transient after HA restart or geofence arrival — presence sensors haven't settled yet
- Prevents unnecessary preset churn (away→home→away) that was occurring on every restart
- Thermostats hold their previous preset until house state transitions to a stable state

## Files Changed
- `domain_coordinators/hvac.py` — early return during arriving state
