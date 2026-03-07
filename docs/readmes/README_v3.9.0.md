# v3.9.0 — Energy E6 Completion + Coordinator Transparency

## Summary
Completes Energy Coordinator sub-cycle E6 (load shedding, pre_heat/shed constraint
modes, configurable offsets, max_runtime_minutes) and adds transparency/diagnostic
features across Energy and HVAC coordinators. Users can now see and configure
internal coordinator decisions through config flow options and diagnostic sensors.

## Changes

### Part A: Energy E6 Completion

#### New Constraint Modes (`energy.py`)
- **`pre_heat`** mode: Fires during off-peak when forecast low < configurable
  threshold (default 40F) and SOC > 50%. Raises heat setpoint by configurable
  offset (default +2F) to bank warmth before peak.
- **`shed`** mode: Fires during peak when SOC < 20% AND active load shedding.
  Most aggressive offset (default +5F). Signals HVAC to maximize conservation.
- All constraint offsets (coast, pre_cool, pre_heat, shed) now configurable
  via Energy config flow instead of hardcoded values.

#### `max_runtime_minutes` (`energy.py`, `signals.py`)
- Computed from time remaining until current TOU period ends.
- Published in `EnergyConstraint` signal for HVAC to use.
- Visible in HVAC Constraint sensor attributes.

#### Load Shedding Engine (`energy.py`)
- Configurable cascade: pool -> EV -> smart plugs -> HVAC (via constraint).
- Trigger: sustained grid import exceeding threshold for configurable duration.
- **Sustained** = all readings in window exceed threshold (default 15 min = 3 cycles).
- Threshold modes: **fixed** (user-configured, default 5 kW) or **auto** (learns
  from historical 90th percentile of peak-period import after 30 days).
- Escalates one level per sustained window; de-escalates when full window drops
  below threshold. Actually executes shed actions (pool speed reduction, EV/plug
  pause) not just bookkeeping.
- Enable/disable via config flow boolean.

#### New Config Flow Options (`config_flow.py`)
- Load shedding: enable, mode (fixed/auto), threshold (kW), sustained window (min)
- Constraint offsets: coast, pre-cool, pre-heat, shed (all in F)
- Pre-heat temperature threshold (F)

### Part B: HVAC Transparency

#### Override Arrester Enable/Disable (`switch.py`, `hvac_override.py`)
- New switch: `switch.ura_hvac_override_arrester` (EntityCategory.CONFIG)
- When OFF: passive mode — overrides tracked for diagnostics but NOT reverted.
  All in-flight timers cancelled on disable.
- Survives HA restart via RestoreEntity.
- Configurable via HVAC config flow step (initial enable/disable).

#### Arrester State Sensor (`sensor.py`)
- New diagnostic: `sensor.ura_hvac_arrester_state`
- States: idle, grace_period, compromise, active, disabled
- Attributes: per-zone detail (overrides today, state, direction), energy state

#### Zone Preset Sensors (`sensor.py`)
- New per-zone diagnostic: `sensor.ura_hvac_zone_preset_{zone_id}`
- Shows current preset mode, target setpoints (high/low), current temperature,
  HVAC mode/action, override counts, season.

#### HVAC Observation Mode (`switch.py`, `hvac.py`)
- New switch: `switch.ura_hvac_observation_mode` (EntityCategory.CONFIG)
- When ON: sensors compute normally but no actions executed (no preset changes,
  no fan/cover control, no AC resets). Arrester still tracks for diagnostics.
- Survives HA restart via RestoreEntity.

### Part C: Energy Transparency

#### Battery Decision Sensor (`sensor.py`)
- New diagnostic: `sensor.ura_energy_battery_decision`
- Shows last battery strategy mode and full decision details (reason, SOC,
  actions taken, Envoy status).

#### Load Shedding Sensor (`sensor.py`)
- New diagnostic: `sensor.ura_energy_load_shedding`
- States: disabled, idle, level_1 through level_4
- Attributes: shed loads list, effective threshold, learned threshold,
  configured threshold, mode, sustained readings count.

#### HVAC Constraint Sensor Enhancement (`energy.py`)
- Existing `sensor.ura_hvac_constraint` now exposes full detail in attributes:
  reason, solar_class, SOC, forecast_high_temp, forecast_low_temp,
  max_runtime_minutes, fan_assist.

### Part D: Cross-Coordinator

#### Config Flow Additions
- Energy: 8 new options (load shedding + constraint offsets)
- HVAC: 1 new option (arrester enable toggle)

#### Observation Mode Pattern
- Energy already had observation mode; HVAC now matches.
- Both coordinators can be put in "watch only" mode for safe testing.

## Review Fixes Applied
- Load shedding de-escalation race condition (required full window before de-escalating)
- Load shedding now executes actual shed actions (pool speed, EV pause, plug pause)
- Arrester disable cancels in-flight grace/compromise timers
- Arrester state priority corrected (grace_period before active)
- Switches survive restart via RestoreEntity
- Load shedding evaluated before constraint (no 1-cycle lag)
- Duplicate forecast code extracted to `_get_forecast_temps()` helper
- Net power correctly converted from watts to kW for threshold comparison
- Docstring percentile corrected (90th, not 80th)
- Removed unused `CONF_HVAC_OBSERVATION_MODE` constant

## Files Changed
- `domain_coordinators/energy.py` — E6 constraint modes, load shedding engine, transparency properties
- `domain_coordinators/energy_const.py` — 20 new constants (config keys, defaults, priority order)
- `domain_coordinators/hvac.py` — observation mode, arrester wiring, mode attrs
- `domain_coordinators/hvac_const.py` — arrester enabled config key + default
- `domain_coordinators/hvac_override.py` — enabled/passive mode, state methods, timer cancellation
- `sensor.py` — 4 new sensor classes, registration
- `switch.py` — 2 new switch classes with RestoreEntity
- `config_flow.py` — 9 new config fields (8 Energy, 1 HVAC)
- `__init__.py` — config wiring for arrester enabled + broadened energy config pass-through
- `const.py` — version bump to 3.9.0
- `manifest.json` — version bump to 3.9.0

## New Entities
| Entity | Type | Category | Device |
|--------|------|----------|--------|
| `sensor.ura_energy_battery_decision` | sensor | diagnostic | Energy Coordinator |
| `sensor.ura_energy_load_shedding` | sensor | diagnostic | Energy Coordinator |
| `sensor.ura_hvac_arrester_state` | sensor | diagnostic | HVAC Coordinator |
| `sensor.ura_hvac_zone_preset_{zone}` | sensor | diagnostic | HVAC Coordinator |
| `switch.ura_hvac_override_arrester` | switch | config | HVAC Coordinator |
| `switch.ura_hvac_observation_mode` | switch | config | HVAC Coordinator |
