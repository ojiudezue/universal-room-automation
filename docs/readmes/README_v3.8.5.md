# v3.8.5 — HVAC H4: Predictive Sensors + Weather Pre-Conditioning

## Summary
Completes the HVAC Coordinator's predictive intelligence layer with pre-cool/pre-heat
triggering, comfort violation risk assessment, zone demand analysis, and daily outcome
tracking.

## Changes

### New: HVACPredictor (`hvac_predict.py`)
- **Pre-cool likelihood** (0-100%): Combines forecast high temp, TOU peak proximity,
  battery SOC, and season into a pre-cool probability score
- **Comfort violation risk** (low/medium/high): Based on energy constraint mode and
  how many zones exceed setpoints by >2F
- **Per-zone demand**: Factors indoor delta + outdoor temp into low/medium/high demand
- **Daily outcome tracking**: Zone satisfaction %, override count, AC reset count,
  energy mode minutes, pre-cool/pre-heat trigger history

### New: Pre-Conditioning Engine
- **Pre-cool**: Triggers before peak (2h lead) when forecast > 90F, lowers cooling
  setpoints by 2F on occupied zones. Requires SOC >= 30%
- **Pre-heat**: Triggers before off-peak ends (1h lead) when outdoor < 35F, raises
  heating setpoints by 2F on occupied zones. Winter only

### New Sensors
- `sensor.ura_hvac_pre_cool_likelihood` — pre-cool probability percentage
- `sensor.ura_hvac_comfort_risk` — comfort violation risk level

### Bug Fixes (from review)
- **Override arrester suppression**: Pre-conditioning temperature changes now suppress
  the override arrester so they aren't detected as manual overrides
- **Pre-heat uses actual zone setpoints**: Fixed from hardcoded seasonal defaults to
  using `zone.target_temp_low + 2` (same fix applied to pre-cool earlier)
- **SEASON_SHOULDER constant**: Replaced string literal "shoulder" with proper constant
- **Daily outcome reset ordering**: `flush_daily_outcome()` now called before
  `reset_daily_counters()` so yesterday's override/reset counts are captured correctly
- **Predictor receives override_arrester**: Constructor now passes the arrester instance

## Files Changed
- `domain_coordinators/hvac_predict.py` — new (predictive sensors + pre-conditioning)
- `domain_coordinators/hvac_override.py` — added suppression mechanism
- `domain_coordinators/hvac.py` — predictor integration, daily reset ordering
- `domain_coordinators/hvac_const.py` — (unchanged, constants already present)
- `sensor.py` — 2 new sensor classes
- `const.py` — version bump to 3.8.5

## HVAC Coordinator Status
All 4 milestones complete:
- H1: Core + Zone Management + Preset + Diagnostics ✓ (v3.8.2)
- H2: Override Arrester + AC Reset ✓ (v3.8.3)
- H3: Fan Controller + Cover Controller ✓ (v3.8.4)
- H4: Predictive Sensors + Pre-Conditioning ✓ (v3.8.5)
