# Energy Coordinator Implementation Plan

**Version:** v3.7.0
**Status:** Planning
**Created:** 2026-03-06
**Source:** ENERGY_COORDINATOR_DESIGN_v2.3.md + ENERGY_HVAC_QUESTIONS.md (all answers)
**Predecessor:** PLANNING_v3.6.0_REVISED.md Cycle 5

---

## Differences from Revised Plan (C5)

| Area | Revised Plan (C5) | This Plan | Rationale |
|------|-------------------|-----------|-----------|
| **Vehicle detection** | In scope (LLMVision + cameras) | Deferred | Not in user's feature list; no presence coordinator support yet |
| **Load shedding** | Configurable priority list, active | Planned + stubbed, off by default | High risk; user wants it designed but not active initially |
| **SPAN control** | Deferred to future cycle | Monitor-only, discover + tag controllable | User confirmed no active control, but track capability |
| **Livability scoring** | 0-10 scale per action | Coarse strategies only | User: "pareto principle"; formal scoring is edge-case refinement |
| **Bill calculation** | Not mentioned | Full billing: cost today/week/cycle, predicted bill | User requirement: predict monthly bill after 1 week of cycle data |
| **Forecast + prediction** | Solar forecast only (Solcast) | PV forecast + weather + historical Bayesian, daily prediction, accuracy feedback loop | User wants energy use prediction, battery-full-time, net import/export forecasts |
| **Circuit anomaly** | Anomaly detection, weekly learning | Anomaly + critical NM notification + sensor | User: tripped breakers → immediate NM alert, not just logged |
| **Smart plug loads** | Not mentioned | Additional controllable loads in config | User has L1 charger and other smart-plug loads beyond EVSEs |
| **Blinds / solar gain** | Not mentioned | Common area covers for solar gain reduction | Separate from room cover automation; energy-driven |
| **Config approach** | TOU in config flow, full setup | Minimal setup, most in options flow (reconfig) | User preference |
| **Effort estimate** | 3-4 hours | 12-16 hours across sub-cycles | Realistic given scope expansion |
| **Generator** | Load management during outages | Monitoring + alerts only | User: "not much use except state monitoring" |
| **HVAC constraints** | Full governance in C5 | Stub interface only; HVAC coordinator is C6 | Build order: Energy first, HVAC responds later |
| **Export optimization** | In scope | In scope (unchanged) | Symmetric rates make this straightforward |
| **Cost sensors** | `sensor.ura_energy_savings_today` | Real-time rate, cost today/week/cycle, import vs export separated | Expanded per user request |

---

## 1. Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                    ENERGY COORDINATOR (priority 40)                 │
│                    domain_coordinators/energy.py                    │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  CORE ENGINE (5-min cycle + event-driven)                          │
│  ├── TOU Rate Engine         → current period, rate, season        │
│  ├── Battery Strategy        → mode, reserve, grid switches        │
│  ├── Solar Forecast Reader   → Solcast day classification          │
│  ├── Weather Reader          → outdoor temp, forecast conditions   │
│  └── Decision Evaluator      → combines inputs → actions           │
│                                                                    │
│  ACTIVE CONTROL (direct service calls)                             │
│  ├── Battery Controller      → storage_mode, reserve, grid export  │
│  ├── Pool Optimizer          → VSF speed, circuit switches         │
│  ├── EV Charger Controller   → on/off per EVSE + smart plugs       │
│  └── Cover Controller        → common area blinds for solar gain   │
│                                                                    │
│  MONITORING (read-only)                                            │
│  ├── SPAN Circuit Monitor    → per-circuit power, anomaly detect   │
│  ├── Emporia Monitor         → EVSEs, sub-panel, excess solar      │
│  ├── Generator Monitor       → running state, alerts               │
│  └── Grid Monitor            → net import/export, consumption      │
│                                                                    │
│  FORECASTING                                                       │
│  ├── Daily Energy Predictor  → PV + weather + historical baseline  │
│  ├── Battery Full Time Est   → when will SOC reach 100% today?     │
│  ├── Net Position Forecast   → import vs export prediction         │
│  └── Accuracy Tracker        → forecast vs actual, feedback loop   │
│                                                                    │
│  BILLING                                                           │
│  ├── Cost Calculator         → real-time rate, daily/weekly cost   │
│  ├── Bill Cycle Tracker      → cycle dates (23rd-23rd)             │
│  └── Bill Predictor          → predicted monthly bill (after 7d)   │
│                                                                    │
│  CONSTRAINTS (published via dispatcher)                            │
│  └── SIGNAL_ENERGY_CONSTRAINT → HVACConstraints for HVAC coord    │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
         │ dispatcher signal
         ▼
