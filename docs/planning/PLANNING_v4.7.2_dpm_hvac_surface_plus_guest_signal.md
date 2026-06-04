# PLANNING v4.7.2 — DPM HVAC Coordinator Surface + Phase 2 Feature B (Sustained-Occupancy Guest Signal)

**Status:** Plan ready for build
**Tier:** Tier 2 (two parallel staff-engineer reviews, different framings)
**Predecessors:** v4.7.1 (DPM Cycle B + Phase 1 D2/D3/D4) + v4.7.1.1 (translations hotfix)
**Recall:** "Resume v4.7.2 — DPM HVAC surface + Phase 2 Feature B"

---

## 1. Tier Classification

**Tier 2.** Triggers checked against Tier 2-DB criteria:

| Tier 2-DB Trigger | Hit? | Notes |
|---|---|---|
| Touches `database.py` DAO definitions | No | No DB code modified |
| Migrates ≥3 callers to a new DAO | No | No new DAO |
| Changes payload shape of a dispatched event or persisted record | No | `guest_gate_armed` remains bool; `_confidence` semantic still float 0..1 |
| Adds behavioral test infrastructure against real schemas | No | Test additions ride existing fixtures |
| Followed within 1-2 versions by a planned schema migration | No | No upcoming schema migration depends on this |

Two parallel staff-engineer reviews per CLAUDE.md Tier 2 protocol. Framings in §9 are deliberately disjoint to prevent blind-spot overlap.

---

## 2. Goal + Why

**Goal:** Bridge from v4.7.1's interim state — where DPM works but its master kill switch sits on the Energy Coordinator device (sourcefactory artefact) while the actuation gate sits on the HVAC Coordinator device (correctly) — to a polished v4.7.2 where both DPM master toggles live on the HVAC Coordinator device, are numerically ordered for predictable HA frontend sort (Intl.Collator numeric:true; ref memory `project_ha_frontend_entity_sort.md`), and a second user-facing surface (HVAC Coordinator → Configure → Dynamic Preset) duplicates the Zone Manager per-zone bucket step so the user can reach DPM configuration from the HVAC entry point.

Concurrently ships Phase 2 Feature B of the Guest Mode actuation plan: a per-Room `is_guest_room: bool` config flag and a new sustained-occupancy guest signal that OR's additively into the existing v4.6.2.2 unidentified-persons gate (`presence.py:_guest_gate_armed`). Higher-specificity confidence (0.9) wins over the existing path's 0.8 when both fire.

**User position (locked 2026-05-28):** "Regard 4.7.1 as interim." v4.7.1 shipped DPM but the user-facing affordance is fragmented:
- The master kill switch lives on EC (because `_ec_switch_factory` was the cheap path at build time), not HVAC where the feature surfaces user-visible behavior.
- The HVAC actuation gate (v4.7.1 D3 `HVACGuestModeActuationSwitch`) is correctly placed but mislabeled ("Guest Mode Actuation" — actually gates ALL preset-override sources including DPM and future actuators).
- DPM configuration is reachable only via Zone Manager. A user entering the HVAC Coordinator surface to configure climate-related behavior has no path to DPM.

v4.7.2 closes all three gaps without changing the underlying engine behavior. The Phase 2 Feature B work bundles cleanly because both involve `presence.py` + per-Room config flags and benefit from one validation cycle, not two.

---

## 3. Discovery — Read Before Build (Mandatory)

Builder MUST read these before code changes:

