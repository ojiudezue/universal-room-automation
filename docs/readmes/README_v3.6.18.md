# v3.6.18 — Person Coordinator Performance Fix

**Date:** 2026-03-02
**Cycle:** Performance — person tracking efficiency

---

## Summary

Fixes a performance bottleneck in the Person Coordinator where `_calculate_confidence()` and `_get_area_scanners()` scanned the entire HA entity/device registry (5000+ entities, 400+ devices) every 30-second update cycle. Replaced with targeted lookups that only scan Bermuda and BLE integration entries.

## Problem

The `sensor.ura_<person>_likely_next_room` sensor was taking >10 seconds to update for frequently-home persons (e.g., Ezinne). Root cause: three full registry scans per confidence calculation:

1. **`_calculate_confidence()`** — iterated ALL entities to find Bermuda distance sensors
2. **`_get_area_scanners()`** — iterated ALL devices to find BLE scanners in an area
3. **`_auto_enable_distance_sensors()`** — duplicate full entity scan for auto-enable

## Fix

### `_calculate_confidence()` (lines 548-569)
- **Before:** `for entity_id, entity_entry in ent_reg.entities.items()` — 5000+ iterations
- **After:** `hass.config_entries.async_entries("bermuda")` → `er.async_entries_for_config_entry()` — scans only Bermuda entities (~50-100)
- Auto-enable logic folded inline, eliminating the duplicate scan

### `_get_area_scanners()` (lines 668-685)
- **Before:** `for device in dev_reg.devices.values()` — 400+ device iterations
- **After:** Iterates only devices from shelly/esphome/bluetooth/bermuda config entries using `dr.async_entries_for_config_entry()`

### Removed: `_auto_enable_distance_sensors()`
- Method deleted entirely — auto-enable is now handled inline during the distance sensor lookup in `_calculate_confidence()`

## Impact

- ~50-100x reduction in entities scanned per confidence calculation
- ~10-20x reduction in devices scanned per area scanner lookup
- Most visible improvement for persons who are home frequently (more BLE updates → more confidence calculations)

## Tests

590 existing tests pass. No regressions.
