# HVAC Coordinator Implementation Plan

**Version:** v3.8.0
**Parent Docs:** HVAC_COORDINATOR_DESIGN.md, PLANNING_v3.6.0_REVISED.md (C6), ENERGY_HVAC_QUESTIONS.md
**Status:** Planning
**Date:** 2026-03-07
**Priority:** 30 (below Energy at 40, Safety at 100, Security at 80)

---

## 1. SCOPE & MISSION

### Primary Mission
Cost management and zone comfort. The HVAC Coordinator is the active controller
for all HVAC zones, ceiling/portable fans, and common area covers. It is
energy-aware, weather-aware, and condition-aware (indoor + outdoor).

### What Ships
1. **Zone thermostat management** — 3 Carrier Infinity zones, room-aware aggregation
2. **Preset management** — house state → preset, seasonal range adjustment, time schedules
3. **Energy constraint response** — consume `SIGNAL_ENERGY_CONSTRAINT` from Energy Coordinator
4. **Manual override arrester** — subsume existing Zone 2/3 YAML automations natively
5. **AC reset** — stuck heating/cooling cycle detection and recovery
6. **Fan coordination** — ceiling/portable fans with hysteresis, energy-aware
7. **Common area cover control** — south/west blinds during peak solar gain
8. **Predictive sensors** — pre-cool likelihood, comfort violation risk, demand forecast
9. **Weather-aware pre-conditioning** — forecast-driven pre-cool/pre-heat
10. **Sleep protection** — limited offsets during sleep hours

### What Does NOT Ship
- Per-person comfort preferences (deferred — Comfort Coordinator if built)
- Circadian lighting (different domain entirely)
- Portable heater/dehumidifier control (marginal, can be room-level automation)
- Load shedding execution (stubbed in Energy, remains off by default)

### Comfort Coordinator Decision
Fan coordination moves to HVAC. The Comfort Coordinator (C7) retains only:
circadian lighting, per-person preferences, comfort scoring, portable device
control. This is thin enough to defer indefinitely. If built later, it signals
HVAC via `SIGNAL_COMFORT_REQUEST` for zone adjustments it can't achieve locally.

---

## 2. ARCHITECTURE

### Coordinator Position

```
ENERGY COORDINATOR (priority 40)
    │
    │ SIGNAL_ENERGY_CONSTRAINT:
    │   mode: normal|pre_cool|pre_heat|coast|shed
    │   setpoint_offset: -3 to +4°F
    │   occupied_only: bool
    │   max_runtime_minutes: int|null
    │   fan_assist: bool
    │   reason: str
    │   solar_class: str
    │   forecast_high_temp: float|null
    │   soc: int|null
    │
    ▼
HVAC COORDINATOR (priority 30)
    │
    ├─── Zone Manager (3 zones → thermostats)
    │    ├── Room Aggregator (rooms → zone conditions)
    │    ├── Preset Manager (house state + seasonal ranges)
    │    ├── Override Arrester (manual detection + severity response)
    │    └── AC Reset Monitor (stuck cycle detection)
    │
    ├─── Fan Controller (all room fans, hysteresis)
    │
    └─── Cover Controller (common area blinds, solar gain)
```

### Energy Constraint Enhancement (E6 completion)

The existing Energy Coordinator stub (`_update_hvac_constraint()`) will be
enhanced to:

1. **Fire `SIGNAL_ENERGY_CONSTRAINT` via HA dispatcher** instead of just
   setting internal state. HVAC listens via `async_dispatcher_connect`.
2. **Richer constraint payload** — add `pre_heat` mode, `fan_assist` flag,
   `solar_class`, `forecast_high_temp`, `soc` for HVAC decision-making.
3. **Publish on transitions** — TOU period changes, significant solar/weather
   changes, not just every 5-min cycle.

The `EnergyConstraint` dataclass in `signals.py` already has the right shape.
Energy just needs to actually dispatch it.

### Zone-to-Room Mapping

HVAC zones are read from existing `CONF_ZONE_THERMOSTAT` on each URA zone.
The coordinator discovers which rooms belong to each zone via zone membership.
Room weights default to 1.0 for primary rooms and can be configured.

```
Zone 1 (climate.thermostat_bryant_wifi_studyb_zone_1) → Master Suite rooms
Zone 2 (climate.up_hallway_zone_2) → Upstairs rooms
Zone 3 (climate.back_hallway_zone_3) → Main living rooms
```

The coordinator auto-discovers zone→thermostat mappings at startup by reading
`CONF_ZONE_THERMOSTAT` from each zone entry. No hardcoded entity IDs.

---

## 3. FAN COORDINATION WITH HYSTERESIS

Fans are cheaper conditioning devices than HVAC compressors. The fan controller
uses proper hysteresis to prevent cycling.

### Hysteresis Model

```
Fan ON trigger:  room_temp > setpoint + activation_delta
Fan OFF trigger: room_temp < setpoint + deactivation_delta

where: deactivation_delta = activation_delta - hysteresis_band

Example (cooling, setpoint 74°F):
  activation_delta  = +2.0°F  → fan ON at 76°F
  hysteresis_band   = 1.5°F
  deactivation_delta = +0.5°F → fan OFF at 74.5°F
```

### Fan Speed Scaling

| Room Temp Delta | Fan Speed | Rationale |
|-----------------|-----------|-----------|
| +2.0 to +3.0°F | Low (33%) | Mild assist |
| +3.0 to +5.0°F | Medium (66%) | Moderate assist |
| > +5.0°F | High (100%) | Maximum assist |

### Fan Triggers (priority order)

1. **Energy fan_assist** — Energy constraint says run fans to reduce HVAC load
   (during coast mode). Hysteresis: ON at setpoint, OFF at setpoint - 1°F.
2. **Temperature delta** — Room warmer than cooling setpoint by activation_delta.
   Uses full hysteresis model above.
3. **Humidity** — Room humidity > threshold (default 60%). Hysteresis: ON at
   60%, OFF at 50% (10% band).
4. **Occupancy gate** — Fans only run in occupied rooms. Turn off in vacant
   rooms after 5-min vacancy hold (allows brief exits without cycling).