| File | Lines | Why |
|---|---|---|
| `switch.py` | 550-745 (`_ec_switch_factory`) | Factory generates `_ECSwitch` with `DeviceInfo(identifiers={(DOMAIN, "energy_coordinator")}, ...)` and unique_id `f"{DOMAIN}_energy_{unique_suffix}"`. For D2 migration: NEW class must preserve the unique_id while changing only `DeviceInfo.identifiers` and `name`. |
| `switch.py` | 891-895 (`ECDynamicPresetSwitch`) | The factory call to be replaced/migrated. unique_suffix is `"dynamic_preset_enabled"` → existing unique_id is `f"{DOMAIN}_energy_dynamic_preset_enabled"`. Backing attr is `dynamic_preset_enabled` on EC. |
| `switch.py` | 898-970 (`HVACGuestModeActuationSwitch`) | The toggle to rename. `_attr_name = "Guest Mode Actuation"` at line 920. unique_id `f"{DOMAIN}_hvac_coordinator_guest_mode_actuation_enabled"` MUST NOT change. |
| `config_flow.py` | 4456-4479 (`async_step_zone_config_menu`) | Surface 2's menu — already routes `zone_dynamic_preset`. |
| `config_flow.py` | 5004-5184 (`async_step_zone_dynamic_preset`) | Surface 2's step function. Storage pattern at lines 5132-5140 (merges into `zm_entry.options["zones"][zone_name]`). |
| `config_flow.py` | 5186-5274 (`_build_dynamic_preset_schema`) | The shared per-zone schema helper. Surface 1 MUST consume this helper exactly. |
| `presence.py` | 1522-1620 (`_guest_gate_armed` + `_disarm_guest_gate`) | Existing gate logic for v4.6.2.2 unid-persons path. Feature B layers in additively. |
| `presence.py` | 367-449 (`StateInferenceEngine.infer`) | Consumer of `guest_gate_armed`. Confidence set at line 443 (`self._confidence = 0.8`). |
| `hvac_zones.py` | 693-729 (`iter_canonical_hvac_zones`) | Canonical zone resolver. Surface 1 MUST consume this to enumerate per-zone rows. Same helper Surface 2 already uses (config_flow.py:5066). |
| `hvac.py` | `_apply_house_state_presets` + `_async_apply_preset_overrides` | Sink where `_guest_mode_actuation_enabled` already gates emission. D3 rename has zero behavior impact at this site. |
| `energy.py` | `_dynamic_preset_enabled` field + `_async_evaluate_dynamic_presets()` | Backing field of D2 migrated switch. D2 does NOT move the field — just relocates the UI surface. |
| `energy_const.py` | (entire) | New CONFs land here: `CONF_DYNAMIC_PRESET_DELTA_COOL_MAX`, `_MILD_MAX`, `_HOT_MAX`, `CONF_DYNAMIC_PRESET_DWELL_MINUTES`, `CONF_DYNAMIC_PRESET_HYSTERESIS_F` (already exist per v4.7.1) — Surface 1 EXPOSES them to UI; CONFs themselves already exist. New CONFs for Feature B: `CONF_ROOM_IS_GUEST_ROOM`, `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN`. |
| `config_flow.py` | 5280-5350 (`async_step_basic_setup`) | Per-Room reconfigure step. D4 adds `is_guest_room` + `guest_occupancy_threshold_min` fields here. |
| `strings.json` + `translations/en.json` | (entire) | D1 adds ~30 entries (step title, master enable, bucket boundaries, dwell, hysteresis, per-zone repeat labels). D3 updates description for renamed switch. D4 adds room flag labels. |
| `docs/QUALITY_CONTEXT.md` | Bug Classes #2, #5, #10, #11, #14, #19, #22, #23, #32, #36, #38, #42, #45 | See compliance matrix §8 for which apply where. |

---

## 4. Deliverables

### D1 — HVAC Coordinator → Configure → Dynamic Preset Step (Surface 1, NEW)

**Description:** New `async_step_hvac_dynamic_preset()` under the CM coordinator-manager options flow. Reachable via Settings → Devices & Services → URA Coordinator Manager → Configure → HVAC step → Dynamic Preset submenu. NOT a new config entry; reuses CM entry options storage for house-wide settings and ZM entry options for per-zone rows.

**Files touched:**
- `config_flow.py`: add `async_step_hvac_dynamic_preset()` + helper `_render_hvac_dpm_form()`; route from the HVAC CM step menu. **NEW shared helper `_validate_dynamic_preset_input(user_input)`** extracted from `async_step_zone_dynamic_preset` (currently at lines 5097-5129). Both surfaces call it. ~250 LoC.
- `strings.json` + `translations/en.json`: ~30 new labels.
- `energy_const.py`: no new CONFs needed for D1 (`CONF_DYNAMIC_PRESET_DELTA_COOL_MAX`, `_MILD_MAX`, `_HOT_MAX`, `_DWELL_MINUTES`, `_HYSTERESIS_F` already exist from v4.7.1).

**Form layout:**
1. Master enable toggle — mirrors `EnergyCoordinator._dynamic_preset_enabled` (the backing field of the migrated switch in D2). Toggling here writes the same field the switch writes.
2. House-wide settings section:
   - `CONF_DYNAMIC_PRESET_DELTA_COOL_MAX` (default -2.0; range -10..0; step 0.5)
   - `CONF_DYNAMIC_PRESET_DELTA_MILD_MAX` (default +8.0; range 0..15; step 0.5)
   - `CONF_DYNAMIC_PRESET_DELTA_HOT_MAX` (default +18.0; range 10..30; step 0.5)
   - `CONF_DYNAMIC_PRESET_DWELL_MINUTES` (default 60; range 15..240; step 5)
   - `CONF_DYNAMIC_PRESET_HYSTERESIS_F` (default 2.0; range 0.5..5.0; step 0.5)
3. Per-zone summary: N rows where N = `len(iter_canonical_hvac_zones(self.hass))`. Each row inlines the same fields as Surface 2 via `_build_dynamic_preset_schema(zone_name)`. House-wide settings sit ABOVE the per-zone repeat.

