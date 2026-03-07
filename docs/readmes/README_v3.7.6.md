# URA v3.7.6 — Energy Coordinator Fixes + Observation Mode

## Summary

Fixes critical Envoy connectivity false alarm, adds monthly solar thresholds,
renames rate sensors, adds Delivery Rate sensor, and introduces Observation Mode.

## Changes

### energy_const.py
- **Fixed SOC entity**: `DEFAULT_BATTERY_SOC_ENTITY` corrected from
  `sensor.encharge_aggregate_battery_percentage` (doesn't exist) to
  `sensor.envoy_202428004328_battery`. This was causing `envoy_available = False`
  and the Envoy showing as "Disconnected" on the device page.
- **Monthly solar thresholds**: Replaced flat thresholds (excellent=60 kWh) with
  per-month P25/P50/P75 thresholds derived from actual Enphase production data
  (50 panels, 19.4kW DC). June "excellent" is now 136+ kWh, December 83+ kWh.
- **Custom override support**: Added `SOLAR_CLASS_MODE_AUTOMATIC` / `SOLAR_CLASS_MODE_CUSTOM`
  config keys for future config flow dropdown.

### energy_battery.py
- **`classify_solar_day()`**: Now uses monthly percentile thresholds by default.
  Supports custom absolute thresholds when `solar_classification_mode="custom"`.

### energy_forecast.py
- **Forecast retry**: `generate_prediction()` now retries if `predicted_production_kwh`
  was null (e.g., Solcast not ready at HA startup). Previously, a null on first
  attempt locked the prediction as null for the entire day.

### sensor.py
- **Renamed**: "Current Energy Rate" -> "Actual Energy Rate" (entity ID unchanged)
- **New sensor**: `EnergyDeliveryRateSensor` — shows delivery + transmission rate
  per kWh ($0.042476). Entity: `sensor.ura_energy_delivery_rate`

### switch.py
- **New toggle**: `EnergyObservationModeSwitch` — when ON, all Energy Coordinator
  sensors compute normally but no control actions are executed (battery mode changes,
  pool speed, EV pause/resume all skipped). Entity: `switch.ura_energy_observation_mode`

### energy.py
- **Observation mode**: `_observation_mode` flag gates all action execution in
  `_async_decision_cycle()`. Property with setter for switch entity access.
- **New accessor**: `delivery_rate` property returns combined delivery + transmission $/kWh.

### const.py
- VERSION bumped to 3.7.6
