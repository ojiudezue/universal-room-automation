# Energy Coordinator Design - URA v3.6.0
## Comprehensive Specification for Whole-House Energy Intelligence

**Version:** 2.3 (Updated with Pentair VSF speed control)  
**Status:** Design Phase - Ready for Implementation  
**Created:** January 23, 2026  
**Updated:** January 26, 2026  
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

### Key Additions in v2.3

| Feature | Description | Impact |
|---------|-------------|--------|
| **🎉 VSF Speed Control** | Direct GPM control via `number.madrone_pool_vsf_speed_*` | **CONTINUOUS load modulation!** |
| **Updated Entity Names** | All pool entities now use `madrone_pool` prefix | Consistent naming |
| **Pump Speed Range** | 20-140 GPM in 5 GPM increments | Fine-grained energy control |
| **Power Savings Model** | Affinity law: 75→30 GPM = 94% power reduction | Quantified optimization |
| **Tiered Strategy** | Speed reduction → Circuit shed → Full shutdown | Livability-first approach |

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
│  │  • Pool: VSF speed control + circuit switches                       │    │
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
| Reduce pool to 30 GPM | High | 0/10 (invisible) | ✅ Excellent |
| Pause EV charging | Low | 0/10 (invisible) | ✅ Excellent |
| Turn off pool entirely | Medium | 0/10 (invisible) | ✅ Good |
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
# POOL SYSTEM (Pentair Integration - v2.3 Updated with VSF Speed Control!)
#═══════════════════════════════════════════════════════════════════════════════
pool:
  system: "Pentair IntelliCenter with Variable Speed Pumps"
  model: "IntelliCenter IC: 1.064"
  integration: "pentair"
  device_name: "Madrone Pool"
  variable_speed_control: true  # ✅ CAN SET VSF PUMP SPEED DIRECTLY!
  
  # Pump power follows the affinity law: Power ∝ (GPM)³
  # Current operation: Main pump 75 GPM @ 1,375W, Infinity edge 23 GPM @ 125W
  # Pump range: 20-140 GPM (step 5), 450-3,450 RPM
  
  entities:
    #─────────────────────────────────────────────────────────────────────────────
    # CONTROLLABLE CIRCUITS (On/Off switches) - Updated entity names!
    #─────────────────────────────────────────────────────────────────────────────
    pool_circuit: switch.madrone_pool_pool                                    # Main pool circulation
    spa_circuit: switch.madrone_pool_spa                                      # Spa mode
    booster_pump: switch.madrone_pool_booster_pump                            # Booster pump
    infinity_edge: switch.madrone_pool_infinity_edge                          # Infinity edge feature
    jets: switch.madrone_pool_jets                                            # Spa jets
    air_blower: switch.madrone_pool_air_blower                                # Air blower
    vacation_mode: switch.madrone_pool_vacation_mode                          # Reduced operation mode
    
    #─────────────────────────────────────────────────────────────────────────────
    # 🎉 VSF PUMP SPEED CONTROLS (NEW in v2.3! - Direct GPM control!)
    #─────────────────────────────────────────────────────────────────────────────
    vsf_speed_pool: number.madrone_pool_vsf_speed_pool                        # Pool mode: 20-140 GPM, step 5
    vsf_speed_spa: number.madrone_pool_vsf_speed_spa                          # Spa mode: 20-140 GPM
    vsf_speed_jets: number.madrone_pool_vsf_speed_jets                        # Jets mode: 20-140 GPM
    vsf_2_speed_infinity_edge: number.madrone_pool_vsf_2_speed_infinity_edge  # Infinity edge: GPM control
    
    # VSF Mode Selection (GPM vs RPM)
    vsf_mode_pool: select.madrone_pool_vsf_mode_pool                          # GPM or RPM mode
    vsf_mode_spa: select.madrone_pool_vsf_mode_spa
    vsf_mode_jets: select.madrone_pool_vsf_mode_jets
    vsf_2_mode_infinity_edge: select.madrone_pool_vsf_2_mode_infinity_edge
    
    #─────────────────────────────────────────────────────────────────────────────
    # VSF PUMP MONITORING (Read-only - TWO variable speed pumps!)
    #─────────────────────────────────────────────────────────────────────────────
    # Primary VSF pump (main pool)
    vsf_power: sensor.madrone_pool_vsf_power                                  # W real-time (currently 1375W)
    vsf_rpm: sensor.madrone_pool_vsf_rpm                                      # Current RPM (currently 2839)
    vsf_gpm: sensor.madrone_pool_vsf_gpm                                      # Flow rate GPM (currently 75)
    vsf_running: binary_sensor.madrone_pool_vsf                               # Running status
    vsf_min_rpm: sensor.madrone_pool_vsf_min_rpm                              # Min RPM setting
    vsf_max_rpm: sensor.madrone_pool_vsf_max_rpm                              # Max RPM setting
    vsf_min_gpm: sensor.madrone_pool_vsf_min_gpm                              # Min GPM setting (20)
    vsf_max_gpm: sensor.madrone_pool_vsf_max_gpm                              # Max GPM setting (140)
    
    # Secondary VSF pump (infinity edge)
    vsf_2_power: sensor.madrone_pool_vsf_2_power                              # W real-time (currently 125W)
    vsf_2_rpm: sensor.madrone_pool_vsf_2_rpm                                  # Current RPM (currently 1116)
    vsf_2_gpm: sensor.madrone_pool_vsf_2_gpm                                  # Flow rate GPM (currently 23)
    vsf_2_running: binary_sensor.madrone_pool_vsf_2                           # Running status
    vsf_2_min_rpm: sensor.madrone_pool_vsf_2_min_rpm
    vsf_2_max_rpm: sensor.madrone_pool_vsf_2_max_rpm
    vsf_2_min_gpm: sensor.madrone_pool_vsf_2_min_gpm
    vsf_2_max_gpm: sensor.madrone_pool_vsf_2_max_gpm
    
    #─────────────────────────────────────────────────────────────────────────────
    # TEMPERATURE CONTROL
    #─────────────────────────────────────────────────────────────────────────────
    pool_heater: water_heater.madrone_pool_pool                               # Pool heater (temp setpoint)
    spa_heater: water_heater.madrone_pool_spa                                 # Spa heater (temp setpoint)
    water_sensor: sensor.madrone_pool_water_sensor                            # Water temperature
    air_sensor: sensor.madrone_pool_air_sensor                                # Air temperature
    solar_sensor: sensor.madrone_pool_solar_sensor                            # Solar heating sensor
    
    #─────────────────────────────────────────────────────────────────────────────
    # STATUS MONITORING
    #─────────────────────────────────────────────────────────────────────────────
    gas_heater_status: binary_sensor.madrone_pool_gas_heater                  # Gas heater running
    freeze_protection: binary_sensor.madrone_pool_freeze                      # Freeze protection active
    firmware_version: sensor.madrone_pool_firmware_version                    # IC: 1.064
    
    #─────────────────────────────────────────────────────────────────────────────
    # SCHEDULE STATUS (Read-only)
    #─────────────────────────────────────────────────────────────────────────────
    pool_schedule: binary_sensor.madrone_pool_pool_schedule
    booster_schedule: binary_sensor.madrone_pool_booster_pump_schedule
    infinity_schedule: binary_sensor.madrone_pool_infinity_edge_schedule
    pool_light_schedule: binary_sensor.madrone_pool_pool_light_schedule
    spa_lights_schedule: binary_sensor.madrone_pool_spa_lights_schedule
    
    #─────────────────────────────────────────────────────────────────────────────
    # LIGHTING
    #─────────────────────────────────────────────────────────────────────────────
    pool_light: light.madrone_pool_pool_light
    spa_lights: light.madrone_pool_spa_lights
  
  #─────────────────────────────────────────────────────────────────────────────
  # ENERGY CONTROL STRATEGY (v2.3 - Tiered Approach)
  #─────────────────────────────────────────────────────────────────────────────
  # 
  # TIER 1: VSF Speed Reduction (Preferred - maintains filtration, saves energy)
  #   - Normal operation: 75 GPM @ 1,375W
  #   - TOU peak reduction: 30 GPM @ ~88W (94% savings!)
  #   - Uses affinity law: Power ∝ (GPM)³
  # 
  # TIER 2: Circuit Shedding (Secondary - full load removal)
  #   - Turn off infinity edge during peak (saves 125W)
  #   - Defer jets, booster pump to off-peak
  #
  # TIER 3: Full Shutdown (Emergency only)
  #   - Turn off main pool circuit entirely
  #   - Limit to <4 hours for pool chemistry
  #   - Last resort during extreme grid events
  #
  # EXAMPLE: Optimize pool for TOU peak
  #   async def optimize_pool_for_tou(self, tou_period: str):
  #       if tou_period == "peak":
  #           # Tier 1: Reduce main pump to minimum safe speed
  #           await self.hass.services.async_call(
  #               "number", "set_value",
  #               {"entity_id": "number.madrone_pool_vsf_speed_pool", "value": 30}
  #           )
  #           # Turn off infinity edge (Tier 2)
  #           await self.hass.services.async_call(
  #               "switch", "turn_off",
  #               {"entity_id": "switch.madrone_pool_infinity_edge"}
  #           )
  #       else:
  #           # Off-peak: restore normal operation
  #           await self.hass.services.async_call(
  #               "number", "set_value",
  #               {"entity_id": "number.madrone_pool_vsf_speed_pool", "value": 75}
  #           )
  #
  # POWER ESTIMATES (using affinity law P ∝ GPM³):
  #   | GPM | Est. Power | Savings vs 75 GPM |
  #   |-----|------------|-------------------|
  #   | 75  | 1,375W     | baseline          |
  #   | 60  | ~704W      | 49%               |
  #   | 45  | ~296W      | 78%               |
  #   | 30  | ~88W       | 94%               |
  #   | 20  | ~26W       | 98%               |

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
      charger_switch: switch.garage_a
      power_monitor: sensor.garage_a_power_minute_average
      energy_today: sensor.garage_a_energy_today
      energy_month: sensor.garage_a_energy_this_month
      breaker: switch.span_panel_garage_a_evse_breaker
      
  - system: "Emporia EVSE Garage B"
    device_id: "d4b7f4886922f569cb3df6782fedc8f5"
    model: "VVDN01"
    capacity: "48A @ 240V = 11.5 kW"
    control_type: "Simple switch (on/off only)"
    entities:
      charger_switch: switch.garage_b
      power_monitor: sensor.garage_b_power_minute_average
      energy_today: sensor.garage_b_energy_today
      energy_month: sensor.garage_b_energy_this_month
      breaker: switch.span_panel_garage_b_evse_breaker

