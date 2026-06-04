# PLANNING v4.7.7 — AC Nudge / AC Reset Decouple + DPM Sensor Cleanup (combined Tier 2 cycle)

**Status:** Plan ready for build
**Tier:** Tier 2 (TWO parallel staff-engineer reviews, different framings)
**Predecessor:** v4.7.6.1 (Helper text + ExcessSolarSOC promotion) — LIVE 2026-05-29
**User decision 2026-05-29:** bundle AC nudge decouple + DPM sensor cleanup into one release
**Filed:** 2026-05-29
**Recall:** "Plan v4.7.7 — AC nudge decouple + DPM cleanup" / "Resume v4.7.7"

---

## 1. Tier Classification

**Tier 2.** Two concern groups in one cycle; touches HVAC override gating + entity registry migrations across two device boundaries.

Tier 2-DB trigger check:

| Tier 2-DB Trigger | Hit? | Notes |
|---|---|---|
| Touches `database.py` DAO definitions | No | No new/changed DAO. `_db.get_ac_reset_state` / `save_ac_reset_state` / `get_global_last_hard_reset_ts` are read-only at the touched sites. |
| Migrates ≥3 callers to a new DAO | No | No new DAO. |
| Changes payload shape of a dispatched event / persisted record | No | `ac_ramp_events` schema unchanged. DPM signal payloads unchanged. `skipped_zones` attr gains a `skip_reason` companion attr if B2.fix lands — additive only, not a payload-shape change to a dispatched event. |
| Adds behavioral test infrastructure against real schemas | No | Test additions ride existing fixtures. |
| Followed within 1-2 versions by a planned schema migration | No | No upcoming schema migration depends on this. |

**Tier 2 dispatch:** TWO parallel reviewers, deliberately disjoint framings per §10 to prevent blind-spot overlap.

---

## 2. Goal + Why

**Two concern groups, one release window:**

### Group A — AC Nudge / AC Reset decouple

Today (post-v4.7.4.4 live), `switch.ura_hvac_coordinator_ac_reset` is the SINGLE Gate 0 (`hvac_override.py:846`) for BOTH the soft-nudge detection iteration AND the hard-reset escalation path. Turning AC Reset OFF disables soft nudges too — that was discovered live during v4.7.6.1 close-out diagnostics ("why aren't nudges engaging post-boot? — ac_reset switch is OFF").

User-confirmed design (memo `project_ac_nudge_decouple_backlog.md`, 2026-05-29):
- "AC Reset" = standalone feature (off → wait → restore mode flow)
- "AC Nudge" = standalone feature (bump +nudge_size °F, restore after duration) with its own toggle
- BOTH enabled → chain (current behavior: failed nudge eval escalates to reset)
- Nudge ON / Reset OFF → soft-nudge detection runs; escalation path skipped cleanly
- Nudge OFF / Reset ON → soft-nudge gates skipped; reset only via direct triggers
- Both OFF → arrester gates short-circuit, no work

Plus the **lockout side-effect bug** the current architecture papers over: when `_hard_reset_daily_limit=0`, `_perform_hard_reset_escalation` engages lockout on the FIRST failed nudge eval (because `int(state.get("hard_reset_count", 0)) >= 0` is true immediately, line 1469). Decoupling cleanly via `_ac_reset_enabled=False` MUST skip the escalation WITHOUT engaging lockout.

**Adjacent bug bundled:** `sensor.ura_hvac_ac_ramp_state_*` and `sensor.ura_hvac_ac_ramp_last_action_*` entity_ids are misaligned with their friendly-name zone labels (per v4.7.5 close-out backlog note and `project_ac_nudge_decouple_backlog.md`). Entity_id slug `_back_hallway` shows friendly name "(Entertainment + Master Suite)", `_entertainment` shows "(Upstairs)", `_master_suite` shows "(Back Hallway)". Root cause (read at planning): `unique_id` is built from canonical `zone_id` (thermostat-derived, stable across boots), but `_attr_name` uses `zone_name` (merged display label, ordering-dependent). HA's entity_id slug is generated from the FIRST `_attr_name` it saw at first registration — so a different merge ordering on a later boot produces the mismatch.

### Group B — DPM sensor cleanup

Surfaced during v4.7.6.1 live validation. Three sub-issues from memo `project_dpm_sensor_cleanup_backlog.md`:

1. **Orphan registry entries.** Three legacy `sensor.ura_energy_coordinator_dynamic_preset_bucket_<zone>` entities sit `Unknown` permanently — class was renamed to `DynamicPresetActiveBucketSensor` with new `unique_id = f"{DOMAIN}_dynamic_preset_active_bucket_{zone_id}"`. Old `unique_id = f"{DOMAIN}_dynamic_preset_bucket_{zone_id}"` entries have no class producing them.
2. **DPM zone-skip pattern.** `sensor.ura_energy_coordinator_dynamic_preset_overrides_applied.skipped_zones: ["zone_1", "zone_2", "zone_3"]` — DPM is skipping every zone right now. Investigation needed before fix.
3. **Device-assignment inconsistency.** DPM master switch lives on HVAC Coordinator (v4.7.2 D2 migration), but DPM observability sensors (Range, ActiveBucket, OverridesApplied) still on Energy Coordinator. User looks for DPM observability on the HVAC card and doesn't find it.

**Why bundle A + B in one release:** Both groups are mechanical entity-registry-touching cycles with tight blast radius. Single deploy window + single live validation. Reviewer A focuses on correctness and state-machine math; Reviewer B focuses on async lifecycle + entity-registry safety. Disjoint enough to cover both groups in parallel.

---

## 3. Discovery — Read Before Build (Mandatory)

Builder MUST read these before code changes. Cite file:line in code comments where the patterns are reused.

