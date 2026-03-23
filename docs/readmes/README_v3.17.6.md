# v3.17.6 — Zone ID Regex Fix

## Changes

### Fix zone ID extraction regex for thermostat entity names
- `\bzone` word boundary never matched because `_` before "zone" is a word character in regex
- All three thermostats were falling through to auto-numbering (zone_0, zone_1, zone_2) instead of extracting physical zone numbers
- Result: zone_3 sensor showed "unknown", Back Hallway zone invisible to dashboards, zone_0 discovered but had no sensor entity
- Fixed regex to `(?:^|[_.\s])zone[_\s]?(\d+)` — matches zone preceded by underscore, dot, whitespace, or start-of-string
- Still correctly rejects false positives like "ozone_1"

## Files Changed
- `domain_coordinators/hvac_zones.py` — regex fix in `_zone_id_from_thermostat()`
