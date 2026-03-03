# v3.6.23: Zone Thermostat Configuration

**Date:** 2026-03-03
**Type:** Feature
**Plan:** `docs/plans/PLAN_zone_thermostat_config.md`

## Summary

Adds a direct thermostat entity setting to zone configuration, replacing non-deterministic room traversal for HVAC zone control.

## Changes

### New: Zone HVAC config step
- New "Zone HVAC" menu option in zone configuration
- Climate entity selector for `CONF_ZONE_THERMOSTAT`
- When set, zone uses this entity directly for occupancy-based preset switching
- When not set, falls back to existing room-traversal behavior (backward compatible)

### Auto-populate
- When a room's climate entity is configured and the room belongs to a zone, the zone thermostat is auto-populated if not already set
- Only triggers on initial configuration, not when user has cleared the field

### Architecture
- `_get_zone_config()` helper reads zone-specific config from the ZM zones dict
- `_get_zone_climate_entity()` checks zone-level config first, then falls back to room traversal
- Preset UI intentionally omitted — the HVAC Coordinator (C6) will supersede current preset logic

## Files Changed
- `const.py` — Add `CONF_ZONE_THERMOSTAT` constant
- `config_flow.py` — Add `zone_hvac` menu option + step; auto-populate in room climate step
- `aggregation.py` — Modify `_get_zone_climate_entity()`; add `_get_zone_config()` helper
- `strings.json` — Add zone_hvac step strings
- `translations/en.json` — Mirror strings
