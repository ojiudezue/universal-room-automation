# URA Energy Management System

Technical reference for how the Universal Room Automation energy coordinator optimizes electricity cost while maintaining comfort and battery longevity.

---

## 1. Goal

Minimize electricity cost while maintaining comfort and battery longevity. The system optimizes battery reserve level, EVSE charging, pool pump speed, and smart plugs based on Time-of-Use (TOU) rates and solar forecast. All decisions run on a configurable timer (default 5 minutes) and can operate in observation mode (sensors compute but no actions execute).

---

## 2. System Hardware

| Component | Details |
|---|---|
| Battery | 40 kWh total — 8x Enphase IQ 5P (5 kWh each) |
| Solar array | 19.4 kW DC — 50 panels |
| EVSE | 2x Emporia WiFi (11.5 kW each) — Garage A and Garage B |
| Pool pump | Pentair VSF — variable speed 15-75 GPM |
| L1 charger plugs | Moes WiFi smart plug (4 sockets) |
| Smart panel | SPAN — per-circuit monitoring and breaker control |
| Gateway | Enphase Envoy — solar/battery/grid monitoring |
| Forecast | Solcast PV — today, tomorrow, remaining, peak |

---

## 3. Control Levers

### Storage Mode
Always `self_consumption`. The Enphase codicil prohibits `savings` mode because it gives up Home Assistant control of the battery. Enphase does not support direct battery-to-grid export; `self_consumption` with reserve level adjustment is the only viable strategy.

### Reserve SOC
Primary control lever. A `number` entity on the Enpower (`number.enpower_482348004678_reserve_battery_level`), range 0-100%. Setting reserve high holds charge; setting it low allows discharge. The coordinator adjusts this every decision cycle based on TOU period and solar forecast.

### Charge from Grid
Switch entity on the Enpower (`switch.enpower_482348004678_charge_from_grid`). Used for two scenarios:
- **Storm prep**: Pre-charge battery before severe weather
- **Overnight arbitrage**: Charge at off-peak rate when tomorrow's solar is poor

### EVSE Switches
On/off control per charger:
- `switch.garage_a` (Garage A)
- `switch.garage_b` (Garage B)

Power monitored via `sensor.garage_a_power_minute_average` and `sensor.garage_b_power_minute_average`. Charging detected when power > 100W.

### Pool VSF Speed
`number.pentair_pool_variable_speed_pump_1_speed` — normal operation at 75 GPM, reduced to 30 GPM during peak (approximately 94% power savings due to the cubic relationship between flow and power in VSF pumps).

### Smart Plugs
On/off switches for additional controllable loads. Configured via options flow as a list of entity IDs. Default: 4x Moes WiFi sockets for L1 EV charging.

---

## 4. TOU Rate Structure

**PEC 2026 Time-of-Use Interconnection Metering (<50 kW)**

### Summer (Jun-Sep)

| Period | Hours | Rate ($/kWh) |
|---|---|---|
| Off-peak | 12am-2pm, 9pm-12am | $0.0435 |
| Mid-peak | 2pm-4pm, 8pm-9pm | $0.0932 |
| **Peak** | **4pm-8pm** | **$0.1618** |

### Shoulder (Mar-May, Oct-Nov)

| Period | Hours | Rate ($/kWh) |
|---|---|---|
| Off-peak | 12am-5pm, 9pm-12am | $0.0435 |
| Mid-peak | 5pm-9pm | $0.0864 |

### Winter (Dec-Feb)

| Period | Hours | Rate ($/kWh) |
|---|---|---|
| Off-peak | 12am-5am, 9am-5pm, 9pm-12am | $0.0435 |
| Mid-peak | 5am-9am, 5pm-9pm | $0.0864 |

### Fixed Charges
- Service availability: $32.50/month
- Delivery: $0.0225/kWh
- Transmission: $0.0199/kWh
- **Effective import rate** = base rate + delivery + transmission

### Symmetric Import/Export
Export credit equals import rate at each TOU period. Stored solar exported during peak earns $0.1618/kWh in summer -- the same as avoided peak import.

### Custom Rate Files
The TOU engine supports loading rates from a JSON file at `/config/universal_room_automation/tou_rates.json`, falling back to the built-in PEC 2026 table if the file is absent or invalid.

