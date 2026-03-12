# v3.11.0 — Energy Management Refinement Plan

**Status**: Implemented
**Date**: 2026-03-11
**Scope**: Battery strategy refinement, EVSE intelligence, energy DB wiring

---

## Context

v3.10.5 deployed season-aware battery strategy + TOU rate file support. The battery now correctly discharges during shoulder/winter mid-peak instead of holding for a non-existent peak. This plan addresses the next tier of optimizations:

- **Off-peak is too simple**: Battery powers the house from stored solar during off-peak when grid costs $0.043/kWh. That stored solar is worth $0.086-$0.162/kWh if exported later. We should drain to a forecast-dependent target, then import cheap grid.
- **No grid charge arbitrage**: When tomorrow's solar is poor and SOC is low, charging from grid overnight ($0.043) saves money vs importing at mid-peak/peak ($0.086-$0.162).
- **EVSEs drain the battery**: EVSEs appear as house load to Envoy. Battery discharges to "cover" EV charging, wasting stored solar when grid is cheap.
- **Empty DB tables**: energy_history, external_conditions tables have write methods with zero callers. energy_history is critical for forecasting and simulation.

---

## Phase A: Off-Peak Battery Hold (SOC-Conditional)

### Problem
Off-peak branch in `energy_battery.py` set reserve to `self.reserve_soc` unconditionally. If SOC is 90%, battery powers the house from stored solar. But off-peak grid costs $0.043/kWh — stored solar is worth more if exported during mid-peak/peak.

### Solution
1. Read `DEFAULT_SOLCAST_TOMORROW_ENTITY` (exists at `energy_const.py:151`, previously never imported by battery strategy)
2. Classify tomorrow's solar using same monthly threshold logic as `classify_solar_day()`
3. Compute drain target based on forecast class (aggressive — off-peak grid at $0.043 is 3.7x cheaper than peak):
   - excellent: 10% (drain aggressively, solar refills tomorrow)
   - good: 15%
   - moderate: 20%
   - poor/very_poor: 30%
   - unknown: 40% (conservative default)
4. If SOC > target: reserve = target (drain stored solar — free energy)
5. If SOC <= target: reserve = SOC (hold, import cheap grid at $0.043/kWh)

### Files Modified
- **`energy_const.py`**: `DEFAULT_OFFPEAK_DRAIN_*` (5 constants), `CONF_ENERGY_OFFPEAK_DRAIN_*` (4 config keys)
- **`energy_battery.py`**: `solcast_tomorrow` property, `classify_tomorrow_solar()`, `_get_offpeak_drain_target()`, off-peak branch rewrite, `_result()` + `get_status()` extended
- **`energy.py`**: Drain config passthrough to `BatteryStrategy.__init__`

### New Sensor Attributes
- `tomorrow_solar_class` on `sensor.ura_energy_battery_decision`

### Tests (7 new)
- SOC 90% + excellent tomorrow → reserve = 10
- SOC 90% + poor tomorrow → reserve = 30
- SOC 30% + good tomorrow → SOC 30 > target 15 → drains to 15
- SOC at target → hold
- Solcast tomorrow unavailable → conservative 40%
- Custom drain targets via config
- Decision includes `tomorrow_solar_class`

---

## Phase B: Grid Charge Arbitrage

### Problem
`charge_from_grid` only activated for storm prep. When tomorrow is poor solar and SOC is low overnight, importing grid at $0.043/kWh off-peak saves vs $0.086-0.162/kWh later.

### Solution
Arbitrage check inserted in off-peak branch BEFORE Phase A drain logic. Conditions:
1. Tomorrow solar = poor or very_poor
2. SOC < arbitrage trigger (default 30%)
3. Off-peak period (implied by branch position)
4. Grid connected (checked earlier in method)
5. NOT storm scenario (storm takes priority — checked earlier)

When triggered: `charge_from_grid=True`, low reserve. Track `_arbitrage_active` state. Stop when SOC reaches target (default 80%).

### Files Modified
- **`energy_const.py`**: `DEFAULT_ARBITRAGE_SOC_TRIGGER` (30), `DEFAULT_ARBITRAGE_SOC_TARGET` (80), `CONF_ENERGY_ARBITRAGE_*` (3 keys)
- **`energy_battery.py`**: `__init__` accepts arbitrage params, off-peak branch has arbitrage check before drain logic, `_result()` + `get_status()` include `arbitrage_active`/`arbitrage_enabled`

