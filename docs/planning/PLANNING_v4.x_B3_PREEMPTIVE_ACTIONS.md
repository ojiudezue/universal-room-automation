# B3: Pre-emptive Actions — Zone & House Level

**Version:** 1.0
**Date:** April 27, 2026
**Status:** Ready to build
**Depends on:** B1 (v4.0.0, shipped), B2 (v4.0.2, shipped)
**Effort:** ~15-20 hours
**Priority:** HIGH — completes the Bayesian capstone by making predictions actionable

---

## Supersedes

This plan replaces the original B3 scope described in:
- `docs/ROADMAP_v11.md` lines 369-371 (room-level pre-emptive actions)
- `docs/BACKLOG.md` B3 entry (deferred, practical utility under review)

**What changed:** The original B3 targeted room-level preparation (lights, music).
After review, room-level actions have minimal practical value in URA because:
- Lights: Presence detection fires in 2-5s; pre-turning lights adds waste, not value
- HVAC: Rooms don't have independent climate — zones do
- Music: Already follows presence via Music Following coordinator

This plan scopes B3 to **zone-level and house-level** pre-emptive actions where
Bayesian predictions provide genuine lead time over reactive detection.

---

## Design Principle: Prediction vs Detection Lead Time

Pre-emptive actions are only valuable when they provide **meaningful lead time**
over existing reactive systems. If detection already handles it in seconds,
prediction adds cost without benefit.

| System | Trigger | Latency | What it catches |
|--------|---------|---------|-----------------|
| Presence detection | BLE/camera sees person | 2-5s | Person already in room |
| BLE pre-arrival (v3.18.6) | BLE signal approaching zone | 30-90s | Person physically moving toward zone |
| **Bayesian prediction** | Routine pattern match | **15-30 min** | Person hasn't moved yet but pattern says they will |

Bayesian predictions buy 15-30 minutes of lead time. That's valuable for HVAC
(which takes 10-20 min to change zone temperature) and house state transitions
(which benefit from gradual ramp). It's not valuable for lights (2s is fine).

---

## Available Bayesian APIs

All APIs are on `BayesianPredictor` (accessed via `hass.data[DOMAIN]["bayesian_predictor"]`):

```python
# Per-person: where will this person be at future_dt?
predictor.predict_room_at_time(person_id, future_dt) -> dict | None
# Returns: {"room_id": str, "probability": float, "confidence_interval": tuple, "learning_status": str}

# Per-room: probability room will be occupied at future_dt?
predictor.predict_room_occupancy_at_time(room_id, future_dt) -> float | None
# Returns: 0.0-1.0 or None if insufficient data

# Anomaly: is current occupancy surprising vs prediction?
predictor.get_anomaly_score(room_id, is_occupied) -> dict
# Returns: {"predicted_probability": float, "anomaly": bool, "learning_status": str}

# Learning status: INSUFFICIENT_DATA | LEARNING | ACTIVE
# Only act on predictions when learning_status == ACTIVE
```

**Time bins:** NIGHT (0-5), MORNING (6-9), MIDDAY (10-12), AFTERNOON (13-16), EVENING (17-20), LATE (21-23)
**Day types:** Weekday (0), Weekend (1)

Note: predictions are per-bin, not per-minute. A "30-min lookahead" means
querying the bin that contains `now + 30min`. Predictions are coarse — good
for HVAC pre-conditioning (which operates on 15-30 min timescales), not for
sub-minute actions.

---

## Deliverables

### D1: Prediction-Aware HVAC Zone Pre-Conditioning

**What:** Extend existing HVAC pre-arrival to accept Bayesian predictions as a
trigger source, alongside BLE and geofence.

**How it works:**
1. Every 5 minutes (via `async_track_time_interval`), check Bayesian predictions
   for each zone's rooms at `now + 30min`
2. If any room in the zone has P(occupied) > threshold AND the zone is currently
   vacant AND learning_status == ACTIVE:
   - Add `"bayesian"` to the zone's pre-arrival sources
   - Trigger the existing `_handle_person_arriving` pathway
   - Log: "Bayesian pre-conditioning: zone {zone} predicted occupied in 30min (P={p})"
