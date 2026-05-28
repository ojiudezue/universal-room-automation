# URA v4.7.2 — DPM HVAC Coordinator Surface + Phase 2 Feature B (Sustained-Occupancy Guest Signal)

**Release date:** 2026-05-28
**Tier:** Tier 2 (new config-flow surface, new switch class, new presence logic)
**Scope:** D1 Surface 1 config-flow step, D2 switch migration, D3 rename, D4 per-room guest constants, D5 sustained-occupancy guest signal

**Trigger:**
- Dynamic Preset Management Surface 1 (HVAC Coordinator → Configure → Dynamic Preset)
- D2 migration of `ECDynamicPresetSwitch` from Energy Coordinator device to HVAC Coordinator device
- D3 rename of `HVACGuestModeActuationSwitch` for frontend sort clarity
- Phase 2 Feature B: sustained-occupancy guest signal as additive OR into the existing unidentified-persons gate

---

## Headline Changes

- **Dynamic Preset config now reachable from HVAC Coordinator → Configure → Dynamic Preset.** The `coordinator_hvac` options menu now has two entries: `coordinator_hvac_settings` (existing tuning form) and `hvac_dynamic_preset` (new Surface 1). House-wide constants (delta thresholds, dwell minutes, hysteresis) sit in the CM entry; per-zone bucket boundaries are stored in the ZM entry. `_validate_dynamic_preset_input` is the shared validation helper called by both Surface 1 and the existing Surface 2 (`async_step_zone_dynamic_preset`).

- **Dynamic Preset Auto-Adjust switch migrated to HVAC Coordinator device.** `HVACDynamicPresetSwitch` replaces `ECDynamicPresetSwitch` on the device page. The unique_id `{DOMAIN}_energy_dynamic_preset_enabled` is preserved so existing entity_registry entries are not orphaned. Default flipped OFF → ON (DPM is a no-op without per-zone opt-in). Full SIGNAL_ENERGY_COORDINATOR_READY deferred-restore.

- **HVAC Coordinator device numeric prefixes.** `HVACGuestModeActuationSwitch._attr_name` renamed to `"01 · Custom Preset Ranges"` and `HVACDynamicPresetSwitch._attr_name` set to `"02 · Dynamic Preset Auto-Adjust"`. Non-colliding with the existing 00·/10·/15·/.../50· range. Frontend sort via Intl.Collator(numeric:true) places them at the top of the device page.

- **Per-room guest designation.** Two new constants: `CONF_ROOM_IS_GUEST_ROOM` (bool, default False) and `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN` (int, default 30, range 5-240). Wired into the room reconfigure step (basic_setup). Labeled in strings.json and translations/en.json.

- **Sustained-occupancy guest signal.** When a room is flagged `is_guest_room=True`, `PresenceCoordinator._discover_guest_rooms()` subscribes to `binary_sensor.{room_slug}_occupied`. If the room is occupied by an unidentified person for >= `threshold_min` minutes, `_guest_room_gate_armed()` returns True and `_run_inference()` fires GUEST via additive OR. Confidence is 0.9 (vs 0.8 for the unid-persons path). The GUEST exit condition now checks BOTH `unidentified_count == 0 AND not guest_gate_armed` to prevent immediate re-exit.

---

## TL;DR

v4.7.2 adds the HVAC Coordinator side of the Dynamic Preset config surface (the zone side shipped in v4.7.0/v4.7.1), moves the DPM switch to the HVAC device, and adds a second path for guest-mode detection via sustained room occupancy by unknown persons. The sustained-occupancy path is completely independent of the census/BLE unidentified-persons path and composes cleanly with it via an additive OR gate.

---

## What's Changed

### Modified files

| File | What changed |
|---|---|
| `const.py` | D4: `CONF_ROOM_IS_GUEST_ROOM`, `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN` |
| `config_flow.py` | D1: `coordinator_hvac` → menu; `async_step_coordinator_hvac_settings` (renamed form); `async_step_hvac_dynamic_preset` + `_validate_dynamic_preset_input` + `_build_hvac_dynamic_preset_schema`; D4: two fields in `async_step_basic_setup` |
| `switch.py` | D2: new `HVACDynamicPresetSwitch` class (HVAC device, preserved unique_id, default ON, deferred-restore); D3: `HVACGuestModeActuationSwitch._attr_name` → `"01 · Custom Preset Ranges"` |
| `domain_coordinators/presence.py` | D5: `_guest_room_state`, `_guest_room_unsubs`, `_discover_guest_rooms()`, `_handle_guest_room_occupancy_change()`, `_is_known_person_in_room()`, `_guest_room_gate_armed()`; `_run_inference()` additive OR + confidence 0.9; combined GUEST exit condition; teardown cleanup |
| `strings.json` | D1: `coordinator_hvac` menu, `coordinator_hvac_settings` form, `hvac_dynamic_preset` step; D4: `room_is_guest_room`, `room_guest_occupancy_threshold_min` in `basic_setup` |
| `translations/en.json` | Mirrors strings.json (all D1 + D4 entries) |

### New test files

| File | Tests | Covers |
|---|---|---|
| `quality/tests/test_v472_dpm_surfaces.py` | 33 | D1 menu/form structure, D1 Surface 1 step, D2 migration, D3 rename |
| `quality/tests/test_v472_feature_b_guest_signal.py` | 39 | D4 constants, D4 config-flow, D4 strings, D5 init, D5 discovery, D5 callback, D5 gate, D5 inference OR, D5 exit guard, D5 teardown |

### Updated tests (adapted to renamed step)

