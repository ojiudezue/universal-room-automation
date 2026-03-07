# URA v3.7.9 — EntityCategory Categorization + Review Fixes

## Summary

Properly categorizes all energy coordinator entities into HA entity categories
(primary/diagnostic/config) and fixes 3 bugs found during code review.

## Changes

### sensor.py
- **EntityCategory.DIAGNOSTIC** added to 7 sensor classes:
  - `EnergyCircuitAnomalySensor`
  - `EnergyGeneratorStatusSensor`
  - `EnergyForecastAccuracySensor`
  - `EnergyBatteryFullTimeSensor`
  - `EnergyPoolOptimizationSensor`
  - `EnergyEVChargingStatusSensor`
  - `EnergyHVACConstraintSensor`
- 18 primary state sensors correctly left without entity_category

### binary_sensor.py
- **EntityCategory.DIAGNOSTIC** added to `EnergyEnvoyAvailableBinarySensor`
- `EnergyL1ChargerBinarySensor` left as primary (no category)

### domain_coordinators/energy_forecast.py
- **Fixed day-of-week off-by-one**: `record_actual_consumption()` now uses
  yesterday's weekday (consumption data is from yesterday since it's called
  at midnight rollover)

### domain_coordinators/energy_billing.py
- **Fixed docstring**: `_get_net_power` docstring corrected from "watts" to "kW"

### domain_coordinators/energy_battery.py
- **Fixed custom solar threshold ordering**: `classify_solar_day()` now sorts
  custom thresholds descending before iterating, preventing lower thresholds
  from matching first

### const.py
- VERSION bumped to 3.7.9
