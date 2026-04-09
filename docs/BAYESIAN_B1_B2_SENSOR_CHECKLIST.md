# Bayesian B1 + B2 Sensor Verification Checklist

## B1 Sensors (v4.0.0)

### Coordinator Manager Device
| Entity | Expected State | Check |
|--------|---------------|-------|
| `sensor.ura_coordinator_manager_bayesian_data_quality` | "91% quality" or similar | Should show belief_cells, known_rooms, known_persons, learning_suppressed in attributes |
| `button.ura_coordinator_manager_clear_bayesian_beliefs` | "unknown" (not pressed) | Should be available (not unavailable). Press to reset beliefs. |

### Per-Room Sensors (disabled by default — enable in HA UI to check)
For each room, these 3 sensors exist but are disabled:

| Entity Pattern | Expected | Notes |
|----------------|----------|-------|
| `sensor.{room}_weekday_morning_occupancy_probability` | 0-100% or "Learning" | P(room occupied \| morning, weekday) |
| `sensor.{room}_weekend_evening_occupancy_probability` | 0-100% or "Learning" | P(room occupied \| evening, weekend) |
| `sensor.{room}_bayesian_occupancy_pattern` | Time bin name or "Learning" | e.g., "Morning (Weekday)" = most active time |

**To enable:** Settings → Devices → [Room Device] → find disabled entity → Enable

**Sample rooms to check:**
- Kitchen (high traffic, should have ACTIVE learning status)
- Master Bedroom (high traffic)
- Stair Closet (low traffic, may be LEARNING or INSUFFICIENT)

---

## B2 Sensors (v4.0.2)

### Coordinator Manager Device
| Entity | Expected State | Check |
|--------|---------------|-------|
| `sensor.ura_bayesian_prediction_accuracy` | "N/A" initially, then "X%" after first time-bin evaluation | Attributes: brier_score, hit_rate, total_predictions. Will populate after first bin boundary (hours 0,6,9,12,17,21 at :05). |

### Per-Person Sensors (existing entity, Bayesian upgrade)
| Entity | Expected State | Check |
|--------|---------------|-------|
| `sensor.ura_person_oji_udezue_likely_next_room` | Room name | Attributes: `source` should be "bayesian" (or "frequency" if insufficient data), `learning_status`, `confidence_interval` |
| `sensor.ura_person_ezinne_likely_next_room` | Room name | Same checks |
| `sensor.ura_person_jaya_likely_next_room` | Room name | Same checks |
| `sensor.ura_person_ziri_likely_next_room` | Room name | Same checks |

### Per-Room Sensors (disabled by default — enable to check)
| Entity Pattern | Expected | Notes |
|----------------|----------|-------|
| `sensor.{room}_occupancy_forecast` | 0-100% | Attributes: probability_now, probability_1h, probability_4h, learning_status |
| `sensor.{room}_occupancy_percentage_today` | 0-100% | % of today this room was occupied |
| `sensor.{room}_time_occupied_today` | Minutes (float) | Total occupied minutes today |
| `sensor.{room}_time_uncomfortable_today` | Minutes (int) | Minutes outside comfort zone while occupied |
| `sensor.{room}_avg_time_to_comfort` | Minutes (int) | Estimated comfort ramp-up time |

### Per-Room Binary Sensors (disabled by default)
| Entity Pattern | Expected | Notes |
|----------------|----------|-------|
| `binary_sensor.{room}_occupancy_anomaly` | OFF (normal) | ON = occupied when Bayesian says <10% likely AND learning ACTIVE. Guest/observation mode suppressed. NM alert fires on anomaly. |

**Sample rooms to check:**
- Kitchen (enable forecast + anomaly sensors)
- Study A (enable forecast)
- Living Room (enable occupancy_percentage_today)

---

## Quick Verification Steps

### 1. Check Bayesian is running
```
sensor.ura_coordinator_manager_bayesian_data_quality → should show "91% quality"
Attributes: belief_cells=48, known_rooms=31, known_persons=4
```

### 2. Check person predictions upgraded to Bayesian
```
sensor.ura_person_oji_udezue_likely_next_room → check attributes.source = "bayesian"
```

### 3. Enable one forecast sensor and check
```
Settings → Devices → Kitchen → sensor.kitchen_occupancy_forecast → Enable
Wait 30s → should show probability_now, probability_1h, probability_4h
```

### 4. Wait for accuracy tracking to populate
Predictions are recorded at time-bin boundaries (hours 0, 6, 9, 12, 17, 21 at :05 past).
After one full day, `sensor.ura_bayesian_prediction_accuracy` will show Brier score + hit rate.

### 5. Test anomaly detection
Enable `binary_sensor.kitchen_occupancy_anomaly` on a room that's typically empty at night.
Walk into it after midnight — if Bayesian predicts <10% occupancy for that time bin, the anomaly should fire (only if learning_status = ACTIVE for that cell).

---

## Entity Count Summary

| Level | Sensor Type | Count | Default State |
|-------|-------------|-------|---------------|
| Coordinator Manager | Bayesian Data Quality | 1 | Enabled |
| Coordinator Manager | Prediction Accuracy | 1 | Enabled (disabled by default, enable manually) |
| Coordinator Manager | Clear Beliefs Button | 1 | Enabled |
| Per-Person | Likely Next Room (upgraded) | 4 | Enabled (existing) |
| Per-Room | Weekday Morning Prob | ~31 | Disabled |
| Per-Room | Weekend Evening Prob | ~31 | Disabled |
| Per-Room | Occupancy Pattern | ~31 | Disabled |
| Per-Room | Occupancy Forecast | ~31 | Disabled |
| Per-Room | Occupancy % Today | ~31 | Disabled |
| Per-Room | Time Occupied Today | ~31 | Disabled |
| Per-Room | Time Uncomfortable | ~31 | Disabled |
| Per-Room | Avg Time to Comfort | ~31 | Disabled |
| Per-Room | Occupancy Anomaly | ~31 | Disabled |
| **Total** | | **~287** | Most disabled |
