# URA v3.7.10 — Energy Coordinator Config Flow

## Summary

Adds entity selectors and solar classification mode to the Energy Coordinator
options flow. Weather entity inherits from house settings if not configured
at the EC level.

## Changes

### config_flow.py
- **Expanded `async_step_coordinator_energy`** with new fields:
  - Weather entity selector (pre-populated from house config if set)
  - EVSE Garage A/B power sensor selectors
  - L1 charger smart plug multi-selector
  - Solar day classification mode dropdown (Automatic/Custom)
  - Four custom solar threshold inputs (Excellent/Good/Moderate/Poor kWh)

### __init__.py
- **Weather entity fallback**: If not set in EC config, reads from
  integration/house entry's `weather_entity` setting
- **EVSE config**: Builds proper nested dict structure matching
  `EVChargerController` expectations (switch, power, energy_today, etc.)
  with user power entity overrides
- **Smart plug entities**: Passes configured or default L1 charger switches
- **Solar classification**: Passes mode and custom thresholds to
  `EnergyCoordinator` → `BatteryStrategy`

### domain_coordinators/energy.py
- Constructor accepts `solar_classification_mode` and
  `custom_solar_thresholds` params, forwards to `BatteryStrategy`

### strings.json
- Added labels and descriptions for all 9 new config fields

### const.py
- VERSION bumped to 3.7.10