**Sync invariant:**
- Surface 1 and Surface 2 BOTH call `_build_dynamic_preset_schema` — schema text never inlined per-surface.
- Surface 1 and Surface 2 BOTH call `_validate_dynamic_preset_input` — validation logic identical.
- House-wide CONFs stored at CM `entry.options[<conf_key>]`.
- Per-zone CONFs stored at ZM `entry.options["zones"][zone_name][<conf_key>]` (existing Surface 2 storage pattern at config_flow.py:5132-5140).
- Either surface writes; the other reads on next form open (verified via test §D1.Test below).

**Validation parity (both surfaces):**
- `cool_low ≤ cool_high − MIN_DEADBAND` per bucket (existing rule from `_build_dynamic_preset_schema`).
- Sleep `cool_high + offset ≥ 74.0` (`SLEEP_FLOOR`).
- House-wide bucket boundary ordering: `DELTA_COOL_MAX < DELTA_MILD_MAX < DELTA_HOT_MAX`. **NEW invariant introduced by D1**; Surface 2 inherits when it acquires house-wide editing.

**Out of scope for D1:**
- Surface 1 does NOT expose `CONF_DYNAMIC_PRESET_PRIORITY` (priority remains at default 30; only adjustable by code).
- Surface 1 does NOT add new bucket dimensions (e.g., "rainy" or "windy"); buckets remain `cool/mild/hot/extreme`.
- Surface 1 does NOT allow per-zone bucket boundary overrides; boundaries are house-wide only.

**Acceptance criteria:**
- **Verify:** Settings → Devices & Services → URA Coordinator Manager → Configure menu shows "Dynamic Preset" option under HVAC step.
- **Verify:** Opening the step renders master enable + 5 house-wide fields + N per-zone repeat sections where N matches `len(iter_canonical_hvac_zones)`.
- **Verify:** Editing any field through Surface 1 and saving causes that change to appear on next open of Surface 2 for the same zone.
- **Verify:** Editing the SAME field through Surface 2 then re-opening Surface 1 shows the Surface-2 edit. Bidirectional.
- **Verify:** Invalid input (e.g., `cool_low=78, cool_high=77`) is rejected with the same error string regardless of which surface submitted it.
- **Verify:** Invalid bucket-boundary ordering (e.g., `MILD_MAX=20 > HOT_MAX=15`) is rejected with `"dynamic_preset_bucket_boundary_disorder"` error.
- **Sensor:** No new sensor for D1 (form-only deliverable).
- **Test:** `test_v472_d1_surface1_renders_canonical_zones`
- **Test:** `test_v472_d1_validation_parity_both_surfaces`
- **Test:** `test_v472_d1_storage_invariant`
- **Test:** `test_v472_d1_house_wide_boundary_order`
- **Live:** Open Configure → URA Coordinator Manager → HVAC → Dynamic Preset on live HA; verify all N rows visible, named per `iter_canonical_hvac_zones[*].zone_name`.
- **Live:** Edit a per-zone offset through Surface 1; close form; open Surface 2 (Zone Manager → zone → zone_dynamic_preset); verify the edit is shown.

---

### D2 — Migrate `ECDynamicPresetSwitch` from EC Device → HVAC Coordinator Device

**Description:** Re-author the master DPM kill switch as a new class `HVACDynamicPresetSwitch` (formerly `ECDynamicPresetSwitch`) attached to the HVAC Coordinator device. Backing field stays `EnergyCoordinator._dynamic_preset_enabled` — the runtime evaluation lives in EC; the device association is presentational.

**Critical unique_id strategy:**
- **PRESERVE `unique_id` UNCHANGED** at `f"{DOMAIN}_energy_dynamic_preset_enabled"`. Entity_registry row is keyed on (`platform`, `domain`, `unique_id`); preserving unique_id keeps the same `entity_id` regardless of which device the entity claims.
- Change `DeviceInfo.identifiers` to `{(DOMAIN, "hvac_coordinator")}` so the entity moves to the HVAC Coordinator device card.
- Change `_attr_name` to `"02 · Dynamic Preset Auto-Adjust"` (frontrunner — see §13 Open Questions).
- **Default flip OFF → ON.** Rationale: the feature is a no-op for any zone that hasn't opted in (`CONF_ZONE_DYNAMIC_PRESET_ENABLED` defaults False per-zone). The OFF default was over-conservative.
- **Migration: respect user-saved OFF.** If `last_state.state == "off"` at `async_added_to_hass`, restore OFF — do not force-flip explicit user OFF to ON. The flip applies ONLY to first-time install or absent saved state.

**HA entity_registry behavior (verified uncertainty — see §13):** Per HA developer docs, the entity is looked up by `(platform, domain, unique_id)`. Changing only `DeviceInfo.identifiers` should reassign the entity's device association on the next platform setup. Builder MUST verify before deploy. Mitigation: pre-deploy validation test verifies entity_registry shows the same `entity_id` post-restart, only the `device_id` changed.

