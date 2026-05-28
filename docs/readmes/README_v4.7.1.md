# URA v4.7.1 — Dynamic Preset Override Source (Cycle B)

**Release date:** 2026-05-28
**Tier:** Tier 2-DB (new entities, new coordinator logic, new config-flow step, new dispatcher signals)

**Trigger:**
- Dynamic Preset Management Cycle B, as planned in `docs/planning/PLANNING_v4.7.x_dynamic_preset_management.md` §B.
- Consumes the `WeatherProviderManager.baseline_delta_for_zone()` apparent-temp primitive shipped in v4.7.0 Cycle A.

---

## TL;DR

**Dynamic Preset Override Source:** per-zone HVAC preset-range overrides driven by today's forecast apparent high vs. each zone's baseline. Delta is bucketed into one of four thermal load levels (cool / mild / hot / extreme). A 1-hour dwell timer + ±2°F hysteresis prevents flapping on the 5-minute EC decision cycle. Overrides compose cleanly with Guest Mode (priority 50 wins over dynamic preset priority 30). The feature is off by default; each zone opts in independently.

**OverrideEngine prerequisite:** `preset_overrides.py` implements the stateless highest-priority-wins composition engine that both Dynamic Preset and the upcoming Guest Mode Phase 1 will use. This is the shared composition substrate — no one caller owns it.

---

## What's Changed

### New files

| File | Purpose |
|---|---|
| `custom_components/universal_room_automation/domain_coordinators/preset_overrides.py` | `PresetOverride` dataclass, `ResolvedRange` dataclass, `OverrideEngine` class |
| `custom_components/universal_room_automation/domain_coordinators/dynamic_preset.py` | `BucketClass(StrEnum)`, `classify_bucket()`, `DynamicPresetOverrideSource`, hysteresis + dwell logic |

### Modified files

| File | What changed |
|---|---|
| `domain_coordinators/energy_const.py` | ~60 new CONF keys + defaults for bucket boundaries, dwell, hysteresis, per-zone preset table, guest mode schema |
| `domain_coordinators/signals.py` | `SIGNAL_DYNAMIC_PRESET_TRANSITIONED` + `SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED` |
| `domain_coordinators/energy.py` | `_dynamic_preset_source`, `_dynamic_preset_enabled`, `_async_evaluate_dynamic_presets()` wired into decision cycle |
| `sensor.py` | 3 new sensor classes (2 per-zone + 1 global) |
| `switch.py` | `ECDynamicPresetSwitch` via `_ec_switch_factory` |
| `number.py` | `DynamicPresetDwellMinutesNumber`, `DynamicPresetHysteresisFNumber` |
| `config_flow.py` | `async_step_zone_dynamic_preset()` + `_build_dynamic_preset_schema()` |

---

## New Entities

### Sensors

| Entity ID | Type | Per-zone? | Purpose |
|---|---|---|---|
| `sensor.ura_energy_dynamic_preset_active_bucket_{zone_id}` | Sensor | Yes | Current thermal load bucket (cool/mild/hot/extreme/unknown) |
| `sensor.ura_energy_dynamic_preset_effective_range_{zone_id}` | Sensor | Yes | Resolved cool range as "low–high °F" or "default" |
| `sensor.ura_energy_dynamic_preset_overrides_applied` | Sensor | No (global) | Count of zones currently with an active override |