---

## 5. Per-Season Battery Strategy

The battery strategy runs in `BatteryStrategy.determine_mode()` each decision cycle. It receives the current TOU period and season and returns a set of service calls (mode change, reserve level, charge-from-grid toggle).

### Priority Chain (evaluated top to bottom)

1. **Envoy unavailable** -- hold current state, issue no commands
2. **Grid disconnected** -- switch to `backup` mode
3. **Storm forecast** -- pre-charge to 90% via grid if needed, then hold in `backup`
4. **Peak period** -- discharge
5. **Mid-peak** -- season-dependent (hold or discharge)
6. **Off-peak** -- SOC-conditional drain with optional arbitrage

### Summer Cycle

**Off-peak (12am-2pm, 9pm-12am)**: SOC-conditional drain based on tomorrow's solar forecast:

| Tomorrow's Solar | Drain Target (SOC %) | Rationale |
|---|---|---|
| Excellent (>= P75) | 10% | Solar refills tomorrow; maximize absorption headroom |
| Good (>= P50) | 15% | Solar refills tomorrow |
| Moderate (>= P25) | 20% | Off-peak grid at $0.043 is 3.7x cheaper than peak |
| Poor (< P25) | 30% | Arbitrage catches worst case if SOC drops further |
| Unknown | 40% | Conservative default |

- If SOC > drain target: set reserve to drain target, battery discharges stored solar (free energy) while home imports at $0.0435/kWh
- If SOC <= drain target: set reserve to current SOC (hold), home imports cheap grid

**Mid-peak (2pm-4pm, 8pm-9pm)**: Hold charge. Reserve set to current SOC. Battery is preserved for the upcoming peak window.

**Peak (4pm-8pm)**: Discharge battery to cover home load. Reserve set to configured minimum (default 20%). Solar simultaneously exports at $0.1618/kWh.

**Late mid-peak (8pm-9pm)**: Hold remaining charge. Reserve set to current SOC.

### Shoulder/Winter Cycle

No peak period exists. Mid-peak IS the highest-rate window.

**Off-peak**: Same SOC-conditional drain logic as summer, using tomorrow's solar forecast.

**Mid-peak (shoulder 5pm-9pm, winter 5am-9am + 5pm-9pm)**: Discharge battery to cover load. Reserve set to configured minimum. This IS the best rate window -- battery should discharge rather than holding for a peak that never comes.

### Grid Charge Arbitrage

When all conditions are met:
- Arbitrage is enabled in config
- Tomorrow's solar is `poor` or `very_poor`
- Current SOC < trigger threshold (default 30%)

Then:
- Enable `charge_from_grid` switch
- Battery charges overnight at $0.0435/kWh off-peak
- Avoids importing at $0.0864-$0.1618/kWh later
- Stops when SOC reaches target (default 80%)
- Storm prep takes priority over arbitrage

---

## 6. Battery-EV Interaction

### Problem: EVSE Battery Drain

EVSEs appear as house load to the Envoy. When an EVSE draws 11.5 kW, the Envoy sees 11.5 kW of "house consumption" and discharges the battery to cover it. This wastes stored solar energy when grid power costs only $0.0435/kWh during off-peak.

### Solution: EVSE Battery Hold

When any EVSE is actively charging (power > 100W), the coordinator overrides battery reserve to current SOC. The battery holds its charge instead of discharging. The EV draws directly from the grid at the cheap off-peak rate.

The hold is released when EVSE charging stops. The `_evse_battery_hold_active` flag tracks this state.

### Excess Solar EVSE Charging

When surplus solar would otherwise be wasted:

**Activation conditions** (all must be true):
- Battery SOC >= 95% (configurable)
- Remaining solar forecast >= 5.0 kWh (configurable)
- Current TOU period is off-peak or mid-peak (never peak)
- EVSE not already paused by TOU logic

**Behavior**:
- Turn on EVSEs to absorb excess solar
- Track which EVSEs the system turned on (`_excess_solar_active` set)
- Turn off only system-activated EVSEs when conditions are no longer met
- Peak period forces immediate turn-off of excess solar EVSEs

---