| File | Tests updated | Reason |
|---|---|---|
| `quality/tests/test_v4510_hvac_tunables_and_labels.py` | 6 | `coordinator_hvac` → `coordinator_hvac_settings` (form step renamed) |
| `quality/tests/test_v4592_strings_and_delta.py` | 2 | `coordinator_hvac` → `coordinator_hvac_settings` |
| `quality/tests/test_v4511_ac_energy_aware_ramp_down.py` | 2 | `_discover_ac_zones` now delegates to `iter_canonical_hvac_zones` (v4.5.13.1 refactor); `_hvac_zone_kwh_threshold_factory` uses explicit keyword args |
| `quality/tests/test_v4622_guest_mode_hardening.py` | 1 | D5 GUEST exit: `unidentified_count == 0 and not guest_gate_armed` combined condition |

---

## Entity Impact

### New entities

None. (HVACDynamicPresetSwitch is a migration, not a net-new entity.)

### Renamed entity display names (entity_id stable)

| Entity ID | Old name | New name |
|---|---|---|
| `switch.ura_hvac_coordinator_guest_mode_actuation_enabled` | Guest Mode Actuation | 01 · Custom Preset Ranges |
| `switch.ura_energy_dynamic_preset_enabled` | Dynamic Preset Overrides | 02 · Dynamic Preset Auto-Adjust |

Note: `switch.ura_energy_dynamic_preset_enabled` moves from the Energy Coordinator device page to the HVAC Coordinator device page. The entity_id does not change.

---

## Bug Class Compliance

| Bug Class | Guard |
|---|---|
| #5 (Startup Race) | D2: `SIGNAL_ENERGY_COORDINATOR_READY` deferred-restore with 3-retry chain |
| #11 (UTC vs Local) | D5: `dt_util.utcnow()` for all first_seen timestamps |
| #14 (Config Snapshot Staleness) | D5: `_is_known_person_in_room()` reads fresh from `hass.data` each call |
| #32 (Form Field With No Runtime Reader) | D1: all Surface 1 fields written to CM/ZM entry options at save time |
| #38 (Listener Cleanup) | D5: all unsubs stored in `_guest_room_unsubs`, cleaned up in `async_teardown()` |
| #42 (Lambda+async_create_task) | D5: `_handle_guest_room_occupancy_change` is a `@callback` bound method, no lambda |

---

## D2 Entity Registry Pre-Deploy Verification

Before deploying v4.7.2, confirm the current entity_registry entry for the switch:

```bash
# Expected: unique_id = universal_room_automation_energy_dynamic_preset_enabled
# Expected: platform = universal_room_automation
# After deploy: device page changes from "URA: Energy Coordinator" to "URA: HVAC Coordinator"
# entity_id does NOT change
```

---

## Test Results

```
3912 passed, 54 failed (pre-existing), 2 skipped
```

Pre-existing failures (54) are in test_cycle_b_config_flow, test_data_pipeline, test_envoy_auto_derive, test_hvac_fan_control, test_metric_baseline_integration, test_runtime_smoke, and test_activity_logger. None of these were introduced by v4.7.2.

v4.7.2-specific test files: 88 tests, all pass.
v4.7.2-adapted existing tests: all pass.

---

## Post-Review Fix-up (2026-05-28)

Following the Tier 2 reviewer pass (Reviewer A: correctness; Reviewer B: async + lifecycle), six issues were fixed before deploy:

**CRITICAL C1** (`config_flow.py:5504–5524`): Surface 2 (`async_step_zone_dynamic_preset`) had inline validation instead of calling `_validate_dynamic_preset_input`. Replaced with a call to the shared helper with `zone_prefix=""` so both surfaces produce identical error keys for identical bad input.

**CRITICAL B1** (`presence.py:1897–1930`): `_run_inference()` hardcoded `guest_room_gate_armed = False` when `current_state == HouseState.GUEST`, causing immediate GUEST→HOME oscillation because the exit condition at `infer()` reduced to `unidentified_count == 0`. Fixed by adding an `elif current_state == HouseState.GUEST` branch that evaluates `_guest_room_gate_armed()` (pure predicate, no side effects) while keeping the unid gate skipped (side-effect-bearing). This is Bug Class #46: Exit-Path Gate Skip.

**HIGH H1** (`config_flow.py:3676–3693`): Docstring for `async_step_hvac_dynamic_preset` referenced non-existent `CONF_DYNAMIC_PRESET_MASTER_ENABLED` and a master toggle field that was never built. Rewritten to accurately describe the form layout and clarify that the master toggle is the D2 switch entity on the HVAC Coordinator device page.

**HIGH B2** (`__init__.py`, CM entry branch): Added idempotent entity_registry device-reassignment helper after `async_forward_entry_setups`. If HA does not auto-reassign `switch.ura_energy_dynamic_preset_enabled` to the HVAC Coordinator device on restart, the helper does the work. If HA already reassigned, the `device_id != target_device.id` guard no-ops. Wrapped in try/except (non-fatal).

**MEDIUM B4** (`switch.py:936`): Added `self._default_flip_pending_nm: bool = False` to `HVACDynamicPresetSwitch.__init__` so all code paths can use direct attribute access instead of the fragile `getattr(..., False)` pattern.

**MEDIUM B5** (`presence.py:1641`): Corrected the `_handle_guest_room_occupancy_change` docstring. Old text said "no async_create_task in this callback" but line 1698 calls `async_create_task`. New text accurately describes the safe pattern: `async_create_task` from a `@callback` running on the event loop.

16 new tests added across both v4.7.2 test files covering all fix-up items.
