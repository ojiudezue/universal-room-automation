# v3.11.0 — Energy Management Refinement

**Date**: 2026-03-12
**Scope**: Battery strategy refinement, EVSE intelligence, energy DB wiring, config flow UI, simulation

---

## Summary

Comprehensive energy management upgrade: off-peak SOC-conditional drain based on tomorrow's solar forecast, grid charge arbitrage for poor-forecast nights, EVSE battery hold and excess solar charging, full DB wiring for energy and presence tables, config flow UI for all energy settings, and a Monte Carlo simulation script for parameter optimization.

---

## Phase A: Off-Peak SOC-Conditional Drain

Battery drain during off-peak is now forecast-dependent. Tomorrow's solar classification drives how aggressively we drain overnight:

| Tomorrow's Forecast | Drain Target | Rationale |
|---|---|---|
| Excellent (>= P75) | 10% | Max headroom for solar absorption |
| Good (>= P50) | 15% | Solar refills; cheap grid covers overnight |
| Moderate (>= P25) | 20% | Off-peak grid at $0.043 is 3.7x cheaper than peak |
| Poor (< P25) | 30% | Arbitrage catches worst case |
| Unknown | 40% | Conservative when forecast unavailable |

- Reads `sensor.solcast_pv_forecast_forecast_tomorrow` for classification
- Uses per-month P25/P50/P75 percentile thresholds from `SOLAR_MONTHLY_THRESHOLDS`
- All targets configurable via config flow

## Phase B: Grid Charge Arbitrage

When tomorrow's solar is poor/very_poor AND SOC is below trigger (default 30%), charges battery from grid overnight at off-peak rate to avoid importing at mid-peak/peak rates later.

- Disabled by default (toggle in config flow)
- Stops when SOC reaches target (default 80%)
- Storm forecast takes priority over arbitrage

## Phase C: EVSE Refinement

### C1: Battery Hold During EV Charging
EVSEs appear as house load to Envoy. Battery would discharge to "cover" EV charging during cheap off-peak. Now: when any EVSE draws > 100W, battery reserve locks at current SOC (captured at hold start to prevent ratchet-down).

### C2: Excess Solar EV Charging
When battery SOC >= 95% AND remaining solar forecast >= 5.0 kWh, turns on EVSEs to use excess solar. Turns off when conditions drop or peak begins. Only controls EVSEs it turned on.

### C3: EVSE State Persistence
EVSE paused/excess-solar state saved to DB on teardown, restored on startup. Validates EVSE IDs against current config on restore.

## Phase D: DB Wiring

7 previously-orphaned DB write methods now have callers:

| Table | Caller | Frequency |
|---|---|---|
| energy_history | energy.py decision cycle | Every 3rd cycle (~15 min) |
| external_conditions | energy.py decision cycle | Every 3rd cycle (~15 min) |
| house_state_log | presence.py | On transition |
| zone_events | presence.py | On zone change |
| census_snapshots | camera_census.py | After census |
| person_visits | person_coordinator.py | On room change |
| person_presence_snapshots | person_coordinator.py | Every 15 min |

Daily cleanup: energy_history (180 days), external_conditions (90 days).

## Config Flow UI

All v3.11.0 energy settings now exposed in the Energy Coordinator config step:

- **Off-Peak Drain Targets**: 4 sliders (excellent/good/moderate/poor)
- **Overnight Grid Charging**: Toggle + SOC trigger/target sliders
- **Excess Solar EV Charging**: Toggle + SOC threshold + kWh threshold sliders

Also backfilled 9 missing v3.9.0 load shedding/constraint strings that were rendering as raw key names.

## Simulation Script

`scripts/energy_simulation.py` — standalone 365-day Monte Carlo optimizer. Imports PEC TOU rates and solar thresholds from energy_const.py. Runs 1000+ trials to find optimal drain targets, arbitrage thresholds, and EVSE parameters. Outputs markdown report with cost comparison and sensitivity analysis.

## Explainer Doc

`docs/ENERGY_MANAGEMENT_EXPLAINER.md` — comprehensive technical reference covering hardware, control levers, TOU rates, per-season strategy, battery-EV interaction, export economics, forecast integration, and decision cycle flow.

## Future Planning

`docs/PLANNING_FUTURE_ENERGY_SAVINGS_MODE.md` — exploration doc for temporary savings mode during peak to enable battery-to-grid export. Data-driven approach: collect 30 days of energy_history, quantify gap, then experiment.

---

## Test Summary

| File | Tests |
|---|---|
| test_energy_battery.py | 49 (+26 new) |
| test_energy_evse.py | 21 (new file) |
| D3-D7 wiring tests | +67 |
| **Suite total** | **938** |

---

## Files Changed

| File | Changes |
|---|---|
| domain_coordinators/energy_battery.py | Off-peak drain, arbitrage, tomorrow solar classification |
| domain_coordinators/energy.py | Decision cycle orchestrator, EVSE hold, DB logging, state persistence |
| domain_coordinators/energy_pool.py | Excess solar EVSE logic |
| domain_coordinators/energy_const.py | All new constants |
| database.py | EVSE state table, cleanup methods |
| sensor.py | Battery decision attribute filtering |
| config_flow.py | 11 new energy config fields |
| strings.json | 20 new labels + descriptions |
| translations/en.json | Synced with strings.json |
| presence.py | D3+D4 house state + zone event logging |
| camera_census.py | D5 census snapshot logging |
| person_coordinator.py | D6+D7 person visit + snapshot logging |
| scripts/energy_simulation.py | New: Monte Carlo optimizer |
| docs/ENERGY_MANAGEMENT_EXPLAINER.md | New: technical reference |
| docs/PLANNING_FUTURE_ENERGY_SAVINGS_MODE.md | New: savings mode exploration |
