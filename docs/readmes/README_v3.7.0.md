# URA v3.7.0 — Energy Coordinator

## Summary

Major feature release: Full Energy Coordinator with TOU-aware battery optimization,
pool/EV load management, SPAN circuit monitoring, cost tracking, and daily forecasting.

## New Files (8)

- `domain_coordinators/energy_const.py` — PEC TOU rate tables, entity defaults, config keys
- `domain_coordinators/energy_tou.py` — TOU rate engine (3 seasons, 3 periods, symmetric rates)
- `domain_coordinators/energy_battery.py` — Battery strategy via Enphase self_consumption + reserve level
- `domain_coordinators/energy_pool.py` — Pool VSF optimizer, EV charger pause/resume, smart plug controller
- `domain_coordinators/energy_circuits.py` — SPAN circuit monitor (tripped breaker detection), Generac generator
- `domain_coordinators/energy_billing.py` — Real-time cost tracking, bill cycle management, bill prediction
- `domain_coordinators/energy_forecast.py` — Daily energy prediction, Bayesian accuracy tracking
- `domain_coordinators/energy.py` — Main EnergyCoordinator (priority 40), 5-minute decision cycle

## Modified Files (4)

- `__init__.py` — Energy Coordinator registration block (lines 966-992)
- `switch.py` — Energy enable/disable toggle
- `sensor.py` — 21 new Energy Coordinator sensors across 6 sub-cycles
- `const.py` — VERSION bumped to 3.7.0

## Sub-Cycles

### E1: TOU Engine + Battery Strategy
- PEC 3-season rate schedule (summer Jun-Sep, shoulder Mar/May/Oct/Nov, winter Dec-Feb)
- Battery strategy using self_consumption exclusively per Enphase Control Codicil
- Reserve level as primary control lever (not savings mode)
- 5 sensors: TOU Period, TOU Rate, TOU Season, Battery Strategy, Solar Day Class

### E2: Pool + EV + Smart Plugs
- Pool VSF speed reduction during peak (75→30 GPM, ~94% power savings)
- EV charger pause during peak/mid-peak, resume on off-peak
- Smart plug pause/resume with tracking of "paused by us" set
- 2 sensors: Pool Optimization, EV Charging Status

### E3: Circuit Monitoring + Generator
- Auto-discover SPAN panel circuit entities
- Tripped breaker detection (zero power >120s on loaded circuit)
- Generac generator status monitoring with NM alerts
- 2 sensors: Circuit Anomaly, Generator Status

### E4: Billing & Cost Tracking
- Real-time cost accumulation per decision cycle (power × time × rate)
- Daily and billing cycle accumulators (23rd-23rd cycle)
- Bill prediction after 7 days via linear extrapolation + fixed charges
- 6 sensors: Cost Today, Cost This Cycle, Predicted Bill, Current Rate, Import Today, Export Today

### E5: Forecasting & Prediction
- Daily PV production forecast from Solcast
- Consumption prediction from historical baseline × weather adjustment × Bayesian factor
- Battery full time estimate from remaining solar ÷ charge rate
- Accuracy tracking with rolling 30-day window and Bayesian adjustment (0.7-1.3)
- 3 sensors: Forecast Today, Battery Full Time, Forecast Accuracy

### E6: HVAC Constraint + Situation
- HVAC constraint modes: normal/pre_cool/coast with temperature offsets
- Energy situation assessment: normal/optimizing/constrained
- Stub interface for future HVAC Coordinator consumption
- 2 sensors: Energy Situation, HVAC Constraint

## Dashboard

Added Energy tab to URA v4 dashboard with 6 sections:
- TOU & Rates (6 cards)
- Battery & Solar (6 cards including Enphase entities)
- Cost & Billing (5 cards)
- Real-Time Power (4 cards from Envoy)
- Load Management (5 cards)
- Forecast (4 cards including Solcast)

Also added Energy switch to System tab Coordinator Controls.

## Key Design Decisions

1. **self_consumption only** — Per Enphase Control Codicil, never use savings mode (gives up HA control). Reserve level is the primary control lever.
2. **No battery-to-grid export** — Enphase doesn't support this. "Export optimization" = battery covers home load while solar exports.
3. **5-minute decision cycle** — Accommodates Enphase 30-60s command latency with comfortable margin.
4. **Priority 40** — Above Comfort/HVAC (20-30), below Safety (100).

## Bug Fixes from Code Review

- Fixed class name collision: `EnergyCostTodaySensor` (room) vs coordinator-level → renamed to `EnergyCoordCostTodaySensor`
- Fixed double-unsubscribe of decision timer on disable/enable cycle
- Connected AccuracyTracker feedback loop to DailyEnergyPredictor (was dead code)
- Connected consumption recording for baseline learning (was never called)
- Added missing device_class/state_class on monetary and energy sensors
- Fixed monetary sensors using "$" instead of "USD" unit
- Removed unused imports (defaultdict, DEFAULT_GRID_CONSUMPTION_ENTITY)
- Fixed return type annotation on `_get_cycle_start`
