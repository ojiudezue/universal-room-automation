# v3.20.2 — Stub Cleanup (Cycle C)

**Date:** 2026-03-31
**Review tier:** Hotfix (1 review)

## What Changed

Removed 15 dead entities (stub sensors, buttons, binary sensors) and 1 dead signal
that returned hardcoded placeholder values. All removed entities are documented in
`docs/DEFERRED_TO_BAYESIAN.md` for reimplementation with real data pipelines in v4.0.0.

### D1: Remove Non-Functional Buttons
- Removed `ClearDatabaseButton` (logged warning only, no action)
- Removed `OptimizeNowButton` (logged warning only, no action)

### D2: Remove Stub Sensors
- Removed 11 stub sensors from `sensor.py`: OccupancyPercentageTodaySensor,
  EnergyWasteIdleSensor, MostExpensiveDeviceSensor, OptimizationPotentialSensor,
  EnergyCostPerOccupiedHourSensor, TimeUncomfortableTodaySensor, AvgTimeToComfortSensor,
  WeekdayMorningOccupancyProbSensor, WeekendEveningOccupancyProbSensor,
  TimeOccupiedTodaySensor, OccupancyPatternDetectedSensor
- Removed 2 stub binary sensors: OccupancyAnomalyBinarySensor, EnergyAnomalyBinarySensor
- Removed orphaned `STATE_OCCUPANCY_PCT_TODAY` constant from `const.py`

### D3: Remove Dead Signal
- Removed `SIGNAL_COMFORT_REQUEST` and `ComfortRequest` dataclass from `signals.py`
  (defined but never dispatched or consumed)

### Documentation
- Created `docs/DEFERRED_TO_BAYESIAN.md` with all 15 entities + 1 signal mapped to
  v4.0.0 Bayesian Intelligence milestones (B1-B4)

## Files Changed
- `button.py`, `sensor.py`, `binary_sensor.py`, `const.py`, `domain_coordinators/signals.py`
- `quality/tests/test_domain_coordinators.py` (removed dead signal test refs)
- New: `docs/DEFERRED_TO_BAYESIAN.md`, `quality/tests/test_cycle_c_stub_cleanup.py`