**Numeric prefix audit:** Before assigning `"02 ·"` to the migrated switch, **the builder MUST grep the HVAC Coordinator device's existing entities** for friendly names with numeric prefixes and choose a non-colliding low band. Numeric prefix is the ONLY native lever for HA frontend sort (Intl.Collator numeric:true) per memory `project_ha_frontend_entity_sort.md`.

**Files touched:**
- `switch.py`: define new `HVACDynamicPresetSwitch(SwitchEntity, RestoreEntity)` class. Delete or comment-out the factory call at line 892-895. Wire setup in `async_setup_entry` to instantiate the new class when CM entry loads. ~80 LoC net add.
- `strings.json` + `translations/en.json`: rename label.

**Out of scope for D2:**
- D2 does NOT move the backing field `_dynamic_preset_enabled` from EC to HVAC. The runtime evaluation continues to live in EC's `_async_evaluate_dynamic_presets`.
- D2 does NOT introduce a new `unique_id` (would orphan entity_registry row).
- D2 does NOT touch `_async_evaluate_dynamic_presets` or any downstream emit logic.

**Acceptance criteria:**
- **Verify:** Post-deploy + restart, the switch appears on the HVAC Coordinator device card, NOT the Energy Coordinator card.
- **Verify:** entity_registry shows the entity with `entity_id = switch.ura_energy_coordinator_dynamic_preset_overrides` (preserved) and `device_id` = HVAC Coordinator device id (changed).
- **Verify:** Existing automations referencing the old entity_id continue to function (entity_id preserved).
- **Verify:** First-time install (no saved RestoreEntity state) → switch starts ON.
- **Verify:** Existing install with explicit user-saved OFF → switch restores OFF.
- **Verify:** Toggling the switch from the HVAC device page sets `EnergyCoordinator._dynamic_preset_enabled` on the backing coord.
- **Sensor:** `sensor.ura_hvac_coordinator_active_preset_overrides` (existing v4.7.1 D4) reflects 0 when switch is OFF.
- **Test:** `test_v472_d2_unique_id_preserved`
- **Test:** `test_v472_d2_device_info_targets_hvac`
- **Test:** `test_v472_d2_default_on_first_install`
- **Test:** `test_v472_d2_restore_respects_user_off`
- **Live:** Restart HA, verify the entity appears under the HVAC Coordinator device. Toggle off, verify `_dynamic_preset_enabled` becomes False.

---

### D3 — Rename `HVACGuestModeActuationSwitch` Label

**Description:** Existing `HVACGuestModeActuationSwitch._attr_name = "Guest Mode Actuation"` (switch.py:920) is mislabeled. The switch gates `_apply_house_state_presets` for ALL preset-override sources (DPM today, Guest Mode preset overrides when Phase 1 D2 fires for guest house_state, and any future actuator that consumes the OverrideEngine resolved-range path).

**Frontrunner label:** `"01 · Custom Preset Ranges"` (see §13 Open Questions).

**Critical: unique_id preserved.** `unique_id = f"{DOMAIN}_hvac_coordinator_guest_mode_actuation_enabled"` MUST NOT change.

**Files touched:**
- `switch.py`: change `_attr_name` at line 920 only. ~1 LoC.
- `strings.json` + `translations/en.json`: ~3 entries.

**Out of scope for D3:**
- D3 does NOT change backing field name.
- D3 does NOT change unique_id.
- D3 does NOT change gate semantics in `_apply_house_state_presets` / `_async_apply_preset_overrides`.

**Acceptance criteria:**
- **Verify:** HVAC Coordinator device page shows the entity with new label.
- **Verify:** entity_id unchanged: `switch.ura_hvac_coordinator_guest_mode_actuation_enabled`.
- **Verify:** Toggling OFF still skips `_async_apply_preset_overrides` (existing behavior; regression check).
- **Sensor:** `sensor.ura_hvac_coordinator_active_preset_overrides` still shows correct count when toggled.
- **Test:** `test_v472_d3_unique_id_unchanged`
- **Test:** `test_v472_d3_attr_name_renamed`
- **Live:** Existing automation (if any) targeting the old entity_id continues to fire.

---

### D4 — Per-Room `is_guest_room` + Threshold CONFs

**Description:** Add two per-Room config fields to the room reconfigure step:
- `CONF_ROOM_IS_GUEST_ROOM: bool` (default False).
- `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN: int` (default 30, range 5..240, step 5).

Both persist into the room entry's `options` dict.

**Files touched:**
- `const.py`: add CONF strings.
- `config_flow.py:async_step_basic_setup`: extend `schema_fields` with the two new optional fields.
- `strings.json` + `translations/en.json`: ~6 entries.
- `presence.py`: read at startup in `_discover_guest_rooms()`.