┌────────────────────────────────────────────────────────────────────┐
│              HVAC COORDINATOR (priority 30) — FUTURE C6            │
│              Receives constraints, manages 3 climate zones         │
└────────────────────────────────────────────────────────────────────┘
```

### Device Ownership (MECE)

| Device Domain | Owner | Control |
|---------------|-------|---------|
| Battery (Enphase) | Energy | Direct: storage_mode, reserve, grid switches |
| Pool (Pentair) | Energy | Direct: VSF speed, circuit switches |
| EVSEs (Emporia) | Energy | Direct: on/off switches |
| Smart plug loads | Energy | Direct: on/off |
| SPAN circuits | Energy | Monitor only (control stubbed) |
| Generator (Generac) | Energy | Monitor only |
| Common area covers | Energy | Direct: close for solar gain |
| Climate zones | HVAC (future) | Via constraint signal |
| Room fans | HVAC (future) | Via constraint signal |

---

## 2. Sub-Cycles

The Energy Coordinator is too large for a single cycle. Split into sub-cycles
that each deliver testable, deployable functionality.

### Sub-Cycle E1: TOU Engine + Battery Strategy
**Scope:** Core TOU rate engine, battery mode control, solar forecast reading
**Delivers:** The brain — knows what TOU period it is, reads solar/battery state, sets battery mode

**What ships:**
- `EnergyCoordinator` class extending `BaseCoordinator`
- `TOU Rate Engine`: PEC rate table as Python dict default, season/period/hour resolution
  - `get_current_period()` → off_peak / mid_peak / peak
  - `get_current_rate()` → $/kWh for current period
  - `get_season()` → summer / shoulder / winter
  - Fixed charges tracked separately (service $32.50, delivery $0.0225/kWh, transmission $0.0199/kWh)
- `Battery Strategy`: Reads SOC, solar production, grid net; sets storage_mode
  - Off-peak: `self_consumption` (charge from solar + grid if needed)
  - Mid-peak: `self_consumption` (hold, discharge to home only)
  - Peak: `savings` (discharge to grid for export credits when solar covers home)
  - Storm pre-charge: if weather forecast shows storm, charge to 100% before
  - Reserve SOC floor: configurable (default 20%)
- `Solar Forecast Reader`: Reads Solcast sensors
  - Day classification: excellent/good/moderate/poor/very_poor
  - Forecast remaining today, peak power, 30min/1hr lookahead
- 5-minute decision cycle + TOU transition events
- Config: minimal setup (enable toggle), options flow for reserve SOC, battery entity mapping

**Sensors:**
- `sensor.ura_tou_period` — current TOU period (off_peak/mid_peak/peak)
- `sensor.ura_tou_rate` — current import rate $/kWh
- `sensor.ura_tou_season` — current season
- `sensor.ura_battery_strategy` — current battery mode + reason
- `sensor.ura_solar_day_class` — Solcast day classification

**Tests:** 25+ (TOU period resolution for all seasons/hours, battery mode selection, solar classification)

### Sub-Cycle E2: Pool + EV + Smart Plugs
**Scope:** Active control of pool, EVSEs, and additional controllable loads
**Delivers:** Load management — reduce pool speed during peak, defer EV charging

**What ships:**
- `Pool Optimizer`:
  - Tier 1: VSF speed reduction (75→30 GPM during peak, 94% power savings)
  - Tier 2: Circuit shedding (infinity edge off during peak) — stubbed, off by default
  - Tier 3: Full shutdown — stubbed, off by default
  - Restore to normal speeds on off-peak transition
  - Respect Pentair schedules (don't fight the IntelliCenter scheduler)
- `EV Charger Controller`:
  - Pause charging during peak/mid-peak via `switch.garage_a/b`
  - Resume on off-peak transition
  - SPAN breaker awareness (can control at circuit level too)
- `Smart Plug Controller`:
  - Config: list of additional controllable loads (entity_id + name)
  - Pause during peak, resume off-peak
- Config: pool entity mapping, EVSE entity mapping, smart plug list in options flow

**Sensors:**
- `sensor.ura_pool_optimization` — current pool state (normal/reduced/shed/off)
- `sensor.ura_ev_charging_status` — charging/paused/idle per EVSE
- `binary_sensor.ura_load_shedding_active` — any load shedding in effect

**Tests:** 15+ (pool speed commands, EV pause/resume, TOU-driven transitions)

### Sub-Cycle E3: Circuit Monitoring + Anomaly Detection
**Scope:** SPAN/Emporia circuit monitoring, anomaly detection, NM integration
**Delivers:** Circuit-level visibility and tripped-breaker alerts

**What ships:**
- `SPAN Circuit Monitor`:
  - Auto-discover all SPAN circuit entities on startup
  - Per-circuit power tracking (read-only)
  - Tag circuits as: controllable / measurement-only / protected (stored in options)
  - Build per-circuit baselines by hour-of-day and day-of-week (after 14 days)
- `Emporia Monitor`:
  - EVSE power monitoring (detect active charging vs idle)
  - Sub-panel total power
  - Excess solar monitoring
- `Circuit Anomaly Detection`:
  - Sudden zero-power on a normally-loaded circuit → tripped breaker alert
  - Consumption outside historical baseline → anomaly notification
  - Alerts via NM (critical severity for tripped breaker)
  - Anomaly sensor for external automation
- Generator monitoring: Generac running state, NM alert on outage detection

**Sensors:**
- `sensor.ura_circuit_anomaly` — anomaly state + details
- `sensor.ura_generator_status` — running/standby/off
- Per-circuit power data exposed via attributes (not individual sensors — too many)

**Tests:** 15+ (circuit discovery, anomaly detection thresholds, NM notification triggers)

### Sub-Cycle E4: Billing + Cost Tracking
**Scope:** Real-time cost awareness, bill cycle tracking, bill prediction
**Delivers:** Know what energy costs right now and predict monthly bill

**What ships:**
- `Cost Calculator`:
  - Real-time effective rate: base power charge + delivery + transmission for imports
  - Export credit rate: base power credit only (no delivery/transmission on exports)
  - Cost accumulation: per-TOU-period, daily, weekly
  - Import cost vs export credits tracked separately
- `Bill Cycle Tracker`:
  - Configurable cycle start day (default: 23)
  - Tracks: days into cycle, cost so far this cycle, import kWh, export kWh
- `Bill Predictor`:
  - After 7 days of cycle data: extrapolate to end of cycle
  - Factor in: remaining days, seasonal patterns, weather forecast
  - Updates daily

**Sensors:**
- `sensor.ura_energy_cost_today` — net cost today (import cost - export credit)
- `sensor.ura_energy_cost_this_cycle` — cost so far in billing cycle
- `sensor.ura_energy_predicted_bill` — predicted monthly bill (available after 7 days)
- `sensor.ura_energy_current_rate` — effective $/kWh right now
- `sensor.ura_energy_import_today` — import kWh + cost
- `sensor.ura_energy_export_today` — export kWh + credit

**Tests:** 10+ (rate calculation, bill prediction math, cycle date handling)

### Sub-Cycle E5: Forecasting + Prediction
**Scope:** Daily energy prediction, battery timing, accuracy feedback
**Delivers:** Morning prediction of the day's energy position

**What ships:**
- `Daily Energy Predictor` (runs at start of day):
  - PV production estimate (Solcast forecast_today)
  - Consumption estimate (historical baseline for day-of-week + weather correlation)
  - Net position: expected import vs export
  - Sub-predictions:
    - Battery full time estimate (PV curve + current SOC + charge rate)
    - Excess energy estimate (production - consumption)
    - Pre-cool needed? (based on outdoor temp forecast vs comfort threshold)
    - With/without EV charging scenarios
- `Accuracy Tracker`:
  - Compare yesterday's prediction vs actual at end of day
  - Rolling error metrics (7-day, 30-day)
  - Bayesian adjustment: weight recent accuracy to improve future predictions
  - Sensor showing current prediction confidence

**Sensors:**
- `sensor.ura_energy_forecast_today` — predicted net kWh (+ = export, - = import)
- `sensor.ura_energy_battery_full_time` — estimated time battery reaches 100%
- `sensor.ura_energy_forecast_accuracy` — prediction accuracy (7-day rolling %)

**Tests:** 10+ (prediction logic, accuracy calculation, baseline learning)

### Sub-Cycle E6: HVAC Constraint Interface + Covers
**Scope:** Publish HVAC constraints, common area cover control for solar gain
**Delivers:** The bridge to HVAC Coordinator + energy-driven blinds

**What ships:**
- `HVAC Constraint Publisher`:
  - `SIGNAL_ENERGY_CONSTRAINT` via HA dispatcher
  - Constraint modes: normal, pre_cool, pre_heat, coast, shed
  - Fields: mode, setpoint_offset (-3 to +4°F), occupied_only, max_runtime_minutes, fan_assist
  - Publish on: TOU transitions, significant solar/weather changes
  - Hierarchy: cost saving first, comfort second; short comfort cycles if humans would override
  - Pre-cool strategy: before peak when energy budget allows
- `Cover Controller` (common area only):
  - Config: list of common area cover entities + orientation (south/west)
  - Close south/west-facing covers during peak solar gain (configurable hours, summer only)
  - Separate from room cover automation (v3.6.39) — different entity list, different triggers
- Load shedding priority: designed + stubbed, not active
  - Priority order: pool speed → EV pause → infinity edge → pool heater → HVAC setback → circuits
  - Data structures in place, execution gated behind `load_shedding_enabled = False`

**Sensors:**
- `sensor.ura_energy_situation` — overall energy situation (normal/optimizing/constrained/shedding)
- `sensor.ura_hvac_constraint` — current constraint mode + offset

**Tests:** 10+ (constraint generation, cover timing, load shedding priority order)

---

## 3. File Structure

```
domain_coordinators/
├── energy.py              # EnergyCoordinator class (E1-E6)
├── energy_tou.py          # TOU rate engine, season/period resolution
├── energy_battery.py      # Battery strategy, SOC management
├── energy_pool.py         # Pool optimizer, VSF speed, circuit control
├── energy_circuits.py     # SPAN/Emporia monitor, anomaly detection
├── energy_forecast.py     # Daily predictor, accuracy tracker
├── energy_billing.py      # Cost calculator, bill cycle, prediction
└── energy_const.py        # Energy-specific constants, rate tables
```

**Why multiple files:** The revised plan estimated 700 lines in one file. This plan
is substantially larger (~1500-2000 lines). Splitting by domain keeps files
manageable and testable. `energy.py` is the coordinator class that orchestrates
the sub-modules.

**Modified files:**

| File | Change |
|------|--------|
| `domain_coordinators/manager.py` | Register Energy in coordinator dict |
| `sensor.py` | Add Energy sensors (~15 new sensors) |
| `binary_sensor.py` | Add `load_shedding_active` |
| `config_flow.py` | Energy enable toggle (setup), options flow for all config |
| `const.py` | Energy constants, `CONF_ENERGY_ENABLED` already exists |
| `switch.py` | Energy coordinator enable/disable toggle |
| `__init__.py` | Wire Energy coordinator in init |

---

## 4. Configuration

### Setup (minimal)
- Energy coordinator enable toggle (already exists in CM config)

### Options Flow (reconfig)
Organized as sub-steps:

**Step 1: General**
- Reserve SOC floor (default 20%)
- Decision cycle interval (default 5 min)
- Bill cycle start day (default 23)

**Step 2: Platform Entities**
- Battery entities (auto-discovered from Enphase integration)
- Pool entities (auto-discovered from Pentair integration)
- EVSE entities (auto-discovered from Emporia integration)
- Solar forecast entities (auto-discovered from Solcast integration)
- Weather entity (selector)
- Generator entity (selector, optional)
- Additional controllable loads (entity selector, multiple)
- Common area covers for solar gain (entity selector, multiple)

**Step 3: TOU Rate Overrides** (optional — defaults from PEC table)
- Season date overrides
- Per-period rate overrides
- Export credit rate overrides (if asymmetric in future)

---

## 5. TOU Rate Table (PEC 2026 Default)

```python
PEC_TOU_RATES = {
    "summer": {  # June - September
        "months": [6, 7, 8, 9],
        "periods": {
            "off_peak": {
                "hours": [(0, 14), (21, 24)],  # 12a-2p, 9p-12a
                "import_rate": 0.043481,
                "export_rate": 0.043481,
            },
            "mid_peak": {
                "hours": [(14, 16), (20, 21)],  # 2p-4p, 8p-9p
                "import_rate": 0.093169,
                "export_rate": 0.093169,
            },
            "peak": {
                "hours": [(16, 20)],  # 4p-8p
                "import_rate": 0.161843,
                "export_rate": 0.161843,
            },
        },
    },
    "shoulder": {  # March-May, October-November
        "months": [3, 4, 5, 10, 11],
        "periods": {
            "off_peak": {
                "hours": [(0, 17), (21, 24)],  # 12a-5p, 9p-12a
                "import_rate": 0.043481,
                "export_rate": 0.043481,
            },
            "mid_peak": {
                "hours": [(17, 21)],  # 5p-9p
                "import_rate": 0.086442,
                "export_rate": 0.086442,
            },
        },
    },
    "winter": {  # December - February
        "months": [12, 1, 2],
        "periods": {
            "off_peak": {
                "hours": [(0, 5), (9, 17), (21, 24)],  # 12a-5a, 9a-5p, 9p-12a
                "import_rate": 0.043481,
                "export_rate": 0.043481,
            },
            "mid_peak": {
                "hours": [(5, 9), (17, 21)],  # 5a-9a, 5p-9p
                "import_rate": 0.086442,
                "export_rate": 0.086442,
            },
        },
    },
}

