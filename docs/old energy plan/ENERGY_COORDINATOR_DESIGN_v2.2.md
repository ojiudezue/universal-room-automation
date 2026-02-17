# Energy Coordinator Design - URA v3.6.0
## Comprehensive Specification for Whole-House Energy Intelligence

**Version:** 2.1 (Updated with Pentair IntelliCenter discovery)  
**Status:** Design Phase - Ready for Implementation  
**Created:** January 23, 2026  
**Updated:** January 24, 2026  
**Author:** Energy optimization analysis for Oji's Madrone Labs system  
**Effort Estimate:** 8-10 hours core + 4-6 hours optional vehicle tracking  
**Dependencies:** v3.5.0 Census System (for person count awareness)  

---

### Table of Contents

1. [Design Philosophy](#1-design-philosophy) - Governor model, livability-first approach
2. [Hardware Integration Map](#2-hardware-integration-map) - **CONFIRMED** entity mappings (80+ entities)
3. [PEC TOU Schedule Configuration](#3-pec-tou-schedule-configuration) - Three-season rate structure
4. [Solar Forecast Integration](#4-solar-forecast-integration) - **NEW** Solcast-aware strategies
5. [Energy Coordinator Architecture](#5-energy-coordinator-architecture) - Core class structure
6. [HVAC Coordinator Integration](#6-hvac-coordinator-integration) - Constraint-based governance
7. [Configuration via Options Flow](#7-configuration-via-options-flow) - User-friendly setup
8. [Sensors & Entities](#8-sensors--entities) - Exposed state and attributes
9. [Implementation Phases](#9-implementation-phases) - Development roadmap (includes optional vehicle tracking)
10. [Testing Strategy](#10-testing-strategy) - Validation approach
11. [Success Criteria](#11-success-criteria) - Measurable outcomes
12. [Conclusion](#12-conclusion-why-ura-is-the-right-home) - Integration rationale

---

### Key Additions in v2.0

| Feature | Description | Impact |
|---------|-------------|--------|
| **Solcast Integration** | 30-min granular forecasts with confidence bands | Weather-aware strategy selection |
| **Day Classification** | excellent/good/moderate/poor/very_poor | Automatic strategy adjustment |
| **Confirmed Entities** | Verified 80+ entity mappings from live HA | Zero guesswork in implementation |
| **Battery Control** | `select.enpower_482348004678_storage_mode` confirmed | Full charge/discharge control |
| **EV Charging** | 2x Emporia EVSEs via switches + power monitoring | On/off deferral with load tracking |
| **Pool System (Expanded!)** | Full Pentair IntelliCenter: 33 entities, 7 circuits, 2 VSF pumps | Circuit-level control + monitoring |
| **Vehicle Tracking (Optional)** | Camera + door data infrastructure documented | Future departure prediction |

### Key Additions in v2.1

| Feature | Description | Impact |
|---------|-------------|--------|
| **Pentair IntelliCenter** | Full 33-entity mapping discovered | Multiple controllable circuits |
| **VSF Pump Monitoring** | 2x variable speed pumps with power/RPM/GPM sensors | Real-time load visibility |
| **Pool Circuit Control** | `switch.pool`, `switch.spa`, `switch.booster_pump`, etc. | Granular load shedding |
| **EVSE Power Monitoring** | `sensor.garage_a/b_power_minute_average` | Detect active charging |
| **Vehicle Data Sources** | UniFi + Frigate + door sensors documented | Foundation for optional tracking |

---

## 1. DESIGN PHILOSOPHY

### Energy Coordinator as Active Controller + Room Governor

The Energy Coordinator has a **dual role**:

1. **ACTIVE CONTROLLER** for house-level energy infrastructure
   - Battery, Pool, EVSEs have no other controller - Energy Coordinator owns them
   - Direct service calls, not suggestions
   - Real-time response to TOU periods and solar conditions

2. **GOVERNOR** for room-level climate
   - HVAC Coordinator manages the 3 climate zones
   - Energy Coordinator publishes constraints that HVAC must respect
   - Rooms retain autonomy within energy bounds

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ENERGY COORDINATOR                                   │
│                   "Whole-House Energy Intelligence"                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    DIRECT CONTROL (Active)                          │    │
│  │  Devices outside room scope - Energy Coordinator IS the controller  │    │
│  ├─────────────────────────────────────────────────────────────────────┤    │
│  │  • Battery: select.enpower_*_storage_mode, reserve level, grid      │    │
│  │  • Pool: switch.pool, switch.infinity_edge, switch.booster_pump     │    │
│  │  • EVSEs: switch.garage_a, switch.garage_b                          │    │
│  │  • SPAN: Load shedding via breaker control (emergency)              │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                   HVAC GOVERNANCE (Constraints)                      │    │
│  │  HVAC Coordinator manages zones, Energy publishes limits            │    │
│  ├─────────────────────────────────────────────────────────────────────┤    │
│  │  → Publishes: setpoint offsets, mode restrictions, occupied_only    │    │
│  │  → Receives: compliance status, actual consumption, zone temps      │    │
│  │  → HVAC Coordinator handles: zone control, fan coordination, presets│    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    INTELLIGENCE INPUTS                               │    │
│  │  Data that informs all decisions                                     │    │
│  ├─────────────────────────────────────────────────────────────────────┤    │
│  │  FROM ROOMS (via URA):     │  FROM EXTERNAL:                        │    │
│  │  • Census count            │  • TOU rates (import AND export)       │    │
│  │  • Room occupancy          │  • Solar forecast (Solcast)            │    │
│  │  • Temperature readings    │  • Weather conditions                  │    │
│  │  • Humidity levels         │  • Grid status                         │    │
│  │  • Activity patterns       │  • Battery SOC                         │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Architectural Principles

**1. Energy Coordinator ACTIVELY CONTROLS house-level infrastructure**
- Battery, Pool, EVSEs have no other controller
- Direct `hass.services.async_call()` execution
- Real-time response to rate changes and solar production

**2. Energy Coordinator INFORMS HVAC Coordinator**
- Publishes constraints via event bus
- HVAC Coordinator respects bounds while managing zones
- Bidirectional: HVAC reports compliance and consumption

**3. Energy Coordinator IS INFORMED BY room conditions**
- Census feeds occupancy-aware decisions
- Room temperatures validate strategy effectiveness
- Activity patterns predict load changes

**4. Energy Coordinator UNDERSTANDS the larger context**
- TOU rates drive timing (both IMPORT and EXPORT optimization)
- Solar forecast drives aggressiveness
- Weather predicts heating/cooling demand
- Battery SOC enables/constrains discharge options

### TOU Rate Optimization - Import AND Export

**Critical Insight:** TOU rates apply to BOTH grid import AND export credits.

```
SUMMER RATE STRUCTURE (PEC 2026):
┌────────────────────────────────────────────────────────────────────────┐
│ Period    │ Hours      │ Import Rate │ Export Credit │ Strategy       │
├────────────────────────────────────────────────────────────────────────┤
│ OFF_PEAK  │ 0-14, 21-24│ $0.0435/kWh │ $0.0435/kWh  │ Import cheap   │
│ MID_PEAK  │ 14-16,20-21│ $0.0932/kWh │ $0.0932/kWh  │ Moderate       │
│ PEAK      │ 16-20      │ $0.1618/kWh │ $0.1618/kWh  │ EXPORT HERE!   │
└────────────────────────────────────────────────────────────────────────┘

OPTIMIZATION TARGETS:
• IMPORT: Minimize during peak/mid-peak, maximize during off-peak
• EXPORT: Maximize during peak (3.7x value vs off-peak!)
• BATTERY: Charge off-peak, discharge TO GRID during peak for credits
```

**Export Optimization Strategy:**
```python
# Battery export decision during peak (4-8pm summer)
if tou_period == "peak" and battery_soc > reserve_level:
    if solar_production < home_consumption:
        # Use battery to cover home load (avoid $0.16 import)
        battery_action = "discharge_to_home"
    else:
        # Solar covers home, EXPORT battery to grid for $0.16 credit!
        battery_action = "discharge_to_grid"
```

### Livability First

Every decision must pass the "livability test":
- **Comfort Impact Score (0-10)** - How noticeable is this to occupants?
- **Recovery Time** - How long to restore comfort?
- **Override Available** - Can user easily bypass?

**Example Decision Matrix:**
| Action | Savings | Comfort Impact | Livability Score |
|--------|---------|----------------|------------------|
| Pre-cool 2-4pm (-3°F) | High | 2/10 (pleasant) | ✅ Excellent |
| Coast 4-8pm (+3°F) | High | 4/10 (noticeable) | ✅ Good |
| Turn off pool 4-8pm | Medium | 0/10 (invisible) | ✅ Excellent |
| Pause EV charging | Low | 0/10 (invisible) | ✅ Excellent |
| Emergency HVAC off | Critical | 8/10 (uncomfortable) | ⚠️ Last resort |

---

## 2. HARDWARE INTEGRATION MAP

### Confirmed Entity Mappings (January 2026)

```yaml
# Oji's Energy Infrastructure - CONFIRMED ENTITIES

#═══════════════════════════════════════════════════════════════════════════════
# SOLAR PRODUCTION
#═══════════════════════════════════════════════════════════════════════════════
solar:
  system: "24.25 kW array (50x QCell 485W)"
  microinverters: "Enphase IQ8X"
  integration: "Enphase Envoy 202428004328"
  entities:
    production_power: sensor.envoy_202428004328_current_power_production     # kW, real-time
    production_today: sensor.envoy_202428004328_energy_production_today      # kWh
    production_7days: sensor.envoy_202428004328_energy_production_last_seven_days  # kWh
    production_lifetime: sensor.envoy_202428004328_lifetime_energy_production     # MWh

#═══════════════════════════════════════════════════════════════════════════════
# BATTERY STORAGE (40 kWh Enphase 5P x8)
#═══════════════════════════════════════════════════════════════════════════════
battery:
  system: "8x Enphase 5P (40 kWh total capacity)"
  integration: "Enphase Envoy + Battery Control"
  control_capable: true  # ✅ CAN SET STORAGE MODE
  entities:
    # Read-only status
    soc_percent: sensor.envoy_202428004328_battery                           # 0-100%
    available_energy: sensor.envoy_202428004328_available_battery_energy     # Wh
    reserve_energy: sensor.envoy_202428004328_reserve_battery_energy         # Wh
    capacity: sensor.envoy_202428004328_battery_capacity                     # Wh (40000)
    reserve_level: sensor.envoy_202428004328_reserve_battery_level           # %
    discharge_power: sensor.envoy_202428004328_current_battery_discharge     # kW (negative=charging)
    lifetime_charged: sensor.envoy_202428004328_lifetime_battery_energy_charged      # MWh
    lifetime_discharged: sensor.envoy_202428004328_lifetime_battery_energy_discharged # MWh
    
    # CONTROLLABLE - Storage Mode
    storage_mode: select.enpower_482348004678_storage_mode
    #   Options: ["backup", "self_consumption", "savings"]
    #   - backup: Maintain full charge for outages
    #   - self_consumption: Use solar to power home, excess to battery
    #   - savings: TOU optimization (charge off-peak, discharge peak)
    
    # CONTROLLABLE - Reserve Level
    reserve_battery_level: number.enpower_482348004678_reserve_battery_level  # 0-100%
    
    # CONTROLLABLE - Grid Interaction
    grid_enabled: switch.enpower_482348004678_grid_enabled                    # Allow grid export
    charge_from_grid: switch.enpower_482348004678_charge_from_grid            # Allow grid charging
    
    # Status
    grid_status: binary_sensor.enpower_482348004678_grid_status               # Grid connected?
    communicating: binary_sensor.enpower_482348004678_communicating           # Online?

#═══════════════════════════════════════════════════════════════════════════════
# GRID MONITORING
#═══════════════════════════════════════════════════════════════════════════════
grid:
  measurement: "SPAN Panel + Enphase CT"
  entities:
    consumption_power: sensor.envoy_202428004328_current_power_consumption   # kW
    net_power: sensor.envoy_202428004328_current_net_power_consumption       # kW (+ = import, - = export)
    consumption_today: sensor.envoy_202428004328_energy_consumption_today    # kWh
    net_consumption_lifetime: sensor.envoy_202428004328_lifetime_net_energy_consumption  # MWh
    net_production_lifetime: sensor.envoy_202428004328_lifetime_net_energy_production    # MWh

#═══════════════════════════════════════════════════════════════════════════════
# POOL SYSTEM (Pentair IntelliCenter - 33 entities!)
#═══════════════════════════════════════════════════════════════════════════════
pool:
  system: "Pentair IntelliCenter with Variable Speed Pumps"
  model: "IntelliCenter IC: 1.064"
  integration: "intellicenter"
  device_id: "165876a055ab4fbf97768318c8a8e5ea"
  control_method: "Native IntelliCenter integration OR SPAN breaker fallback"
  variable_speed_control: false  # VSF sensors are READ-ONLY, no direct RPM control
  
  # STRATEGY NOTE: While we cannot directly set pump RPM, we can control different
  # circuits (pool, spa, booster, infinity edge) which operate at different power 
  # levels. The `switch.pool` is the main high-power circulation circuit.
  
  entities:
    #─────────────────────────────────────────────────────────────────────────────
    # CONTROLLABLE CIRCUITS (On/Off switches)
    #─────────────────────────────────────────────────────────────────────────────
    pool_circuit: switch.pool                                                 # Main pool circulation (big load)
    spa_circuit: switch.spa                                                   # Spa mode
    booster_pump: switch.booster_pump                                         # Booster pump
    infinity_edge: switch.infinity_edge                                       # Infinity edge feature
    jets: switch.jets                                                         # Spa jets
    air_blower: switch.air_blower                                             # Air blower
    vacation_mode: switch.vacation_mode                                       # Reduced operation mode
    
    # SPAN fallback (if IntelliCenter unavailable)
    breaker_switch: switch.span_panel_pool_breaker                            # SPAN breaker fallback
    
    #─────────────────────────────────────────────────────────────────────────────
    # VSF PUMP MONITORING (Read-only - TWO variable speed pumps!)
    #─────────────────────────────────────────────────────────────────────────────
    # Primary VSF pump
    vsf_power: sensor.vsf_power                                               # W real-time
    vsf_rpm: sensor.vsf_rpm                                                   # Current RPM
    vsf_gpm: sensor.vsf_gpm                                                   # Flow rate GPM
    vsf_running: binary_sensor.vsf                                            # Running status
    
    # Secondary VSF pump
    vsf_2_power: sensor.vsf_2_power                                           # W real-time
    vsf_2_rpm: sensor.vsf_2_rpm                                               # Current RPM
    vsf_2_gpm: sensor.vsf_2_gpm                                               # Flow rate GPM
    vsf_2_running: binary_sensor.vsf_2                                        # Running status
    
    #─────────────────────────────────────────────────────────────────────────────
    # TEMPERATURE CONTROL
    #─────────────────────────────────────────────────────────────────────────────
    pool_heater: water_heater.pool                                            # Pool heater (temp setpoint)
    spa_heater: water_heater.spa                                              # Spa heater (temp setpoint)
    pool_temp: sensor.pool_last_temp                                          # Current pool temp
    pool_desired_temp: sensor.pool_desired_temp                               # Pool setpoint
    spa_temp: sensor.spa_last_temp                                            # Current spa temp
    spa_desired_temp: sensor.spa_desired_temp                                 # Spa setpoint
    water_sensor: sensor.water_sensor_1                                       # Water temperature
    air_sensor: sensor.air_sensor                                             # Air temperature
    solar_sensor: sensor.solar_sensor_1                                       # Solar heating sensor
    
    #─────────────────────────────────────────────────────────────────────────────
    # STATUS MONITORING
    #─────────────────────────────────────────────────────────────────────────────
    gas_heater_status: binary_sensor.gas_heater                               # Gas heater running
    freeze_protection: binary_sensor.freeze                                   # Freeze protection active
    
    #─────────────────────────────────────────────────────────────────────────────
    # SCHEDULE STATUS (Read-only - shows IntelliCenter's internal schedules)
    #─────────────────────────────────────────────────────────────────────────────
    pool_schedule: binary_sensor.pool_schedule                                # Pool scheduled on?
    booster_schedule: binary_sensor.booster_pump_schedule                     # Booster scheduled?
    infinity_schedule: binary_sensor.infinity_edge_schedule                   # Infinity edge scheduled?
    pool_light_schedule: binary_sensor.pool_light_schedule                    # Lights scheduled?
    spa_lights_schedule: binary_sensor.spa_lights_schedule                    # Spa lights scheduled?
    
    #─────────────────────────────────────────────────────────────────────────────
    # LIGHTING
    #─────────────────────────────────────────────────────────────────────────────
    pool_light: light.pool_light                                              # Pool light
    spa_lights: light.spa_lights                                              # Spa lights
  
  # ENERGY CONTROL STRATEGY:
  # - During TOU peak (4-8pm summer): Turn off switch.pool to stop main circulation
  # - During solar peak (10am-2pm): Run pool and infinity edge for maximum load shifting
  # - Use vacation_mode for extended away periods
  # - Monitor vsf_power to track actual consumption
  # - Note: Cannot modulate RPM directly, but can shed entire circuits

#═══════════════════════════════════════════════════════════════════════════════
# EV CHARGING (2x Emporia 48A EVSEs)
#═══════════════════════════════════════════════════════════════════════════════
ev_charging:
  - system: "Emporia EVSE Garage A"
    device_id: "867eaa0fe1bd30a39e5dc195cc1c3700"
    model: "VVDN01"
    capacity: "48A @ 240V = 11.5 kW"
    control_type: "Simple switch (on/off only)"
    entities:
      charger_switch: switch.garage_a                                         # EVSE_Emporia_Wifi_GarageA
      power_monitor: sensor.garage_a_power_minute_average                     # Real-time power (W)
      energy_today: sensor.garage_a_energy_today                              # Daily energy (kWh)
      energy_month: sensor.garage_a_energy_this_month                         # Monthly energy (kWh)
      breaker: switch.span_panel_garage_a_evse_breaker                        # SPAN backup control
      
  - system: "Emporia EVSE Garage B"
    device_id: "d4b7f4886922f569cb3df6782fedc8f5"
    model: "VVDN01"
    capacity: "48A @ 240V = 11.5 kW"
    control_type: "Simple switch (on/off only)"
    entities:
      charger_switch: switch.garage_b                                         # EVSE_Emporia_Wifi_GarageB
      power_monitor: sensor.garage_b_power_minute_average                     # Real-time power (W)
      energy_today: sensor.garage_b_energy_today                              # Daily energy (kWh)
      energy_month: sensor.garage_b_energy_this_month                         # Monthly energy (kWh)
      breaker: switch.span_panel_garage_b_evse_breaker                        # SPAN backup control
  
  # ENERGY CONTROL STRATEGY:
  # - Simple on/off control via switch.garage_a / switch.garage_b
  # - Monitor power_monitor sensors to detect active charging
  # - During TOU peak: Switch off to pause charging (EV handles gracefully)
  # - During solar peak: Enable charging to absorb excess production
  # - No variable rate control - just on/off deferral
  
#═══════════════════════════════════════════════════════════════════════════════
# VEHICLE PRESENCE TRACKING (Infrastructure for future departure prediction)
#═══════════════════════════════════════════════════════════════════════════════
# NOTE: This section documents AVAILABLE data for future vehicle tracking.
# Implementation is marked as OPTIONAL MILESTONE - useful for EV charge scheduling
# but not required for core energy optimization.
#
# Available detection sources:
#   - event.garage_a_vehicle: UniFi Protect vehicle detection (with confidence %)
#   - event.garage_b_vehicle: UniFi Protect vehicle detection
#   - binary_sensor.garage_a_vehicle_detected: Frigate real-time detection
#   - binary_sensor.garage_b_vehicle_detected: Frigate real-time detection
#   - event.garage_doorbell_lite_vehicle: Driveway approach detection
#   - cover.konnected_f0f5bd523b00_garage_door: Garage A door state (open/closed)
#   - cover.ratgdov25i_dbfe2a_door: Garage B door state (open/closed)
#   - sensor.garageopener_gdoblaq_wifi_garagea_garage_openings: 2,061 total openings tracked!
#
# Potential future implementation could correlate:
#   Door opens + vehicle_detected → not_detected = DEPARTURE
#   Door opens + not_detected → vehicle_detected = ARRIVAL
#   Build patterns over 2-4 weeks for departure time prediction
#
# See OPTIONAL MILESTONE 7 for implementation details if needed.

#═══════════════════════════════════════════════════════════════════════════════
# SOLAR FORECASTING (Solcast) - CRITICAL FOR OPTIMIZATION
#═══════════════════════════════════════════════════════════════════════════════
forecasting:
  system: "Solcast PV Forecast"
  integration: "Solcast Solar"
  api_calls_used: sensor.solcast_pv_forecast_api_used                         # Track API usage
  api_calls_limit: sensor.solcast_pv_forecast_api_limit                       # 10 calls/day
  
  entities:
    # Current estimates
    power_now: sensor.solcast_pv_forecast_power_now                           # W expected right now
    power_30min: sensor.solcast_pv_forecast_power_in_30_minutes               # W in 30 min
    power_1hour: sensor.solcast_pv_forecast_power_in_1_hour                   # W in 1 hour
    
    # Energy forecasts
    forecast_this_hour: sensor.solcast_pv_forecast_forecast_this_hour         # Wh this hour
    forecast_next_hour: sensor.solcast_pv_forecast_forecast_next_hour         # Wh next hour
    forecast_remaining_today: sensor.solcast_pv_forecast_forecast_remaining_today  # kWh remaining
    
    # Daily forecasts
    forecast_today: sensor.solcast_pv_forecast_forecast_today                 # kWh total today
    forecast_tomorrow: sensor.solcast_pv_forecast_forecast_tomorrow           # kWh tomorrow
    forecast_day_3: sensor.solcast_pv_forecast_forecast_day_3                 # kWh day 3
    forecast_day_4: sensor.solcast_pv_forecast_forecast_day_4                 # kWh day 4
    forecast_day_5: sensor.solcast_pv_forecast_forecast_day_5                 # kWh day 5
    forecast_day_6: sensor.solcast_pv_forecast_forecast_day_6                 # kWh day 6
    forecast_day_7: sensor.solcast_pv_forecast_forecast_day_7                 # kWh day 7
    
    # Peak forecasts
    peak_power_today: sensor.solcast_pv_forecast_peak_forecast_today          # W peak today
    peak_time_today: sensor.solcast_pv_forecast_peak_time_today               # Timestamp of peak
    peak_power_tomorrow: sensor.solcast_pv_forecast_peak_forecast_tomorrow    # W peak tomorrow
    peak_time_tomorrow: sensor.solcast_pv_forecast_peak_time_tomorrow         # Timestamp
    
    # Settings
    use_forecast_field: select.solcast_pv_forecast_use_forecast_field         # estimate/estimate10/estimate90
  
  # Rich attribute data available in forecast_today:
  #   - estimate: Expected production (kWh)
  #   - estimate10: Pessimistic 10th percentile (kWh)
  #   - estimate90: Optimistic 90th percentile (kWh)
  #   - detailedForecast: 30-minute intervals with pv_estimate/pv_estimate10/pv_estimate90
  #   - detailedHourly: Hourly intervals with same structure
```

### Solar Forecast Intelligence

The Solcast integration provides **game-changing** data for Energy Coordinator decisions:

**Example: Today's Forecast (Cloudy Day)**
```yaml
# sensor.solcast_pv_forecast_forecast_today attributes
estimate: 10.8499 kWh      # Expected production
estimate10: 5.9021 kWh     # Pessimistic (10th percentile)  
estimate90: 17.5324 kWh    # Optimistic (90th percentile)

# Compare to clear day (Day 5): 126.37 kWh - that's 11x more!
```

**Forecast-Aware Strategy Decisions:**

| Solar Forecast | Battery Strategy | HVAC Strategy | EV/Pool |
|---------------|------------------|---------------|---------|
| **High** (>80 kWh) | Self-consumption mode, minimal grid charge | Normal operation, use solar for pre-cool | Run during peak solar |
| **Medium** (30-80 kWh) | Savings mode, partial grid top-up | Moderate pre-cool | Run during off-peak + peak solar |
| **Low** (<30 kWh) | Savings mode, full grid charge overnight | Aggressive pre-cool, conservative coast | Off-peak only |
| **Very Low** (<15 kWh) | Full grid charge, extend reserve | Max pre-cool, tight coast | Defer if possible |

---

## 3. PEC TOU SCHEDULE CONFIGURATION

### Time-of-Use Rates (Pedernales Electric Cooperative)

```python
# domain_coordinators/energy/tou_schedules.py

@dataclass
class TOUPeriod:
    """Definition of a TOU period."""
    name: str           # "off_peak", "mid_peak", "peak"
    rate: float         # $/kWh
    hours: list[tuple]  # [(start_hour, end_hour), ...]

@dataclass
class SeasonalTOUSchedule:
    """TOU schedule for a season."""
    name: str           # "summer", "shoulder", "winter"
    months: list[int]   # [6, 7, 8, 9] for summer
    periods: list[TOUPeriod]

# PEC 2026 TOU Schedule (configurable via options flow)
PEC_TOU_SCHEDULE = {
    "summer": SeasonalTOUSchedule(
        name="summer",
        months=[6, 7, 8, 9],
        periods=[
            TOUPeriod("off_peak", 0.04348, [(0, 14), (21, 24)]),
            TOUPeriod("mid_peak", 0.09317, [(14, 16), (20, 21)]),
            TOUPeriod("peak",     0.16184, [(16, 20)]),
        ]
    ),
    "shoulder": SeasonalTOUSchedule(
        name="shoulder",
        months=[3, 4, 5, 10, 11],
        periods=[
            TOUPeriod("off_peak", 0.04348, [(0, 17), (21, 24)]),
            TOUPeriod("mid_peak", 0.08644, [(17, 21)]),
            # No peak in shoulder
        ]
    ),
    "winter": SeasonalTOUSchedule(
        name="winter",
        months=[12, 1, 2],
        periods=[
            TOUPeriod("off_peak", 0.04348, [(0, 5), (9, 17), (21, 24)]),
            TOUPeriod("mid_peak", 0.08644, [(5, 9), (17, 21)]),
            # No peak in winter
        ]
    ),
}
```

### TOU Period Sensor

```python
# domain_coordinators/energy/sensors.py

class TOUPeriodSensor(SensorEntity):
    """Current TOU period with rich attributes."""
    
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["off_peak", "mid_peak", "peak"]
    
    @property
    def native_value(self) -> str:
        """Return current TOU period."""
        return self.coordinator.get_current_tou_period()
    
    @property
    def extra_state_attributes(self) -> dict:
        """Return comprehensive TOU information."""
        period = self.coordinator.get_current_tou_period()
        season = self.coordinator.get_current_season()
        schedule = self.coordinator.tou_schedule[season]
        
        # Find current period details
        current_rate = None
        for p in schedule.periods:
            if p.name == period:
                current_rate = p.rate
                break
        
        # Calculate time until next period change
        next_period, time_until = self.coordinator.get_next_period_change()
        
        return {
            "season": season,
            "rate_per_kwh": current_rate,
            "rate_multiplier": round(current_rate / 0.04348, 2),  # vs off-peak baseline
            "next_period": next_period,
            "minutes_until_change": time_until,
            "is_expensive": period in ["mid_peak", "peak"],
            "is_critical": period == "peak" and season == "summer",
            "hvac_strategy": self.coordinator.get_recommended_hvac_strategy(),
        }
```

---

## 4. SOLAR FORECAST INTEGRATION

### The Solar Intelligence Layer

Solcast provides probabilistic solar production forecasts that fundamentally change energy strategy. Rather than reactive TOU-only optimization, we can now make **proactive, weather-aware decisions**.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    SOLAR FORECAST DATA FLOW                              │
├─────────────────────────────────────────────────────────────────────────┤
│  Solcast API → sensor.solcast_pv_forecast_* → Energy Coordinator        │
│                                                                          │
│  Key Attributes (in forecast_today):                                     │
│    • estimate: Expected kWh (50th percentile)                           │
│    • estimate10: Pessimistic kWh (10th percentile - cloudy)             │
│    • estimate90: Optimistic kWh (90th percentile - sunny)               │
│    • detailedForecast[]: 30-min granular predictions                    │
│    • detailedHourly[]: Hourly summary predictions                       │
└─────────────────────────────────────────────────────────────────────────┘
```

### SolarForecastAnalyzer Class

```python
# domain_coordinators/energy/solar_forecast.py

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

@dataclass
class SolarForecastWindow:
    """Solar forecast for a specific time window."""
    start: datetime
    end: datetime
    expected_kwh: float
    pessimistic_kwh: float   # 10th percentile
    optimistic_kwh: float    # 90th percentile
    peak_power_w: float
    peak_time: datetime

@dataclass
class SolarDayClassification:
    """Classify day quality for strategy selection."""
    quality: str             # "excellent", "good", "moderate", "poor", "very_poor"
    expected_kwh: float
    confidence_range: float  # estimate90 - estimate10
    excess_after_base_load: float  # kWh available after ~20kWh base load
    recommended_battery_strategy: str
    recommended_hvac_aggressiveness: str
    recommended_ev_strategy: str


class SolarForecastAnalyzer:
    """
    Analyze Solcast forecasts to inform energy decisions.
    
    Key insight: With a 24.25 kW array, a clear summer day produces ~120+ kWh,
    while a cloudy winter day might only produce ~10 kWh. Strategy must adapt!
    """
    
    # Day classification thresholds (based on 24.25 kW array capacity)
    EXCELLENT_THRESHOLD = 100  # kWh - clear summer day
    GOOD_THRESHOLD = 60        # kWh - partly cloudy or shoulder season
    MODERATE_THRESHOLD = 30    # kWh - cloudy or winter
    POOR_THRESHOLD = 15        # kWh - very cloudy winter
    
    # Estimated base load (house runs ~20 kWh/day without HVAC spikes)
    BASE_LOAD_KWH = 20
    
    def __init__(self, hass: HomeAssistant):
        self.hass = hass
        
    def get_forecast_today(self) -> Optional[SolarForecastWindow]:
        """Get today's complete forecast."""
        state = self.hass.states.get("sensor.solcast_pv_forecast_forecast_today")
        if not state or state.state in ("unavailable", "unknown"):
            return None
            
        attrs = state.attributes
        return SolarForecastWindow(
            start=datetime.now().replace(hour=0, minute=0, second=0),
            end=datetime.now().replace(hour=23, minute=59, second=59),
            expected_kwh=float(attrs.get("estimate", 0)),
            pessimistic_kwh=float(attrs.get("estimate10", 0)),
            optimistic_kwh=float(attrs.get("estimate90", 0)),
            peak_power_w=self._get_peak_power_today(),
            peak_time=self._get_peak_time_today(),
        )
    
    def get_forecast_remaining(self) -> float:
        """Get remaining kWh expected today."""
        state = self.hass.states.get("sensor.solcast_pv_forecast_forecast_remaining_today")
        if state and state.state not in ("unavailable", "unknown"):
            return float(state.state)
        return 0.0
    
    def get_power_forecast(self, hours_ahead: int = 0) -> float:
        """Get power forecast for specified hours ahead (W)."""
        if hours_ahead == 0:
            entity = "sensor.solcast_pv_forecast_power_now"
        elif hours_ahead == 1:
            entity = "sensor.solcast_pv_forecast_power_in_1_hour"
        else:
            # Use detailed forecast for other windows
            return self._get_power_from_detailed(hours_ahead)
            
        state = self.hass.states.get(entity)
        if state and state.state not in ("unavailable", "unknown"):
            return float(state.state)
        return 0.0
    
    def classify_day(self, forecast: SolarForecastWindow = None) -> SolarDayClassification:
        """
        Classify today's solar potential and recommend strategies.
        
        This is the KEY DECISION POINT that affects all other strategies.
        """
        if forecast is None:
            forecast = self.get_forecast_today()
            
        if forecast is None:
            # No forecast available - use conservative defaults
            return SolarDayClassification(
                quality="unknown",
                expected_kwh=0,
                confidence_range=0,
                excess_after_base_load=-self.BASE_LOAD_KWH,
                recommended_battery_strategy="savings",  # TOU mode
                recommended_hvac_aggressiveness="moderate",
                recommended_ev_strategy="off_peak_only",
            )
        
        expected = forecast.expected_kwh
        confidence = forecast.optimistic_kwh - forecast.pessimistic_kwh
        excess = expected - self.BASE_LOAD_KWH
        
        # Classify based on expected production
        if expected >= self.EXCELLENT_THRESHOLD:
            quality = "excellent"
            battery_strategy = "self_consumption"  # Don't need grid, use solar
            hvac_strategy = "relaxed"              # Normal operation, solar handles it
            ev_strategy = "solar_priority"         # Run during peak solar
            
        elif expected >= self.GOOD_THRESHOLD:
            quality = "good"
            battery_strategy = "self_consumption"
            hvac_strategy = "moderate"             # Light pre-cool
            ev_strategy = "solar_preferred"        # Prefer solar, off-peak backup
            
        elif expected >= self.MODERATE_THRESHOLD:
            quality = "moderate"
            battery_strategy = "savings"           # TOU optimization
            hvac_strategy = "moderate"             # Standard pre-cool/coast
            ev_strategy = "off_peak_only"          # Stick to cheap rates
            
        elif expected >= self.POOR_THRESHOLD:
            quality = "poor"
            battery_strategy = "savings"           # Need TOU optimization
            hvac_strategy = "aggressive"           # Strong pre-cool, tight coast
            ev_strategy = "off_peak_only"
            
        else:
            quality = "very_poor"
            battery_strategy = "savings"           # Max TOU optimization
            hvac_strategy = "aggressive"           # Max pre-cool before peak
            ev_strategy = "minimal"                # Only charge if needed
            
        return SolarDayClassification(
            quality=quality,
            expected_kwh=expected,
            confidence_range=confidence,
            excess_after_base_load=excess,
            recommended_battery_strategy=battery_strategy,
            recommended_hvac_aggressiveness=hvac_strategy,
            recommended_ev_strategy=ev_strategy,
        )
    
    def get_solar_window_forecast(
        self, 
        start_hour: int, 
        end_hour: int
    ) -> SolarForecastWindow:
        """
        Get forecast for a specific time window (e.g., peak hours 4-8pm).
        
        Uses detailedHourly attribute for granular predictions.
        """
        state = self.hass.states.get("sensor.solcast_pv_forecast_forecast_today")
        if not state or not state.attributes.get("detailedHourly"):
            return None
            
        hourly = state.attributes["detailedHourly"]
        
        expected = 0.0
        pessimistic = 0.0
        optimistic = 0.0
        peak_power = 0.0
        peak_time = None
        
        for entry in hourly:
            hour = datetime.fromisoformat(entry["period_start"]).hour
            if start_hour <= hour < end_hour:
                expected += entry.get("pv_estimate", 0)
                pessimistic += entry.get("pv_estimate10", 0)
                optimistic += entry.get("pv_estimate90", 0)
                
                power = entry.get("pv_estimate", 0) * 1000  # kW to W
                if power > peak_power:
                    peak_power = power
                    peak_time = datetime.fromisoformat(entry["period_start"])
        
        return SolarForecastWindow(
            start=datetime.now().replace(hour=start_hour),
            end=datetime.now().replace(hour=end_hour),
            expected_kwh=expected,
            pessimistic_kwh=pessimistic,
            optimistic_kwh=optimistic,
            peak_power_w=peak_power,
            peak_time=peak_time,
        )
    
    def should_charge_battery_now(
        self, 
        current_soc: float, 
        target_soc: float = 90
    ) -> tuple[bool, str]:
        """
        Determine if battery should charge from grid now.
        
        Logic:
        - If forecast is excellent, don't grid charge (solar will fill)
        - If forecast is poor and SOC low, grid charge during off-peak
        - Consider tomorrow's forecast for overnight decisions
        """
        forecast = self.get_forecast_today()
        if forecast is None:
            return (True, "No forecast available - charging conservatively")
        
        classification = self.classify_day(forecast)
        remaining = self.get_forecast_remaining()
        
        # Calculate needed charge
        needed_kwh = (target_soc - current_soc) / 100 * 40  # 40 kWh capacity
        
        if classification.quality in ["excellent", "good"]:
            if remaining > needed_kwh:
                return (False, f"Solar will provide {remaining:.1f} kWh, need {needed_kwh:.1f} kWh")
            else:
                return (True, f"Solar only {remaining:.1f} kWh remaining, need {needed_kwh:.1f} kWh")
        
        elif classification.quality in ["moderate"]:
            if current_soc < 50:
                return (True, f"Moderate forecast ({forecast.expected_kwh:.1f} kWh) with low SOC ({current_soc}%)")
            return (False, f"Moderate forecast but SOC adequate ({current_soc}%)")
        
        else:  # poor or very_poor
            if current_soc < target_soc:
                return (True, f"Poor forecast ({forecast.expected_kwh:.1f} kWh) - grid charge recommended")
            return (False, f"Poor forecast but SOC at target ({current_soc}%)")
    
    def get_optimal_pool_window(self) -> tuple[int, int, str]:
        """
        Find optimal hours to run pool pump based on solar forecast.
        
        Goal: Run during peak solar production, avoid TOU peak.
        Summer: Start early (6am) to finish before 4pm peak
        Winter: Run during midday solar peak
        """
        state = self.hass.states.get("sensor.solcast_pv_forecast_forecast_today")
        if not state or not state.attributes.get("detailedHourly"):
            # Default: 6am-2pm (safe off-peak)
            return (6, 14, "No forecast - using default off-peak window")
        
        hourly = state.attributes["detailedHourly"]
        
        # Find hours with best solar production (avoiding 4-8pm peak)
        candidates = []
        for entry in hourly:
            hour = datetime.fromisoformat(entry["period_start"]).hour
            if 6 <= hour < 16:  # 6am-4pm window (before TOU peak)
                power = entry.get("pv_estimate", 0)
                candidates.append((hour, power))
        
        # Sort by power descending
        candidates.sort(key=lambda x: x[1], reverse=True)
        
        # Take top 8 hours (typical pool run time)
        if len(candidates) >= 8:
            hours = sorted([c[0] for c in candidates[:8]])
            start = hours[0]
            end = hours[-1] + 1
            total_solar = sum(c[1] for c in candidates[:8])
            return (start, end, f"Optimized for {total_solar:.1f} kWh solar during run")
        
        return (6, 14, "Limited forecast data - using default window")
```

### Solar Forecast Sensor

```python
# domain_coordinators/energy/sensors.py

class SolarForecastQualitySensor(SensorEntity):
    """Exposes solar day classification for automations."""
    
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["excellent", "good", "moderate", "poor", "very_poor", "unknown"]
    
    def __init__(self, coordinator: EnergyCoordinator):
        self.coordinator = coordinator
        self._analyzer = SolarForecastAnalyzer(coordinator.hass)
    
    @property
    def native_value(self) -> str:
        """Return day quality classification."""
        classification = self._analyzer.classify_day()
        return classification.quality
    
    @property
    def extra_state_attributes(self) -> dict:
        """Return comprehensive forecast intelligence."""
        classification = self._analyzer.classify_day()
        forecast = self._analyzer.get_forecast_today()
        
        # Get TOU peak window forecast (summer: 4-8pm)
        peak_window = self._analyzer.get_solar_window_forecast(16, 20)
        
        attrs = {
            "expected_today_kwh": classification.expected_kwh,
            "confidence_range_kwh": classification.confidence_range,
            "excess_available_kwh": classification.excess_after_base_load,
            "recommended_battery_strategy": classification.recommended_battery_strategy,
            "recommended_hvac_aggressiveness": classification.recommended_hvac_aggressiveness,
            "recommended_ev_strategy": classification.recommended_ev_strategy,
        }
        
        if forecast:
            attrs.update({
                "pessimistic_kwh": forecast.pessimistic_kwh,
                "optimistic_kwh": forecast.optimistic_kwh,
                "peak_power_w": forecast.peak_power_w,
                "peak_time": forecast.peak_time.isoformat() if forecast.peak_time else None,
            })
        
        if peak_window:
            attrs.update({
                "peak_window_solar_kwh": peak_window.expected_kwh,
                "peak_window_solar_pessimistic_kwh": peak_window.pessimistic_kwh,
            })
        
        # Tomorrow's forecast for overnight decisions
        tomorrow = self.hass.states.get("sensor.solcast_pv_forecast_forecast_tomorrow")
        if tomorrow and tomorrow.state not in ("unavailable", "unknown"):
            attrs["tomorrow_forecast_kwh"] = float(tomorrow.state)
        
        return attrs
```

### Strategy Integration

The Solar Forecast Analyzer integrates with all Energy Coordinator strategies:

```python
# In EnergyCoordinator.evaluate_strategies()

def evaluate_strategies(self) -> EnergyStrategy:
    """
    Evaluate all inputs and determine optimal strategy.
    
    Decision cascade:
    1. Solar forecast classification (sets baseline)
    2. TOU period (modifies aggressiveness)
    3. Battery state (enables/disables options)
    4. Census count (scales predictions)
    """
    
    # Step 1: Get solar classification
    solar = self.solar_analyzer.classify_day()
    
    # Step 2: Get current TOU period
    tou_period = self.get_current_tou_period()
    tou_season = self.get_current_season()
    
    # Step 3: Get battery state
    battery_soc = self._get_battery_soc()
    
    # Step 4: Get census (from v3.5.0)
    census_count = self._get_census_count()
    
    # Construct strategy based on solar quality
    if solar.quality in ["excellent", "good"]:
        # Good solar day - relaxed operation
        strategy = self._build_solar_abundant_strategy(solar, tou_period, battery_soc)
    elif solar.quality == "moderate":
        # Moderate solar - balanced approach
        strategy = self._build_balanced_strategy(solar, tou_period, battery_soc)
    else:
        # Poor solar - aggressive TOU optimization
        strategy = self._build_conservation_strategy(solar, tou_period, battery_soc)
    
    # Scale for occupancy
    strategy = self._scale_for_census(strategy, census_count)
    
    return strategy


def _build_solar_abundant_strategy(
    self, 
    solar: SolarDayClassification,
    tou_period: str,
    battery_soc: float
) -> EnergyStrategy:
    """
    Strategy for excellent/good solar days.
    
    Philosophy: Solar will cover most needs, minimal grid reliance.
    """
    return EnergyStrategy(
        name="solar_abundant",
        battery_mode="self_consumption",
        charge_from_grid=False,  # Solar will charge battery
        
        hvac_constraints=HVACConstraints(
            mode="normal",
            setpoint_offset=0,
            max_power_kw=None,  # No limit
            occupied_only=False,
            reason=f"Good solar day ({solar.expected_kwh:.0f} kWh expected)"
        ),
        
        pool_schedule=self.solar_analyzer.get_optimal_pool_window(),
        
        ev_charging={
            "strategy": "solar_priority",
            "allowed_periods": ["off_peak", "mid_peak"],  # More flexible
            "reason": "Charge during solar production"
        },
        
        load_shedding_threshold_kw=None,  # No shedding needed
    )


def _build_conservation_strategy(
    self, 
    solar: SolarDayClassification,
    tou_period: str,
    battery_soc: float
) -> EnergyStrategy:
    """
    Strategy for poor/very_poor solar days.
    
    Philosophy: Maximize TOU arbitrage, minimize peak usage.
    """
    # Determine HVAC aggressiveness based on TOU period
    if tou_period == "off_peak":
        # Pre-cool aggressively
        hvac_mode = "pre_cool"
        setpoint_offset = -3.0  # 3°F colder than setpoint
    elif tou_period == "mid_peak":
        # Moderate pre-cool
        hvac_mode = "pre_cool"
        setpoint_offset = -2.0
    elif tou_period == "peak":
        # Coast - allow warmer
        hvac_mode = "coast"
        setpoint_offset = +3.0
    else:
        hvac_mode = "normal"
        setpoint_offset = 0
    
    return EnergyStrategy(
        name="conservation",
        battery_mode="savings",  # TOU optimization
        charge_from_grid=battery_soc < 80,  # Charge from grid if needed
        
        hvac_constraints=HVACConstraints(
            mode=hvac_mode,
            setpoint_offset=setpoint_offset,
            max_power_kw=5.0 if tou_period == "peak" else None,
            occupied_only=(tou_period == "peak"),
            reason=f"Poor solar ({solar.expected_kwh:.0f} kWh) - {hvac_mode} mode"
        ),
        
        pool_schedule=(6, 14, "Off-peak only due to poor solar"),  # Fixed safe window
        
        ev_charging={
            "strategy": "off_peak_only",
            "allowed_periods": ["off_peak"],
            "pause_during_peak": True,
            "reason": f"Conservation mode - poor solar day"
        },
        
        load_shedding_threshold_kw=5.0,  # Enable shedding if importing >5kW during peak
    )
```

---

## 4.5 ENERGY DECISION ENGINE (THE FUSION SYSTEM)

### Overview: Situation Classification + Action Generation

The Energy Decision Engine is **NOT a rigid state machine**. Instead, it uses a **Situation Classifier + Action Generator** pattern that:

1. **Classifies** the current energy situation based on all inputs
2. **Generates** specific actions for each controllable device
3. **Executes** direct control for battery/pool/EVSE
4. **Publishes** constraints for HVAC Coordinator

**Why NOT a pure state machine?**
- Combinatorial explosion: TOU (3) × Solar (5) × Battery (5) × Season (3) = 225 states
- Reality has gradations (battery 35% ≠ battery 15%)
- Conditions change continuously, not discretely

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      ENERGY DECISION ENGINE                                  │
│                 "The Fusion System for Active Control"                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    INPUTS (Read Every Cycle - 60s)                  │    │
│  ├─────────────────────────────────────────────────────────────────────┤    │
│  │  TOU STATE          │  ENERGY STATE        │  ENVIRONMENT          │    │
│  │  • period           │  • battery_soc       │  • outdoor_temp       │    │
│  │  • rate_per_kwh     │  • solar_now_w       │  • outdoor_humidity   │    │
│  │  • minutes_to_next  │  • solar_forecast    │  • weather_condition  │    │
│  │  • season           │  • grid_import_w     │                       │    │
│  │  • rate_multiplier  │  • grid_export_w     │  OCCUPANCY            │    │
│  │                     │                      │  • census_count       │    │
│  │  LOAD STATE         │  DEVICE STATE        │  • rooms_occupied[]   │    │
│  │  • pool_power_w     │  • evse_a_charging   │  • predicted_occ[]    │    │
│  │  • hvac_power_w     │  • evse_b_charging   │                       │    │
│  │  • total_load_w     │  • pool_running      │                       │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    SITUATION CLASSIFIER                             │    │
│  │         (Determines operating mode based on weighted inputs)        │    │
│  ├─────────────────────────────────────────────────────────────────────┤    │
│  │                                                                     │    │
│  │  NORMAL        : off_peak + good_solar + battery > 50%             │    │
│  │  PRE_CONDITION : 30-60 min before expensive period                 │    │
│  │  EXPENSIVE     : mid_peak or peak period active                    │    │
│  │  CONSTRAINED   : peak + poor_solar + battery < 40%                 │    │
│  │  CRITICAL      : peak + very_poor_solar + battery < 20%            │    │
│  │  EXPORT_OPP    : peak + good_solar + battery > 80% + low_load      │    │
│  │  EMERGENCY     : grid_down or import > safety_threshold            │    │
│  │                                                                     │    │
│  │  Output: situation, urgency_score (0-100), time_horizon_minutes    │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                     ACTION GENERATORS                               │    │
│  │           (Produce specific commands per situation)                 │    │
│  ├─────────────────────────────────────────────────────────────────────┤    │
│  │                                                                     │    │
│  │  BATTERY ACTIONS (Direct Control)                                  │    │
│  │  ├─ storage_mode: backup | self_consumption | savings              │    │
│  │  ├─ reserve_level: 10-100%                                         │    │
│  │  ├─ charge_from_grid: true | false                                 │    │
│  │  └─ export_to_grid: true | false (NEW: for TOU export credits)     │    │
│  │                                                                     │    │
│  │  POOL ACTIONS (Direct Control)                                     │    │
│  │  ├─ circuits_on: [pool, infinity_edge, booster_pump]              │    │
│  │  ├─ circuits_off: [spa, jets, air_blower]                         │    │
│  │  └─ schedule_override: run_now | stop_now | follow_schedule       │    │
│  │                                                                     │    │
│  │  EVSE ACTIONS (Direct Control)                                     │    │
│  │  ├─ garage_a: enable | disable                                     │    │
│  │  └─ garage_b: enable | disable                                     │    │
│  │                                                                     │    │
│  │  HVAC CONSTRAINTS (Published to HVAC Coordinator)                  │    │
│  │  ├─ mode: normal | pre_cool | pre_heat | coast | shed             │    │
│  │  ├─ setpoint_offset: -3 to +4 °F                                  │    │
│  │  ├─ occupied_only: true | false                                    │    │
│  │  └─ max_runtime_minutes: null | 15 | 30                           │    │
│  │                                                                     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                       EXECUTION LAYER                               │    │
│  ├─────────────────────────────────────────────────────────────────────┤    │
│  │  • Direct service calls for battery, pool, EVSE                    │    │
│  │  • Event bus publish for HVAC constraints                          │    │
│  │  • State updates to Energy Coordinator sensors                     │    │
│  │  • Logging for analysis and debugging                              │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Situation Classifier Implementation

```python
# domain_coordinators/energy/decision_engine.py

@dataclass
class EnergyContext:
    """All inputs needed for decision making - refreshed every cycle."""
    
    # TOU State
    tou_period: str           # off_peak, mid_peak, peak
    tou_rate_import: float    # $/kWh for importing
    tou_rate_export: float    # $/kWh credit for exporting (SAME as import for PEC)
    minutes_until_period_change: int
    season: str               # summer, shoulder, winter
    
    # Energy State
    battery_soc: float        # 0-100%
    solar_now_w: float        # Current production
    solar_forecast_quality: str  # excellent, good, moderate, poor, very_poor
    solar_remaining_today_kwh: float
    grid_import_w: float      # Current import (positive = importing)
    grid_export_w: float      # Current export (positive = exporting)
    
    # Load State
    pool_power_w: float
    hvac_power_w: float
    evse_power_w: float
    total_consumption_w: float
    
    # Device State
    pool_running: bool
    evse_a_charging: bool
    evse_b_charging: bool
    battery_mode: str         # Current mode
    
    # Environment
    outdoor_temp_f: float
    
    # Occupancy
    census_count: int
    rooms_occupied: list[str]


@dataclass
class EnergySituation:
    """Classified energy situation."""
    name: str                 # NORMAL, PRE_CONDITION, EXPENSIVE, etc.
    urgency: int              # 0-100, higher = more urgent action needed
    time_horizon_minutes: int # How long this situation likely to last
    target_period: str | None = None  # For PRE_CONDITION: what period coming
    export_opportunity: bool = False   # Can we profitably export?


class SituationClassifier:
    """Classify current energy situation for decision making."""
    
    def classify(self, ctx: EnergyContext) -> EnergySituation:
        """
        Determine operating situation based on all inputs.
        
        Priority order (check first to last, return first match):
        1. EMERGENCY - Safety critical
        2. CRITICAL - Battery very low during peak
        3. EXPORT_OPPORTUNITY - Can export at high value
        4. CONSTRAINED - Peak with poor conditions
        5. PRE_CONDITION - Approaching expensive period
        6. EXPENSIVE - In expensive period
        7. NORMAL - Default operation
        """
        
        # 1. EMERGENCY
        if ctx.battery_soc < 10 and ctx.tou_period == "peak":
            return EnergySituation(
                name="EMERGENCY",
                urgency=100,
                time_horizon_minutes=self._minutes_until_off_peak(ctx),
            )
        
        # 2. CRITICAL
        if (ctx.tou_period == "peak" and 
            ctx.solar_forecast_quality in ["poor", "very_poor"] and
            ctx.battery_soc < 25):
            return EnergySituation(
                name="CRITICAL",
                urgency=85,
                time_horizon_minutes=self._minutes_until_off_peak(ctx),
            )
        
        # 3. EXPORT_OPPORTUNITY - Key for TOU export credits!
        if self._is_export_opportunity(ctx):
            return EnergySituation(
                name="EXPORT_OPPORTUNITY",
                urgency=60,  # Profitable but not critical
                time_horizon_minutes=ctx.minutes_until_period_change,
                export_opportunity=True,
            )
        
        # 4. CONSTRAINED
        if (ctx.tou_period == "peak" and 
            ctx.solar_forecast_quality in ["moderate", "poor"] and
            ctx.battery_soc < 40):
            return EnergySituation(
                name="CONSTRAINED",
                urgency=70,
                time_horizon_minutes=ctx.minutes_until_period_change,
            )
        
        # 5. PRE_CONDITION (approaching expensive period)
        if ctx.minutes_until_period_change <= 60:
            next_period = self._get_next_period(ctx)
            if next_period in ["mid_peak", "peak"] and ctx.tou_period == "off_peak":
                return EnergySituation(
                    name="PRE_CONDITION",
                    urgency=60 - ctx.minutes_until_period_change,  # More urgent as time passes
                    time_horizon_minutes=ctx.minutes_until_period_change,
                    target_period=next_period,
                )
        
        # 6. EXPENSIVE
        if ctx.tou_period in ["mid_peak", "peak"]:
            urgency = 70 if ctx.tou_period == "peak" else 40
            # Reduce urgency if solar is helping
            if ctx.solar_forecast_quality in ["excellent", "good"]:
                urgency -= 20
            return EnergySituation(
                name="EXPENSIVE",
                urgency=urgency,
                time_horizon_minutes=ctx.minutes_until_period_change,
            )
        
        # 7. NORMAL
        return EnergySituation(
            name="NORMAL",
            urgency=0,
            time_horizon_minutes=ctx.minutes_until_period_change,
        )
    
    def _is_export_opportunity(self, ctx: EnergyContext) -> bool:
        """
        Detect export opportunity - when we can export at high value.
        
        Conditions:
        - Peak period (highest export credit: $0.16/kWh)
        - Battery > 60% (have energy to export)
        - Solar covering home load (export from battery, not solar)
        - OR solar excess + battery available
        """
        if ctx.tou_period != "peak":
            return False
        
        if ctx.battery_soc < 60:
            return False
        
        # Solar covering load means battery can export
        home_load_covered_by_solar = ctx.solar_now_w >= ctx.total_consumption_w
        
        # Or we have enough battery to export while covering load
        battery_can_cover_and_export = (
            ctx.battery_soc > 80 and
            ctx.solar_now_w > ctx.total_consumption_w * 0.5
        )
        
        return home_load_covered_by_solar or battery_can_cover_and_export
    
    def _get_next_period(self, ctx: EnergyContext) -> str:
        """Get the next TOU period."""
        # Logic depends on season and current period
        period_order = {
            "summer": ["off_peak", "mid_peak", "peak", "mid_peak", "off_peak"],
            "shoulder": ["off_peak", "mid_peak", "off_peak"],
            "winter": ["off_peak", "mid_peak", "off_peak", "mid_peak", "off_peak"],
        }
        # Simplified - actual implementation uses TOU schedule
        return "peak" if ctx.tou_period == "mid_peak" else "mid_peak"
    
    def _minutes_until_off_peak(self, ctx: EnergyContext) -> int:
        """Calculate minutes until off-peak starts."""
        # Depends on season and current time
        # Summer peak ends at 8pm → off_peak at 9pm
        return ctx.minutes_until_period_change + 60  # Approximate
```

### Action Generator Implementation

```python
# domain_coordinators/energy/action_generator.py

@dataclass
class BatteryAction:
    """Action for battery/Enphase system."""
    mode: str                 # backup, self_consumption, savings
    reserve_level: int        # 10-100%
    charge_from_grid: bool
    export_to_grid: bool      # NEW: Explicitly export for credits
    reason: str


@dataclass
class PoolAction:
    """Action for pool equipment."""
    circuits_on: list[str]    # Entity IDs to turn on
    circuits_off: list[str]   # Entity IDs to turn off
    reason: str


@dataclass  
class EVSEAction:
    """Action for EV charger."""
    enable: bool
    reason: str


@dataclass
class HVACConstraint:
    """Constraint to publish to HVAC Coordinator."""
    mode: str                 # normal, pre_cool, pre_heat, coast, shed
    setpoint_offset: float    # °F offset from user preference
    occupied_only: bool       # Only condition occupied zones
    max_runtime_minutes: int | None  # Limit HVAC runtime during peak
    reason: str


@dataclass
class EnergyActions:
    """Complete set of actions from decision engine."""
    battery: BatteryAction | None = None
    pool: PoolAction | None = None
    evse_a: EVSEAction | None = None
    evse_b: EVSEAction | None = None
    hvac: HVACConstraint | None = None


class EnergyActionGenerator:
    """Generate specific actions based on situation."""
    
    def generate(self, situation: EnergySituation, ctx: EnergyContext) -> EnergyActions:
        """Generate actions for current situation."""
        
        if situation.name == "EMERGENCY":
            return self._emergency_actions(ctx)
        elif situation.name == "CRITICAL":
            return self._critical_actions(ctx)
        elif situation.name == "EXPORT_OPPORTUNITY":
            return self._export_opportunity_actions(ctx)
        elif situation.name == "CONSTRAINED":
            return self._constrained_actions(ctx)
        elif situation.name == "PRE_CONDITION":
            return self._pre_condition_actions(situation, ctx)
        elif situation.name == "EXPENSIVE":
            return self._expensive_actions(ctx)
        else:
            return self._normal_actions(ctx)
    
    def _export_opportunity_actions(self, ctx: EnergyContext) -> EnergyActions:
        """
        Actions when export opportunity detected.
        
        Goal: Maximize export to grid at peak rate ($0.16/kWh credit)
        
        Strategy:
        - Battery: Export mode (discharge to grid, not just home)
        - Pool: OFF (reduce home load so more can export)
        - EVSE: OFF (reduce load)
        - HVAC: Coast (reduce load, pre-cooled thermal mass carries through)
        """
        return EnergyActions(
            battery=BatteryAction(
                mode="savings",  # TOU mode enables export
                reserve_level=20,  # Keep 20% for backup
                charge_from_grid=False,
                export_to_grid=True,  # EXPORT for credits!
                reason=f"Export opportunity: ${ctx.tou_rate_export:.4f}/kWh credit",
            ),
            
            pool=PoolAction(
                circuits_on=[],
                circuits_off=["switch.pool", "switch.infinity_edge", "switch.booster_pump"],
                reason="Reduce load to maximize export",
            ),
            
            evse_a=EVSEAction(enable=False, reason="Reduce load for export"),
            evse_b=EVSEAction(enable=False, reason="Reduce load for export"),
            
            hvac=HVACConstraint(
                mode="coast",
                setpoint_offset=+3.0,
                occupied_only=True,
                max_runtime_minutes=15,  # Limit HVAC to maximize export
                reason="Coasting to maximize peak export value",
            ),
        )
    
    def _pre_condition_actions(
        self, 
        situation: EnergySituation, 
        ctx: EnergyContext
    ) -> EnergyActions:
        """
        Actions when approaching expensive period.
        
        Goal: Prepare for peak - charge battery, pre-cool, run loads now
        
        From TOU analysis: Pre-cool 2-4pm before 4-8pm peak (summer)
        """
        # Determine pre-cool aggressiveness based on target period
        if situation.target_period == "peak":
            setpoint_offset = -3.0  # Aggressive pre-cool
        else:
            setpoint_offset = -2.0  # Moderate
        
        return EnergyActions(
            battery=BatteryAction(
                mode="self_consumption",
                reserve_level=20,
                charge_from_grid=ctx.battery_soc < 90,  # Top up if needed
                export_to_grid=False,  # Save for peak
                reason=f"Building charge before {situation.target_period}",
            ),
            
            pool=PoolAction(
                circuits_on=["switch.pool"],  # Run now before peak
                circuits_off=[],
                reason="Run pool before peak rates",
            ),
            
            evse_a=EVSEAction(enable=True, reason="Charge before peak"),
            evse_b=EVSEAction(enable=True, reason="Charge before peak"),
            
            hvac=HVACConstraint(
                mode="pre_cool",
                setpoint_offset=setpoint_offset,
                occupied_only=False,  # Pre-cool ALL zones for thermal mass
                max_runtime_minutes=None,  # Run as needed
                reason=f"Pre-cooling before {situation.target_period}",
            ),
        )
    
    def _expensive_actions(self, ctx: EnergyContext) -> EnergyActions:
        """
        Actions during mid-peak or peak.
        
        Goal: Minimize import, use battery, consider export
        
        From TOU analysis:
        - Peak (4-8pm): Coast +2-3°F, stop pool, discharge battery
        - Mid-peak: Moderate conservation
        """
        is_peak = ctx.tou_period == "peak"
        
        # Determine if we should export or just cover home load
        should_export = (
            is_peak and 
            ctx.battery_soc > 60 and 
            ctx.solar_now_w > ctx.total_consumption_w * 0.7
        )
        
        return EnergyActions(
            battery=BatteryAction(
                mode="savings",
                reserve_level=20,
                charge_from_grid=False,
                export_to_grid=should_export,
                reason=f"{'Exporting' if should_export else 'Covering home load'} during {ctx.tou_period}",
            ),
            
            pool=PoolAction(
                circuits_on=[] if is_peak else (["switch.pool"] if ctx.solar_now_w > 2000 else []),
                circuits_off=["switch.pool", "switch.infinity_edge"] if is_peak else [],
                reason="Pool off during peak" if is_peak else "Pool follows solar",
            ),
            
            evse_a=EVSEAction(
                enable=not is_peak and ctx.solar_now_w > 5000,
                reason="No charging during peak" if is_peak else "Charge with solar excess",
            ),
            evse_b=EVSEAction(
                enable=not is_peak and ctx.solar_now_w > 8000,
                reason="No charging during peak" if is_peak else "Charge with solar excess",
            ),
            
            hvac=HVACConstraint(
                mode="coast",
                setpoint_offset=+3.0 if is_peak else +2.0,
                occupied_only=True,
                max_runtime_minutes=15 if is_peak else None,
                reason=f"Coasting during {ctx.tou_period} @ ${ctx.tou_rate_import:.4f}/kWh",
            ),
        )
    
    def _normal_actions(self, ctx: EnergyContext) -> EnergyActions:
        """
        Actions during normal off-peak operation.
        
        Goal: Normal comfort, charge battery if needed, run loads freely
        """
        return EnergyActions(
            battery=BatteryAction(
                mode="self_consumption",
                reserve_level=20,
                charge_from_grid=ctx.battery_soc < 80 and ctx.solar_forecast_quality in ["poor", "very_poor"],
                export_to_grid=False,  # Off-peak export not valuable
                reason="Normal self-consumption",
            ),
            
            pool=PoolAction(
                circuits_on=["switch.pool"] if not ctx.pool_running else [],
                circuits_off=[],
                reason="Normal pool schedule",
            ),
            
            evse_a=EVSEAction(enable=True, reason="Off-peak charging allowed"),
            evse_b=EVSEAction(enable=True, reason="Off-peak charging allowed"),
            
            hvac=HVACConstraint(
                mode="normal",
                setpoint_offset=0,
                occupied_only=False,
                max_runtime_minutes=None,
                reason="Normal operation - off-peak",
            ),
        )
    
    def _emergency_actions(self, ctx: EnergyContext) -> EnergyActions:
        """Emergency: Battery critical during peak."""
        return EnergyActions(
            battery=BatteryAction(
                mode="backup",
                reserve_level=15,
                charge_from_grid=False,
                export_to_grid=False,
                reason="EMERGENCY: Battery critical",
            ),
            pool=PoolAction(circuits_on=[], circuits_off=["switch.pool", "switch.infinity_edge", "switch.booster_pump", "switch.spa"], reason="Emergency shed"),
            evse_a=EVSEAction(enable=False, reason="Emergency shed"),
            evse_b=EVSEAction(enable=False, reason="Emergency shed"),
            hvac=HVACConstraint(mode="shed", setpoint_offset=+5.0, occupied_only=True, max_runtime_minutes=10, reason="Emergency load shedding"),
        )
    
    def _critical_actions(self, ctx: EnergyContext) -> EnergyActions:
        """Critical: Low battery + poor solar during peak."""
        return EnergyActions(
            battery=BatteryAction(mode="savings", reserve_level=15, charge_from_grid=False, export_to_grid=False, reason="Conserving for critical period"),
            pool=PoolAction(circuits_on=[], circuits_off=["switch.pool", "switch.infinity_edge"], reason="Critical load reduction"),
            evse_a=EVSEAction(enable=False, reason="Critical - no charging"),
            evse_b=EVSEAction(enable=False, reason="Critical - no charging"),
            hvac=HVACConstraint(mode="coast", setpoint_offset=+4.0, occupied_only=True, max_runtime_minutes=15, reason="Critical conservation"),
        )
    
    def _constrained_actions(self, ctx: EnergyContext) -> EnergyActions:
        """Constrained: Peak with moderate battery."""
        return EnergyActions(
            battery=BatteryAction(mode="savings", reserve_level=20, charge_from_grid=False, export_to_grid=False, reason="Constrained discharge"),
            pool=PoolAction(circuits_on=[], circuits_off=["switch.pool"], reason="Constrained - pool off"),
            evse_a=EVSEAction(enable=False, reason="Constrained - no charging"),
            evse_b=EVSEAction(enable=False, reason="Constrained - no charging"),
            hvac=HVACConstraint(mode="coast", setpoint_offset=+3.0, occupied_only=True, max_runtime_minutes=20, reason="Constrained operation"),
        )
```

### Decision Engine Execution Loop

```python
# domain_coordinators/energy/coordinator.py (addition)

class EnergyCoordinator:
    """Energy Coordinator with Decision Engine integration."""
    
    async def _decision_cycle(self) -> None:
        """
        Main decision cycle - runs every 60 seconds.
        
        1. Gather all inputs into EnergyContext
        2. Classify situation
        3. Generate actions
        4. Execute direct controls (battery, pool, EVSE)
        5. Publish HVAC constraints
        """
        # 1. Gather context
        ctx = await self._gather_context()
        
        # 2. Classify situation
        situation = self._classifier.classify(ctx)
        
        _LOGGER.info(
            f"Energy Decision: {situation.name} (urgency={situation.urgency}, "
            f"horizon={situation.time_horizon_minutes}min)"
        )
        
        # 3. Generate actions
        actions = self._action_generator.generate(situation, ctx)
        
        # 4. Execute direct controls
        if actions.battery:
            await self._execute_battery_action(actions.battery)
        if actions.pool:
            await self._execute_pool_action(actions.pool)
        if actions.evse_a:
            await self._execute_evse_action("switch.garage_a", actions.evse_a)
        if actions.evse_b:
            await self._execute_evse_action("switch.garage_b", actions.evse_b)
        
        # 5. Publish HVAC constraints (HVAC Coordinator listens)
        if actions.hvac:
            await self.event_bus.publish(DomainEvent(
                type="energy.hvac_constraint",
                source="energy_coordinator",
                data=asdict(actions.hvac),
            ))
        
        # 6. Update sensors
        await self._update_decision_sensors(situation, actions)
```

---

## 5. ENERGY COORDINATOR ARCHITECTURE

### Core Class Structure

```python
# domain_coordinators/energy/coordinator.py

class EnergyCoordinator:
    """
    Whole-house energy optimization - Active Controller + HVAC Governor.
    
    Responsibilities:
    - ACTIVELY CONTROL battery, pool, EVSEs (direct service calls)
    - GOVERN HVAC through published constraints
    - Monitor TOU periods and solar forecasts
    - Execute decision engine every 60 seconds
    
    Philosophy:
    - Active controller for house-level infrastructure
    - Governor for room-level HVAC
    - Livability first (comfort impact scoring)
    - Fail-safe (if uncertain, do less)
    """
    
    def __init__(self, hass: HomeAssistant, event_bus: DomainEventBus) -> None:
        """Initialize energy coordinator."""
        self.hass = hass
        self.event_bus = event_bus
        
        # Configuration (from options flow)
        self.tou_schedule: dict = {}
        self.load_priorities: list = []
        self.entity_mappings: dict = {}
        
        # State tracking
        self._current_period: str = "off_peak"
        self._current_season: str = "summer"
        self._battery_soc: float = 0.0
        self._solar_production: float = 0.0
        self._grid_power: float = 0.0
        self._total_load: float = 0.0
        
        # Strategy state
        self._hvac_constraints: HVACConstraints = None
        self._load_shedding_active: bool = False
        self._active_deferrals: list = []
        
        # Event subscriptions
        self.event_bus.subscribe("hvac_request", self._on_hvac_request)
        self.event_bus.subscribe("census_update", self._on_census_update)
    
    async def async_init(self) -> None:
        """Initialize coordinator with entity discovery."""
        # Discover hardware entities
        await self._discover_enphase_entities()
        await self._discover_span_circuits()
        await self._discover_ev_chargers()
        await self._discover_pool_equipment()
        
        # Load configuration
        self.tou_schedule = await self._load_tou_schedule()
        self.load_priorities = await self._load_priorities()
        
        # Start monitoring loops
        self._schedule_tou_monitoring()
        self._schedule_optimization_loop()
        
        # Publish initial state
        await self._publish_initial_state()
    
    # === TOU PERIOD MANAGEMENT ===
    
    def get_current_tou_period(self) -> str:
        """Get current TOU period based on time and season."""
        now = dt_util.now()
        hour = now.hour
        month = now.month
        
        season = self._get_season(month)
        schedule = self.tou_schedule.get(season)
        
        for period in schedule.periods:
            for start, end in period.hours:
                if start <= hour < end:
                    return period.name
        
        return "off_peak"  # Default
    
    async def _on_tou_period_change(self, new_period: str) -> None:
        """Handle TOU period transition."""
        old_period = self._current_period
        self._current_period = new_period
        
        _LOGGER.info(f"Energy: TOU period changed {old_period} → {new_period}")
        
        # Calculate new HVAC constraints
        constraints = self._calculate_hvac_constraints(new_period)
        
        # Publish to event bus (HVAC Coordinator listens)
        await self.event_bus.publish(DomainEvent(
            type="tou_period_changed",
            source="energy_coordinator",
            data={
                "old_period": old_period,
                "new_period": new_period,
                "season": self._current_season,
                "hvac_constraints": constraints.to_dict(),
                "timestamp": dt_util.now().isoformat(),
            }
        ))
        
        # Execute period-specific actions
        await self._execute_period_transition_actions(old_period, new_period)
    
    # === HVAC GOVERNANCE ===
    
    def _calculate_hvac_constraints(self, period: str) -> "HVACConstraints":
        """Calculate HVAC constraints for current period."""
        season = self._current_season
        person_count = self._get_census_count()
        
        if season == "summer":
            if period == "peak":
                return HVACConstraints(
                    mode="coast",
                    setpoint_offset=+3.0,  # Allow warmer
                    max_power_kw=5.0,       # Limit compressor runtime
                    occupied_only=True,     # Only cool occupied rooms
                    reason="Summer peak - coast mode",
                )
            elif period == "mid_peak" and self._is_pre_cooling_window():
                return HVACConstraints(
                    mode="pre_cool",
                    setpoint_offset=-3.0,  # Aggressive cooling
                    max_power_kw=None,      # No limit
                    occupied_only=False,    # Pre-cool predicted rooms too
                    reason="Summer mid-peak - pre-cooling window",
                )
        
        # Default: no constraints
        return HVACConstraints(
            mode="normal",
            setpoint_offset=0.0,
            max_power_kw=None,
            occupied_only=False,
            reason="Off-peak - normal operation",
        )
    
    async def _on_hvac_request(self, event: DomainEvent) -> None:
        """
        Handle HVAC request from rooms or HVAC Coordinator.
        
        This is where Energy Coordinator acts as governor:
        - Review the request against current constraints
        - Approve, modify, or deny
        - Publish response
        """
        request = event.data
        room = request.get("room")
        action = request.get("action")  # "cool", "heat", "fan"
        
        constraints = self._hvac_constraints
        
        # Check if request violates constraints
        if constraints and constraints.mode == "coast":
            if action == "cool" and not request.get("emergency"):
                # Modify request: allow but with offset
                await self.event_bus.publish(DomainEvent(
                    type="hvac_request_modified",
                    source="energy_coordinator",
                    data={
                        "original_request": request,
                        "modification": "setpoint_offset",
                        "offset": constraints.setpoint_offset,
                        "reason": constraints.reason,
                    }
                ))
                return
        
        # Request approved without modification
        await self.event_bus.publish(DomainEvent(
            type="hvac_request_approved",
            source="energy_coordinator",
            data={"request": request}
        ))
    
    # === BATTERY OPTIMIZATION ===
    
    async def optimize_battery_strategy(self) -> "BatteryStrategy":
        """
        Determine optimal battery strategy.
        
        Strategy Matrix:
        
        OFF-PEAK:
        - If SOC < 80% AND low solar forecast: Charge from grid
        - If SOC > 80%: Hold, solar will top up
        
        MID-PEAK (pre-peak):
        - Ensure SOC > 90% before peak
        - Charge from solar if available
        
        PEAK:
        - Discharge to offset home load
        - Target: minimize grid import
        - Reserve: keep 20% for backup
        
        CRITICAL (battery < 15%):
        - Emergency load shedding
        - Disable all deferrals
        """
        soc = await self._get_battery_soc()
        solar = await self._get_solar_production()
        solar_forecast = await self._get_solar_forecast(hours=4)
        period = self.get_current_tou_period()
        
        if soc < 15:
            # CRITICAL - emergency mode
            return BatteryStrategy(
                mode="emergency_hold",
                target_soc=15,
                allow_discharge=False,
                load_shedding_required=True,
                reason=f"Battery critical at {soc}%",
            )
        
        if period == "peak":
            if soc > 20:
                return BatteryStrategy(
                    mode="discharge",
                    target_soc=20,
                    discharge_rate_kw=5.0,  # Moderate discharge
                    reason="Peak period - offsetting grid import",
                )
            else:
                return BatteryStrategy(
                    mode="hold",
                    reason="Peak period but SOC too low to discharge",
                )
        
        if period == "off_peak":
            if soc < 80 and solar_forecast < 15:  # Less than 15 kWh forecast
                return BatteryStrategy(
                    mode="charge_from_grid",
                    target_soc=80,
                    charge_rate_kw=5.0,
                    reason="Off-peak grid charging - low solar forecast",
                )
        
        if period == "mid_peak":
            # Pre-peak: ensure batteries ready
            if soc < 90:
                return BatteryStrategy(
                    mode="charge_from_solar",
                    target_soc=95,
                    reason="Mid-peak solar charging before peak",
                )
        
        return BatteryStrategy(
            mode="self_consumption",
            reason="Default self-consumption mode",
        )
    
    # === LOAD MANAGEMENT ===
    
    async def evaluate_load_shedding(self) -> list["LoadSheddingAction"]:
        """
        Evaluate if load shedding is needed.
        
        Triggers:
        1. Peak period AND grid import > 5 kW
        2. Battery SOC < 15%
        3. Total load > solar production + battery discharge
        
        Priority Order (shed first → last):
        1. Pool pump (invisible, long recovery OK)
        2. EV charging (invisible, can resume later)
        3. Water heater (invisible, thermal mass OK)
        4. HVAC setback +2°F (noticeable but livable)
        5. Non-critical circuits via SPAN (noticeable)
        """
        actions = []
        
        period = self.get_current_tou_period()
        soc = await self._get_battery_soc()
        grid_import = await self._get_grid_import()
        
        # Trigger 1: Peak + high grid import
        if period == "peak" and grid_import > 5.0:
            # Shed in priority order
            actions.extend(await self._generate_shedding_actions(
                target_reduction=grid_import - 2.0,  # Target 2 kW import
                trigger="peak_grid_import"
            ))
        
        # Trigger 2: Battery critical
        if soc < 15:
            actions.extend(await self._generate_shedding_actions(
                target_reduction=None,  # Shed everything deferrable
                trigger="battery_critical"
            ))
        
        return actions
    
    async def _generate_shedding_actions(
        self, 
        target_reduction: float | None,
        trigger: str
    ) -> list["LoadSheddingAction"]:
        """Generate load shedding actions based on priority."""
        actions = []
        current_reduction = 0.0
        
        for load in self.load_priorities:
            if target_reduction and current_reduction >= target_reduction:
                break
            
            # Check if load is currently active
            state = self.hass.states.get(load.entity_id)
            if not state or state.state in ["off", "unavailable"]:
                continue
            
            # Calculate power savings
            power = load.typical_power_kw
            
            # Create shedding action
            actions.append(LoadSheddingAction(
                priority=load.priority,
                entity_id=load.entity_id,
                action=load.shed_action,  # "turn_off", "pause", "reduce"
                power_reduction_kw=power,
                recovery_delay_minutes=load.recovery_delay,
                comfort_impact=load.comfort_impact,
                trigger=trigger,
            ))
            
            current_reduction += power
        
        return actions
    
    # === DEFERRABLE LOAD SCHEDULING ===
    
    async def schedule_pool_pump(self) -> None:
        """
        Schedule pool pump for optimal TOU periods.
        
        Summer: Run 6am-2pm (off-peak + peak solar)
        Avoid: 4pm-8pm (peak rates)
        """
        season = self._current_season
        
        if season == "summer":
            schedule = {
                "start": time(6, 0),
                "end": time(14, 0),
                "duration_hours": 8,
                "avoid_periods": ["peak"],
            }
        elif season in ["shoulder", "winter"]:
            schedule = {
                "start": time(9, 0),
                "end": time(17, 0),
                "duration_hours": 6,
                "avoid_periods": ["mid_peak"],
            }
        
        await self._apply_pool_schedule(schedule)
    
    async def schedule_ev_charging(self) -> None:
        """
        Schedule EV charging for off-peak periods.
        
        Default: 12am-6am (deep off-peak)
        Smart: Based on departure time + needed charge
        """
        # Check if any EV needs charging
        for charger in self.entity_mappings.get("ev_chargers", []):
            state = self.hass.states.get(charger)
            if not state:
                continue
            
            # If currently charging during expensive period, pause
            current_period = self.get_current_tou_period()
            if state.state == "on" and current_period in ["mid_peak", "peak"]:
                await self.hass.services.async_call(
                    "switch", "turn_off", {"entity_id": charger}
                )
                
                # Schedule resume at off-peak
                self._schedule_resume(charger, wait_for="off_peak")
    
    # === CENSUS INTEGRATION ===
    
    async def _on_census_update(self, event: DomainEvent) -> None:
        """
        Handle census update from Person Coordinator (v3.5.0).
        
        Census data affects:
        - Load predictions (more people = more load)
        - HVAC priority (adjust for occupant count)
        - Pre-cooling aggressiveness
        """
        census = event.data
        person_count = census.get("total_count", 0)
        identified = census.get("identified", [])
        
        # Adjust predictions based on occupancy
        # More people = higher evening load prediction
        expected_peak_load = self._base_peak_load + (person_count * 0.5)  # kWh per person
        
        # Store for other calculations
        self._census_data = census
        
        _LOGGER.debug(
            f"Energy: Census update - {person_count} people, "
            f"expected peak load: {expected_peak_load:.1f} kWh"
        )
```

---

## 6. HVAC COORDINATOR

### Overview: Multi-Zone Climate Control with Energy Awareness

The HVAC Coordinator is a **separate domain coordinator** that:
1. **Manages** the 3 Carrier Infinity HVAC zones directly
2. **Responds** to constraints from Energy Coordinator
3. **Aggregates** room conditions from many URA rooms → fewer HVAC zones
4. **Coordinates** room fans based on temperature/humidity conditions
5. **Chooses** between coarse control (presets) and fine control (setpoints)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          HVAC COORDINATOR                                    │
│              "Multi-Zone Climate Control with Energy Awareness"              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                  CARRIER INFINITY HVAC ZONES (3)                    │    │
│  ├─────────────────────────────────────────────────────────────────────┤    │
│  │                                                                     │    │
│  │  ZONE 1: Master Suite (1st Floor)                                  │    │
│  │  Entity: climate.thermostat_bryant_wifi_studyb_zone_1              │    │
│  │  URA Rooms: master_bedroom, master_bathroom, master_closet         │    │
│  │                                                                     │    │
│  │  ZONE 2: Upstairs (2nd Floor)                                      │    │
│  │  Entity: climate.up_hallway_zone_2                                 │    │
│  │  URA Rooms: kids_bedroom_1, kids_bedroom_2, game_room,             │    │
│  │             upstairs_bathroom, upstairs_hallway                    │    │
│  │                                                                     │    │
│  │  ZONE 3: Back Hallway (1st Floor - Main Living)                    │    │
│  │  Entity: climate.back_hallway_zone_3                               │    │
│  │  URA Rooms: living_room, kitchen, dining_room, office,             │    │
│  │             guest_bedroom, media_room                              │    │
│  │                                                                     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │               CARRIER INFINITY CONTROL CAPABILITIES                 │    │
│  ├─────────────────────────────────────────────────────────────────────┤    │
│  │                                                                     │    │
│  │  COARSE CONTROL (Presets) - Preferred for energy modes             │    │
│  │  ┌────────────────────────────────────────────────────────────┐    │    │
│  │  │  preset_mode options:                                      │    │    │
│  │  │  • away     - Wide band, minimal conditioning (unoccupied) │    │    │
│  │  │  • home     - Normal comfort band (daily operation)        │    │    │
│  │  │  • sleep    - Optimized for sleeping (wider band OK)       │    │    │
│  │  │  • wake     - Transition to active comfort                 │    │    │
│  │  │  • vacation - Extended absence, minimal conditioning       │    │    │
│  │  │  • manual   - User override, HVAC Coord doesn't touch      │    │    │
│  │  │  • resume   - Return to scheduled programming              │    │    │
│  │  └────────────────────────────────────────────────────────────┘    │    │
│  │                                                                     │    │
│  │  FINE CONTROL (Temperature) - For precise energy optimization      │    │
│  │  ┌────────────────────────────────────────────────────────────┐    │    │
│  │  │  • target_temp_high: Cooling setpoint (1°F granularity)    │    │    │
│  │  │  • target_temp_low:  Heating setpoint (1°F granularity)    │    │    │
│  │  │  • Range: 45°F - 95°F                                      │    │    │
│  │  │  • Use for: Pre-cool offsets, coast offsets                │    │    │
│  │  └────────────────────────────────────────────────────────────┘    │    │
│  │                                                                     │    │
│  │  MODE CONTROL                                                       │    │
│  │  ┌────────────────────────────────────────────────────────────┐    │    │
│  │  │  hvac_mode: off, fan_only, heat_cool, heat, cool           │    │    │
│  │  │  fan_mode:  low, med, high, auto                           │    │    │
│  │  └────────────────────────────────────────────────────────────┘    │    │
│  │                                                                     │    │
│  │  MONITORING (Read-Only)                                            │    │
│  │  ┌────────────────────────────────────────────────────────────┐    │    │
│  │  │  • current_temperature, current_humidity                   │    │    │
│  │  │  • hvac_action: idle, heating, cooling                     │    │    │
│  │  │  • conditioning: active_heat, active_cool, idle            │    │    │
│  │  │  • blower_rpm: Fan speed feedback                          │    │    │
│  │  └────────────────────────────────────────────────────────────┘    │    │
│  │                                                                     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Zone-to-Room Mapping Configuration

**The Problem:** URA has many room zones (potentially 20+), but only 3 HVAC zones exist. Multiple URA rooms share each HVAC zone. The HVAC Coordinator must:
- Aggregate occupancy from all rooms in an HVAC zone
- Use worst-case temperature for decisions (hottest room in summer)
- Allow user configuration of room→HVAC zone mapping

```python
# domain_coordinators/hvac/zone_mapping.py

@dataclass
class HVACZoneConfig:
    """Configuration for an HVAC zone and its room mappings."""
    
    zone_id: str                    # e.g., "zone_1_master"
    climate_entity: str             # e.g., "climate.thermostat_bryant_wifi_studyb_zone_1"
    friendly_name: str              # e.g., "Master Suite"
    floor: str                      # "first", "second"
    
    # Room mappings (URA room_id → weight for aggregation)
    # Weight affects how much this room influences zone decisions
    room_mappings: dict[str, float] = field(default_factory=dict)
    # Example: {"master_bedroom": 1.0, "master_bathroom": 0.5, "master_closet": 0.3}
    
    # User preferences for this zone
    user_setpoint_cool: float = 74.0  # Default cooling setpoint
    user_setpoint_heat: float = 70.0  # Default heating setpoint
    
    # Sleep hours for this zone (None if not applicable)
    sleep_schedule: tuple[int, int] | None = None  # (start_hour, end_hour)
    
    # Associated fans in rooms covered by this zone
    room_fans: list[str] = field(default_factory=list)


# Default zone configuration (user can customize via options flow)
DEFAULT_HVAC_ZONES = {
    "zone_1_master": HVACZoneConfig(
        zone_id="zone_1_master",
        climate_entity="climate.thermostat_bryant_wifi_studyb_zone_1",
        friendly_name="Master Suite",
        floor="first",
        room_mappings={
            "master_bedroom": 1.0,      # Primary room, full weight
            "master_bathroom": 0.5,     # Secondary, less influence
            "master_closet": 0.3,       # Minimal influence
        },
        user_setpoint_cool=73.0,
        user_setpoint_heat=70.0,
        sleep_schedule=(22, 7),  # 10pm - 7am
        room_fans=[
            "fan.ceilingfan_fanimaton_rf304_25_masterbedroom",
            "fan.polyfan_508s_wifi_masterbedroom",
        ],
    ),
    
    "zone_2_upstairs": HVACZoneConfig(
        zone_id="zone_2_upstairs",
        climate_entity="climate.up_hallway_zone_2",
        friendly_name="Upstairs",
        floor="second",
        room_mappings={
            "kids_bedroom_ziri": 1.0,
            "kids_bedroom_jaya": 1.0,
            "game_room": 0.8,
            "upstairs_bathroom": 0.3,
            "upstairs_hallway": 0.2,
            "exercise_room": 0.7,
        },
        user_setpoint_cool=74.0,
        user_setpoint_heat=70.0,
        sleep_schedule=(21, 7),  # 9pm - 7am (kids earlier)
        room_fans=[
            "fan.fanswitch_treat_wifi_ziribedroom",
            "fan.fanswitch_treat_wifi_jayabedroom",
            "fan.game_room_ceiling_fan",
            "fan.fan_switch_3",  # Exercise
            "fan.fan_switch_4",  # UpGuest
        ],
    ),
    
    "zone_3_main": HVACZoneConfig(
        zone_id="zone_3_main",
        climate_entity="climate.back_hallway_zone_3",
        friendly_name="Main Living",
        floor="first",
        room_mappings={
            "living_room": 1.0,
            "kitchen": 0.9,
            "dining_room": 0.8,
            "office_a": 0.9,
            "office_b": 0.9,
            "guest_bedroom": 0.7,
            "media_room": 0.8,
            "breakfast_nook": 0.6,
        },
        user_setpoint_cool=74.0,
        user_setpoint_heat=70.0,
        sleep_schedule=None,  # Main living areas, no sleep schedule
        room_fans=[
            "fan.towerfan_dreopilotmaxs_wifi_livingroom",
            "fan.polyfan_dreo704s_wifi_studya",
            "fan.media_room_ceiling_fan",
            "fan.guest_room_down_ceiling_fan",
            "fan.151732606487193_fan",  # Kitchen/Breakfast
        ],
    ),
}
```

### Control Strategy: Coarse vs Fine

**Philosophy:** Use presets (coarse) for major mode changes, use temperature offsets (fine) for energy optimization within a mode.

```python
# domain_coordinators/hvac/control_strategy.py

class HVACControlStrategy(Enum):
    """Strategy for HVAC control decisions."""
    
    # COARSE CONTROL - Use presets, minimize cycling
    PRESET_BASED = "preset_based"
    # - Best for: Major occupancy changes (home→away→home)
    # - How: Change preset_mode, let thermostat manage setpoints
    # - Benefit: Thermostat's built-in schedules respected
    
    # FINE CONTROL - Direct temperature manipulation
    TEMPERATURE_BASED = "temperature_based"
    # - Best for: Energy optimization (pre-cool, coast)
    # - How: Adjust target_temp_high/low directly
    # - Benefit: Precise control of setpoint offsets
    
    # HYBRID - Preset for mode, temp for tuning
    HYBRID = "hybrid"
    # - Best for: Normal operation with energy awareness
    # - How: Set preset, then fine-tune temp within preset bounds


@dataclass
class HVACAction:
    """An action to take on an HVAC zone."""
    
    zone_id: str
    strategy: HVACControlStrategy
    
    # Coarse control
    preset_mode: str | None = None      # away, home, sleep, etc.
    hvac_mode: str | None = None        # off, heat_cool, cool, heat
    fan_mode: str | None = None         # auto, low, med, high
    
    # Fine control
    temp_offset_cool: float | None = None  # Offset from user setpoint
    temp_offset_heat: float | None = None
    
    # Direct setpoint (overrides offset if set)
    target_temp_high: float | None = None
    target_temp_low: float | None = None
    
    # Reason for logging/debugging
    reason: str = ""


class HVACActionGenerator:
    """Generate HVAC actions based on conditions and constraints."""
    
    def generate_for_energy_constraint(
        self,
        zone: HVACZoneConfig,
        zone_state: "HVACZoneState",
        constraint: "HVACConstraints",
    ) -> HVACAction:
        """
        Generate HVAC action for energy constraint.
        
        Strategy:
        - For PRE_COOL/PRE_HEAT: Use fine control (temperature offset)
        - For COAST: Use fine control (temperature offset)
        - For SHED: Use coarse control (preset=away or mode=off)
        - For NORMAL: Return to preset=home with user setpoints
        """
        
        if constraint.mode == "shed":
            # Emergency - use coarse control to minimize cycling
            return HVACAction(
                zone_id=zone.zone_id,
                strategy=HVACControlStrategy.PRESET_BASED,
                preset_mode="away",  # Widest temperature band
                reason=f"Energy shedding: {constraint.reason}",
            )
        
        if constraint.mode == "pre_cool":
            # Fine control - lower cooling setpoint
            return HVACAction(
                zone_id=zone.zone_id,
                strategy=HVACControlStrategy.TEMPERATURE_BASED,
                target_temp_high=zone.user_setpoint_cool + constraint.setpoint_offset,
                # Keep heating setpoint at user preference
                target_temp_low=zone.user_setpoint_heat,
                reason=f"Pre-cooling: {constraint.setpoint_offset}°F offset",
            )
        
        if constraint.mode == "pre_heat":
            # Fine control - raise heating setpoint
            return HVACAction(
                zone_id=zone.zone_id,
                strategy=HVACControlStrategy.TEMPERATURE_BASED,
                target_temp_low=zone.user_setpoint_heat + abs(constraint.setpoint_offset),
                target_temp_high=zone.user_setpoint_cool,
                reason=f"Pre-heating: {constraint.setpoint_offset}°F offset",
            )
        
        if constraint.mode == "coast":
            # Fine control - allow warmer (cooling) or cooler (heating)
            if zone_state.is_cooling_season:
                return HVACAction(
                    zone_id=zone.zone_id,
                    strategy=HVACControlStrategy.TEMPERATURE_BASED,
                    target_temp_high=zone.user_setpoint_cool + constraint.setpoint_offset,
                    target_temp_low=zone.user_setpoint_heat,
                    reason=f"Coasting: +{constraint.setpoint_offset}°F during peak",
                )
            else:
                return HVACAction(
                    zone_id=zone.zone_id,
                    strategy=HVACControlStrategy.TEMPERATURE_BASED,
                    target_temp_low=zone.user_setpoint_heat - abs(constraint.setpoint_offset),
                    target_temp_high=zone.user_setpoint_cool,
                    reason=f"Coasting: -{abs(constraint.setpoint_offset)}°F during peak",
                )
        
        # Normal mode - return to user preferences
        return HVACAction(
            zone_id=zone.zone_id,
            strategy=HVACControlStrategy.HYBRID,
            preset_mode="home",
            target_temp_high=zone.user_setpoint_cool,
            target_temp_low=zone.user_setpoint_heat,
            reason="Normal operation",
        )
```

### Room Condition Aggregation

Since multiple URA rooms map to one HVAC zone, we must aggregate their conditions:

```python
# domain_coordinators/hvac/aggregation.py

@dataclass
class AggregatedZoneConditions:
    """Aggregated conditions from all rooms in an HVAC zone."""
    
    zone_id: str
    
    # Occupancy - ANY room occupied = zone occupied
    any_room_occupied: bool
    occupied_rooms: list[str]
    total_occupancy_weight: float  # Sum of weights for occupied rooms
    
    # Temperature - use worst case for decisions
    hottest_room_temp: float
    hottest_room_id: str
    coldest_room_temp: float
    coldest_room_id: str
    weighted_avg_temp: float
    
    # Humidity - max for fan decisions
    max_humidity: float
    max_humidity_room_id: str
    weighted_avg_humidity: float
    
    # Time-based
    is_sleep_hours: bool
    predicted_occupied_soon: bool  # Based on patterns


class RoomConditionAggregator:
    """Aggregate room conditions for HVAC zone decisions."""
    
    def __init__(self, hass: HomeAssistant, zone_config: HVACZoneConfig):
        self.hass = hass
        self.zone_config = zone_config
    
    async def aggregate(self) -> AggregatedZoneConditions:
        """Aggregate conditions from all rooms in this HVAC zone."""
        
        occupied_rooms = []
        temps = []
        humidities = []
        total_weight = 0.0
        
        for room_id, weight in self.zone_config.room_mappings.items():
            # Get room entity states
            occ_state = self.hass.states.get(f"binary_sensor.{room_id}_occupancy")
            temp_state = self.hass.states.get(f"sensor.{room_id}_temperature")
            hum_state = self.hass.states.get(f"sensor.{room_id}_humidity")
            
            # Occupancy
            if occ_state and occ_state.state == "on":
                occupied_rooms.append(room_id)
                total_weight += weight
            
            # Temperature
            if temp_state and temp_state.state not in ("unavailable", "unknown"):
                temps.append({
                    "room_id": room_id,
                    "temp": float(temp_state.state),
                    "weight": weight,
                })
            
            # Humidity
            if hum_state and hum_state.state not in ("unavailable", "unknown"):
                humidities.append({
                    "room_id": room_id,
                    "humidity": float(hum_state.state),
                    "weight": weight,
                })
        
        # Calculate aggregates
        hottest = max(temps, key=lambda x: x["temp"]) if temps else {"room_id": "", "temp": 0}
        coldest = min(temps, key=lambda x: x["temp"]) if temps else {"room_id": "", "temp": 0}
        max_hum = max(humidities, key=lambda x: x["humidity"]) if humidities else {"room_id": "", "humidity": 0}
        
        weighted_temp = sum(t["temp"] * t["weight"] for t in temps) / sum(t["weight"] for t in temps) if temps else 0
        weighted_hum = sum(h["humidity"] * h["weight"] for h in humidities) / sum(h["weight"] for h in humidities) if humidities else 0
        
        # Check sleep hours
        is_sleep = self._is_sleep_hours()
        
        return AggregatedZoneConditions(
            zone_id=self.zone_config.zone_id,
            any_room_occupied=len(occupied_rooms) > 0,
            occupied_rooms=occupied_rooms,
            total_occupancy_weight=total_weight,
            hottest_room_temp=hottest["temp"],
            hottest_room_id=hottest["room_id"],
            coldest_room_temp=coldest["temp"],
            coldest_room_id=coldest["room_id"],
            weighted_avg_temp=weighted_temp,
            max_humidity=max_hum["humidity"],
            max_humidity_room_id=max_hum["room_id"],
            weighted_avg_humidity=weighted_hum,
            is_sleep_hours=is_sleep,
            predicted_occupied_soon=False,  # TODO: Add prediction logic
        )
    
    def _is_sleep_hours(self) -> bool:
        """Check if current time is within zone's sleep schedule."""
        if not self.zone_config.sleep_schedule:
            return False
        
        start_hour, end_hour = self.zone_config.sleep_schedule
        current_hour = dt_util.now().hour
        
        # Handle overnight schedules (e.g., 22-7)
        if start_hour > end_hour:
            return current_hour >= start_hour or current_hour < end_hour
        else:
            return start_hour <= current_hour < end_hour
```

### Fan Coordination

The HVAC Coordinator also manages room fans based on conditions:

```python
# domain_coordinators/hvac/fan_coordinator.py

@dataclass
class FanAction:
    """Action to take on a room fan."""
    fan_entity: str
    action: str  # "turn_on", "turn_off", "set_percentage"
    percentage: int | None = None
    reason: str = ""


class FanCoordinator:
    """Coordinate room fans based on conditions and HVAC state."""
    
    # Thresholds for fan activation
    HUMIDITY_HIGH = 60  # Turn on fan if humidity exceeds this
    TEMP_DELTA_THRESHOLD = 3  # Turn on fan if room is 3°F warmer than setpoint
    
    def __init__(self, hass: HomeAssistant, zone_config: HVACZoneConfig):
        self.hass = hass
        self.zone_config = zone_config
    
    async def evaluate_fans(
        self,
        zone_conditions: AggregatedZoneConditions,
        hvac_state: "HVACZoneState",
        energy_constraint: "HVACConstraints | None",
    ) -> list[FanAction]:
        """
        Evaluate and generate fan actions based on conditions.
        
        Fan activation triggers:
        1. High humidity in a room → Turn on that room's fan
        2. Room significantly warmer than HVAC setpoint → Fan for circulation
        3. HVAC in fan_only mode → Support with ceiling fans
        4. Energy coast mode → Fans can help maintain comfort with less HVAC
        """
        actions = []
        
        for fan_entity in self.zone_config.room_fans:
            # Determine which room this fan is in
            room_id = self._fan_to_room(fan_entity)
            if not room_id:
                continue
            
            # Get room-specific conditions
            room_temp = self._get_room_temp(room_id)
            room_humidity = self._get_room_humidity(room_id)
            room_occupied = room_id in zone_conditions.occupied_rooms
            
            # Skip if room not occupied (save energy)
            if not room_occupied:
                current_state = self.hass.states.get(fan_entity)
                if current_state and current_state.state == "on":
                    actions.append(FanAction(
                        fan_entity=fan_entity,
                        action="turn_off",
                        reason="Room unoccupied",
                    ))
                continue
            
            should_run = False
            reason = ""
            
            # Trigger 1: High humidity
            if room_humidity and room_humidity > self.HUMIDITY_HIGH:
                should_run = True
                reason = f"High humidity ({room_humidity}%)"
            
            # Trigger 2: Room warmer than setpoint (cooling season)
            if room_temp and hvac_state.target_temp_high:
                delta = room_temp - hvac_state.target_temp_high
                if delta > self.TEMP_DELTA_THRESHOLD:
                    should_run = True
                    reason = f"Room {delta:.1f}°F above setpoint"
            
            # Trigger 3: Energy coast mode - fans help maintain comfort
            if energy_constraint and energy_constraint.mode == "coast":
                if room_temp and hvac_state.target_temp_high:
                    # If room is warming during coast, fan helps
                    if room_temp > hvac_state.target_temp_high - 1:
                        should_run = True
                        reason = "Supporting coast mode with circulation"
            
            # Generate action
            current_state = self.hass.states.get(fan_entity)
            is_on = current_state and current_state.state == "on"
            
            if should_run and not is_on:
                actions.append(FanAction(
                    fan_entity=fan_entity,
                    action="turn_on",
                    reason=reason,
                ))
            elif not should_run and is_on:
                actions.append(FanAction(
                    fan_entity=fan_entity,
                    action="turn_off",
                    reason="Conditions normalized",
                ))
        
        return actions
    
    def _fan_to_room(self, fan_entity: str) -> str | None:
        """Map fan entity to room ID."""
        # This mapping should be configurable
        FAN_ROOM_MAP = {
            "fan.ceilingfan_fanimaton_rf304_25_masterbedroom": "master_bedroom",
            "fan.polyfan_508s_wifi_masterbedroom": "master_bedroom",
            "fan.fanswitch_treat_wifi_ziribedroom": "kids_bedroom_ziri",
            "fan.fanswitch_treat_wifi_jayabedroom": "kids_bedroom_jaya",
            "fan.game_room_ceiling_fan": "game_room",
            "fan.towerfan_dreopilotmaxs_wifi_livingroom": "living_room",
            "fan.polyfan_dreo704s_wifi_studya": "office_a",
            "fan.media_room_ceiling_fan": "media_room",
            "fan.guest_room_down_ceiling_fan": "guest_bedroom",
            "fan.151732606487193_fan": "kitchen",
        }
        return FAN_ROOM_MAP.get(fan_entity)
    
    def _get_room_temp(self, room_id: str) -> float | None:
        """Get temperature for a room."""
        state = self.hass.states.get(f"sensor.{room_id}_temperature")
        if state and state.state not in ("unavailable", "unknown"):
            return float(state.state)
        return None
    
    def _get_room_humidity(self, room_id: str) -> float | None:
        """Get humidity for a room."""
        state = self.hass.states.get(f"sensor.{room_id}_humidity")
        if state and state.state not in ("unavailable", "unknown"):
            return float(state.state)
        return None
```

### HVAC Coordinator Core Class

```python
# domain_coordinators/hvac/coordinator.py

class HVACCoordinator:
    """
    HVAC zone coordination with energy awareness.
    
    Responsibilities:
    1. Manage 3 Carrier Infinity HVAC zones
    2. Respond to Energy Coordinator constraints
    3. Aggregate room conditions (many rooms → few zones)
    4. Coordinate room fans
    5. Choose between coarse (preset) and fine (temp) control
    
    Control Philosophy:
    - Use presets for major mode changes (away/home/sleep)
    - Use temperature offsets for energy optimization
    - Fans supplement HVAC during energy-constrained periods
    - Sleep hours get special protection
    """
    
    def __init__(
        self,
        hass: HomeAssistant,
        event_bus: DomainEventBus,
        zone_configs: dict[str, HVACZoneConfig] | None = None,
    ) -> None:
        self.hass = hass
        self.event_bus = event_bus
        
        # Zone configurations (default or user-provided)
        self.zone_configs = zone_configs or DEFAULT_HVAC_ZONES
        
        # Room aggregators per zone
        self.aggregators = {
            zone_id: RoomConditionAggregator(hass, config)
            for zone_id, config in self.zone_configs.items()
        }
        
        # Fan coordinators per zone
        self.fan_coordinators = {
            zone_id: FanCoordinator(hass, config)
            for zone_id, config in self.zone_configs.items()
        }
        
        # Current energy constraints
        self._energy_constraint: HVACConstraints | None = None
        
        # Action generator
        self._action_generator = HVACActionGenerator()
        
        # Subscribe to energy events
        self.event_bus.subscribe("energy.hvac_constraint", self._on_energy_constraint)
        self.event_bus.subscribe("energy.tou_period_changed", self._on_tou_period_changed)
    
    async def async_init(self) -> None:
        """Initialize HVAC coordinator."""
        # Verify HVAC entities exist
        for zone_id, config in self.zone_configs.items():
            state = self.hass.states.get(config.climate_entity)
            if not state or state.state == "unavailable":
                _LOGGER.warning(f"HVAC zone {zone_id} entity unavailable: {config.climate_entity}")
        
        # Start periodic evaluation
        self._schedule_evaluation_loop()
    
    async def _on_energy_constraint(self, event: DomainEvent) -> None:
        """Handle constraint update from Energy Coordinator."""
        self._energy_constraint = HVACConstraints.from_dict(event.data)
        
        _LOGGER.info(
            f"HVAC: Received energy constraint - mode={self._energy_constraint.mode}, "
            f"offset={self._energy_constraint.setpoint_offset}°F, "
            f"reason={self._energy_constraint.reason}"
        )
        
        # Apply constraints to all zones
        await self._apply_constraints()
    
    async def _apply_constraints(self) -> None:
        """Apply current energy constraints to all HVAC zones."""
        for zone_id, config in self.zone_configs.items():
            # Get aggregated room conditions
            conditions = await self.aggregators[zone_id].aggregate()
            
            # Get current zone state
            zone_state = await self._get_zone_state(config)
            
            # Check occupancy requirement
            if self._energy_constraint and self._energy_constraint.occupied_only:
                if not conditions.any_room_occupied:
                    # Zone unoccupied - use away preset
                    await self._execute_action(HVACAction(
                        zone_id=zone_id,
                        strategy=HVACControlStrategy.PRESET_BASED,
                        preset_mode="away",
                        reason="Zone unoccupied during energy constraint",
                    ))
                    continue
            
            # Check sleep hours protection
            if conditions.is_sleep_hours:
                # Limit offsets during sleep
                constraint = self._limit_for_sleep(self._energy_constraint)
            else:
                constraint = self._energy_constraint
            
            # Generate and execute action
            if constraint:
                action = self._action_generator.generate_for_energy_constraint(
                    config, zone_state, constraint
                )
                await self._execute_action(action)
            
            # Evaluate fans for this zone
            fan_actions = await self.fan_coordinators[zone_id].evaluate_fans(
                conditions, zone_state, constraint
            )
            for fan_action in fan_actions:
                await self._execute_fan_action(fan_action)
    
    def _limit_for_sleep(self, constraint: "HVACConstraints | None") -> "HVACConstraints | None":
        """Limit energy constraint offsets during sleep hours."""
        if not constraint:
            return None
        
        MAX_SLEEP_OFFSET = 1.5  # Max ±1.5°F during sleep
        
        if abs(constraint.setpoint_offset) > MAX_SLEEP_OFFSET:
            limited_offset = MAX_SLEEP_OFFSET if constraint.setpoint_offset > 0 else -MAX_SLEEP_OFFSET
            return HVACConstraints(
                mode=constraint.mode,
                setpoint_offset=limited_offset,
                occupied_only=constraint.occupied_only,
                max_runtime_minutes=constraint.max_runtime_minutes,
                reason=f"{constraint.reason} (limited for sleep)",
            )
        
        return constraint
    
    async def _execute_action(self, action: HVACAction) -> None:
        """Execute an HVAC action on a zone."""
        config = self.zone_configs[action.zone_id]
        entity_id = config.climate_entity
        
        _LOGGER.debug(f"HVAC executing: {action}")
        
        # Execute based on strategy
        if action.preset_mode:
            await self.hass.services.async_call(
                "climate", "set_preset_mode",
                {"entity_id": entity_id, "preset_mode": action.preset_mode}
            )
        
        if action.hvac_mode:
            await self.hass.services.async_call(
                "climate", "set_hvac_mode",
                {"entity_id": entity_id, "hvac_mode": action.hvac_mode}
            )
        
        if action.target_temp_high is not None or action.target_temp_low is not None:
            service_data = {"entity_id": entity_id}
            if action.target_temp_high is not None:
                service_data["target_temp_high"] = action.target_temp_high
            if action.target_temp_low is not None:
                service_data["target_temp_low"] = action.target_temp_low
            
            await self.hass.services.async_call(
                "climate", "set_temperature", service_data
            )
        
        if action.fan_mode:
            await self.hass.services.async_call(
                "climate", "set_fan_mode",
                {"entity_id": entity_id, "fan_mode": action.fan_mode}
            )
    
    async def _execute_fan_action(self, action: FanAction) -> None:
        """Execute a fan action."""
        _LOGGER.debug(f"Fan action: {action.fan_entity} → {action.action} ({action.reason})")
        
        if action.action == "turn_on":
            await self.hass.services.async_call(
                "fan", "turn_on", {"entity_id": action.fan_entity}
            )
        elif action.action == "turn_off":
            await self.hass.services.async_call(
                "fan", "turn_off", {"entity_id": action.fan_entity}
            )
        elif action.action == "set_percentage" and action.percentage is not None:
            await self.hass.services.async_call(
                "fan", "set_percentage",
                {"entity_id": action.fan_entity, "percentage": action.percentage}
            )
    
    async def _get_zone_state(self, config: HVACZoneConfig) -> "HVACZoneState":
        """Get current state of an HVAC zone."""
        state = self.hass.states.get(config.climate_entity)
        
        if not state or state.state == "unavailable":
            return HVACZoneState(
                zone_id=config.zone_id,
                available=False,
            )
        
        attrs = state.attributes
        
        return HVACZoneState(
            zone_id=config.zone_id,
            available=True,
            hvac_mode=state.state,
            preset_mode=attrs.get("preset_mode"),
            fan_mode=attrs.get("fan_mode"),
            current_temp=attrs.get("current_temperature"),
            current_humidity=attrs.get("current_humidity"),
            target_temp_high=attrs.get("target_temp_high"),
            target_temp_low=attrs.get("target_temp_low"),
            hvac_action=attrs.get("hvac_action"),
            is_cooling_season=self._is_cooling_season(),
        )
    
    def _is_cooling_season(self) -> bool:
        """Determine if we're in cooling season."""
        month = dt_util.now().month
        return month in [4, 5, 6, 7, 8, 9, 10]  # April - October in Texas


@dataclass
class HVACZoneState:
    """Current state of an HVAC zone."""
    zone_id: str
    available: bool = True
    hvac_mode: str | None = None
    preset_mode: str | None = None
    fan_mode: str | None = None
    current_temp: float | None = None
    current_humidity: float | None = None
    target_temp_high: float | None = None
    target_temp_low: float | None = None
    hvac_action: str | None = None
    is_cooling_season: bool = True
```

### HVAC Coordinator Sensors

```yaml
# Sensors created by HVAC Coordinator

sensor.ura_hvac_mode:
  state: "coast"  # normal, pre_cool, pre_heat, coast, shed
  attributes:
    energy_constraint_active: true
    setpoint_offset: 3.0
    constraint_reason: "Summer peak - coast mode"

sensor.ura_hvac_zone_1_status:
  state: "heat_cool"
  attributes:
    friendly_name: "Master Suite"
    preset_mode: "home"
    effective_cool_setpoint: 77  # User 74 + 3 offset
    effective_heat_setpoint: 70
    current_temperature: 75
    any_room_occupied: true
    occupied_rooms: ["master_bedroom"]
    active_fans: ["fan.ceilingfan_fanimaton_rf304_25_masterbedroom"]

sensor.ura_hvac_zone_2_status:
  state: "heat_cool"
  attributes:
    friendly_name: "Upstairs"
    preset_mode: "sleep"  # Kids schedule
    effective_cool_setpoint: 77
    effective_heat_setpoint: 70
    current_temperature: 74
    any_room_occupied: true
    occupied_rooms: ["kids_bedroom_ziri", "kids_bedroom_jaya"]
    is_sleep_hours: true

sensor.ura_hvac_zone_3_status:
  state: "heat_cool"
  attributes:
    friendly_name: "Main Living"
    preset_mode: "away"  # Unoccupied during constraint
    effective_cool_setpoint: 80
    effective_heat_setpoint: 65
    current_temperature: 76
    any_room_occupied: false
    occupied_rooms: []

binary_sensor.ura_hvac_energy_constrained:
  state: "on"
  attributes:
    constraint_mode: "coast"
    constraint_source: "energy_coordinator"
    zones_affected: ["zone_1_master", "zone_2_upstairs", "zone_3_main"]
```

---

## 7. CONFIGURATION VIA OPTIONS FLOW

### Options Flow Steps

```python
# config_flow.py additions for Energy Coordinator

class EnergyCoordinatorOptionsFlow(OptionsFlow):
    """Options flow for Energy Coordinator configuration."""
    
    async def async_step_init(self, user_input=None):
        """Initial step - choose what to configure."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "tou_schedule",
                "entity_mapping",
                "load_priorities",
                "optimization_settings",
            ]
        )
    
    async def async_step_tou_schedule(self, user_input=None):
        """Configure TOU schedule."""
        if user_input is not None:
            # Store TOU configuration
            self.options["tou_schedule"] = user_input
            return await self.async_step_init()
        
        # Show form with TOU configuration
        return self.async_show_form(
            step_id="tou_schedule",
            data_schema=vol.Schema({
                vol.Required("utility", default="PEC"): vol.In(["PEC", "Austin Energy", "Custom"]),
                vol.Optional("custom_schedule"): str,  # JSON for custom
            }),
            description_placeholders={
                "current": "PEC Time-of-Use (2026)"
            }
        )
    
    async def async_step_entity_mapping(self, user_input=None):
        """Map hardware entities."""
        if user_input is not None:
            self.options["entity_mapping"] = user_input
            return await self.async_step_init()
        
        # Discover available entities
        enphase_entities = await self._discover_enphase()
        span_entities = await self._discover_span()
        
        return self.async_show_form(
            step_id="entity_mapping",
            data_schema=vol.Schema({
                vol.Required("battery_soc"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required("solar_production"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required("grid_power"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional("pool_pump"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Optional("ev_charger"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
            })
        )
    
    async def async_step_load_priorities(self, user_input=None):
        """Configure load shedding priorities."""
        if user_input is not None:
            # Parse priority list
            priorities = []
            for i, entity_id in enumerate(user_input.get("priority_order", [])):
                priorities.append({
                    "priority": i + 1,
                    "entity_id": entity_id,
                    "comfort_impact": user_input.get(f"comfort_{entity_id}", 1),
                })
            self.options["load_priorities"] = priorities
            return await self.async_step_init()
        
        return self.async_show_form(
            step_id="load_priorities",
            data_schema=vol.Schema({
                vol.Required("priority_order"): selector.EntitySelector(
                    selector.EntitySelectorConfig(multiple=True)
                ),
            }),
            description_placeholders={
                "hint": "Order: Pool pump, EV charging, Water heater, HVAC setback"
            }
        )
```

---

## 8. SENSORS & ENTITIES

### Energy Coordinator Sensors

```yaml
# Sensors created by Energy Coordinator

# TOU Status
sensor.ura_tou_period:
  state: "peak"
  attributes:
    season: "summer"
    rate_per_kwh: 0.16184
    rate_multiplier: 3.72
    next_period: "mid_peak"
    minutes_until_change: 47
    is_expensive: true
    is_critical: true
    hvac_strategy: "coast"

sensor.ura_current_rate:
  state: 0.16184
  unit: "$/kWh"
  attributes:
    period: "peak"
    rate_class: "expensive"

# Battery Strategy
sensor.ura_battery_strategy:
  state: "discharge"
  attributes:
    target_soc: 20
    reason: "Peak period - offsetting grid import"
    discharge_rate_kw: 5.0

# Load Shedding
binary_sensor.ura_load_shedding_active:
  state: "on"
  attributes:
    trigger: "peak_grid_import"
    shed_loads:
      - pool_pump
      - ev_charger
    total_reduction_kw: 3.5

# HVAC Constraints
sensor.ura_hvac_mode:
  state: "coast"
  attributes:
    setpoint_offset: 3.0
    occupied_only: true
    max_power_kw: 5.0
    reason: "Summer peak - coast mode"

# Energy Summary
sensor.ura_energy_optimization_status:
  state: "active"
  attributes:
    current_period: "peak"
    battery_soc: 65
    solar_production_kw: 2.1
    grid_import_kw: 1.5
    estimated_savings_today: 4.50
    strategy: "Battery discharging, pool deferred, HVAC coasting"
```

---

## 9. IMPLEMENTATION PHASES

### Phase 1: Core Infrastructure (2-3 hours)
- [ ] Create `domain_coordinators/energy/` directory
- [ ] Implement EnergyCoordinator base class
- [ ] TOU period calculation and monitoring
- [ ] Event bus integration (publish TOU changes)
- [ ] Basic sensors (TOU period, current rate)

### Phase 2: Solar Forecast Integration (2 hours) **NEW**
- [ ] Implement SolarForecastAnalyzer class
- [ ] Day classification logic (excellent/good/moderate/poor/very_poor)
- [ ] Solcast entity subscription
- [ ] Solar forecast quality sensor
- [ ] Window-based forecast extraction (detailedHourly)
- [ ] Integration with strategy selection

### Phase 3: HVAC Governance (2 hours)
- [ ] Implement HVACConstraints class
- [ ] HVAC request approval flow
- [ ] Pre-cooling/coasting strategy logic (solar-aware)
- [ ] Occupancy integration for occupied_only mode
- [ ] HVAC Coordinator subscription handling

### Phase 4: Battery Optimization (1-2 hours)
- [ ] Battery strategy calculation (solar-aware)
- [ ] Enphase entity mapping (CONFIRMED entities)
- [ ] Storage mode control: `select.enpower_482348004678_storage_mode`
- [ ] Reserve level control: `number.enpower_482348004678_reserve_battery_level`
- [ ] Grid charge control: `switch.enpower_482348004678_charge_from_grid`
- [ ] Strategy sensor with forecast integration

### Phase 5: Load Management (1-2 hours)
- [ ] Load shedding evaluation (solar-aware thresholds)
- [ ] Priority-based shedding actions
- [ ] Pool circuit control: `switch.pool`, `switch.infinity_edge`, `switch.booster_pump`
- [ ] Pool power monitoring: `sensor.vsf_power`, `sensor.vsf_2_power`
- [ ] EV charging deferral: `switch.garage_a`, `switch.garage_b`
- [ ] EV power monitoring: `sensor.garage_a_power_minute_average`, `sensor.garage_b_power_minute_average`
- [ ] Load shedding sensors

### Phase 6: Configuration (1 hour)
- [ ] Options flow for TOU schedule (PEC presets)
- [ ] Entity mapping configuration (with discovery)
- [ ] Solcast entity auto-discovery
- [ ] Load priority configuration
- [ ] Optimization settings (pre-cool/coast aggressiveness)

**Total: 8-10 hours** (Updated from 6-8 to include solar integration)

### OPTIONAL MILESTONE 7: Vehicle Presence Tracker (4-6 hours)

**Status:** Optional - Not required for core energy optimization  
**Priority:** Low - Implement only if departure prediction provides clear ROI  
**Dependencies:** Core Energy Coordinator must be stable first

**Rationale:** While vehicle departure prediction could enhance EV charge scheduling,
the core Energy Coordinator can function effectively with simpler heuristics:
- Charge during off-peak periods by default
- Pause during TOU peak regardless of departure time
- User can manually override for urgent charging needs

**If implemented, would include:**
- [ ] SQLite database for garage_vehicle_events
- [ ] State machine: door_state + vehicle_detected → arrival/departure events
- [ ] Pattern analysis: departure times by day_of_week, workday vs weekend
- [ ] Prediction engine: typical_departure_time, confidence_level
- [ ] Integration with EV charging: pre-charge completion targeting

**Available Data Sources (already present in HA):**
```yaml
vehicle_detection:
  garage_a:
    unifi_event: event.garage_a_vehicle                    # Confidence %, zone, trackerId
    frigate_binary: binary_sensor.garage_a_vehicle_detected  # Real-time presence
    door_state: cover.konnected_f0f5bd523b00_garage_door   # open/closed
    door_counter: sensor.garageopener_gdoblaq_wifi_garagea_garage_openings  # 2061 openings!
  garage_b:
    unifi_event: event.garage_b_vehicle
    frigate_binary: binary_sensor.garage_b_vehicle_detected
    door_state: cover.ratgdov25i_dbfe2a_door
  driveway:
    approach_event: event.garage_doorbell_lite_vehicle     # Approaching vehicles
```

**Output Sensors (if implemented):**
- `sensor.garage_a_vehicle_present` - Binary: car in garage?
- `sensor.garage_a_predicted_departure` - Datetime of expected departure
- `sensor.garage_a_predicted_arrival` - Datetime of expected return
- `sensor.garage_a_departure_confidence` - 0-100% confidence
- `sensor.garage_a_typical_away_duration` - Average hours away

**Decision:** Defer until core Energy Coordinator proves value. Simpler charging
heuristics (off-peak default, peak pause) provide 80% of the benefit.

---

## 10. TESTING STRATEGY

### Unit Tests

```python
# tests/test_energy_coordinator.py

async def test_tou_period_summer_peak():
    """Test TOU period detection for summer peak."""
    with freeze_time("2026-07-15 17:30:00"):
        coordinator = EnergyCoordinator(hass, event_bus)
        period = coordinator.get_current_tou_period()
        assert period == "peak"

async def test_tou_period_winter_midpeak():
    """Test TOU period detection for winter mid-peak."""
    with freeze_time("2026-01-15 07:30:00"):
        coordinator = EnergyCoordinator(hass, event_bus)
        period = coordinator.get_current_tou_period()
        assert period == "mid_peak"

async def test_hvac_constraints_peak():
    """Test HVAC constraints calculation during peak."""
    coordinator = EnergyCoordinator(hass, event_bus)
    coordinator._current_season = "summer"
    
    constraints = coordinator._calculate_hvac_constraints("peak")
    
    assert constraints.mode == "coast"
    assert constraints.setpoint_offset == 3.0
    assert constraints.occupied_only == True

async def test_battery_strategy_peak_discharge():
    """Test battery discharges during peak."""
    coordinator = EnergyCoordinator(hass, event_bus)
    coordinator._battery_soc = 75.0
    coordinator._current_period = "peak"
    
    strategy = await coordinator.optimize_battery_strategy()
    
    assert strategy.mode == "discharge"
    assert strategy.target_soc == 20

async def test_load_shedding_priority():
    """Test load shedding follows priority order."""
    coordinator = EnergyCoordinator(hass, event_bus)
    coordinator.load_priorities = [
        LoadPriority("pool_pump", 1, 1.5),
        LoadPriority("ev_charger", 2, 1.8),
        LoadPriority("hvac_setback", 3, 0.5),
    ]
    
    actions = await coordinator._generate_shedding_actions(
        target_reduction=2.0,
        trigger="test"
    )
    
    # Pool shed first, then EV
    assert len(actions) == 2
    assert actions[0].entity_id == "pool_pump"
    assert actions[1].entity_id == "ev_charger"


#═══════════════════════════════════════════════════════════════════════════════
# SOLAR FORECAST TESTS
#═══════════════════════════════════════════════════════════════════════════════

async def test_solar_day_classification_excellent():
    """Test day classification for high production days."""
    analyzer = SolarForecastAnalyzer(hass)
    
    # Mock excellent solar day (100+ kWh)
    forecast = SolarForecastWindow(
        start=datetime.now(),
        end=datetime.now(),
        expected_kwh=120.0,
        pessimistic_kwh=90.0,
        optimistic_kwh=140.0,
        peak_power_w=15000,
        peak_time=datetime.now().replace(hour=13)
    )
    
    classification = analyzer.classify_day(forecast)
    
    assert classification.quality == "excellent"
    assert classification.recommended_battery_strategy == "self_consumption"
    assert classification.recommended_hvac_aggressiveness == "relaxed"

async def test_solar_day_classification_poor():
    """Test day classification for cloudy days."""
    analyzer = SolarForecastAnalyzer(hass)
    
    # Mock poor solar day (10 kWh - like today)
    forecast = SolarForecastWindow(
        start=datetime.now(),
        end=datetime.now(),
        expected_kwh=10.8,
        pessimistic_kwh=5.9,
        optimistic_kwh=17.5,
        peak_power_w=1700,
        peak_time=datetime.now().replace(hour=12)
    )
    
    classification = analyzer.classify_day(forecast)
    
    assert classification.quality == "poor"
    assert classification.recommended_battery_strategy == "savings"
    assert classification.recommended_hvac_aggressiveness == "aggressive"

async def test_battery_charge_decision_excellent_solar():
    """Test battery doesn't grid-charge on excellent solar days."""
    analyzer = SolarForecastAnalyzer(hass)
    
    # Mock excellent forecast
    hass.states.async_set("sensor.solcast_pv_forecast_forecast_today", "120.0", {
        "estimate": 120.0,
        "estimate10": 90.0,
        "estimate90": 140.0,
    })
    hass.states.async_set("sensor.solcast_pv_forecast_forecast_remaining_today", "80.0")
    
    should_charge, reason = analyzer.should_charge_battery_now(current_soc=60)
    
    assert should_charge == False
    assert "Solar will provide" in reason

async def test_battery_charge_decision_poor_solar():
    """Test battery grid-charges on poor solar days."""
    analyzer = SolarForecastAnalyzer(hass)
    
    # Mock poor forecast
    hass.states.async_set("sensor.solcast_pv_forecast_forecast_today", "10.8", {
        "estimate": 10.8,
        "estimate10": 5.9,
        "estimate90": 17.5,
    })
    hass.states.async_set("sensor.solcast_pv_forecast_forecast_remaining_today", "5.0")
    
    should_charge, reason = analyzer.should_charge_battery_now(current_soc=60)
    
    assert should_charge == True
    assert "Poor forecast" in reason

async def test_pool_window_optimization():
    """Test pool pump window follows solar production."""
    analyzer = SolarForecastAnalyzer(hass)
    
    # Mock forecast with peak at noon
    hass.states.async_set("sensor.solcast_pv_forecast_forecast_today", "80.0", {
        "detailedHourly": [
            {"period_start": "2026-01-24T07:00:00-06:00", "pv_estimate": 0.5},
            {"period_start": "2026-01-24T08:00:00-06:00", "pv_estimate": 2.0},
            {"period_start": "2026-01-24T09:00:00-06:00", "pv_estimate": 5.0},
            {"period_start": "2026-01-24T10:00:00-06:00", "pv_estimate": 8.0},
            {"period_start": "2026-01-24T11:00:00-06:00", "pv_estimate": 10.0},
            {"period_start": "2026-01-24T12:00:00-06:00", "pv_estimate": 12.0},  # Peak
            {"period_start": "2026-01-24T13:00:00-06:00", "pv_estimate": 11.0},
            {"period_start": "2026-01-24T14:00:00-06:00", "pv_estimate": 9.0},
            {"period_start": "2026-01-24T15:00:00-06:00", "pv_estimate": 6.0},
        ]
    })
    
    start, end, reason = analyzer.get_optimal_pool_window()
    
    # Should prioritize hours with highest production
    assert start >= 9  # High production hours
    assert end <= 16   # Before TOU peak
    assert "solar" in reason.lower()

async def test_strategy_selection_with_solar_forecast():
    """Test strategy changes based on solar forecast quality."""
    coordinator = EnergyCoordinator(hass, event_bus)
    
    # Test excellent solar day
    coordinator.solar_analyzer.classify_day = Mock(return_value=SolarDayClassification(
        quality="excellent",
        expected_kwh=120.0,
        confidence_range=50.0,
        excess_after_base_load=100.0,
        recommended_battery_strategy="self_consumption",
        recommended_hvac_aggressiveness="relaxed",
        recommended_ev_strategy="solar_priority",
    ))
    
    strategy = coordinator.evaluate_strategies()
    assert strategy.battery_mode == "self_consumption"
    assert strategy.hvac_constraints.mode == "normal"
    
    # Test poor solar day
    coordinator.solar_analyzer.classify_day = Mock(return_value=SolarDayClassification(
        quality="poor",
        expected_kwh=10.0,
        confidence_range=12.0,
        excess_after_base_load=-10.0,
        recommended_battery_strategy="savings",
        recommended_hvac_aggressiveness="aggressive",
        recommended_ev_strategy="off_peak_only",
    ))
    
    strategy = coordinator.evaluate_strategies()
    assert strategy.battery_mode == "savings"
    # HVAC mode depends on current TOU period
```

### Integration Tests

```python
async def test_hvac_coordinator_receives_constraints():
    """Test HVAC Coordinator receives and applies energy constraints."""
    energy_coord = EnergyCoordinator(hass, event_bus)
    hvac_coord = HVACCoordinator(hass, event_bus)
    
    # Simulate TOU period change to peak
    await energy_coord._on_tou_period_change("peak")
    
    # Wait for event propagation
    await asyncio.sleep(0.1)
    
    # Verify HVAC received constraints
    assert hvac_coord._energy_constraints is not None
    assert hvac_coord._energy_constraints.mode == "coast"

async def test_census_affects_load_prediction():
    """Test that census count affects energy predictions."""
    coordinator = EnergyCoordinator(hass, event_bus)
    
    # Simulate census update with 4 people
    await coordinator._on_census_update(DomainEvent(
        type="census_update",
        data={"total_count": 4, "identified": ["John", "Jane"]}
    ))
    
    # Verify load prediction increased
    assert coordinator._census_data["total_count"] == 4
```

---

## 11. SUCCESS CRITERIA

### Quantitative Metrics
- [ ] Reduce peak grid import by 50% (from 318 kWh to ~160 kWh annually)
- [ ] Shift 890 kWh export from off-peak to peak (+$105/year)
- [ ] HVAC peak usage reduced by 30% via pre-cooling
- [ ] Zero pool pump operation during peak hours
- [ ] **Solar-aware**: 90%+ accuracy in day classification vs actual production
- [ ] **Forecast utilization**: Strategy adapts within 30 min of forecast update
- [ ] **Grid charge optimization**: Reduce unnecessary off-peak grid charging by 40%+ on good solar days

### Qualitative Metrics
- [ ] All decisions pass livability test (comfort impact < 5/10)
- [ ] Load shedding never activated unnecessarily
- [ ] Recovery from constraints within 30 minutes
- [ ] User override always available and respected
- [ ] **Graceful degradation**: System operates correctly when Solcast unavailable (falls back to TOU-only)

### System Health
- [ ] Event bus latency < 100ms
- [ ] No missed TOU transitions
- [ ] Battery strategy updates within 60 seconds of state change
- [ ] Graceful degradation if hardware unavailable

---

## 12. CONCLUSION: WHY URA IS THE RIGHT HOME

The Energy Coordinator belongs in URA because:

1. **Data Access** - Needs room occupancy, person count, comfort scores
2. **Governor Role** - Event bus architecture designed for cross-domain coordination
3. **Shared Infrastructure** - Same SQLite, same coordinator pattern, same config flow
4. **Integration Synergy** - Census from v3.5.0, comfort from Comfort Coordinator
5. **Priority Resolution** - Built-in priority: Security > Energy > Comfort > HVAC

**URA provides the nervous system; Energy Coordinator adds the metabolic intelligence.**

---

**Document Status:** Ready for implementation review  
**Next Steps:** Review with user, finalize configuration options, begin Phase 1  
**Estimated Completion:** 6-8 hours over 2-3 development sessions
