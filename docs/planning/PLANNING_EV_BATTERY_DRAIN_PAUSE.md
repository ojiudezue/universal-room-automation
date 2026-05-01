# Cycle A: EV Battery Drain Auto-Pause

**Risk: LOW** — Small scope, well-understood code, existing patterns, easily reversible.

## Context

When the EV is plugged in during evening/night, the charger draws power that drains the Enphase battery instead of (or in addition to) pulling from the grid. The user manually pauses charging via the Emporia app. URA has TOU-based pause/resume and grid import cap, but no battery-drain-aware pause.

## Current EV Control Architecture

`EVChargerManager` in `energy_pool.py` handles two chargers:
- Garage A: `switch.garage_a` + `sensor.garage_a_power_minute_average`
- Garage B: `switch.garage_b` + `sensor.garage_b_power_minute_average`

Existing pause reasons tracked via sets:
- `_paused_by_us` — TOU pause (peak/mid-peak)
- `_paused_by_grid_cap` — grid import cap exceeded
- `_excess_solar_active` — excess solar charging override

Charging detection: `power > EVSE_CHARGING_POWER_THRESHOLD` (100W)

## Deliverable

### D1: Battery Drain Detection + Auto-Pause

Detect: EV charger drawing power AND battery is discharging AND SOC below configurable threshold.

**Inputs:**
- `sensor.garage_a_power_minute_average` > 100W (already read by `_get_evse_state`)
- Battery power < 0 (discharging) — from `self._battery.battery_power`
- Battery SOC < threshold — from `self._battery.battery_soc`

**Action:** `switch.turn_off` on the charger switch.

**Resume conditions (any of):**
- Battery stops discharging (battery_power >= 0)
- Battery SOC rises above threshold + 5% hysteresis
- Next off-peak TOU window starts (grid power is cheap, drain is acceptable)
- Manual turn-on detected (user override — clear pause, don't re-pause for 1 hour cooldown)

**New tracking set:** `_paused_by_battery_drain: set[str]`

**New method:** `determine_battery_drain_actions(battery_power, battery_soc, soc_threshold, tou_period)`

**Integration point:** Called from `EnergyCoordinator._async_update_data()` after existing `determine_actions()` and `determine_grid_cap_actions()`. Battery drain pause takes priority over TOU resume (same pattern as grid cap).

### Acceptance Criteria
- **Verify:** EV plugged in + battery discharging + SOC < 50% → charger turns off within one decision cycle (~5 min)
- **Verify:** Battery stops discharging → charger turns back on within one decision cycle
- **Verify:** Manual turn-on during pause → 1 hour cooldown, no re-pause
- **Verify:** Off-peak TOU → resume even if battery still draining (grid power is cheap)
- **Verify:** Grid cap pause takes priority over battery drain resume
- **Sensor:** Battery drain pause reason visible in EVSE status sensor attributes
- **Test:** Unit tests for all pause/resume transitions

### D2: Config Flow

Add to energy coordinator options step:
- `CONF_ENERGY_EV_BATTERY_DRAIN_SOC_THRESHOLD` (number, default 50%, range 10-90%)
- Use existing EVSE entity config — no new entity pickers needed

### Acceptance Criteria
- **Verify:** Threshold configurable via UI, takes effect on next decision cycle
- **Verify:** Default 50% when not configured

## Files Modified

| File | Changes |
|------|---------|
| `energy_pool.py` | `_paused_by_battery_drain` set, `determine_battery_drain_actions()` method, resume logic with hysteresis + cooldown |
| `energy.py` | Call `determine_battery_drain_actions()` in decision cycle, pass battery state |
| `energy_const.py` | `CONF_ENERGY_EV_BATTERY_DRAIN_SOC_THRESHOLD`, default constant |
| `config_flow.py` | SOC threshold number input in energy step |
| `strings.json` + `translations/en.json` | Label for threshold |

## Risk Assessment

**LOW risk because:**
- Follows exact pattern of existing `_paused_by_grid_cap` (same code shape, same tracking set, same priority logic)
- Only adds a new pause reason — doesn't modify existing TOU or grid cap logic
- Easily testable: plug in EV, watch battery SOC, verify pause/resume
- Reversible: disable via toggle (EV TOU management switch already exists) or set threshold to 10%
- No DB changes, no new sensors (uses existing EVSE status attributes), no new entities beyond the config threshold