PEC_FIXED_CHARGES = {
    "service_availability": 32.50,       # $/month
    "delivery_per_kwh": 0.022546,        # on delivered (imported) energy only
    "transmission_per_kwh": 0.019930,    # on delivered (imported) energy only
}
```

---

## 6. Decision Logic (5-minute cycle)

```
Every 5 minutes (or on TOU transition / significant change):

1. READ INPUTS
   - Current TOU period + rate
   - Battery SOC, production, consumption, net power
   - Solar forecast (remaining today, next hour)
   - Weather (outdoor temp, forecast)
   - Grid status (connected?)

2. BATTERY DECISION
   if grid_disconnected:
       → backup mode, maximize reserve
   elif tou == peak AND soc > reserve_floor:
       if solar > consumption:
           → savings mode (export battery to grid for credits)
       else:
           → savings mode (discharge to home, avoid peak import)
   elif tou == off_peak:
       → self_consumption (charge from solar, grid if needed)
   elif storm_forecast AND soc < 90%:
       → charge_from_grid = True (pre-charge for storm)
   else:
       → self_consumption (default)

3. POOL DECISION
   if tou == peak:
       → reduce VSF to 30 GPM (Tier 1)
       → (Tier 2/3 stubbed, off by default)
   else:
       → restore to normal speed (75 GPM)

