# v3.8.4 — Fan Controller + Cover Controller (H3)

## What Ships

### Fan Controller (`hvac_fans.py`)
Manages room ceiling/portable fans with:
- **Temperature hysteresis**: ON at setpoint + 2F, OFF at setpoint + 0.5F (1.5F hysteresis band)
- **Speed scaling**: Low (33%) at +2-3F, Med (66%) at +3-5F, High (100%) at >+5F
- **Occupancy gating**: 5-minute vacancy hold before turning off
- **Minimum runtime**: 10 minutes (vacancy overrides)
- **Energy fan_assist**: Activates fans when Energy Coordinator signals coast mode and room is 1F+ above setpoint
- **Humidity fans**: ON at 60% RH, OFF at 50% RH (10% hysteresis band)

Fan discovery reads `CONF_FANS` and `CONF_HUMIDITY_FANS` from room config entries that belong to HVAC zones. Supports both `fan.*` entities (with speed control) and `switch.*` entities (on/off only).

### Cover Controller (`hvac_covers.py`)
Manages common area blinds for solar gain reduction:
- **Solar window**: Apr-Oct, 1PM-6PM
- **Temperature hysteresis**: Close at 85F outdoor, open at 80F (5F band)
- **Manual override respect**: 2-hour backoff when cover is manually moved
- **Garage exclusion**: Covers with `device_class=garage` are excluded
- **Command window**: 120s window to avoid false manual override detection during cover movement

Cover discovery reads from Coordinator Manager `CONF_HVAC_COVER_ENTITIES` (explicit) and room config `CONF_COVERS` (auto-discovery from zone rooms).

### Mode Sensor Attributes
The existing `sensor.ura_hvac_coordinator_mode` now includes:
- `active_fans`: count of rooms with fans currently running
- `fan_assist_active`: whether energy fan_assist is driving fans
- `covers_closed`: whether solar gain covers are closed
- `managed_covers`: total managed cover count

## New Files
- `domain_coordinators/hvac_fans.py` — `FanController` class
- `domain_coordinators/hvac_covers.py` — `CoverController` class

## Modified Files
- `domain_coordinators/hvac_const.py` — fan speed, humidity, cover constants
- `domain_coordinators/hvac.py` — FanController/CoverController integration
- `const.py` — version bump to 3.8.4