**Out of scope for D4:**
- D4 does NOT include any UI for marking specific GUESTS vs FAMILY person entities.
- D4 does NOT change AWAY semantics for guest rooms.
- D4 does NOT add Feature A's "unoccupied guest room warmer offset".

**Acceptance criteria:**
- **Verify:** Room reconfigure step renders the two new fields with correct defaults.
- **Verify:** Saving the form persists both fields to `room_entry.options`.
- **Verify:** Existing rooms (no prior save) read defaults (False, 30) correctly.
- **Test:** `test_v472_d4_form_fields_render`
- **Test:** `test_v472_d4_storage_roundtrip`
- **Test:** `test_v472_d4_defaults_when_absent`
- **Live:** Open a room entry in HA UI → Reconfigure → verify "Is Guest Room" checkbox + "Guest occupancy threshold" slider.

---

### D5 — Phase 2 Feature B: Sustained-Occupancy Guest Signal

**Description:** Add a new boolean signal `guest_room_gate_armed` to `PresenceCoordinator._guest_gate_armed()` that fires when:
1. A room marked `is_guest_room=True` (D4) has been continuously occupied for ≥ `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN` minutes, AND
2. The occupant is NOT a known person, AND
3. No flapping — continuous occupancy required.

The existing v4.6.2.2 unidentified-persons gate (`unid_gate_armed`) is unchanged. Composition: `guest_gate_armed = unid_gate_armed OR guest_room_gate_armed`.

**Confidence layering math:**
- When `unid_gate_armed` fires alone: `_confidence = 0.8` (existing).
- When `guest_room_gate_armed` fires alone: `_confidence = 0.9` (higher specificity).
- When both fire same inference tick: `_confidence = max(0.8, 0.9) = 0.9`.

**Anti-flap state machine (per designated guest room):**

```
_guest_room_state: Dict[str, dict] = {
    room_name: {
        "first_seen": Optional[datetime],
        "current_occupancy_known": bool,
    }
}
```

State transitions on room occupancy state-change event:
1. Room goes occupied + occupant unknown → `first_seen = utcnow()` (if None); `current_occupancy_known = False`.
2. Room goes occupied + occupant identified as known person → reset `first_seen = None`; `current_occupancy_known = True`.
3. Room goes unoccupied → reset `first_seen = None`.

Gate evaluation: for each designated guest room: if `first_seen is not None` AND `(utcnow() - first_seen).total_seconds() / 60 ≥ threshold_min` AND NOT `current_occupancy_known` → `guest_room_gate_armed = True`.

**Cross-restart resilience:** `_guest_room_first_seen` is in-memory only. On HA restart, the timer resets. **Explicit decision:** do not persist this state — restart is rare; a guest occupying a room for 30 minutes will re-arm within 30 minutes of restart.

**Exit semantics:** Immediate exit when `guest_room_gate_armed` clears, matching the existing unid-path's "cheaper to leave than to enter" comment.

**Files touched:**
- `presence.py`: state field + listener registration in `_discover_guest_rooms()` + gate-eval + exit-condition + confidence layering.
- New tests at `quality/tests/test_v472_feature_b_guest_signal.py`.

**Out of scope for D5:**
- D5 does NOT add a diagnostic sensor exposing `guest_room_gate_armed`.
- D5 does NOT change the existing `unid_gate_armed` confidence value 0.8.
- D5 does NOT introduce per-guest-room confidence weighting.
- D5 does NOT include guest-person designation UI.

**Acceptance criteria:**
- **Verify:** Marking a room as `is_guest_room=True` and an unknown occupant present ≥30 min causes house_state to enter GUEST.
- **Verify:** A known-person occupying a designated guest room does NOT trigger GUEST mode.
- **Verify:** A designated guest room with intermittent occupancy does NOT trigger GUEST mode.
- **Verify:** When both `unid_gate_armed` and `guest_room_gate_armed` fire same tick, confidence reflects 0.9.
- **Verify:** When only `guest_room_gate_armed` fires, GUEST mode entered with confidence 0.9.
- **Verify:** When only `unid_gate_armed` fires, GUEST mode entered with confidence 0.8 (regression).
- **Verify:** Disabling `is_guest_room` on a room removes its listener (no leak).
- **Sensor:** `sensor.ura_presence_house_state.attributes.confidence` reflects 0.9 when guest-room path fires.
- **Test:** `test_v472_d5_guest_room_threshold_met_arms_gate`
- **Test:** `test_v472_d5_known_person_does_not_arm`
- **Test:** `test_v472_d5_intermittent_occupancy_resets_first_seen`
- **Test:** `test_v472_d5_both_paths_max_confidence`
- **Test:** `test_v472_d5_unid_path_unchanged_regression`
- **Test:** `test_v472_d5_listener_cleanup_on_unload`
- **Test:** `test_v472_d5_listener_cleanup_on_room_unflagged`
- **Test:** `test_v472_d5_exit_condition_requires_both_false`
- **Live:** Designate a real bedroom as `is_guest_room=True`; simulate sustained occupancy for 30+ min by an unknown person; observe house_state transition to GUEST.