4. EV DECISION
   if tou in (peak, mid_peak):
       → pause charging
   else:
       → resume charging (if was paused by us)

5. COVER DECISION (common area)
   if summer AND peak_solar_hours AND solar_gain_covers_configured:
       → close south/west-facing covers
   else:
       → open (or leave to room automation)

6. HVAC CONSTRAINT (stub — HVAC coordinator consumes this later)
   if tou == peak:
       → publish coast constraint (+2-3°F offset)
   elif approaching_peak AND budget_allows:
       → publish pre_cool constraint (-2-3°F offset)
   else:
       → publish normal constraint

7. CIRCUIT MONITORING
   for each monitored circuit:
       if sudden_zero AND was_loaded:
           → NM critical alert (tripped breaker)
       if consumption outside baseline:
           → anomaly sensor update

8. COST TRACKING
   accumulate: import_kwh * effective_rate, export_kwh * export_rate
   update: daily, weekly, cycle totals
```

---

## 7. Verification Checklist

### E1: TOU + Battery
- [ ] TOU period correct for every hour in all 3 seasons
- [ ] Season transitions on correct months
- [ ] Battery switches to savings during summer peak
- [ ] Battery pre-charges before storm forecast
- [ ] Reserve SOC floor respected
- [ ] Decision cycle runs every 5 minutes
- [ ] TOU transition triggers immediate re-evaluation
- [ ] Energy coordinator can be disabled; battery reverts to Enphase default

### E2: Pool + EV
- [ ] Pool pump reduces to 30 GPM during peak
- [ ] Pool pump restores to 75 GPM on off-peak
- [ ] EV charging pauses during peak/mid-peak
- [ ] EV charging resumes on off-peak
- [ ] Smart plug loads pause/resume with TOU
- [ ] Pentair schedules not overridden

### E3: Circuits
- [ ] SPAN circuits auto-discovered on startup
- [ ] Tripped breaker detected and NM critical alert sent
- [ ] Circuit baseline builds after 14 days
- [ ] Consumption anomaly detected and reported
- [ ] Generator outage triggers NM alert

### E4: Billing
- [ ] Current rate reflects TOU period + fixed charges
- [ ] Cost today accumulates correctly
- [ ] Bill cycle resets on day 23
- [ ] Bill prediction available after 7 days of cycle
- [ ] Import cost and export credits tracked separately

### E5: Forecasting
- [ ] Daily prediction generated at start of day
- [ ] Battery full time estimate reasonable
- [ ] Forecast accuracy tracks prediction vs actual
- [ ] Bayesian adjustment improves over 30 days

### E6: Constraints + Covers
- [ ] HVAC constraint published on TOU transition
- [ ] Pre-cool constraint published before peak when budget allows
- [ ] Common area covers close during peak solar hours (summer)
- [ ] Load shedding priority order correct (stubbed)

---

## 8. Sensor Summary

| Sensor | Sub-Cycle | Device |
|--------|-----------|--------|
| `sensor.ura_tou_period` | E1 | Energy Coordinator |
| `sensor.ura_tou_rate` | E1 | Energy Coordinator |
| `sensor.ura_tou_season` | E1 | Energy Coordinator |
| `sensor.ura_battery_strategy` | E1 | Energy Coordinator |
| `sensor.ura_solar_day_class` | E1 | Energy Coordinator |
| `sensor.ura_pool_optimization` | E2 | Energy Coordinator |
| `sensor.ura_ev_charging_status` | E2 | Energy Coordinator |
| `binary_sensor.ura_load_shedding_active` | E2 | Energy Coordinator |
| `sensor.ura_circuit_anomaly` | E3 | Energy Coordinator |
| `sensor.ura_generator_status` | E3 | Energy Coordinator |
| `sensor.ura_energy_cost_today` | E4 | Energy Coordinator |
| `sensor.ura_energy_cost_this_cycle` | E4 | Energy Coordinator |
| `sensor.ura_energy_predicted_bill` | E4 | Energy Coordinator |
| `sensor.ura_energy_current_rate` | E4 | Energy Coordinator |
| `sensor.ura_energy_import_today` | E4 | Energy Coordinator |
| `sensor.ura_energy_export_today` | E4 | Energy Coordinator |
| `sensor.ura_energy_forecast_today` | E5 | Energy Coordinator |
| `sensor.ura_energy_battery_full_time` | E5 | Energy Coordinator |
| `sensor.ura_energy_forecast_accuracy` | E5 | Energy Coordinator |
| `sensor.ura_energy_situation` | E6 | Energy Coordinator |
| `sensor.ura_hvac_constraint` | E6 | Energy Coordinator |

---

## 9. Estimated Effort

| Sub-Cycle | Scope | Est. Lines | Est. Hours |
|-----------|-------|------------|------------|
| E1 | TOU + Battery + Solar | ~400 | 3-4 |
| E2 | Pool + EV + Smart Plugs | ~250 | 2-3 |
| E3 | Circuits + Anomaly | ~300 | 2-3 |
| E4 | Billing + Cost | ~200 | 1-2 |
| E5 | Forecasting + Prediction | ~300 | 2-3 |
| E6 | HVAC Constraints + Covers | ~200 | 1-2 |
| **Total** | | **~1650** | **12-16** |

Plus ~300 lines of modified files (sensors, config_flow, const, manager, switch, init).

---

## 10. Build Order

```
E1 (TOU + Battery) → E2 (Pool + EV) → E3 (Circuits) → E4 (Billing) → E5 (Forecast) → E6 (Constraints)
```

E1 is the foundation — everything else reads from the TOU engine.
E2 adds the first real-world actions (pool/EV control).
E3-E5 can be parallelized but E4 depends on E1's rate engine.
E6 is last because HVAC coordinator doesn't exist yet — stub the signal.

Each sub-cycle is independently deployable and testable.

---

## 11. v3.7.6 Amendments (2026-03-06)

Decisions made during the v3.7.5 post-mortem and EC review session.
These amend the plan above and take precedence where they conflict.

### 11.1 Immediate Fixes (pre-E1, ship in v3.7.6)

| # | Fix | Detail |
|---|-----|--------|
| 1 | **SOC entity ID** | `DEFAULT_BATTERY_SOC_ENTITY` in `energy_const.py` → `"sensor.envoy_202428004328_battery"` (current value `sensor.encharge_aggregate_battery_percentage` doesn't exist, causes `envoy_available = False`) |
| 2 | **Energy forecast sensor** | `predicted_production_kwh` is null — investigate and fix |
| 3 | **Sensor rename** | "Current Energy Rate" → "Actual Energy Rate". "TOU Rate" stays. Add new "Delivery Rate" sensor showing delivery + transmission per-kWh |

### 11.2 Solar Day Classification

**Default mode: Automatic (monthly percentiles)**

Uses per-month P25/P50/P75 thresholds derived from actual Enphase production data (50 panels, 19.4kW DC):

| Month | Poor (<P25) | Moderate (P25-P50) | Good (P50-P75) | Excellent (>=P75) |
|-------|-------------|--------------------|-----------------|--------------------|
| Jan   | <33*        | 33-61*             | 61-83*          | >=83*              |
| Feb   | <49         | 49-66              | 66-80           | >=80               |
| Mar   | <60         | 60-80              | 80-95           | >=95               |
| Apr   | <73         | 73-93              | 93-108          | >=108              |
| May   | <85         | 85-103             | 103-118         | >=118              |
| Jun   | <106        | 106-125            | 125-136         | >=136              |
| Jul   | <100        | 100-120            | 120-133         | >=133              |
| Aug   | <88         | 88-108             | 108-124         | >=124              |
| Sep   | <68         | 68-88              | 88-104          | >=104              |
| Oct   | <50         | 50-68              | 68-83           | >=83               |
| Nov   | <36         | 36-52              | 52-66           | >=66               |
| Dec   | <33         | 33-61              | 61-83           | >=83               |

*Jan values extrapolated from Dec (no Jan data in dataset).

**Override mode: Custom (absolute thresholds)**

Config flow dropdown: "Solar day classification" with two choices:
- **"Automatic (monthly)"** — default, uses table above
- **"Custom"** — reveals four number inputs (Excellent/Good/Moderate/Poor kWh), applied year-round

### 11.3 New Sensors: Consumption + EV + Monitored Plug

| Sensor | Source | Type |
|--------|--------|------|
| `sensor.ura_energy_total_consumption` | Envoy CT clamp (ground truth) | Monitoring |
| `sensor.ura_energy_net_consumption` | Calculated: consumption - solar self-consumed | Monitoring |
| `sensor.ura_energy_ev_charge_rate_garage_a` | `sensor.garage_a_power_minute_average` | Monitoring |
| `sensor.ura_energy_ev_charge_rate_garage_b` | `sensor.garage_b_power_minute_average` | Monitoring |
| `binary_sensor.ura_energy_l1_charger_garage_a` | `switch.smartplug_moes_wifi_garagealeftfront_socket_*` | Monitoring (Charging/Not Charging) |

The Moes plug is switch-only (no power sensor). Binary sensor derived from socket switch state.

### 11.4 Config Flow Additions (Options/Reconfig)

New fields to add:
- **EVSE entities**: entity selector for Emporia WiFi charger devices (Garage A, Garage B)
- **Monitored plugs**: entity selector for smart plugs used as charge status indicators
- **Weather entity**: entity selector, auto-discover `weather.forecast_home` as default
- **Solar day classification mode**: dropdown (Automatic/Custom) + conditional threshold inputs

### 11.5 TOU Rate File

Rates loaded from JSON file at `/config/universal_room_automation/tou_rates.json`:

```json
{
  "utility": "PEC",
  "effective_date": "2025-01-01",
  "seasons": {
    "summer": {
      "months": [6, 7, 8, 9],
      "periods": {
        "off_peak": { "rate": 0.043481, "hours": [[0,6], [22,24]] },
        "mid_peak": { "rate": 0.093169, "hours": [[6,14], [19,22]] },
        "on_peak":  { "rate": 0.161843, "hours": [[14,19]] }
      }
    },
    "shoulder": {
      "months": [3, 4, 5, 10, 11],
      "periods": {
        "off_peak": { "rate": 0.043481, "hours": [[0,6], [22,24]] },
        "mid_peak": { "rate": 0.086442, "hours": [[6,22]] }
      }
    },
    "winter": {
      "months": [12, 1, 2],
      "periods": {
        "off_peak": { "rate": 0.043481, "hours": [[0,6], [22,24]] },
        "mid_peak": { "rate": 0.086442, "hours": [[6,22]] }
      }
    }
  },
  "fixed_charges": {
    "service_availability_monthly": 32.50,
    "delivery_per_kwh": 0.022546,
    "transmission_per_kwh": 0.019930
  }
}
```

Config flow field for file path (defaults to above). Rate changes = edit the JSON, no code changes.

### 11.6 Observation Mode

Separate toggle from the coordinator enable switch:
- **Label**: "Observation Mode"
- **Behavior when ON**: All sensors compute and update normally. No `ServiceCallAction`s are returned from `evaluate()`. Coordinator appears active but takes no control actions.
- **Behavior when OFF** (default): Normal operation — sensors + actions.
- **When coordinator is disabled**: All sensors go `unavailable` (existing behavior). Observation Mode toggle hidden.

Implementation: `switch.ura_energy_observation_mode` entity. In `evaluate()`, gate action generation behind `if not self._observation_mode`.

### 11.7 Bill Extrapolation

**Storage**: URA SQLite DB (not dict). Daily snapshots table:

```sql
CREATE TABLE IF NOT EXISTS energy_daily (
    date TEXT PRIMARY KEY,
    import_kwh REAL,
    export_kwh REAL,
    solar_kwh REAL,
    consumption_kwh REAL,
    cost REAL,
    tou_breakdown TEXT  -- JSON: {"off_peak": {"kwh": X, "cost": Y}, ...}
);
```

**Logic**:
- Current cycle: sum actuals from cycle start (day 23) to today
- Remaining days: extrapolate using 7-day rolling average (weighted by day-of-week when 30+ days available)
- **Learning label**: sensor shows `"Learning (N days)"` until 7 days of data exist in current cycle
- Future: month-over-month comparisons, seasonal adjustments as data accumulates

### 11.8 Daily Predictions / Forecasting

**Schedule**: Run at **midnight**, refresh at **sunrise**

**Inputs**:
- Solar production: Solcast forecast
- Weather: from configured weather entity (`weather.get_forecasts` service) — temperature for consumption adjustment
- Historical consumption: from URA DB, 7-day same-day-of-week rolling average
- Battery: current SOC, capacity, observed charge rates

**Predictions**:
- **Predicted consumption**: `base_consumption + temp_coefficient * |temp - comfort_midpoint|` (linear regression once 30+ days paired data available; simple rolling avg before that)
- **Day cost**: `predicted_solar * self_consumption_ratio * avoided_rate + predicted_import * actual_rate`
- **Battery full time**: `(capacity - current_soc * capacity) / avg_morning_charge_rate` from sunrise
- **Predicted export**: `predicted_solar - predicted_consumption` (clamped >= 0), adjusted by battery absorption

**Weather integration**:
- Config flow: weather entity selector, defaults to auto-discovered `weather.forecast_home`
- First release: temperature for consumption adjustment only
- Future: cloud cover as Solcast cross-check, storm pre-charge triggers, battery strategy recommendations

**Accuracy tracking**: forecast vs actual compared at end of day, stored in DB, 7-day and 30-day rolling error metrics.

### 11.9 Entity Categories (HA Pattern)

Apply `EntityCategory` properly across all Energy sensors:

| Category | Entities |
|----------|----------|
| **None** (state card) | TOU period, TOU rate, battery strategy, solar day class, energy situation |
| **None** (state card) | Cost today, cost this cycle, predicted bill, forecast today |
| **Diagnostic** | Forecast accuracy, circuit anomaly, generator status, observation mode state |
| **Config** | Observation mode toggle, (future) load shedding toggle |

### 11.10 Pending Questions (Resolved)

| Question | Resolution |
|----------|------------|
| Solar thresholds: relative or absolute? | Both — monthly automatic (default) + custom absolute override |
| Moes plug: power monitoring? | No — switch-only, binary charge status |
| Total consumption: source? | Both Envoy CT (ground truth) + calculated net |
| TOU file format? | JSON at `/config/universal_room_automation/tou_rates.json` |
| Simulate toggle label? | "Observation Mode" |
| Bill extrapolation: DB or dict? | DB (`energy_daily` table) |
| Weather integration? | Config flow weather entity selector, temperature for consumption prediction |

---

## 12. Updated Build Order

```
v3.7.6 hotfix: SOC entity fix + forecast fix + sensor rename (ship immediately)
    |
    v
E1 (TOU + Battery + Solar thresholds) — amended with monthly thresholds, TOU JSON file, observation mode
    |
    v
E2 (Pool + EV + Smart Plugs) — amended with EVSE config, Moes plug binary sensor
    |
    v
E3 (Circuits + Anomaly) — unchanged
    |
    v
E4 (Billing + Cost) — amended with DB storage, learning label, consumption sensors
    |
    v
E5 (Forecast + Prediction) — amended with weather integration, midnight+sunrise schedule
    |
    v
E6 (HVAC Constraints + Covers) — unchanged
```