### Minimum Runtime

Fans have a 10-minute minimum runtime to prevent short cycling. Once activated,
they stay on for at least 10 minutes regardless of condition changes (except
vacancy).

---

## 4. CONTROL STRATEGY

### Preset-First Philosophy

The primary control lever is Carrier presets (away/home/sleep/wake). The
coordinator reads and edits preset temperature ranges — this keeps manual
thermostat use compatible with automation.

**Seasonal Preset Range Adjustment:**

| Season | Home Cool | Home Heat | Sleep Cool | Sleep Heat | Away Cool | Away Heat |
|--------|-----------|-----------|------------|------------|-----------|-----------|
| Summer (Jun-Sep) | 77°F | 70°F | 76°F | 70°F | 82°F | 60°F |
| Shoulder (Mar-May, Oct-Nov) | 74°F | 70°F | 73°F | 68°F | 80°F | 62°F |
| Winter (Dec-Feb) | 72°F | 70°F | 70°F | 68°F | 78°F | 60°F |

These are configurable defaults. The coordinator adjusts preset ranges at
season boundaries and on startup. Users can override via options flow.

### House State → Preset Mapping

| House State | Preset | Notes |
|-------------|--------|-------|
| HOME_DAY | home | Normal comfort |
| HOME_EVENING | home | Same as day (comfort) |
| SLEEP | sleep | Limited energy offsets |
| AWAY | away | Wide band, minimal conditioning |
| VACATION | vacation | Extended absence |
| ARRIVING | home | Pre-condition if energy budget allows |

### Time-Based Schedule (per zone, configurable)

Subsumes the hardcoded schedules from the arrester automations:

| Zone | Wake | Day | Away | Evening | Sleep |
|------|------|-----|------|---------|-------|
| Zone 1 (Master) | 6-8 | 8-22 | — | — | 22-6 |
| Zone 2 (Upstairs) | 6-8 | — | 8-17 | 17-22 | 22-6 |
| Zone 3 (Main) | 6-8 | 8-22 | — | — | 22-6 |

The schedule is a fallback when house state is unavailable or stale. When
presence is active, house state takes precedence over schedule.

### Control Modes (from Energy)

| Energy Mode | HVAC Strategy | Setpoint Change | Fan Action |
|-------------|---------------|-----------------|------------|
| **normal** | HYBRID (preset + tune) | User preference | Occupancy-based |
| **pre_cool** | TEMPERATURE | -2 to -3°F | Auto |
| **pre_heat** | TEMPERATURE | +2 to +3°F | Auto |
| **coast** | TEMPERATURE | +2 to +4°F | fan_assist ON |
| **shed** | PRESET | away preset | Off |

---

## 5. MANUAL OVERRIDE ARRESTER

Subsumes `automation.back_hallway_hvac_arrester` (v10),
`automation.upstairs_zone_hvac_arrester`, and `back_hallway_hvac_arrester2`.

### Detection

Triggers on `preset_mode` changing to `manual` or `target_temp_high/low`
changing outside expected range. Listens via HA state change events on all
zone climate entities.

### Two-Tier Severity Response

**Severe violation (>3°F from effective setpoint):**
- 2-minute grace period (re-check after delay)
- If still violated: immediate revert to time-based preset
- NM notification: critical severity

