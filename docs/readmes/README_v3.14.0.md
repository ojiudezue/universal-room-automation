# v3.14.0: Energy Consumption Foundation Fix + Forecast Sensors

**Date:** 2026-03-13
**Branch:** develop -> main
**Tests:** 1061 passed (24 new)

## Problem

The Envoy has a **net-consumption CT** (`production CT, net-consumption CT, storage CT`). With this CT mode, `lifetime_energy_consumption` and `energy_consumption_today` accumulate **net grid import**, NOT total home consumption. The code in `_maybe_reset_daily()` treated the lifetime delta as total consumption, producing near-zero values on sunny days (0.026 kWh vs actual ~30 kWh), making forecast accuracy permanently "unknown" and poisoning the prediction baseline.

## Solution

Derive true daily consumption from 5 independent lifetime sensors using the energy conservation formula:

```
actual_consumption = grid_import + (solar_produced - solar_exported) + (battery_discharged - battery_charged)
```

The `(solar_produced - solar_exported)` term includes solar that charged the battery, so `battery_charged` must be subtracted to avoid double-counting.

## Changes

### `domain_coordinators/energy.py`
- **Imports:** Added `DEFAULT_LIFETIME_BATTERY_CHARGED_ENTITY`, `DEFAULT_LIFETIME_BATTERY_DISCHARGED_ENTITY`, `DEFAULT_LIFETIME_NET_EXPORT_ENTITY`, `DEFAULT_LIFETIME_NET_IMPORT_ENTITY`, `DEFAULT_LIFETIME_PRODUCTION_ENTITY`
- **Snapshot fields:** Added 5 new `_lifetime_*_snapshot` attributes (production, net_import, net_export, battery_charged, battery_discharged)
- **Getter methods:** Added `_get_lifetime_production()`, `_get_lifetime_net_import()`, `_get_lifetime_net_export()`, `_get_lifetime_battery_discharged()`, `_get_lifetime_battery_charged()`
- **`_maybe_reset_daily()`:** Rewrote to use 5-sensor derived formula with battery_charged correction. Falls back to legacy delta when derived sensors unavailable. Added negative delta guard for Envoy reboot resilience. Resets/seeds all 6 snapshots independently.
- **`_save_daily_snapshot()`:** Now passes `solar_production_kwh` to DB
- **`_crosscheck_consumption()`:** Re-seeds all 6 snapshots (not just legacy) on Envoy reboot detection
- **`_log_energy_history_snapshot()`:** Added `rooms_energy_total` to data dict
- **`_get_rooms_energy_total()`:** New method — sums `energy_today` from room coordinators (via `UniversalRoomCoordinator` isinstance check)
- **`predicted_import_kwh`:** New property — `consumption - production`
- **`predicted_consumption_kwh`:** New property — delegates to predictor

### `domain_coordinators/energy_forecast.py`
- **`_estimate_battery_full_time()`:** Consumption-aware (deducts remaining home consumption from available solar) + piecewise SOC-based taper (3.5 kW < 80%, 2.5 kW 80-90%, 1.5 kW > 90%)

### `sensor.py`
- **`EnergyForecastTodaySensor`:** Renamed display name from "Energy Forecast Today" to "Predicted Net Energy" (unique_id unchanged)
- **`EnergyForecastedImportSensor`:** New sensor — predicted grid draw (battery-aware: accounts for solar timing, battery buffering, reserve SOC). Attributes: consumption, production, battery capacity/SOC/reserve, solar window hours, battery full time
- **`EnergyForecastedConsumptionSensor`:** New sensor — predicted total home consumption

### `quality/tests/test_energy_consumption.py` (new)
- 27 tests covering: derived formula with battery_charged, double-count prevention, sunny day scenario, legacy fallback, independent seeding, solar_production passthrough, negative delta guard (single + full reboot), non-positive consumption guard, piecewise battery taper (7 scenarios including after-8-PM), battery-aware grid import (sunny/cloudy/moderate/no-battery/zero-solar/none), rooms_energy_total, first-boot scenario

## Code Review Findings Fixed
- **CRITICAL:** Formula was missing `- battery_charged` term (would overcount by ~10-15 kWh/day)
- **CRITICAL:** `_get_rooms_energy_total` was iterating domain coordinators instead of room coordinators
- **HIGH:** Crosscheck re-seed only updated legacy snapshot, not the 5 new ones
- **HIGH:** No negative delta guard — Envoy reboot could persist negative values to DB
- **HIGH:** Battery full time used single taper rate — 36% optimistic at low SOC

## Post-Deploy

```sql
DELETE FROM energy_daily WHERE date <= '2026-03-13';
```

## Verification

1. Check renamed sensor: `sensor.ura_energy_coordinator_energy_forecast_today` → "Predicted Net Energy"
2. Check new sensors: `sensor.ura_energy_coordinator_forecasted_energy_import`, `sensor.ura_energy_coordinator_forecasted_consumption`
3. Check `energy_history` table: `rooms_energy_total` column populated
4. Wait for midnight → check `energy_daily`: `consumption_kwh` ~30-40 kWh, `solar_production_kwh` populated
5. After 1+ days: `sensor.ura_energy_coordinator_forecast_accuracy` transitions from "unknown" to real %
6. Battery full time sensor gives later (more realistic) estimates
