# v4.1.1 — B4 Layer 2: Occupancy-Weighted Energy Prediction

**Date:** April 17, 2026
**Scope:** B4 Energy Integration — Occupancy-Weighted Prediction + Baseline Fix
**Tests:** 1478 passing (no regressions)

## Summary

Second layer of B4 (Bayesian Energy Integration). The DailyEnergyPredictor now
blends Bayesian room occupancy probabilities with learned power profiles to produce
occupancy-shaped consumption estimates. A 5-bedroom house at 2 PM on a workday
now predicts different consumption than a fully-occupied Saturday. Gated by an
off-by-default toggle on the Energy Coordinator device.

Also fixes an energy baseline bug where cumulative lifetime values leaked into
daily delta calculations when sensors were unavailable at startup.

## Changes

### D3b: Occupancy Weighting Toggle
- New `switch.ura_energy_occupancy_weighted_prediction` on Energy Coordinator device
- Entity category: CONFIG, default OFF
- Config flow toggle in Energy Coordinator options (syncs to switch)
- RestoreEntity pattern for persistence across restarts

### D4: DailyEnergyPredictor Bayesian Integration
- `_occupancy_weighted_estimate()`: sums occupancy-weighted load across all rooms
  by time bin using RoomPowerProfile baselines x BayesianPredictor probabilities
- `_occupancy_blend_weight()`: adaptive 0-40% weight based on Bayesian cell maturity
- Standby power from NIGHT-bin vacant observations (not hardcoded)
- Lazy BayesianPredictor lookup via callable (survives integration reloads)

### D5: Battery Strategy Occupancy Awareness
- `_remaining_occupancy_weighted_consumption()`: shaped consumption curve replaces
  flat `daily_consumption * (hours_left / 24)` in battery full time estimate
- Accounts for "afternoon low-occupancy" vs "evening high-occupancy" patterns

### Power Profile Wiring
- RoomPowerProfile instantiated in Energy Coordinator, updated per cycle
- Reads power + occupancy state from all room coordinators each cycle
- Persists to DB hourly via existing `save_power_profiles()` / `load_power_profiles()`
- Restores from DB on startup

### Hotfix: Energy Baseline Bug
- `coordinator.py`: Skip unavailable/unknown sensors when setting energy baselines
- Previously, sensors returning default 0 on startup caused baselines to be set to 0,
  making full cumulative lifetime values appear as "today's" energy delta
- Affected rooms with TOTAL_INCREASING energy sensors (Shelly, Emporia, SPAN)

### BayesianPredictor Additions
- `count_active_cells()`: cells with 50+ observations (ACTIVE status)
- `count_total_cells()`: all cells with any observations
- Used for adaptive blend weight calculation

## Quality Review

Tier 1 review completed. Findings:
- 0 CRITICAL, 1 HIGH (fixed: stale Bayesian ref), 3 MEDIUM (2 fixed, 1 pre-existing), 2 LOW (acceptable)
- All HIGH/MEDIUM findings resolved before deploy

## Files Changed
- `coordinator.py` — energy baseline fix
- `const.py` — CONF_OCCUPANCY_WEIGHTED_ENERGY
- `bayesian_predictor.py` — cell counting methods
- `energy_forecast.py` — occupancy weighting methods in DailyEnergyPredictor
- `energy.py` — RoomPowerProfile wiring, toggle, profile updates
- `switch.py` — OccupancyWeightedPredictionSwitch
- `config_flow.py` — toggle in energy coordinator options
- `strings.json` / `translations/en.json` — toggle labels
