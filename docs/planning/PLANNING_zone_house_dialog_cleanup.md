# PLANNING — Zone and House dialog cleanup (ZONE-DIALOGS-CLEANUP-1 + HOUSE-DIALOGS-CLEANUP-1)

**Status:** REV 1 (draft, needs plan review). **Tier 2** (options-flow UI only, plus string files and tests; no runtime behaviour change).
**Cards:** `ZONE-DIALOGS-CLEANUP-1` (kanban.data.yaml:30533), `HOUSE-DIALOGS-CLEANUP-1` (kanban.data.yaml:30543).
**Precondition:** `ROOM-TYPE-TRIMMED-MENU-1` (REV 4, build-ready, status `pre_planning`) ships first. It supplies the shared pieces this plan reuses: `advanced_hint()` (rename of `lighting_advanced_hint`, config_flow.py:58), `_adv(key, merged, default)`, the I2 forced-render rule and the I3 save guard. This plan triggers that card's "Parked follow-on" (PLANNING_room_type_trimmed_menu.md:397-409) for the zone and house flows only.

**Scope words.** In the UI the integration entry is **House** and the Coordinator Manager entry is **CM** (config_flow.py:3533-3536 comment: "House / CM / Room"). This plan covers:
- **Zone Manager** options flow: full field pass.
- **House** (integration entry) options flow: full field pass.
- **CM**: menu-level fixes only (orphan steps, menu labels), plus a per-step inventory. Field-level Simple/Advanced work for each coordinator is split into follow-on cycles, as the House card says ("then the per-coordinator dialogs"). CM has about 260 fields, and the cost/safety knobs (energy, HVAC) belong in Tier 2-DB cycles of their own.

---

## Institutional context verified

### Greps run and results

| Proposed piece | Verdict | Evidence |
|---|---|---|
| Simple/Advanced hint text | REUSE (after the precondition card renames it) | `lighting_advanced_hint` config_flow.py:58, `LIGHTING_ADVANCED_HINT_HIDDEN/_SHOWN` :50-55. Becomes `advanced_hint` in ROOM-TYPE-TRIMMED-MENU-1 D8.3 |
| Advanced field marker | REUSE | `description={"advanced": True}`, already used by Lighting (PLANNING_room_type_trimmed_menu.md:242). `_adv()` comes from the precondition card (D8.2) |
| `show_advanced_options` gate | REUSE | HA flow property, used at the Lighting save guard (precondition plan :282, config_flow `:11611-11624`) |
| Factory-default comparison | REUSE the rule, not the shim | Zone and House handlers render defaults from module constants (`DEFAULT_*`), not from `_get_current` alone. `_adv` compares against those `DEFAULT_*` constants directly, so the room shim (`_render_step_schema`) is not needed here |
| Label/helper meta-test | EXTEND | `quality/tests/test_room_dialog_strings.py` (step lists :39/:64, `MAX_HELPER_LEN = 220` :87, assertions :266-293, menu-label test :296). Parametrise over new `ZONE_OPTIONS_STEPS` / `HOUSE_OPTIONS_STEPS` lists. No new framework |
| Reload-suppress allowlist (constraint, not changed) | REUSE as-is | `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` `__init__.py:7125-7193`. Simple-mode saves must not change which keys look "changed" (see D5) |
| Zone shared-thermostat mirror (constraint) | REUSE as-is | `MIRROR_KEYS_ZONE_*` config_flow.py:763-802; `_auto_mirror_to_siblings` |
| New CONF_* / sensor / helper | **NONE proposed** | Only string, marker and menu-list edits, plus one new test file |

### Prior planning docs consulted
- `PLANNING_room_type_trimmed_menu.md` REV 4: full read of D2, D3, D7-D9, the acceptance criteria and the parked follow-on (:397-409). This is the mechanism being reused.
- `PLANNING_room_dialog_cleanup_and_lighting_roles.md`: its "Zone / House dialog cleanup — problem list" (:329-333) is the seed list for this plan. Its cited card line (:30571) is stale; the card is at :30533.
- Card adjacency: `CM-CONFIG-FLOW-UX-1`, `-SELECTORS-1` (done, CM menu rows and two sub-editors), `ROOM-DIALOGS-USABILITY-SWEEP-1` (shipped `58464918d`, created the meta-test), `CM-ZONE-MENU-POLISH-1` / `MENU-ZONE-PICKER-1` (v5.100.4 one-tap zone menu, config_flow.py:9041-9101).