---

## 5. Sync + Guarded Duplication Invariant

The two DPM surfaces must produce **identical state** from identical edits. Enforced by:

1. **Shared schema helper.** Both `async_step_zone_dynamic_preset` and `async_step_hvac_dynamic_preset` call `_build_dynamic_preset_schema(zone_name)`. No surface inlines the schema.
2. **Shared validation helper.** New `_validate_dynamic_preset_input(user_input)` extracted from Surface 2's inline validation and called by both surfaces with identical error-string mapping.
3. **Single storage path per dimension.** House-wide CONFs → CM `entry.options`. Per-zone CONFs → ZM `entry.options["zones"][zone_name]`. Either surface writes; the other reads on next form open.

**Programmatic invariant tests:**
- `test_v472_dpm_surface_schema_identity`
- `test_v472_dpm_validation_parity`
- `test_v472_dpm_storage_roundtrip_both_surfaces`

---

## 6. Migration Safety for D2 (Entity Registry + RestoreEntity)

**The migration question:** when v4.7.2 ships, an existing user has the v4.7.1 `ECDynamicPresetSwitch` with unique_id `{DOMAIN}_energy_dynamic_preset_enabled` already registered in entity_registry with `device_id` pointing to the EC device. After upgrade, the new `HVACDynamicPresetSwitch` claims the same unique_id but declares `DeviceInfo.identifiers = {(DOMAIN, "hvac_coordinator")}`.

**Expected HA behavior:** HA looks up the entity by `(platform, domain, unique_id)`, finds the existing registry row, updates `device_id` to match the new `DeviceInfo.identifiers` resolution. `entity_id` preserved.

**Uncertainty (flagged in §13):** the exact HA behavior when only `DeviceInfo.identifiers` changes between platform setups was not verifiable from HA dev docs. Builder MUST verify before deploy. If HA does NOT auto-reassign device, builder ADDS a one-shot `async_setup_entry`-level migration helper.

**RestoreEntity behavior:**

| last_state | Behavior |
|---|---|
| None (first-time install) | `_dynamic_preset_enabled = True` (D2 default-flip). |
| "on" | `_dynamic_preset_enabled = True`. |
| "off" | `_dynamic_preset_enabled = False`. **Respects user's explicit OFF.** |

The deferred-restore SIGNAL_ENERGY_COORDINATOR_READY pattern must be replicated in the new class.

---

## 7. Confidence Layering Math (D5)

```
guest_gate_armed = unid_gate_armed OR guest_room_gate_armed

if guest_room_gate_armed and unid_gate_armed:
    confidence = max(0.8, 0.9) = 0.9
elif guest_room_gate_armed:
    confidence = 0.9
elif unid_gate_armed:
    confidence = 0.8
```

**Why max() not weighted-average:** the two signals observe different aspects (transient identity gap vs sustained-occupancy pattern). Averaging would dampen the stronger signal. Taking the max preserves "the best evidence we have for guest presence."

**Rationale for 0.9 vs 0.8:**
- Existing 0.8 (unid path): vulnerable to Bermuda BLE bounces, Frigate camera-census transient mis-counts.
- New 0.9 (guest-room path): three layered guards (designated room + sustained occupancy + known-person filter + anti-flap) all pass.
- Gap of 0.1: small enough that downstream sensors don't differentiate; large enough that diagnostic users see which path fired.

---

## 8. Bug Class Compliance Matrix

| Class | Risk | Addressed where |
|---|---|---|
| #2 Config Storage Pattern | LOW | D1/D4 use `entry.options` merge pattern |
| #5 Startup Race | MEDIUM | D2 inherits `SIGNAL_ENERGY_COORDINATOR_READY` deferred-restore pattern. D5 listener registration runs in `async_setup` after `_discover_zones`. |
| #10 Cross-Restart State Loss | LOW | D2 RestoreEntity preserves user OFF. D5 in-memory state intentionally not persisted. |
| #11 UTC vs Local | MEDIUM | D5 `_guest_room_first_seen` uses `dt_util.utcnow()`. |
| #14 Config Snapshot Staleness | MEDIUM | D5 reads `is_guest_room` + threshold fresh from `entry.options`. |
| #19 Untracked Background Tasks | LOW | D5 listeners registered via `async_track_state_change_event`; unsubs tracked. |
| #22 Enum Mismatch | LOW | D1 reuses existing `BucketClass(StrEnum)`. |
| #23 Observation Mode Gating | MEDIUM | Observation-mode suppression at the dispatch site catches both paths. |
| #32 Form Field With No Runtime Reader | MEDIUM | Every new CONF has runtime reader. AST source-contract test added. |
| #36 Per-Zone Entity Bypasses ZoneManager Dedup | MEDIUM | D1 enumerates zones via `iter_canonical_hvac_zones`. |
| #38 Listener Cleanup | HIGH | D5 listeners registered with `async_on_remove(unsub)`. |
| #42 Lambda + async_create_task | LOW | D5 listener callback is `@callback`-decorated bound method. |
| #45 Lambda Closure Captures Stale Local | LOW | Patterns from v4.7.1 fix-up (bound methods on `self`) followed. |

