# URA v3.6.24 — Config UX Streamlining

**Date:** 2026-03-03
**Type:** Enhancement
**Scope:** config_flow.py, strings.json, translations/en.json

## Summary

Streamlines the room configuration flow by reducing the number of steps for typical rooms from 8 to 5-6. Adds area-based entity pre-population, conditional sub-steps, and auto-detection of light capabilities.

## Changes

### Area Entity Pre-Population
- New `_get_area_entities(area_id, domain, device_class)` helper discovers entities in a Home Assistant area using entity_registry + device_registry area_id fallback
- When an area is selected in room_setup, entity fields in sensors, devices, climate, and energy steps are pre-filled with matching entities
- Only applies to initial setup — options flow reconfigure uses existing saved values

### Conditional Sub-Steps
- **night_light_detail**: Only shown when night lights are selected in devices step. Contains brightness/color fields previously in the devices step.
- **cover_behavior**: Only shown when covers are selected. Contains cover type, entry/exit actions, timing fields previously in automation_behavior step.
- **fan_speeds**: Only shown when fan control is enabled in climate step. Contains low/med/high temperature thresholds previously in climate step.

### Auto-Detect Light Capabilities
- New `_detect_light_capabilities(entity_ids)` reads `supported_features` bitmask from light entities
- Maps: SUPPORT_COLOR (16) → full, SUPPORT_COLOR_TEMP (2) → brightness, SUPPORT_BRIGHTNESS (1) → brightness
- Pre-fills CONF_LIGHT_CAPABILITIES default (user can override)

### Skip Hints
- sleep_protection, energy, and notifications steps now show hints about submitting unchanged to use defaults

### Flow Routing
```
Before: room_setup → sensors → devices → automation_behavior → climate → sleep_protection → energy → notifications
After:  room_setup → sensors → devices → [night_light_detail?] → [cover_behavior?] → automation_behavior → climate → [fan_speeds?] → sleep_protection → energy → notifications
```

## Regression Safety
- Options flow completely untouched — all fields remain accessible for reconfigure
- _data accumulator pattern preserved in all sub-steps
- Area pre-population only on initial setup, never overwrites saved options
- All 622 tests pass
