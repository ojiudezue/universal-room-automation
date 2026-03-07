# URA v3.7.12 — Sunrise Refresh, DB-Backed Accuracy, Temperature Regression

## Summary

Forecast improvements: predictions refresh at sunrise with fresh Solcast data,
accuracy history persists across restarts via DB, and temperature regression
learns consumption patterns after 30+ days of paired data.

## Changes

### domain_coordinators/energy_forecast.py
- **`DailyEnergyPredictor`**: Refactored `generate_prediction()` → delegates to
  `_do_prediction()` for reuse by sunrise refresh
- **`refresh_at_sunrise()`**: Re-generates prediction within 30 min after sunrise
  with updated Solcast data (once per day)
- **`_get_sunrise()`**: Reads sunrise time from `sun.sun` entity
- **`_estimate_consumption()`**: Temperature regression (70% regression, 30%
  day-of-week baseline) when 30+ days of paired data exist, falls back to
  fixed multiplier bands otherwise
- **`set_temp_regression()`**: Accepts learned base/coeff from DB fit
- **`_get_current_temperature()`**: Reads temperature from weather entity
- **`AccuracyTracker.restore_from_db()`**: Loads recent accuracy records from
  `energy_daily` rows to restore rolling accuracy and adjustment factor

### domain_coordinators/energy.py
- **`async_setup()`**: Now calls `_restore_accuracy_from_db()` and
  `_fit_temp_regression()` on startup
- **`_restore_accuracy_from_db()`**: Loads last 30 days of accuracy data from DB,
  restores `AccuracyTracker` state and Bayesian adjustment factor
- **`_fit_temp_regression()`**: Simple linear regression on historical
  consumption-temperature pairs (y = base + coeff * |temp - 72°F|)
- **`_async_decision_cycle()`**: Added sunrise refresh call after daily prediction
- **`_save_daily_snapshot()`**: Now persists predicted_consumption_kwh,
  prediction_error_pct, adjustment_factor, avg_temperature to DB
- **`_maybe_reset_daily()`**: Fixed variable scoping for accuracy data passed
  to daily snapshot (forecast/accuracy_result initialized before conditional)

### database.py
- **`energy_daily` migration**: Added 4 new columns — predicted_consumption_kwh,
  avg_temperature, prediction_error_pct, adjustment_factor
- **`log_energy_daily()`**: Updated signature to accept accuracy/temperature fields
- **`get_energy_daily_recent()`**: Returns last N days of accuracy data for restore
- **`get_energy_temp_pairs()`**: Returns consumption-temperature pairs for regression

### const.py
- VERSION bumped to 3.7.12
