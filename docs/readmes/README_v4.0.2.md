# v4.0.2 — Bayesian B2: Prediction Sensors

## Overview

Second milestone of Bayesian Predictive Intelligence. Adds prediction sensors, occupancy anomaly detection with NM alerts, prediction accuracy tracking, and 4 deferred room-level entities.

## New Capabilities

### Per-Person Next-Room Prediction (Bayesian Upgrade)
`sensor.ura_person_{name}_likely_next_room` — existing sensor now uses Bayesian predictor as primary source with frequency-based fallback. New attributes: `learning_status`, `confidence_interval`, `source` ("bayesian" or "frequency").

### Per-Room Occupancy Forecast
`sensor.{room}_occupancy_forecast` — shows probability of room being occupied now, in 1 hour, and in 4 hours. Uses Bayesian model's time-bin predictions.

### Occupancy Anomaly Detection
`binary_sensor.{room}_occupancy_anomaly` — fires ON when room is occupied but Bayesian model predicts <10% probability AND learning status is ACTIVE (50+ observations). Guest-mode suppressed. Observation-mode suppressed. Fires NM alert: HIGH severity at night (10PM-6AM), MEDIUM during day. 30-minute cooldown between alerts. 5-minute startup grace period prevents alert spam on restart.

### Prediction Accuracy Tracking
`sensor.ura_bayesian_prediction_accuracy` — Brier score + hit rate over rolling 7-day window. Predictions recorded at each time-bin boundary (6x/day) comparing predicted occupancy probability vs actual. Results stored in `prediction_results` DB table.

### Deferred Entities Implemented
- `sensor.{room}_occupancy_percentage_today` — % of today room was occupied
- `sensor.{room}_time_occupied_today` — hours occupied today
- `sensor.{room}_time_uncomfortable_today` — minutes outside comfort zone while occupied
- `sensor.{room}_avg_time_to_comfort` — estimated comfort ramp-up time

## Review Findings Fixed

| Finding | Severity | Fix |
|---------|----------|-----|
| `max(statuses)` on strings — wrong lexicographic ordering | CRITICAL | Explicit status_order dict |
| `prune_prediction_results` deletes all prediction types | CRITICAL | Scoped to bayesian_occupancy only |
| 31 individual DB writes in accuracy eval | CRITICAL | Batched into single executemany |
| Accuracy sensor triggers DB query on every transition | HIGH | Removed SIGNAL subscription, uses polling |
| Anomaly sensor fires without observation mode check | HIGH | Added observation mode guard |
| Alert cooldown lost on restart | HIGH | 5-minute startup grace period |
| Hardcoded "occupied" string | HIGH | Uses STATE_OCCUPIED constant |
| Missing AggregationEntity base class | HIGH | Fixed inheritance |
| UTC/local midnight mismatch | MEDIUM | Uses dt_util.start_of_local_day() |
| Cached transition rows never freed | MEDIUM | Cleared after quality scan |

## Files Changed
- `bayesian_predictor.py` — 5 new methods + memory fix
- `database.py` — prediction_results reuse + 5 methods + batch save + midnight fix
- `sensor.py` — PersonLikelyNextRoomSensor upgrade + 6 new sensor classes
- `binary_sensor.py` — OccupancyAnomalyBinarySensor with NM + observation mode + grace period
- `__init__.py` — Accuracy timer + batch eval + STATE_OCCUPIED import + cleanup
- `signals.py` — SIGNAL_OCCUPANCY_ANOMALY

## Tests
- 45 new B2 tests pass
- 55 existing B1 tests pass
- 0 regressions
