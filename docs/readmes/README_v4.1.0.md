# v4.1.0 — B4 Layer 1: Energy Attribution + Power Profiles

**Date:** April 17, 2026
**Scope:** B4 Energy Integration — Config + Data Foundation
**Tests:** 30 new (1478 total passing)

## Summary

First layer of B4 (Bayesian Energy Integration). Adds multi-energy sensor support,
zone/house device power/energy configuration, 4-tier energy attribution model,
and room power profile learning. No Bayesian dependency — ships standalone.

## Changes

### D1: Multi-Energy Sensor Config (Room Level)
- `CONF_ENERGY_SENSORS` (plural, `multiple=True`) replaces `CONF_ENERGY_SENSOR`
- Backward-compatible migration: old singular configs auto-wrapped in list
- Room coordinator sums deltas from all configured energy sensors
- Per-sensor baselines for accurate daily delta tracking

### D1b: Zone + House Device Sensor Config
- Zone Manager: new `zone_energy` options step with `CONF_ZONE_POWER_SENSORS` / `CONF_ZONE_ENERGY_SENSORS`
- Coordinator Manager: new `CONF_HOUSE_DEVICE_POWER_SENSORS` / `CONF_HOUSE_DEVICE_ENERGY_SENSORS` for EV chargers, pool pumps, water heaters
- Whole-house sensors upgraded to `multiple=True` with singular-to-plural migration

### D1c: 4-Tier Energy Attribution Model
- `sensor.ura_energy_coverage_delta` upgraded from 2-tier (whole house - rooms) to 4-tier:
  - Rooms (sum of all room energy sensors)
  - Zones (sum of zone energy sensors — HVAC circuits)
  - House Devices (EV, pool, water heater)
  - Unattributed (whole house minus all attributed)
- New attributes: `zones_total`, `house_devices_total`, `attributed_total`, `attribution_coverage_pct`

### D2: Room Power Profile Learning
- `RoomPowerProfile` class in `energy_forecast.py`
- EMA (exponential moving average) by room, time bin (6 periods), day type (weekday/weekend)
- Standby watts learned from NIGHT-bin vacant observations (not hardcoded)
- Cold start threshold: 20 samples per cell before profile is trusted
- DB persistence: `room_power_profiles` table with save/load methods
- `get_status()` reports rooms tracked, mature cells, standby coverage

## Files Changed

| File | Lines | Description |
|------|-------|-------------|
| const.py | +15 | New energy sensor constants |
| config_flow.py | +158 | Multi-select pickers, zone_energy step, migration helpers |
| coordinator.py | +48 | Multi-energy sensor tracking with per-sensor baselines |
| aggregation.py | +222 | WholeHouse plural upgrade, 4-tier attribution model |
| energy_forecast.py | +185 | RoomPowerProfile class |
| database.py | +66 | room_power_profiles table + save/load |
| strings.json | +43 | New labels and descriptions |
| translations/en.json | +43 | English translations |
| test_b4_energy_integration.py | +30 tests | Full coverage of L1 deliverables |

## What's Next (Layer 2)
- Occupancy weighting toggle (switch entity on Energy Coordinator device)
- DailyEnergyPredictor Bayesian integration
- Battery strategy occupancy awareness
