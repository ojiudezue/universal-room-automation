# v3.17.1 — Guest Detection Fix + HVAC Zone Merging + Sleep Vacancy

**Hotfix release** addressing critical guest detection false positives causing HVAC flapping.

## Changes

### Critical: Guest Detection False Positives
- **Removed WiFi VLAN from census unidentified formula** — now camera-only (`unidentified = camera_unrecognized`). WiFi guest count still tracked in sensor attributes for diagnostics but no longer inflates `unidentified_count`.
- Root cause: WiFi VLAN detection had too many false positives from persistent infrastructure/IoT devices that passed hostname filters. This kept house state stuck on "guest" for 27+ hours, causing HVAC preset flapping (home↔away every 5 minutes).

### Critical: HVAC Zone Merging for Shared Thermostats
- **Multiple URA zones sharing a thermostat now merge rooms** instead of the second zone being silently dropped. Fixes Master Suite occupancy being invisible to HVAC when it shares the StudyB Zone 1 thermostat with Entertainment zone.
- Previously, zone discovery skipped any zone whose thermostat was already assigned to another zone. Now rooms from all zones sharing a thermostat are merged into a single HVAC zone.

### HVAC: Sleep Vacancy Override
- **ZI vacancy override now applies during sleep hours** — vacant zones get "away" instead of staying on "sleep". Matches expectation: occupied zones → sleep preset, vacant zones → away preset.

### HVAC: Thermostat Mode Restoration (from develop)
- Thermostats stuck in "off" mode are restored to "heat_cool" during decision cycles (skips zones mid-AC-reset).
- Override arrester revert now restores hvac_mode before setting preset.

## Files Changed
- `camera_census.py` — WiFi removed from unidentified formula
- `domain_coordinators/hvac.py` — ZI sleep vacancy + mode restoration
- `domain_coordinators/hvac_zones.py` — Zone merging for shared thermostats
- `domain_coordinators/hvac_override.py` — Revert mode restoration
- `quality/tests/test_census_v2.py` — Updated 3 test assertions

## Test Results
- 146 census/HVAC tests pass
- 452 total tests pass (1 pre-existing failure in data_pipeline, unrelated)
