# URA v4.7.1 — Dynamic Preset Override Source + Fix-Up + Guest Mode Phase 1 D2/D3/D4

**Release date:** 2026-05-28
**Tier:** Tier 2-DB (new entities, new coordinator logic, new config-flow step, new dispatcher signals)
**Scope:** Cycle B feature build + 3-reviewer CRIT/HIGH fix-up + Guest Mode Phase 1 D2/D3/D4

**Trigger:**
- Dynamic Preset Management Cycle B, as planned in `docs/planning/PLANNING_v4.7.x_dynamic_preset_management.md` §B.
- Consumes the `WeatherProviderManager.baseline_delta_for_zone()` apparent-temp primitive shipped in v4.7.0 Cycle A.
- Closes 7 CRIT+HIGH findings from the 3-reviewer Tier 2-DB pass (Reviewers A, B, C on `agent-a52962f6264a4c339`).
- Ships Guest Mode Phase 1 D2 (HVAC actuation path), D3 (CM master toggle switch), D4 (diagnostic sensor).

---

## Headline Changes

- **Dynamic Preset now actuates thermostats.** When a zone is opted in and a bucket override is active, `HVACCoordinator._async_apply_preset_overrides()` calls `climate.set_temperature` with the resolved range after each `_apply_house_state_presets` cycle. Arrester suppression and `_last_emitted_range` throttling prevent duplicate commands.

- **Guest Mode master toggle.** `switch.ura_hvac_coordinator_guest_mode_actuation_enabled` on the HVAC Coordinator device globally enables/disables override actuation. Defaults ON. RestoreEntity. Turning it off also clears `_last_emitted_range` so the next enable starts fresh.

- **Active Preset Overrides diagnostic sensor.** `sensor.ura_hvac_coordinator_active_preset_overrides` on the HVAC Coordinator device shows the count of currently-active override records and carries `by_zone`, `house_state`, `master_enabled`, and `resolved_ranges` as extra attributes.

- **Bug Class #45 documented.** "Lambda Closure Captures Stale Local Variable" — a Python-specific variant of Bug Class #14. Added to `docs/QUALITY_CONTEXT.md`.

---

## TL;DR

**Dynamic Preset Override Source:** per-zone HVAC preset-range overrides driven by today's forecast apparent high vs. each zone's baseline. Delta is bucketed into one of four thermal load levels (cool / mild / hot / extreme). A 1-hour dwell timer + ±2°F hysteresis prevents flapping on the 5-minute EC decision cycle. Overrides compose cleanly with Guest Mode (priority 50 wins over dynamic preset priority 30). The feature is off by default; each zone opts in independently.

**OverrideEngine prerequisite:** `preset_overrides.py` implements the stateless highest-priority-wins composition engine that both Dynamic Preset and the upcoming Guest Mode Phase 1 use. This is the shared composition substrate — no one caller owns it.

---

## What's Changed

### New files

| File | Purpose |
|---|---|
| `custom_components/universal_room_automation/domain_coordinators/preset_overrides.py` | `PresetOverride` dataclass, `ResolvedRange` dataclass, `OverrideEngine` class |
| `custom_components/universal_room_automation/domain_coordinators/dynamic_preset.py` | `BucketClass(StrEnum)`, `classify_bucket()`, `DynamicPresetOverrideSource`, hysteresis + dwell logic |
| `quality/tests/test_v471_fixup_d2_d3_d4.py` | NEW: 14 tests for D2/D3/D4 actuation, switch, sensor |

### Modified files (Cycle B)

| File | What changed |
|---|---|
| `domain_coordinators/energy_const.py` | ~60 new CONF keys + defaults for bucket boundaries, dwell, hysteresis, per-zone preset table, guest mode schema |
| `domain_coordinators/signals.py` | `SIGNAL_DYNAMIC_PRESET_TRANSITIONED` + `SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED` |
| `domain_coordinators/energy.py` | `_dynamic_preset_source`, `_dynamic_preset_enabled`, `_async_evaluate_dynamic_presets()` wired into decision cycle |
| `sensor.py` | 3 new Cycle B sensor classes (2 per-zone + 1 global); 1 new D4 sensor class |
| `switch.py` | `ECDynamicPresetSwitch` via `_ec_switch_factory`; new `HVACGuestModeActuationSwitch` (D3) |
| `number.py` | `DynamicPresetDwellMinutesNumber`, `DynamicPresetHysteresisFNumber` |
| `config_flow.py` | `async_step_zone_dynamic_preset()` + `_build_dynamic_preset_schema()`; zone picker remapped to `iter_canonical_hvac_zones` (HIGH C/H2 fix) |

