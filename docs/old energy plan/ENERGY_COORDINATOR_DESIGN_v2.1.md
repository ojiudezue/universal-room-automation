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

### Energy Coordinator as Governor

The Energy Coordinator operates as a **governor** - it doesn't directly control devices but rather:
1. **Publishes constraints** that other coordinators must respect
2. **Monitors compliance** and can escalate if ignored
3. **Makes recommendations** that room automation can follow
4. **Enforces limits** during critical situations (battery < 15%, grid overload)

```
                    ┌─────────────────────┐
                    │  Energy Coordinator │ (GOVERNOR)
                    │  "You're in peak,   │
                    │   max import 5kW"   │
                    └─────────┬───────────┘
                              │ Events + Constraints
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
    ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
    │    HVAC     │  │    Pool     │  │     EV      │
    │ Coordinator │  │   Manager   │  │   Manager   │
    │ (subscribes)│  │ (subscribes)│  │ (subscribes)│
    └─────────────┘  └─────────────┘  └─────────────┘
           │                │                │
           ▼                ▼                ▼
    [Climate zones]   [Pentair pump]   [ChargePoint]
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

## 5. ENERGY COORDINATOR ARCHITECTURE

### Core Class Structure

```python
# domain_coordinators/energy/coordinator.py

class EnergyCoordinator:
    """
    Whole-house energy optimization governor.
    
    Responsibilities:
    - Monitor TOU periods and publish transitions
    - Optimize battery charge/discharge strategy
    - Coordinate load shedding priorities
    - Govern HVAC through constraints
    - Schedule deferrable loads (pool, EV, water heater)
    - Integrate solar forecasting
    
    Philosophy:
    - Governor, not controller (publish constraints)
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

## 6. HVAC COORDINATOR INTEGRATION

### HVAC Coordinator Subscribes to Energy Events

```python
# domain_coordinators/hvac/coordinator.py

class HVACCoordinator:
    """HVAC zone coordination - subscribes to Energy Coordinator."""
    
    def __init__(self, hass: HomeAssistant, event_bus: DomainEventBus) -> None:
        self.hass = hass
        self.event_bus = event_bus
        
        # Energy constraints (set by Energy Coordinator)
        self._energy_constraints: HVACConstraints | None = None
        
        # Subscribe to energy events
        self.event_bus.subscribe("tou_period_changed", self._on_tou_period_changed)
        self.event_bus.subscribe("load_shedding_active", self._on_load_shedding)
        self.event_bus.subscribe("hvac_request_modified", self._on_request_modified)
    
    async def _on_tou_period_changed(self, event: DomainEvent) -> None:
        """Handle TOU period change from Energy Coordinator."""
        constraints = HVACConstraints.from_dict(event.data["hvac_constraints"])
        self._energy_constraints = constraints
        
        _LOGGER.info(
            f"HVAC: Received energy constraints - mode={constraints.mode}, "
            f"offset={constraints.setpoint_offset}°F"
        )
        
        # Apply constraints to all zones
        await self._apply_energy_constraints(constraints)
    
    async def _apply_energy_constraints(self, constraints: HVACConstraints) -> None:
        """Apply energy constraints to HVAC zones."""
        if constraints.mode == "coast":
            # Raise setpoints to coast through peak
            for zone in self.zones:
                if constraints.occupied_only and not zone.is_occupied:
                    # Skip unoccupied rooms entirely
                    await self._set_zone_mode(zone, "off")
                else:
                    # Apply setpoint offset
                    new_setpoint = zone.target_temp + constraints.setpoint_offset
                    await self._set_zone_setpoint(zone, new_setpoint)
        
        elif constraints.mode == "pre_cool":
            # Aggressive cooling before peak
            for zone in self.zones:
                # Pre-cool occupied and predicted-occupied rooms
                if zone.is_occupied or zone.predicted_occupied:
                    new_setpoint = zone.target_temp + constraints.setpoint_offset
                    await self._set_zone_setpoint(zone, new_setpoint)
    
    async def request_hvac_action(self, room: str, action: str, **kwargs) -> None:
        """
        Request HVAC action - goes through Energy Coordinator approval.
        
        This is the key governance point: HVAC doesn't act directly,
        it requests permission from Energy Coordinator.
        """
        request = {
            "room": room,
            "action": action,
            "timestamp": dt_util.now().isoformat(),
            **kwargs
        }
        
        # Publish request for Energy Coordinator to review
        await self.event_bus.publish(DomainEvent(
            type="hvac_request",
            source="hvac_coordinator",
            data=request
        ))
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
