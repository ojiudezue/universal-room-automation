# URA v3.7.2 — Consumption Tracking Fix (Q1)

## Summary

Fixes the critical consumption tracking accuracy issue (Q1 from ENERGY_QUESTIONS_v3.7.0.md).
Daily consumption now uses Envoy's lifetime_energy_consumption CT measurement instead of
the incorrect `import_kwh + export_kwh` formula.

## Changes

### Accurate daily consumption via Envoy lifetime delta
- **Old**: `actual_kwh = import_kwh + export_kwh` — wrong (double-counts exports, misses solar self-consumed)
- **New**: `actual_kwh = delta(lifetime_energy_consumption) * 1000` — true home consumption from Envoy CT
- Envoy's consumption CT measures everything flowing to the home load (grid + solar + battery)
- Lifetime values are monotonically increasing in MWh, delta gives exact daily kWh
- Snapshot stored at each day boundary, robust to timing and restarts

### Battery capacity from Envoy entity
- Replaced hardcoded `BATTERY_TOTAL_CAPACITY_KWH = 15.0` with live read from
  `sensor.envoy_202428004328_battery_capacity` (Wh, converted to kWh)
- Falls back to 15.0 kWh if entity unavailable

### New Envoy entity constants
Added to `energy_const.py`:
- `DEFAULT_LIFETIME_CONSUMPTION_ENTITY` — total home consumption (MWh, lifetime)
- `DEFAULT_LIFETIME_PRODUCTION_ENTITY` — total solar production (MWh, lifetime)
- `DEFAULT_LIFETIME_NET_IMPORT_ENTITY` — net grid import (MWh, lifetime)
- `DEFAULT_LIFETIME_NET_EXPORT_ENTITY` — net grid export (MWh, lifetime)
- `DEFAULT_LIFETIME_BATTERY_CHARGED_ENTITY` — battery charged (MWh, lifetime)
- `DEFAULT_LIFETIME_BATTERY_DISCHARGED_ENTITY` — battery discharged (MWh, lifetime)
- `DEFAULT_BATTERY_CAPACITY_ENTITY` — battery capacity (Wh)
