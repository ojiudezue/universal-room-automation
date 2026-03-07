# v3.8.0 — HVAC Coordinator H1: Core + Zone Management + Preset + E6 Signal

## What Ships

### HVAC Coordinator (priority 30)
New domain coordinator managing HVAC zones, presets, and energy constraint response.

**New Files:**
- `domain_coordinators/hvac.py` — HVACCoordinator main class
- `domain_coordinators/hvac_zones.py` — ZoneManager with auto-discovery from CONF_ZONE_THERMOSTAT
- `domain_coordinators/hvac_preset.py` — PresetManager with seasonal range adjustment
- `domain_coordinators/hvac_const.py` — Constants, seasonal defaults, house state mapping

**Features:**
1. **Zone auto-discovery** — reads thermostats from existing zone config (CONF_ZONE_THERMOSTAT)
2. **House state -> preset mapping** — automatically sets away/home/sleep/vacation presets
3. **Seasonal range defaults** — summer/shoulder/winter preset temperature ranges
4. **Room condition aggregation** — reads occupancy and temperature from room coordinators per zone
5. **Self-driven decision cycle** — 5-minute periodic evaluation + immediate on house state change
6. **Energy constraint response** — listens to SIGNAL_ENERGY_CONSTRAINT, tracks mode/offset
7. **Sleep protection** — configurable max offset during sleep hours
8. **Diagnostics skeleton** — DecisionLogger, ComplianceTracker, AnomalyDetector wired in

### E6 Completion: Energy -> HVAC Signal
The Energy Coordinator now fires `SIGNAL_ENERGY_CONSTRAINT` via HA dispatcher whenever the HVAC constraint mode changes. Extended `EnergyConstraint` dataclass with `reason`, `solar_class`, `forecast_high_temp`, `soc` fields.

### Sensors
- `sensor.ura_hvac_coordinator_mode` — current operating mode (normal/pre_cool/coast/shed)
- `sensor.ura_hvac_coordinator_zone_{n}_status` — per-zone HVAC status with rich attributes
- `sensor.ura_hvac_coordinator_anomaly` — anomaly detection status (diagnostic)
- `sensor.ura_hvac_coordinator_compliance` — compliance tracking (diagnostic)

### Switch
- `switch.ura_hvac_coordinator_enabled` — enable/disable toggle

## Modified Files
- `const.py` — version bump to 3.8.0
- `__init__.py` — HVAC coordinator registration in CM block
- `switch.py` — HVAC enable/disable toggle added
- `sensor.py` — HVAC sensors added to CM entry + sensor classes
- `domain_coordinators/signals.py` — EnergyConstraint extended with 4 new fields
- `domain_coordinators/energy.py` — E6: fires SIGNAL_ENERGY_CONSTRAINT on mode change

## Review Findings Fixed
- Used ServiceCallAction pattern (then switched to direct service calls for self-driven model)
- Fixed falsy 0.0 temperature check (use `is not None` instead of truthiness)
- Added vacation preset to seasonal defaults
- Wrapped diagnostics setup in try/except
- Fixed room data lookup to use config entries (not non-existent "rooms" key)
- Added self-driven decision cycle (Energy-style timer) since intent system doesn't route to HVAC
- Immediate decision cycle on house state change for prompt preset response
