# v3.8.1 — HVAC Zone Discovery Fix + Thermostat Configuration

## What Ships

### Zone Discovery Fix
`hvac_zones.py` `async_discover_zones()` was only reading legacy `ENTRY_TYPE_ZONE` config entries (pre-v3.6.0). Since v3.6.0, zones are stored in the Zone Manager entry's `zones` dict. Fixed to read from both sources.

### Changes
1. **Zone Manager support**: Reads zones from `{**entry.data, **entry.options}.get("zones", {})` on the Zone Manager entry
2. **Entry ID → room name conversion**: Zone Manager stores room references as config entry IDs; these are now converted to room names so `update_room_conditions()` can match them against room coordinators
3. **Thermostat dedup**: `seen_thermostats` set prevents duplicate HVAC zones when the same thermostat appears in multiple sources
4. **Unresolved entry ID warning**: Logs a warning if a zone references a room entry ID that no longer exists
5. **Legacy path fix**: Legacy `ENTRY_TYPE_ZONE` entries also get entry ID → room name conversion

### Thermostat Configuration
Set `zone_thermostat` on Zone Manager options for:
- Back Hallway → `climate.back_hallway_zone_3`
- Entertainment → `climate.thermostat_bryant_wifi_studyb_zone_1`
- Upstairs → `climate.up_hallway_zone_2` (already configured)

## Modified Files
- `domain_coordinators/hvac_zones.py` — Zone Manager zone discovery, entry ID conversion, dedup
- `const.py` — version bump to 3.8.1
