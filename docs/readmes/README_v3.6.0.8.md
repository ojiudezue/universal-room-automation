# Universal Room Automation v3.6.0.8 — Temperature Unit Normalization

**Release Date:** 2026-03-01
**Previous Release:** v3.6.0.7
**Minimum HA Version:** 2024.1+

---

## Summary

Fixes temperature unit mismatch: Safety Coordinator thresholds are in Fahrenheit but sensors may report in Celsius. A Celsius sensor reporting 10°C (50°F) was compared directly against the freeze risk threshold (≤ 35), triggering a false HIGH freeze risk alert. Now normalizes all temperature readings to °F before threshold comparison.

---

## Problem

`_process_sensor()` read the raw state value via `float(state_value)` and passed it directly to threshold checks. All temperature thresholds (freeze ≤ 35/40/45, overheat ≥ 100/105/115) are in Fahrenheit. When a sensor reports in Celsius:

- 10°C (normal board temp) → compared as "10" → triggers freeze_risk HIGH (10 ≤ 35)
- 24°C (76°F room temp) → compared as "24" → triggers freeze_risk LOW (24 ≤ 45)

Every Celsius sensor in the system would generate false freeze risk alerts.

## Fix

New `_normalize_temperature()` method:
1. Reads the entity's `unit_of_measurement` attribute from HA state
2. Converts °C → °F using standard formula: `value * 9/5 + 32`
3. Caches the unit per entity_id to avoid repeated state reads
4. Defaults to °F if unit can't be determined (preserves pre-patch behavior)

Normalization is applied **before** both rate-of-change recording and threshold checks, so all downstream processing sees consistent Fahrenheit values.

### Why only temperature?

- **Humidity:** Always reported in `%` — no unit ambiguity
- **CO/CO2:** Always in ppm — no unit ambiguity
- **TVOC:** Always in ppb — no unit ambiguity
- **Temperature** is the only sensor type with real-world unit variation (°F in US installs, °C in EU/international)

---

## Files Changed

| File | Change |
|------|--------|
| `domain_coordinators/safety.py` | `_normalize_temperature()` method; unit normalization in `_process_sensor()`; `_sensor_units` dict in `__init__` and `async_teardown()` |
| `const.py` | Version stamp 3.6.0.8 |
| `manifest.json` | Version stamp 3.6.0.8 |

---

## How to Verify

1. After restart, Celsius sensors should no longer trigger false freeze risk alerts
2. `sensor.invisoutlet_b7d0_temperature` (reports °C) should show normalized °F value in hazard details
3. A sensor reporting 24°C should be evaluated as 75.2°F — well above freeze thresholds
4. Rate-of-change thresholds still function correctly (now in °F units)
5. Fahrenheit sensors continue to work unchanged (no double-conversion)
