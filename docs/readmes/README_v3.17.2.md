# v3.17.2 — HVAC Zone ID Alignment

## Changes

### HVAC zone IDs match thermostat physical zone numbers
- Zone discovery now extracts the zone number from the thermostat entity name (regex `zone_N`) instead of auto-incrementing in config iteration order.
- `climate.thermostat_bryant_wifi_studyb_zone_1` → `zone_1` (was `zone_2`)
- `climate.up_hallway_zone_2` → `zone_2` (was `zone_3`)
- `climate.back_hallway_zone_3` → `zone_3` (was `zone_1`)
- Dashboard mapping updated to 1:1 (no more cross-wiring).
- Falls back to auto-increment for thermostats without zone numbers in entity name.

## Files Changed
- `domain_coordinators/hvac_zones.py` — `_zone_id_from_thermostat()` helper
- `dashboard-v3/src/components/tabs/HVACTab.tsx` — Zone mapping simplified
