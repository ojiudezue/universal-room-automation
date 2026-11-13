# Person sightings Phase 1 — Review C (test authority via real per-site source mutation)

Branch `feature/person-sightings-p1`, HEAD abbc765c, base 3348d379. Framing C only. 92 production sites neutered ONE at
a time (harness: Python mutate, run, restore in `finally`; `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`,
`__pycache__` removed before every run; run over ALL 31 cycle test files, `-x`). `git status --short` clean after every
batch. Baseline: 393 passed / 44 skipped (the skips are the opt-in D7-hygiene subprocess anchors).

Opt-in gates over the cycle files: `URA_SOURCE_MUTATION=1 -m source_mutation` -> 26 passed, 2 skipped (probe-only helper
tests); `URA_D7_HYGIENE=1` full cycle set -> 436 passed, 1 skipped. Both green.

## Site x test x RED-on-neuter (RED rows; first failing test named)

| Site neutered | RED test |
|---|---|
| classifier fail-closed tail -> False | test_face_access_invariant::test_unknown_arrival_source_requires_corroboration[camera_vision] |
| classifier non-string guard | test_person_sighting_review_a::test_a6_unhashable_source_fails_closed |
| classifier camera set -> False | test_face_access_invariant::test_camera_egress_requires_corroboration |
| lock regime gate disabled / literal-camera_face-only | test_face_access_invariant::...[camera_vision] |
| security gate classifier -> False | same |
| security regime None accepted | test_face_sighting_realhass::test_sources_to_consumers_end_to_end[False] |
| security at_ts forced None / face_input_corroborated ignores at_ts | test_face_access_invariant::test_no_sighting_payload_uses_now |
| face_input_corroborated torn-down guard | test_sc_lock_person_sighting::test_face_input_corroborated_matches_private |
| FACE_ARRIVAL_INTERIOR_ENABLED check | test_face_arrival_rule::test_kill_switch_noop |
| D2 observation_mode / boot / home / unknown / phone-edge gap / debounce / egress role | test_face_arrival_rule (7 distinct named tests: observation_mode_suppresses_arrival, boot_window_suppresses_arrival, home_resident_no_arrival, unknown_state_fails_closed, phone_already_home_skip, arrival_debounce_per_person, egress_never_arrival) |
| D2 source literal / payload sighting | test_face_arrival_rule::test_d2_dispatch_carries_camera_face_source |
| `_last_home_edge_ts` writer | test_face_arrival_rule::test_last_home_edge_written_by_real_person_listener |
| recog switch gate (emit / tracker fields / trip-wire) and `_face_recognition_on` default | test_person_sighting_review_a::test_a2_* (4 tests) |
| denominator boot cutoff (A1) | test_person_sighting_review_a::test_a1_restart_boot_window_faces_do_not_page |
| denominator suppressed skip / tracked filter | test_face_sighting_tripwire::test_suppressed_faces_silent / test_unmapped_only_faces_silent |
| suppression gate in emit | test_face_sighting_tripwire::test_suppressed_faces_silent |
| emit boot drop | test_person_sighting::test_boot_restore_not_a_sighting |
| bridge callback register / teardown remove / census call / ring append | test_face_sighting_realhass::test_sources_to_consumers_end_to_end[True]; test_person_sighting::test_teardown_unsubscribes_all; test_face_sighting_tripwire::test_zero_with_faces_pages |
| restore/unavailable drop, attr-only update, egress non-face skip | test_face_sighting_realhass...; test_a3_attribute_only_update_is_not_a_sighting; test_person_sighting::test_egress_ble_provenance_silent |
| egress outcome log: write call, persist kill switch, tracked-task set | test_egress_direction_aware::test_switch_off_golden_replay (see M1 note) |
| egress outcome log: torn-down guard | test_egress_outcome_log::test_no_row_after_teardown |
| bus identity_provenance key, attach stash provenance, resolution provenance | test_egress_direction_aware::test_switch_off_golden_replay (see M1 note) |
| writer-health registration | test_egress_outcome_log::test_registered_for_writer_health_unless_persist_off |
| B-L4 absence call site / prior-row conjunct | test_memory_writer_health::test_bl4_house_absent_whole_window_suppresses_egress_page[rows0]; test_zero_row_writer_backed_type_fires_anomaly |
| path-map loader: reject -> install | test_exterior_seam_loader::test_setup_invalid_file_rejected_wholesale_keeps_const |
| path-map: later reject keeps previous / sha only for installed / load lock / validate raise whole file | test_interior_paths::test_four_load_outcomes; ::test_file_wins_over_const; test_person_sighting_review_b::test_bl3_path_map_loads_are_serialised; test_four_load_outcomes |
| path-map STARTED listener / registry listener / reload button call | test_interior_paths::test_cold_boot_valid_file_loads_after_ha_started; ::test_registry_update_upgrades_const_to_file; ::test_reload_button_swaps_map |
| validator rules 2, 3, 4, 5, 10 | test_interior_paths (sha_names_installed_source, four_load_outcomes, frigate_and_protect_legs_one_node, cycle_rejected, detached_door_inward_to_house_rejected) |
| rebind on room lifecycle | test_person_sighting_review_b::test_bm1_room_cameras_edit_rebinds_via_lifecycle_signal |
| B-L1 setup guard, B-L2 flag callback | test_bl1_sighting_setup_failure_keeps_later_subscriptions; test_bl2_face_recognition_flip_applies_on_the_loop |
| sighting debounce / store write / arrival_rule call / dispatch / HVAC + tracker counters / egress listener / setup kill switch / on_tick / teardown | test_identity_fusion_d2_d3_d4::test_fs4_...; test_face_arrival_rule (kill_switch_noop, hvac_counter_matches_compound_zone, egress_never_arrival); test_person_sighting (kill_switch_noop, presence_async_setup_builds_producer); test_face_sighting_tripwire::test_zero_with_faces_pages |
| trip-wire MIN_FACES compare / latch / fire / re-arm | test_face_sighting_tripwire (zero_without_faces_silent, zero_with_faces_pages, rearm_after_recovery) |
| egress sighting synthetic flag copied | test_person_sighting::test_egress_provenance_copied_not_recomputed |
| `test_face_sighting_realhass` bridge-callback not registered (plan §9A step 5 D6 ask) | RED: realhass::test_sources_to_consumers_end_to_end[True] when callback registration is neutered |

