# v3.13.1 — Complete Data Pipeline

**Date**: 2026-03-12
**Scope**: Energy history full column population, cross-coordinator data access, circuit state wiring, D3-D7 verification
**Tests**: 15 new (test_data_pipeline.py), 31 M1+M2 total, 945+ total passing

---

## Summary

M1 (v3.13.0) built the DB infrastructure. This release wires the complete data pipeline — energy_history rows now include all 13 data columns (was previously only 6), external_conditions uses real occupancy counts (was hardcoded to 0), and circuit state persists across restarts.

## Changes

### 1. Complete Energy History Population
- `_log_energy_history_snapshot()` now passes all columns to `log_energy_history()`:
  - `outside_humidity`, `house_avg_temp`, `house_avg_humidity`
  - `temp_delta_outside`, `humidity_delta_outside`
  - `rooms_occupied`, `tou_period`
- `log_energy_history()` updated to include `tou_period` as 19th column in INSERT

### 2. Cross-Coordinator Helper Methods
- `_get_house_avg_climate()`: Iterates room config entries, reads temperature/humidity sensor states, returns averages. Filters `unknown`/`unavailable` states.
- `_get_occupancy_counts()`: Reads presence coordinator zone trackers via `tracker.to_dict()["rooms"]` public interface (not private `_room_occupied`)
- `_get_occupied_room_count()`: Simplified room count helper using same public interface

### 3. Circuit State Persistence Wiring
- `_save_circuit_state()`: Serializes `SPANCircuitMonitor._circuits` dict to DB
- `_restore_circuit_state()`: Restores `CircuitInfo` fields on startup with stale `zero_since` protection — resets to current time to prevent false tripped-breaker alerts
- Wired into `async_setup()` (restore) and `async_teardown()` (save)
- Periodic save every 3rd decision cycle via `_periodic_db_writes()`

### 4. Serialized Periodic DB Writes
- Replaced 4 concurrent `async_create_task` DB writes with sequential `_periodic_db_writes()` to avoid SQLite contention

### 5. D3-D7 Caller Verification
All DB write callers already exist — no new wiring needed:
- D3: `presence.py` → `log_house_state_change()`, `log_zone_event()`
- D5: `person_coordinator.py` → `log_person_entry()`, `log_person_snapshot()`
- D7: `camera_census.py` → `log_census()`

## Review Findings Fixed (3-Review Protocol)

- **C1**: DB rollback moved inside `async with` scope in `save_circuit_state` (was outside, would crash on connection error)
- **H1**: Stale `zero_since` reset to current time on restore (prevents false tripped-breaker alerts from pre-restart timestamps)
- **H2**: Replaced private `tracker._room_occupied` with public `tracker.to_dict()["rooms"]` interface
- **H3**: Serialized 4 concurrent `async_create_task` DB writes into sequential `_periodic_db_writes()`
- **Test gaps**: Added `test_get_house_avg_climate_unavailable_sensors`, `test_get_house_avg_climate_partial_data`
- **Mock ordering**: Fixed `test_database_resilience.py` HA mock to include `async_track_time_interval` (prevented import when tests run together)

## Files Modified

| File | Changes |
|------|---------|
| `database.py` | Fixed `save_circuit_state` rollback scope, `log_energy_history` tou_period column |
| `domain_coordinators/energy.py` | Added 6 methods: `_get_house_avg_climate`, `_get_occupancy_counts`, `_get_occupied_room_count`, `_save_circuit_state`, `_restore_circuit_state`, `_periodic_db_writes`. Modified `_log_energy_history_snapshot`, `_log_external_conditions_snapshot`, `async_setup`, `async_teardown` |
| `quality/tests/test_data_pipeline.py` | 15 tests: tou_period storage (3), D3-D7 regression guards (5), helper methods (7) |
| `quality/tests/test_database_resilience.py` | Fixed HA mock ordering for `async_track_time_interval` |

## Deferred to M3 (v3.13.2)

- MetricBaseline integration for circuit anomaly detection
- Load shedding z-score threshold
- Additional EC baselines (solar deviation, battery cycle efficiency)
