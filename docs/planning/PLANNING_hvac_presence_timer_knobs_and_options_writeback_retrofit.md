# PLANNING — HVAC Presence-Timer Knobs (build) + EC/HC Options-Writeback Retrofit (deferred)

**Status:** Plan (no version stamped — versions assigned at deploy time per the operator's versioning convention).
**Tier:** Tier 2 (feature cycle, multi-file, new entities + new config form fields; no DB shape change, no listener surgery). Two parallel reviews with disjoint framings (A = correctness + edge cases; B = async + lifecycle + race conditions, plus Bug Class #32 / #46 framing).
**Scope:** This plan has TWO parts.
  - **Part 1 (build THIS cycle):** Expose the three currently-invisible HVAC presence timers as both config-flow form fields AND device Number entities on the HVAC Coordinator device. Standardise on `entry.options` as the SOLE source of truth (no RestoreEntity). Retrofit the existing `ZoneEntryDwellNumber` to the same pattern. Add a reset-to-default button.
  - **Part 2 (DEFER):** Apply the same options-source-of-truth + writeback + drop-RestoreEntity pattern to the EC `*Number` family and the DPM/HVAC RestoreEntity Numbers in a later pass. HVAC is the reference implementation.

---

## Institutional context verified

This is the proof-of-work that the plan was scoped against the existing codebase and not from a guessed mental model. All file:line refs below were re-read in this session (not copy-pasted from the brief). The brief's refs that drifted are flagged.

### Greps run (verified against current `develop`)

**Existing constants (REUSED, do not redefine):**
- `CONF_HVAC_VACANCY_GRACE_MINUTES` — `domain_coordinators/hvac_const.py:94`. Default `DEFAULT_VACANCY_GRACE_MINUTES = 15` at `hvac_const.py:126`.
- `CONF_HVAC_VACANCY_GRACE_CONSTRAINED` — `hvac_const.py:95`. Default `DEFAULT_VACANCY_GRACE_CONSTRAINED = 5` at `hvac_const.py:127`. **Brief drift:** brief named this `CONF_HVAC_VACANCY_GRACE_MINUTES_CONSTRAINED`; the actual const has NO `_MINUTES` suffix. Use the existing name verbatim.
- `CONF_HVAC_MAX_OCCUPANCY_HOURS` — `hvac_const.py:96`. Default `DEFAULT_MAX_OCCUPANCY_HOURS = 8` at `hvac_const.py:128`.
- `CONF_HVAC_ZONE_ENTRY_DWELL` — `hvac_const.py:130` (NOT 94-96 as brief implied). Default `DEFAULT_ZONE_ENTRY_DWELL_MINUTES = 3` at `hvac_const.py:129`.

**Existing CM-load wiring (REUSED, no change needed):**
- `__init__.py:2020-2031` — already reads all four CONF keys via `cm_config.get(...)` and passes them to `HVACCoordinator(..., vacancy_grace=..., vacancy_grace_constrained=..., max_occupancy_hours=..., zone_entry_dwell=...)`.
- `HVACCoordinator.__init__` accepts all four as kwargs at `hvac.py:88-91`, stores them on `self._vacancy_grace` / `self._vacancy_grace_constrained` / `self._max_occupancy_hours` / `self._zone_entry_dwell` at `hvac.py:221-224`.
- Live-attr reads (the "nicety" target sites): `hvac.py:1037-1038` (vacancy grace, energy-constrained branch), `hvac.py:1081`, `hvac.py:1106`, `hvac.py:1119` (max-occupancy), `hvac.py:1130` (zone-entry dwell), `hvac.py:1864-1865` (vacancy grace, second site). All read attrs every decision cycle — direct push-to-attr in `async_set_native_value` takes effect on the next cycle without waiting for the CM reload to settle.

**Existing config-flow field (REUSED, will be moved into the new collapsed section):**
- `CONF_HVAC_ZONE_ENTRY_DWELL` is already a top-level slider on `coordinator_hvac_settings` at `config_flow.py:4218-4228`. Imports at `config_flow.py:3924-3925`. Save path at `config_flow.py:3968-3971` already does `data={**self._config_entry.options, **user_input}`.
- **Recommendation:** MOVE the dwell field into the new collapsed `presence_timing` section alongside the three new fields. Rationale: (a) keep all four presence timers visually clustered for the operator; (b) "rarely change" is true for dwell too; (c) the form-save merge already handles missing fields gracefully (the `{**options, **user_input}` flatten preserves existing options when the section is collapsed-and-not-touched).

**Existing platform Number (REUSED, will be retrofitted):**
- `ZoneEntryDwellNumber` — `number.py:277-343`. Currently: NOT a RestoreEntity (consistent with the target pattern on the no-Restore axis), but ALSO has no writeback to `entry.options` — only pushes to `hvac._zone_entry_dwell` live. **Bug Class #32 manifestation:** slider edit survives in-memory until next reload but does not persist to `entry.options`. Operator confirmed this is the bug to fix.
- Existing label at `number.py:307` = `"48 · Zone Entry Dwell"` — to be RENUMBERED to `"47 · Zone Entry Dwell"` (cosmetic only; unique_id at `number.py:306` = `f"{DOMAIN}_hvac_zone_entry_dwell"` stays unchanged → entity_id stable).

**Pattern reference for writeback (REUSED as architectural template):**
- `DynamicPresetDwellMinutesNumber.async_set_native_value` at `number.py:1893-1907` — already does `async_update_entry(options={**self._entry.options, CONF: value})`. **The pattern to adopt — minus the RestoreEntity inheritance.** The class docstring at `number.py:1834-1836` literally says "v4.3.2 mirror pattern: entry.options = initial seed only; RestoreEntity is the canonical runtime store. No async_update_entry writeback." That docstring is OUT OF DATE relative to the code — the code at `number.py:1900-1903` DOES the writeback. The operator's call ("writeback is better… RestoreEntity is the CAUSE of the shadowing") is the explicit successor.

**Pattern reference for collapsed section + flatten-on-save (REUSED):**
- `fan_recheck_advanced` — schema definition at `config_flow.py:2991` (`vol.Optional("fan_recheck_advanced"): section(...)`); flatten-on-save at `config_flow.py:2893-2898` (`advanced = user_input.pop("fan_recheck_advanced", None); if isinstance(advanced, dict): user_input = {**user_input, **advanced}`). Adopt verbatim shape.
- `advanced` section on DPM — `config_flow.py:4502-4513`.

**Pattern reference for inter-field validation reject (REUSED):**
- Cover temp hysteresis reject — `config_flow.py:3957-3971`. Same `errors: dict[str, str] = {}` + `errors["base"] = "..."` + fall-through-to-show-form pattern. Use this exact shape for the new validation: `vacancy_grace_constrained <= vacancy_grace_minutes`.

**Existing strings.json data + data_description sections (REUSED, extended):**
- `strings.json:958-1013` — `coordinator_hvac_settings.data` (label table) + `data_description` (helper-text table). All three new fields + the new `sections` label go here. Existing `hvac_zone_entry_dwell` label at `strings.json:974` and helper at `strings.json:1000` stay (helper is the house-style template).

**Existing reset-style button (REUSED as template):**
- `ClearBayesianBeliefsButton` at `button.py:528-585`. Use as structural template for the new `ResetPresenceTimersButton`: same DeviceInfo dict, same `_attr_entity_category = EntityCategory.CONFIG` (or DIAGNOSTIC — pick CONFIG since the action is config-mutating), same singleton-on-CM-entry pattern. Button's `async_press` calls `async_update_entry(options=...)` writing the four defaults — same Bug Class #46-safety analysis as the Number writeback (runtime user action, not setup-path).

**Numbering cluster verified (cosmetic ordering trick under trial on HC):**
- The `NN ·` `_attr_name` prefix is a COSMETIC ordering device — operator-confirmed it's an ordering trick being trialed on the HVAC Coordinator (HC) device card. Entity identity (unique_id + entity_id) is number-free for every entity below, so any prefix move is purely a friendly-name change with NO dashboard/automation breakage. HA's device card sorts all platforms (number/switch/button/sensor) TOGETHER by friendly name, so the prefixes order the whole card, not one platform.
- **Operator revision (2026-06-06): cluster the switch.** As originally drafted, the lone `50 · Vacancy Auto-Off` switch would be wedged in the middle of the new Number block. Operator wants switches clustered. `HVACZoneSweepSwitch` ("50 · Vacancy Auto-Off", `switch.py:2311`, `_attr_name` literal at `switch.py:2336`) is moved to `46 ·` so it sits adjacent to its neighbour switch `45 · Solar Cover Management` (`HVACSolarCoverSwitch`, `switch.py:2430`). CONFIRMED cosmetic-safe: `HVACZoneSweepSwitch` `unique_id = f"{DOMAIN}_hvac_zone_sweep"` (`switch.py:2333`), entity_id `switch.ura_hvac_zone_sweep` — both number-free, and a prior-art comment at `switch.py:2334-2335` explicitly notes the label is decoupled from CONF + entity_id.
- **Final cluster (renders top-to-bottom on the HC device card):**

  | Slot | Entity | Platform | Change |
  |---|---|---|---|
  | `45 · Solar Cover Management` | `HVACSolarCoverSwitch` | switch | unchanged |
  | `46 · Vacancy Auto-Off` | `HVACZoneSweepSwitch` | switch | MOVED from 50 (one-line `_attr_name`) |
  | `47 · Zone Entry Dwell` | `ZoneEntryDwellNumber` | number | RENUMBERED from 48 |
  | `48 · Vacancy Grace` | `VacancyGraceMinutesNumber` | number | NEW |
  | `49 · Vacancy Grace · Energy-Saving` | `VacancyGraceConstrainedNumber` | number | NEW |
  | `50 · Max Occupancy Failsafe` | `MaxOccupancyHoursNumber` | number | NEW (was drafted at 51) |
  | `51 · Reset Presence Timers` | `ResetPresenceTimersButton` | button | NEW (was drafted at 46) — sits right after the four timers it resets |

  Net: switches 45/46 cluster; a contiguous Number block 47-50; the reset action parked at the tail (51). No platform wedged mid-cluster. NOTE: friendly-name labels above are subject to the naming pass in the next subsection (units + jargon review).

### Naming decisions — user-friendly + cognitively clear (operator to confirm)

**Operator directive (2026-06-06): "make sure sensor naming is user friendly and cognitively clear."** Two moves: (a) add explicit UNITS to every timer label so the card is self-describing (matches the existing precedent `03 · Dynamic Preset Dwell (minutes)` in DPM); (b) drop insider jargon ("Grace", "Failsafe"). **RESOLVED 2026-06-06 — operator picked the final labels below.** Note the pleasing consistency: every Number now leads with "Zone", matching the existing "Zone Entry Dwell".

| Slot | FINAL label (operator-confirmed) | Notes |
|---|---|---|
| 47 | **Zone Entry Dwell (minutes)** | "Dwell" kept (established URA term); unit added. |
| 48 | **Zone Vacancy Delay (minutes)** | replaces "Vacancy Grace" — drops the "Grace" jargon. |
| 49 | **Zone Vacancy Delay · Energy-Saving (minutes)** | mirrors 48 + `· Energy-Saving` suffix. |
| 50 | **Max Zone Occupied Time (hours)** | replaces "Max Occupancy Failsafe" — drops the "Failsafe" jargon. |
| 51 | **Reset Presence Timers** | already plain; unchanged. |

Helper text (`data_description` in strings.json + the Number descriptions) leads with the plain-English effect, states the unit, and ends "Default: N." per house style (`strings.json:958-1013`), using the SAME noun as the final label (e.g. "vacancy delay", "occupied"). The config-flow `presence_timing` section title is drafted "Advanced — presence timing (rarely change)".

### Prior planning docs consulted
- `docs/planning/PLANNING_v4.7.6.1_labels_helpers_excess_solar_number.md` — skim. Most-recent precedent for a "labels + helper-text + promote-config-form-field-to-Number-entity" cycle. Confirms the house style: `data` + `data_description` extensions in strings.json kept in lockstep with translations/en.json, and unique_id stability across renames.
- `docs/planning/PLANNING_v4.7.13_sleep_state_zone_presence_trust.md` — skim. Related domain (presence-trust + HVAC) but does NOT touch presence-timer constants. No overlap.
- `docs/planning/PLANNING_presence_provenance_split_and_fan_diagnostic.md` — skim. Adjacent; no overlap with timer knobs.
- `docs/planning/PLANNING_v4.6.5_in_memory_anomaly_persistence.md` + `PLANNING_v4.6.11_d3_persistence_polish_and_dashboard_attrs.md` — skim. Persistence-class plans; neither addresses the Number-entity-vs-options-source-of-truth question this plan resolves.

### Memory bodies pulled
- `feedback_ura_mirror_pattern` — historical "RestoreEntity = runtime store, entry.options = seed only" pattern (v4.3.2). **This plan is the explicit successor pattern:** entry.options = source of truth, drop RestoreEntity. The operator's reasoning is captured in the brief and verified against `DynamicPresetDwellMinutesNumber`'s current code state.
- `feedback_parsimonious_room_config` — relevant rule: "show the full knob inventory before deploy for a pruning pass." Carried into the deploy checklist below.
- `feedback_plan_phrasing_number_fields` — caveat: "number fields" sometimes meant form fields only, not platform Numbers. **DOES NOT apply here**: operator explicitly asked for BOTH (config-flow form fields AND platform Number entities).
- `feedback_configurability_clarity` — house style for helper text + named-bucket dropdowns. Helper-text drafts below follow this.
- Bug Class #32 (`docs/QUALITY_CONTEXT.md:1144`) — the bug this plan eliminates for the four timers (existing dwell Number persists nowhere; three new timers had no persistence path at all because they had no Number).
- Bug Class #46 (`docs/QUALITY_CONTEXT.md:1766`) — the hazard this plan avoids. The plan's `async_update_entry` calls live ONLY in `async_set_native_value` (runtime user action) and `Button.async_press` (runtime user action). NEITHER is on the setup path. The reload triggered by the listener at `__init__.py:3540-3542` is the standard options-save reload (same as a config-form save), and the task is correctly untracked per B-CRIT-1 (`__init__.py:3531-3540`).
- `feedback_parent_entry_reload_watchdog_hazard` — different scenario (deliberate parent-entry reload to test unload symmetry). Does NOT apply to a CM options-save reload, which is the standard HA pattern.

### Design docs read
- `docs/Coordinator/HVAC_COORDINATOR_DESIGN.md` — exists; consulted for the HVAC Coordinator device-identity contract (`identifiers={(DOMAIN, "hvac_coordinator")}` + `via_device=(DOMAIN, "coordinator_manager")`). All four new entities follow this shape, matching the existing dwell Number at `number.py:308-315`.

### Code locations surveyed end-to-end
- `domain_coordinators/hvac_const.py` — const table around lines 85-130.
- `domain_coordinators/hvac.py:88-91, 221-224, 1037-1130, 1864-1865` — live attr storage and read sites.
- `__init__.py:1953-1967, 2015-2031, 3521-3543` — CM load wiring + options-update listener.
- `config_flow.py:2880-2902 (fan_recheck flatten), 2991 (section), 3894-3971 (HVAC settings save + cover-temp validation), 4200-4255 (HVAC settings schema tail), 4502-4513 (DPM advanced section)`.
- `number.py:277-343 (ZoneEntryDwellNumber), 346-431 (OffPeakDrainNumber Pattern A), 1828-1907 (DynamicPresetDwellMinutesNumber Pattern B writeback)`.
- `button.py:528-585 (ClearBayesianBeliefsButton template)`.
- `strings.json:958-1013` — HVAC settings labels + helper text.

---

## Part 1 deliverables (build this cycle)

Each deliverable lists files touched, the change, and acceptance criteria (Verify / Sensor / Test / Live).

### D1: Three new presence-timer Number entities on the HVAC Coordinator device

**Files:** `custom_components/universal_room_automation/number.py`.

**Change.** Add three new classes alongside `ZoneEntryDwellNumber`:
- `VacancyGraceMinutesNumber` — backs `CONF_HVAC_VACANCY_GRACE_MINUTES`. min=0, max=60, step=1, unit=`UnitOfTime.MINUTES`, `mode=NumberMode.BOX`. `_attr_name = "48 · Zone Vacancy Delay (minutes)"`. `unique_id = f"{DOMAIN}_hvac_vacancy_grace_minutes"`. Pushes to `hvac._vacancy_grace`.
- `VacancyGraceConstrainedNumber` — backs `CONF_HVAC_VACANCY_GRACE_CONSTRAINED`. min=0, max=60, step=1, unit=MINUTES, `mode=NumberMode.BOX`. `_attr_name = "49 · Zone Vacancy Delay · Energy-Saving (minutes)"`. `unique_id = f"{DOMAIN}_hvac_vacancy_grace_constrained"`. Pushes to `hvac._vacancy_grace_constrained`.
- `MaxOccupancyHoursNumber` — backs `CONF_HVAC_MAX_OCCUPANCY_HOURS`. min=1, max=24, step=1, unit=`UnitOfTime.HOURS`, `mode=NumberMode.BOX`. `_attr_name = "50 · Max Zone Occupied Time (hours)"`. `unique_id = f"{DOMAIN}_hvac_max_occupancy_hours"`. Pushes to `hvac._max_occupancy_hours`.

**Input mode — operator decision (2026-06-06): BOX, not slider.** All four presence-timer Numbers (the three above + the retrofitted dwell in D3) use `mode=NumberMode.BOX`. Rationale: these are precise minute/hour values the operator reads and sets exactly; a 0–60 slider is twitchy to land on a specific value (especially on a tablet); sliders earn their keep for rough/bounded/visual settings (dimmer %, eyeballed SOC), not exact timer minutes. Set `mode` EXPLICITLY rather than relying on `NumberMode.AUTO` (AUTO's slider-vs-box range threshold was NOT re-verified this session — explicit BOX is the safe, deterministic choice). This INCLUDES flipping the existing dwell Number from its current mode to BOX so the whole 47–50 cluster is visually uniform.

**Pattern (identical for all three + the retrofitted dwell — D3):**
1. NO `RestoreEntity` inheritance. Inherit `NumberEntity` only.
2. `__init__`: seed `self._value = {**entry.data, **entry.options}.get(CONF, DEFAULT)`.
3. `available` property: `return self._get_hvac() is not None` (same as existing dwell at `number.py:332-334`).
4. NO `async_added_to_hass` restore (the whole point — entry.options is the source).
5. `async_set_native_value(value)`:
   ```python
   self._value = int(value)
   # Live-attr nicety: take effect on the very next decision cycle.
   hvac = self._get_hvac()
   if hvac is not None:
       hvac._<attr_name> = int(value)
   # Persist to entry.options — source of truth.
   self.hass.config_entries.async_update_entry(
       self._entry,
       options={**self._entry.options, CONF_<KEY>: int(value)},
   )
   self.async_write_ha_state()
   _LOGGER.info("<knob name> set to %d", int(value))
   ```

**Platform setup.** Register all three on the CM entry inside the existing `ENTRY_TYPE_COORDINATOR_MANAGER` branch of `async_setup_entry` in `number.py` (around `number.py:41`, same gate as the existing dwell Number).

**Bug Class #46 analysis (REUSED prevention reasoning):** `async_set_native_value` is a runtime user action, not on the setup path. The update_listener-driven reload at `__init__.py:3540-3542` is the standard CM options-save reload. Safe per the conditions enumerated at `docs/QUALITY_CONTEXT.md:1793-1810` ("called from outside `async_setup_entry` entirely"). The live-attr push happens BEFORE the writeback so the operator-perceived latency is zero (next decision cycle picks up the new value immediately; the reload settling later is a no-op for them).

#### D1 Acceptance Criteria
- **Verify:** The three classes appear in `number.py`, NONE inherits from `RestoreEntity`, all three have `async_set_native_value` that (a) sets `self._value`, (b) pushes to the matching `hvac._*` attr, (c) calls `async_update_entry(options=...)`, (d) calls `async_write_ha_state()` — in that order.
- **Sensor:** Post-restart, the URA: HVAC Coordinator device shows three new Number entities: `number.ura_hvac_coordinator_vacancy_grace`, `number.ura_hvac_coordinator_vacancy_grace_energy_saving`, `number.ura_hvac_coordinator_max_occupancy_failsafe` (or whatever Home Assistant slugifies the friendly names to — entity_id stability is via `unique_id`, not display name). `native_value` matches the values in `entry.options` (or the defaults if not yet saved).
- **Test:** Unit test asserts: (a) constructor reads `entry.options` over `entry.data` over default in that precedence; (b) `async_set_native_value(N)` mutates `entry.options[CONF_X] = N` via a mocked `async_update_entry`; (c) live-attr push hits `hvac._<attr>` when coordinator is present; (d) no `RestoreEntity` import / no `async_added_to_hass` restore branch (AST assertion).
- **Live:** On the running HA instance after restart: set the Vacancy Grace slider to 20, wait ~3 s, restart HA, confirm `number.ura_hvac_coordinator_vacancy_grace` reports `20` after restart AND that the value also persists into `entry.options["hvac_vacancy_grace_minutes"]` (read via `config_entries.async_get_entry(<CM_entry_id>).options`). Repeat for the other two timers.

---

### D2: Config-flow — add the three fields inside a new collapsed `presence_timing` section + cross-field validation

**Files:** `custom_components/universal_room_automation/config_flow.py`.

**Change.** Inside `async_step_coordinator_hvac_settings` (`config_flow.py:3894`):

1. **Imports** (`config_flow.py:3901-3951` block): add `CONF_HVAC_VACANCY_GRACE_MINUTES`, `CONF_HVAC_VACANCY_GRACE_CONSTRAINED`, `CONF_HVAC_MAX_OCCUPANCY_HOURS`, `DEFAULT_VACANCY_GRACE_MINUTES`, `DEFAULT_VACANCY_GRACE_CONSTRAINED`, `DEFAULT_MAX_OCCUPANCY_HOURS`.

2. **Section schema** — add a new collapsed section keyed `"presence_timing"`, modeled on `fan_recheck_advanced` (`config_flow.py:2991`). Move `CONF_HVAC_ZONE_ENTRY_DWELL` INTO this section (delete its current top-level definition at `config_flow.py:4218-4228`). The section holds 4 fields in order: vacancy grace, vacancy grace · energy-saving, zone entry dwell, max occupancy failsafe.

3. **Flatten-on-save** — at the top of the `if user_input is not None:` block (`config_flow.py:3958`), add:
   ```python
   advanced = user_input.pop("presence_timing", None)
   if isinstance(advanced, dict):
       user_input = {**user_input, **advanced}
   ```
   placed BEFORE the existing cover-temp hysteresis validation (so the validation block sees flattened values if it ever needs to read them).

4. **Cross-field validation** — after the existing cover-temp validation block, add:
   ```python
   grace = int(user_input.get(
       CONF_HVAC_VACANCY_GRACE_MINUTES, DEFAULT_VACANCY_GRACE_MINUTES
   ))
   grace_constrained = int(user_input.get(
       CONF_HVAC_VACANCY_GRACE_CONSTRAINED, DEFAULT_VACANCY_GRACE_CONSTRAINED
   ))
   if grace_constrained > grace:
       errors["base"] = "vacancy_grace_constrained_exceeds_normal"
   ```
   Reject path is the existing fall-through `async_show_form(..., errors=errors)` at `config_flow.py:4251-4255`.

5. **Selector specifics — all BOX (operator decision 2026-06-06; match the device-Number mode):**
   - Vacancy grace: `NumberSelector(min=0, max=60, step=1, unit="min", mode=NumberSelectorMode.BOX)`.
   - Vacancy grace · energy-saving: same.
   - Zone entry dwell: keep its existing range (`min=0, max=15, step=1, unit="min"`) but FLIP `mode` to `NumberSelectorMode.BOX` (it is currently `SLIDER` at `config_flow.py:4222-4227`) so the section is uniform with the other three.
   - Max occupancy failsafe: `NumberSelector(min=1, max=24, step=1, unit="h", mode=NumberSelectorMode.BOX)`.

6. **Top-level position** — place the new `presence_timing` section AFTER the existing `pre_arrival_sources` selector (`config_flow.py:4203-4217`) and BEFORE the anomaly sensitivity dropdown (`config_flow.py:4229-4246`). This keeps presence-related settings clustered.

#### D2 Acceptance Criteria
- **Verify:** Schema build path produces a `presence_timing` section with exactly 4 fields, collapsed by default. Save path flattens `presence_timing` BEFORE running cover-temp validation. Constraint reject (`grace_constrained > grace`) returns the form with `errors["base"] = "vacancy_grace_constrained_exceeds_normal"`. The top-level `CONF_HVAC_ZONE_ENTRY_DWELL` field is no longer present outside the section.
- **Sensor:** N/A — this is a config-flow surface, not an entity.
- **Test:** (a) `test_hvac_settings_schema_includes_presence_timing_section` — schema dict contains key `"presence_timing"`. (b) `test_hvac_settings_save_flattens_presence_timing` — submitting `{"presence_timing": {...}, "hvac_cover_close_temp": 85, ...}` results in `entry.options` containing the flattened keys. (c) `test_hvac_settings_rejects_constrained_grace_exceeding_normal` — submitting `grace=10, grace_constrained=15` returns the form with the expected error key. (d) `test_zone_entry_dwell_moved_into_section` — top-level schema does NOT contain `CONF_HVAC_ZONE_ENTRY_DWELL` as a direct key.
- **Live:** Open URA → HVAC Coordinator → Configure → HVAC Tuning. The "Advanced — presence timing (rarely change)" section is present and collapsed. Expanding reveals 4 fields. Saving valid values writes to CM `entry.options`. Saving invalid (constrained > normal) shows the inline error and does NOT persist.

---

### D3: Retrofit `ZoneEntryDwellNumber` to writeback + renumber 48 → 47; move `HVACZoneSweepSwitch` 50 → 46

**Files:** `custom_components/universal_room_automation/number.py`, `custom_components/universal_room_automation/switch.py`.

**Change.**
- `number.py:307` — change `self._attr_name = "48 · Zone Entry Dwell"` → `"47 · Zone Entry Dwell (minutes)"` (renumber + add unit per naming pass). unique_id at `number.py:306` is unchanged (entity_id stays).
- `switch.py:2336` — change `self._attr_name = "50 · Vacancy Auto-Off"` → `"46 · Vacancy Auto-Off"` (cosmetic prefix move to cluster with switch 45; one-line label edit only, NO logic change). unique_id (`switch.py:2333` `f"{DOMAIN}_hvac_zone_sweep"`) and entity_id `switch.ura_hvac_zone_sweep` are UNCHANGED.
- `number.py:336-343` (`async_set_native_value`) — add the writeback step. Final body matches the D1 pattern:
  ```python
  self._value = int(value)
  hvac = self._get_hvac()
  if hvac is not None:
      hvac._zone_entry_dwell = int(value)
  self.hass.config_entries.async_update_entry(
      self._entry,
      options={**self._entry.options, CONF_HVAC_ZONE_ENTRY_DWELL: int(value)},
  )
  self.async_write_ha_state()
  _LOGGER.info("Zone entry dwell set to %d minutes", int(value))
  ```
- Confirm there is NO `async_added_to_hass` restore branch to remove (verified: there is none today).

#### D3 Acceptance Criteria
- **Verify:** `ZoneEntryDwellNumber.async_set_native_value` calls `async_update_entry` with the merged options. Display name reads `"47 · Zone Entry Dwell (minutes)"`. unique_id unchanged. `HVACZoneSweepSwitch._attr_name` reads `"46 · Vacancy Auto-Off"`; its unique_id/entity_id are UNCHANGED (an existing dashboard referencing `switch.ura_hvac_zone_sweep` still resolves).
- **Sensor:** `number.ura_hvac_coordinator_zone_entry_dwell` (or whatever HA slugified it as originally — unique_id is stable so entity_id does not change) survives across restarts at the operator-set value. `switch.ura_hvac_zone_sweep` still present (entity_id unchanged, only friendly name moved to the 46 slot).
- **Test:** Update existing dwell test (if any) to assert `async_update_entry` is called with `{CONF_HVAC_ZONE_ENTRY_DWELL: N}` in options. Add an AST test asserting `ZoneEntryDwellNumber._attr_name` starts `"47 · Zone Entry Dwell"` AND `HVACZoneSweepSwitch._attr_name` starts `"46 · Vacancy Auto-Off"` AND that `HVACZoneSweepSwitch._attr_unique_id` is still `f"{DOMAIN}_hvac_zone_sweep"` (entity-identity stability bar).
- **Live:** Set dwell to `5` via device card. Restart HA. Read `number.ura_hvac_coordinator_zone_entry_dwell` — value is `5`. Also confirm `entry.options["hvac_zone_entry_dwell"] == 5` via `config_entries.async_get_entry(<CM_entry_id>).options`. Confirm the HC device card renders 45/46 as adjacent switches and 47-50 as the contiguous Number block.

---

### D4: `ResetPresenceTimersButton` (slot 51) on the HVAC Coordinator device

**Files:** `custom_components/universal_room_automation/button.py`.

**Change.** New class `ResetPresenceTimersButton`, structural template = `ClearBayesianBeliefsButton` at `button.py:528-585`.
- `_attr_name = "51 · Reset Presence Timers"` (parked at the tail of the cluster, right after the four timers it resets).
- `_attr_unique_id = f"{DOMAIN}_hvac_reset_presence_timers"`.
- `_attr_entity_category = EntityCategory.CONFIG`.
- `_attr_icon = "mdi:timer-refresh"`.
- DeviceInfo: `identifiers={(DOMAIN, "hvac_coordinator")}`, `via_device=(DOMAIN, "coordinator_manager")` (same shape as the dwell Number at `number.py:308-315`).
- `async_press` body:
  ```python
  defaults = {
      CONF_HVAC_VACANCY_GRACE_MINUTES: DEFAULT_VACANCY_GRACE_MINUTES,
      CONF_HVAC_VACANCY_GRACE_CONSTRAINED: DEFAULT_VACANCY_GRACE_CONSTRAINED,
      CONF_HVAC_MAX_OCCUPANCY_HOURS: DEFAULT_MAX_OCCUPANCY_HOURS,
      CONF_HVAC_ZONE_ENTRY_DWELL: DEFAULT_ZONE_ENTRY_DWELL_MINUTES,
  }
  # Live-attr push so the next decision cycle picks defaults up instantly.
  manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
  hvac = manager.coordinators.get("hvac") if manager else None
  if hvac is not None:
      hvac._vacancy_grace = DEFAULT_VACANCY_GRACE_MINUTES
      hvac._vacancy_grace_constrained = DEFAULT_VACANCY_GRACE_CONSTRAINED
      hvac._max_occupancy_hours = DEFAULT_MAX_OCCUPANCY_HOURS
      hvac._zone_entry_dwell = DEFAULT_ZONE_ENTRY_DWELL_MINUTES
  # Writeback (single options-save → single reload, not four).
  self.hass.config_entries.async_update_entry(
      self._entry,
      options={**self._entry.options, **defaults},
  )
  _LOGGER.info("Presence timers reset to defaults")
  ```
- Platform setup: register on the CM entry alongside the other CM-scoped buttons (see existing CM-scoped button registrations in `button.py`'s `async_setup_entry`).

**Why one writeback, not four.** Each `async_update_entry` triggers the update_listener → one reload. Bundling all four defaults into a single call yields one reload instead of four cascading ones.

#### D4 Acceptance Criteria
- **Verify:** Button class exists. `async_press` writes all four defaults in a single `async_update_entry` call. Live-attr pushes precede the writeback.
- **Sensor:** `button.ura_hvac_coordinator_reset_presence_timers` (slug-dependent) appears on the URA: HVAC Coordinator device card.
- **Test:** Mocked-bus test asserting (a) a single `async_update_entry` call, (b) defaults exactly match the const values, (c) live-attr push is conditional on `hvac is not None`.
- **Live:** Set Vacancy Grace = 25, Dwell = 8, Failsafe = 12. Press Reset Presence Timers. All four entities snap to default values (15 / 5 / 8 / 3 — matching `DEFAULT_VACANCY_GRACE_MINUTES` / `DEFAULT_VACANCY_GRACE_CONSTRAINED` / `DEFAULT_MAX_OCCUPANCY_HOURS` / `DEFAULT_ZONE_ENTRY_DWELL_MINUTES`) within ~2 s. Restart HA → defaults survive.

---

### D5: strings.json + translations/en.json — labels, helpers, section title, error key, button + Number entity names

**Files:** `custom_components/universal_room_automation/strings.json`, `custom_components/universal_room_automation/translations/en.json`.

**Change.** Extend the existing `coordinator_hvac_settings` block at `strings.json:958-1013`:

- Add to `data`:
  ```
  "hvac_vacancy_grace_minutes": "Zone Vacancy Delay (minutes)",
  "hvac_vacancy_grace_constrained": "Zone Vacancy Delay · Energy-Saving (minutes)",
  "hvac_max_occupancy_hours": "Max Zone Occupied Time (hours)"
  ```
- Add to `data_description` (helper-text house style: terse, direction-of-effect, "Default: N."):
  ```
  "hvac_vacancy_grace_minutes": "Minutes a zone must stay empty before HVAC backs off to the Away preset. Lower = AC retreats faster after you leave. Default: 15.",
  "hvac_vacancy_grace_constrained": "Shorter vacancy delay used while the house is energy-coasting (constrained). Must be ≤ the normal Zone Vacancy Delay. Default: 5.",
  "hvac_max_occupancy_hours": "If a zone reads continuously occupied this long, HVAC treats the presence signal as stuck and stops trusting it. Default: 8 (hours)."
  ```
- Existing `hvac_zone_entry_dwell` label (`strings.json:974`) + helper (`strings.json:1000`) stay verbatim. Helper already reads "Default: 3." which matches house style.
- Add a `sections` block (new key inside `coordinator_hvac_settings`) for the section title:
  ```
  "sections": {
    "presence_timing": {
      "name": "Advanced — presence timing (rarely change)"
    }
  }
  ```
  (Mirror whatever shape HA expects for section title localisation — verify against the existing `fan_recheck_advanced` / DPM `advanced` section keys in `strings.json` before shipping.)
- Add an error message under the existing `error` map of the relevant step (verify location):
  ```
  "vacancy_grace_constrained_exceeds_normal": "Energy-Saving Zone Vacancy Delay must be less than or equal to the normal Zone Vacancy Delay."
  ```
- Add the three Number entity friendly names + the button name under the existing `entity.number` / `entity.button` translation blocks. Use the same `_attr_name` strings as the code-side definitions (D1, D3, D4) so the device card renders the numbered prefixes verbatim.
- Mirror ALL of the above changes verbatim into `translations/en.json`. The two files must stay in lockstep — this has burnt prior cycles.

#### D5 Acceptance Criteria
- **Verify:** `data`, `data_description`, `sections`, and `error` blocks all updated in BOTH files. Helper text for the three new fields follows the "Default: N." closer style.
- **Sensor:** Device card displays the friendly names + helper text correctly.
- **Test:** AST/JSON test that asserts `strings.json` and `translations/en.json` have IDENTICAL keys under `coordinator_hvac_settings.data` / `.data_description` (any one-side addition is a bug).
- **Live:** Open the HVAC Tuning form → confirm the three new fields show with friendly labels + helper text. Trigger the constraint reject → confirm the error message renders.

---

### D6: Tests

**Files:** `quality/tests/` (location matching existing entity / config-flow test conventions).

**New tests** (in addition to the per-deliverable tests called out above):
1. `test_no_restore_entity_on_presence_timer_numbers` — AST scan: assert none of `VacancyGraceMinutesNumber`, `VacancyGraceConstrainedNumber`, `MaxOccupancyHoursNumber`, `ZoneEntryDwellNumber` inherit from `RestoreEntity`. (Acts as a regression bar.)
2. `test_presence_timer_numbers_writeback_on_set` — for each of the four Numbers, mock `async_update_entry` and assert `async_set_native_value(N)` calls it with the matching CONF key set to `N` inside merged `options`.
3. `test_presence_timer_numbers_live_attr_push_before_writeback` — assert the `hvac._<attr>` push happens BEFORE `async_update_entry` (call-order assertion via mock).
4. `test_reset_presence_timers_button_single_writeback` — assert one `async_update_entry` call carrying all four defaults; assert all four live attrs set on mocked hvac.
5. `test_hvac_settings_form_presence_timing_section_present` — schema build returns dict with `"presence_timing"` key.
6. `test_hvac_settings_form_constrained_validation` — invalid input (`grace_constrained > grace`) yields `errors["base"] == "vacancy_grace_constrained_exceeds_normal"` and does NOT call `async_create_entry`.
7. `test_strings_and_translations_data_keys_in_lockstep` — JSON load both files, diff key sets under `coordinator_hvac_settings.data` / `.data_description`; assert equality.
8. `test_zone_entry_dwell_display_name_47` — AST/regex on `number.py` confirming `_attr_name` starts `"47 · Zone Entry Dwell"`; and `test_vacancy_sweep_switch_renumbered_46` confirming `HVACZoneSweepSwitch._attr_name` starts `"46 · Vacancy Auto-Off"` while `_attr_unique_id` is still `f"{DOMAIN}_hvac_zone_sweep"`.
9. `test_presence_timer_numbers_use_box_mode` — assert all four presence-timer Numbers set `_attr_mode = NumberMode.BOX` (no slider), and the four config-flow `NumberSelector`s use `NumberSelectorMode.BOX`.

#### D6 Acceptance Criteria
- **Verify:** All 8 tests above pass in addition to the per-D tests in D1-D5.
- **Test:** `PYTHONPATH=quality python3 -m pytest quality/tests/ -v` baseline-diffs CLEAN against `pre-review-v<assigned>` (no regressions on unrelated suites).
- **Live:** N/A (test-only deliverable).

---

## Part 2 — DEFERRED retrofit (do NOT build this cycle)

**Operator instruction verbatim:** "We don't have to fix now. For EC. but we can do it in this pass on HVAC and then retrofit to EC."

HVAC is the reference implementation. The same pattern (entry.options = sole source of truth + writeback in `async_set_native_value` + live-attr push nicety + DROP `RestoreEntity`) gets applied to the following Number classes in a later cycle. Confirmed line numbers from `number.py` in this session:

**EC Numbers (RestoreEntity Pattern A — restore on add → push to coordinator, NO writeback):**
- `OffPeakDrainNumber` — `number.py:346`. Backs `CONF_ENERGY_OFFPEAK_DRAIN_{EXCELLENT,GOOD,MODERATE,POOR}` (per-quality 4 instances, see `number.py:389-396`). Setter: `energy.set_offpeak_drain(quality, value)` at `number.py:419-420`.
- `PeakBufferTargetNumber` — `number.py:433`.
- `ArbitrageChargeLeadTimeNumber` — `number.py:558`.
- `EVBatteryDrainSOCNumber` — `number.py:681`.
- `FillPrioritySOCNumber` — `number.py:808`.
- `ExcessSolarSOCNumber` — `number.py:924`.
- `BayesianCellStalenessNumber` — `number.py:1043` (not strictly EC, but same RestoreEntity Pattern A — fold into the same retrofit).

**DPM / HVAC RestoreEntity Numbers (Pattern B — RestoreEntity + writeback; just drop the RestoreEntity inheritance and the `async_added_to_hass` restore branch):**
- `DynamicPresetDwellMinutesNumber` — `number.py:1828`. Already does the writeback at `:1900-1903`; need to drop the RestoreEntity branch at `:1884-1891` and update the docstring at `:1834-1836` (currently OUT OF DATE; says "no writeback" while the code writes back).
- `DynamicPresetHysteresisFNumber` — `number.py:1910`.
- `HVACEgressPauseThresholdNumber` — `number.py:2003`.
- `HVACEgressResumeDelayNumber` — `number.py:2102`.
- `FanInterferenceHoldNumber` — `number.py:2200`.

**Per-platform HVAC tunable factory (also RestoreEntity Pattern A — verify):**
- `_HVACTunableNumber` — `number.py:1347`. Generates the 60-66 cover/fan cluster. Same retrofit applies.
- `_HVACZoneKwhThresholdNumber` — `number.py:1685`. Same.

### OPEN QUESTION (capture for operator decision, do NOT decide here)

The 4 per-ROOM Numbers — `TimeoutOverrideNumber` (`number.py:133`), `ComfortTempMinNumber` (`number.py:169`), `ComfortTempMaxNumber` (`number.py:205`), `ComfortHumidityMaxNumber` (`number.py:241`) — inherit from `UniversalRoomEntity, NumberEntity` (not `RestoreEntity`). They live on ROOM entries, not the CM entry. So the writeback target differs (the room entry's options, not the CM's). **Question:** Are these in scope for the Part-2 retrofit, or are they their own track? Flag for operator decision when Part 2 is scheduled. Do not assume.

### Where Part 2 is tracked
- Add a backlog memory entry on close-out of Part 1 referencing this planning doc by name (filename, since no version is stamped). Title: "Options-writeback retrofit — EC Numbers + DPM/HVAC RestoreEntity Numbers."
- Do NOT plan or pre-stamp a version for Part 2. Per operator versioning convention, version is assigned at the next deploy.

---

## Tier classification rationale

**Tier 2 (two parallel reviews with disjoint framings).** Reasoning:
- Multiple files (number.py, config_flow.py, button.py, strings.json, translations/en.json, tests).
- New device entities + new config-flow form fields.
- Touches `async_update_entry` from a runtime user action — Bug Class #46 risk surface, even though the safety analysis is clear.
- NO DB shape change. NO listener registration surgery. NO new persistent table. → does NOT trip the Tier 2-DB criteria.
- The pattern itself (entry.options as sole source of truth) is a doctrinal flip from the v4.3.2 "mirror pattern" memory — even though the current `DynamicPresetDwellMinutesNumber` already does writeback, codifying this as THE pattern for the integration deserves a second pair of eyes.

**Suggested reviewer framings:**
- **Reviewer A — correctness + edge cases + Bug Class #32 + form-validation.** Check: every code path that writes `entry.options` matches the agreed pattern; cross-field validation (`grace_constrained ≤ grace`) rejects correctly and renders the error key; the flatten-on-save merge order is correct relative to validation; helper text is house-style and accurate; strings/translations lockstep.
- **Reviewer B — async + lifecycle + race conditions + Bug Class #46.** Check: every `async_update_entry` site is NOT on the setup path; the live-attr push before writeback is safe under concurrent decision-cycle reads (HVAC reads from another task); the CM reload triggered by the update_listener is correctly untracked (cross-check `__init__.py:3540-3542` invariant per B-CRIT-1); button-press rapid-fire does not enqueue overlapping reloads in a problematic way; renumbering the dwell Number does not break any test that asserts the literal `_attr_name`.

---

## Pre-deploy zero-bugs gate (per `feedback_pre_deploy_zero_bugs_gate`)

Before running `./scripts/deploy.sh <assigned-version> <summary> <release-notes>`:
1. `git grep -nE '<<<<<<< |>>>>>>> '` — no merge conflict markers.
2. `python3 -m py_compile` on every changed `.py` (number.py, config_flow.py, button.py + any test files).
3. `PYTHONPATH=quality python3 -m pytest quality/tests/ -v` — all D6 tests + baseline diff CLEAN.
4. Open the URA: HVAC Coordinator device card mentally — list every Number, Button, Switch, Sensor under their friendly-name prefixes 40-59 and confirm visual order matches the operator's mental model. **Show this inventory to the operator before deploy** (parsimonious-room-config rule: pruning pass before commit).
5. Verify HACS installed_version matches the assigned version post-deploy; restart HA; run live validation D1+D3+D4 acceptance criteria.

---

## Post-deploy README validation table

Per the URA "Record Live Validation Back Into the README" rule, after live validation runs, the `README_v<assigned>.md` MUST be updated with an observed-results table. Prospective Live bullets in D1 / D2 / D3 / D4 / D5 each become rows in that table with PASS / FAIL and concrete entity_id + attribute evidence (the four `number.*` `native_value`s post-restart; the `entry.options` dict read; the form render; the constraint-reject error message).

---

## Plan Completion Tracking — explicit deferral list

Items NOT being built this cycle and where they are tracked.

| Item | Why deferred | Where tracked |
|---|---|---|
| Apply options-writeback pattern to EC Numbers (`OffPeakDrainNumber`, `PeakBufferTargetNumber`, `ArbitrageChargeLeadTimeNumber`, `EVBatteryDrainSOCNumber`, `FillPrioritySOCNumber`, `ExcessSolarSOCNumber`, `BayesianCellStalenessNumber`) | Operator instruction — HVAC is the reference implementation; retrofit EC in a later pass. | This planning doc, Part 2; new backlog memory entry on Part-1 close. |
| Drop `RestoreEntity` + update docstring on DPM/HVAC RestoreEntity Numbers (`DynamicPresetDwellMinutesNumber`, `DynamicPresetHysteresisFNumber`, `HVACEgressPauseThresholdNumber`, `HVACEgressResumeDelayNumber`, `FanInterferenceHoldNumber`) | Same retrofit pass as EC. The current code is already doing the writeback for some — needs the RestoreEntity inheritance dropped and the v4.3.2-mirror docstring corrected. | Part 2 (same backlog entry). |
| Retrofit `_HVACTunableNumber` factory + `_HVACZoneKwhThresholdNumber` factory | Same retrofit pass; touches a different code shape (factories) so will need its own targeted review framing. | Part 2 (same backlog entry, sub-bullet). |
| Per-room Number retrofit (`TimeoutOverrideNumber`, `ComfortTempMinNumber`, `ComfortTempMaxNumber`, `ComfortHumidityMaxNumber`) | OPEN QUESTION — these live on room entries, not the CM entry; writeback target differs. Operator must decide whether they are in scope for the EC retrofit or a separate track. | Part 2 (flag in the backlog entry as an open Q). |
| Updating QUALITY_CONTEXT.md to codify "entry.options = sole source of truth" as the pattern, retiring the v4.3.2 mirror-pattern guidance | Post-review documentation step; happens after the Part-1 review cycle when the new pattern has at least one shipped instance. | Tier-2 review fix-up + the standard post-review "check if a new bug class needs adding" step in CLAUDE.md. |
| Version assignment | Per operator versioning convention, versions are assigned at deploy time. | Deploy step. |
| Config-flow `errors["base"]` collision (Tier-2 A-MED-1) — cover-temp and vacancy cross-field errors can't surface together (two-trip fix) | Surfacing both needs field-attached errors inside a `section(...)`, whose HA rendering is unverified (No-Fabrication). Single-base-error is the established convention across all 15 base-error sites; not a regression. | Form-UX backlog; revisit only if it bites. See `docs/reviews/code-review/hvac_presence_timer_knobs_tier2.md`. |
| CM reload fan-out on rapid Number edits (Tier-2 B-H1) — ACCEPTED, not deferred | Convergent by design (per-entry reload lock + reseed from entry.options). A debounce timer was rejected as over-engineering (own untracked-timer hazard). Documented at the live-attr push sites. | Closed in-review; no follow-up. |