## Findings: sites that stayed GREEN (untested)

| # | Sev | Class | Site | Neutered -> GREEN | Failure scenario |
|---|---|---|---|---|---|
| C-M1 | LOW (resolved in-pass) | #62 aggregate anchor | `_log_egress_outcome` call / persist switch / task set / bus `identity_provenance` / resolution provenance | Re-run against the dedicated files only: write call and task set -> RED `test_every_resolution_persists_one_row_switch_off`, `test_two_crossings_both_persist`; kill switch -> RED `test_persist_kill_switch`; bus key -> RED `test_resolution_carries_provenance`, `test_bus_event_carries_identity_provenance`; resolution provenance -> RED `test_face_only_real_path_provenance_face`. | Cleared: dedicated anchors hold. |
| C-M5 | MEDIUM | #62 / INV-PROVENANCE | `transit_validator.py:2082` `census._egress_identity_last_attach["provenance"] = IDENTITY_PROVENANCE_FACE` -> BLE | GREEN on both egress test files (RED only on the coarse `test_switch_off_golden_replay`) | The explicit stash value read by `:2080-2092` readers / census union has no dedicated test; a face-only attach mis-tagged `ble` would let face names bypass the face-producer-outage gate. Add a test asserting the stash on the real face-only path. |
| C-M2 | MEDIUM | #63 numerator/denominator scope split | `person_sighting.py:761` numerator `sum(t >= now - window_s)` -> `len(self._interior_emits)` | GREEN | A sighting from 2 days ago (ring holds 2000) keeps `numerator > 0`, so the HIGH `face_sighting_zero` page is suppressed while the producer is dead now. Trip-wire blindness. Needs a test: sightings only older than the window + enough faces -> pages. |
| C-M3 | MEDIUM | #63 same | `person_sighting.py:722` denominator window bound `now - window_s` -> 0 | GREEN | Faces older than 24 h (ring max 2000, only the boot floor otherwise) count toward `FACE_SIGHTING_ZERO_MIN_FACES`; false HIGH page when yesterday had 10 faces and the last 24 h has none and zero sightings. Needs a stale-faces-silent test. |
| C-M4 | MEDIUM | Fixture authority (class: hand-copied DDL) | `quality/tests/test_memory_writer_health.py:269` | n/a (confirms builder's note) | `house_state_log` DDL is hand-typed, though `conftest_db._extract_create_table_statements` / `real_schema_db` extract from production `database.py:1526`. A column rename in `database.py` keeps the test green while the real query breaks. Fix: build the table from the production source (add `house_state_log` to the conftest `_TABLES` subset) or extract the statement with the same helper. No other new test file has `CREATE TABLE`. |
| C-L1 | LOW | Untested wire | `presence.py:5578`ff `producer.note_arrival(sighting.ts)` (neutered) | GREEN | `_last_arrival_ts` never set -> `face_arrival_zero` LOW trip-wire anchor is wrong (since = setup_ts). Dormant while `FACE_ARRIVAL_INTERIOR_ENABLED` is False. Add a test that an emitted arrival updates `_last_arrival_ts`. |
| C-L2 | LOW | Untested wire | presence midnight `self._person_sightings.reset_daily()` | GREEN | Today-counters (`face_sightings_today`, by-source, arrivals) never reset: diagnostics lie after day one. |
| C-L3 | LOW | Untested | `person_sighting.py:473-476` egress sighting `ts` from the event `timestamp` (neuter -> `self._now()`) | GREEN | Crossing time is replaced by processing time. Skews the boot-window drop and the `at_ts` the security gate hands to `face_input_corroborated`. Needs a test with an event timestamp offset from now. |
| C-L4 | LOW | Untested | `transit_validator.py:2377` `_on_registry_updated_path_map` guard `self._path_map_from_file` | GREEN | Once the file is installed, registry events should do nothing (button reloads). Without the guard a registry edit silently re-reads the file. No test asserts "no reload while file installed". |
| C-L5 | LOW | Untested | `interior_paths.py:131` rule 8 range `0 < lag <= buffer_s` | GREEN (bool/type check survives) | `lag_p90_s: 9999` or `-1` passes. Test only covers bool (A8). |
| C-L6 | LOW | Untested counter | `person_sighting.py` `_SENTINELS` drop | GREEN | Sentinel names (`unknown`) fall through to `unmapped_names`; behaviour same, only the counter label differs. Only the diagnostics counter changes. |
| C-L7 | LOW | Equivalent mutant | `const.py:3430` drop `camera_egress` from `CAMERA_DERIVED_ARRIVAL_SOURCES` | GREEN | Classifier fails closed for any non-listed source, so the set is documentation. Not a leak. A drift test (`camera_egress in set`) would pin the named set. |
| C-L8 | NIT | Equivalent mutant | `transit_validator.py:2565` `dedup_source_ref=False -> True` | GREEN | `source_ref` is per crossing (camera@ts), so the existence check only skips an exact re-log of the same crossing. No INV-LOG breach shown. |

## Invariant checklist (test authority)

- INV-ACCESS: every gate site (classifier x3 branches, lock regime, security gate x3, public wrapper x2) has a named RED test. HOLDS.
- INV-NOOP / kill switch: RED. INV-LOG: persistence sites RED on dedicated tests (C-M1 cleared); last-attach provenance stamp unanchored (C-M5). Trip-wire numerator/denominator window: NOT anchored (C-M2, C-M3).
- Restored after every run; `git status` clean. No source edits committed.

## Verdict: FIX-REQUIRED

Must-fix before ship: **C-M2 and C-M3** (trip-wire window tests: a window-bound regression silently blinds or false-pages the HIGH NM page); **C-M4** (fixture schema from production); **C-M5** (dedicated test for the `_egress_identity_last_attach` provenance stamp). LOWs C-L1..L5 should get one-line tests in the same fix-up (cheap, 1-3 assertions each); C-L6..L8 at builder discretion.

## Fix-up round 3 (test authority) — tests only, no production change

Each site mutated in source (one at a time, Python mutate/run/restore in `finally`, `PYTHONDONTWRITEBYTECODE=1`,
`-p no:cacheprovider`, `__pycache__` cleared before every run); `git status` clean of production files afterwards.
No test exposed a production bug.

| Finding | Site mutated | Mutation | New test (RED on mutation) |
|---|---|---|---|
| C-M2 | `person_sighting.py:761` numerator | `sum(t >= now - window_s)` -> `len(_interior_emits)` | test_face_sighting_tripwire::test_old_sighting_outside_window_does_not_suppress_page |
| C-M3 | `person_sighting.py:722` denominator cutoff | `now - window_s` -> `0.0` | test_face_sighting_tripwire::test_faces_older_than_window_silent |
| C-M4 | `test_memory_writer_health.py` `_house` now builds on `conftest_db.real_schema_db` (production-extracted); hand DDL removed | `database.py:1529` column `state` -> `house_state` | test_memory_writer_health::test_bl4_* (all 9 rows; drill ran test_bl4_absence_never_suppresses_other_writers) |
| C-M5 | `transit_validator.py:2082` last-attach stash | `IDENTITY_PROVENANCE_FACE` -> `IDENTITY_PROVENANCE_BLE` | test_transit_validator_provenance::test_face_only_attach_stash_provenance_face |
| C-L1 | `presence.py:5602` `producer.note_arrival(...)` | call -> `pass` | test_face_arrival_rule::test_emitted_arrival_notes_producer |
| C-L2 | `presence.py:8745` `reset_daily()` | call -> `pass` | test_face_sighting_tripwire::test_midnight_reset_clears_today_counters |
| C-L3 | `person_sighting.py:466` egress ts | `parsed.timestamp()` -> `self._now()` | test_person_sighting::test_egress_sighting_ts_is_crossing_time |
| C-L4 | `transit_validator.py:2377` guard | drop `self._path_map_from_file` | test_interior_paths::test_registry_update_ignored_while_file_installed |
| C-L5 | `interior_paths.py:131` rule 8 range | drop `not 0 < lag <= buffer_s` | test_interior_paths::test_rule8_lag_out_of_range_rejected[9999,-1,0] (3 RED) |

C-L6..L8 not addressed (builder discretion per verdict; equivalent/counter-label mutants). Cycle files green (135 passed,
reverse file order also green).
