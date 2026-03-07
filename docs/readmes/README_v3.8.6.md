# v3.8.6 — HVAC Config Flow UI

## Summary
Adds a config flow options step for the HVAC Coordinator, exposing all tunable
parameters via the HA UI. Also wires config values through to the coordinator
constructors so changes take effect on restart.

## Changes

### New: `coordinator_hvac` Options Step
Accessible from Coordinator Manager → HVAC in the options menu. Fields:

| Setting | Key | Default | Description |
|---------|-----|---------|-------------|
| Sleep Setpoint Offset | `hvac_max_sleep_offset` | 1.5°F | Max temp adjustment during sleep |
| Override Compromise Duration | `hvac_compromise_minutes` | 30 min | How long to hold compromise before revert |
| AC Reset Stuck Timeout | `hvac_ac_reset_timeout` | 10 min | Minutes stuck before AC reset cycle |
| Fan Activation Delta | `hvac_fan_activation_delta` | 2.0°F | Temp above setpoint to activate fans |
| Fan Deactivation Hysteresis | `hvac_fan_hysteresis` | 1.5°F | Hysteresis band for fan off |
| Fan Minimum Runtime | `hvac_fan_min_runtime` | 10 min | Min runtime once activated |
| Managed Cover Entities | `hvac_cover_entities` | auto-discover | Explicit cover list for solar gain |

### Wired Config to Constructors
- `HVACCoordinator.__init__` now accepts and forwards: `compromise_minutes`,
  `fan_activation_delta`, `fan_hysteresis`, `fan_min_runtime`
- `__init__.py` reads all HVAC config keys from CM entry and passes to constructor

## Files Changed
- `config_flow.py` — added `async_step_coordinator_hvac`, added menu entry
- `strings.json` — menu label, step title/description, field labels and descriptions
- `domain_coordinators/hvac.py` — expanded constructor params, forwarded to sub-controllers
- `__init__.py` — reads HVAC config from CM entry, passes to HVACCoordinator
- `const.py` — version bump to 3.8.6