### Memory bodies applied
`feedback_label_style_guide` (short phrase, plain helper text, entity names of 3 words or fewer, no nerd words), `feedback_configurability_clarity` (named buckets, set-once knobs belong in the config flow), `feedback_parsimonious_room_config`, `feedback_extend_existing_never_rebuild`, `project_house_zones_vs_hvac_zones` (a house zone is not an HVAC zone, so labels must say which one they mean), `feedback_parent_entry_reload_watchdog_hazard`.

### Design docs
`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` was **not** fully read for this plan. That is acceptable only because no HVAC behaviour changes. The `zone_hvac` / `zone_dynamic_preset` wording edits are text only. **Builder and plan reviewer must read it in full before touching those two steps' strings** (CLAUDE.md §5b), because the helper text describes HVAC behaviour.

### Code surveyed (read end-to-end)
config_flow.py:3514-3605 (options init), :3611-4195 (House steps), :8979-9034 (`default_notifications`), :9036-9956 (Zone Manager steps), :6041-6057 (HVAC submenu), :740-802 (mirror keys). en.json :556-833, :1636-1661. Consumer greps listed per row below.

### Producer / consumer check (per CLAUDE.md)
For a UI-only plan, the "value" is each stored option key. The **producer** is the options step that writes the key. Every key in the tables below has a consumer verdict from grep (`!config_flow.py,!const.py`). Dead and unwired rows are the producer-without-consumer cases.

---

## Inventory — Zone Manager options flow

Entry path: `async_step_init` jumps straight to `manage_zones` (:3532-3542). That is a one-tap menu of zones (:9036-9101), which opens `zone_config_menu` (:9158-9204) with 8 items.

| Step (file:line) | Field (schema line) | Consumer (grep) | Findings |
|---|---|---|---|
| `manage_zones` :9036 | (menu, dynamic) | — | en.json:614 description is 260+ chars and uses "RAW house zones", "merged HVAC label", "sibling(s)". **Nerd words / too long.** en.json:616-620 `data.zone_name` + helper are **dead strings**: the step became a menu in v5.100.4 and has no form fields |
| `zone_config_menu` :9158 | (menu) | — | Title "Zone Configuration" collides with the `zone_rooms` title (en.json:1637), so two screens share one name. Menu label "Dynamic Preset (Weather-Driven)" is jargon |
| `zone_rooms` :9210 | `zone_name` :9448 | many | OK |
| | `zone_description` :9454 | **none at runtime.** Written by config_flow and copied by migration `__init__.py:429,1020`; no reader | **DEAD (display-free).** Clutter |
| | `zone_is_outdoor` :9461 | safety.py:546-567, presence.py:1766-1778, aggregation.py:4629 | **No label or helper in en.json or strings.json** (grep: zero hits). The UI shows the raw key `zone_is_outdoor`. HIGH UX bug |
| | `zone_rooms` :9468 | hvac_zones.py:437, many | Helper "Rooms included in this zone" only repeats the label. Enumeration-vs-automation: OK |
| `zone_media` :9486 | `zone_player_entity` :9541 | music_following.py:1319+ | OK |
| | `zone_player_mode` :9547 | music_following.py:1333,1347 | Option labels are built in code (:9534-9538) rather than translated. Acceptable (same pattern as room). Helper "How to handle music when zone player unavailable" is vague |
| `zone_hvac` :9563 | `zone_thermostat` :9637 | hvac_zones.py:432 | Description en.json:648 says "(v4.5.11)" (**version tag in UI**). Mirror to siblings is not mentioned on the form; it only appears in the menu banner |
| | `hvac_ac_load_sensor` :9643 | hvac_zones.py:457,570,2727 | Label "AC Load Sensor (kW or kWh)": unit noise. Power-user field |
| | `hvac_ac_ramp_zone_enabled` :9652 | hvac_zones.py:458,573,2729 | Label "AC Ramp-Down enabled for this zone": jargon ("ramp-down"). Power-user |
| `zone_energy` :9663 | `zone_power_sensors` :9721 | **none.** Only an import at aggregation.py:109; `_get_zones_total_energy` (:3548-3575) reads ENERGY only | **DEAD / UNWIRED.** Still mirrored to siblings (:788). The user picks sensors and nothing happens |
| | `zone_energy_sensors` :9727 | aggregation.py:3565 | OK |
| `zone_persons` :9740 | `zone_persons` :9773 | hvac_zones.py:452 | OK. Helper mentions "geofence"; plainer wording possible |
| `zone_cameras` :9793 | `zone_cameras` :9824 | hvac_zones.py:453 | Selector is `binary_sensor` occupancy/motion (:9829-9831) but the label says "Cameras". Helper names vendors and entity ids ("Frigate person_occupancy"). The House `camera_census` step also picks cameras (`camera` domain), so there are **two camera pickers with different entity types**. Rename the label to "Person sensors near this zone" (operator decision O3) |
| `zone_dynamic_preset` :9844 | `zone_dynamic_preset_enabled`, `_offset`, `_reset_offset_guest`, `_sleep_enabled` (builder `_build_dynamic_preset_schema`, :10576-10581) | dynamic_preset.py:860,940 + others | Helper en.json:702 uses "DPM". Label "Enable sleep preset ranges" points at bucket cells that were UI-stripped in v4.7.18 (:9917-9923), so the user cannot see the "ranges" it mentions. `reset_offset_guest` and `sleep_enabled` are power-user |
| `zone_delete_confirm` :10173 | `confirm_zone_name` :10241 | — | Already plain-language. No change |

