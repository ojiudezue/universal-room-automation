# URA HVAC Management System

Technical reference for how the Universal Room Automation HVAC coordinator drives multi-zone climate while preventing energy waste and respecting user overrides.

---

## 1. Goal

Maintain comfort across zones while preventing AC waste, fighting user overrides safely, and yielding to the Energy Coordinator's TOU strategy. The system runs a 5-minute decision cycle, applies house-state-aware presets, monitors AC kWh-rate for stuck cycles, throttles fans to occupancy, and lets the Energy Coordinator nudge setpoints during peak periods. All control surfaces have an observation mode that computes decisions without executing them.

---

## 2. System Hardware

| Component | Details |
|---|---|
| Thermostats | Bryant WiFi + ecobee — per-zone setpoints, fan, preset |
| Zones | 4 active — Master Suite, Entertainment, Upstairs, Back Hallway |
| Per-zone fans | Aubric / Treatlife switch-fans — humidity + temp triggered |
| Motorized covers | Hunter Douglas PowerView — solar gain management |
| Per-AC power monitoring | SPAN circuits — `sensor.span_panel_ac{1,2,3}_power` (kW) + `..._consumed_energy` (kWh) |
| Outdoor temp | `weather.phalanxmadrone` forecast high/low (from EC's weather service) |

---

## 3. Control Levers

### Thermostat presets

The HVAC coordinator owns preset assignment. Setpoint ranges come from `SEASONAL_DEFAULTS` (built-in per-season-per-preset table — see §4) and are applied via `climate.set_preset_mode`. URA does NOT directly set `target_temp_high/low` today; the thermostat's own preset machinery resolves the range from the URA-issued preset name.

### House-state preset map

`HOUSE_STATE_PRESET_MAP` (in `hvac_const.py:780`), resolved via
`HVACPresetManager.get_preset_for_house_state` (`hvac_preset.py:111`):

| House state | Preset applied |
|---|---|
| `home_day` / `home_evening` / `home_night` | `home` |
| `arriving` / `waking` | `home` |
| `guest` | `home` (`hvac_const.py:789`) |
| `sleep` | `sleep` |
| `away` | `away` |
| `vacation` | `vacation` |

### Fan controllers (per-zone)

`SwitchFanController` decides when to turn each per-zone room fan ON or OFF using thresholds:
- **On** when room temp ≥ target + `fan_activation_delta` (default 2.0°F) AND zone is occupied
- **Off** when room temp ≤ target + `fan_hysteresis` (default 1.5°F) AND minimum runtime elapsed (default 10 min)

### Motorized covers — solar gain management

`CoverController` closes south/west-facing motorized blinds during the configured solar-gain window (default 13:00-18:00) when:
- Outdoor temp ≥ `cover_close_temp` (default 85°F)
- Zone is NOT being solar-banked (see §8)
- User hasn't manually overridden in the last `cover_override_hours` (default 2h)

Re-opens when outdoor temp drops below `cover_open_temp` (default 80°F) or window ends.

### AC Ramp-Down (v4.5.11) — kWh-aware nudging

When AC overshoots setpoint AND keeps burning kWh past the natural cycle end, the system nudges the setpoint up by `ac_nudge_size` (default 1.5°F) for `ac_nudge_duration` (default 5 min) then evaluates whether the compressor stopped. Two strikes → hard reset (toggle climate.turn_off/on). Hard-reset count capped per day per zone.

### Override Arrester (legacy v3.8.3)

Detects manual user setpoint changes on thermostats and either reverts them or compromises (averages user value with URA's preset). Used when URA's preset is "correct" per its rules but the user disagrees momentarily. Per-zone setting; respects user authority on long-running overrides.

### Energy constraint (from EC)

EC dispatches `SIGNAL_ENERGY_CONSTRAINT` with an offset (°F) and mode. HVAC applies the offset on top of the current preset range. See §9.

---

## 4. Seasonal Preset Defaults

Built-in per-season, per-preset baseline ranges (°F). Stored in `hvac_const.py:SEASONAL_DEFAULTS`. Format: `(cool_high, heat_low)` — the thermostat may auto-mode between these.

### Summer (Jun-Sep)

| Preset | Cool ≤ | Heat ≥ |
|---|---|---|
| home | 77 | 70 |
| sleep | 76 | 70 |
| away | 82 | 60 |
| vacation | 85 | 58 |

### Shoulder (Mar-May, Oct-Nov)

| Preset | Cool ≤ | Heat ≥ |
|---|---|---|
| home | 74 | 70 |
| sleep | 73 | 68 |
| away | 80 | 62 |
| vacation | 82 | 58 |

### Winter (Dec-Feb)

| Preset | Cool ≤ | Heat ≥ |
|---|---|---|
| home | 72 | 70 |
| sleep | 70 | 68 |
| away | 78 | 60 |
| vacation | 80 | 58 |

Season boundaries come from `TOURateEngine.get_season()` (Energy Coordinator); HVAC reads this so its seasonal logic stays aligned with TOU rates.

---

## 5. The AC Ramp-Down State Machine (v4.5.11)

Per-zone state machine in `hvac_override.py:check_ac_reset`. Default OFF at master level (`hvac_ac_ramp_master_enabled = False`); enable per-zone with `hvac_ac_ramp_zone_enabled`.

### States

```
IDLE
  │ overshoot detected + kwh_rate > zone threshold
  ▼
DETECTING (counting consecutive samples + minutes)
  │ samples ≥ sustained_samples AND elapsed ≥ detection_time_gate_min
  ▼
NUDGING  (setpoint raised by ac_nudge_size for ac_nudge_duration)
  │ nudge timer expired
  ▼
AWAITING_EVALUATION  (10 min, sensor settles)
  │ post-nudge kwh_rate STILL above threshold
  ▼
ESCALATING  (hard reset: climate.turn_off → wait → climate.turn_on)
  │
  ▼ either succeeded → IDLE, or exceeded daily limit → LOCKED_OUT
LOCKED_OUT  (until next day rollover OR user clears via button)
```

### Gates (`check_ac_reset` evaluation order, all must pass to advance)

| # | Gate | Skip condition |
|---|---|---|
| 0 | Legacy kill-switch | `_ac_reset_enabled = False` |
| 1 | Ramp master switch | `_ramp_master_enabled = False` (default) |
| 2 | Per-zone opt-in | `zone.ramp_zone_enabled = False` |
| 3 | `ac_load_sensor` configured | no sensor → feature disabled for zone |
| 4 | HVAC action = cooling, temps known | not cooling or readings None |
| 5 | Daily lockout flag (DB) | already locked-out for the day |
| 6 | Overshoot (current ≤ target_high, at-or-below setpoint) | not overshooting |
| 7 | kWh-rate debounce: N consecutive samples > zone threshold | counter < `sustained_samples` |
| 8 | Time-sustained for `detection_time_gate_min` | not yet long enough |
| 9 | Not already mid-nudge / mid-evaluation | overlap |

### Tunable knobs

| Knob | Range | Default | Purpose |
|---|---|---|---|
| Nudge Size | 0.5–3.0°F | 1.5°F | How far up to push setpoint |
| Nudge Duration | 1–15 min | 5 min | How long the nudge holds before restore |
| Sustained Samples | 2–10 | 3 | Consecutive kwh-rate ticks before counting as sustained |
| Detection Time Gate | 5–30 min | 10 min | Minimum overshoot duration before nudging |
| Hard Reset Daily Limit | 0–5 | 2 | Max compressor cycles per zone per day |
| Hard Reset Min Interval | 30–360 min | 120 min | Between back-to-back resets |
| Per-zone kWh Rate Threshold | 0.3–3.0 kW | 0.8 kW | Above-this-rate counts as "still burning" |

### Per-zone buttons

- **Force AC Nudge (zone)** — force a nudge regardless of detector state
- **Cancel AC Nudge (zone)** — abort nudge in progress, restore setpoint
- **Clear AC Ramp Lockout (zone)** — clear the daily lockout flag

---

## 6. Override Arrester

Detects manual setpoint changes on a thermostat that disagree with URA's currently-applied preset. Two modes per zone:

- **Active (default)**: Arrester reverts user changes after `compromise_minutes` (default 5 min) — or "compromises" by averaging if configured.
- **Passive**: Arrester tracks the override for diagnostics but does NOT revert.

Suppressed automatically when URA itself issues `set_preset_mode` or `set_temperature` calls (so the arrester doesn't fight URA's own legitimate writes). The v4.6.3.2 cycle hardened the suppress/release symmetry; v4.7.x Guest Mode actuation will extend the suppress logic to include `set_temperature` calls coming from the Override Engine.

### Sensor

`sensor.ura_hvac_coordinator_arrester_state` reports per-zone arrester state (`tracking`, `compromising`, `reverting`, `suppressed`).

---

## 7. Per-Zone HVAC Control

Each HVAC zone (configured in URA Zone Manager) has:
- A `zone_thermostat` (one HA climate entity)
- A `zone_rooms` list (rooms that contribute occupancy to this zone)
- Optional `hvac_ac_load_sensor` (kW or kWh — for ramp-down)
- Optional `hvac_ac_ramp_zone_enabled` opt-in
- Per-zone kWh rate threshold

Per-zone master toggle: `switch.ura_hvac_zone_<zone>_managed` — when off, URA leaves that zone alone entirely (no preset application, no ramp-down).

---

## 8. Solar Cover Management

When sun + outdoor heat would heat a south/west-facing zone above its cool setpoint, motorized blinds close to block solar gain. Trigger conditions:

- Outdoor temp ≥ `hvac_cover_close_temp` (default 85°F)
- Time within `hvac_cover_solar_start_hour` to `hvac_cover_solar_end_hour` (default 13:00-18:00)
- Zone NOT being solar-banked (see below)
- No user override in the last `hvac_cover_override_hours` (default 2h)
- `hvac_solar_gain_cover_enabled` is true (default true)

### Solar-banking interaction

When excess solar would heat the battery up (per EC), the HVAC coordinator can intentionally **lower** setpoints to absorb energy into the house (turning electricity into thermal mass) instead of exporting. This is gated by:
- EC's solar forecast classification AND
- Battery SOC ≥ `hvac_solar_bank_soc_min` (default 95%) AND
- Cool floor = `hvac_solar_bank_floor` (default 72°F — don't push lower than this)

When solar-banking is active for a zone, cover management for that zone is SUPPRESSED (don't close blinds — we WANT the heat in).

---

## 9. Energy Constraint Integration

EC dispatches `SIGNAL_ENERGY_CONSTRAINT` to HVAC each decision cycle. Payload (`EnergyConstraint` dataclass):

| Field | Meaning |
|---|---|
| `mode` | `normal` / `pre_cool` / `pre_heat` / `coast` / `shed` |
| `setpoint_offset` | °F to add to current preset's setpoints |
| `occupied_only` | Apply only to occupied zones (default True) |
| `max_runtime_minutes` | Optional runtime cap |
| `fan_assist` | Boost fans to help offset |
| `reason` | Human-readable trigger |
| `forecast_high_temp` | EC's forecast for today |
| `soc` | Battery SOC at decision time |

### Modes (per `energy_constraint_*_offset` config defaults)

| Mode | Default offset | Trigger |
|---|---|---|
| `pre_cool` | −2.0°F | EC anticipates peak; forecast high ≥ 90°F |
| `pre_heat` | +2.0°F | EC anticipates peak; forecast low < 40°F |
| `coast` | +3.0°F | Load shedding cascade level 4 reached |
| `shed` | +5.0°F | Aggressive shed (rare; sustained import) |

HVAC applies the offset on top of the current preset's setpoints (so summer `home` 70-77 + coast +3°F becomes 70-80°F). Reverts to baseline when EC sends `mode=normal`.

### Diagnostic sensor

`sensor.ura_energy_coordinator_hvac_constraint` — what EC is asking HVAC to do right now. Mode string state; attributes include offset + reason + forecast_high.

---

## 10. Vacancy Auto-Off

When a zone is unoccupied for `hvac_vacancy_grace_minutes` (default 30 min), the coordinator pushes that zone's preset toward `away` levels. If EC is in `constrained` mode, grace shortens to `hvac_vacancy_grace_constrained` (default 15 min) — vacancy-during-peak is a stronger signal than vacancy-during-cheap.

Hard ceiling: `hvac_max_occupancy_hours` (default 6 hr) — even if presence sensors say occupied, after this many continuous hours the zone reverts to away. Prevents stuck-occupied false-positive sensors from holding `home` preset indefinitely.

Re-enters `home` immediately on first occupancy signal.

---

## 11. Pre-Arrival

Reads presence-coordinator's `pre_arrival_sources` (default `["geofence", "ble", "camera_face"]`). When any source signals someone is arriving home AND house state is `away`, HVAC pre-conditions the destination zone (transitions to `home` preset early).

Independent of pre-cool / pre-heat (which are EC-driven, peak-anticipatory). Pre-arrival is presence-driven, comfort-anticipatory.

---

## 12. Pre-Cool Likelihood (Predictor)

`HVACPredictor` produces a 0-100% likelihood that today's peak window will trigger a pre-cool action. Inputs:
- Forecast peak outdoor temp (today)
- Forecast peak time
- Current TOU period
- House state + occupancy

Sensor: `sensor.ura_hvac_coordinator_pre_cool_likelihood` (state = %, attributes include forecast_peak_outside_f, forecast_peak_time_iso, anchor_period, solar_intent, prior_day_at_this_hour_f).

User-visible as a "will URA pre-cool today?" hint on the dashboard.

---

## 13. Decision Cycle Flow

Every 5 minutes (`_async_decision_cycle`):

1. **Determine current preset** — read house_state, map via `HOUSE_STATE_PRESET_MAP`, apply optional `Per-Zone Managed` opt-out
2. **Apply energy constraint** — if EC signaled non-normal mode, layer offset on top of preset setpoints
3. **Per-zone preset push** — `_apply_house_state_presets` issues `climate.set_preset_mode` per zone (arrester-suppressed)
4. **Fan controller update** — each zone's `SwitchFanController.update()` re-evaluates fan on/off
5. **Cover controller update** — solar-gain + solar-banking checks; close/open motorized blinds
6. **Override Arrester** — scan recent `climate.*` state changes; revert or compromise as configured
7. **AC Ramp-Down check** — `check_ac_reset` walks zone state machine
8. **Vacancy sweep** — check each zone's vacancy grace; push away if exceeded
9. **Anomaly observations** — record HVAC kWh-rate, runtime, override-frequency observations for the Anomaly Detector
10. **Compliance / decision recording** — write decision record to DB for telemetry sensors

### Observation Mode

`switch.ura_hvac_coordinator_observation_mode` — when ON, all logic runs but NO `climate.*` service calls fire. Sensors update normally. Used to dry-run a configuration change before letting it actually touch the thermostats.

---

## 14. Sensors

### Mode + status

| Sensor | Value |
|---|---|
| `sensor.ura_hvac_coordinator_mode` | Current overall mode (normal / pre_cool / pre_heat / coast / shed) |
| `sensor.ura_hvac_coordinator_zone_<n>_status` | Per-zone status (idle / cooling / heating / fan_only / off) |
| `sensor.ura_hvac_coordinator_zone_preset_<n>` | Per-zone effective preset right now |
| `sensor.ura_hvac_coordinator_arrester_state` | Override arrester per-zone state |

### Diagnostics + telemetry

| Sensor | Value |
|---|---|
| `sensor.ura_hvac_coordinator_anomaly` | Active anomaly count (kWh-rate, runtime, override-frequency) |
| `sensor.ura_hvac_coordinator_compliance` | % of decisions complied with (no manual override) |
| `sensor.ura_hvac_coordinator_override_frequency` | Manual overrides per 24h (rolling window) |
| `sensor.ura_hvac_coordinator_comfort_risk` | Current comfort-risk class (low / medium / high) |
| `sensor.ura_hvac_coordinator_pre_cool_likelihood` | 0-100% predictor |

### AC Ramp-Down (per-zone)

| Sensor | Value |
|---|---|
| `sensor.ura_hvac_coordinator_<zone>_ac_ramp_state` | State machine state (idle / detecting / nudging / awaiting_evaluation / escalating / locked_out) |
| `sensor.ura_hvac_coordinator_<zone>_ac_ramp_last_action` | ISO timestamp of last nudge/reset/lockout |
| `sensor.ura_hvac_coordinator_<zone>_ac_ramp_kwh_rate` | Live kWh-rate reading from `ac_load_sensor` |
| `sensor.ura_hvac_coordinator_<zone>_ac_nudges_today` | Count |
| `sensor.ura_hvac_coordinator_<zone>_ac_resets_today` | Count |

### Energy-side mirror

| Sensor | Value |
|---|---|
| `sensor.ura_energy_coordinator_hvac_constraint` | What EC is currently asking HVAC to do |

---

## 15. Database Tables

| Table | Purpose | Write Frequency |
|---|---|---|
| `hvac_decisions` | Per-decision record (zone, preset, setpoint, action, reason) | Every decision cycle, per zone |
| `ac_ramp_events` | AC nudge / hard reset / lockout events | On state transition |
| `hvac_compliance` | Whether the preceding decision was honored (vs reverted by user) | Per decision per zone |

All tables in `/config/universal_room_automation/data/universal_room_automation.db`.

---

## 16. Entity Reference (URA-controlled)

### Switches (master toggles)

| Entity | Purpose |
|---|---|
| `switch.ura_hvac_coordinator_enabled` | Master HVAC enable |
| `switch.ura_hvac_coordinator_observation_mode` | Dry-run mode |
| `switch.ura_hvac_override_arrester` | Override Arrester enable |
| `switch.ura_hvac_ac_reset_enabled` | Legacy AC reset (kept for backward compat) |
| `switch.ura_hvac_fan_control_enabled` | Fan controller enable |
| `switch.ura_hvac_solar_gain_cover_enabled` | Solar cover management enable |
| `switch.ura_hvac_ac_ramp_master_enabled` | v4.5.11 AC ramp-down master |
| `switch.ura_hvac_zone_<zone>_managed` | Per-zone master |
| `switch.ura_hvac_zone_<zone>_ramp_zone_enabled` | Per-zone ramp-down opt-in |

### Numbers (runtime sliders)

Configured under `URA: HVAC Coordinator` device page. See §3 + §5 tunable knob tables for ranges.

### Buttons

Per-zone: Force AC Nudge, Cancel AC Nudge, Clear AC Ramp Lockout.

### Per-zone climate

`climate.<zone_thermostat>` — controlled by URA via `set_preset_mode` (arrester-suppressed during URA writes).

---

## 17. Architecture

```
HVACCoordinator (hvac.py)
├── PresetManager (hvac_preset.py)            — seasonal defaults + house_state → preset map
├── ZoneManager (hvac_zones.py)               — per-zone state, opt-out toggles
├── CoverController (hvac_covers.py)          — motorized blinds, solar gain, solar banking
├── SwitchFanController (hvac_fans.py)        — per-zone fan on/off with hysteresis
├── HVACPredictor (hvac_predict.py)           — pre-cool / pre-heat likelihood
└── OverrideArrester (hvac_override.py)       — user-override detection + AC ramp-down state machine
```

**Priority:** 30 (above Comfort at 20, below Energy at 40, below Safety at 100). Energy can push HVAC around via `SIGNAL_ENERGY_CONSTRAINT`; Safety can preempt HVAC entirely (e.g., emergency heat-off on smoke alarm).

**Decision interval:** 5 minutes. Most state changes within a cycle are idempotent (e.g., re-issuing the same `set_preset_mode` for an already-active preset is a no-op).
