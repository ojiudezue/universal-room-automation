# B2: Prediction Sensors — Implementation Plan

**Status:** In Progress
**Version:** v4.0.2-B2
**Depends on:** B1 (v4.0.1) deployed and running

## Deliverables

### D1: BayesianPredictor Extensions
- `predict_room_at_time(person_id, future_dt)` — future time bin lookup
- `predict_room_occupancy_at_time(room_id, future_dt)` — room-level future lookup
- `get_anomaly_score(room_id)` — predicted vs actual occupancy comparison
- `record_prediction(...)` + `get_accuracy_stats(days=7)` — accuracy tracking

### D2: prediction_results DB Table + 5 Methods

### D3: PersonLikelyNextRoomSensor → Bayesian Upgrade (fallback to frequency)

### D4: Per-Room Occupancy Forecast Sensor (now / 1h / 4h)

### D5: Occupancy Anomaly Binary Sensor + NM Alert
- Only fires when learning_status = ACTIVE
- Guest-aware suppression
- Severity: HIGH at night, MEDIUM during day

### D6: Prediction Accuracy Tracking Sensor (Brier score + hit rate)

### D7: 4 Deferred Entities (occupancy_pct_today, time_occupied, time_uncomfortable, avg_time_to_comfort)

### D8: Wiring (accuracy timer at bin boundaries, pruning, cleanup)

## ~187 new entities (all diagnostic, disabled by default except accuracy sensor)
