# v3.11.1 — Solar Forecast Sensor Config UI

**Date**: 2026-03-12
**Scope**: Config flow patch

---

## Summary

Adds solar forecast sensor entity selectors to the Energy Coordinator config flow. Allows users to configure which forecast sensors to use instead of assuming Solcast defaults. Users with alternative solar forecast integrations can now point to their own sensors.

## Changes

- **config_flow.py**: Added 3 entity selectors for solar forecast today, tomorrow, and remaining-today sensors
- **strings.json + translations/en.json**: Labels and descriptions for the 3 new fields

## New Config Fields

| Field | Label | Default |
|---|---|---|
| `energy_solcast_today_entity` | Solar Forecast Today | `sensor.solcast_pv_forecast_forecast_today` |
| `energy_solcast_tomorrow_entity` | Solar Forecast Tomorrow | `sensor.solcast_pv_forecast_forecast_tomorrow` |
| `energy_solcast_remaining_entity` | Solar Forecast Remaining Today | `sensor.solcast_pv_forecast_forecast_remaining_today` |

These are optional — if not set, the system uses the Solcast defaults. Any sensor providing kWh values will work.
