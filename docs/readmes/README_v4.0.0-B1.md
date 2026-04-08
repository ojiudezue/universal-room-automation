# v4.0.0-B1 — Bayesian Predictive Intelligence: Model Core

## Overview

The first milestone of URA's capstone feature. Implements a Dirichlet-Multinomial Bayesian model that predicts room occupancy probabilities per person, conditioned on time of day and day type (weekday/weekend).

## What It Does

**Predicts where people will be.** For each person, time bin (6 periods), and day type:
- P(Oji → Kitchen | Morning, Weekday) = 0.72
- P(Jaya → Bedroom | Late, Weekend) = 0.91

**Room-level aggregation:** P(Kitchen occupied) = 1 - product(1 - P(each person in Kitchen))

**Prior initialization from historical data:** 155k room transitions over 94 days, filtered for quality (99.3% pass rate). Priors scaled by 0.5 to allow new data to shift the posterior within days.

**Live learning:** Every room transition updates the Bayesian posterior in real-time. Guest mode suppresses learning to prevent guest patterns from contaminating the model.

## Mathematical Model

- **Prior:** Dirichlet(alpha_1, ..., alpha_R) initialized from room_transitions frequency
- **Update:** alpha_r += confidence_weight per observation
- **Prediction:** P(room) = alpha_r / sum(alphas)
- **Uncertainty:** Dirichlet variance formula with 95% CI approximation
- **Time bins:** Night (0-6), Morning (6-9), Midday (9-12), Afternoon (12-17), Evening (17-21), Late (21-24)
- **Day types:** Weekday (Mon-Fri) vs Weekend (Sat-Sun)

## Data Quality

7-point quality filter applied to both prior initialization and live updates:
1. Null/empty rooms
2. Self-transitions (from == to)
3. Impossible durations (<0 or >24h)
4. Duplicate timestamps
5. Unknown rooms (away, home, not_home)
6. Low confidence (<0.3)
7. Excluded from_room (away, home, etc.)

Data quality report logged at startup and available via `sensor.ura_bayesian_data_quality`.

## Learning Status

Per (person, time_bin, day_type) cell:
- **INSUFFICIENT_DATA:** <5 observations — no predictions
- **LEARNING:** 5-49 observations — predictions with learning flag
- **ACTIVE:** 50+ observations — full predictions

## New Entities

| Entity | Type | Device | Default |
|--------|------|--------|---------|
| `sensor.{room}_weekday_morning_occupancy_probability` | Per-room | Room device | Disabled |
| `sensor.{room}_weekend_evening_occupancy_probability` | Per-room | Room device | Disabled |
| `sensor.{room}_bayesian_occupancy_pattern` | Per-room | Room device | Disabled |
| `sensor.ura_bayesian_data_quality` | Coordinator | CM device | Disabled |
| `button.ura_clear_bayesian_beliefs` | Button | CM device | Enabled |

## Guest Mode

When house state transitions to GUEST, Bayesian learning is automatically suppressed. Predictions continue (using existing beliefs) but no posterior updates occur. When house leaves GUEST state, learning resumes.

## Persistence

- Beliefs saved to `bayesian_beliefs` DB table every 30 minutes + on shutdown
- Restored on startup — warm start from saved beliefs
- If no saved beliefs (first run), builds priors from `room_transitions` (last 90 days)
- `button.ura_clear_bayesian_beliefs` resets all beliefs and rebuilds from priors

## Files Changed

### New
- `bayesian_predictor.py` — Core BayesianPredictor class (~480 lines)
- `quality/tests/test_bayesian_predictor.py` — 55 tests

### Modified
- `database.py` — `bayesian_beliefs` table + 4 methods
- `__init__.py` — Initialization, periodic save, guest listener, shutdown save, transition listener cleanup
- `sensor.py` — 4 new sensors (3 per-room diagnostic + 1 coordinator-level)
- `button.py` — ClearBayesianBeliefsButton
- `signals.py` — SIGNAL_BAYESIAN_UPDATED

## Review Findings Fixed

| Finding | Severity | Fix |
|---------|----------|-----|
| `predict_room_occupancy` used MINIMUM_ALPHA for absent rooms | CRITICAL | Use 0.0, skip persons with no data |
| Unused DOMAIN import (Bug Class #22 adjacent) | CRITICAL | Removed |
| Prior build didn't apply all data quality filters | HIGH | Added self-transition, duration, from_room filters |
| `clear_and_reinitialize` raced with `update()` | HIGH | Suppress learning during reinit |
| Transition listener never removed on reload | HIGH | Store reference, remove in unload |
| 155k row double-fetch blocks event loop | HIGH | Added days=90 limit, cached rows |
| Self-referential via_device on button | HIGH | Removed |
| Guest listener fragile payload handling | HIGH | isinstance guard |

## Test Results
- 55 new Bayesian tests pass
- 1573 existing tests pass (56 pre-existing failures unchanged)
- 0 regressions

## What's Next
- **B2:** Prediction sensors — per-person next-room prediction with confidence, whole-house occupancy forecast, prediction accuracy tracking
- **B3:** Pre-emptive actions — high-confidence prediction triggers room preparation
- **B4:** Energy integration — occupancy-weighted consumption prediction
