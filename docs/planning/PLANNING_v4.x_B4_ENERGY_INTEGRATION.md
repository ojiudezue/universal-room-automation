# B4: Bayesian Energy Integration — Implementation Plan

**Status:** Draft
**Target:** v4.x (next after current work)
**Depends on:** B1+B2 deployed (done). B3 is independent — deferred to backlog.
**Scope:** 3 layers, ~700 lines production code

## Problem Statement

`DailyEnergyPredictor` estimates consumption using three signals: historical DOW
baseline, temperature regression, and an accuracy adjustment factor. It has **zero
occupancy awareness**. A 5-bedroom house at 2 PM on a workday predicts the same
consumption as a fully-occupied Saturday — the model cannot distinguish.

Additionally, the room-level energy configuration has a gap: `CONF_POWER_SENSORS`
accepts multiple sensors (Shelly plugs, Emporia circuits, SPAN panels) but
`CONF_ENERGY_SENSOR` accepts only one. Rooms with multiple metered circuits can
track power in real time but lose fidelity on cumulative energy.

## Architecture Overview

Three layers, each independently deployable:

```
Layer 1: Config + Data Foundation
  ├── Multi-energy sensor config flow (room, zone, house, whole-house)
  ├── 4-tier energy attribution model + unattributed delta upgrade
  ├── Room power profile learning (time-bin baselines + learned standby)
  └── Room coordinator energy tracking update

Layer 2: Occupancy-Weighted Prediction (toggle-gated, off by default)
  ├── Toggle: CONF_OCCUPANCY_WEIGHTED_ENERGY on Energy Coordinator device
  ├── DailyEnergyPredictor Bayesian integration
  ├── Per-room weighted consumption calculation
  └── Battery strategy occupancy awareness

Layer 3: Energy Intelligence Sensors
  ├── EnergyWasteIdleSensor
  ├── EnergyCostPerOccupiedHourSensor
  ├── EnergyAnomalyBinarySensor
  ├── MostExpensiveDeviceSensor (circuit-level)
  ├── OptimizationPotentialSensor (simple idle-waste version)
  └── OptimizeNowButton (deferred to Optimizer P4)
```

## Layer 1: Config + Data Foundation (~300 lines)

**Why first:** Layers 2 and 3 need room-level power profiles and multi-sensor
energy data. Without this, occupancy weighting has no per-room baseline to weight.

### D1: Multi-Energy Sensor Config Flow

Expand `CONF_ENERGY_SENSOR` to accept multiple sensors, matching `CONF_POWER_SENSORS`.

**Current (config_flow.py:1697):**
```python
vol.Optional(CONF_ENERGY_SENSOR, ...):
    selector.EntitySelector(
        selector.EntitySelectorConfig(domain="sensor", device_class="energy")
    ),
```

**Target:**
```python
vol.Optional(CONF_ENERGY_SENSORS, ...):
    selector.EntitySelector(
        selector.EntitySelectorConfig(domain="sensor", device_class="energy", multiple=True)
    ),
```

**Migration:** Read old `CONF_ENERGY_SENSOR` (singular) and wrap in list for
backward compatibility. New config key: `CONF_ENERGY_SENSORS` (plural).

**Files changed:**
- `const.py`: Add `CONF_ENERGY_SENSORS`
- `config_flow.py`: Update selector, add migration from singular → plural
- `coordinator.py`: Update energy tracking to sum multiple energy sensors

**Acceptance Criteria:**
- **Verify:** Existing single-sensor configs auto-migrate to list on reload
- **Verify:** Config flow shows multi-select picker for energy sensors
- **Verify:** `STATE_ENERGY_TODAY` sums deltas from all configured energy sensors
- **Test:** Migration from singular to plural, multi-sensor summation
- **Live:** Room with 2 Emporia circuits shows correct summed energy

### D1b: Zone and House Power/Energy Sensor Config

Add power/energy sensor pickers to Zone Manager and Coordinator Manager config entries.

**Zone Manager entry — new fields:**
```python
vol.Optional(CONF_ZONE_POWER_SENSORS): selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", device_class="power", multiple=True)
),
vol.Optional(CONF_ZONE_ENERGY_SENSORS): selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", device_class="energy", multiple=True)
),
```

Typical zone sensors: HVAC circuit CT (Emporia/SPAN), zone subpanel meter.

**Coordinator Manager entry — new fields (house-level devices):**
```python
vol.Optional(CONF_HOUSE_DEVICE_POWER_SENSORS): selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", device_class="power", multiple=True)
),
vol.Optional(CONF_HOUSE_DEVICE_ENERGY_SENSORS): selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", device_class="energy", multiple=True)
),
```

Typical house sensors: EV charger CT, pool pump power, water heater circuit.
These are devices not attributable to any room or zone.

