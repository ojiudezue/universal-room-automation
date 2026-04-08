# B1: Bayesian Model Core — Implementation Plan

**Status:** In Progress
**Version:** v4.0.0-B1
**Scope:** Single cycle, 6 deliverables

## Mathematical Model

### Dirichlet-Multinomial Conjugate

Predicts P(person → room | time_bin, day_type).

- **Prior:** Dirichlet(alpha_1, ..., alpha_R) initialized from room_transitions frequency data
- **Update:** alpha_r_posterior = alpha_r_prior + n_r (per observation)
- **Point estimate:** P(room_r) = alpha_r / sum(alphas)
- **Uncertainty:** Var(theta_r) = alpha_r(alpha_0 - alpha_r) / (alpha_0^2(alpha_0 + 1))

### Time Bins (6 periods)

| Bin | Name | Hours |
|-----|------|-------|
| 0 | NIGHT | 00-06 |
| 1 | MORNING | 06-09 |
| 2 | MIDDAY | 09-12 |
| 3 | AFTERNOON | 12-17 |
| 4 | EVENING | 17-21 |
| 5 | LATE | 21-24 |

### Day Types
- 0 = Weekday (Mon-Fri, non-holiday)
- 1 = Weekend (Sat-Sun + holidays)

### Prior Initialization
- PRIOR_SCALE_FACTOR = 0.5 (scale historical counts to prevent prior domination)
- MINIMUM_ALPHA = 0.1 (Jeffreys-like floor for unseen rooms)
- Cold start: bins with <10 samples use person's global distribution at COLD_START_ALPHA = 1.0

### Learning Status (per cell)
- INSUFFICIENT_DATA: <5 observations
- LEARNING: 5-49 observations
- ACTIVE: 50+ observations

### Room-Level Aggregation
P(room occupied) = 1 - product(1 - P(person_p in room)) across all persons

## Data Quality Filters (7 checks)

1. Null/empty rooms → exclude
2. Self-transitions (from == to) → exclude
3. Impossible durations (<0 or >24h) → exclude
4. Duplicate timestamps (same person, <2s gap) → keep first
5. Unknown rooms ("unknown", "away", "home", "not_home") → exclude
6. Low confidence (<0.3) → exclude from priors, fractional weight in online updates
7. Path type filter → include "direct" and "via_hallway", exclude "separate"

## Deliverables

### D1: BayesianPredictor Class
New file: `bayesian_predictor.py`

**Acceptance Criteria:**
- **Verify:** `predict_room("Oji", 1, 0)` returns {top_room, probability, alternatives, confidence_interval, learning_status}
- **Verify:** `update()` increases alpha for observed room
- **Verify:** Learning status transitions INSUFFICIENT → LEARNING → ACTIVE
- **Verify:** `predict_room_occupancy()` returns float 0-1
- **Verify:** `suppress_learning()` makes `update()` no-op
- **Test:** 12 tests covering posterior update, prior init, learning status, guest suppression, room aggregate, confidence intervals
- **Live:** Startup log shows `B1 Data Quality:` summary

### D2: DB Persistence
New table `bayesian_beliefs` + 3 methods in database.py.

**Acceptance Criteria:**
- **Verify:** Save/load round-trip preserves exact alpha values
- **Verify:** Write uses `_db()`, read uses `_db_read()`
- **Test:** 4 tests covering save, load, round-trip, table creation
- **Live:** Query `bayesian_beliefs` via MCP after first 30min save

### D3: Data Quality Scanner
Static method in bayesian_predictor.py.

**Acceptance Criteria:**
- **Verify:** Reports counts for all 7 exclusion categories
- **Test:** 5 tests covering each filter type
- **Live:** Startup log shows quality summary

### D4: Integration Wiring
Init in `__init__.py`, update in `transitions.py`, guest-state via signal.

**Acceptance Criteria:**
- **Verify:** Each transition triggers `predictor.update()`
- **Verify:** GUEST state suppresses learning
- **Verify:** Beliefs saved every 30min + on shutdown
- **Verify:** PatternLearner unchanged (no regression)
- **Test:** 4 tests
- **Live:** `bayesian_beliefs` table populates, PatternLearner sensors still work

### D5: 3 Deferred Sensors
WeekdayMorningOccupancyProbSensor, WeekendEveningOccupancyProbSensor, OccupancyPatternDetectedSensor.

**Acceptance Criteria:**
- **Sensor:** Per-room, diagnostic, disabled by default
- **Verify:** Shows percentage or "Learning" based on status
- **Test:** 4 tests
- **Live:** Enable sensor in HA UI, verify value

### D6: ClearDatabaseButton
Resets beliefs and re-initializes from room_transitions.

**Acceptance Criteria:**
- **Verify:** Clears bayesian_beliefs, re-runs prior init
- **Test:** 1 test
- **Live:** Button on Coordinator Manager device

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `bayesian_predictor.py` | NEW | Core engine + data quality scanner (~400 lines) |
| `database.py` | MODIFY | bayesian_beliefs table + 3 methods (~60 lines) |
| `__init__.py` | MODIFY | Init, shutdown, guest listener (~20 lines) |
| `transitions.py` | MODIFY | Update call (~5 lines) |
| `sensor.py` | MODIFY | 3 sensor classes (~80 lines) |
| `button.py` | MODIFY | ClearDatabaseButton (~30 lines) |
| `signals.py` | MODIFY | SIGNAL_BAYESIAN_UPDATED (~1 line) |
| `test_bayesian_predictor.py` | NEW | ~30 tests (~300 lines) |

## What B1 Does NOT Do
- Replace PatternLearner (B2)
- Add next-room prediction sensors (B2)
- Add occupancy anomaly detection (B2)
- Add pre-emptive automation triggers (B3)
- Add energy integration (B4)
- Add camera/BLE confidence boosting (B3)
- Add lookahead predictions 1h/4h (B2)