**Not on the zone form, but zone-scoped (cross-flow finding):** `zone_vacancy_sweep_enabled` is rendered on the **CM** HVAC tuning form (config_flow.py:6593-6594, writes CM options) and listed in `MIRROR_KEYS_ZONE_HVAC` (:782). Its only reader is `hvac_zones.py:451`, which reads the **Zone Manager zones dict** `zone_cfg` (default True). No zone form writes it into `zone_cfg`. Grep found no other reader, so the CM toggle "Vacancy Auto-Off" (en.json:1179) **looks unwired**: turning it off should have no effect. **(Plan review correction)** The live control already exists: switch `46 · Vacancy Auto-Off` (`switch.py:3905-3934`, unique_id `..._hvac_zone_sweep`) writes `zone.vacancy_sweep_enabled` on every zone in memory. So the CM form field is a dead DUPLICATE of a working switch with the same name, not a missing control. The card should decide remove-vs-redirect the form field, and check whether a zone rebuild from `zone_cfg` (`hvac_zones.py:451`, default True) overrides a switch set to off. This is a behavioural defect, so it is **out of scope for this UI plan**. It needs a card (proposed `HVAC-VACANCY-SWEEP-KNOB-UNWIRED-1`, Tier 2, adjacency sweep first). Before carding, confirm with a live read of the CM options value and the ZM `zones` dict (measure-before-build).

## Inventory — House (integration entry) options flow

Menu (:3518-3531): `global_sensors`, `energy_sensors`, `person_tracking`, `default_notifications`, `camera_census`, `perimeter_alerting`.

