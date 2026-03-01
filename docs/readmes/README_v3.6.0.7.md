# Universal Room Automation v3.6.0.7 — Config-First Discovery

**Release Date:** 2026-03-01
**Previous Release:** v3.6.0.6
**Minimum HA Version:** 2024.1+

---

## Summary

Rewrites Safety Coordinator sensor discovery from entity-registry scanning to config-first. Instead of scanning all HA entities and filtering inward (which pulled in freezer sensors, appliance temps, and random devices), discovery now reads ONLY the exact sensors configured in URA room entries and SC global config.

---

## Problem

v3.6.0.5 added device area_id lookup to discovery, which caused the sensor scan to pull in ALL entities from devices in URA room areas — including freezer temperature sensors, outlet power readings, and other non-safety devices. `sensors_monitored` jumped to 123 with irrelevant devices.

v3.6.0.6 added appliance blocklists and embedded-sensor checks, but the fundamental approach was wrong: starting from the full HA entity registry and filtering down will always have edge cases.

## Solution

Config-first discovery. Two sources, no entity registry scanning:

**Source 1: URA Room Config Entries**
- Reads `CONF_TEMPERATURE_SENSOR`, `CONF_HUMIDITY_SENSOR`, `CONF_WATER_LEAK_SENSOR` from each room config
- Sensor type is KNOWN from the config key — no device_class guessing needed
- Location is KNOWN from the room config — no area_id lookup needed

**Source 2: SC Global Config**
- Reads 5 explicit sensor lists: smoke, leak, AQ, temperature, humidity
- These are sensors the user explicitly added for devices not in any URA room
- Location resolved via device area_id → URA room mapping

**No appliance filtering needed** because the user already curated the sensor list in config.

---

## Dead Code Removed

Four methods that were part of the old entity-registry scanning approach are now unused and have been removed:

| Method | Purpose (now obsolete) |
|--------|----------------------|
| `_collect_global_entities()` | Collected global config entity IDs (absorbed into new `_discover_sensors()`) |
| `_classify_entity()` | Classified entities by device_class/entity_id pattern matching |
| `_is_embedded_sensor()` | Checked if temp/humidity sensor was embedded in appliance device |
| `_discover_sensors_fallback()` | Fallback discovery via state machine scanning |

---

## Files Changed

| File | Change |
|------|--------|
| `domain_coordinators/safety.py` | Rewrote `_discover_sensors()` config-first; added `_resolve_global_location()`, `_classify_aq_sensor()`; removed 4 dead methods |
| `const.py` | Version stamp 3.6.0.7 |
| `manifest.json` | Version stamp 3.6.0.7 |

---

## How to Verify

1. After restart, `sensors_monitored` count should match URA room sensors + SC global sensors (not 123)
2. No freezer, appliance, or random device sensors in monitoring
3. Room-configured sensors (temperature, humidity, water leak) should show correct room names
4. Global sensors should resolve location via device area → URA room mapping
5. Safety status should be "normal" with 0 active hazards (no false positives)

---

## Discovery Strategy

```
Before (v3.6.0.3-v3.6.0.6):
  Entity Registry (all entities) → filter by area → filter by device_class → filter appliances → safety sensors
  Result: 123 sensors, false positives, random devices

After (v3.6.0.7):
  URA Room Config (temp, humidity, leak per room) + SC Global Config (5 sensor lists) → safety sensors
  Result: Only user-configured sensors, no false positives
```
