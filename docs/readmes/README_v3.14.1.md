# v3.14.1: Battery-Aware Grid Import Prediction

**Date:** 2026-03-13
**Branch:** develop -> main
**Tests:** 1064 passed (27 in energy consumption suite)

## Problem

The `predicted_import_kwh` sensor was computing `consumption - production` (= -121.7 kWh), which is just the negative of the net forecast sensor — completely redundant and not actionable. What matters is: **how much will we actually draw from the grid?**

## Solution

Battery-aware grid import model that accounts for solar timing and battery buffering:
- **Daytime (sunrise→sunset):** Solar covers consumption; surplus charges battery
- **Nighttime (sunset→sunrise):** Battery discharges to cover consumption; grid covers shortfall
- **Reserve SOC:** Battery can't discharge below reserve level

On a sunny day (150 kWh solar, 28 kWh consumption, 40 kWh battery), predicted grid import = **0 kWh** — the battery easily covers overnight consumption. On a cloudy day (10 kWh solar, 30 kWh consumption), the model correctly predicts significant grid draw.

## Changes

### `domain_coordinators/energy.py`
- **`predicted_import_kwh`:** Rewrote from simple `consumption - production` to battery-aware model with solar window estimation, daytime/nighttime split, and reserve SOC floor
- **`_get_solar_window_hours()`:** New method — reads `sun.sun` entity to get sunrise/sunset window in hours (fallback: 12h)

### `domain_coordinators/energy_forecast.py`
- **`BATTERY_TOTAL_CAPACITY_KWH_FALLBACK`:** Changed from 15.0 to 40.0 kWh (actual system capacity)

### `sensor.py`
- **`EnergyForecastedImportSensor`:** Renamed from "Forecasted Energy Import" to "Predicted Grid Import". Enhanced attributes: battery_capacity_kwh, battery_soc_pct, reserve_soc_pct, solar_window_hours

### `quality/tests/test_energy_consumption.py`
- 6 grid import tests: sunny day (0 import), cloudy day (20 kWh), moderate solar, no-battery scenario, zero solar, None propagation