#═══════════════════════════════════════════════════════════════════════════════
# SOLAR FORECASTING (Solcast)
#═══════════════════════════════════════════════════════════════════════════════
forecasting:
  system: "Solcast PV Forecast"
  integration: "Solcast Solar"
  api_calls_used: sensor.solcast_pv_forecast_api_used
  api_calls_limit: sensor.solcast_pv_forecast_api_limit
  
  entities:
    power_now: sensor.solcast_pv_forecast_power_now
    power_30min: sensor.solcast_pv_forecast_power_in_30_minutes
    power_1hour: sensor.solcast_pv_forecast_power_in_1_hour
    forecast_this_hour: sensor.solcast_pv_forecast_forecast_this_hour
    forecast_next_hour: sensor.solcast_pv_forecast_forecast_next_hour
    forecast_remaining_today: sensor.solcast_pv_forecast_forecast_remaining_today
    forecast_today: sensor.solcast_pv_forecast_forecast_today
    forecast_tomorrow: sensor.solcast_pv_forecast_forecast_tomorrow
    peak_power_today: sensor.solcast_pv_forecast_peak_forecast_today
    peak_time_today: sensor.solcast_pv_forecast_peak_time_today
    use_forecast_field: select.solcast_pv_forecast_use_forecast_field
```