## 7. Export Economics

With symmetric TOU rates, stored solar exported during peak earns the same credit as avoided peak import. During summer peak:

- **Battery discharge** covers home load (avoids importing at $0.1618/kWh)
- **Solar production** exports to grid (earns $0.1618/kWh credit)
- **Net savings** = avoided import cost + export credit

The effective import rate includes delivery ($0.0225) and transmission ($0.0199), so total import cost is $0.2042/kWh at peak -- but export credit is only the base rate ($0.1618). This asymmetry means avoiding import is slightly more valuable than exporting.

---

## 8. Cost Tracking

### Real-Time Accumulation

The `CostTracker` accumulates cost each decision cycle by reading net power and multiplying by the effective rate for elapsed time:

- **Net power > 0** (importing): cost += energy_kwh * effective_import_rate
- **Net power < 0** (exporting): cost -= energy_kwh * export_rate

Skips unreasonable intervals (> 1 hour gap, e.g., after HA restart).

### Daily Snapshots

At each date change, daily totals are saved to the `energy_daily` database table:
- Grid import kWh and cost
- Grid export kWh and credit
- Net cost (import cost minus export credit)
- Predicted vs actual consumption (for accuracy tracking)

### Billing Cycle

- Accumulates from bill cycle start day (default: 23rd of month)
- Restores cycle totals from database on HA startup
- Resets automatically when a new cycle begins

### Bill Prediction

- Available after 7+ days of data in current cycle
- Linear extrapolation: `(net_cost / days_elapsed) * total_cycle_days + $32.50 service fee`
- Shows "Learning (N days)" label while building sufficient data
- Uses DB day count (survives restarts) when available

### Key Sensors

| Sensor | Value |
|---|---|
| Cost today | Net import cost minus export credit |
| Cost this cycle | Accumulated since bill cycle start |
| Predicted bill | Extrapolated monthly bill |
| Current effective rate | Base + delivery + transmission |
| Import/export kWh | Daily and cycle totals |

---

## 9. Forecast Integration

### Solcast PV Forecast

| Entity | Purpose |
|---|---|
| `sensor.solcast_pv_forecast_forecast_today` | Today's total production forecast (kWh) |
| `sensor.solcast_pv_forecast_forecast_tomorrow` | Tomorrow's total (drives off-peak drain) |
| `sensor.solcast_pv_forecast_forecast_remaining_today` | Remaining today (drives excess solar EVSE) |
| `sensor.solcast_pv_forecast_peak_forecast_today` | Peak production forecast |
| `sensor.solcast_pv_forecast_peak_time_today` | Time of peak production |

### Solar Day Classification

Per-month percentile thresholds derived from actual Enphase production data (50 panels, 19.4 kW DC):

| Month | P25 (kWh) | P50 (kWh) | P75 (kWh) |
|---|---|---|---|
| Jan | 33 | 61 | 83 |
| Feb | 49 | 66 | 80 |
| Mar | 60 | 80 | 95 |
| Apr | 73 | 93 | 108 |
| May | 85 | 103 | 118 |
| Jun | 106 | 125 | 136 |
| Jul | 100 | 120 | 133 |
| Aug | 88 | 108 | 124 |
| Sep | 68 | 88 | 104 |
| Oct | 50 | 68 | 83 |
| Nov | 36 | 52 | 66 |
| Dec | 33 | 61 | 83 |

Classification rules:
- **Excellent**: forecast >= P75
- **Good**: forecast >= P50
- **Moderate**: forecast >= P25
- **Poor**: forecast < P25

An alternative `custom` mode allows fixed thresholds independent of month (configurable via options flow).

### Temperature Regression

After 30+ days of paired temperature-consumption data:

```
consumption = base + coeff * |temp - 72|
```

- Fit from `energy_daily` table (temp_high, consumption_kwh pairs)
- Blended with day-of-week baseline: 70% regression, 30% historical
- Falls back to fixed multiplier bands when insufficient data:
  - >95F: 1.3x, >85F: 1.15x, >75F: 1.0x, <40F: 1.2x, <55F: 1.05x, 55-75F: 0.9x

### Bayesian Accuracy