3. The existing HVAC pre-arrival machinery handles the rest (preset application,
   timeout, cleanup)

**Integration point:** `domain_coordinators/hvac.py` `_handle_person_arriving()`
already accepts a `source` field. Currently only `"ble"` and `"geofence"`. Add
`"bayesian"` as a third source.

**Config:**
- `bayesian_pre_conditioning` toggle (default OFF) — in Coordinator Manager HVAC step
- `bayesian_confidence_threshold` number (default 0.75, range 0.5-0.95) — minimum P to trigger
- `bayesian_lookahead_minutes` number (default 30, range 15-60) — how far ahead to predict

**Guard rails:**
- Only trigger when `learning_status == ACTIVE` (not LEARNING or INSUFFICIENT_DATA)
- Max 1 Bayesian trigger per zone per hour (prevent re-triggering on same prediction)
- Guest mode suppresses Bayesian triggers (predictions trained on residents, not guests)
- Observation mode suppresses triggers (existing gate)
- If BLE pre-arrival already active for the zone, skip (don't double-trigger)

### Acceptance Criteria
- **Verify:** With toggle ON and sufficient training data, zone HVAC moves to occupied preset ~30min before predicted arrival
- **Verify:** With toggle OFF, no Bayesian triggers fire (BLE/geofence still work)
- **Verify:** Guest mode active = no Bayesian triggers
- **Verify:** Zone already in pre-arrival from BLE = Bayesian trigger skipped
- **Sensor:** `sensor.ura_hvac_coordinator_pre_arrival_triggers_today` increments on Bayesian trigger
- **Test:** test_bayesian_pre_conditioning_trigger, test_bayesian_suppressed_by_guest, test_bayesian_skipped_when_ble_active
- **Live:** After deploy, check `_last_pre_arrival_source` attribute shows "bayesian" for predicted arrivals

---

### D2: Prediction-Aware Vacancy Hold

**What:** Dynamically adjust zone vacancy hold duration based on predicted
reoccupancy probability.

**How it works:**
1. When a zone transitions to vacant (existing vacancy detection), before starting
   the vacancy hold timer:
2. Query `predict_room_occupancy_at_time` for each room in the zone at `now + 1h`
3. Compute `max_reoccupancy_p` across all rooms
4. Adjust vacancy hold:
   - P > 0.70: Extend hold to `2x` configured duration (someone likely returning)
   - P 0.30-0.70: Use configured duration (uncertain, use default)
   - P < 0.30: Reduce hold to `0.5x` configured duration (unlikely, save energy)
5. Only adjust when learning_status == ACTIVE; otherwise use configured duration

**Integration point:** `domain_coordinators/hvac.py` — wherever vacancy hold
timer is started. The adjustment is a multiplier on the existing
`CONF_FAN_VACANCY_HOLD` / zone vacancy hold config value.

**Config:**
- Uses `bayesian_pre_conditioning` toggle from D1 (same toggle controls both)
- No additional config needed — multipliers are hardcoded (simple, auditable)

**Guard rails:**
- Floor: vacancy hold never less than 2 minutes (prevent lights-off-then-on flicker)
- Ceiling: vacancy hold never more than 3x configured duration
- Guest mode: use configured duration (no prediction adjustment)

### Acceptance Criteria
- **Verify:** High P(reoccupancy) zone holds lights/fans longer than configured
- **Verify:** Low P(reoccupancy) zone sweeps faster than configured
- **Verify:** LEARNING status = configured duration used unchanged
- **Test:** test_vacancy_hold_extended_high_p, test_vacancy_hold_shortened_low_p, test_vacancy_hold_no_adjustment_learning
- **Live:** After deploy, check zone vacancy sweep timing correlates with prediction accuracy

---

### D3: Predicted Departure Pre-Transition

**What:** When Bayesian prediction indicates high probability of all-away within
30 minutes, begin gradual house state pre-transition.

**How it works:**
1. Every 5 minutes (same interval as D1, combined into one periodic check), if
   house state is any HOME_* state:
2. For each tracked person, query `predict_room_at_time(person, now + 30min)`
3. If NO person has a home room in their prediction (i.e., all predicted to be
   away/unknown) AND confidence is high:
   - Dispatch new signal `SIGNAL_PREDICTED_DEPARTURE` with data:
     `{"confidence": float, "predicted_departure_bin": str, "source": "bayesian"}`
4. Coordinators subscribe to `SIGNAL_PREDICTED_DEPARTURE`:
   - **HVAC:** Start setback toward away preset (gradual, not immediate)
   - **Energy:** If battery strategy active, begin pre-departure battery hold
   - **Security:** No action (arming requires actual departure confirmation)

**Why not full AWAY transition:**
Predictions are probabilistic. An 80% confidence departure prediction is wrong
20% of the time. Full AWAY transition (arming, setback, sweep) is disruptive to
reverse. Instead, dispatch a softer signal that coordinators can use for
*gradual* pre-positioning. Full AWAY still requires actual departure detection.

**Config:**
- `predicted_departure_enabled` toggle (default OFF) — in Coordinator Manager Presence step
- `predicted_departure_threshold` number (default 0.80, range 0.60-0.95)

**Guard rails:**
- Max 1 departure prediction signal per hour (prevent re-firing on same prediction)
- Only fire when ALL tracked persons predict away (not just one)
- Cancel/suppress if any person arrives home while pre-transition is active
- Guest mode: suppress entirely (guest movements unpredictable)

### Acceptance Criteria
- **Verify:** 30 min before routine departure (e.g., weekday morning), HVAC begins setback
- **Verify:** If person doesn't leave (prediction wrong), setback reverses on next occupancy detection
- **Verify:** Security does NOT arm on prediction alone
- **Test:** test_predicted_departure_fires, test_predicted_departure_cancelled_by_arrival, test_predicted_departure_suppressed_guest
- **Live:** After deploy, check `SIGNAL_PREDICTED_DEPARTURE` in debug logs during typical departure windows

---

### D4: Predicted Return Pre-Transition

**What:** When house is in AWAY state and Bayesian prediction indicates someone
will return within 30 minutes, begin warming zones.

**How it works:**
1. Same 5-minute periodic check. If house state is AWAY:
2. For each tracked person, query `predict_room_at_time(person, now + 30min)`
3. If ANY person predicts a home room with high confidence:
   - Dispatch `SIGNAL_PREDICTED_RETURN` with data:
     `{"person": str, "predicted_zone": str, "confidence": float, "source": "bayesian"}`
4. Coordinators subscribe:
   - **HVAC:** Pre-condition the predicted zone (same as D1 but from AWAY state)
   - **Energy:** If battery, prepare for load increase

**Difference from D1:**
D1 triggers when the house is occupied and a currently-vacant zone is predicted
to fill. D4 triggers when the *entire house* is empty and someone is predicted
to return. D4 may start HVAC from a deeper setback (away preset), requiring
more lead time.

**Config:**
- Uses `bayesian_pre_conditioning` toggle from D1
- Uses same `bayesian_confidence_threshold` from D1

**Guard rails:**
- Max 1 return prediction per person per 2 hours
- If AWAY duration < 1 hour, skip (short absence, zones probably still warm)
- Guest mode: suppress

### Acceptance Criteria
- **Verify:** 30 min before routine return (e.g., weekday evening), primary zone begins warming from away preset
- **Verify:** Short absence (< 1h) does not trigger pre-conditioning
- **Test:** test_predicted_return_from_away, test_predicted_return_short_absence_skipped
- **Live:** After deploy, check zone temperature ramp starts before BLE detection on routine return days

---

### D5: Battery Strategy Occupancy Shaping (Wire Existing Code)

**What:** Connect B4 L2's existing `_remaining_occupancy_weighted_consumption()`
to the Bayesian predictor for real-time occupancy forecast in battery
charge/discharge decisions.

**How it works:**
B4 L2 already implemented `_occupancy_blend_weight()` and
`_occupancy_weighted_estimate()` in `energy_forecast.py`. These use Bayesian
predictions to shape the consumption curve for battery full-time estimates.

D5 ensures the battery strategy's `_should_hold_charge()` decision incorporates
the occupancy forecast:
- If predicted low-occupancy afternoon (all away): discharge more aggressively
  during peak TOU (battery empty before cheap night rate)
- If predicted high-occupancy evening: hold more charge for evening peak

**Integration point:** `domain_coordinators/energy_forecast.py` —
`DailyEnergyPredictor._battery_strategy_recommendation()`

**Config:**
- Uses existing `switch.ura_energy_occupancy_weighted_prediction` toggle (B4 L2)
- No new config

**Effort:** Low (~2 hours) — mostly wiring, the prediction code exists.

### Acceptance Criteria
- **Verify:** With occupancy weighting ON, battery hold decision differs on predicted-away vs predicted-home days
- **Test:** test_battery_hold_low_occupancy, test_battery_hold_high_occupancy
- **Live:** After deploy, compare `battery_full_time_estimate` on work-from-home vs office days

---

## Implementation Order

```
D1 (zone pre-conditioning)  ─┐
D2 (vacancy hold)            ├─ Can ship together as v4.3.0
D5 (battery wiring)         ─┘

D3 (predicted departure)    ─┐
D4 (predicted return)        ├─ Ship as v4.3.1 (needs D1 signal infrastructure)
                             ┘
```

**D1+D2+D5 first** because:
- D1 extends existing pre-arrival infrastructure (lowest risk)
- D2 is a parameter tweak to existing vacancy hold (very low risk)
- D5 wires existing B4 L2 code (low risk, low effort)

**D3+D4 second** because:
- New signals (`SIGNAL_PREDICTED_DEPARTURE`, `SIGNAL_PREDICTED_RETURN`)
- New cross-coordinator subscription paths
- Higher blast radius — needs careful review

---

## Estimated Line Counts

| Deliverable | Production Code | Test Code | Config Flow |
|-------------|----------------|-----------|-------------|
| D1 | ~120 lines (hvac.py + __init__.py) | ~80 lines | ~30 lines |
| D2 | ~40 lines (hvac.py) | ~50 lines | 0 (reuses D1 toggle) |
| D3 | ~100 lines (presence.py + signals.py + hvac.py) | ~80 lines | ~20 lines |
| D4 | ~80 lines (presence.py + hvac.py) | ~60 lines | 0 (reuses D1 toggle) |
| D5 | ~30 lines (energy_forecast.py) | ~40 lines | 0 (existing toggle) |
| **Total** | **~370 lines** | **~310 lines** | **~50 lines** |

---

## Review Protocol

**Tier 2: Feature Cycle** (new signals, cross-coordinator interactions)

1. Review 1 (Core A): D1-D5 against QUALITY_CONTEXT.md bug classes — especially:
   - Bug #19 (untracked background tasks): periodic check timer must be tracked + cancelled
   - Bug #20 (concurrent reload race): new signals must not trigger during reload
   - Bug #22 (enum mismatch): new signal constants must match actual dispatch strings
   - Bug #23 (observation mode): all new triggers must check observation mode
   - Bug #24 (lambda scope): any lambdas must use module-level imports

2. Review 2 (Core B): Focus on race conditions between Bayesian triggers and
   reactive triggers (BLE pre-arrival, geofence, actual departure). Ensure
   no double-triggering, no conflicting actions.

3. Deploy via `/deploy`

4. Live validation: Check predictions are firing at expected times, verify
   no false triggers during LEARNING status.

---

## What's NOT in This Plan

- **Room-level pre-emptive actions** (lights, music) — no practical value over
  2-5s reactive presence detection. See "Supersedes" section.
- **Camera/BLE confidence boosting for predictions** — originally scoped for B3
  in ROADMAP_v11.md. Deferred to backlog. Predictions are already usable without
  boosting; boosting is an accuracy refinement, not a functional gap.
- **SIGNAL_COMFORT_REQUEST** — referenced in BACKLOG.md as deferred to B3.
  Remains deferred — it's an optimization coordinator concern, not a prediction
  concern.
- **Chained automations from predictions** — AI Custom Automation (v3.10-v3.12)
  could theoretically trigger on predictions. Deferred — the automation engine
  would need a new trigger type, which is a separate feature.