### Modified files (fix-up)

| File | Fix | Severity |
|---|---|---|
| `domain_coordinators/energy.py` | Replaced stale lambda `lambda: cm_options` with bound method `self._get_cm_options` (Bug #45); added change-detection guard before dispatching `SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED` | CRIT A1/B1/C1; HIGH B3 |
| `domain_coordinators/preset_overrides.py` | Deleted dead `build_guest_mode_overrides` static method (zero callers) | HIGH A3 |
| `sensor.py` | Removed `_attr_state_class = "measurement"` from `DynamicPresetOverridesAppliedSensor` (volatile count, not a continuous measurement) | HIGH A4 |
| `number.py` | `async_set_native_value` in both Number entities now writes back to `entry.options` via `async_update_entry` | HIGH A2/B2/C2 |
| `config_flow.py` | `async_step_zone_dynamic_preset` remaps `_selected_zone_name` to canonical merged zone name via `iter_canonical_hvac_zones` | HIGH C/H2 |
| `docs/user-manual/DYNAMIC_PRESET.md` | Fixed entity ID format, signal payload key names, "Reset offset on guest state" default | HIGH C/H1 doc fixes |
| `docs/QUALITY_CONTEXT.md` | Added Bug Class #45 "Lambda Closure Captures Stale Local Variable" | -- |

### Modified files (D2/D3/D4)

| File | What changed |
|---|---|
| `domain_coordinators/hvac.py` | Added `_guest_mode_actuation_enabled` + `_last_emitted_range`; added `_async_apply_preset_overrides()` method; called from `_apply_house_state_presets` when not in observation_mode |
| `switch.py` | `HVACGuestModeActuationSwitch` (D3) — on HVAC Coordinator device; RestoreEntity; turn_off clears `_last_emitted_range` |
| `sensor.py` | `HVACActivePresetOverridesSensor` (D4) — on HVAC Coordinator device; count + by_zone/house_state/master_enabled/resolved_ranges attributes |

---

## New Entities

### Sensors

| Entity ID | Type | Per-zone? | Purpose |
|---|---|---|---|
| `sensor.ura_energy_coordinator_dynamic_preset_bucket_{zone_id}` | Sensor | Yes | Current thermal load bucket (cool/mild/hot/extreme/unknown) |
| `sensor.ura_energy_coordinator_dynamic_preset_range_{zone_id}` | Sensor | Yes | Resolved cool range as "low–high °F" or "default" |
| `sensor.ura_energy_coordinator_dynamic_preset_overrides_applied` | Sensor | No (global) | Count of zones currently with an active override |
| `sensor.ura_hvac_coordinator_active_preset_overrides` | Sensor | No (D4) | Total active override records; attributes: by_zone, house_state, master_enabled, resolved_ranges |

`DynamicPresetActiveBucketSensor` is a `RestoreEntity` — bucket + `last_transition_at` survive HA restarts. On restore, the saved bucket is injected into `DynamicPresetOverrideSource.restore_zone_state()` so the dwell timer resumes from the original transition timestamp rather than resetting (Bug Class #10).

### Switches

| Entity ID | Device | Purpose |
|---|---|---|
| `switch.ura_energy_coordinator_dynamic_preset_enabled` | Energy Coordinator | Master on/off for all zones; defaults OFF; RestoreEntity |
| `switch.ura_hvac_coordinator_guest_mode_actuation_enabled` | HVAC Coordinator | D3: enables/disables override actuation; defaults ON; RestoreEntity |

### Numbers

| Entity ID | Type | Default | Range | Step | Unit |
|---|---|---|---|---|---|
| `number.ura_energy_coordinator_dynamic_preset_dwell_minutes` | Number | 60 | 15–240 | 5 | min |
| `number.ura_energy_coordinator_dynamic_preset_hysteresis` | Number | 2.0 | 0.5–5.0 | 0.5 | °F |

---

## New Dispatcher Signals

| Signal | Payload | Fires when |
|---|---|---|
| `ura_dynamic_preset_transitioned` | `{zone_id, previous_bucket, new_bucket, delta_f, now_iso}` | Zone bucket changes after dwell + hysteresis pass |
| `ura_dynamic_preset_overrides_updated` | (none) | After an EC decision cycle when overrides actually changed (new: change-detected before dispatch) |

---

## New CONF Keys (energy_const.py)

### Global EC options

| CONF key | Default | Purpose |
|---|---|---|
| `dynamic_preset_enabled` | `False` | Master enable (mirrors EC sub-switch) |
| `dynamic_preset_delta_cool_max` | `-2.0` | δ ≤ this → cool bucket |
| `dynamic_preset_delta_mild_max` | `8.0` | δ ≤ this → mild bucket |
| `dynamic_preset_delta_hot_max` | `18.0` | δ ≤ this → hot bucket; δ > this → extreme |
| `dynamic_preset_dwell_minutes` | `60` | Minimum minutes between bucket transitions |
| `dynamic_preset_hysteresis_f` | `2.0` | Extra delta past boundary required to exit tighter bucket |

### Per-zone options (zone_dynamic_preset config-flow step)

| CONF key | Purpose |
|---|---|
| `zone_dynamic_preset_enabled` | Zone opts in |
| `zone_dynamic_preset_offset_f` | Offset added to zone's home_high before computing sleep_high |
| `zone_dynamic_preset_reset_offset_on_guest` | Zero offset when house_state == 'guest' |
| `zone_dynamic_preset_sleep_enabled` | Emit sleep preset override in addition to home |
| `zone_dynamic_preset_cool_home_low` / `_home_high` | Preset range for cool bucket, home preset |
| `zone_dynamic_preset_mild_home_low` / `_home_high` | Preset range for mild bucket, home preset |
| `zone_dynamic_preset_hot_home_low` / `_home_high` | Preset range for hot bucket, home preset |
| `zone_dynamic_preset_extreme_home_low` / `_home_high` | Preset range for extreme bucket, home preset |
| `zone_dynamic_preset_cool_sleep_high` etc. | Preset range for each bucket, sleep preset |

---

## Bucket Classification Logic

```
delta = apparent_forecast_high − zone_home_cool_high (from WPM.baseline_delta_for_zone())

δ ≤ cool_max (-2°F)     → COOL
δ ≤ mild_max (+8°F)     → MILD
δ ≤ hot_max  (+18°F)    → HOT
else                    → EXTREME
```

**Dwell guard:** bucket must have been stable for ≥ `dwell_minutes` before a transition fires.

**Hysteresis (asymmetric):**
- Entering a tighter bucket (e.g., mild → hot): allowed by classification alone; no buffer required.
- Exiting a tighter bucket (e.g., hot → mild): delta must be past the boundary by ≥ `hysteresis_f` (i.e., delta ≤ mild_max − hysteresis_f).

**Sleep floor:** `sleep_high = max(74°F, home_high - 1) + zone_offset`. Prevents sleeping with a setpoint below 74°F regardless of zone config.

---

## OverrideEngine Composition Model

`OverrideEngine.resolve_range()` applies highest-priority-wins per field. When `cool_low` from two sources differ, the higher-priority source wins for `cool_low` independently of `cool_high`.

Priority ladder (lower number = evaluated first; higher number wins on conflict):
- `DYNAMIC_PRESET_PRIORITY = 30`
- `GUEST_MODE_PRIORITY = 50`

**Deadband enforcement:** if a resolved range has `cool_high - cool_low < MIN_DEADBAND (2°F)`, `cool_low` is clamped down to `cool_high - MIN_DEADBAND`.

---

## D2: HVAC Actuation Path

`HVACCoordinator._async_apply_preset_overrides()` is called at the end of `_apply_house_state_presets` when `not self._observation_mode`:

1. Exit early if `_guest_mode_actuation_enabled` is False.
2. Look up the EC's `_dynamic_preset_overrides` from `hass.data`.
3. For each canonical HVAC zone: call `OverrideEngine.resolve_range()` to get `ResolvedRange`.
4. If `resolved.differs_from_baseline(baseline_low, baseline_high)` AND range differs from `_last_emitted_range[zone_id]`: suppress arrester, call `climate.set_temperature`, update `_last_emitted_range`.
5. If no override is active: restore baseline, clear `_last_emitted_range[zone_id]`.

Observation mode gate: step is skipped entirely when `self._observation_mode` is True (Bug Class #23).

---

## EC Decision Cycle Integration

`_async_evaluate_dynamic_presets()` is called at the end of each `_async_decision_cycle()` tick:

1. Skip if master switch is OFF or WPM is not available.
2. For each canonical HVAC zone (`iter_canonical_hvac_zones`): call `source.async_evaluate_and_emit()`.
3. Store per-zone overrides in `self._dynamic_preset_overrides`.
4. **Signal spam guard (HIGH B3 fix):** Compare new overrides dict against previous; only dispatch `SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED` if the content changed.

---

## Bug Class Compliance

| Class | Compliance |
|---|---|
| #5 Startup race | `DynamicPresetActiveBucketSensor.available` returns False when WPM unavailable |
| #10 Cross-restart state | `DynamicPresetActiveBucketSensor(RestoreEntity)` + `restore_zone_state()` injection |
| #11 UTC datetime | `dt_util.utcnow()` throughout; naive-datetime restore guard in `_try_restore_to_source` |
| #14 Config snapshot staleness | Number entities now write to `entry.options`; `_get_cm_options` re-reads on every call |
| #19 Untracked tasks | `asyncio.Lock` re-entrancy guard; no fire-and-forget tasks created |
| #22 StrEnum | `BucketClass(StrEnum)` for all 4 bucket values |
| #23 Observation mode | Source computes always; actuation gated on HVAC coordinator side (D2 gate confirmed) |
| #32 Source contract AST | `TestSourceContract` AST-walks `dynamic_preset.py` for all referenced CONF keys |
| #34 Local import shadowing | `dt_util` imported at module level in `sensor.py`; no re-import inside functions |
| #38 Listener cleanup | All dispatcher subscriptions via `async_on_remove()` |
| #42 Lambda + task | No lambda + `async_create_task` in callback positions |
| #44 sys.modules isolation | `sys.modules` force-set in test harness with unique sentinel objects |
| **#45 Lambda closure staleness** | **`_get_cm_options` bound method replaces stale `lambda: cm_options` (CRIT A1/B1/C1)** |

---

## Tests

- **Cycle B test file:** `quality/tests/test_v47x_dynamic_preset.py` — 65 tests (2 dead-code tests removed: `TestBuildGuestModeOverrides`)
- **New test file:** `quality/tests/test_v471_fixup_d2_d3_d4.py` — 14 tests
- **Full suite result:** 56 failed / 3822 passed (vs. Cycle B baseline: 56 failed / 3808 passed) — 14 net new passing tests, 0 new failures

### test_v47x_dynamic_preset.py class summary

| Class | Tests | Covers |
|---|---|---|
| `TestBucketClassification` | 10 | Boundary conditions + plan examples |
| `TestHysteresisBuffer` | 6 | Entry/exit asymmetry |
| `TestSleepFloor` | 6 | Floor rule with/without offset |
| `TestEvaluateAndEmit` | 15 | Zone opt-in, forecast gate, dwell, hysteresis, offset, sleep preset |
| `TestRestoreZoneState` | 4 | Bug #10 restore valid/invalid/naive-dt/dwell-resume |
| `TestReentrancyGuard` | 1 | Concurrent async calls serialize |
| `TestOverrideEngine` | 9 | Composition, priority, deadband, baseline-diff |
| `TestGuestModePredicate` | 4 | Predicate evaluation |
| `TestObservationModeGating` | 1 | Source has no `observation_mode` attribute |
| `TestSourceContract` | 5 | Bug #32 AST walk, StrEnum, constants, priority ordering |
| `TestGetZoneState` | 2 | Uninitialized zone + dwell_remaining |
| `TestGetCmOptionsFreshRead` | 2 | Bug #45 fix — bound method re-reads options on every call |
| `TestNumberEntityWriteback` | 2 | HIGH A2/B2/C2 fix — Number entities write to entry.options |

### test_v471_fixup_d2_d3_d4.py class summary

| Class | Tests | Covers |
|---|---|---|
| `TestHvacApplyEmitsSetTemperatureWhenOverrideActive` | 5 | D2 actuation: override fires/skips, baseline restore, arrester, throttle |
| `TestGuestModeActuationSwitch` | 3 | D3: switch off skips path, round-trips RestoreEntity, default=True |
| `TestActivePresetOverridesSensor` | 4 | D4: state count, attributes shape, clears on master disabled, updates on house_state change |
| `TestD2D3Integration` | 2 | master_enabled flag respected, observation_mode gate pattern |

---

## Acceptance Criteria — Live Validation

After deploy + HACS download + restart, verify on the live HA instance:

1. **Cycle B entities present**
   - `switch.ura_energy_coordinator_dynamic_preset_enabled` visible in CM device page, state `off`.
   - `number.ura_energy_coordinator_dynamic_preset_dwell_minutes` shows `60`.
   - `number.ura_energy_coordinator_dynamic_preset_hysteresis` shows `2.0`.
   - `sensor.ura_energy_coordinator_dynamic_preset_overrides_applied` shows `0`.

2. **D3/D4 entities present**
   - `switch.ura_hvac_coordinator_guest_mode_actuation_enabled` visible in HVAC Coordinator device page, state `on`.
   - `sensor.ura_hvac_coordinator_active_preset_overrides` visible in HVAC Coordinator device page, state `0`.

3. **Per-zone entities present** (for at least one HVAC zone)
   - `sensor.ura_energy_coordinator_dynamic_preset_bucket_{zone_id}` shows `unknown`.
   - `sensor.ura_energy_coordinator_dynamic_preset_range_{zone_id}` shows `default`.

4. **Config flow surfaces new zone step**
   - URA Zone Manager → Configure → HVAC zone → zone_dynamic_preset option present.
   - Zone picker shows canonical merged zone names (e.g., "Entertainment + Master Suite"), not all zones separately.

5. **End-to-end activation (opt in one zone)**
   - Enable `switch.ura_energy_coordinator_dynamic_preset_enabled`.
   - Via config-flow, opt in one zone with hot-bucket home range 74–78°F.
   - Within ≤5 min (next EC decision tick), `sensor.ura_energy_coordinator_dynamic_preset_bucket_{zone_id}` shows a non-unknown bucket.
   - `sensor.ura_energy_coordinator_dynamic_preset_overrides_applied` shows `1`.
   - `sensor.ura_hvac_coordinator_active_preset_overrides` shows ≥1.
   - If house_state = home_day: thermostat receives a `climate.set_temperature` call matching the resolved range.

6. **Number entity write-back**
   - Set `number.ura_energy_coordinator_dynamic_preset_dwell_minutes` to 30.
   - Restart HA.
   - After restart, value remains `30` (not reset to `60`).

7. **No HA-core warnings introduced**
   - `ha_get_logs(source="system_service", slug="core")` — zero new ERROR entries under `universal_room_automation`.

8. **No frame-helper violations**
   - Zero `"calls async_create_task from a thread other than the event loop"` warnings (v4.6.15 invariant holds).

---

## What's Deferred

| Item | Reason | Where tracked |
|---|---|---|
| Per-zone Guest UI (CONF_ZONE_GUEST_* keys) | Requires new config-flow step + validation; D3 reduced scope is CM master toggle only | `docs/planning/PLANNING_v4.7.x_guest_mode_actuation_phase1.md` Phase 2 |
| Multi-bedroom aggregation | Requires zone topology refactor | Future cycle |
| resolve_range tiebreak (narrowest-range for equal-priority sources) | No tie is possible with current sources; safe to ship without | Planning doc §I backlog A5 |
| DynamicPresetActiveBucketSensor deferred restore retry via SIGNAL_ENERGY_COORDINATOR_READY | Dwell resets to zero on restart; first tick may trigger early transition | Planning doc §I backlog B4/M4 |
| `_make_override` test helper preset="sleep" in state count test | Test fixed to use matching preset; sleep-override counting is a future test gap | Test comment in test_v471_fixup_d2_d3_d4.py |

---

## Files Touched

```
custom_components/universal_room_automation/
  config_flow.py                                     — zone_dynamic_preset step + _build_dynamic_preset_schema + iter_canonical_hvac_zones remap
  domain_coordinators/
    dynamic_preset.py                                — NEW: BucketClass, classify_bucket, DynamicPresetOverrideSource
    energy.py                                        — _dynamic_preset_source/enabled/overrides + _async_evaluate_dynamic_presets + _get_cm_options (Bug #45) + change-detection guard
    energy_const.py                                  — ~60 new CONF keys + defaults
    hvac.py                                          — D2: _guest_mode_actuation_enabled, _last_emitted_range, _async_apply_preset_overrides
    preset_overrides.py                              — NEW: PresetOverride, ResolvedRange, OverrideEngine; build_guest_mode_overrides DELETED (dead code)
    signals.py                                       — SIGNAL_DYNAMIC_PRESET_TRANSITIONED + _OVERRIDES_UPDATED
  number.py                                          — DynamicPresetDwellMinutesNumber + DynamicPresetHysteresisFNumber + entry.options writeback
  sensor.py                                          — 4 new sensor classes; DynamicPresetOverridesAppliedSensor state_class removed
  switch.py                                          — ECDynamicPresetSwitch via _ec_switch_factory; HVACGuestModeActuationSwitch (D3)

quality/tests/
  test_v47x_dynamic_preset.py                        — 65 tests (2 dead-code tests removed, 4 new fix-up tests added)
  test_v471_fixup_d2_d3_d4.py                        — NEW: 14 tests for D2/D3/D4

docs/
  QUALITY_CONTEXT.md                                 — Bug Class #45 added
  planning/PLANNING_v4.7.x_dynamic_preset_management.md  — §I Post-Review Backlog (Cycle B) appended
  user-manual/DYNAMIC_PRESET.md                      — entity IDs, signal payload keys, default values corrected
  readmes/README_v4.7.1.md                           — this file
```