| File | Lines | Why |
|---|---|---|
| `domain_coordinators/hvac_override.py` | 70-153 (`__init__`) | Existing `_ac_reset_enabled = True` instance attr (line 94). Add `_ac_nudge_enabled = True` adjacent with same default. |
| `domain_coordinators/hvac_override.py` | 220-239 (`ramp_master_enabled` property + setter) | Pattern for new `ac_nudge_enabled` and `ac_reset_enabled` properties/setters. Note the setter side-effect (cancels in-flight nudges on OFF) — DO NOT mirror that side-effect for nudge OFF unless explicitly designed. |
| `domain_coordinators/hvac_override.py` | 820-963 (`check_ac_reset` decision body) | Gate 0 lives at line 846. Split per A2 design. Gates 1-9 logic untouched apart from gate 0 split. |
| `domain_coordinators/hvac_override.py` | 1381-1444 (`_evaluate_nudge_outcome`) | The "ineffective → escalate" call at line 1434 (`await self._perform_hard_reset_escalation`). Reviewer A traces: with reset disabled, escalation early-returns; with nudge disabled, this method never runs. |
| `domain_coordinators/hvac_override.py` | 1446-1540 (`_perform_hard_reset_escalation` + `_engage_lockout`) | A3 early-return guard goes at the TOP of `_perform_hard_reset_escalation`. Set `zone.ramp_state = AC_RAMP_STATE_IDLE` and `return` BEFORE the lockout daily-cap check at line 1469. |
| `domain_coordinators/hvac_const.py` | 87 (`CONF_HVAC_AC_RESET_ENABLED`), 116 (`DEFAULT_AC_RESET_ENABLED = True`), 168-176 (CONF/DEFAULT ramp master + nudge size + duration) | Existing constants. Add `CONF_HVAC_AC_NUDGE_ENABLED = "hvac_ac_nudge_enabled"` and `DEFAULT_HVAC_AC_NUDGE_ENABLED = True` alongside the reset constants. |
| `switch.py` | 1383-1516 (`HVACACResetSwitch`) | Exact pattern for new `HVACACNudgeSwitch`. Mirror line-for-line: `_attr_has_entity_name`, `_attr_icon = "mdi:fan-chevron-up"` (suggested) or `"mdi:thermometer-chevron-up"`, `_attr_entity_category = EntityCategory.CONFIG`. **Critical:** mirror the v4.7.3.1 deferred-restore via `SIGNAL_HVAC_COORDINATOR_READY` + bound method handler (Bug Classes #5, #38, #19, #42 all addressed by the existing class). |
| `switch.py` | 1383-1407 (HVACACResetSwitch friendly name + unique_id) | `_attr_name = "25 · AC Reset"`. Pick a numerically-adjacent prefix for AC Nudge (suggest `"26 · AC Nudge"`) per `project_ha_frontend_entity_sort.md` (Intl.Collator numeric:true) — see §6 prefix rationale. |
| `sensor.py` | 6536-6673 (`DynamicPresetActiveBucketSensor`) | Class to keep. Device-info line `self._attr_device_info = _energy_device_info()` (line 6562) → migrate to `_hvac_device_info()` per B3. unique_id pattern at line 6560 is the NEW one (active_bucket); legacy unique_id pattern (`dynamic_preset_bucket_<zone_id>`) is what B1 sweeps. |
| `sensor.py` | 6675-6763 (`DynamicPresetRangeSensor`) | Same `_attr_device_info` migration per B3 (line 6698). |
| `sensor.py` | 6766-6866 (`DynamicPresetOverridesAppliedSensor`) | Same device migration per B3 (line 6788). `extra_state_attributes` builds `skipped_zones` (line 6848); B2.fix lands here as `skipped_zones_with_reason` companion attr or in-line list-of-dicts. |
| `sensor.py` | 6766-6866 (`extra_state_attributes` of OverridesAppliedSensor) | Current `skipped_zones` definition is "zones with no overrides this tick" — empty list returned. The reason is invisible. B2.fix exposes the reason. |
| `sensor.py` | 8823-8930 (`HVACACRampStateSensor` + `HVACACRampLastActionSensor`) | A4 bug: `unique_id = f"{DOMAIN}_hvac_ac_ramp_state_{zone_id}"` is stable, but `_attr_name = f"60 · AC Ramp State ({zone_name})"` uses the merged display label. Friendly name updates correctly on re-init but entity_id was slugified at first registration. A4.fix: rename entity_ids via `entity_registry.async_update_entity` to match the current friendly name OR rebuild friendly name to match the stable unique_id (see §5.A4 for the trade-off discussion). |
| `sensor.py` | 335-367 (per-zone sensor creation loop in `async_setup_entry`) | Per-zone sensors are created in `iter_canonical_hvac_zones` order. Verify that order is stable across boots (it is — driven by `hass.config_entries.async_entries(DOMAIN)` which is insertion-ordered). |
| `sensor.py` | 5980 area (`_energy_device_info` definition) and the `_hvac_device_info` equivalent | Confirm `_hvac_device_info` exists and binds to `(DOMAIN, "hvac_coordinator")`. If not, builder MUST find the canonical helper used by existing HVAC-bound sensors before D3 (search for `identifiers={(DOMAIN, "hvac_coordinator")}` in sensor.py). |
| `domain_coordinators/energy.py` | 2608-2785 (`_async_evaluate_dynamic_presets`) | DPM evaluation entry point. Trace why each zone returns `[]` from `async_evaluate_and_emit`. Lines 2693-2708 already log a warning on canonical-merged-label mismatch (v4.7.5 D3). B2 investigation reads this trace + the underlying `dynamic_preset.py:async_evaluate_and_emit` skip points. |
| `domain_coordinators/dynamic_preset.py` | 320-425 (`async_evaluate_and_emit`) | Skip points return `[]` at line 342 (zone not opted in), 347 (no forecast delta). `_build_overrides` returns `[]` at 437 (unknown bucket) or 483 (home range not configured). B2 fix attaches a `skip_reason` per zone in the caller. |
| `domain_coordinators/dynamic_preset.py` | 320-360 (read of `CONF_DYNAMIC_PRESET_DWELL_MINUTES`) | Dwell gate at line 376. If elapsed_min < dwell_min, the zone stays in the current bucket (no skip, but no new override emit either). For B2, "dwell pending" needs surfacing as a skip reason. |
| `__init__.py` | 2404-2452 (v4.7.2 D2 / v4.7.3 D4 entity_registry device-reassignment block) | **Exact pattern to mirror for B3 (DPM sensor device migration) AND B1 (orphan removal).** Idempotent, uses `er.async_get_entity_id(_platform, DOMAIN, _unique_id)` + `er.async_update_entity(_entity_id, device_id=_target_device.id)`. For B1, use `er.async_remove(_entity_id)` instead. |
| `__init__.py` | 311-320 (existing `ent_reg.async_remove(entity_id)` pattern) | Reference for the remove call shape. |
| `docs/QUALITY_CONTEXT.md` | Bug Class #5, #11, #19, #20, #38, #42, #45, #46 | See §7 compliance matrix. |
| `docs/QUALITY_CONTEXT.md` | Bug Class #46 (line 1743) + "when async_update_entry IS safe" sub-section | Confirm: A4 entity_registry calls happen INSIDE setup but BEFORE `entry.add_update_listener` registration — verify the call site. The pattern at __init__.py:2404-2452 runs AFTER `async_forward_entry_setups` and AFTER `entry.async_on_unload(entry.add_update_listener(...))` at line 2454, but it does NOT call `async_update_entry` on the config entry itself; it only mutates `entity_registry`. Verify in QUALITY_CONTEXT #46 that entity_registry mutations are NOT subject to the re-entrancy hazard. |
| `graphify-out/GRAPH_REPORT.md` | (entire) | Pre-read per project CLAUDE.md. |

---

## 4. Deliverables

### Group A — AC Nudge / AC Reset decouple

---

#### A1 — New HVAC switch: AC Nudge

**Description:** New `switch.ura_hvac_coordinator_ac_nudge` entity (default ON), backed by a `CONF_HVAC_AC_NUDGE_ENABLED` config-flow option on the HVAC Coordinator entry. Mirror the existing `HVACACResetSwitch` class line-for-line including deferred-restore via `SIGNAL_HVAC_COORDINATOR_READY`.

**Files touched:**
- `switch.py` — NEW class `HVACACNudgeSwitch` (~130 LoC) mirroring `HVACACResetSwitch`. Friendly name `"26 · AC Nudge"`. unique_id `f"{DOMAIN}_hvac_ac_nudge"`. Device: HVAC Coordinator.
- `switch.py` — register the new switch in the CM-coordinator switch list adjacent to `HVACACResetSwitch` instantiation.
- `domain_coordinators/hvac_const.py` — add `CONF_HVAC_AC_NUDGE_ENABLED: Final = "hvac_ac_nudge_enabled"` and `DEFAULT_HVAC_AC_NUDGE_ENABLED: Final = True`.
- `strings.json` + `translations/en.json` — `entity.switch.hvac_ac_nudge.name` = "AC Nudge"; `data_description` block describing what AC Nudge does in 2-3 sentences (mechanics only, per v4.7.6.1 helper text discipline).

**Mirror-pattern compliance:**
- `RestoreEntity` for runtime store of user toggle state (per `feedback_ura_mirror_pattern.md`).
- `entry.options` is seed-only; runtime store is the switch's restored state.
- Deferred-restore via `SIGNAL_HVAC_COORDINATOR_READY` (Bug Class #5).
- Unsub tracked via `async_on_remove` (Bug Class #38).
- Bound-method handler `_handle_hvac_ready` (Bug Class #42 — not a lambda).
- `@callback` decorator on the sync handler (Bug Class #19).

**Acceptance criteria:**
- **Verify:** `switch.ura_hvac_ac_nudge` appears on HVAC Coordinator device after first boot post-v4.7.7. Default state ON.
- **Verify:** Friendly name renders as "26 · AC Nudge" with translation-driven helper text visible in the More Info dialog.
- **Sensor:** N/A (switch only).
- **Test:** `test_v477_a1_ac_nudge_switch_exists` — schema check: class exists, has correct unique_id format, device_info points at HVAC Coordinator.
- **Test:** `test_v477_a1_ac_nudge_default_on` — fresh-install state is ON; setter wired to `override_arrester.ac_nudge_enabled`.
- **Test:** `test_v477_a1_ac_nudge_deferred_restore` — when HVAC coord absent at `async_added_to_hass`, defers; when `SIGNAL_HVAC_COORDINATOR_READY` fires later, restore lands. Mirrors `test_v473_1_ac_reset_deferred_restore` (verify name in quality/tests/ before reusing).
- **Live:** Open HVAC Coordinator device card. See AC Nudge and AC Reset as two sibling toggles. Both default ON. Toggling AC Nudge OFF takes effect within 1 EC tick (5 min); toggling back ON resumes nudge detection.

---

#### A2 — Split Gate 0 in `check_ac_reset`

**Description:** Replace single-gate Gate 0 at `hvac_override.py:846` with two independent gates. Add `_ac_nudge_enabled` instance attribute + property + setter on `OverrideArrester` (mirror the `_ac_reset_enabled` triad).

**Decision flow (refactored `check_ac_reset`):**

```
Gate 0a: if NOT _ac_nudge_enabled AND NOT _ac_reset_enabled:
    return  # arrester soft-nudge work disabled entirely

Gate 0b: if NOT _ac_nudge_enabled:
    # Skip soft-nudge detection. AC Reset can still be invoked
    # by direct triggers (e.g., force_reset button). check_ac_reset
    # is the soft-nudge entry point; with nudges disabled it has no work.
    return

# _ac_nudge_enabled IS True → proceed through gates 1-9
# (Gate 1: master, Gate 2: per-zone, ... Gate 9: in-flight)
# Reset gating happens later — in _evaluate_nudge_outcome →
# _perform_hard_reset_escalation (A3 early-return guard).
```

**Files touched:**
- `domain_coordinators/hvac_override.py:__init__` — add `self._ac_nudge_enabled: bool = True` adjacent to `self._ac_reset_enabled = True` at line 94.
- `domain_coordinators/hvac_override.py` — add `ac_nudge_enabled` property + setter (no side-effect on OFF — distinct from `ramp_master_enabled` which cancels in-flight nudges. Rationale: turning AC Nudge OFF mid-flight should let the current nudge complete naturally rather than strand the zone. Reviewer A challenges this in §10.)
- `domain_coordinators/hvac_override.py:check_ac_reset` — replace lines 845-850 with the 2-gate split above. Keep existing Gate 1 (`_ramp_master_enabled`) and gates 2-9 unchanged.

**Setter side-effect decision (locked at planning):**
- `ac_reset_enabled = False` → no side-effect (matches existing behavior at switch.py:1442-1448).
- `ac_nudge_enabled = False` → no side-effect (let in-flight nudges complete). Justification: a nudge's restore timer (`_nudge_restore_timers`) fires regardless of `_ac_nudge_enabled` — restoring the setpoint is part of completing the in-flight action cleanly. Cancelling mid-flight would strand the zone at +nudge_size °F.
- If user wants "OFF cancels in-flight": that's a follow-up backlog item, not v4.7.7 scope.

**Acceptance criteria:**
- **Verify:** `check_ac_reset` early-returns when both flags are False; runs gates 1-9 when `_ac_nudge_enabled=True` regardless of `_ac_reset_enabled`.
- **Test:** `test_v477_a2_state_matrix_4_combinations` — drive a state-machine table of `(_ac_nudge_enabled, _ac_reset_enabled)` ∈ {(T,T), (T,F), (F,T), (F,F)}. For each cell, assert:
  - (T,T): soft-nudge detection runs; escalation path engages on ineffective eval.
  - (T,F): soft-nudge detection runs; escalation early-returns to IDLE without lockout.
  - (F,T): `check_ac_reset` returns immediately (no soft-nudge work); zone.ramp_state unchanged.
  - (F,F): `check_ac_reset` returns immediately; no work.
- **Test:** `test_v477_a2_nudge_off_does_not_cancel_in_flight` — set up an in-flight nudge, flip `ac_nudge_enabled=False`, advance time past restore — assert restore fires cleanly.
- **Live:** Toggle AC Nudge OFF, AC Reset ON. Verify (via debug log line we add at gate 0b: "AC Nudge disabled — skipping soft-nudge detection") that gates 1-9 are skipped while the AC Reset force button still works. Toggle AC Nudge ON, AC Reset OFF: confirm gate 0a / gate 0b passthrough behavior (soft-nudge eval still iterates).

---

#### A3 — Escalation guard: skip cleanly when AC Reset disabled

**Description:** Add an early-return guard at the top of `_perform_hard_reset_escalation` (`hvac_override.py:1446`). When `_ac_reset_enabled=False`, set `zone.ramp_state = AC_RAMP_STATE_IDLE` and return WITHOUT engaging lockout, daily-cap math, or DB writes.

**Why:** Today's lockout side-effect bug — if `_hard_reset_daily_limit=0` (user-configurable to 0) OR if the user simply wants AC nudges without AC reset, the current code path at line 1469 (`int(state.get("hard_reset_count", 0)) >= self._hard_reset_daily_limit`) is True (0 >= 0), which fires `_engage_lockout` immediately. That sets `lockout_flag` in DB AND `zone.ramp_state = AC_RAMP_STATE_LOCKED_OUT` — both wrong outcomes when reset is decoupled-disabled.

**Refactored entry:**

```python
async def _perform_hard_reset_escalation(self, zone, kwh_rate_now):
    # NEW: clean skip when reset feature is disabled
    if not self._ac_reset_enabled:
        zone.ramp_state = AC_RAMP_STATE_IDLE
        _LOGGER.debug(
            "Hard reset on %s skipped — AC Reset feature disabled "
            "(soft-nudge ran but escalation is decoupled-off)",
            zone.zone_name,
        )
        return

    # ... existing logic from line 1459 onwards unchanged ...
```

**Daily-limit semantics with reset ENABLED:** unchanged. The existing `daily_limit=0` engages lockout-on-first-failed-eval; we are NOT fixing that semantic in this cycle (it's a separate UX question: should `daily_limit=0` mean "no resets" or "lock me out immediately"?). Document the unchanged semantic in `README_v4.7.7.md`. If the user wants "0 = disable, not lock", that becomes a future cycle.

**Files touched:**
- `domain_coordinators/hvac_override.py:_perform_hard_reset_escalation` — 6-line guard at top of method.

**Acceptance criteria:**
- **Verify:** With nudge ON, reset OFF, and a contrived ineffective-nudge scenario, escalation enters and returns immediately to IDLE without touching DB lockout state.
- **Test:** `test_v477_a3_escalation_skip_when_reset_disabled` — mock DB; assert no `save_ac_reset_state` call, no `log_ac_ramp_event` call with `lockout_triggered=True`, `zone.ramp_state == AC_RAMP_STATE_IDLE`.
- **Test:** `test_v477_a3_escalation_unchanged_when_reset_enabled` — regression guard: with reset ON, all existing gates (daily cap, min-interval) still execute, lockout fires when `hard_reset_count >= daily_limit`.
- **Live:** Set AC Nudge ON, AC Reset OFF. Wait for naturally-occurring ineffective nudge OR contrive one via force-button. Confirm via `sensor.ura_hvac_ac_ramp_state_<zone>` flips to `idle` (not `locked_out`), and `sensor.ura_hvac_ac_ramp_last_action_<zone>` does NOT show `lockout_engaged`.

---

#### A4 — AC Ramp sensor label scrambling fix

**Description:** Fix the entity_id ↔ friendly-name mismatch on `sensor.ura_hvac_ac_ramp_state_<suffix>` and `sensor.ura_hvac_ac_ramp_last_action_<suffix>` (and `sensor.ura_hvac_ac_ramp_kwh_rate_<suffix>` while we're here — same construction pattern).

**Root cause (read at planning, confirmed in §3 trace):**
- `unique_id` is built from canonical `zone_id` (e.g., `zone_1`, `zone_2`) — stable across boots.
- `_attr_name` uses `zone_name` (merged display label, e.g., "Back Hallway" or "Entertainment + Master Suite") — display label can change across boots if Zone Manager order changes.
- HA generates the entity_id slug from the FIRST `_attr_name` it saw at unique_id registration. On a later boot when the merged name changes, friendly name updates but entity_id slug is frozen.
- Result: entity_id `_back_hallway` (from boot 1 when zone_id=zone_X mapped to "Back Hallway") + current friendly name "Entertainment + Master Suite" (boot N's merge).

**Fix direction (locked at planning):** rename entity_ids to match the stable `unique_id` form, NOT the volatile display name. Use the canonical `zone_id` as the entity_id suffix.

- Target entity_id pattern: `sensor.ura_hvac_ac_ramp_state_<zone_id>` (e.g., `_zone_1`, `_zone_2`, `_zone_3`).
- Migration: on coordinator setup, for each AC ramp sensor unique_id, look up the existing entity_id; if it does NOT end with `_<zone_id>` (i.e., it has a stale slug), call `er.async_update_entity(entity_id, new_entity_id=f"sensor.ura_hvac_ac_ramp_state_{zone_id}")`.
- Idempotent: subsequent boots find the entity_id already in canonical form and no-op.

**HACS history trade-off:** renaming entity_ids breaks historical statistics binding. Acceptable because:
- These sensors are diagnostic, not metered (no Long-Term Statistics on `ramp_state` — it's a string).
- `ac_ramp_last_action` is `SensorDeviceClass.TIMESTAMP` — no statistics either.
- `ac_ramp_kwh_rate` IS a measurement; verify before renaming whether it carries LTS. If yes, prefer renaming friendly name to match entity_id instead (the opposite direction). **Builder must verify the kWh-rate sensor's `state_class` before deciding.**

**Files touched:**
- `__init__.py` — add a new migration block (mirror the v4.7.2 D2 pattern at lines 2404-2452) that iterates AC ramp sensor unique_ids and renames entity_ids to canonical form. Run in CM-entry setup path, AFTER `async_forward_entry_setups`, BEFORE `entry.add_update_listener` registration (Bug Class #46 — the migration itself doesn't call `async_update_entry` on the config entry, it only mutates entity registry, so it's #46-safe; double-check during build).
- `sensor.py` — NO code change to the sensor classes themselves. The construction pattern is correct; only the slug-rename migration is new.

**Acceptance criteria:**
- **Verify:** Post-v4.7.7 boot, all three AC ramp sensors per zone have entity_id ending in canonical zone_id (e.g., `_zone_1`).
- **Verify:** Friendly name and entity_id are consistent with the same canonical zone (no more "_back_hallway" displaying "Entertainment + Master Suite").
- **Test:** `test_v477_a4_ramp_sensor_entity_id_migration_idempotent` — first boot renames stale slugs; second boot no-ops (no `async_update_entity` call when entity_id already canonical).
- **Test:** `test_v477_a4_ramp_sensor_no_lts_loss` — confirm `state_class` on the three classes (state, last_action, kwh_rate). If any has `state_class` set, the test ASSERTS the migration uses the inverse direction (rename friendly name to match entity_id) instead of breaking LTS history.
- **Live:** Post-restart, the three AC ramp sensors per zone all sit on the HVAC Coordinator device card with consistent labels (e.g., `sensor.ura_hvac_ac_ramp_state_zone_1` named "60 · AC Ramp State (Back Hallway)"). No "_back_hallway" entity displaying "Entertainment + Master Suite" anywhere.

---

### Group B — DPM sensor cleanup

---

#### B1 — Orphan registry sweep for legacy `dynamic_preset_bucket_*` entities

**Description:** On coordinator setup, run an idempotent registry sweep that removes any entity with a unique_id matching the legacy pattern (NOT matching the current `dynamic_preset_active_bucket_*` pattern).

**Pattern (mirroring `__init__.py:2404-2452`):**

```python
# v4.7.7 B1: sweep stale dynamic_preset_bucket_* entries
# The class was renamed to DynamicPresetActiveBucketSensor (sensor.py:6536)
# with unique_id f"{DOMAIN}_dynamic_preset_active_bucket_{zone_id}".
# Pre-rename entries with unique_id f"{DOMAIN}_dynamic_preset_bucket_{zone_id}"
# have no producing class and sit in Unknown state.
try:
    from homeassistant.helpers import entity_registry as er
    _er = er.async_get(hass)
    _legacy_prefix = f"{DOMAIN}_dynamic_preset_bucket_"
    _current_prefix = f"{DOMAIN}_dynamic_preset_active_bucket_"
    for _ent_entry in list(_er.entities.values()):
        if _ent_entry.platform != DOMAIN:
            continue
        if not _ent_entry.unique_id.startswith(_legacy_prefix):
            continue
        if _ent_entry.unique_id.startswith(_current_prefix):
            # Active class — never sweep
            continue
        _er.async_remove(_ent_entry.entity_id)
        _LOGGER.info(
            "v4.7.7 B1: removed stale dynamic_preset_bucket entity %s "
            "(legacy unique_id; current class uses active_bucket prefix)",
            _ent_entry.entity_id,
        )
except Exception:
    _LOGGER.debug("v4.7.7 B1: orphan sweep skipped", exc_info=True)
```

**Critical guard:** the legacy prefix `dynamic_preset_bucket_` is a STRICT prefix of the current `dynamic_preset_active_bucket_`. The `startswith` check on the current prefix is the exclusion clause — without it, the sweep would delete the LIVE entities.

**Files touched:**
- `__init__.py` — sweep block placed in CM-entry setup AFTER `async_forward_entry_setups` (so registered entities are visible) and AFTER the v4.7.2/v4.7.3 device-reassignment block. BEFORE `entry.add_update_listener` registration — same Bug Class #46 placement reasoning as v4.7.6 entity migrations.

**Idempotency:**
- First boot: removes 3 legacy entries. Second boot: legacy entries no longer in registry, loop iterates current entities and no-ops on each (startswith-current-prefix continues).
- HA upgrade with re-discovery: same as second boot.
- User manually re-creates an orphan via UI: HA does not allow recreating entity_registry entries via UI; if a user manually adds a YAML sensor with the legacy name, that's a different platform (not URA-domain) and the `platform != DOMAIN` guard skips it.

**Acceptance criteria:**
- **Verify:** Post-v4.7.7 boot, querying entity registry for entries with unique_id starting with `<DOMAIN>_dynamic_preset_bucket_` AND NOT starting with `<DOMAIN>_dynamic_preset_active_bucket_` returns 0 results.
- **Test:** `test_v477_b1_orphan_sweep_removes_legacy` — seed registry with 3 legacy entries + 3 current entries → run sweep → assert legacy gone, current intact.
- **Test:** `test_v477_b1_orphan_sweep_idempotent` — run sweep twice; second call removes 0 entries.
- **Test:** `test_v477_b1_orphan_sweep_skips_non_ura_platform` — entry with `platform != DOMAIN` is untouched.
- **Live:** Open HA Settings → Devices & Services → Entities. Search "dynamic_preset_bucket". No `Unknown`-state entries appear (only the 3 active ones with unique_id pattern `*_active_bucket_*`).

---

#### B2 — DPM zone-skip investigation + skip_reason exposure

**Description:** Two-phase deliverable.

**Phase 1 — Investigation (planning-time + builder verification):**

Trace why `skipped_zones: ["zone_1", "zone_2", "zone_3"]` covers every zone post-v4.7.6.1. Candidate root causes (from `dynamic_preset.py:async_evaluate_and_emit`):

| Skip point | Location | Trigger condition |
|---|---|---|
| `gate_disabled` | line 342 | `zone_data[CONF_ZONE_DYNAMIC_PRESET_ENABLED]` is False/absent (per-zone opt-in) |
| `no_forecast_delta` | line 346 | `delta is None` (WPM forecast unavailable for this zone) |
| `unknown_bucket` | line 437 | bucket classification returned an invalid name (data corruption — shouldn't happen) |
| `home_range_not_configured` | line 483 | bucket cells absent AND seasonal baseline derivation failed |
| `dwell_pending` | line 376 | bucket transition computed but dwell not elapsed → stays in current_bucket → emits CURRENT bucket overrides, NOT skip → only counts as "skip" if current_bucket's range is also missing |
| `canonical_label_mismatch` | `energy.py:2701` | canonical-merged label parts don't resolve to any house zone → skips entire eval for that zone |

Builder MUST instrument the eval path with a temporary `skip_reason` capture (TRACE-level log per zone) and run a single live tick post-build to identify the actual reason for each of zone_1/2/3 on the user's instance. Surface the finding in the build commit message AND in `README_v4.7.7.md`.

**Phase 2 — Fix or document:**

- If the finding is a **real bug** (e.g., v4.7.5 lazy-canonical-resolution gap left some zones unresolved): file a small fix in this cycle if ≤30 LoC; otherwise scope to v4.7.8 follow-up.
- If the finding is **expected behavior** (e.g., dwell pending after recent restarts, SOC bands not hit, per-zone DPM not opted in): expose the reason in `sensor.ura_energy_coordinator_dynamic_preset_overrides_applied.skipped_zones_with_reason`.

**Skipped_zones_with_reason attr structure:**

```python
# in DynamicPresetOverridesAppliedSensor.extra_state_attributes
"skipped_zones_with_reason": [
    {"zone_id": "zone_1", "reason": "gate_disabled"},
    {"zone_id": "zone_2", "reason": "home_range_not_configured"},
    {"zone_id": "zone_3", "reason": "no_forecast_delta"},
],
# Existing skipped_zones list-of-strings kept for back-compat (mirror style).
```

**Files touched:**
- `domain_coordinators/dynamic_preset.py:async_evaluate_and_emit` — return tuple `(overrides, skip_reason)` instead of just `overrides`. `skip_reason` is None when overrides is non-empty; otherwise it's one of the labels above.
- `domain_coordinators/energy.py:_async_evaluate_dynamic_presets` — capture skip reasons per zone in `self._dynamic_preset_skip_reasons: dict[str, str]`.
- `sensor.py:DynamicPresetOverridesAppliedSensor.extra_state_attributes` — read `self._dynamic_preset_skip_reasons` and emit as `skipped_zones_with_reason`.

**Scope guardrail:** if the investigation finds a non-trivial fix (e.g., schema-touching, multi-file), the FIX is deferred and only the skip_reason exposure ships in v4.7.7. Builder logs the deferral per CLAUDE.md "Plan Completion Tracking".

**Acceptance criteria:**
- **Verify:** Builder's commit message includes a one-line root-cause finding for each of zone_1/2/3.
- **Verify:** `sensor.ura_energy_coordinator_dynamic_preset_overrides_applied` exposes both `skipped_zones` (existing) AND `skipped_zones_with_reason` (new) in its attributes.
- **Sensor:** `sensor.ura_energy_coordinator_dynamic_preset_overrides_applied.skipped_zones_with_reason[*].reason` ∈ {`gate_disabled`, `no_forecast_delta`, `unknown_bucket`, `home_range_not_configured`, `dwell_pending`, `canonical_label_mismatch`}.
- **Test:** `test_v477_b2_skip_reason_labels` — drive each skip point with a synthetic zone_data + mock WPM, assert correct label.
- **Test:** `test_v477_b2_overrides_emitted_no_skip_reason` — when overrides non-empty, zone NOT in `skipped_zones_with_reason`.
- **Live:** Within 1 EC tick post-restart, the user can read `skipped_zones_with_reason` on the sensor and immediately know why each zone is skipped.

---

#### B3 — Migrate DPM observability sensors to HVAC Coordinator device

**Description:** Update `_attr_device_info` on `DynamicPresetActiveBucketSensor`, `DynamicPresetRangeSensor`, and `DynamicPresetOverridesAppliedSensor` from `_energy_device_info()` to `_hvac_device_info()`. Run an idempotent entity-registry device-reassignment migration on CM setup to move existing entities from Energy Coordinator device to HVAC Coordinator device.

**Pattern: mirror v4.7.2 D2 / v4.7.3 D4 block at `__init__.py:2404-2452`. EXACT same construction.**

Add to the existing `_HVAC_DEVICE_MIGRATIONS` list:

```python
_HVAC_DEVICE_MIGRATIONS = [
    ("switch", f"{DOMAIN}_energy_dynamic_preset_enabled"),        # v4.7.2 D2
    ("number", f"{DOMAIN}_energy_dynamic_preset_dwell_minutes"),   # v4.7.3 D4
    ("number", f"{DOMAIN}_energy_dynamic_preset_hysteresis_f"),    # v4.7.3 D4
    # v4.7.7 B3: DPM observability sensors join the master switch on HVAC device
    ("sensor", f"{DOMAIN}_dynamic_preset_overrides_applied"),
    # Per-zone sensors registered for each canonical zone_id — handled by
    # a small inner loop over iter_canonical_hvac_zones (below). Adding
    # them to this static list would require enumerating zones at module
    # load, which is wrong; do it inside the try block.
]
```

For the per-zone classes, append at runtime:

```python
from .domain_coordinators.hvac_zones import iter_canonical_hvac_zones
for _z in iter_canonical_hvac_zones(hass):
    _HVAC_DEVICE_MIGRATIONS.append(
        ("sensor", f"{DOMAIN}_dynamic_preset_active_bucket_{_z['zone_id']}")
    )
    _HVAC_DEVICE_MIGRATIONS.append(
        ("sensor", f"{DOMAIN}_dynamic_preset_range_{_z['zone_id']}")
    )
```

**Files touched:**
- `sensor.py:DynamicPresetActiveBucketSensor.__init__` — change `_attr_device_info = _energy_device_info()` to `_hvac_device_info()` (line 6562).
- `sensor.py:DynamicPresetRangeSensor.__init__` — same (line 6698).
- `sensor.py:DynamicPresetOverridesAppliedSensor.__init__` — same (line 6788).
- `__init__.py` — extend `_HVAC_DEVICE_MIGRATIONS` per above + per-zone loop.

**Idempotency:** first boot moves entities; subsequent boots find `_ent_entry.device_id == _target_device.id` and skip the `async_update_entity` call (existing guard at `__init__.py:2436-2442`).

**Acceptance criteria:**
- **Verify:** Post-v4.7.7 boot, all 1 + 2N DPM observability sensors (1 global + per-zone × 2 classes) appear under the HVAC Coordinator device card alongside the DPM master switch and dwell/hysteresis numbers.
- **Verify:** No DPM observability sensors remain on the Energy Coordinator device.
- **Sensor:** `sensor.ura_energy_coordinator_dynamic_preset_overrides_applied` retains its entity_id (slug derived at first registration; only device_id changes per `_er.async_update_entity` semantics).
- **Test:** `test_v477_b3_dpm_sensors_on_hvac_device` — schema check: all three classes' `_attr_device_info` resolves to HVAC Coordinator identifiers.
- **Test:** `test_v477_b3_migration_idempotent` — first run reassigns 1+2N entities; second run reassigns 0.
- **Live:** Open HA Settings → Devices & Services → URA: HVAC Coordinator device. Scroll the entity list — Dynamic Preset Bucket, Range, OverridesApplied all present. Open URA: Energy Coordinator device — DPM sensors absent.

---

## 5. Size Estimate

| Area | LoC (prod) | LoC (test) |
|---|---|---|
| A1: HVACACNudgeSwitch class + registration + strings | ~135 + 8 + 12 | ~80 |
| A2: Gate 0 split + new property/setter | ~30 | ~120 (4-cell state matrix + in-flight nudge) |
| A3: Escalation early-return guard | ~10 | ~40 (skip + regression) |
| A4: AC ramp sensor entity_id migration | ~45 (mirror existing block) | ~50 |
| B1: Orphan registry sweep | ~25 | ~50 |
| B2: skip_reason instrumentation + sensor attr | ~50 | ~70 |
| B3: DPM sensor device migration | ~15 (3 device_info lines + list extension) | ~50 |
| **Subtotals** | **~330 prod** | **~460 tests** |

Above the "120-200 LoC prod + 250-350 LoC tests" rough estimate in the brief — primarily because A1 mirrors the entire `HVACACResetSwitch` class (130 LoC of class body), B2 instrumentation crosses three files, and the state-matrix test for A2 is large. Still tight for a Tier 2 combined cycle.

**Builder reduction levers if cycle bloats:**
- A1 class body could be factored to a shared base if `HVACACResetSwitch` is also refactored — DEFER, too much scope for v4.7.7.
- B2 could ship "skip_reason for the 3 most common reasons only" instead of all 6 — acceptable trim if needed.

---

## 6. Naming + Friendly-Name Ordering (HA Frontend Intl.Collator)

Per `project_ha_frontend_entity_sort.md`, HA Settings → Devices page sorts entities by friendly name using `Intl.Collator(numeric:true)`. URA uses numeric prefixes (`25 ·`, `26 ·`, `60 ·`) to control visible order.

**A1 prefix selection:** AC Reset is `"25 · AC Reset"`. AC Nudge gets `"26 · AC Nudge"` (sibling, immediately following). This keeps the two paired in the device card list and avoids re-prefixing existing entities.

**Cross-check:** verify no existing entity already claims `"26 ·"` (builder runs `grep -n '"26 · ' custom_components/universal_room_automation/` before locking the prefix). If `"26"` is taken, use `"25.5"` or move both to `"25 · AC Reset"` / `"26 · AC Nudge"` and accept whatever cousin entity has `"26"`.

---

## 7. Bug Class Compliance Matrix

| Bug Class | A1 | A2 | A3 | A4 | B1 | B2 | B3 |
|---|---|---|---|---|---|---|---|
| #5 (Deferred restore via signal) | yes — mirror existing | n/a | n/a | n/a | n/a | n/a | n/a |
| #11 (UTC vs local TZ date compare) | n/a | n/a | n/a | n/a | n/a | check: `_last_transition_at` already TZ-aware (dynamic_preset.py:337) | n/a |
| #19 (sync @callback) | yes — handler is @callback | n/a | n/a | n/a | n/a | n/a | n/a |
| #20 (concurrent reload race) | n/a | n/a | n/a | n/a | n/a — sweep is registry-only, no entry reload | n/a | n/a |
| #38 (untracked unsub) | yes — `async_on_remove(async_dispatcher_connect(...))` | n/a | n/a | n/a | n/a | n/a | n/a |
| #42 (lambda+async_create_task in scheduler) | yes — bound method, not lambda | n/a | n/a | n/a | n/a | n/a | n/a |
| #45 (lambda closure stale local) | n/a | n/a | n/a | n/a | n/a | yes — when capturing skip_reason per zone, use bound method or per-zone dict, NOT a closure over loop variable | n/a |
| #46 (`async_update_entry` in setup) | n/a | n/a | n/a | yes — entity_registry mutation only, NOT `async_update_entry`; verify pre-update-listener placement | yes — same | n/a | yes — same migration pattern as v4.7.2 D2 / v4.7.3 D4 |

**Reviewer focus areas distilled:** Reviewer A owns the state-matrix + lockout side-effect (A2/A3/A4 correctness, B2 root-cause). Reviewer B owns Bug Class #46 placement, async lifecycle, and entity_registry idempotency (A1 restore, A4 migration, B1 sweep, B3 device move).

---

## 8. Pre-Deploy Zero-Bugs Gate (5 gates)

Per `feedback_pre_deploy_zero_bugs_gate.md` (user-coined 2026-05-29 after v4.7.4.3 broken-release incident) and the planner-added JSON-validity gate from v4.7.6.1:

```bash
# Gate 1: No unresolved conflict markers
grep -rln "^<<<<<<<\|^>>>>>>>" custom_components/ docs/ quality/ \
  | grep -v "TEST_SUITE_ACCESS\|test_scenarios" \
  && echo "ABORT: unresolved conflict markers" && exit 1

# Gate 2: py_compile every changed Python file
git diff --name-only pre-review-v4.7.7..HEAD -- '*.py' \
  | xargs -I{} python3 -m py_compile {} || exit 1

# Gate 3: JSON validity (strings.json + en.json)
python3 -m json.tool custom_components/universal_room_automation/strings.json > /dev/null || exit 1
python3 -m json.tool custom_components/universal_room_automation/translations/en.json > /dev/null || exit 1

# Gate 4: cycle tests
PYTHONPATH=quality python3 -m pytest quality/tests/test_v477_*.py -q || exit 1

# Gate 5: full URA suite — no NEW regressions vs pre-review-v4.7.7
PYTHONPATH=quality python3 -m pytest quality/tests/ -q
# compare against baseline tagged at start of cycle
```

If ANY gate fails: STOP, fix, re-run all 5, then `./scripts/deploy.sh 4.7.7 ...`.

---

## 9. Pre-Review Baseline Tag

Before applying ANY review fixes:

```bash
git tag pre-review-v4.7.7 -m "Pre-review baseline for v4.7.7 — AC nudge decouple + DPM cleanup"
```

This enables `git diff pre-review-v4.7.7..HEAD` to isolate review-fix changes.

---

## 10. Reviewer Framings (Tier 2 — locked at planning)

Two parallel staff-engineer reviews. Framings are deliberately disjoint to prevent blind-spot overlap (lesson from `feedback_db_sensitive_3x_targeted_reviews.md`).

### Reviewer A — Correctness + state-machine + edge cases

**Scope:** A2/A3 decision-flow correctness. A4 migration consistency. B2 root-cause identification quality.

**Specific checks:**

1. **Full state-machine table for AC Nudge × AC Reset.** 4-cell table per the test_v477_a2_state_matrix_4_combinations spec. Each cell's expected behavior documented and verified vs code.
   - (T, T): soft-nudge runs; ineffective eval → escalation runs all gates → lockout fires if daily cap hit.
   - (T, F): soft-nudge runs; ineffective eval → escalation early-returns to IDLE WITHOUT lockout, WITHOUT DB writes for lockout state, WITHOUT `log_ac_ramp_event(lockout_triggered=True)`.
   - (F, T): `check_ac_reset` early-returns at gate 0b; no soft-nudge work; `zone.ramp_state` is whatever was set last (NOT clobbered to IDLE — verify that's the desired behavior or whether we should clear to IDLE).
   - (F, F): same as (F, T) per the gate 0a/0b combination.
2. **Lockout removal correctness.** Trace `_perform_hard_reset_escalation` end-to-end with `_ac_reset_enabled=False`. Confirm:
   - No `_db.save_ac_reset_state` call.
   - No `_db.log_ac_ramp_event(lockout_triggered=True)` call.
   - No `_engage_lockout` call.
   - `zone.ramp_state == AC_RAMP_STATE_IDLE` post-return (not LOCKED_OUT, not ESCALATING).
3. **Daily-limit semantics with reset ENABLED.** Reviewer A confirms the existing `daily_limit=0 → lockout-on-first-eval` semantic is UNCHANGED. v4.7.7 does NOT fix that semantic (separate UX question, deferred). If reviewer believes the semantic SHOULD also be fixed, file as backlog, do not block ship.
4. **In-flight nudge persistence when `_ac_nudge_enabled` flipped OFF.** Confirm the setter has NO side-effect (no cancel-in-flight), and an active restore timer fires correctly. Trace from `cancel_nudge` usage sites — was `ramp_master_enabled.setter` cancel-on-OFF logic copied accidentally?
5. **A4 ramp sensor scrambling fix consistency.**
   - Existing entities renamed to canonical zone_id form.
   - NEW entities created post-fix (if a new zone is added later) follow the same canonical form — verify by reading the per-zone sensor creation loop (sensor.py:335-367), which uses `iter_canonical_hvac_zones`. Since unique_id was always based on canonical zone_id, new entities will register with entity_ids matching unique_id by HA default.
   - Trade-off: friendly name continues to reflect the merged display label ("Entertainment + Master Suite"). entity_id is canonical (`_zone_2`). User sees `sensor.ura_hvac_ac_ramp_state_zone_2` with name "60 · AC Ramp State (Entertainment + Master Suite)". Confirm this matches user expectation.
6. **B2 root-cause identification quality.** Does the builder's commit message precisely identify the skip reason for each of zone_1/2/3? If reason is `home_range_not_configured`, is the user's actual configuration captured in evidence? If `canonical_label_mismatch`, is the v4.7.5 lazy-canonical-resolution gap implicated?

**Output:** Standard Tier 2 review doc at `docs/reviews/code-review/v4.7.7_reviewerA_correctness.md` with severity-bucketed findings (CRITICAL / HIGH / MED / LOW) and bug-class tagging per CLAUDE.md.

---

### Reviewer B — Async + lifecycle + restart resilience

**Scope:** Bug Class #46 placement of entity_registry mutations. Bug Class #45 in new B2 instrumentation. RestoreEntity for the new AC Nudge switch. Entity registry sweep idempotency. Cross-coordinator signal propagation.

**Specific checks:**

1. **Bug Class #46 placement of all 3 entity_registry mutations (A4 ramp rename, B1 orphan sweep, B3 device migration).**
   - Confirm placement is BEFORE `entry.async_on_unload(entry.add_update_listener(...))` registration at `__init__.py:2454`.
   - Confirm NONE of the three blocks calls `async_update_entry` on the config entry itself.
   - Confirm placement is AFTER `async_forward_entry_setups` so that entities being mutated are actually registered.
   - Verify QUALITY_CONTEXT #46 explicitly classes entity_registry mutations as #46-safe (NOT subject to re-entrancy hazard). If unclear, builder ASKS at planning rather than guessing.
2. **Bug Class #45 in B2 instrumentation.** When `dynamic_preset.py:async_evaluate_and_emit` returns a `skip_reason`, the caller in `energy.py:_async_evaluate_dynamic_presets` stores per-zone reasons in a dict. Confirm:
   - The dict is keyed by `zone_id` (stable string), NOT by loop-variable closure.
   - If a lambda is introduced for any helper, confirm it captures via default-argument pattern or bound method (per QUALITY_CONTEXT #45).
3. **Bug Class #11 timezone checks.** Likely zero exposure in this cycle (no new ISO datetime fields). Reviewer B confirms by grep of changed files.
4. **RestoreEntity for HVACACNudgeSwitch.**
   - Survives HA restart: `async_get_last_state` returns the prior state; setter applies via fast path OR deferred path.
   - Fresh install: `last_state is None` → default ON kept (no spurious OFF).
   - Bad state (`unknown`/`unavailable`): early-return, keep default ON.
   - Deferred-restore failure (signal never fires): switch shows `available=False` until coord registers; restore lands on signal arrival.
5. **Entity registry sweep idempotency (B1).**
   - Second reload: 0 removes.
   - HA major upgrade: 0 removes (no re-introduction of legacy entries).
   - User manually re-creates a YAML sensor with the legacy name: `platform != DOMAIN` guard skips.
   - Race: what if the legacy entity is in the process of being added by HA at sweep time? Likely impossible (sweep runs after `async_forward_entry_setups` completes, by which point new entity registrations are finalized). Reviewer B traces.
6. **Cross-coordinator interaction for the new AC Nudge switch.**
   - Switch's setter writes to `hvac.override_arrester.ac_nudge_enabled`.
   - When HVAC coord reloads, the property reads default `True` unless the deferred-restore path lands.
   - Verify the SIGNAL_HVAC_COORDINATOR_READY dispatcher fires AFTER the OverrideArrester is instantiated (`hvac.py` setup ordering).
7. **Concurrent reload race (Bug Class #20).** If user toggles the new switch during a config-entry reload, what happens? Setter writes to a stale `override_arrester` instance, which is GC'd shortly. Lost write. Reviewer B confirms this is acceptable for a user-driven toggle (HA's standard idempotency expectation — user retries).

**Output:** Standard Tier 2 review doc at `docs/reviews/code-review/v4.7.7_reviewerB_async_lifecycle.md`.

---

## 11. Live Validation Plan (post-deploy)

After `./scripts/deploy.sh 4.7.7 ...` AND HACS install + HA restart:

**A1:**
- `switch.ura_hvac_ac_nudge` exists on HVAC Coordinator device, state ON.
- Toggle OFF → confirm `OverrideArrester._ac_nudge_enabled` flips (via debug log line we add).
- Restart HA → confirm restored state is OFF (RestoreEntity working).
- Toggle ON → restart → confirm restored state is ON.

**A2:**
- With Nudge ON, Reset ON: existing behavior preserved (no regression vs v4.7.6.1).
- Flip Nudge OFF, Reset ON: log shows "AC Nudge disabled — skipping soft-nudge detection" within 1 EC tick.
- Flip Nudge ON, Reset OFF: log shows soft-nudge detection running across zones.

**A3:**
- Contrive ineffective nudge OR wait for natural occurrence with Nudge ON / Reset OFF. Confirm:
  - `sensor.ura_hvac_ac_ramp_state_<zone>` → `idle` (not `locked_out`, not `escalating`).
  - `sensor.ura_hvac_ac_ramp_last_action_<zone>` shows `nudge_evaluated`, NOT `lockout_engaged`.
  - DB `ac_reset_state` row for that zone has `lockout_flag = 0`.

**A4:**
- All AC ramp sensor entity_ids end in `_zone_1` / `_zone_2` / `_zone_3` (canonical form).
- Friendly names match the canonical zone (no `_back_hallway` showing "Entertainment + Master Suite").

**B1:**
- HA Settings → Entities → search "dynamic_preset_bucket". Only 3 entries (active_bucket), 0 Unknown-state.

**B2:**
- `sensor.ura_energy_coordinator_dynamic_preset_overrides_applied.skipped_zones_with_reason` populated with 3 entries.
- Each entry has a `reason` in the allowed set.

**B3:**
- HA Settings → URA: HVAC Coordinator device card → DPM observability sensors (Bucket, Range, OverridesApplied) present.
- HA Settings → URA: Energy Coordinator device card → DPM observability sensors absent.

**General:**
- Zero new URA ERROR logs since boot.
- HACS `installed_version: v4.7.7`.

---

## 12. Explicit Non-Goals

- **No changes to DPM evaluation logic itself.** B2 surfaces skip reasons; if investigation finds a non-trivial fix, it's deferred to v4.7.8.
- **No new gating rules in EV / L1 land.** v4.7.6 / v4.7.6.1 already shipped that surface.
- **No master-switch addition on top of AC Nudge / AC Reset.** They stay as two siblings on the HVAC Coordinator device. A future cycle could add a `"24 · AC Ramp Master"` umbrella if user wants — not v4.7.7.
- **No HACS history migration on the new AC Nudge switch.** First-install entity; no prior unique_id to reclaim.
- **No fix to the `daily_limit=0` semantic.** That's a separate UX question (should "0" mean "disable" or "lock immediately"?). v4.7.7 leaves it as-is and decouples via `_ac_reset_enabled` instead.
- **No deletion of `HVACACResetSwitch` class.** It stays alongside the new `HVACACNudgeSwitch`.
- **No config-flow schema changes.** Both `CONF_HVAC_AC_RESET_ENABLED` and the new `CONF_HVAC_AC_NUDGE_ENABLED` are switch-mirror options; no new options-flow step.

---

## 13. Plan-Completion Tracking (filled at cycle end)

Per CLAUDE.md "Plan Completion Tracking — MANDATORY". At cycle end, fill in:

| Deliverable | Shipped? | If deferred, why + where tracked |
|---|---|---|
| A1 HVACACNudgeSwitch | TBD | |
| A2 Gate 0 split | TBD | |
| A3 Escalation guard | TBD | |
| A4 Ramp sensor entity_id migration | TBD | |
| B1 Orphan sweep | TBD | |
| B2 skip_reason exposure | TBD | (root-cause finding: ___) |
| B2 fix for any real-bug finding | TBD | If non-trivial, deferred to v4.7.8 |
| B3 DPM sensor device migration | TBD | |

---

## 14. Reference Files Cited

| Path | Purpose |
|---|---|
| `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/hvac_override.py` | A2/A3 target file |
| `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/hvac_const.py` | A1 new CONF + DEFAULT |
| `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/switch.py` | A1 mirror pattern |
| `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/sensor.py` | A4 + B3 device migration |
| `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/__init__.py` | A4 + B1 + B3 registry migrations |
| `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/dynamic_preset.py` | B2 skip_reason source |
| `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/energy.py` | B2 caller |
| `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/hvac_zones.py` | iter_canonical_hvac_zones used by B3 per-zone loop |
| `/Users/okosisi/Code/universal-room-automation/docs/QUALITY_CONTEXT.md` | Bug class compliance |
| `/Users/okosisi/Code/universal-room-automation/docs/planning/PLANNING_v4.7.2_dpm_hvac_surface_plus_guest_signal.md` | Device migration pattern precedent |
| `/Users/okosisi/Code/universal-room-automation/docs/planning/PLANNING_v4.7.4_dpm_ui_simplification.md` | DPM UI history |
| `/Users/okosisi/Code/universal-room-automation/docs/CONTEXT_TRANSFER_2026-05-29.md` | v4.7.x stretch state |

---

**End of plan.**
