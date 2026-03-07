# v3.9.1 — Forecast Temp Fix

## Summary
Hotfix for HVAC constraint sensor showing wrong forecast temperatures.
`forecast_high_temp` was displaying current temperature (from predictor snapshot)
instead of actual daily forecast high. `forecast_low_temp` was always null because
modern HA (2024.3+) removed the `forecast` attribute from weather entities.

## Root Cause
`_get_forecast_temps()` read `_prediction_temperature` from the energy predictor,
which stores the **current** temperature at prediction time — not the forecast high.
It also tried to read `ws.attributes.get("forecast")` which no longer exists in
modern HA weather entities (deprecated in 2024.3, replaced by `weather.get_forecasts`
service).

## Fix
- Replaced sync `_get_forecast_temps()` with async `_update_forecast_temps()` that
  calls the `weather.get_forecasts` service to get daily forecast data.
- Results cached in `_cached_forecast_high` / `_cached_forecast_low` instance vars.
- Called once per decision cycle (every 5 minutes) before constraint evaluation.
- `hvac_constraint` property now reads cached values instead of calling the method.

## Files Changed
- `domain_coordinators/energy.py` — async forecast fetch, cached temps
- `const.py` — version bump to 3.9.1
- `manifest.json` — version bump to 3.9.1