- Compares yesterday's predicted consumption vs actual each morning
- Maintains rolling 30-day error window (persisted in DB, survives restarts)
- Computes adjustment factor from recent 7-day average error
- Factor range clamped to [0.7, 1.3] with 30% damping
- Applied multiplicatively to consumption estimates

### Sunrise Refresh

Prediction is generated at midnight but refreshed within 30 minutes of sunrise with updated Solcast data (Solcast updates overnight forecasts).

### Weather Service

`weather.get_forecasts` provides daily high/low temperatures (async service call, cached). Used for:
- Temperature regression input
- HVAC pre-heat decision (forecast low < 40F threshold)
- Storm detection (lightning, hail, tornado, hurricane, exceptional conditions)

---

## 10. Load Shedding Cascade

When sustained grid import exceeds the threshold for the configured duration (default: 5.0 kW for 15 minutes), loads are shed in priority order:

| Level | Target | Action |
|---|---|---|
| 1 | Pool pump | Reduce speed 75 -> 30 GPM |
| 2 | EV chargers | Pause (turn off switches) |
| 3 | Smart plugs | Turn off |
| 4 | HVAC | Energy constraint signal (coast/shed offset) |

The cascade is defined in `LOAD_SHEDDING_PRIORITY: ["pool", "ev", "smart_plugs", "hvac"]`.

### HVAC Constraint Signals

When the cascade reaches level 4, the Energy Coordinator publishes an energy constraint signal to the HVAC Coordinator with configurable temperature offsets:

| Mode | Offset (default) | Meaning |
|---|---|---|
| `coast` | +3.0 F | Widen deadband, reduce cycling |
| `pre_cool` | -2.0 F | Pre-cool before peak (anticipatory) |
| `pre_heat` | +2.0 F | Pre-heat before peak (anticipatory) |
| `shed` | +5.0 F | Aggressive setpoint relaxation |

Pre-heat activates when forecast low < 40F.

### Threshold Modes

- **Fixed**: User-configured threshold in kW (default 5.0)
- **Auto-learned**: 90th percentile of peak import history. Requires 30+ days of data. Peak import values saved hourly to `energy_peak_import` DB table (with dirty flag to avoid unnecessary writes).

### Recovery

Loads are restored in reverse cascade order when grid import drops below threshold. Only loads paused by the energy coordinator are restored (tracked via `_paused_by_us` sets in each controller).

---

## 11. Decision Cycle Flow

Every 5 minutes (configurable), `_async_decision_cycle` runs:

1. **Date change check** -- reset daily counters, save yesterday's data to DB, evaluate forecast accuracy
2. **Sunrise refresh** -- re-generate prediction with fresh Solcast if within 30min of sunrise
3. **Generate daily prediction** -- PV forecast, consumption estimate, battery full time
4. **Billing accumulation** -- track import/export cost for the elapsed interval
5. **Battery decision** -- determine mode, reserve level, and charge-from-grid state
6. **EVSE battery hold** -- if any EVSE charging, override reserve to current SOC
7. **Excess solar EVSE** -- if SOC >= 95% and remaining solar >= 5 kWh, turn on EVSEs
8. **Pool optimization** -- reduce speed during peak
9. **EV charger TOU** -- pause during peak/mid-peak
10. **Smart plug TOU** -- pause during peak
11. **Load shedding evaluation** -- check sustained import, cascade if needed
12. **HVAC constraint** -- publish energy constraint signal if situation warrants
13. **Forecast temperature update** -- async `weather.get_forecasts` call (cached)
14. **Execute actions** -- unless observation mode is active

### Observation Mode

When enabled, the coordinator computes all decisions and updates all sensors but does not execute any service calls. Useful for monitoring what the system would do before enabling live control.

---

## 12. Database Tables

| Table | Purpose | Write Frequency |
|---|---|---|
| `energy_daily` | Daily import/export/cost/consumption/prediction | Once per day (midnight) |
| `energy_peak_import` | Peak import readings for auto-learned threshold | Hourly during peak (with dirty flag) |
| `energy_history` | 15-minute snapshots of solar, grid, battery, consumption | Every decision cycle |

All tables are in the URA SQLite database at `/config/universal_room_automation/data/universal_room_automation.db`.

