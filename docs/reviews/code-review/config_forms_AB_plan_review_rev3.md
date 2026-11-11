# Plan review (rev 3): FORM-CONDITIONAL-FIELDS-1 + FORM-TEXT-PLAIN-PASS-1

Tier-2 adversarial plan review, one pass. Targets on develop `bc67a321`:
- `docs/planning/PLANNING_config_forms_sections_and_conditional_fields.md` rev 3 (§0, §13, §14)
- `docs/planning/AUDIT_form_text_plain_pass.md`

Read in full before judging: both targets, prior reviews `config_forms_AB_plan_review_1.md` / `_2.md` (headers), `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md`, `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (HVAC text rows C5-C11, zone_hvac rows), memory `feedback_label_style_guide.md`, `feedback_configurability_clarity.md`. No presence or HVAC ledger claim is re-asserted below.

**Verdict: FIX-PLAN.** The marker count holds and release 1 is buildable on the 2026.2.3 harness, but four HIGH gaps would let the builder ship raw-key labels or silent value loss, and three text rows say something the code does not do.

---

## 1. Release 1 buildability (ask 1): PASS

- `.venv-ha` = HA 2026.2.3; `homeassistant/data_entry_flow.py:921` `class section` exists, no `visible`, no `Optional`/`Required` marker classes. Release 1 (D2 + D3 + text) needs only `section`, already imported at `config_flow.py:30-35` (`_ha_section` shim) and `:8626`.
- `hacs.json` has no `homeassistant` key today; nothing in release 1 needs one. Correct per D5.
- Nothing in D3 needs 2026.11 API. **But see L5:** D2 lists "a `visible` evaluator if D0(f) finds none" and `_absent_field_defaults` case (b) (visible-false fields). D0(f) has not run, so the builder cannot tell whether release 1 builds the evaluator. Say "release 1: case (a) only; evaluator and case (b) ship with D4".

## 2. Advanced-marker / `show_advanced_options` re-enumeration (ask 2)

Field markers confirmed **67**: `grep -c "description=_adv("` = 53; `adv` variable at `config_flow.py:1651`, used by 8 fields (`:1688-1728`); `advanced_if_empty=True` at `:2478`, `:2493`, `:2498`, `:2546`, `:2552` (5); literal `:13606` (1). The flag is read only in `config_flow.py` (a package-wide grep finds no other file). The room_class skip (`:2336-2341`) and the lighting clearable list (`:14116`) are in §13. Two non-marker uses are **missing**:

### H3 (HIGH, missed behaviour): `integration_config` has two `_show_adv()` branches that are not markers
`config_flow.py:1597-1623`:
- `:1614-1617` with Advanced off, `CONF_NOTIFY_SERVICE` is filled from the chosen phone (`notify.*`), because the legacy alert sender only fires on `CONF_NOTIFY_SERVICE` (comment `:1608-1613`).
- `:1620-1623` with Advanced off, the energy screen is **skipped** (`async_step_energy_setup(user_input={})`).

D3 deletes `_show_adv`, so the builder has to pick a behaviour for both, and §13 gives none. Live today (2026.11, property True) both run the Advanced path: energy step shown, no phone fallback. The 2026.2.3 harness tests (`test_onboarding_simplify_phase2.py`) exercise the not-Advanced path. Fix: add §13 rows 69-70 that state the target (recommend: energy step always shown, as live; keep the phone → notify-service fallback unconditionally when the service is blank, since nothing else populates it) and the test that pins each.

Other `_show_adv` callers (`:2379`, `:2515`, `:4394`, `:4606`, the 11 `_filter_advanced` sites) are covered by §1 / D3.

## 3. D1 row spot-checks (ask 3): 14 rows checked, correct except the gaps noted

| Row | Checked | Result |
|---|---|---|
| 1-8 integration_config | `:1651-1735`, callers `:1601`, `:1624` only | Correct, create-only. **L1:** §4 table says "integration_config (create + Options) 1-2"; there is no Options use of `_integration_config_schema`. Fix the §4 row. |
| 9-11 sensors_confirm | `:2449-2500` | Marker correct. See **H4** (target is wrong for these). |
| 19, 22, 23, 31, 32-37 save effect | `__init__.py:7733-7800` `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` | live-apply rows correct; 20, 21 (`enhanced_census`, deliberately not allowlisted) correct as reload. |
| 32-36 enrichment gate | `perimeter_enrichment.py:147-190` | Y correct: the four reads are after `_is_enabled_for_camera`. No other reader (grep). |
| 45 / B13 zone DPM | `dynamic_preset.py:581`, `:859`, `:940` | Y correct (gate 1 returns first). |
| 47 night-light sleep brightness | `switch.py:5661-5670`, resolver | Y correct. `actuator_reconciler.py:68` and `automation.py:175` only import it. |
| 52-61 lighting | `_ROOM_SUPPRESS_KEYS` `__init__.py:8519-8673` | reload correct (none listed). See **H2** for the clearable pops. |
| 63 sunset offset | `automation.py:2739-2763` | Y correct. |
| 64-67 climate | `__init__.py:8661` lists all three speed temps + `HUMIDITY_FAN_MAX_RUNTIME` | live-apply correct. |
| B1/B2 sleep | `automation.py:1297`, `:1312-1318` | Y correct. Hours stay visible (correct, `aggregation.py:885`). |
| B8 cover close temp | `hvac_covers.py:428`, `:462` | Y correct. |
| B10-B12 | `config_flow.py:8723-8770` | **L2:** left as "rule 2 if all its fields depend; else rule 1". The source already answers it: relax mode, cool-day relax and hot-day tighten are top-level; the `advanced` section holds dwell/hysteresis/deltas. Resolution = rule 1. "No row ships ambiguous" (§4) is violated as written. |

Dropped pairs, both right:
- O16 known guests: `perimeter_alert.py:4977-4980` and `camera_census.py:3993`, `:4069` read it with no face toggle.
- O3 Timed-close: `_is_cover_close_time` (`automation.py:2733-2758`) has no Timed-close gate, and it is also reached from the open-intent check.

Fan-speed re-spec `not_eq off` is right: `fan_owner` returns None only for Off (`const.py:1408-1412`), and `automation.py:2789-2791` returns before `:3204-3206`. **L3 (release 2):** `room_fan_mode()` maps a missing key through the legacy toggles and an unknown value to `off` (`const.py:1443-1450`). The `visible` condition sees the form value, so the climate form default for `CONF_ROOM_FAN_MODE` must be `room_fan_mode(merged)`, not the raw stored key. Otherwise an unmigrated room hides the temperatures it is using.

## 4. Save-path findings the D1 table does not cover

### H2 (HIGH, silent value loss): Options steps that read "key absent" as "clear"
§3 shape 1 says merge, no backfill. §8 Q6 ("does the frontend always send a section dict?") is marked "plan is built to not care". That holds for create (case a) and for plain merges. It does **not** hold for two restructured Options steps that delete stored values when a key is missing from the submit:
- **Options `sensors`:** `raw_caps = user_input.pop("sensor_capabilities_json", "")` (`config_flow.py:12892`), then `merged.pop(CONF_SENSOR_CAPABILITIES)` when the payload is empty (`:13215-13218`). Row 46 moves `sensor_capabilities_json` into the collapsed section. If the section dict is absent, every per-sensor capability override is deleted on a no-edit save, including `trust_class` / `failure_mode`, which can only be set through that JSON. The per-entity dropdowns are processed before this (`:12957-13116`), so a partial payload can survive while the JSON-only fields are lost.
- **Options `options_lighting_behaviour`:** the clearable loop (`:14102-14121`) pops the 7 evening/scene keys whenever they are missing from the submit. These are rows 55-61, all moving into the section.

The repo already treats "absent section" as a real case: `config_flow.py:6511` ("absent section = untouched", energy cloud_verification). Fix:
- State the rule in §3: a clear-on-absent site may clear a section key only when that section's dict was present in the raw `user_input`. Name both sites.
- Add a harness variant to D2 that **omits** unexpanded section dicts on Options (today D2 step 2 always nests, so INV-1a cannot see this).
- Add a Review C drill: drop the presence guard at one site and expect the omitted-section round-trip test to go RED.

### H4 (HIGH): create confirm steps put area guesses in a collapsed section, and the backfill cannot restore single-entity guesses
- Rows 9-13 move `presence_sensors`, `door_sensor`, `water_leak_sensor`, `auto_switches`, `humidity_fans` into a collapsed section **unconditionally**. Today each is Advanced only when it has no area guess (`:2460`, `:2471`, `:2537`).
- The single-entity guesses travel only as `description={"suggested_value": guess}`, never `default=` (P4 comment `:2441-2447`, v5.37.1 clear hazard).
- `_absent_field_defaults` case (a) returns marker defaults (`_collect_schema_defaults`, `:3942-3968`, reads `marker.default` only). So if the frontend omits a never-expanded section (Q6), the area-guessed door and water-leak sensors are dropped on create.
- The water-leak pre-fill is the safety path (`:2496`). This is silent loss of leak alerting for that room.
- The presence radar list (the still-person holder, SENSOR_FLEET_CLASSES Rule 1) would also be hidden one click down on the first screen that asks for it.

Fix: keep these five fields on the top level of the create confirm steps (placement rule 5's spirit: the guess is the value the step needs). Or, at minimum, have `_absent_field_defaults` include `suggested_value` for create and test it. Recommend the first: it is simpler, and §6's argument ("a collapsed section shows saved values") does not apply on create, where there is nothing saved yet.

### M1 (MEDIUM): section strings are under-specified (ask 5)
- HA reads a section field's label from `step.<id>.sections.<section>.data` / `data_description`, not from `step.<id>.data`. Existing example: `options.step.coordinator_presence.sections.fan_recheck_advanced.data` holds all 8 fan labels, and none of them is in the step's `data` (checked).
- D3 says only "section label strings added per new section". The builder must **move** each of the 55 release-1 fields' `data` + `data_description` entries into `sections.advanced`, in both `strings.json` and `translations/en.json`, for every step. Otherwise every moved field renders its raw key, which is the exact defect the §14 text pass exists to remove. Release 2 moves the 14 B rows back up again.
- Steps needing a new `sections.advanced` block: config `integration_config`, `sensors_confirm`, `devices_confirm`. Options `global_sensors`, `energy_sensors`, `person_tracking`, `camera_census`, `perimeter_alerting`, `zone_rooms`, `zone_media`, `zone_hvac`, `zone_energy`, `zone_dynamic_preset`, `sensors`, `devices`, `options_lighting_behaviour`, `options_covers`, `climate`.
- `options_lighting_behaviour` and `climate` already have two sections each. `hvac_dynamic_preset` already has an `advanced` section label (`strings.json:1336`), so check the collision rule in strings too.
- The audit's `test_every_form_field_has_label` must resolve section fields against `sections.<name>.data`. Say so in audit §4.

Fix: list these steps in D3 with "move, don't copy", and extend the parity test to section blocks.

## 5. Text table accuracy (ask 4)

Checked against code: P1-P18 (all), R1-R12 (all), C5, C6, C7, C8, C10, C11, C16, C17, C18, C19, Z4, Z8. Accurate unless listed.

### M2 (MEDIUM, wrong): C11 `hvac_cover_entities`, "Empty = use each room's covers"
`hvac_covers.discover_covers` (`hvac_covers.py:170-189`) always takes room covers from HVAC-zone rooms first (phase 1, per-room `CONF_COVER_HVAC_MANAGED` opt-out). The CM list adds covers not already found. The list never replaces room covers. Proposed: "Extra blinds to close on hot, sunny days, on top of the covers in HVAC-zone rooms (a room can opt out on its Covers step)."

### M3 (MEDIUM, over-claims): P6 `lost_away_grace_min`
"How long to wait before the house may switch to Away" is not what happens in most cases. Path β skips the grace once census = 0, unidentified = 0 and indoor-clear hold for `CONF_LOST_AWAY_INDOOR_CLEAR_TICKS` (3) ticks (`presence.py:1302-1316`, `:7585-7598`). Those same conditions are already required for β to fire at all. So the 60 min only applies while cameras or rooms still disagree. Proposed: "When a resident's phone has gone silent, how long to wait before the house may switch to Away without them, unless the cameras and every room have read empty for a few updates in a row. Default 60."

### M4 (MEDIUM, unverified equivalence): P9 / R1 "Same as the Fan Recheck switch"
- The form field and the device switch are not symmetric. `FanRecheckEnabledSwitch` (`switch.py:5976-6062`) seeds from options in `__init__`, then `async_added_to_hass` overwrites the value from `async_get_last_state()` (`:6041-6047`). Its own docstring calls RestoreEntity "the canonical runtime store".
- A form save of `fan_recheck_enabled` reloads the CM entry, because the key is not in `OPTIONS_RELOAD_SUPPRESS_KEYS`. The switch is re-created, and if its restored last state is the old value, the form edit is undone at runtime while `options` keeps the new value.
- I did not run this. HA's restore-on-entity-removal behaviour decides it.
- Fix: before the text says "same as", verify with one test through the reload. If it reproduces, card it (form edit reverted by RestoreEntity) and word P9 as "The Fan Recheck switch on the Presence device controls the same thing; use the switch to change it."
- The per-room switch (R1, `switch.py:6065`) has the same shape.

### M5 (MEDIUM, audit miss): create `sensors_confirm` shows two raw keys today
- `strings.json` `config.step.sensors_confirm.data` labels `mmwave_sensors` and `door_sensors`. The form's real keys are `presence_sensors` (`CONF_MMWAVE_SENSORS`, `const.py:627`) and `door_sensor` (`CONF_DOOR_SENSORS`, `const.py:1111`).
- Effect: the presence radar list and the door sensor render as raw keys on the create flow's sensor-confirm screen, and there are two more dead strings.
- The audit's counts (39 raw, 22 dead) miss both. The likely cause is that the AST scan does not follow keys passed into `_multi(...)` / `_opt_single(...)`.
- This is presence text on the step the operator meets first, and it should sit with R6/R7. Re-run the scan through helper-argument keys and re-count.

### LOW text findings
- **L-T1 P11** "before a check is planned": the arm delay runs after arming and before the pause (`_enter_armed` `presence_fan_recheck.py:735-745`, re-checked by `_still_armed_eligible`). Use "before the fan is paused".
- **L-T2 P7** "Between Home Night and Waking": the exemption covers SLEEP / HOME_NIGHT / WAKING plus any hour inside the house sleep window (`presence.py:7600-7608`). Use "at night (from Home Night through Waking, or inside the house sleep hours)".
- **L-T3 R5** "An overnight stay here turns on Guest mode": entry needs a qualifying night plus ≥ 0.10 of the same room's day window (`GUEST_STAY_DAY_MIN_FRACTION`, Presence STATE_OF_PLAY §2 step 3). Use "A day and a night here turns on Guest mode".
- **L-T4 R2** "Off = skip the check whenever anyone is nearby": off vetoes whenever anyone is in the zone (`presence_fan_recheck.py:700-713`), not only nearby. Use "anyone is in this part of the house".
- **L-T5 C8** omits the default (72 °F, `automation.py:4241-4243`), which audit rule 3 requires. **C9** label "Energy Saver Pre-Cool" is Title Case, against audit rule 3.
- **L-T6 C16** under-claims: picking the Envoy entity auto-fills the other Enphase entity ids from its serial (`repairs.py:79-83` `derive_envoy_config`). Add one clause.
- Style: every proposed label is a short phrase and every description says what it does. Where a default exists, most also say when to change it. P9's "Fan check" vs the device switch "Fan Recheck" leaves two names for one control. Pick one or name both.

## 6. Acceptance criteria and builder traps (ask 6)

- **L4:** INV-1a / D2 assume the frontend sends section dicts. Add the omitted-section variant (H2), or the round-trip tests cannot falsify H2 or H4.
- **L5:** release-1 scope of the D2 helpers (see §1).
- **L6:** the `_ha_section` fallback (`config_flow.py:33-35`) returns the bare schema when HA's `section` cannot be imported, so `_flatten_sections` (identifying sections by type) is blind under that mocked harness. Have the helper also accept the fallback shape, or have the collision test assert the real `section` class is in use.
- **L7:** the §1 citation `config_flow.py:5559-5561` (the "no inner defaults" comment) has drifted; that line is now the coordinator_presence import block. Re-cite.
- Discriminating criteria (D3) are good. INV-P's "editing one key not on the suppress set triggers exactly one reload" is a strong discriminator. Keep it.
- Audit §4 old-claim pins: also pin C11 and P6 once rewritten (they are wrong or over-claiming today, but not in the WRONG list).

## 7. Summary

| Sev | ID | Finding | Bug class |
|---|---|---|---|
| HIGH | H2 | Options clear-on-absent sites (sensors caps JSON, lighting clearables) delete values when a section is omitted | #53 one missed site / silent value loss |
| HIGH | H3 | `integration_config` notify fallback + energy-step skip not in D1 | #53 |
| HIGH | H4 | create guesses (incl. water-leak, presence radar) moved into a collapsed section; backfill ignores `suggested_value` | silent value loss |
| MED | M1 | section field strings must move to `sections.advanced.data`; step list not given | #53 (raw-key labels) |
| MED | M2 | C11 text wrong | display prose lies |
| MED | M3 | P6 text over-claims | display prose lies |
| MED | M4 | P9/R1 "same as switch": RestoreEntity may revert form edits | #63-adjacent (two stores, one concept) |
| MED | M5 | sensors_confirm raw keys + 2 dead strings missed by the audit | scan completeness |
| LOW | L1-L7, L-T1..L-T6 | as above | — |

**Must fix before build dispatch:** H2, H3, H4, M1, M2, M3, M5. Resolve M4 by a test or by rewording.