**Also upgrade existing whole-house sensors to multiple:**
`CONF_WHOLE_HOUSE_POWER_SENSOR` → `CONF_WHOLE_HOUSE_POWER_SENSORS` (plural, `multiple=True`)
`CONF_WHOLE_HOUSE_ENERGY_SENSOR` → `CONF_WHOLE_HOUSE_ENERGY_SENSORS` (plural, `multiple=True`)
Migration: wrap existing singular values in list, same as D1 room energy migration.

This gives three tiers of attribution:
```
Whole House (sum of whole-house sensors)
  ├── Rooms (sum of all room power/energy sensors)
  ├── Zones (sum of zone power/energy sensors — HVAC, subpanels)
  ├── House Devices (sum of house device sensors — EV, pool, water heater)
  └── Unattributed Delta (whole house - rooms - zones - house devices)
```

**Files changed:**
- `const.py`: Add `CONF_ZONE_POWER_SENSORS`, `CONF_ZONE_ENERGY_SENSORS`,
  `CONF_HOUSE_DEVICE_POWER_SENSORS`, `CONF_HOUSE_DEVICE_ENERGY_SENSORS`,
  `CONF_WHOLE_HOUSE_POWER_SENSORS`, `CONF_WHOLE_HOUSE_ENERGY_SENSORS`
- `config_flow.py`: Add selectors to zone manager and coordinator manager options
  steps + migration for whole-house singular → plural
- `strings.json` / `translations/en.json`: Labels and descriptions

**Acceptance Criteria:**
- **Verify:** Zone Manager options show power/energy sensor pickers
- **Verify:** Coordinator Manager options show house device sensor pickers
- **Verify:** Whole-house sensors accept multiple (backward-compatible migration)
- **Test:** Migration from singular to plural for whole-house sensors
- **Live:** Configure HVAC circuit on zone, EV charger on house — both show in UI

### D1c: Energy Attribution Model + Unattributed Delta Upgrade

Upgrade existing `sensor.ura_energy_coverage_delta` from informational display to
a load attribution model that B4 Layer 2 consumes.

**Current state:** Coverage delta sensor already computes `whole_house - rooms_total`
with `delta_percent` and `coverage_rating` attributes (`aggregation.py:2060-2131`).

**Upgrade:**
1. Expand delta calculation to include zone and house device tiers:
   ```
   unattributed = whole_house - rooms_total - zones_total - house_devices_total
   ```
2. Learn unattributed load profile by time bin (same EMA as room profiles).
   The unattributed load has a shape — HVAC peaks midday in summer, evening in
   winter. Learning this lets the prediction model account for it.
3. Add attribution breakdown to sensor attributes:
   ```
   rooms_total, zones_total, house_devices_total, unattributed,
   attribution_coverage_pct, unattributed_profile (by time bin)
   ```
4. Flag poor coverage as a diagnostic finding:
   - `coverage_rating`: "excellent" (>90%), "good" (75-90%), "fair" (50-75%), "poor" (<50%)
   - When "poor": attribute includes recommendation to configure more sensors

**Failsafe role in Layer 2:** The occupancy-weighted prediction sums:
```
predicted_daily = room_weighted + zone_weighted + house_devices + unattributed_profile
```
If zone/house sensors aren't configured, `unattributed` absorbs everything not
room-attributed. As sensors are added, unattributed shrinks and explicit attribution
takes over. The whole-house sensor is the anchor — the sum of all tiers should
approximate it. If they diverge by >15%, log a warning and fall back to the
whole-house-based estimate.

**Cross-check (the "what if they don't tally" answer):**
- `attributed_total = rooms + zones + house_devices`
- `expected = whole_house`
- `divergence = abs(attributed_total + unattributed - expected) / expected`
- If divergence < 5%: normal (sensor timing/rounding)
- If divergence 5-15%: attribute `attribution_drift` on sensor, log INFO
- If divergence > 15%: log WARNING, add `attribution_warning` attribute,
  fall back to whole-house-only prediction for that cycle. This catches:
  - Stale/unavailable sensors
  - Double-counted circuits (e.g., room sensor on a circuit also in zone meter)
  - Whole-house sensor misconfiguration

**Acceptance Criteria:**
- **Verify:** Attribution breakdown shows all 4 tiers when configured
- **Verify:** Unattributed delta shrinks as zone/house sensors are added
- **Verify:** Unattributed profile learned by time bin after 24h
- **Verify:** Divergence >15% triggers warning and fallback
- **Test:** Attribution with all tiers configured, with gaps, divergence handling
- **Live:** Check delta sensor attributes after configuring zone HVAC sensor

### D2: Room Power Profile Learning

Learn per-room average power by time bin and day type. Uses existing
`STATE_POWER_CURRENT` (already updated every 30s in coordinator Phase 2).

**New class in `energy_forecast.py`:**

