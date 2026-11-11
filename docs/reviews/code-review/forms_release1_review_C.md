# FORMS-RELEASE-1 Review C: test authority via per-site source mutation

Branch feature/forms-release-1, head 5c77b417. Drills ran in a separate worktree (removed after). Each drill edits ONE site, clears `__pycache__`, runs `test_forms_release1.py`, `test_form_text_release1.py`, `test_presence_geofence_late_person.py` (baseline 217 passed), then restores. Tree clean after every drill.

## Verdict: FIX-REQUIRED (2 MEDIUM test-authority gaps; no production defect found)

## Drill table

| # | Site (config_flow.py unless noted) | Mutation | Result | Test that went RED |
|---|---|---|---|---|
| 1 | global_sensors :4627 (Options) | flatten removed | RED | test_forms_round_trip_options[global_sensors] |
| 2 | integration_config :1564 (create) | flatten removed | RED | test_forms_round_trip_create_integration_config |
| 3 | `_absent_field_defaults` :112 | no recursion into section defaults | RED | test_absent_field_defaults_unexpanded_section |
| 4a | global_sensors :4631 | `{**options, **flat}` -> `flat` | RED | round_trip_options[global_sensors] |
| 4b | energy_sensors :4719 | merge -> `flat` | **GREEN** | none (F1) |
| 4c | devices :13543 | merge -> `flat` | RED | round_trip_options[devices] |
| 4d | person_tracking :4812, camera_census :4959, perimeter :5212, lighting :13884, covers :14138, climate :14359 | merge dropped | RED each | round_trip_options[<step>] |
| 4e | sensors :13037 | `{**options, **user_input}` -> `user_input` | **GREEN** | none (F1) |
| 5 | all 16 `_flatten_sections` call sites (1564, 4627, 4718, 4809, 4921, 5210, 10981, 11260, 11364, 11484, 11729, 12672, 13540, 13837, 14135, 14271), one at a time | flatten neutered | RED x16 | round_trip_options[<step>] / edit_propagates (zone_rooms, zone_dynamic_preset mirror) |
| 6 | zone_rooms :10981 / zone DPM :11729 | flatten removed | RED | test_forms_edit_propagates_options[zone_rooms-zone_description], [zone_dynamic_preset-...] |
| 7 | sensors caps seed :12676 | seed disabled | RED | test_options_sensors_omitted_section_keeps_capabilities |
| 8 | lighting guard :13893 | `if ADVANCED_SECTION in _present` -> `if True` | RED | test_options_lighting_omitted_section_keeps_clearables |
| 9 | climate_backstop `_backstop_present` :14311 | clear always | RED | test_climate_backstop_omitted_keeps_hvac_holds |
| 10 | climate cap `_effective` | validate sent keys only | RED | test_climate_cap_checked_against_stored_max_when_section_unsent |
| 11a | notify fallback | overwrite entered service | RED | test_integration_config_notify_explicit_service_kept |
| 11b | notify fallback | removed | RED | test_integration_config_notify_fallback_blank_service |
| 12 | energy step skip restored (`user_input={}`) | skip | RED | test_forms_round_trip_create_integration_config (note: test_integration_config_energy_step_always_shown did not fire first under -x; the round-trip caught it) |
| 13 | presence.py old_state None guard | guard removed | RED | test_person_added_home_with_prior_tracker_is_not_an_arrival |
| 14a | presence.py `_handle_person_added` | no-op | RED | test_person_added_after_setup_is_tracked |
| 14b | presence.py added-domain listener | not registered | RED | test_person_added_after_setup_is_tracked |
| 15 | strings label moved key copied back into step `data` (strings.json + en.json) | copy | RED | test_section_strings_moved_not_copied[options-global_sensors-strings.json] |
| 16 | helper text copied back into `data_description` | copy | RED | same test |
| 17 | old claims C11, P6, P3 restored | text revert | RED each | test_wrong_claims_are_gone[strings.json] |
| N/A | "drop reader controller gate", `visible` eq->not_eq, `{**options}` added to a replace step | release 2 (`visible` pairs, replace carry-forward) | not applicable to release 1 | n/a |

## Findings

**F1 MEDIUM (Bug Class #62, hollow anchor): energy_sensors (:4719) and sensors (:13037) merge are unanchored.** Replacing `{**self._config_entry.options, **flat}` with `flat` (or `**user_input` alone) leaves the suite GREEN. Reason: `_seed(step)` (test_forms_release1.py:~188) builds the stored options by saving from an empty base, so the stored dict holds only that step's own form keys, and for these two steps the omitted section yields no defaults. No unrelated stored key (e.g. `lights`, other steps' options) is seeded, so the "stored options survive a save" invariant is never exercised there. Real effect if the merge regressed: saving Energy Sensors or Sensors silently wipes every other room/integration option. Fix: seed one unrelated stored key (and one stored advanced-section key such as `house_device_power_sensors`) in `_save`/`_seed` for all steps, assert it survives with the section sent and omitted.

**F2 LOW: energy-step-always-shown not first-RED.** Under `-x`, drill 12 failed in the create round-trip; confirm test_integration_config_energy_step_always_shown also goes RED (run without -x). Not verified by me.

## Notes
- Drills used `-x`, so each row names the first failing test; multiple tests may fail per row.
- Worktree removed; main tree untouched.
