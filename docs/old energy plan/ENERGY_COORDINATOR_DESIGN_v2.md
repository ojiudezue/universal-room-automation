# Energy Coordinator Design - URA v3.6.0
## Comprehensive Specification for Whole-House Energy Intelligence

**Version:** 2.0 (Updated with confirmed entities and solar forecasting)  
**Status:** Design Phase - Ready for Implementation  
**Created:** January 23, 2026  
**Updated:** January 24, 2026  
**Author:** Energy optimization analysis for Oji's Madrone Labs system  
**Effort Estimate:** 8-10 hours (expanded to include solar forecast integration)  
**Dependencies:** v3.5.0 Census System (for person count awareness)  

---

### Table of Contents

1. [Design Philosophy](#1-design-philosophy) - Governor model, livability-first approach
2. [Hardware Integration Map](#2-hardware-integration-map) - **CONFIRMED** entity mappings
3. [PEC TOU Schedule Configuration](#3-pec-tou-schedule-configuration) - Three-season rate structure
4. [Solar Forecast Integration](#4-solar-forecast-integration) - **NEW** Solcast-aware strategies
5. [Energy Coordinator Architecture](#5-energy-coordinator-architecture) - Core class structure
6. [HVAC Coordinator Integration](#6-hvac-coordinator-integration) - Constraint-based governance
7. [Configuration via Options Flow](#7-configuration-via-options-flow) - User-friendly setup
8. [Sensors & Entities](#8-sensors--entities) - Exposed state and attributes
9. [Implementation Phases](#9-implementation-phases) - Development roadmap
10. [Testing Strategy](#10-testing-strategy) - Validation approach
11. [Success Criteria](#11-success-criteria) - Measurable outcomes
12. [Conclusion](#12-conclusion-why-ura-is-the-right-home) - Integration rationale

---

### Key Additions in v2.0

| Feature | Description | Impact |
|---------|-------------|--------|
| **Solcast Integration** | 30-min granular forecasts with confidence bands | Weather-aware strategy selection |
| **Day Classification** | excellent/good/moderate/poor/very_poor | Automatic strategy adjustment |
| **Confirmed Entities** | Verified 50+ entity mappings from live HA | Zero guesswork in implementation |
| **Battery Control** | `select.enpower_482348004678_storage_mode` confirmed | Full charge/discharge control |
| **EV Charging** | 2x Emporia EVSEs via switches | Simple on/off deferral |
| **Pool via SPAN** | `switch.span_panel_pool_breaker` | Circuit-level control |

---

## ENTITY QUICK REFERENCE

### Confirmed Control Entities

```yaml
# BATTERY CONTROL
select.enpower_482348004678_storage_mode      # Options: backup, self_consumption, savings
number.enpower_482348004678_reserve_battery_level  # 0-100%
switch.enpower_482348004678_charge_from_grid  # Allow grid charging
switch.enpower_482348004678_grid_enabled      # Allow grid export

# BATTERY STATUS
sensor.envoy_202428004328_battery             # SOC %
sensor.envoy_202428004328_current_battery_discharge  # kW (negative=charging)
sensor.envoy_202428004328_available_battery_energy   # Wh

# SOLAR PRODUCTION
sensor.envoy_202428004328_current_power_production   # kW real-time
sensor.envoy_202428004328_energy_production_today    # kWh

# GRID
sensor.envoy_202428004328_current_net_power_consumption  # kW (+import, -export)

# SOLAR FORECAST (Solcast)
sensor.solcast_pv_forecast_forecast_today           # kWh with detailedForecast attribute
sensor.solcast_pv_forecast_forecast_remaining_today # kWh
sensor.solcast_pv_forecast_power_now                # W expected now
sensor.solcast_pv_forecast_forecast_tomorrow        # kWh

# POOL CONTROL
switch.span_panel_pool_breaker                      # On/Off via SPAN

# EV CHARGING
switch.garage_a                                     # EVSE_Emporia_Wifi_GarageA
switch.garage_b                                     # EVSE_Emporia_Wifi_GarageB
```

---

## SOLAR FORECAST STRATEGY MATRIX

| Day Quality | Expected kWh | Battery Mode | HVAC Strategy | EV/Pool |
|-------------|-------------|--------------|---------------|---------|
| **Excellent** | >100 | self_consumption | Normal (relaxed) | Run during peak solar |
| **Good** | 60-100 | self_consumption | Light pre-cool | Prefer solar, off-peak backup |
| **Moderate** | 30-60 | savings (TOU) | Standard pre-cool/coast | Off-peak only |
| **Poor** | 15-30 | savings (TOU) | Aggressive pre-cool | Off-peak only |
| **Very Poor** | <15 | savings + grid charge | Max pre-cool, tight coast | Defer if possible |

**Today's Example (Cloudy):**
- Forecast: 10.8 kWh (estimate), 5.9 kWh (pessimistic), 17.5 kWh (optimistic)
- Classification: **Poor**
- Strategy: Aggressive TOU optimization, grid charge battery overnight

---

## IMPLEMENTATION PHASES

### Phase 1: Core Infrastructure (2-3 hours)
- Create `domain_coordinators/energy/` directory
- Implement EnergyCoordinator base class
- TOU period calculation and monitoring
- Event bus integration
- Basic sensors (TOU period, current rate)

### Phase 2: Solar Forecast Integration (2 hours) **NEW**
- Implement SolarForecastAnalyzer class
- Day classification logic
- Solcast entity subscription
- Solar forecast quality sensor
- Integration with strategy selection

### Phase 3: HVAC Governance (2 hours)
- HVACConstraints class
- HVAC request approval flow
- Pre-cooling/coasting strategy logic (solar-aware)
- Occupancy integration

### Phase 4: Battery Optimization (1-2 hours)
- Battery strategy calculation (solar-aware)
- Enphase entity mapping (confirmed)
- Storage mode control
- Strategy sensor

### Phase 5: Load Management (1-2 hours)
- Load shedding evaluation
- Pool pump scheduling
- EV charging deferral

### Phase 6: Configuration (1 hour)
- Options flow with PEC presets
- Solcast auto-discovery
- Optimization settings

**Total: 8-10 hours**

---

See full document for complete architecture, code examples, and testing strategy.