```python
class RoomPowerProfile:
    """Learns room power baselines by time bin and day type.

    Stores exponential moving average of room power per (time_bin, day_type).
    Updated from room coordinator data during energy coordinator cycles.
    """

    def __init__(self) -> None:
        # {room_id: {(time_bin, day_type): {"avg_watts": float, "samples": int}}}
        self._profiles: dict[str, dict[tuple[int, int], dict]] = {}

    def update(self, room_id: str, time_bin: int, day_type: int,
               current_watts: float) -> None:
        """Update EMA for room/bin/day_type."""

    def get_baseline_watts(self, room_id: str, time_bin: int,
                           day_type: int) -> float | None:
        """Return learned baseline watts, or None if insufficient data."""

    def get_all_baselines(self) -> dict:
        """Return full profile dict for DB persistence."""
```

**Data source:** Room coordinator already computes:
```python
# coordinator.py ~line 1420
total_power = sum(self._get_sensor_value(sensor, 0) for sensor in power_sensors)
data[STATE_POWER_CURRENT] = total_power
```

Energy coordinator reads this during its 5-minute cycle across all rooms.

**DB persistence:** New table `room_power_profiles` with columns:
`room_id, time_bin, day_type, avg_watts, sample_count, updated_at`

**Acceptance Criteria:**
- **Verify:** After 24h, each room has baselines for 6 time bins × 2 day types
- **Verify:** EMA converges (not volatile) after 50+ samples per cell
- **Test:** EMA calculation, cold start (no data), DB save/restore round-trip
- **Live:** Query `room_power_profiles` via MCP after 24h of operation

### D3: Device State Context (informational, not predictive)

The room coordinator already tracks device counts:
- `STATE_LIGHTS_ON_COUNT`, `STATE_FANS_ON_COUNT`, `STATE_SWITCHES_ON_COUNT`

