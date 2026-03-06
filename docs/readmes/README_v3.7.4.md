# URA v3.7.4 — Envoy Sensor + Energy Config Flow

## Summary

Adds Envoy availability binary sensor for dashboard visibility and NM alerting,
plus the missing Energy Coordinator entry in the Coordinator Manager config flow.

## Changes

### Envoy Available binary sensor (binary_sensor.py)
- `binary_sensor.ura_energy_coordinator_envoy_available`
- device_class: connectivity, icon: mdi:solar-panel
- On when Envoy is responding (SOC + storage mode readable)
- Off when Envoy is unavailable (Energy Coordinator holding state)
- Attributes: `unavailable_count`, `last_available`
- Registered on "URA: Energy Coordinator" device

### Energy Coordinator config flow (config_flow.py, strings.json, translations/en.json)
- Added `coordinator_energy` to Coordinator Manager options menu
- New options step with 3 configurable fields:
  - Battery Reserve SOC (slider, 5-100%, default 20%)
  - Billing Cycle Start Day (1-28, default 23)
  - Decision Interval (1-30 min, default 5)
- Menu label and step descriptions in both strings.json and translations/en.json
