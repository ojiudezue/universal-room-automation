# v3.17.3 — HVAC Zone ID Collision Guard

## Changes

### Zone ID collision guard
- `_zone_id_from_thermostat()` now checks for collisions before assigning a zone ID
- If two thermostats both contain "zone_1" in their name, the second auto-numbers to the next available slot
- Thermostats without "zone_N" in their entity name auto-number sequentially (starting from 0)
- Ensures no duplicate zone IDs regardless of thermostat naming convention

## Files Changed
- `domain_coordinators/hvac_zones.py` — collision guard in `_zone_id_from_thermostat()`