These are **not** used for power prediction in Layer 1 — the power sensors measure
actual draw. But they provide context for Layer 3 sensors (e.g., "room drawing 800W
with 0 devices on" is anomalous vs "room drawing 800W with HVAC + 3 lights" is normal).

**No code changes needed** — existing state keys are sufficient. Document the
dependency for Layer 3.

---

## Layer 2: Occupancy-Weighted Prediction (~220 lines)

**Depends on:** Layer 1 (room power profiles) + B1/B2 (BayesianPredictor)
**Gated by:** `CONF_OCCUPANCY_WEIGHTED_ENERGY` toggle (off by default)

### D3b: Occupancy Weighting Toggle (config flow + switch entity)

**Config key:** `CONF_OCCUPANCY_WEIGHTED_ENERGY` (boolean, default `False`)
**Entity:** `switch.ura_energy_occupancy_weighted_prediction`
**Device:** URA: Energy Coordinator
**Entity category:** `config`

Both config flow and a live switch — config flow sets the initial value on setup,
switch provides runtime control without reconfiguration. Same dual pattern as
`fan_control_enabled` on room devices (config flow option + switch entity).

**Behavior:**
- Config flow sets the initial state when the integration is configured
- Switch entity reflects and overrides the current state at runtime
- Switch state syncs back to config entry on toggle (options listener)
- Config flow change updates the switch state

When OFF:
- Power profile learning (Layer 1) still runs — data accumulates passively
- `_estimate_consumption()` skips occupancy blend entirely (zero runtime cost)
- Battery strategy uses flat consumption curve (existing behavior)
- Layer 3 sensors that depend only on presence + power still work (D6, D7, D9)
- Layer 3 sensors that require Bayesian (D8 EnergyAnomaly) show "unavailable"

When ON:
- Occupancy blend activates in `_estimate_consumption()`
- Battery strategy uses occupancy-shaped consumption curve
- All Layer 3 sensors fully functional

**Files changed:**
- `const.py`: Add `CONF_OCCUPANCY_WEIGHTED_ENERGY`
- `config_flow.py`: Add toggle to energy coordinator options step
- `switch.py`: New `OccupancyWeightedPredictionSwitch` class (~30 lines)
- `energy.py`: Read switch state, gate occupancy blend in DailyEnergyPredictor
- `strings.json` / `translations/en.json`: Toggle label + description

**Acceptance Criteria:**
- **Verify:** Toggle visible in Energy Coordinator options flow (default OFF)
- **Verify:** Switch appears on Energy Coordinator device card in HA UI
- **Verify:** Flipping switch updates config entry; changing config flow updates switch
- **Verify:** Toggling ON/OFF takes effect on next energy coordinator cycle (no reload)
- **Verify:** When OFF, `predicted_consumption_kwh` matches pre-B4 behavior exactly
- **Verify:** When ON, prediction differs from baseline (weekday vs weekend)
- **Test:** Toggle on/off via switch, config flow sync, graceful degradation
- **Live:** Flip switch in HA dashboard, observe prediction change within 5 minutes

### D4: DailyEnergyPredictor Bayesian Integration

Extend `_estimate_consumption()` to accept an occupancy-weighted estimate from
BayesianPredictor and blend it with existing regression/historical estimates.

**Current flow:**
```
DOW baseline → temperature regression → adjustment factor → consumption estimate
```

**New flow:**
```
DOW baseline → temperature regression → occupancy weighting → adjustment factor → estimate
                                              ↑
                                    BayesianPredictor.predict_room_occupancy()
                                              +
                                    RoomPowerProfile.get_baseline_watts()
```

**Integration point in `_estimate_consumption()`:**
```python
def _estimate_consumption(self, now: datetime, temp: float | None) -> float:
    # ... existing regression/fallback logic produces `adjusted` ...

    # NEW: Occupancy-weighted estimate (gated by switch entity, off by default)
    if self._is_occupancy_weighting_enabled() and self._bayesian_predictor and self._power_profiles:
        occupancy_estimate = self._occupancy_weighted_estimate(now)
        if occupancy_estimate is not None:
            # Blend: existing estimate 60%, occupancy-weighted 40%
            # Ratio shifts as occupancy model matures (more ACTIVE cells → higher weight)
            weight = self._occupancy_blend_weight()
            adjusted = adjusted * (1 - weight) + occupancy_estimate * weight

    return max(0.1, adjusted * self._adjustment_factor)
```

**Occupancy weighting calculation:**
```python
def _occupancy_weighted_estimate(self, now: datetime) -> float | None:
    """Sum occupancy-weighted load across all attribution tiers."""
    day_type = 1 if now.weekday() >= 5 else 0
    rooms_kwh = 0.0
    rooms_with_data = 0

    # Tier 1: Room loads (occupancy-weighted)
    for room_id in self._room_ids:
        for time_bin in range(6):
            hours_in_bin = BIN_HOURS[time_bin]
            baseline_w = self._power_profiles.get_baseline_watts(
                room_id, time_bin, day_type)
            if baseline_w is None:
                continue

            p_occupied = self._bayesian_predictor.predict_room_occupancy(
                room_id, time_bin, day_type)

            # Standby learned from NIGHT-bin vacant data (D2), not hardcoded
            standby_w = self._power_profiles.get_standby_watts(room_id) or 0
            weighted_w = standby_w + (baseline_w - standby_w) * p_occupied
            rooms_kwh += weighted_w * hours_in_bin / 1000.0
            rooms_with_data += 1

    if rooms_with_data < 3:
        return None  # Not enough room data

    # Tier 2: Zone loads (from zone power profiles, not occupancy-weighted)
    zones_kwh = self._attribution.get_zones_daily_estimate(day_type)

    # Tier 3: House device loads (schedule-driven, not occupancy-weighted)
    house_devices_kwh = self._attribution.get_house_devices_daily_estimate(day_type)

    # Tier 4: Unattributed load (learned profile by time bin)
    unattributed_kwh = self._attribution.get_unattributed_daily_estimate(day_type)

    total = rooms_kwh + zones_kwh + house_devices_kwh + unattributed_kwh

    # Cross-check against whole-house profile
    whole_house_estimate = self._attribution.get_whole_house_daily_estimate(day_type)
    if whole_house_estimate and whole_house_estimate > 0:
        divergence = abs(total - whole_house_estimate) / whole_house_estimate
        if divergence > 0.15:
            _LOGGER.warning(
                "Attribution divergence %.0f%% — falling back to whole-house estimate",
                divergence * 100)
            return whole_house_estimate

    return total
```

**Blend weight (adaptive):**
```python
def _occupancy_blend_weight(self) -> float:
    """Higher weight when more Bayesian cells are ACTIVE."""
    # Count ACTIVE cells across all rooms
    active_cells = self._bayesian_predictor.count_active_cells()
    total_cells = self._bayesian_predictor.count_total_cells()
    if total_cells == 0:
        return 0.0
    maturity = active_cells / total_cells
    # Scale from 0.0 (no active cells) to 0.4 (all active)
    return min(0.4, maturity * 0.5)
```

**Files changed:**
- `energy_forecast.py`: `DailyEnergyPredictor.__init__()` accepts optional
  `bayesian_predictor` and `power_profiles` params
- `energy.py`: Pass BayesianPredictor ref from `hass.data[DOMAIN]` during setup
- `energy_forecast.py`: `_occupancy_weighted_estimate()`, `_occupancy_blend_weight()`

**Acceptance Criteria:**
- **Verify:** With Bayesian at ACTIVE + profiles populated, consumption estimate differs from non-occupancy baseline
- **Verify:** Blend weight scales with Bayesian maturity (0% at INSUFFICIENT, 40% at full ACTIVE)
- **Verify:** Prediction falls back gracefully when Bayesian not available
- **Verify:** Standby fraction (15%) prevents zero-consumption rooms from being invisible
- **Test:** Occupancy weighting with mock profiles, blend weight scaling, graceful degradation
- **Live:** Compare `predicted_consumption_kwh` before/after B4 enable — should differ on weekday vs weekend

### D5: Battery Strategy Occupancy Awareness

Extend `_estimate_battery_full_time()` to use occupancy-weighted consumption drain
instead of flat `daily_consumption * (hours_left / 24)`.

**Current (line 293):**
```python
remaining_consumption = daily_consumption * (hours_left / 24.0)
```

**Target:** Use remaining time bins' occupancy-weighted consumption:
```python
remaining_consumption = self._remaining_occupancy_weighted_consumption(now)
```

This accounts for "afternoon will be low-occupancy (everyone at work)" vs
"evening will be high-occupancy (family home)" — shifting the consumption curve
instead of assuming flat distribution.

**Acceptance Criteria:**
- **Verify:** Battery full time estimate changes based on predicted occupancy curve
- **Verify:** Fallback to flat estimate when occupancy data unavailable
- **Test:** Compare battery estimate with/without occupancy curve (mock data)
- **Live:** Battery full time should be earlier on high-occupancy days, later on low

---

## Layer 3: Energy Intelligence Sensors (~180 lines)

**Depends on:** Layer 1 (power profiles + presence state) for most sensors.
D8 (EnergyAnomaly) additionally requires Bayesian + L2 toggle ON.

### D6: EnergyWasteIdleSensor (per room)

**Entity:** `sensor.{room}_energy_waste_idle_kwh`
**State:** kWh consumed while room was vacant today
**Device class:** energy
**Disabled by default:** Yes

Calculation: For each 30s coordinator cycle where room is unoccupied, accumulate
`STATE_POWER_CURRENT * elapsed_hours / 1000`. Reset at midnight.

**Acceptance Criteria:**
- **Verify:** Accumulates only when room presence is OFF
- **Verify:** Resets at midnight
- **Sensor:** Shows kWh with 2 decimal places
- **Test:** Accumulation logic, midnight reset, zero when always occupied

### D7: EnergyCostPerOccupiedHourSensor (per room)

**Entity:** `sensor.{room}_energy_cost_per_occupied_hour`
**State:** $/hour (energy cost while occupied)
**Disabled by default:** Yes

Calculation: `STATE_ENERGY_TODAY / occupied_hours_today * electricity_rate`.
Uses room's configured electricity rate or integration default.

**Acceptance Criteria:**
- **Verify:** Updates as energy and occupied time accumulate through the day
- **Verify:** Handles division by zero (room never occupied → "unknown")
- **Sensor:** Shows cost with 2 decimal places, unit_of_measurement = "USD/h"
- **Test:** Normal calculation, zero-occupied-hours edge case

### D8: EnergyAnomalyBinarySensor (per room)

**Entity:** `binary_sensor.{room}_energy_anomaly`
**State:** ON when room draws significant power while vacant and Bayesian predicts
low occupancy (P < 10%)
**Disabled by default:** Yes

Trigger conditions (ALL must be true):
1. Room presence is OFF (vacant)
2. `STATE_POWER_CURRENT` > 200W (significant draw, not standby)
3. BayesianPredictor P(occupied) < 0.10 for current time bin
4. Learning status is ACTIVE (sufficient data)
5. Duration > 15 minutes (debounce)
6. Not in GUEST house state

Fires `SIGNAL_ENERGY_ANOMALY` for NM integration.

**Acceptance Criteria:**
- **Verify:** Does not fire for normal standby (<200W)
- **Verify:** Does not fire when Bayesian insufficient data
- **Verify:** Guest mode suppression works
- **Verify:** 15-minute debounce prevents transient alerts
- **Test:** All trigger conditions, suppression paths
- **Live:** Manually leave a high-draw device on in vacant room, check alert

### D9: MostExpensiveDeviceSensor (per room, circuit-level)

**Entity:** `sensor.{room}_most_expensive_circuit`
**State:** Name of highest-cost power sensor in room (by TOU-weighted draw)
**Disabled by default:** Yes

**Requires:** Multiple `CONF_POWER_SENSORS` configured (otherwise "unknown").
Ranks each power sensor by `current_watts * current_tou_rate` and reports the top one.

This is the closest to "device awareness" without requiring device-type mapping.
Each power sensor typically corresponds to a circuit or plug — the entity name
carries the device identity (e.g., `sensor.study_a_tv_plug_power`).

**Attributes:**
- `sensors_ranked`: list of `{entity_id, watts, hourly_cost}` sorted descending
- `tou_period`: current TOU period used for cost calculation

**Acceptance Criteria:**
- **Verify:** Ranks by TOU-weighted cost, not raw watts
- **Verify:** Returns "unknown" when room has 0-1 power sensors
- **Sensor:** Updates every coordinator cycle (30s)
- **Test:** Ranking with mock TOU rates, single-sensor edge case

### D10: OptimizationPotentialSensor (per room)

**Entity:** `sensor.{room}_optimization_potential`
**State:** Estimated monthly savings (USD) from reducing idle power waste
**Disabled by default:** Yes

**Simple calculation (B4 version):**
```python
avg_daily_idle_kwh = rolling_7day_avg(energy_waste_idle_kwh)
monthly_savings = avg_daily_idle_kwh * 30 * electricity_rate
```

Derives directly from D6 (EnergyWasteIdleSensor) data. No rule engine needed.

**Attributes:**
- `avg_daily_idle_kwh`: 7-day rolling average
- `monthly_estimate_kwh`: projected monthly idle waste
- `electricity_rate`: rate used for calculation
- `confidence`: "low" (<7 days data), "medium" (7-30 days), "high" (30+ days)

**Upgrade path:** Optimizer Phase 4 replaces this with a multi-dimensional version
that considers HVAC scheduling, TOU shifting, and device automation — not just
idle waste. The entity_id and unique_id stay the same; the Optimizer enhances
the calculation and adds recommendations to the attributes.

**Acceptance Criteria:**
- **Verify:** Shows $0.00 when room has no idle waste
- **Verify:** Confidence attribute reflects data maturity
- **Verify:** Uses room-specific electricity rate, falls back to integration default
- **Test:** Calculation with mock 7-day data, confidence transitions
- **Live:** Room with known idle draw shows reasonable monthly estimate

### D11: OptimizeNowButton

**Deferred to Optimizer Phase 4.** Not part of B4 scope — requires rule engine
infrastructure that doesn't exist yet.

---

## Deferred Entity Updates

| Entity | Original Target | Updated Target | Reason |
|--------|----------------|----------------|--------|
| EnergyWasteIdleSensor | B4 or Optimizer P1 | B4 Layer 3 (D6) | Has all deps in B4 |
| MostExpensiveDeviceSensor | B4 | B4 Layer 3 (D9) | Circuit-level, not device-level |
| OptimizationPotentialSensor | Optimizer P4 | B4 Layer 3 (D10) — simple idle-waste version | Optimizer P4 enhances with multi-dimensional recommendations |
| EnergyCostPerOccupiedHourSensor | B4 | B4 Layer 3 (D7) | Has all deps in B4 |
| EnergyAnomalyBinarySensor | B4 or Optimizer | B4 Layer 3 (D8) | Bayesian + power profiles |
| OptimizeNowButton | Optimizer P4 | Optimizer P4 | Needs rule engine |

---

## Dependency Chain

```
B1 (done) ──→ B2 (done) ──→ B4
                              │
                    B3 (backlog, independent — no B4 dependency)
```

**B4 does NOT depend on B3.** B3 (pre-emptive actions) is an independent feature
in the backlog. B4 only needs B1+B2 (done) for Bayesian data.

**Layer dependencies within B4:**
```
B4-L1 (config + profiles) ──→ B4-L2 (occupancy weighting, toggle-gated) ──→ B4-L3 (sensors)
         ↑                              ↑
    no Bayesian dep              B1+B2 (done) + toggle ON
```

**Layer 1** can ship immediately — no Bayesian dependency:
- Multi-energy config flow is a standalone fix
- Power profile learning only needs room coordinator data (exists)

**Layer 2** needs L1 (power profiles) + B1/B2 (Bayesian). Both are available.
Toggle defaults to OFF — users enable when ready.

**Layer 3 sensor dependencies vary:**
- D6 (WasteIdle), D7 (CostPerHour), D9 (MostExpensive), D10 (OptPotential):
  Only need power profiles + presence state. Work regardless of L2 toggle.
- D8 (EnergyAnomaly): Needs Bayesian — shows "unavailable" when toggle OFF.

---

## File Changes Summary

| File | Layer | Action | Description |
|------|-------|--------|-------------|
| `const.py` | L1+L2 | MODIFY | `CONF_ENERGY_SENSORS`, zone/house sensor consts, `CONF_OCCUPANCY_WEIGHTED_ENERGY`, whole-house plural |
| `config_flow.py` | L1+L2 | MODIFY | Multi-select pickers (room energy, zone, house device, whole-house plural), toggle, migrations |
| `switch.py` | L2 | MODIFY | `OccupancyWeightedPredictionSwitch` on Energy Coordinator device (~30 lines) |
| `coordinator.py` | L1 | MODIFY | Sum multiple energy sensors per room |
| `energy_forecast.py` | L1+L2 | MODIFY | RoomPowerProfile + attribution model + occupancy weighting |
| `energy.py` | L2 | MODIFY | Read toggle, pass Bayesian ref, profile/attribution updates |
| `aggregation.py` | L1 | MODIFY | Upgrade coverage delta sensor with 4-tier attribution breakdown |
| `database.py` | L1 | MODIFY | `room_power_profiles` table + save/load |
| `sensor.py` | L3 | MODIFY | 4 new sensor classes (~120 lines) |
| `binary_sensor.py` | L3 | MODIFY | EnergyAnomalyBinarySensor (~40 lines) |
| `strings.json` | L1+L2 | MODIFY | Zone/house sensor labels, toggle label |
| `translations/en.json` | L1+L2 | MODIFY | Zone/house sensor labels, toggle label |

**Estimated total:** ~700 lines production code across 3 layers

---

## What B4 Does NOT Do

- Replace DailyEnergyPredictor (extends it)
- Require per-device power mapping (uses aggregate room sensors + circuit names)
- Build a rule engine (deferred to Optimizer Phase 4)
- Add LLM-assisted optimization (deferred to Optimizer Phase 5)
- Predict future device state (only correlates occupancy with learned power baselines)
- Change existing energy TOU, battery, or load shedding logic (only improves inputs)

## Resolved Design Decisions

1. **Standby fraction** — RESOLVED: Learn from overnight vacant-room power data.
   RoomPowerProfile stores NIGHT-bin vacant average as `get_standby_watts(room_id)`.
   No hardcoded 15%. Rooms with servers/aquariums naturally get higher standby. (~30 lines)

2. **HVAC / house device attribution** — RESOLVED: Full config flow for both.
   - Zone Manager gets `CONF_ZONE_POWER_SENSORS` / `CONF_ZONE_ENERGY_SENSORS` (HVAC circuits)
   - Coordinator Manager gets `CONF_HOUSE_DEVICE_POWER_SENSORS` / `CONF_HOUSE_DEVICE_ENERGY_SENSORS` (EV, pool, water heater)
   - Whole-house sensors upgraded to `multiple=True`
   - Coverage delta upgraded to 4-tier attribution model with divergence cross-check
   - See D1b and D1c for full spec.

3. **Power profile cold start** — RESOLVED: `MIN_SAMPLES_PER_CELL = 20` (~10 days
   of data per time bin). Layer 2 skips rooms below this threshold.

4. **TOU interaction** — RESOLVED: kWh is the primary prediction unit. TOU cost
   included as an optional attribute on prediction output (not in core
   `_estimate_consumption()` return). Load shedding operates on real-time power
   thresholds — different time horizon, complementary not redundant. TOU cost
   attribute useful for battery strategy ("discharge during expensive occupied hours")
   without changing existing load shedding logic.

---

## Post-Deploy Validation Checklist

### Layer 1: Config + Data Foundation

#### Config Flow Verification
| Check | How | Expected |
|-------|-----|----------|
| Room energy multi-select | Options → Room → Energy step | Picker accepts multiple energy sensors |
| Room energy migration | Reload integration after upgrade | Existing single sensor preserved in list |
| Zone power/energy pickers | Options → Zone Manager | New power/energy multi-select fields visible |
| House device pickers | Options → Coordinator Manager → Energy | New house device power/energy fields visible |
| Whole-house multi-select | Options → Coordinator Manager → Energy | Power and energy pickers accept multiple |
| Whole-house migration | Reload after upgrade | Existing single sensor preserved in list |

#### Attribution Model Verification
| Entity | Expected State | Check |
|--------|---------------|-------|
| `sensor.ura_energy_coverage_delta` | kWh (number) | Attributes: `rooms_total`, `zones_total`, `house_devices_total`, `unattributed`, `attribution_coverage_pct`, `delta_percent`, `coverage_rating` |

**After configuring zone HVAC sensor:**
- [ ] `zones_total` shows non-zero value
- [ ] `unattributed` decreases compared to before
- [ ] `attribution_coverage_pct` increases

**After configuring house device sensor (EV charger):**
- [ ] `house_devices_total` shows non-zero value
- [ ] `unattributed` decreases further

#### Power Profile Learning (requires 24h+ observation)
- [ ] Query `room_power_profiles` table via MCP — rows exist for active rooms
- [ ] Each room has entries across multiple time bins (at least MORNING, MIDDAY, AFTERNOON, EVENING)
- [ ] Sample counts increment over time (check at +24h and +48h)
- [ ] Standby watts (NIGHT bin, vacant) populated for rooms with overnight data

**Sample query:**
```sql
SELECT room_id, time_bin, day_type, avg_watts, sample_count
FROM room_power_profiles
WHERE room_id = 'kitchen'
ORDER BY day_type, time_bin;
```

#### Room Energy Tracking (multi-sensor)
- [ ] Room with 2+ energy sensors: `STATE_ENERGY_TODAY` shows summed value
- [ ] Room with 1 energy sensor: behavior unchanged (regression check)
- [ ] Room with 0 energy sensors: computed from power integration (regression check)

---

### Layer 2: Occupancy-Weighted Prediction

#### Toggle Verification
| Entity | Expected State | Check |
|--------|---------------|-------|
| `switch.ura_energy_occupancy_weighted_prediction` | OFF (default) | Visible on Energy Coordinator device card |

**Toggle OFF checks:**
- [ ] `predicted_consumption_kwh` matches pre-B4 baseline (compare with git-previous value)
- [ ] Battery `full_time` estimate unchanged from pre-B4
- [ ] No occupancy-related attributes on energy prediction sensors

**Toggle ON checks (flip switch in UI):**
- [ ] `predicted_consumption_kwh` changes within one energy coordinator cycle (~5 min)
- [ ] Value differs between weekday and weekend (if checked on both)
- [ ] Energy prediction sensor attributes include: `occupancy_blend_weight`, `rooms_with_profiles`, `attribution_divergence`
- [ ] Battery `full_time` reflects occupancy-shaped consumption curve

**Config flow sync:**
- [ ] Flip switch ON → Options flow shows toggle ON
- [ ] Change Options flow to OFF → Switch entity shows OFF

#### Blend Weight Maturity
- [ ] With mostly INSUFFICIENT Bayesian cells: blend weight near 0%
- [ ] With mixed ACTIVE/LEARNING cells: blend weight 10-25%
- [ ] With mostly ACTIVE cells: blend weight approaches 40%
- [ ] Attribute `occupancy_blend_weight` on prediction sensor reflects this

#### Divergence Cross-Check
- [ ] When attributed total is within 15% of whole-house: normal prediction used
- [ ] When divergence >15%: WARNING in logs, fallback to whole-house estimate
- [ ] Attribute `attribution_divergence` on prediction sensor shows current %

---

### Layer 3: Energy Intelligence Sensors

All per-room, disabled by default. Enable on 2-3 sample rooms to verify.

**Recommended test rooms:**
- Kitchen (high traffic, should have good data)
- Study A (medium traffic, has power sensors)
- Guest Bedroom or low-traffic room (tests edge cases)

#### Per-Room Sensors (enable in HA UI to check)
| Entity Pattern | Expected | Notes |
|----------------|----------|-------|
| `sensor.{room}_energy_waste_idle_kwh` | 0.0+ kWh | Accumulates only when room vacant. Resets at midnight. |
| `sensor.{room}_energy_cost_per_occupied_hour` | $X.XX/h or "unknown" | "unknown" if room never occupied today. Uses room electricity rate. |
| `sensor.{room}_most_expensive_circuit` | Entity name or "unknown" | "unknown" if 0-1 power sensors. Attributes: `sensors_ranked`, `tou_period`. |
| `sensor.{room}_optimization_potential` | $X.XX/month | `confidence` attribute: "low"/"medium"/"high". Needs 7+ days for meaningful value. |
| `binary_sensor.{room}_energy_anomaly` | OFF (normal) | ON = vacant + >200W + Bayesian P<10% + ACTIVE + 15min debounce. Guest suppressed. |

#### Sensor-Specific Checks
**EnergyWasteIdleSensor:**
- [ ] Leave a room vacant with a known load (e.g., TV on standby at 50W)
- [ ] After 1 hour: sensor shows ~0.05 kWh
- [ ] After midnight: sensor resets to 0.0

**EnergyCostPerOccupiedHourSensor:**
- [ ] Room occupied for 2h, consumed 1 kWh at $0.15/kWh → shows ~$0.075/h
- [ ] Room never occupied today → shows "unknown" (not $0.00)

**MostExpensiveDeviceSensor:**
- [ ] Room with 3 power sensors: highest TOU-weighted cost sensor shown as state
- [ ] `sensors_ranked` attribute: list of 3 entries sorted descending by hourly_cost
- [ ] During peak TOU: rankings may differ from off-peak (cost-weighted, not watts)

**OptimizationPotentialSensor:**
- [ ] After <7 days: `confidence` = "low"
- [ ] After 7-30 days: `confidence` = "medium"
- [ ] Room with zero idle waste: shows $0.00
- [ ] Room with consistent idle draw: estimate plausible (cross-check with manual math)

**EnergyAnomalyBinarySensor:**
- [ ] Normal standby (<200W) in vacant room: stays OFF
- [ ] High draw (>200W) in vacant room with ACTIVE Bayesian: turns ON after 15 min
- [ ] NM alert fires when anomaly triggers
- [ ] GUEST house state: suppressed (stays OFF even with anomaly conditions met)
- [ ] Bayesian INSUFFICIENT_DATA: stays OFF regardless of power draw

---

### Regression Checks

These verify B4 didn't break existing behavior:

- [ ] Existing `sensor.ura_rooms_energy_total` still shows correct sum
- [ ] Existing `sensor.ura_energy_coverage_delta` still works (upgraded, not replaced)
- [ ] Existing `sensor.ura_whole_house_power` still works with migrated config
- [ ] Energy coordinator load shedding unaffected (same thresholds, same TOU logic)
- [ ] Battery full-time estimate with toggle OFF matches pre-B4 values
- [ ] Room coordinator energy tracking with single sensor unchanged
- [ ] DailyEnergyPredictor sunrise refresh still works
- [ ] AccuracyTracker evaluation at midnight still works
- [ ] Energy history DB snapshots still include all existing columns

---

### Data Maturity Timeline

| Milestone | When | What to Check |
|-----------|------|---------------|
| +1 hour | After deploy | Config flow fields visible, switch entity created, attribution sensor upgraded |
| +24 hours | Day 2 | Power profiles populating (6+ time bins per active room), standby learning started |
| +7 days | Day 8 | OptimizationPotentialSensor reaches "medium" confidence, EMA converging |
| +10 days | Day 11 | Cold start threshold met (20 samples/cell), Layer 2 toggle safe to enable |
| +30 days | Day 31 | OptimizationPotentialSensor "high" confidence, attribution model stable |