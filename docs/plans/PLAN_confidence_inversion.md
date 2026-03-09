# Plan: Invert Confidence Calculation — Scanners-First Lookup

**Status:** Pending (after v3.6.18 stabilizes)
**Priority:** Performance optimization

## Problem

`_calculate_confidence()` iterates all Bermuda entities (~100) to find distance sensors, then matches them against area scanners. This is backwards — we know the area, so we should find scanners first and do direct state lookups.

## Approach

### Current flow (v3.6.18)
1. Iterate all Bermuda entities → find `distance_to_` sensors for person (~100 entities)
2. Find scanners in area (~20-30 devices across BLE integrations)
3. For each distance sensor, check if scanner name matches area scanner
4. Score confidence from matching scanners

### Proposed flow
1. Find scanners in area (2-4 devices, already efficient after v3.6.18)
2. Get person's BLE device name from `device_tracker.{private_ble_device}` entity — canonical name Bermuda uses in sensor IDs
3. For each area scanner, construct `sensor.{ble_device_name}_distance_to_{scanner_name}` directly
4. `hass.states.get(sensor_id)` — O(1) dict lookup per scanner
5. Score confidence from results

### Auto-enable handling
- Direct state lookup won't find disabled sensors (they have no state)
- On first run per person, do a one-time Bermuda entity scan to auto-enable any disabled sensors
- Track enabled persons in a set (`_ble_sensors_enabled: set[str]`) to skip subsequent runs
- This is acceptable because auto-enable only matters once per sensor lifecycle

### Getting the BLE device name
- `private_ble_device` config gives the device tracker entity (e.g., `device_tracker.iphone_ezinne`)
- The object_id portion (`iphone_ezinne`) is what Bermuda uses as the prefix in distance sensor entity IDs
- Extract via `entity_id.split(".")[-1]`

## Files to modify

| File | Change |
|------|--------|
| `person_coordinator.py` | Rewrite `_calculate_confidence()` to scanners-first + direct lookup |
| `person_coordinator.py` | Add `_ble_device_prefix()` helper to extract canonical name from private_ble entity |
| `person_coordinator.py` | Add one-time auto-enable scan with tracking set |

## Verification

1. Confidence values match pre-change for all tracked persons
2. No regression in room detection accuracy
3. Auto-enable still works for newly added persons/scanners
4. `sensor.ura_<person>_likely_next_room` updates in <1s (vs >10s before)