---

## 9. Tier 2 Review Framings — Two Parallel Reviews

### Reviewer A — Correctness + Sync Invariants + Form / Validation / Edge Cases

**Scope:** D1, D2, D3, D4.

**Focus areas:**
- Shared schema helper called identically; no inline schema in Surface 1.
- Shared validation helper extracted correctly; both surfaces produce same error keys.
- New house-wide boundary ordering validator covers all edge cases.
- D2 entity_registry preservation: unique_id string IDENTICAL.
- D2 RestoreEntity behavior covers all three cases.
- D2 default-flip OFF→ON does NOT clobber existing user-saved OFF.
- D3 unique_id unchanged.
- D4 form fields render with correct defaults.
- D1 form rejects invalid input with same error regardless of surface.
- Per-zone repeat in D1 form correctly handles zero canonical HVAC zones.

**Bug classes targeted:** #2, #14, #22, #32, #36.

**Deliverable:** `docs/reviews/code-review/v4.7.2_reviewerA_correctness.md`.

### Reviewer B — Async + Lifecycle + Presence Signal Integration + Migration Safety

**Scope:** D2 device migration semantics, D5 signal chain end-to-end, listener lifecycle.

**Focus areas:**
- D2 entity_registry device-reassignment behavior.
- D2 deferred-restore path preserved in the new class.
- D2 backing field accessed across coord boundaries.
- D5 listener registration; unsub handles tracked and cleaned.
- D5 `_guest_room_first_seen` timestamp UTC-aware.
- D5 known-person filter handles `person_coordinator` being None.
- D5 OR composition correct under all 4 combinations.
- D5 GUEST mode exit when only `guest_room_gate_armed` was True.
- D5 confidence math attribution.
- HA restart resilience.
- Cross-coordinator interaction ordering at startup.

**Bug classes targeted:** #5, #10, #11, #19, #21, #23, #38, #42.

**Deliverable:** `docs/reviews/code-review/v4.7.2_reviewerB_async_lifecycle.md`.

---

## 10. Live Validation (Post-Deploy)

1. **Entity location:** `switch.ura_energy_coordinator_dynamic_preset_overrides` (entity_id preserved) appears on the **HVAC Coordinator** device card.
2. **Switch order:** Switches on the HVAC Coordinator device sort with `"01 · Custom Preset Ranges"` before `"02 · Dynamic Preset Auto-Adjust"`.
3. **CM menu surface:** Settings → Devices & Services → URA Coordinator Manager → Configure → HVAC step → "Dynamic Preset" option visible.
4. **Surface 1 renders zone rows:** Opening Surface 1 shows N per-zone repeat blocks where N = number of canonical HVAC zones.
5. **Bidirectional sync:** Edit zone offset in Surface 1, save, open Surface 2 — edit visible. Repeat reverse.
6. **Guest signal — D5 live:** Designate a real room as `is_guest_room=True`; sustained occupancy ≥30 min by unknown person → `sensor.ura_presence_house_state.state == "guest"` AND `attributes.confidence == 0.9`.
7. **Guest signal — known person regression:** Known person occupying same room → house_state stays HOME_*.
8. **Frame-helper invariant:** Zero `"calls async_create_task from a thread other than the event loop"` warnings.
9. **No new HA-core warnings:** `ha_get_logs(source="system_service", slug="core")` shows zero new ERROR entries.

---

## 11. File Touch List (Estimated LoC)

| File | Add | Modify | Delete | Notes |
|---|---|---|---|---|
| `switch.py` | ~50 | ~10 | ~5 | D2 new class; D3 rename; v4.7.1 factory call removed |
| `config_flow.py` | ~280 | ~30 | 0 | D1 Surface 1; D4 room form fields |
| `const.py` | ~4 | 0 | 0 | D4 CONF strings |
| `presence.py` | ~95 | ~25 | 0 | D5 state + listener + gate-eval + exit + confidence |
| `strings.json` | ~40 | ~3 | 0 | D1/D3/D4 labels |
| `translations/en.json` | ~40 | ~3 | 0 | mirror of strings.json |
| `quality/tests/test_v472_dpm_surfaces.py` (NEW) | ~250 | 0 | 0 | D1/D2/D3 tests (~20) |
| `quality/tests/test_v472_feature_b_guest_signal.py` (NEW) | ~200 | 0 | 0 | D4/D5 tests (~12) |
| `docs/readmes/README_v4.7.2.md` (NEW) | ~150 | 0 | 0 | Release notes |