**Normal violation (>1°F outside ±1°F tolerance):**
- 5-minute grace period
- If still violated: compromise temp (effective ±1°F toward user's choice)
- Hold compromise for 30 minutes
- After 30 min: revert to time-based preset
- NM notification: medium severity

**HVAC mode violation (not heat_cool):**
- Immediate correction to heat_cool after grace period
- NM notification: low severity

### Improvements Over YAML Automations

1. **Energy-aware tolerance** — During coast mode, widen tolerance band since
   effective setpoint is already shifted. A manual override during coast that
   moves toward normal comfort is less concerning.
2. **Occupancy-aware** — If zone is vacant, don't compromise — just revert.
   Don't waste energy on an empty zone's manual override.
3. **History tracking** — Count overrides per zone per day. Frequent overrides
   suggest the preset ranges need adjustment (surfaces as a predictive sensor).
4. **NM integration** — Use URA Notification Manager instead of direct Pushover.

---

## 6. AC RESET (STUCK CYCLE RECOVERY)

### Detection

Monitor each zone for: `hvac_action` still `cooling`/`heating` after
`current_temperature` has been at or past setpoint for N minutes (default 10,
configurable).

### Action

```
1. Set hvac_mode to "off"
2. Wait 60 seconds
3. Set hvac_mode back to "heat_cool"
4. Log via NM (medium severity)
5. Track reset count per zone per day
```

### Safety

- Maximum 2 resets per zone per day (prevent infinite cycling)
- If 2 resets in one day, send high-severity NM alert suggesting HVAC service
- Does not reset during first 15 minutes after any setpoint change (allow
  system to stabilize)

---

## 7. COMMON AREA COVER CONTROL

### Scope

Common area covers only (living room, kitchen, dining — south/west facing).
Room-level covers remain under room automation control.

### Config

Cover entities selected in coordinator config flow (multi-entity selector,
domain=cover). Orientation (south/west) tagged per cover.

### Logic

- **Close** south/west covers when: month is Apr-Oct AND hour is 13-18 AND
  outdoor temp > 85°F AND solar_class in (excellent, good)
- **Open** when: hour > 18 OR outdoor temp < 85°F OR solar_class in (poor, very_poor)
- **Override respect**: If cover position changed manually, back off for 2 hours
- Hysteresis: 5°F band on temperature (close at 85°F, open at 80°F)

---

## 8. PREDICTIVE SENSORS

### Pre-Cool Likelihood

`sensor.ura_hvac_pre_cool_likelihood` — percentage (0-100)

Inputs: tomorrow's forecast high, TOU peak start time, current SOC, solar class.
If forecast high > 90°F AND solar is good AND SOC allows, pre-cool is likely.
Published by start of day, updated at sunrise refresh.

### Comfort Violation Risk

`sensor.ura_hvac_comfort_violation_risk` — low/medium/high

Inputs: current indoor temp trend, energy constraint mode, hours until peak
ends, fan availability. "High" means indoor temp likely to exceed comfort bound
during current energy constraint.

### Zone Demand Forecast

`sensor.ura_hvac_zone_{n}_demand` — state: idle/low/moderate/high

Per-zone estimate of conditioning demand for the next 2 hours. Based on:
outdoor temp trend, indoor temp vs setpoint, occupancy prediction, TOU period.

### Override Frequency

`sensor.ura_hvac_override_frequency` — count of manual overrides today

High override frequency (>3/day) suggests preset ranges are mismatched with
user expectations. Attribute shows per-zone breakdown and most common direction
(warmer/cooler) to guide seasonal adjustments.

---

## 9. WEATHER-AWARE PRE-CONDITIONING

### Pre-Cool (Summer)

When forecast high > threshold (default 95°F) AND TOU peak starts in <3 hours
AND Energy publishes `pre_cool`:
- Lower cooling setpoints by 2-3°F in occupied zones
- Start ceiling fans at low speed
- Pre-condition before peak to build thermal mass

### Pre-Heat (Winter)

When forecast low < threshold (default 35°F) AND off-peak ending in <2 hours:
- Raise heating setpoints by 2-3°F
- Build thermal mass before rates increase

### Data Sources

- Outdoor temperature: weather entity (inherited from house config → energy config)
- Forecast high/low: from Energy Coordinator's forecast data
  (`forecast_today.predicted_production_kwh` implies solar, weather entity attrs
  have forecast)
- Indoor temps: per-zone aggregated from room sensors

---

## 10. ENERGY CONSTRAINT INTERFACE (E6 COMPLETION)

This work modifies the Energy Coordinator to complete the deferred E6 items.

### Changes to energy.py

1. **`_update_hvac_constraint()`** enhanced to build full `EnergyConstraint`:
   ```python
   constraint = EnergyConstraint(
       mode=mode,                    # normal|pre_cool|pre_heat|coast|shed
       setpoint_offset=offset,
       occupied_only=True,
       max_runtime_minutes=None,     # future: limit HVAC during peak
       fan_assist=(mode == "coast"),
       reason=reason,
       solar_class=self._battery.classify_solar_day(),
       forecast_high_temp=forecast_high,
       soc=self._battery.battery_soc,
   )
   ```

2. **Fire dispatcher signal** on constraint change:
   ```python
   if constraint != self._last_published_constraint:
       async_dispatcher_send(self.hass, SIGNAL_ENERGY_CONSTRAINT, constraint)
       self._last_published_constraint = constraint
   ```

3. **Add `pre_heat` mode** to `_update_hvac_constraint()`:
   - Winter off-peak, forecast low < 35°F, SOC > 80%

### Changes to signals.py

Extend `EnergyConstraint` with additional fields:
```python
@dataclass
class EnergyConstraint:
    mode: str
    setpoint_offset: float
    occupied_only: bool = True
    max_runtime_minutes: int | None = None
    fan_assist: bool = False
    reason: str = ""
    solar_class: str = ""
    forecast_high_temp: float | None = None
    soc: int | None = None
```

---

## 11. FILE STRUCTURE

### New Files

| File | Purpose | Est. Lines |
|------|---------|------------|
| `domain_coordinators/hvac.py` | HVACCoordinator main class, zone management, decision cycle | 400 |
| `domain_coordinators/hvac_zones.py` | ZoneManager, RoomAggregator, zone state tracking | 300 |
| `domain_coordinators/hvac_preset.py` | PresetManager, seasonal ranges, time schedules, arrester | 350 |
| `domain_coordinators/hvac_fans.py` | FanController with hysteresis, occupancy gating | 250 |
| `domain_coordinators/hvac_covers.py` | CoverController for common area blinds | 150 |
| `domain_coordinators/hvac_const.py` | Constants, defaults, config keys | 100 |

### Modified Files

| File | Change |
|------|--------|
| `__init__.py` | Register HVAC coordinator in CM block |
| `sensor.py` | Add HVAC sensors (mode, zone status x3, predictive x4, operations x3, anomaly, compliance) |
| `binary_sensor.py` | Energy constrained binary sensor |
| `switch.py` | HVAC enable/disable toggle |
| `config_flow.py` | HVAC config step (cover entities, zone weights, seasonal temps) |
| `const.py` | HVAC config keys, version bump |
| `strings.json` | HVAC config flow labels |
| `domain_coordinators/energy.py` | E6 completion: fire SIGNAL_ENERGY_CONSTRAINT |
| `domain_coordinators/signals.py` | Extend EnergyConstraint dataclass |

**Estimated total:** ~1550 new, ~400 modified

---

## 12. SENSOR INTERFACE & DEVICE GROUPING

### Device Hierarchy

All HVAC sensors group under a single device in the HA device registry,
following the same pattern as Safety, Security, and Energy coordinators:

```
URA: Coordinator Manager
  └── URA: HVAC Coordinator          ← all HVAC sensors live here
        identifiers: ("universal_room_automation", "hvac_coordinator")
        model: "HVAC Coordinator"
        via_device: ("universal_room_automation", "coordinator_manager")
```

The `_hvac_device_info()` helper in sensor.py returns this DeviceInfo.
Every HVAC sensor class sets `self._attr_device_info = _hvac_device_info()`.

### Sensor Grouping by Function

Sensors are organized into logical groups. Within the HA device page, primary
sensors appear at the top (no entity_category), diagnostic sensors below
(EntityCategory.DIAGNOSTIC). This gives the user a clean hierarchy:

**At-a-glance sensors** (primary, no entity_category):

| Entity ID | State | Icon | What the User Sees |
|-----------|-------|------|--------------------|
| `sensor.ura_hvac_coordinator_mode` | normal/pre_cool/coast/shed | mdi:thermostat | Current HVAC operating mode — "What is the system doing?" |
| `sensor.ura_hvac_coordinator_pre_cool_likelihood` | 0-100% | mdi:snowflake-alert | "Will pre-cooling happen today?" |
| `sensor.ura_hvac_coordinator_comfort_risk` | low/medium/high | mdi:thermometer-alert | "Are rooms at risk of getting uncomfortable?" |
| `binary_sensor.ura_hvac_coordinator_energy_constrained` | on/off | mdi:flash-alert | "Is energy limiting HVAC right now?" |

**Per-zone status sensors** (diagnostic — one per HVAC zone):

| Entity ID | State | What It Shows |
|-----------|-------|---------------|
| `sensor.ura_hvac_coordinator_zone_1_status` | heat_cool/off/... | Zone 1 (Master Suite) full status |
| `sensor.ura_hvac_coordinator_zone_2_status` | heat_cool/off/... | Zone 2 (Upstairs) full status |
| `sensor.ura_hvac_coordinator_zone_3_status` | heat_cool/off/... | Zone 3 (Main Living) full status |

**Per-zone demand forecast** (diagnostic):

| Entity ID | State | What It Shows |
|-----------|-------|---------------|
| `sensor.ura_hvac_coordinator_zone_1_demand` | idle/low/moderate/high | Near-term conditioning need |
| `sensor.ura_hvac_coordinator_zone_2_demand` | idle/low/moderate/high | Near-term conditioning need |
| `sensor.ura_hvac_coordinator_zone_3_demand` | idle/low/moderate/high | Near-term conditioning need |

**Operations sensors** (diagnostic):

| Entity ID | State | What It Shows |
|-----------|-------|---------------|
| `sensor.ura_hvac_coordinator_override_frequency` | count (int) | Manual overrides today |
| `sensor.ura_hvac_coordinator_ac_resets_today` | count (int) | Stuck-cycle resets today |
| `sensor.ura_hvac_coordinator_active_fans` | count (int) | How many fans running now |
| `sensor.ura_hvac_coordinator_anomaly` | nominal/advisory/alert/critical/learning | Anomaly detection status |
| `sensor.ura_hvac_coordinator_compliance` | 0-100% | Command compliance rate (7-day) |

### Zone Status Attributes (rich, per zone)

Each zone status sensor carries detailed attributes. This keeps the sensor
count manageable while providing drill-down data for dashboards and automations:

```yaml
# sensor.ura_hvac_coordinator_zone_1_status
state: "heat_cool"
attributes:
  friendly_name: "Master Suite"
  zone_id: "zone_1_master"
  climate_entity: "climate.thermostat_bryant_wifi_studyb_zone_1"
  # Current state
  preset_mode: "home"
  hvac_action: "cooling"
  current_temperature: 75
  current_humidity: 42
  # Effective setpoints (after energy offsets)
  effective_cool_setpoint: 77
  effective_heat_setpoint: 70
  # User base setpoints (before offsets)
  user_cool_setpoint: 74
  user_heat_setpoint: 70
  # Energy
  energy_offset_applied: 3.0
  energy_constraint_mode: "coast"
  # Occupancy
  any_room_occupied: true
  occupied_rooms: ["master_bedroom"]
  occupancy_weight: 1.0
  # Schedule
  is_sleep_hours: false
  current_schedule_preset: "home"
  # Fans
  active_fans: ["fan.ceilingfan_fanimaton_rf304_25_masterbedroom"]
  fan_count: 1
  # Override tracking
  last_override: null
  override_count_today: 0
  # AC reset tracking
  ac_reset_count_today: 0
  # Demand
  demand_level: "low"
```

### Pre-Cool Likelihood Attributes

```yaml
# sensor.ura_hvac_coordinator_pre_cool_likelihood
state: "72"  # percentage
attributes:
  forecast_high: 98
  peak_start_hour: 14
  hours_until_peak: 5
  battery_soc: 45
  solar_class: "good"
  recommendation: "Pre-cool likely before 2pm peak"
```

### Comfort Risk Attributes

```yaml
# sensor.ura_hvac_coordinator_comfort_risk
state: "medium"
attributes:
  worst_zone: "zone_3_main"
  worst_zone_temp: 77.5
  worst_zone_setpoint: 74
  energy_constraint_active: true
  constraint_mode: "coast"
  hours_remaining: 2.5
  fan_assist_active: true
  mitigation: "Fans running in occupied rooms"
```

### Entity Naming Convention

All HVAC sensors follow the pattern:
`{domain}.ura_hvac_coordinator_{sensor_name}`

The `ura_hvac_coordinator_` prefix is auto-generated by HA from the device name
"URA: HVAC Coordinator" + the entity's `_attr_name`. Sensor classes set only
the short name:

```python
class HVACModeSensor(SensorEntity):
    _attr_name = "Mode"                      # → sensor.ura_hvac_coordinator_mode
    _attr_unique_id = "hvac_coordinator_mode"
    _attr_icon = "mdi:thermostat"
    _attr_device_info = _hvac_device_info()

class HVACZoneStatusSensor(SensorEntity):
    _attr_name = "Zone 1 Status"             # → sensor.ura_hvac_coordinator_zone_1_status
    _attr_entity_category = EntityCategory.DIAGNOSTIC
```

---

## 13. CONFIG FLOW UI

### Design Principles

1. **Minimal setup** — enable toggle only. Zero config required to start.
2. **Smart defaults** — seasonal temps, sleep schedules, fan thresholds all
   have sensible defaults. Most users never touch these.
3. **Auto-discovery** — zone thermostats read from existing zone config
   (`CONF_ZONE_THERMOSTAT`). No duplicate entity selection.
4. **Progressive disclosure** — simple fields first, advanced in collapsible
   section (via HA's sections feature if available, else ordered last).
5. **Clear labels** — every field has a label AND a description explaining
   what it does in plain English.

### Setup Step: Enable Toggle

The HVAC coordinator enable toggle lives in the existing Coordinator Manager
setup flow alongside Safety, Security, Energy, etc:

```python
# In async_step_coordinator_manager (existing):
vol.Optional(CONF_HVAC_ENABLED, default=False): bool,
```

**strings.json:**
```json
"hvac_enabled": "Enable HVAC Coordinator",
```
Description: "Manages thermostats, fans, and covers based on occupancy, energy
constraints, and weather. Requires zone thermostats to be configured."

### Options Step: `async_step_coordinator_hvac`

Split into **two logical sections** for clarity:

#### Section 1: Zone Comfort Settings

Per-zone setpoint and schedule configuration. Zones auto-discovered — the UI
shows only zones that have a thermostat configured via `CONF_ZONE_THERMOSTAT`.

```python
# For each discovered zone (dynamic schema):
vol.Optional(
    f"hvac_zone_{n}_cool_setpoint",
    default=self._get_current(f"hvac_zone_{n}_cool_setpoint", 74),
): selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=68, max=82, step=1,
        unit_of_measurement="°F",
        mode=selector.NumberSelectorMode.SLIDER,
    )
),
vol.Optional(
    f"hvac_zone_{n}_heat_setpoint",
    default=self._get_current(f"hvac_zone_{n}_heat_setpoint", 70),
): selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=60, max=75, step=1,
        unit_of_measurement="°F",
        mode=selector.NumberSelectorMode.SLIDER,
    )
),
vol.Optional(
    f"hvac_zone_{n}_sleep_start",
    default=self._get_current(f"hvac_zone_{n}_sleep_start", 22),
): selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0, max=23, step=1,
        unit_of_measurement="h",
        mode=selector.NumberSelectorMode.BOX,
    )
),
vol.Optional(
    f"hvac_zone_{n}_sleep_end",
    default=self._get_current(f"hvac_zone_{n}_sleep_end", 7),
): selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0, max=23, step=1,
        unit_of_measurement="h",
        mode=selector.NumberSelectorMode.BOX,
    )
),
```

#### Section 2: Covers & Thresholds

```python
# Common area covers
vol.Optional(
    CONF_HVAC_COVER_ENTITIES,
    default=self._get_current(CONF_HVAC_COVER_ENTITIES, []),
): selector.EntitySelector(
    selector.EntitySelectorConfig(domain="cover", multiple=True)
),

# Protection thresholds
vol.Optional(
    CONF_HVAC_MAX_SLEEP_OFFSET,
    default=self._get_current(CONF_HVAC_MAX_SLEEP_OFFSET, 1.5),
): selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0.5, max=4.0, step=0.5,
        unit_of_measurement="°F",
        mode=selector.NumberSelectorMode.SLIDER,
    )
),
vol.Optional(
    CONF_HVAC_COMPROMISE_MINUTES,
    default=self._get_current(CONF_HVAC_COMPROMISE_MINUTES, 30),
): selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=10, max=60, step=5,
        unit_of_measurement="min",
        mode=selector.NumberSelectorMode.SLIDER,
    )
),
vol.Optional(
    CONF_HVAC_AC_RESET_TIMEOUT,
    default=self._get_current(CONF_HVAC_AC_RESET_TIMEOUT, 10),
): selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=5, max=30, step=1,
        unit_of_measurement="min",
        mode=selector.NumberSelectorMode.BOX,
    )
),
vol.Optional(
    CONF_HVAC_FAN_ACTIVATION_DELTA,
    default=self._get_current(CONF_HVAC_FAN_ACTIVATION_DELTA, 2.0),
): selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=1.0, max=5.0, step=0.5,
        unit_of_measurement="°F",
        mode=selector.NumberSelectorMode.SLIDER,
    )
),
vol.Optional(
    CONF_HVAC_FAN_HYSTERESIS,
    default=self._get_current(CONF_HVAC_FAN_HYSTERESIS, 1.5),
): selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0.5, max=3.0, step=0.5,
        unit_of_measurement="°F",
        mode=selector.NumberSelectorMode.SLIDER,
    )
),
vol.Optional(
    CONF_HVAC_FAN_MIN_RUNTIME,
    default=self._get_current(CONF_HVAC_FAN_MIN_RUNTIME, 10),
): selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=5, max=30, step=5,
        unit_of_measurement="min",
        mode=selector.NumberSelectorMode.SLIDER,
    )
),
```

### strings.json Labels & Descriptions

```json
"coordinator_hvac": {
  "title": "🌡️ HVAC Coordinator",
  "description": "Manages thermostats, ceiling fans, and common area covers. Responds to energy constraints, adjusts presets by house state and season, and prevents energy-wasteful manual overrides.",
  "data": {
    "hvac_zone_1_cool_setpoint": "Zone 1 (Master) Cooling Setpoint",
    "hvac_zone_1_heat_setpoint": "Zone 1 (Master) Heating Setpoint",
    "hvac_zone_1_sleep_start": "Zone 1 (Master) Sleep Start Hour",
    "hvac_zone_1_sleep_end": "Zone 1 (Master) Sleep End Hour",
    "hvac_zone_2_cool_setpoint": "Zone 2 (Upstairs) Cooling Setpoint",
    "hvac_zone_2_heat_setpoint": "Zone 2 (Upstairs) Heating Setpoint",
    "hvac_zone_2_sleep_start": "Zone 2 (Upstairs) Sleep Start Hour",
    "hvac_zone_2_sleep_end": "Zone 2 (Upstairs) Sleep End Hour",
    "hvac_zone_3_cool_setpoint": "Zone 3 (Main) Cooling Setpoint",
    "hvac_zone_3_heat_setpoint": "Zone 3 (Main) Heating Setpoint",
    "hvac_zone_3_sleep_start": "Zone 3 (Main) Sleep Start Hour",
    "hvac_zone_3_sleep_end": "Zone 3 (Main) Sleep End Hour",
    "hvac_cover_entities": "Common Area Covers",
    "hvac_max_sleep_offset": "Max Sleep Temperature Offset",
    "hvac_compromise_minutes": "Override Compromise Duration",
    "hvac_ac_reset_timeout": "AC Stuck Cycle Timeout",
    "hvac_fan_activation_delta": "Fan Activation Threshold",
    "hvac_fan_hysteresis": "Fan Hysteresis Band",
    "hvac_fan_min_runtime": "Fan Minimum Runtime"
  },
  "data_description": {
    "hvac_zone_1_cool_setpoint": "Base cooling temperature for Zone 1 (Master Suite). Seasonally adjusted. Energy offsets apply on top of this.",
    "hvac_zone_1_heat_setpoint": "Base heating temperature for Zone 1 (Master Suite).",
    "hvac_zone_1_sleep_start": "Hour when Zone 1 enters sleep mode (24h format). During sleep, energy offsets are limited.",
    "hvac_zone_1_sleep_end": "Hour when Zone 1 exits sleep mode (24h format).",
    "hvac_zone_2_cool_setpoint": "Base cooling temperature for Zone 2 (Upstairs).",
    "hvac_zone_2_heat_setpoint": "Base heating temperature for Zone 2 (Upstairs).",
    "hvac_zone_2_sleep_start": "Hour when Zone 2 enters sleep mode. Kids' zone defaults to 9pm.",
    "hvac_zone_2_sleep_end": "Hour when Zone 2 exits sleep mode.",
    "hvac_zone_3_cool_setpoint": "Base cooling temperature for Zone 3 (Main Living).",
    "hvac_zone_3_heat_setpoint": "Base heating temperature for Zone 3 (Main Living).",
    "hvac_zone_3_sleep_start": "Hour when Zone 3 enters sleep mode. Set to 0 to disable sleep mode for this zone.",
    "hvac_zone_3_sleep_end": "Hour when Zone 3 exits sleep mode.",
    "hvac_cover_entities": "Select south/west-facing common area covers. These close automatically during peak solar hours in summer to reduce cooling load.",
    "hvac_max_sleep_offset": "Maximum temperature offset allowed during sleep hours. Limits energy-saving adjustments to prevent sleep disruption. Default: 1.5°F.",
    "hvac_compromise_minutes": "When someone manually adjusts a thermostat outside tolerance, the system compromises at a midpoint for this duration before reverting to the scheduled preset. Default: 30 minutes.",
    "hvac_ac_reset_timeout": "Minutes the HVAC can be stuck (still heating/cooling after reaching setpoint) before the system cycles it off and back on. Default: 10 minutes.",
    "hvac_fan_activation_delta": "Degrees above the cooling setpoint before ceiling fans turn on. Lower = more aggressive fan use, higher = less. Default: 2°F.",
    "hvac_fan_hysteresis": "Temperature band below the activation point where fans stay on. Prevents rapid on/off cycling. Fan turns off at (activation_delta - hysteresis) above setpoint. Default: 1.5°F.",
    "hvac_fan_min_runtime": "Minimum minutes a fan stays on once activated, preventing short cycling. Default: 10 minutes."
  }
}
```

### What the User Sees (Step by Step)

1. **Coordinator Manager setup** → Checkbox: "Enable HVAC Coordinator"
2. **First reconfig** → Single page with all settings, sensible defaults pre-filled:
   - Top: Zone setpoints grouped by zone name (sliders)
   - Middle: Sleep schedules (simple number boxes)
   - Bottom: Cover entities (entity picker), thresholds (sliders)
3. **Every field** has a label ("Fan Activation Threshold") AND a description
   paragraph explaining what it does and what the default means
4. **Zero required fields** — all have defaults. Enable and go.

Zone thermostats are **not shown** — they're auto-discovered from zone config.
If no zones have thermostats configured, the coordinator logs a warning and
operates in observation-only mode (sensors populate, no actions taken).

---

## 14. DIAGNOSTICS & ANOMALY DETECTION (C0-diag)

The HVAC Coordinator wires into the existing C0-diag infrastructure
(`coordinator_diagnostics.py`) following the same pattern as Safety, Security,
Presence, and Energy coordinators.

### Components Instantiated

| Component | Class | Coordinator ID | Purpose |
|-----------|-------|----------------|---------|
| Decision logging | `DecisionLogger` | — | Log every preset change, energy constraint response, arrester action, AC reset |
| Compliance | `ComplianceTracker` | — | Verify zones accepted preset/setpoint commands (2-min delay check) |
| Anomaly detection | `AnomalyDetector` | `"hvac"` | Statistical deviation from learned baselines |
| Outcome measurement | `OutcomeMeasurer` | — | Daily summary of zone satisfaction and efficiency |

### Setup Pattern (in `async_setup`)

```python
from .coordinator_diagnostics import (
    AnomalyDetector, DecisionLogger, ComplianceTracker, OutcomeMeasurer,
)

HVAC_METRICS = [
    "zone_call_frequency",     # calls per day per zone
    "short_cycle_rate",        # cycles < 10min / total cycles
    "override_frequency",      # manual overrides per day
    "comfort_deviation_hours", # hours outside comfort band per day
]

# In async_setup:
self._decision_logger = DecisionLogger(self.hass)
self._compliance = ComplianceTracker(self.hass)
self._outcome = OutcomeMeasurer(self.hass)
self.anomaly_detector = AnomalyDetector(
    hass=self.hass,
    coordinator_id="hvac",
    metric_names=HVAC_METRICS,
    minimum_samples=336,  # 14 days × 24 samples/day
)
await self.anomaly_detector.load_baselines()
```

### Decision Logging

Every significant HVAC action logs a `DecisionLog`:

| decision_type | Trigger | What's Logged |
|---------------|---------|---------------|
| `preset_change` | House state transition | scope=zone, old/new preset, reason |
| `energy_constraint` | `SIGNAL_ENERGY_CONSTRAINT` received | mode, offset, fan_assist, reason |
| `seasonal_adjust` | Season boundary or startup | scope=house, old/new ranges per zone |
| `override_arrest` | Manual override detected | scope=zone, severity, action (compromise/revert) |
| `ac_reset` | Stuck cycle recovery | scope=zone, stuck_minutes, reset_count_today |
| `fan_command` | Fan on/off/speed change | scope=room, trigger (temp/humidity/energy), speed |
| `cover_command` | Cover open/close | scope=room, reason (solar_gain/manual_expire) |
| `pre_condition` | Pre-cool/pre-heat initiated | scope=house, forecast_high, soc, peak_hours |

### Compliance Tracking

After each device command, the `ComplianceTracker` schedules a 2-minute
delayed check:

| Device Type | Commanded State Checked | Compliant If |
|-------------|------------------------|--------------|
| `climate` | `preset_mode`, `target_temp_high/low` | Preset matches, setpoints within 1°F |
| `fan` | `state` (on/off) | State matches command |
| `cover` | `position` | Position within 5% of commanded |

Non-compliance triggers:
- `override_detected = True` if climate preset changed to `manual`
- Logged to `compliance_log` table
- Surfaces in `sensor.ura_hvac_coordinator_compliance`

### Anomaly Detection Metrics

| Metric | Observation Source | What Triggers Anomaly | Implication |
|--------|-------------------|-----------------------|-------------|
| `zone_call_frequency` | Count of zone HVAC calls per day | Zone calling 3× more than baseline | Insulation issue, duct leak, window left open |
| `short_cycle_rate` | Ratio of cycles < 10min to total | Rate exceeds baseline by 2σ | Equipment issue, thermostat placement |
| `override_frequency` | Manual overrides per day | More than baseline + 2σ | Preset ranges mismatched with user preference |
| `comfort_deviation_hours` | Hours indoor temp > 2°F outside band | Deviation increasing over baseline | System undersized for conditions, or constraint too aggressive |

**Learning frequency:** Observations recorded every evaluate cycle (5 min).
Baselines build via Welford's online algorithm. Anomaly detection activates
after 14 days (336 samples at 24/day).

**Baseline persistence:** `save_baselines()` called in `async_teardown()`,
`load_baselines()` in `async_setup()`. Survives HA restarts.

### Outcome Measurement

Daily `HVACOutcome` recorded at midnight via `_save_daily_outcome()`:

```python
@dataclass
class HVACOutcome:
    zone_satisfaction_rate: float    # % of time all zones within comfort band
    simultaneous_call_pct: float    # % of cycles with ≥2 zones calling simultaneously
    cycle_efficiency: float         # avg minutes per cycle (longer = more efficient)
    override_count: int             # total manual overrides
    ac_reset_count: int             # total stuck-cycle resets
    energy_savings_kwh: float       # estimated savings from coast/pre-cool vs naive
    fan_assist_hours: float         # total fan runtime during energy constraints
```

Stored via `OutcomeMeasurer.store_outcome()` with `metrics` dict containing
these fields. Available for trending in the URA DB.

### Coordinator Interface Methods

Following the established pattern (see SecurityCoordinator):

```python
def get_anomaly_status(self) -> str:
    """Return anomaly status for sensor."""
    if self.anomaly_detector is None:
        return "not_configured"
    learning = self.anomaly_detector.get_learning_status()
    if hasattr(learning, "value") and learning.value in (
        "insufficient_data", "learning",
    ):
        return learning.value
    return self.anomaly_detector.get_worst_severity().value

def get_compliance_summary(self) -> dict[str, Any]:
    """Return compliance summary for sensor."""
    return {
        "compliance_rate": self._compliance_rate_7d,
        "overrides_today": self._override_count_today,
        "last_check": self._last_compliance_check,
        "zones_compliant": self._zones_compliant_count,
        "zones_total": len(self._zone_managers),
    }
```

### Sensors (on HVAC device, EntityCategory.DIAGNOSTIC)

| Entity ID | State | Attributes |
|-----------|-------|------------|
| `sensor.ura_hvac_coordinator_anomaly` | nominal/advisory/alert/critical/learning/insufficient_data | worst_metric, z_score, learning_status, anomalies_today, metrics (per-metric mean/std/samples) |
| `sensor.ura_hvac_coordinator_compliance` | 0-100% | overrides_today, last_check, zones_compliant, zones_total |

These follow the exact same class pattern as `SecurityAnomalySensor` and
`SecurityComplianceSensor` in sensor.py, using `_hvac_device_info()`.

### Sub-Cycle Assignment

- **H1** ships the diagnostics skeleton: `DecisionLogger`, `ComplianceTracker`,
  `AnomalyDetector` instantiation, `load_baselines`/`save_baselines`,
  `get_anomaly_status()`/`get_compliance_summary()` stubs,
  `sensor.ura_hvac_coordinator_anomaly`, `sensor.ura_hvac_coordinator_compliance`
- **H2** adds override-specific decision logging and compliance checks
- **H3** adds fan/cover compliance checks
- **H4** adds outcome measurement (`_save_daily_outcome()`) with full
  `HVACOutcome` metrics after enough data exists

---

## 15. SUB-CYCLES

### H1: Core + Zone Management + Preset + E6 Signal
**Scope:** Coordinator skeleton, zone discovery, preset management, house state
response, Energy constraint signal (E6 completion), seasonal range adjustment.

**What ships:**
- `HVACCoordinator` extending `BaseCoordinator`
- `ZoneManager` with auto-discovery from `CONF_ZONE_THERMOSTAT`
- `RoomAggregator` reading room temp/humidity/occupancy per zone
- `PresetManager` with house state → preset mapping and seasonal ranges
- Energy Coordinator fires `SIGNAL_ENERGY_CONSTRAINT` (E6 completion)
- HVAC listens and responds (normal/pre_cool/coast/shed → zone actions)
- Sleep protection (limited offsets)
- Basic sensors: `sensor.ura_hvac_mode`, zone status x3
- Diagnostics: DecisionLogger, ComplianceTracker, AnomalyDetector, anomaly + compliance sensors
- Config flow: enable toggle + options step
- Switch toggle

**Files:** hvac.py, hvac_zones.py, hvac_preset.py, hvac_const.py + mods to
energy.py, signals.py, __init__.py, sensor.py, switch.py, config_flow.py, const.py

**Est. lines:** ~900 new, ~250 modified

### H2: Override Arrester + AC Reset
**Scope:** Manual override detection, two-tier severity response, compromise
period, HVAC mode enforcement, stuck cycle recovery.

**What ships:**
- Override arrester (detect manual, grace period, compromise, revert)
- Two-tier severity (normal ±1°F vs severe >3°F)
- Energy-aware tolerance widening during coast
- HVAC mode enforcement (heat_cool)
- AC reset (stuck cycle detection, off→wait→on, max 2/day)
- NM integration for override and reset alerts
- `sensor.ura_hvac_override_frequency`

**Files:** hvac_preset.py expanded + hvac.py additions

**Est. lines:** ~300 new, ~50 modified

### H3: Fan Controller + Covers
**Scope:** Fan coordination with hysteresis, common area cover control.

**What ships:**
- `FanController` with hysteresis model (activation/deactivation deltas)
- Fan speed scaling (low/med/high by temp delta)
- Occupancy gating with 5-min vacancy hold
- 10-minute minimum runtime
- Energy fan_assist response (fans during coast)
- Humidity-triggered fans with 10% hysteresis band
- `CoverController` for common area blinds
- Solar gain logic (close south/west during Apr-Oct 13-18h when hot)
- Manual cover override respect (2-hour backoff)
- Config flow additions (cover entities, fan thresholds)

**Files:** hvac_fans.py, hvac_covers.py + config_flow.py additions

**Est. lines:** ~400 new, ~80 modified

### H4: Predictive Sensors + Weather Pre-Conditioning
**Scope:** Forward-looking intelligence.

**What ships:**
- `sensor.ura_hvac_pre_cool_likelihood` (forecast + TOU + SOC → likelihood %)
- `sensor.ura_hvac_comfort_violation_risk` (trend + constraint → risk level)
- `sensor.ura_hvac_zone_{n}_demand` (outdoor trend + indoor delta → demand)
- Weather-aware pre-conditioning triggers
- Pre-cool: forecast high > threshold AND peak approaching AND energy allows
- Pre-heat: forecast low < threshold AND off-peak ending
- Predictive pre-conditioning initiation (act before constraint arrives)
- Daily `HVACOutcome` measurement (zone satisfaction, cycle efficiency, savings)

**Files:** hvac.py additions + sensor.py additions

**Est. lines:** ~250 new, ~80 modified

---

## 16. BUILD ORDER

```
H1: Core + Zones + Presets + E6 Signal
    │   (foundation — everything depends on this)
    │
    ▼
H2: Override Arrester + AC Reset
    │   (needs zone management from H1)
    │   After deploy: disable YAML arrester automations
    │
    ▼
H3: Fan Controller + Covers
    │   (needs zone/room aggregation from H1)
    │
    ▼
H4: Predictive Sensors + Weather Pre-Conditioning
        (needs all prior data + forecast integration)
```

Each sub-cycle is independently deployable and testable.

---

## 17. VERIFICATION CHECKLIST

### H1
- [ ] Coordinator discovers zones from `CONF_ZONE_THERMOSTAT`
- [ ] House state AWAY → all zones to "away" preset
- [ ] House state SLEEP → all zones to "sleep" with limited offset
- [ ] Energy "coast" → cooling setpoints raised by offset
- [ ] Energy "pre_cool" → cooling setpoints lowered by offset
- [ ] Seasonal range adjustment applies correct temps for current month
- [ ] User manual override detected (`preset_mode == "manual"`)
- [ ] SIGNAL_ENERGY_CONSTRAINT fires from Energy on constraint change
- [ ] HVAC can be disabled via CM toggle
- [ ] Zone status sensors show correct aggregated data
- [ ] `sensor.ura_hvac_coordinator_anomaly` shows "insufficient_data" initially
- [ ] `sensor.ura_hvac_coordinator_compliance` shows 100% with no commands yet
- [ ] DecisionLogger records preset_change decisions to DB
- [ ] ComplianceTracker schedules 2-min check after preset commands
- [ ] AnomalyDetector baselines persist across HA restart

### H2
- [ ] Normal violation (±1°F): 5-min delay → 30-min compromise → revert
- [ ] Severe violation (>3°F): 2-min delay → immediate preset revert
- [ ] HVAC mode violation: corrected to heat_cool
- [ ] Override during coast: widened tolerance
- [ ] Override in vacant zone: no compromise, immediate revert
- [ ] Override frequency sensor increments correctly
- [ ] AC reset triggers after stuck for N minutes past setpoint
- [ ] AC reset max 2 per zone per day
- [ ] NM notifications sent for overrides and resets

### H3
- [ ] Fan ON when room temp > setpoint + activation_delta
- [ ] Fan OFF when room temp < setpoint + deactivation_delta (hysteresis)
- [ ] Fan speed scales with delta (low/med/high)
- [ ] Fan off in vacant rooms after 5-min hold
- [ ] Fan minimum 10-min runtime honored
- [ ] Energy fan_assist triggers fans during coast
- [ ] Humidity fan triggers at threshold with 10% hysteresis
- [ ] Covers close during peak solar hours when hot
- [ ] Cover manual override respected for 2 hours

### H4
- [ ] Pre-cool likelihood sensor published by start of day
- [ ] Comfort violation risk updates during energy constraints
- [ ] Zone demand reflects outdoor temp trend
- [ ] Pre-cool initiated before peak when forecast warrants
- [ ] Pre-heat initiated before off-peak ends in winter
- [ ] Daily HVACOutcome stored at midnight with zone_satisfaction_rate
- [ ] Anomaly detection activates after 14 days of observations

---

## 18. MIGRATION: ARRESTER AUTOMATIONS

After H2 deploys and is verified stable (1-2 days):

1. Disable `automation.back_hallway_hvac_arrester` (currently ON)
2. Disable `automation.upstairs_zone_hvac_arrester` (currently ON)
3. Disable `automation.back_hallway_hvac_arrester2` (currently OFF — already superseded?)
4. Monitor for 2-3 days to confirm HVAC coordinator handles all cases
5. Delete YAML automations after confidence period

---

## 19. ESTIMATED EFFORT

| Sub-Cycle | New Lines | Modified Lines | Hours |
|-----------|-----------|----------------|-------|
| H1 | ~900 | ~250 | 3-4 |
| H2 | ~300 | ~50 | 1-2 |
| H3 | ~400 | ~80 | 2 |
| H4 | ~250 | ~80 | 1-2 |
| **Total** | **~1850** | **~460** | **7-10** |