---

## 13. Entity Reference

### Enphase / Envoy

| Entity | Type | Purpose |
|---|---|---|
| `sensor.envoy_*_current_power_production` | sensor | Current solar production (W) |
| `sensor.envoy_*_current_power_consumption` | sensor | Current grid consumption (W) |
| `sensor.envoy_*_battery` | sensor | Battery SOC (%) |
| `sensor.envoy_*_encharge_aggregate_power` | sensor | Battery power (W, +charge/-discharge) |
| `sensor.envoy_*_current_net_power_consumption` | sensor | Net power (W, +import/-export) |
| `sensor.envoy_*_lifetime_energy_consumption` | sensor | Lifetime consumption (kWh, monotonic) |
| `sensor.envoy_*_lifetime_energy_production` | sensor | Lifetime production (kWh, monotonic) |
| `sensor.envoy_*_battery_capacity` | sensor | Battery capacity (Wh) |
| `select.enpower_*_storage_mode` | select | Storage mode (self_consumption/savings/backup) |
| `number.enpower_*_reserve_battery_level` | number | Reserve SOC (0-100%) |
| `switch.enpower_*_grid_enabled` | switch | Grid connection status |
| `switch.enpower_*_charge_from_grid` | switch | Charge battery from grid |

### Solcast

| Entity | Purpose |
|---|---|
| `sensor.solcast_pv_forecast_forecast_today` | Today's total PV forecast (kWh) |
| `sensor.solcast_pv_forecast_forecast_tomorrow` | Tomorrow's total PV forecast (kWh) |
| `sensor.solcast_pv_forecast_forecast_remaining_today` | Remaining PV today (kWh) |
| `sensor.solcast_pv_forecast_peak_forecast_today` | Peak power forecast |
| `sensor.solcast_pv_forecast_peak_time_today` | Time of peak production |

### EVSE (Emporia)

| Entity | Purpose |
|---|---|
| `switch.garage_a` / `switch.garage_b` | EVSE on/off control |
| `sensor.garage_a_power_minute_average` | Garage A power (W) |
| `sensor.garage_b_power_minute_average` | Garage B power (W) |
| `switch.span_panel_car_charger_breaker` | SPAN breaker for Garage A |
| `switch.span_panel_garage_b_evse_breaker` | SPAN breaker for Garage B |

### Pool (Pentair)

| Entity | Purpose |
|---|---|
| `number.pentair_pool_variable_speed_pump_1_speed` | VSF pump speed (GPM) |
| `sensor.pentair_pool_variable_speed_pump_1_power` | Pump power consumption (W) |

### Smart Plugs (L1 Charger)

| Entity | Purpose |
|---|---|
| `switch.smartplug_moes_wifi_garagealeftfront_socket_1` | L1 charger socket 1 |
| `switch.smartplug_moes_wifi_garagealeftfront_socket_2` | L1 charger socket 2 |
| `switch.smartplug_moes_wifi_garagealeftfront_socket_3` | L1 charger socket 3 |
| `switch.smartplug_moes_wifi_garagealeftfront_socket_4` | L1 charger socket 4 |

---

## 14. Architecture

```
EnergyCoordinator (energy.py)
├── TOURateEngine (energy_tou.py)         — season, period, rate resolution
├── BatteryStrategy (energy_battery.py)   — mode determination, reserve control
├── CostTracker (energy_billing.py)       — real-time cost, billing cycle, prediction
├── DailyEnergyPredictor (energy_forecast.py) — PV/consumption forecast, battery full time
├── AccuracyTracker (energy_forecast.py)  — Bayesian prediction adjustment
├── PoolOptimizer (energy_pool.py)        — VSF speed management
├── EVChargerController (energy_pool.py)  — EVSE pause/resume, excess solar
├── SmartPlugController (energy_pool.py)  — additional load management
├── SPANCircuitMonitor (energy_circuits.py) — per-circuit monitoring
└── GeneratorMonitor (energy_circuits.py) — generator status tracking
```

Priority: 40 (above Comfort/HVAC at 20-30, below Safety at 100).

Decision interval: 5 minutes (configurable). The 60-90 second buffer within each 5-minute cycle accommodates Enphase command latency.
