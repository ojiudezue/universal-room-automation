# Universal Room Automation v3.6.0.5 — Safety Coordinator False Positives Fix

**Release Date:** 2026-03-01
**Previous Release:** v3.6.0.4
**Minimum HA Version:** 2024.1+

---

## Summary

Fixes two Safety Coordinator bugs: (1) rate-of-change thresholds applied to CO2/CO/TVOC sensors causing false overheat, water_leak, and hvac_failure hazards, and (2) entity locations showing device names instead of room names because device-level area_id wasn't checked.

---

## Changes

### 1. Rate-of-Change Filter Fix

**Bug:** `RateOfChangeDetector.check_thresholds()` only filtered for temperature and humidity sensor types using name substring matching. When called with `sensor_type="co2"`, neither filter matched, so ALL rate thresholds were checked against CO2 ppm data. Normal CO2 fluctuations (tens of ppm/30min) easily exceeded temperature/humidity thresholds, producing false hazards:
- CO2 rise ≥10 → "overheat" (temperature_rise_extreme threshold)
- CO2 rise ≥20 → "water_leak" (humidity_rise threshold)
- CO2 drop ≤-5 → "hvac_failure" (temperature_drop threshold)

**Fix:** Early return in `check_thresholds()` for any sensor_type other than "temperature" or "humidity". CO2/CO/TVOC sensors have their own dedicated numeric thresholds and should not trigger rate-of-change alerts designed for environmental sensors.

### 2. Device Area Lookup for Location Resolution

**Bug:** `_classify_entity()` and Source 1 discovery only checked `entity.area_id` from the entity registry. In HA, most entities don't have an explicit entity-level area — they inherit their area from the parent device. So `entity.area_id` was None, the location fell through to `_location_from_entity_id()` which parsed the entity_id string (e.g., "Apollo Air 1 A87420"), and entities in URA room areas weren't matched by Source 1 discovery.

**Fix:** When `entity.area_id` is None, look up the entity's `device_id`, get the device from the device registry, and use `device.area_id`. Applied to both Source 1 discovery loop and `_classify_entity` location resolution.

---

## Files Changed

| File | Change |
|------|--------|
| `domain_coordinators/safety.py` | Early return in `check_thresholds` for non-temp/humidity; device area_id lookup in discovery and classify |

---

## How to Verify

1. After restart, `sensor.ura_safety_coordinator_safety_active_hazards` should show `0` (no false CO2 hazards)
2. Safety status should be "normal" (not "warning" from CO2 false positives)
3. If Apollo Air is in a URA room area (e.g., Kitchen), hazards should show the room name, not "Apollo Air 1 A87420"
4. Check logs for "Safety sensor discovery:" — sensor counts should reflect proper room-scoped discovery via device areas
