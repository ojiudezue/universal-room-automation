# URA v3.7.11 — DB-Backed Billing + Daily Energy Snapshots

## Summary

Persists daily energy billing data to SQLite. Billing cycle totals now survive
HA restarts. Predicted bill uses DB actuals. Learning label shown while
accumulating data.

## Changes

### database.py
- **New table `energy_daily`**: date (PK), import_kwh, export_kwh, import_cost,
  export_credit, net_cost, consumption_kwh, solar_production_kwh
- **`log_energy_daily()`**: INSERT OR REPLACE daily snapshot
- **`get_energy_daily_for_cycle()`**: SUM rows for a billing cycle date range

### domain_coordinators/energy_billing.py
- **`get_yesterday_totals()`**: Captures daily accumulators before midnight reset
- **`update_from_db()`**: Restores cycle totals from DB on startup. Sets
  `_cycle_start_date` to prevent `_check_cycle_reset()` from wiping restored data.
- **`_update_prediction()`**: Uses DB day count when available. Shows
  "Learning (N days)" label until 7 days of cycle data exist.
- **`_check_cycle_reset()`**: Now clears `_db_days_in_cycle` on cycle boundary
  to prevent stale day counts from previous cycles.
- **`prediction_label` property**: Exposes learning label for sensor attributes.

### domain_coordinators/energy.py
- **`async_setup()`**: Restores billing cycle from DB before starting timer
- **`_restore_cycle_from_db()`**: Queries DB for current cycle's daily records,
  feeds to `CostTracker.update_from_db()`
- **`_maybe_reset_daily()`**: Captures yesterday's billing totals and fires
  `_save_daily_snapshot()` as async task before resetting counters
- **`_save_daily_snapshot()`**: Writes daily billing record to `energy_daily` table

### sensor.py
- **`EnergyPredictedBillSensor`**: Added `extra_state_attributes` showing
  `status` (learning label), `days_in_cycle`, and `cycle_start_date`

### const.py
- VERSION bumped to 3.7.11