### New Sensor Attributes
- `arbitrage_active` boolean on battery decision sensor

### Tests (6 new)
- Poor solar + SOC 20% → charge_from_grid=True
- Good solar + SOC 20% → no arbitrage
- Poor solar + SOC 60% → no arbitrage (above trigger)
- SOC reaches 80% → arbitrage stops
- Storm takes priority over arbitrage
- Arbitrage disabled by config

---

## Phase C: EVSE Refinement

### C1: Never Charge EVs From Battery

**Problem**: EVSEs appear as house load. Battery discharges to cover EV charging during off-peak when grid costs $0.043/kWh.

**Solution**: Cross-cutting concern in `energy.py._async_decision_cycle()`. After battery decision but before action execution:
1. Check if any EVSE is actively charging (power > 100W via `_get_evse_state()`)
2. If yes, override battery reserve to current SOC (hold battery)
3. Append " + EVSE hold" to reason string
4. Track `_evse_battery_hold_active` for sensor visibility

**Why in energy.py, not battery strategy**: Keeps battery strategy single-responsibility. EVSE awareness is a coordinator-level cross-cutting concern, avoids circular dependency between battery and EV controller.

### C2: Excess Solar EVSE Charging

**Problem**: No intelligence about when to charge EVs from excess solar.

**Solution**: `determine_excess_solar_actions()` on `EVChargerController` in `energy_pool.py`:
- Only during off-peak or mid-peak (never peak — battery needed for home load)
- SOC >= 95% AND remaining forecast >= 5.0 kWh → turn on EVSEs
- Conditions no longer met → turn off EVSEs we turned on
- Track `_excess_solar_active: set[str]` (separate from `_paused_by_us`)
- Respects TOU pause priority (won't activate paused EVSEs)

Wired into `energy.py._async_decision_cycle()` after TOU-based EV actions.

### C3: EVSE State Persistence

**Problem**: EVSE paused/excess-solar state lost on HA restart.

**Solution**:
- New `evse_state` table in `database.py` (evse_id, paused_by_energy, excess_solar_active, updated_at)
- `save_evse_state()` called in `async_teardown()`
- `restore_evse_state()` called in `async_setup()`
- Restores `_paused_by_us` and `_excess_solar_active` sets

### Files Modified
- **`energy.py`**: `_is_any_evse_charging()`, `_apply_evse_battery_hold()`, excess solar wiring, `_restore_evse_state()`, `_save_evse_state()`, teardown save, setup restore
- **`energy_pool.py`**: `determine_excess_solar_actions()`, `_excess_solar_active` set, `get_status()` updated
- **`energy_const.py`**: `DEFAULT_EXCESS_SOLAR_SOC_THRESHOLD` (95), `DEFAULT_EXCESS_SOLAR_KWH_THRESHOLD` (5.0), `EVSE_CHARGING_POWER_THRESHOLD` (100), `CONF_ENERGY_EXCESS_SOLAR_*` (3 keys)
- **`database.py`**: `evse_state` table, `save_evse_state()`, `restore_evse_state()`

### New Sensor Attributes
- `evse_battery_hold` boolean on battery decision sensor
- `excess_solar_active` + `excess_solar_evses` on EV status sensor

### Tests (14 new in `test_energy_evse.py`)
- EVSE charging detected / not charging / off
- Excess solar turns on when conditions met
- Not during peak
- Turns off when conditions drop
- Low forecast → no activate
- Custom thresholds
- Only turns off EVSEs it turned on
- Peak turns off active excess solar EVSEs
- Status includes new fields

---

## Phase D1-D2: Energy DB Wiring

### Tables Wired

| Method | Table | Caller | Frequency |
|--------|-------|--------|-----------|
| `log_energy_history()` | energy_history | `energy.py` decision cycle | Every 3rd cycle (~15 min) |
| `log_external_conditions()` | external_conditions | `energy.py` decision cycle | Every 3rd cycle (~15 min) |

### Implementation
- Cycle counter `_cycle_count` incremented each cycle
- Every 3rd cycle (% 3 == 0), fire-and-forget `_log_energy_history_snapshot()` and `_log_external_conditions_snapshot()`
- Data sourced from battery strategy properties and weather entity attributes

### Cleanup
- `cleanup_energy_history(retention_days=180)` called daily in `_maybe_reset_daily()`
- `cleanup_external_conditions(retention_days=90)` called daily
- Both added to `database.py`

---

## Phase E: Simulation Script

**File**: `scripts/energy_simulation.py` (standalone, NOT part of HA integration)

### Purpose
Find optimal setpoints for drain targets, arbitrage thresholds, and EVSE triggers via Monte Carlo simulation with synthetic data.

### Approach
- Imports `PEC_TOU_RATES` and `SOLAR_MONTHLY_THRESHOLDS` from `energy_const.py` (via `importlib.util` to bypass HA dependencies)
- 365 days × 24 hours synthetic data: solar (monthly distribution), temperature (Raleigh NC sine curve), consumption (30 kWh/day + temp regression), EV sessions (Poisson)
- Battery: 40 kWh, 95% round-trip efficiency
- 1000 Monte Carlo trials sampling 8 parameters
- Output: markdown report with optimal values, sensitivity analysis, cost comparison

---

## Phase F: Energy Management Explainer

**File**: `docs/ENERGY_MANAGEMENT_EXPLAINER.md`

Comprehensive technical reference covering:
1. System hardware and capabilities
2. Control levers and Enphase constraints
3. PEC TOU rate structure (all 3 seasons)
4. Per-season battery strategy including v3.11.0 drain + arbitrage
5. Battery-EV interaction and EVSE hold
6. Export economics
7. Cost tracking and billing
8. Forecast integration
9. Load shedding cascade
10. Decision cycle flow and DB tables

---

## Test Summary

| File | New Tests | Total |
|------|-----------|-------|
| `test_energy_battery.py` | +26 | 49 |
| `test_energy_evse.py` | +21 (new file) | 21 |
| Other (D3-D7 wiring) | +67 | — |
| **Suite total** | +114 | **938** |

## Review Findings Fixed

Three parallel staff-level reviews identified and fixed:
- **H1**: `total_consumption_kw` (watts) stored without /1000 conversion — fixed
- **H1 (R3)**: `arbitrage_enabled` missing from `_result()` decision dict — added
- **M1**: `very_poor` drain target read from wrong dict key — fixed
- **M2 (R3)**: Envoy-unavailable path omitted `tomorrow_solar_class`, `arbitrage_active`, `reserve_soc` — added
- **M3**: Off-peak branch fallthrough without explicit guard — added warning for unexpected period
- **M3 (R3)**: `_log_person_room_change` lacked top-level try/except — wrapped
- **M4**: External conditions snapshot omitted `occupied_room_count`/`occupied_zone_count` — added
- **M4 (R3)**: `get_energy_summary()` missing `evse_battery_hold` — added
- **M5/M6**: Cleanup methods used `datetime.now()` vs UTC — fixed to `dt_util.utcnow()`
- **M7**: EVSE IDs not validated on restore — added validation against current config
- **M8**: EVSE hold ratcheted reserve down each cycle — now captures SOC at hold start
- **M8 (R1)**: Unused `BATTERY_MODE_SAVINGS` import — removed
- **M9**: Peak excess-solar turn-off didn't check if EVSE already off — added state check
- **L3**: `EVSE_CHARGING_POWER_THRESHOLD` constant unused — now used in energy_pool.py
- **L5**: Redundant `classify_tomorrow_solar()` call in `_result()` — removed
- **L7**: No diagnostic logging for excess solar conditions — added debug log

### Deferred to Follow-Up
- Config flow UI for 10 new CONF keys (arbitrage, drain targets, excess solar) — features default to safe values. Advanced EVSE management (excess solar, battery hold) should be a toggle with configurable thresholds in the UI.
- Strings/translations sync for v3.9.0 load shedding keys (pre-existing, not v3.11.0)
- Savings mode exploration — see `docs/PLANNING_FUTURE_ENERGY_SAVINGS_MODE.md`

---

## Critical Files

| File | Phases | Role |
|------|--------|------|
| `domain_coordinators/energy_battery.py` | A, B | Off-peak drain, arbitrage, tomorrow solar classification |
| `domain_coordinators/energy.py` | A, B, C, D | Decision cycle orchestrator, EVSE hold, DB logging, state persistence |
| `domain_coordinators/energy_pool.py` | C | Excess solar EVSE logic |
| `domain_coordinators/energy_const.py` | A, B, C | All new constants |
| `database.py` | C, D | EVSE state table, cleanup methods |
| `sensor.py` | — | Existing sensors surface new attributes via `battery_decision_status` dict |