`DynamicPresetActiveBucketSensor` is a `RestoreEntity` — bucket + `last_transition_at` survive HA restarts. On restore, the saved bucket is injected into `DynamicPresetOverrideSource.restore_zone_state()` so the dwell timer resumes from the original transition timestamp rather than resetting (Bug Class #10).

### Switch

| Entity ID | Type | Purpose |
|---|---|---|
| `switch.ura_energy_coordinator_dynamic_preset_enabled` | Switch | Master on/off for all zones; defaults OFF; RestoreEntity |

### Numbers

| Entity ID | Type | Default | Range | Step | Unit |
|---|---|---|---|---|---|
| `number.ura_energy_dynamic_preset_dwell_minutes` | Number | 60 | 15–240 | 5 | min |
| `number.ura_energy_dynamic_preset_hysteresis_f` | Number | 2.0 | 0.5–5.0 | 0.5 | °F |

---

## New Dispatcher Signals

| Signal | Payload | Fires when |
|---|---|---|
| `ura_dynamic_preset_transitioned` | `{zone_id, from_bucket, to_bucket, at_iso}` | Zone bucket changes after dwell + hysteresis pass |
| `ura_dynamic_preset_overrides_updated` | `{zone_overrides: dict[str, list]}` | After each EC decision cycle evaluates all zones |

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

## EC Decision Cycle Integration

`_async_evaluate_dynamic_presets()` is called at the end of each `_async_decision_cycle()` tick:

1. Skip if master switch is OFF or WPM is not available.
2. For each canonical HVAC zone (`iter_canonical_hvac_zones`): call `source.async_evaluate_and_emit()`.
3. Store per-zone overrides in `self._dynamic_preset_overrides`.
4. Dispatch `SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED` so sensors update.

Observation mode gating: source computes unconditionally. Actuation gating (the HVAC coordinator applying `set_temperature`) is the HVAC coordinator's responsibility — this follows Bug Class #23 (observation mode gate on actuation side, not source side).

---

## Bug Class Compliance

| Class | Compliance |
|---|---|
| #5 Startup race | `DynamicPresetActiveBucketSensor.available` returns False when WPM unavailable |
| #10 Cross-restart state | `DynamicPresetActiveBucketSensor(RestoreEntity)` + `restore_zone_state()` injection |
| #11 UTC datetime | `dt_util.utcnow()` throughout; naive-datetime restore guard in `_try_restore_to_source` |
| #19 Untracked tasks | `asyncio.Lock` re-entrancy guard; no fire-and-forget tasks created |
| #22 StrEnum | `BucketClass(StrEnum)` for all 4 bucket values |
| #23 Observation mode | Source computes always; actuation gated on HVAC coordinator side |
| #32 Source contract AST | `TestSourceContract` AST-walks `dynamic_preset.py` for all referenced CONF keys |
| #34 Local import shadowing | `dt_util` imported at module level in `sensor.py`; no re-import inside functions |
| #38 Listener cleanup | All dispatcher subscriptions via `async_on_remove()` |
| #42 Lambda + task | No lambda + `async_create_task` in callback positions |
| #44 sys.modules isolation | `sys.modules` force-set in test harness with unique sentinel objects |

---

## Tests

- **New test file:** `quality/tests/test_v47x_dynamic_preset.py`
- **Test count:** 67 tests, 12 classes
- **Result:** 67/67 pass
- **Full suite:** 56 failed / 3806 passed / 14 errors (56 failures are pre-existing missing-HA-dep issues; no new failures introduced)

### Test class summary

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
| `TestBuildGuestModeOverrides` | 2 | Builds home override; empty when opted out |

---

## Acceptance Criteria — Live Validation

After deploy + HACS download + restart, verify on the live HA instance:

1. **Entities present**
   - `switch.ura_energy_coordinator_dynamic_preset_enabled` visible in CM device page, state `off`.
   - `number.ura_energy_dynamic_preset_dwell_minutes` shows `60`.
   - `number.ura_energy_dynamic_preset_hysteresis_f` shows `2.0`.
   - `sensor.ura_energy_dynamic_preset_overrides_applied` shows `0` (no zones opted in yet).

2. **Per-zone entities present** (for at least one HVAC zone)
   - `sensor.ura_energy_dynamic_preset_active_bucket_{zone_id}` shows `unknown`.
   - `sensor.ura_energy_dynamic_preset_effective_range_{zone_id}` shows `default`.

3. **Config flow surfaces new zone step**
   - URA Zone Manager → Configure → HVAC zone → zone_dynamic_preset option present.
   - Form shows enable toggle, offset field, 4 bucket rows for home presets.

4. **End-to-end activation (opt in one zone)**
   - Enable `switch.ura_energy_coordinator_dynamic_preset_enabled`.
   - Via config-flow, opt in one zone with hot-bucket home range 74–78°F.
   - Within ≤5 min (next EC decision tick), `sensor.ura_energy_dynamic_preset_active_bucket_{zone_id}` shows a non-unknown bucket.
   - `sensor.ura_energy_dynamic_preset_overrides_applied` shows `1`.

5. **Restart persistence**
   - With one zone in a non-unknown bucket: restart HA.
   - After restart: `sensor.ura_energy_dynamic_preset_active_bucket_{zone_id}` restores to the same bucket.
   - No "unavailable" gap longer than one EC tick.

6. **No HA-core warnings introduced**
   - `ha_get_logs(source="system_service", slug="core")` — zero new ERROR entries under `universal_room_automation`.

7. **No frame-helper violations**
   - Zero `"calls async_create_task from a thread other than the event loop"` warnings (v4.6.15 invariant holds).

---

## What's Deferred

| Item | Reason | Where tracked |
|---|---|---|
| Number entity dwell/hysteresis values feeding into source at runtime | Number entities persist via RestoreEntity but EC reads from `config_entries.async_entries` options, not from the live Number entity value. Requires a shared mutable options dict or a direct EC attribute read. | Post-review backlog in planning doc |
| Guest Mode Phase 1 actuation path (applying resolved overrides to HVAC coordinator) | Out of scope for this cycle; OverrideEngine prerequisite shipped but actuation wiring is Guest Mode's work | `docs/planning/PLANNING_v4.7.x_guest_mode_actuation_phase1.md` |
| Per-zone bucket override for sleep preset ranges (sleep_low per bucket) | Sleep low not yet exposed in config-flow schema | Future zone preset refinement |

---

## Files Touched

```
custom_components/universal_room_automation/
  config_flow.py                                     — zone_dynamic_preset step + _build_dynamic_preset_schema
  domain_coordinators/
    dynamic_preset.py                                — NEW: BucketClass, classify_bucket, DynamicPresetOverrideSource
    energy.py                                        — _dynamic_preset_source/enabled/overrides + _async_evaluate_dynamic_presets
    energy_const.py                                  — ~60 new CONF keys + defaults
    preset_overrides.py                              — NEW: PresetOverride, ResolvedRange, OverrideEngine
    signals.py                                       — SIGNAL_DYNAMIC_PRESET_TRANSITIONED + _OVERRIDES_UPDATED
  number.py                                          — DynamicPresetDwellMinutesNumber + DynamicPresetHysteresisFNumber
  sensor.py                                          — 3 new sensor classes + _try_restore_to_source Bug #34 fix
  switch.py                                          — ECDynamicPresetSwitch via _ec_switch_factory

quality/tests/
  test_v47x_dynamic_preset.py                        — NEW: 67 tests, 12 classes
```