| Step (file:line) | Field (line) | Consumer | Findings |
|---|---|---|---|
| `global_sensors` :3611 | `outside_temp_sensor` :3621 | many | OK |
| | `outside_humidity_sensor` :3627 | aggregation.py:1086 | OK |
| | `weather_entity` :3633 | many | OK |
| | `outdoor_light_sensor` :3643 | lighting/darkness.py | OK (Slice B', already plain) |
| | `outdoor_dark_lux` :3657 | darkness.py | Tuning number → **Advanced** |
| | `solar_production_sensor` :3668 | aggregation.py:2868 | Belongs in Energy grouping (see D3; label-only, no move) |
| | `electricity_rate` :3674 (Required) | coordinator.py:1396, energy_billing.py:80 | Helper says it is a fallback only; tuning → **Advanced** (Required + Advanced works because it always has a default) |
| `energy_sensors` :3691 | `whole_house_power_sensors` :3709 | many | OK |
| | `whole_house_energy_sensors` :3716 | many | OK |
| | `house_device_power_sensors` :3723 | **none.** Import only, aggregation.py:107 | **DEAD / UNWIRED** |
| | `house_device_energy_sensors` :3729 | aggregation.py:3584 | OK |
| | — | — | en.json:733-756 still holds labels for 6 fields **removed in v4.2.0** (`solar_export_sensor`, `grid_import_sensor`, `_2`, `battery_level_sensor`, `delivery_rate`, `export_reimbursement_rate`). **Dead strings** |
| `person_tracking` :3781 | `tracked_persons` :3792 | person_coordinator.py, `__init__` | OK |
| | `person_data_retention_days` :3801 | **none** (grep: const + config_flow only) | **DEAD** |
| | `transition_detection_window` :3813 | **none** | **DEAD.** Also `description_placeholders` `retention_info` / `window_info` (:3830-3833) are not referenced by the description string |
| `default_notifications` :8979 | `notification_service` :9011, `notification_target` :9017, `notification_level` :9023 | aggregation.py:1413-1415, button.py:457 | **Duplicate surface** with CM `coordinator_notifications` (NM). Users cannot tell which one wins. Description should say what it is for: legacy room alerts plus room fallback. Operator decision O4 |
| `camera_census` :3836 | 15 flat fields :3871-4011 | all live (camera_census.py, `__init__`) | Flat wall of 15. **3 fields have no label or helper**: `known_face_guests` :3937, `egress_identity_failsafe_strict` :3957, `auto_enable_person_detection` :4004 (grep en.json: zero). Label "Enhanced Census (v2)" has a version tag. Helpers for `face_recognition_enabled` / `egress_identity_enabled` (en.json:809,815) are over 220 chars and name entity ids. `census_divergence_downgrade` helper is over 220 chars. Order mixes pickers and tuning (`census_hold_exterior` is last, separated from `census_hold_interior`) |
| `perimeter_alerting` :4029 | 9 fields :4054-4146 | perimeter_alert.py, perimeter_enrichment.py | **All 9 fields are unlabeled.** en.json:818-833 labels the 4 STRIPPED keys (`perimeter_alert_hours_*`, `perimeter_alert_notify_*`, which the save path removes at :4043-4049). The description still says "Send notifications ... during quiet hours", but the hours are now *vehicle* hours. **HIGH UX bug**: the user sees raw keys and wrong text |
| `domain_coordinators` :4167 | `domain_coordinators_enabled` :4186 | — | **Orphan step**: not in any menu since v3.6.0-c2.4 (:3529). Strings en.json:834-843 are dead. Keep the handler (three-bucket: KEEP+DOCUMENT; a removal is not needed for this card) |

**Reload hazard (card item):** of all House keys, only the census/perimeter subset in `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` (`__init__.py:7125-7193`) avoids a parent-entry reload. Saving `global_sensors`, `energy_sensors`, `person_tracking`, `default_notifications`, or a camera list reloads the whole integration. The memory `feedback_parent_entry_reload_watchdog_hazard` records about a 5-minute outage when this happens. The forms do not say so.

## Inventory — CM options flow (step level; field work deferred)

Menu (:3547-3577): 12 rows.

| Step (line) | Fields | Existing folds | Notes |
|---|---|---|---|
| `coordinator_presence` :4201 | 9 + 7 | `fan_recheck_advanced` :4391 | — |
| `coordinator_safety` :4492 | 8 | — | — |
| `coordinator_security` :7269 | 11 | — | — |
| `coordinator_energy` :4607 | ~87 | `INCLEMENT_ADVANCED_SECTION` :5242, `cloud_verification` :5824, `baec` :5945, `baec_advanced` :5968 | Largest surface. Labels such as "Battery Reserve SOC (%)" and "Arbitrage Grid-Charge Import Guard", plus helpers carrying "v4.5.0:" and README refs (en.json:944-1066) |
| `coordinator_hvac` :6041 (menu) → `coordinator_hvac_settings` :6059 | 31 + 5 + 1 | `presence_timing` :6636 | Holds the unwired `zone_vacancy_sweep_enabled` :6593 |
| `hvac_dynamic_preset` :6744 | 4 + 2 | `advanced` :6982 | Description uses "DPM" (en.json:1240) |
| `hvac_baseline_presets` :7009 | 3 season sections + reset | — | — |
| `coordinator_music_following` :7400 | 10 | — | — |
| `coordinator_appliance` :13121 / `appliance_form` :13163 | ~8 | — | — |
| `coordinator_notifications` :7565 → `_persons` :7679 → `_quiet` :7803 → `_cooldowns` :7866 | 15 / 12 / 6 / dynamic | — | A 4-page chained wizard. Persons/quiet/cooldowns are reachable only by paging through |
| `coordinator_notifications_volume` :7916 | 15 | — | Description en.json:1560 says "Rung-2 controls (NM Cycle A-2)". Labels "nm_a4_…" style keys |
| `coordinator_notifications_routing` :8287 | 5 + dynamic | — | Helper en.json:1607 is raw JSON schema prose |
| `signal_responses` :8639 | 7 | — | — |
| `coordinator_optimization` :8708 | 10 | `optimizer_guards` :8933, `optimizer_llm` :8936 | "LLM Tier-2 reasoning" (en.json:1422) |
| `coordinator_toggles` :8598 | 3 | — | **Orphan**: not in the menu (moved to switches in v3.6.0-c2.4). Strings dead |

Init menu-label block (en.json:561-610) is shared by House, CM and Room. It holds dead rows: `domain_coordinators` :569, `coordinator_toggles` :586, `options_lighting` :592, `manage_zones` :566 (no menu shows it now), and sub-step rows that are never init options. These are harmless but confuse the meta-test. Leave as-is and exclude them in the test (non-goal: no string-key deletions in the shared block this cycle).

---

## Classification rule (reused from ROOM-TYPE-TRIMMED-MENU-1 D7)

- **Simple**: entity pickers, on/off feature switches, anything most homes need.
- **Advanced**: pure tuning numbers and kill-switches whose default is right for most homes. Marked with `_adv(key, merged, DEFAULT_X)`. Shown only when Profile → Advanced mode is on, **or** when the stored value differs from the factory default (I2, so no stored value is ever unreachable).
- **Folded**: existing `section()` blocks, unchanged.
- **Factory default** = the `DEFAULT_*` constant the handler already passes to `_get_current(KEY, DEFAULT_*)`. Absent ⇒ default. A list or text field is "in use" if non-empty.
- **Save guard (I3)**: every House step saves with `{**options, **user_input}` (:3617, :3700, :3788, :3853, :8985), and every Zone step routes through `_auto_mirror_to_siblings` with `dict(user_input)` merged into `zone_cfg`. Omitted Advanced keys are therefore preserved, and no clear-on-omit logic exists. **Exception to verify:** `perimeter_alerting` pops 4 *retired* keys (:4043-4049). None of them is an Advanced key, so it is safe. The builder adds the I3 test anyway.

---

## Deliverables

### D1 — Zone label and helper pass (strings only)
Edit `strings.json` + `translations/en.json` for every zone step (`manage_zones`, `zone_config_menu`, `zone_rooms`, `zone_media`, `zone_hvac`, `zone_energy`, `zone_persons`, `zone_cameras`, `zone_dynamic_preset`):
- Add the missing `zone_is_outdoor` label + helper ("Outdoor zone" / "Turn on for patios, yards and pool areas. Safety uses outdoor limits and the house count ignores people here.").
- Shorten the `manage_zones` description to 220 characters or fewer, with no "RAW"/"canonical"/"merged". Delete the dead `manage_zones.data` / `data_description` blocks.
- Retitle `zone_rooms` to "Name and rooms" so it no longer duplicates the "Zone Configuration" menu title.
- Menu labels: "Dynamic Preset (Weather-Driven)" → "Weather comfort"; "Zone HVAC" → "Thermostat"; "Zone Cameras" → per O3.
- Remove "(v4.5.11)", "DPM", "ramp-down" jargon from labels. Helper (checked against HVAC state of play §6: nudge raises the cooling setpoint briefly; hard reset turns the AC off and on; needs the AC load sensor): "Briefly eases or restarts the AC when it keeps running after reaching the set temperature. Needs the AC load sensor."
- `zone_hvac` description gains one line: "Zones sharing this thermostat get the same settings."

**Acceptance**
- **Test:** `test_zone_house_dialog_strings.py::test_zone_field_has_clean_label_and_helper`, parametrised over `ZONE_OPTIONS_STEPS`. Every schema key AST-extracted from each zone step body (including `_build_dynamic_preset_schema` keys) has a label (not the raw key, no `_`) and a helper of 220 characters or fewer, in both files.
- **Test:** `test_zone_menu_options_labelled`: every `zone_config_menu` option has a label in both files.
- **Test:** `test_no_jargon_in_zone_house_strings`: banned tokens `["DPM", "RAW", "canonical", "hysteresis", "debounce", "provenance", "substrate", "failsafe", "tier", "(v"]` do not appear (case-sensitive where needed) in zone/house step titles, descriptions, labels or helpers. Mutation drill: re-insert "(v4.5.11)" → test fails.
- **Live:** open Zone Manager → any zone → Name and rooms. The outdoor toggle shows "Outdoor zone" (not `zone_is_outdoor`).

### D2 — Zone Simple/Advanced markers
Advanced (via `_adv`, default in parentheses): `hvac_ac_load_sensor` (empty), `hvac_ac_ramp_zone_enabled` (`DEFAULT_HVAC_AC_RAMP_ZONE_ENABLED`), `zone_dynamic_preset_reset_offset_guest` (True, per dynamic_preset.py:860), `zone_dynamic_preset_sleep_enabled` (False, :940), `zone_player_mode` (`ZONE_PLAYER_MODE_FALLBACK`).
Dead-field handling (O1): `zone_description` and `zone_power_sensors` are **hidden unless they hold a stored value** (same I2 rule; "factory default" = empty). Stored values are kept. No migration, no constant deletion (three-bucket: KEEP+DOCUMENT; add a one-line comment at const.py:67/:314).
Each zone form step with an Advanced key passes `description_placeholders["advanced_hint"]` and its description gains `{advanced_hint}`.

**Acceptance**
- **Test:** for each D2 key, Simple-mode render (show_advanced=False, default stored) excludes it; Advanced-mode render includes it.
- **Test (I2):** store a non-default value → Simple-mode render includes it. Covers both dead fields with a seeded value.
- **Test (I3):** submit each zone step in Simple mode without the hidden key → `zone_cfg` value unchanged, **and** the sibling zone (shared thermostat fixture) is also unchanged for mirrored keys. Mutation drill: change the step to write `user_input` over `zone_cfg` without merge → test fails.
- **Test:** the mirror set `MIRROR_KEYS_ZONE_HVAC` / `_ENERGY` / `_DPM` is byte-identical (no change to mirror semantics).
- **Live:** Profile Advanced mode OFF → zone Thermostat step shows only the thermostat picker plus the hint line. ON → all three fields.

### D3 — House label and helper pass (strings only)
- `perimeter_alerting`: replace the stale block with labels/helpers for the 9 real keys. Delete the 4 retired-key strings. New description: "Get alerts about vehicles on your outdoor cameras during these hours. Optional AI descriptions add detail."
- `camera_census`: add labels for the 3 unlabeled keys. Drop "(v2)". Cut the 3 long helpers to 220 characters or fewer, with no entity ids (name the switch in plain words: "You can also turn this off from its switch on the House device.").
- `energy_sensors`: delete the 6 dead strings from v4.2.0.
- `person_tracking`: remove the unused `description_placeholders` (:3830-3833). This is code, but it has no behavioural effect. **(Plan review)** The string key is `person_data_retention` but the schema key is `person_data_retention_days`, so this field ALSO shows its raw key today. Rename the string key to `person_data_retention_days` in both files (it must be labelled because I2 can reveal it).
- `global_sensors`: helper for `solar_production_sensor` says "Used for room energy estimates". It stays in this step (no key moves).
- Reload notice (card item): the descriptions of `global_sensors`, `energy_sensors`, `person_tracking`, `default_notifications` gain "Saving briefly restarts URA." The `camera_census` description gains "Some changes here briefly restart URA." **(Plan review)** Not only camera lists: `perimeter_cameras`, `egress_cameras`, `enhanced_census`, `census_divergence_downgrade`, `census_hold_interior`, `census_hold_exterior`, `auto_enable_person_detection` and `guest_vlan_ssid` are all outside the allowlist (`__init__.py:7125-7142`). Text only.

**Acceptance**
- **Test:** `test_house_field_has_clean_label_and_helper` over `HOUSE_OPTIONS_STEPS = [global_sensors, energy_sensors, person_tracking, default_notifications, camera_census, perimeter_alerting]`. Same assertions as D1.
- **Test:** `test_house_strings_have_no_orphan_field_labels`: every `data.<key>` in those 6 steps is a key the step's schema renders. Catches the stale perimeter/energy blocks. Mutation drill: restore `perimeter_alert_notify_service` string → fails.
- **Live:** House → Perimeter Alerting shows 9 readable labels, no raw keys.

### D4 — House Simple/Advanced markers
Advanced: `outdoor_dark_lux`, `electricity_rate`; `census_cross_validation`, `census_divergence_downgrade`, `enhanced_census`, `egress_identity_failsafe_strict`, `census_ble_cancel_enabled`, `auto_enable_person_detection`, `census_hold_interior`, `census_hold_exterior`; `perimeter_enrichment_provider`, `_model`, `_max_tokens`, `_provider_id`, `_person_sensors`, `exterior_snapshot_offset_s`.
Simple: all entity/camera pickers, `face_recognition_enabled`, `egress_identity_enabled`, `known_face_guests`, `guest_vlan_ssid`, `tracked_persons`, notification fields, vehicle hours, `perimeter_enrichment_enabled`.
Dead (O1): `house_device_power_sensors`, `person_data_retention_days`, `transition_detection_window` are hidden unless they hold a non-default stored value.
Reorder `camera_census` fields: pickers, then face/identity switches, then guest list/SSID, then Advanced tuning. **Order only.** Keys are unchanged.

**Acceptance**
- **Test:** D2 test pattern (exclude in Simple / include in Advanced / I2 forced / I3 preserved) for every D4 key.
- **Test (reload safety):** for `camera_census` and `perimeter_alerting`, a Simple-mode save that changes only one allowlisted key produces `changed_keys ⊆ INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` (drive `_async_update_listener`'s changed-keys computation with the pre/post options). This proves that hiding fields did not drag a non-allowlisted key into the diff. Seed the fixture WITHOUT the 4 retired `perimeter_alert_*` keys; add one case that seeds them and asserts the first save reloads (the pop at :4043-4049 puts them in `changed_keys`; pre-existing, accepted, one-time).
- **Test:** `camera_census` Simple render has 7 fields or fewer at default config (down from 15).
- **Live:** Advanced mode OFF → Camera Census shows the cameras, two switches, guest list and SSID only, plus the hint. A House with a non-default `census_hold_interior` still shows it.

### D5 — CM menu-level fixes (no field changes)
- Menu label rename for the CM init options: "Notification Volume & Noise Reduction" → "Alert noise", "Per-Person Routing & Hazard Overrides" → "Who gets which alerts". Others are kept.
- `coordinator_notifications_volume` description: remove "Rung-2 controls (NM Cycle A-2)" and "Fields left at defaults do not persist".
- `hvac_dynamic_preset` description: "DPM" → "Weather comfort".
- No field markers, no label pass on the ~260 CM fields (see Follow-on).

**Acceptance**
- **Test:** `test_cm_menu_options_labelled`: every CM init menu option has a label in both files, and labels contain no banned token.
- **Live:** CM Configure menu shows the renamed rows.

### D6 — Tests file
`quality/tests/test_zone_house_dialog_strings.py` (D1, D3, D5 string tests; it imports the AST extractor from `test_room_dialog_strings.py` or factors it into `quality/tests/_dialog_strings_helpers.py`) and `quality/tests/test_zone_house_advanced_fields.py` (D2, D4).

---

## Non-goals
- No CM per-field classification or label pass (Follow-on, per coordinator).
- No runtime behaviour change. **The unwired `zone_vacancy_sweep_enabled` is carded, not fixed here.**
- No constant deletions and no stored-data migration. Dead fields are hidden-unless-set.
- No moving keys between steps. No new `section()` groupings.
- No change to `MIRROR_KEYS_*`, to the reload allowlist, or to `_auto_mirror_to_siblings`.
- No removal of orphan handlers (`domain_coordinators`, `coordinator_toggles`) or of dead rows in the shared init menu-label block.
- No emoji policy change (room menu keeps emojis; zone/house stay consistent).

## Files touched
- `custom_components/universal_room_automation/config_flow.py`: `_adv` markers + `advanced_hint` placeholders in zone steps (:9210-9956, `_build_dynamic_preset_schema` ~:10576) and House steps (:3611-4165, :8979); `camera_census` field order; drop unused `person_tracking` placeholders.
- `custom_components/universal_room_automation/const.py`: comments only (:67, :159-160, :314, :316).
- `strings.json`, `translations/en.json`.
- `quality/tests/test_zone_house_dialog_strings.py`, `quality/tests/test_zone_house_advanced_fields.py` (new); optional shared helper module.

## Tier and review plan
- **Tier 2.** Options-flow UI only, two entry types, no runtime path. The precedent is ROOM-TYPE-TRIMMED-MENU-1 (Tier 2). This is not Tier 2-DB: no DAO, no payload, no shared runtime primitive. The two shared surfaces it touches are the reload allowlist and the zone mirror, and neither is modified; tests prove both stay inert.
- **Plan review:** one adversarial pass (Tier 2). The reviewer must re-run the dead-field greps (especially `zone_power_sensors`, `house_device_power_sensors`, `person_data_retention_days`, `transition_detection_window`, `zone_description`), re-run the label-presence greps, and read HVAC_ARCHITECTURE_STATE_OF_PLAY.md before signing off D1's `zone_hvac` / `zone_dynamic_preset` wording.
- **Build reviews (two, disjoint):** A = correctness + edge cases (I2 per key, factory defaults, legacy `ENTRY_TYPE_ZONE` path at :9230-9252, dead-field reveal, DPM builder). B = lifecycle + save paths (I3 including sibling mirror, reload-suppress changed-keys, Advanced mode toggled between opens, string parity, menu re-entry).
- **Deploy:** normal. The restart is held while the house sleeps (memory).

## Sequencing
1. ROOM-TYPE-TRIMMED-MENU-1 ships (provides `advanced_hint`, `_adv`).
2. D1 + D3 + D5 (strings only) can ship **before** step 1. They are independent and fix two HIGH raw-key bugs. Recommended as slice A.
3. D2 + D4 (markers) after step 1, as slice B.

## Operator decisions needed
- **O1 — Dead fields:** hide-unless-set (recommended; data-safe). **(Plan review)** `_adv` gives "Advanced-mode OR set", not "hidden unless set": dead fields still show in Advanced mode. Builder uses `_adv` (accepted) unless the operator wants them out of Advanced too, in which case omit them from the schema when unset; vs remove from the form outright vs leave visible. Applies to `zone_description`, `zone_power_sensors`, `house_device_power_sensors`, `person_data_retention_days`, `transition_detection_window`. (Wiring `zone_power_sensors` into a zone power total is a separate KEEP+WIRE option if you want it.)
- **O2 — Slice A first:** ship the string-only fixes (two raw-key HIGH bugs) ahead of the room trimmed-menu card? Recommended yes.
- **O3 — "Zone Cameras" label:** the picker takes person/motion *sensors*, not cameras. Rename to "Person sensors" (recommended), or switch the selector to `camera` like Camera Census. The second option is a behaviour change, so it would get its own card.
- **O4 — House "Default Notifications" vs CM Notifications:** keep both and clarify the House one as "Room alert fallback" (recommended), or plan a merge into NM (separate card).
- **O5 — Vacancy Auto-Off appears unwired:** approve carding `HVAC-VACANCY-SWEEP-KNOB-UNWIRED-1` (live-read first, then wire the CM knob into the HVAC zone build or move it to the zone Thermostat step).
- **O6 — CM follow-on order:** suggested Notifications (4-page wizard + volume + routing) → Presence/Safety/Security → Music/Appliance/Signals → Optimizer → HVAC → Energy last (largest, cost-impacting, Tier 2-DB).

## Follow-on (not this cycle)
Per-coordinator CM cleanup cycles, one card each, reusing D2's pattern. Energy and HVAC are Tier 2-DB (cost/comfort knobs; read the HVAC state-of-play doc first). Record as an adjacency note on HOUSE-DIALOGS-CLEANUP-1 rather than new cards until each is picked up.

---

## Plan review (Tier 2, one adversarial pass, 2026-10-02)

The reviewer read HVAC_ARCHITECTURE_STATE_OF_PLAY.md in full. D1's thermostat and weather-comfort wording is text only and does not contradict §4–§9 or the §10 ledger. The ramp helper was tightened against §6.

**Verified by re-grep (holds):**
- Five dead fields have no runtime reader. `zone_power_sensors` and `house_device_power_sensors` appear only as imports (aggregation.py:107/109). `zone_description` is only written by migration (`__init__.py:429,1020`). `person_data_retention_days` and `transition_detection_window` appear only in const and config_flow.
- Four keys have zero strings in either file: `zone_is_outdoor`, `known_face_guests`, `egress_identity_failsafe_strict`, `auto_enable_person_detection`.
- The perimeter strings hold only the 4 retired keys, and the 9 live keys are unlabelled.
- The 6 dead energy strings are present.
- The CM form field `zone_vacancy_sweep_enabled` (config_flow.py:6593) has no reader. hvac_zones.py:451 reads the ZM `zone_cfg` only.
- The reload allowlist is correct as cited. Saving `global_sensors`, `energy_sensors`, `person_tracking` or `default_notifications` reloads.
- I3 holds. Zone saves go through `zones[...].update(saved_zone_data)`, and the mirror payload carries only keys that are present (config_flow.py ~3405-3437). House saves use `{**options, **user_input}`.
- The precondition exists on `feature/room-trimmed-menu`: `advanced_hint` at :62 and `_adv` at :99.

**Findings (all fixed in the plan above):**
1. MEDIUM: `person_tracking` shows a raw key. The string key is `person_data_retention`, but the schema key is `person_data_retention_days`. Added to D3.
2. MEDIUM: the reload notice in D3 was wrong. Eight more `camera_census` keys outside the camera lists also cause a reload. The wording now says "Some changes here...".
3. MEDIUM: D4 reload test. If an entry still holds the 4 retired perimeter keys, the pop puts them in `changed_keys`, so the first save reloads. The fixture rule and the extra case are added to the plan.
4. MEDIUM: the vacancy-sweep premise needed correcting. A working switch `46 · Vacancy Auto-Off` (switch.py:3905-3934) already exists. The CM form field is a dead duplicate with the same name, not a missing control. The card scope in the inventory note is corrected.
5. LOW: O1 semantics. `_adv` still shows dead fields in Advanced mode. This is now stated in O1.
6. LOW (accepted, no plan change): a Simple-mode zone save no longer re-mirrors hidden keys to sibling zones, so a save no longer heals sibling drift. Mirror semantics are unchanged. Reviewer B should note it.

**Verdict: BUILD-READY.** Slice A (D1/D3/D5) can be built now. Slice B (D2/D4) waits for `feature/room-trimmed-menu` to merge.