**Total estimated LoC:** ~1,560 new + ~70 modified + ~5 deleted across 10 files.

---

## 12. Pre-Deploy Tags

```
git tag pre-review-v4.7.2 -m "Pre-review baseline for v4.7.2"
git tag pre-fixup-v4.7.2 -m "Pre-fixup baseline before applying Reviewer A/B findings"
git tag post-fixup-v4.7.2 -m "Post-fixup, ready for deploy"
```

---

## 13. Open Questions — User-Confirmable

These have **reasonable-call defaults** the builder will adopt per user's autonomous-execution directive (2026-05-28). User may redirect if needed.

1. **Master toggle labels.** Adopt frontrunners: `"01 · Custom Preset Ranges"` (D3) and `"02 · Dynamic Preset Auto-Adjust"` (D2). `·` separator.
2. **Numeric prefix range.** Builder audits HVAC Coordinator device for existing numeric prefixes and picks a non-colliding low band.
3. **D2 default-flip OFF → ON NM notification.** YES — fire a one-shot info-level NM notification on first install-after-v4.7.2 when default-flip applies. Logged via `_LOGGER.info`. Existing user-saved OFF preserved.
4. **D5 exit semantics.** Immediate exit when `guest_room_gate_armed` clears, matching existing unid-path's "cheaper to leave than to enter."
5. **HA entity_registry behavior (D2).** Builder MUST run dev-instance pre-flight test before deploy. If HA does NOT auto-reassign, builder adds one-shot migration helper. **Block deploy on this verification.**
6. **D5 listener target entity.** Builder verifies the correct entity_id for room occupancy subscription. If room uses tier-1 mmWave/PIR, use room occupancy entity_id; if tier-3 BLE-only, fall back to `_zone_trackers[zone_name]` derived state.

---

## 14. Risk Register

| Risk | Severity | Mitigation |
|---|---|---|
| D2 entity_registry breaks entity_id | HIGH | §6 pre-flight verification on dev instance. Test `test_v472_d2_unique_id_preserved`. Live validation §10.1. |
| D2 default-flip ON surprises user | MEDIUM | NM notification per Open Question #3. Per-zone opt-in defaults False. |
| D5 listener leak across reconfigure | MEDIUM | Bug Class #38 — explicit unsub tracking. |
| D5 known-person filter incorrectly flags family as unknown → false GUEST mode | MEDIUM | 30-min threshold + sustained occupancy filter. Raise threshold if observed. |
| D1 form unwieldy with 6+ zones | LOW | HA UI handles scrolling. Defer collapse polish. |
| Surface 1 + Surface 2 schema drift over time | MEDIUM | Shared schema helper + CI test `test_v472_dpm_surface_schema_identity`. |

---

## 15. Acceptance Criteria Summary

Release is "done" when:

- All v4.7.2 tests pass (target: ~32 new tests across D1-D5).
- Isolation check (Bug Class #44) shows 0 new failures.
- Tier 2 review docs land; all CRITICAL + HIGH issues fixed.
- Pre-deploy dev-instance test of D2 entity_registry device reassignment succeeds.
- Live validation §10 all-green.
- `switch.ura_energy_coordinator_dynamic_preset_overrides` appears on HVAC Coordinator device with new label and numeric prefix.
- `switch.ura_hvac_coordinator_guest_mode_actuation_enabled` shows renamed label without entity_id change.
- Designated guest room + sustained unknown occupancy ≥30 min → GUEST mode with confidence 0.9.
- `docs/readmes/README_v4.7.2.md` describes user-visible changes.

---

## 16. What This Cycle Does NOT Do

v4.7.2 polishes the user-facing affordance of DPM (HVAC Coordinator surface + label rename + numeric reorder + default flip) and adds the second additive path to the existing guest mode gate (per-Room is_guest_room + sustained-occupancy signal with confidence 0.9 layering). It does NOT add new actuators (lighting, music, NM, covers — scope-clipped), does NOT migrate the DPM backing field from EC to HVAC (only device association moves), does NOT introduce Phase 1 D3 per-zone Guest UI override fields (obsoleted by DPM offset-reset), does NOT ship Phase 2 Feature A "unoccupied guest room warmer offset" (premature; subsumed by AWAY semantics), and does NOT change the existing v4.6.2.2 unidentified-persons gate semantics or confidence value 0.8 (the new path is strictly additive).
