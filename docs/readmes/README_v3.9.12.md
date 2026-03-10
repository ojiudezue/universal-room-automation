# URA v3.9.12 — Energy Load Shedding Learned Threshold Persistence

## Overview
Persists the Energy Coordinator's auto-learned load shedding threshold and peak import history to the database, surviving HA restarts. Previously, 30 days of peak import data was lost on every restart, forcing the threshold back to the fixed default.

## Changes

### Peak Import History DB Persistence
- **Problem**: `_peak_import_history` (up to 1500 readings) and `_learned_threshold_kw` are in-memory only. Every HA restart wipes the auto-learned threshold, requiring 30 days of data collection before auto-learning can resume.
- **Fix**: Two new DB tables (`energy_peak_import`, `energy_learned_threshold`) store the readings and threshold. Restored on startup, saved hourly during peak periods.
- **Restore**: `_restore_peak_import_history()` runs during `async_setup()` alongside existing billing/accuracy restoration.
- **Save**: Hourly throttle in `_async_decision_cycle` after `_update_load_shedding()` — avoids DB churn while ensuring at most 1 hour of data loss on crash.

## Files Changed
- `database.py` — Two new tables + `save_peak_import_history()` / `get_peak_import_history()` methods
- `domain_coordinators/energy.py` — `_restore_peak_import_history()`, `_save_peak_import_history()`, hourly save trigger

## Design Notes
- Tables use `CREATE TABLE IF NOT EXISTS` for safe migration (no ALTER TABLE needed)
- `energy_learned_threshold` is a single-row table (CHECK constraint `id = 1`) for the scalar threshold value
- Peak import readings use monotonic `seq` column for ordering (not timestamps — honest naming)
- Hourly save throttle uses `_last_peak_save_hour` to avoid saving on every 5-min decision cycle
- Final save on `async_teardown` ensures clean shutdowns lose zero data
- The `DELETE + INSERT` pattern for readings is acceptable at 1500 rows hourly — simpler than incremental sync
- Restored threshold is for immediate diagnostic display; recomputed from readings on first auto-mode evaluation
