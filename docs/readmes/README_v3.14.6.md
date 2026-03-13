# v3.14.6: Sensor State Clarity Fix

**Date:** 2026-03-13
**Branch:** develop -> main

## Problem

Three energy sensors showed misleading states:

1. **Battery Full Time = "unknown"**: Prediction was cached while Envoy was offline (SOC unavailable). Once Envoy came back and battery hit 100%, the cached prediction couldn't update — sensor stayed "unknown" instead of "already_full". Further: when Envoy goes briefly offline again, the sensor reverted to "unknown" even though last known state was "already_full".

2. **Forecast Accuracy = "unknown"**: All historical accuracy data was filtered out in v3.14.5 (poisoned by net-consumption CT bug). With 0 samples, accuracy = 0.0 → sensor returns None → "unknown". No way for the user to tell if this is a bug or a data gap.

3. **Energy Import/Export Today**: User questioned whether these should be direct Envoy readings. Confirmed they ARE based on live Envoy net power readings (accumulated each decision cycle by the CostTracker billing module), not predictions. Values are correct.

## Changes

### `domain_coordinators/energy.py`
- **`battery_full_time` property**: Three-tier evaluation: (1) live SOC check — if >= 99, return "already_full"; (2) predictor's cached estimate; (3) hold cache — retains last known value through Envoy outages. `_last_battery_full_time` field caches any non-None result so brief Envoy drops don't cause the sensor to show "unknown".

### `sensor.py`
- **`EnergyForecastAccuracySensor`**: Added `extra_state_attributes` with `samples`, `status` ("learning" vs "active"), `adjustment_factor`, and `last_eval_date`. When accuracy is "unknown", users can now see `status: learning, samples: 0` instead of guessing.

### `quality/tests/test_energy_consumption.py`
- Added 2 tests for live SOC fallback (SOC full → "already_full", SOC low → None). 30 tests total.
