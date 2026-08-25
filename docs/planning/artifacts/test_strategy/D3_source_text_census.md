# D3 — Source-text test census (Bug Class #62 population)

Method: AST walk of all 429 files under `quality/tests/`. A test is counted when it (or a module-level
constant / fixture / helper it references) obtains PRODUCTION SOURCE TEXT via `.read_text()`,
`open(...).read()`, `inspect.getsource()` or `inspect.signature()`. "STRONG" additionally requires that
an `assert` inside the test actually references that source text — i.e. the assertion is on the text,
not merely near it.

## Counts (finite numbers, as the plan requires)

| quantity | count |
|---|---|
| tests that touch source-reading machinery at all | 1098 |
| **STRONG source-text tests** (an assert binds to source text) | **341** |
| files containing at least one STRONG source-text test | 82 |
| STRONG tests asserting ABSENCE (`'x' not in src`) | 54 |
| STRONG tests asserting a literal NUMBER | 8 |
| tests using `inspect.signature` as the assertion | 5 |
| total tests in the suite (from the full-suite capture) | 9,403 passed + 158 failing ≈ 9,561 |
| STRONG source-text tests as a share of the suite | **3.6%** |

## The plan's discriminator

The plan said: *"if C2+C3+C4 sum is comparable to C1 (≥25% of the total), the class is systemic ... If C1
dominates (>90%), source-text tests are mostly legitimate."*

**Measured answer: C1 dominates.** Of the 341 STRONG source-text tests, only **13 appear in the 158**
baseline failing set (the `B2/C-62` rows in D1: `test_fan_trust_state_extension` ×3,
`test_low_cleanup` ×1, `test_v472_dpm_surfaces` ×1, `test_v475_d3_canonical_runtime_only` ×1,
`test_v4_7_17_2_dpm_simplified_frame` ×1, plus source-anchored asserts inside
`test_evse_drain_precedence_session_b1`, `test_energy_write_verification`, `test_exterior_cycle2` and
`test_deploy_scripts`). **That is a 3.8% failure rate for the class — 96% of source-text tests are
currently green.** Source-text testing is not what is producing the 158.

This is a direct contradiction of the intuition the cycle was launched on. Bug Class #62 is real and its
individual failures are expensive to debug, but as a *noise source* it is the smallest of the four
candidates, by an order of magnitude.

## The three operator-named instances — all THREE are already remediated

The plan's acceptance criterion requires these three to appear with classifications C4/C2/C3. They do
appear, but every one already carries an in-tree fix dated 2026-08-22 or 2026-08-23:

| instance | file:line | class | current state |
|---|---|---|---|
| `test_retention_uses_batched_delete` | `quality/tests/test_v4511_ac_energy_aware_ramp_down.py:243` | **C4** indirection victim | **FIXED 2026-08-22.** Re-anchored from a bare name scan onto `find("async def cleanup_ac_ramp_events")`. Its own docstring names the cause: *"an unrelated comment mentioning the name (e.g. the F5 fix-up migration comment at database.py:7576) cannot poison the scan. Source-text tests are Bug Class #62 — structurally re-anchored here."* Not in the 158. |
| `test_no_triggered_by_parameter_added` | superseded; tombstone comment at `quality/tests/test_ac_ramp_pipeline_hardening.py:1424` | **C2** policy-encoded-as-test | **REPLACED.** The v4.7.9 guard was flipped to assert the parameter IS present, and a behavioural bind (`TestA2ForceResetTriggeredByManual::test_force_ac_reset_writes_manual_on_started_row`) drives `force_ac_reset` and asserts the ledger row carries `'manual'`. Textbook C2→behavioural conversion. Not in the 158. |
| `test_settle_delay_constant_declared_as_module_const` | `quality/tests/test_hvac_excursion_d1_observability.py:480` | **C3** value over-specified | **FIXED 2026-08-23.** Comment in place: *"this assertion originally hard-coded the literal value 12, which conflated the RUNG with the VALUE. v5.89.0 changed the value 12 → 180 through exactly the reviewed-code-change path this test exists to require, and the test failed anyway. Assert the DECLARATION SHAPE, not the value."* Now `re.search(r"^AC_NUDGE_RESTORE_SETTLE_DELAY_S:\s*Final\s*=\s*\d+")`. Not in the 158. |

The three founding exhibits are the *strongest possible* evidence that the class is real — and they are
also all already paid down. The remaining 341-member population is 96% green.

## Top files by STRONG source-text test count

| file | STRONG count |
|---|---|
| `quality/tests/test_v463_anomaly_migration.py` | 30 |
| `quality/tests/test_v4715_universalize_veto.py` | 28 |
| `quality/tests/test_v4_6_11_dashboard_attrs.py` | 15 |
| `quality/tests/test_v465_observability_gap.py` | 12 |
| `quality/tests/test_v4714_1_forgotten_phone_hotfix.py` | 11 |
| `quality/tests/test_v5_7_1_energy_precool.py` | 11 |
| `quality/tests/test_v4622_guest_mode_hardening.py` | 10 |
| `quality/tests/test_evse_solar_aware_ux.py` | 9 |
| `quality/tests/test_fan_recheck_deferred_surfaces.py` | 9 |
| `quality/tests/test_v570_fixup_wiring.py` | 9 |
| `quality/tests/test_v462_regime_detector_dispatches_signals.py` | 8 |
| `quality/tests/test_energy_write_verification.py` | 7 |
| `quality/tests/test_setup_unload_symmetry.py` | 7 |
| `quality/tests/test_v4_6_12_aggregator_sensors.py` | 7 |
| `quality/tests/test_boot_settle_gate.py` | 6 |
| `quality/tests/test_evse_drain_precedence_session_b1.py` | 6 |
| `quality/tests/test_fan_recheck_mode2_cycle.py` | 6 |
| `quality/tests/test_v461_db_migration.py` | 6 |
| `quality/tests/test_v4714_away_state_person_tracker_trust.py` | 6 |
| `quality/tests/test_v4_6_9_next_state_sensor.py` | 6 |
| `quality/tests/test_v570_guest_detection_trust.py` | 6 |
| `quality/tests/test_db_incremental_vacuum.py` | 5 |
| `quality/tests/test_pathalpha_d2c_d3_observability.py` | 5 |
| `quality/tests/test_prediction_sensor_kill_list.py` | 5 |
| `quality/tests/test_v4_6_11_d3_persistence_and_dispatch.py` | 5 |
| `quality/tests/test_v4_6_13_coordinator_telemetry.py` | 5 |
| `quality/tests/test_blind_window_evse_guard.py` | 4 |
| `quality/tests/test_ledger_golden_replay_preserve.py` | 4 |
| `quality/tests/test_v4_6_9_energy_recent_decisions.py` | 4 |
| `quality/tests/test_baec_config_flow_round_trip.py` | 3 |

## Full STRONG census

| test | asserts absence | asserts literal number |
|---|---|---|
| `quality/tests/perimeter/test_circling_diag_sensor.py:370::test_diag_sensor_source_wires_the_poll_pattern` |  |  |
| `quality/tests/test_baec_config_flow_round_trip.py:199::test_setter_dispatch_routes_every_baec_key_to_coord` |  |  |
| `quality/tests/test_baec_config_flow_round_trip.py:309::test_d2_setter_dispatch_registrations_and_setters_exist` |  |  |
| `quality/tests/test_baec_config_flow_round_trip.py:487::test_cm_menu_does_not_reference_coordinator_baec` | yes |  |
| `quality/tests/test_blind_window_evse_guard.py:1446::test_D_HIGH_2_liveness_helper_semantics_pressure_overrides_envelope` |  |  |
| `quality/tests/test_blind_window_evse_guard.py:1698::test_A_HIGH_1_cleanup_decision_log_wired_into_nightly_cadence` |  | yes |
| `quality/tests/test_blind_window_evse_guard.py:2114::test_EC_manual_row_2_5_documents_final_semantics` |  |  |
| `quality/tests/test_blind_window_evse_guard.py:2306::test_D_MED_1_scope_limitation_documented_in_iterator_docstring` |  |  |
| `quality/tests/test_boot_settle_gate.py:273::test_no_new_conf_field_added` | yes |  |
| `quality/tests/test_boot_settle_gate.py:306::test_dispatch_suppression_branch_present` |  |  |
| `quality/tests/test_boot_settle_gate.py:410::test_hvac_boot_settle_fields_present` |  |  |
| `quality/tests/test_boot_settle_gate.py:428::test_hvac_release_helpers_present` |  |  |
| `quality/tests/test_boot_settle_gate.py:500::test_presence_house_state_sensor_exposes_attrs` |  |  |
| `quality/tests/test_boot_settle_gate.py:508::test_attrs_reference_private_fields` |  |  |
| `quality/tests/test_camera_resolver.py:554::test_grep_guardrail_no_switch_actuation_in_resolver_or_dry_run` | yes |  |
| `quality/tests/test_camera_resolver.py:776::test_conf_room_cameras_key_is_distinct_from_migration_target` | yes |  |
| `quality/tests/test_chatter_wire_in.py:358::test_drill_11_same_value_dedup_wire` |  |  |
| `quality/tests/test_cm_reload_suppression.py:60::test_options_reload_suppress_keys_exists_and_is_frozenset` |  |  |
| `quality/tests/test_cm_reload_suppression.py:828::test_d5_save_path_uses_combined_key_when_two_violations` |  |  |
| `quality/tests/test_cm_reload_suppression.py:864::test_d5_strings_and_translations_combined_key_in_lockstep` |  |  |
| `quality/tests/test_d3_area_inherit.py:48::test_source_anchor_uses_async_update_device_not_suggested_area` | yes |  |
| `quality/tests/test_db_incremental_vacuum.py:566::test_button_class_exists` |  |  |
| `quality/tests/test_db_incremental_vacuum.py:569::test_button_registered_in_cm_setup` |  |  |
| `quality/tests/test_db_incremental_vacuum.py:608::test_incremental_vacuum_in_nightly_ops` |  |  |
| `quality/tests/test_db_incremental_vacuum.py:633::test_supervised_vacuum_not_in_nightly_schedule` | yes |  |
| `quality/tests/test_db_incremental_vacuum.py:644::test_nightly_loop_budget_respected` |  |  |
| `quality/tests/test_deploy_scripts.py:244::test_v4710_gitea_only_flag_skips_origin_push` | yes | yes |
| `quality/tests/test_deploy_scripts.py:591::test_v4710_dualpush_timeout_kills_indefinite_hang` |  |  |
| `quality/tests/test_dp_yields_to_excess_solar.py:961::test_MUTATION_M4_remove_orphan_floor_clear_makes_AHIGH1_red` |  |  |
| `quality/tests/test_dpm_cleanup_and_labels.py:274::test_config_flow_module_parses` |  |  |
| `quality/tests/test_energy_projector_grep_singleton.py:183::test_all_coordinators_have_no_inline_projection` |  |  |
| `quality/tests/test_energy_projector_grep_singleton.py:201::test_projector_module_owns_the_expression` |  |  |
| `quality/tests/test_energy_projector_grep_singleton.py:210::test_energy_battery_exempt_marker_count_pinned` |  |  |
| `quality/tests/test_energy_savings_unification.py:476::test_predicted_bill_attrs_include_peak_avoidance` |  |  |
| `quality/tests/test_energy_write_verification.py:389::test_verifier_never_calls_service` | yes |  |
| `quality/tests/test_energy_write_verification.py:1499::test_c_high_1_a_lkg_blip_latch_real_source_mutation_role` |  |  |
| `quality/tests/test_energy_write_verification.py:1525::test_c_high_1_b_adopt_cfg_read_and_attain_cfg_observed_real_source` |  |  |
| `quality/tests/test_energy_write_verification.py:1554::test_c_high_1_c_dispatch_tap_and_evse_reserve_match_real_source` |  |  |
| `quality/tests/test_energy_write_verification.py:1636::test_c_high_2_witness_compare_anchor_present` |  |  |
| `quality/tests/test_energy_write_verification.py:1651::test_c_high_3_tap_normalization_source_anchor` |  |  |
| `quality/tests/test_energy_write_verification.py:1702::test_c_med_1_h3_options_round_trip_source_anchor` |  |  |
| `quality/tests/test_evse_drain_precedence_session_b1.py:61::test_dp_enable_switch_registered_in_setup_entry` |  |  |
| `quality/tests/test_evse_drain_precedence_session_b1.py:75::test_dp_switch_uses_dp_enabled_attr` |  |  |
| `quality/tests/test_evse_drain_precedence_session_b1.py:85::test_dp_number_setups_registered` |  |  |
| `quality/tests/test_evse_drain_precedence_session_b1.py:103::test_dp_house_load_source_select_registered` |  |  |
| `quality/tests/test_evse_drain_precedence_session_b1.py:114::test_dp_state_sensor_registered_in_setup_entry` |  |  |
| `quality/tests/test_evse_drain_precedence_session_b1.py:139::test_ec_setter_dispatch_covers_all_dp_number_and_select_keys` |  |  |
| `quality/tests/test_evse_drain_precedence_session_b2c3_fixup.py:104::test_MUTATION_h1_save_evse_dp_paused_dropped_makes_ast_test_red` |  |  |
| `quality/tests/test_evse_drain_precedence_session_b2c3_fixup.py:238::test_m1_accepted_gap_documented_in_needed_kwh_docstring` |  |  |
| `quality/tests/test_evse_solar_aware_ux.py:125::test_excess_solar_switch_unique_id_preserved` |  |  |
| `quality/tests/test_evse_solar_aware_ux.py:136::test_friendly_name_renamed` |  |  |
| `quality/tests/test_evse_solar_aware_ux.py:149::test_migration_helper_exists` |  |  |
| `quality/tests/test_evse_solar_aware_ux.py:164::test_fill_priority_soc_number_class_exists` |  |  |
| `quality/tests/test_evse_solar_aware_ux.py:173::test_fill_priority_soc_unique_id` |  |  |
| `quality/tests/test_evse_solar_aware_ux.py:325::test_nm_trip_helper_exists` |  |  |
| `quality/tests/test_evse_solar_aware_ux.py:365::test_evse_tou_friendly_name` |  |  |
| `quality/tests/test_evse_solar_aware_ux.py:452::test_config_flow_module_compiles_and_imports` |  |  |
| `quality/tests/test_evse_solar_aware_ux.py:1133::test_config_flow_injects_evse_checkbox_only_when_configured` | yes |  |
| `quality/tests/test_exterior_track_linker.py:353::test_inv_xp_per_camera_cooldown_gate_source_present` |  |  |
| `quality/tests/test_exterior_track_linker.py:415::test_smart_alerts_gate_wired_in_severity_block_only` |  | yes |
| `quality/tests/test_fan_humidity_toggle_symmetry.py:78::test_room_suppress_keys_import_aliases_present` |  |  |
| `quality/tests/test_fan_layer_2_d1.py:473::test_presence_recheck_reader_source_prefers_oracle` |  |  |
| `quality/tests/test_fan_recheck_deferred_surfaces.py:188::test_config_flow_wires_per_room_and_master_keys` |  |  |
| `quality/tests/test_fan_recheck_deferred_surfaces.py:222::test_switch_platform_wires_master_and_room_switches` |  |  |
| `quality/tests/test_fan_recheck_deferred_surfaces.py:248::test_number_platform_no_longer_registers_seven_timing_numbers` | yes |  |
| `quality/tests/test_fan_recheck_deferred_surfaces.py:268::test_init_cleans_up_orphan_fan_recheck_number_registry_entries` |  |  |
| `quality/tests/test_fan_recheck_deferred_surfaces.py:310::test_config_flow_collapses_timing_knobs_into_advanced_section` |  |  |
| `quality/tests/test_fan_recheck_deferred_surfaces.py:333::test_binary_sensor_surfaces_fan_recheck_attrs` |  |  |
| `quality/tests/test_fan_recheck_deferred_surfaces.py:362::test_sensor_platform_wires_state_and_outcome_sensors` |  |  |
| `quality/tests/test_fan_recheck_deferred_surfaces.py:389::test_init_registers_and_unloads_force_restore_service` | yes |  |
| `quality/tests/test_fan_recheck_deferred_surfaces.py:514::test_mirror_pattern_present_in_switch_and_number` | yes |  |
| `quality/tests/test_fan_recheck_mode2_cycle.py:1045::test_state_machine_module_uses_module_top_dispatcher_import` |  | yes |
| `quality/tests/test_fan_recheck_mode2_cycle.py:1057::test_state_machine_does_not_use_legacy_terminology` | yes |  |
| `quality/tests/test_fan_recheck_mode2_cycle.py:1064::test_fan_controller_has_pause_restore_suppress_methods` |  |  |
| `quality/tests/test_fan_recheck_mode2_cycle.py:1088::test_room_coordinator_has_apply_fan_recheck_release` |  |  |
| `quality/tests/test_fan_recheck_mode2_cycle.py:1098::test_presence_has_get_adjacent_rooms_public_method` |  |  |
| `quality/tests/test_fan_recheck_mode2_cycle.py:1106::test_database_module_has_fan_recheck_daos` |  |  |
| `quality/tests/test_fan_transition_gate.py:472::test_mutation_neuter_suppression_causes_incident_test_to_fail` |  |  |
| `quality/tests/test_fan_transition_gate.py:630::test_c1_no_unconditional_return_before_gate` |  |  |
| `quality/tests/test_fan_transition_gate.py:720::test_c2_occupied_binary_sensor_exposes_fan_transition_suppressed_count` |  |  |
| `quality/tests/test_house_state_rung1.py:128::test_optimization_night_literal_fixed` | yes |  |
| `quality/tests/test_hvac_presence_timer_knobs.py:304::test_hvac_settings_schema_includes_presence_timing_section` |  |  |
| `quality/tests/test_hvac_presence_timer_knobs.py:348::test_constrained_validation_reject_in_source` |  |  |
| `quality/tests/test_imsg_audit_fix_1.py:342::test_emit_audit_row_writer_passes_acknowledged` |  |  |
| `quality/tests/test_kanban_ship.py:126::test_atomic_write_roundtrip` |  |  |
| `quality/tests/test_kanban_ship.py:252::test_real_board_idempotent_reship` |  |  |
| `quality/tests/test_ledger_golden_replay.py:141::test_p22_end_to_end_on_synthetic` |  | yes |
| `quality/tests/test_ledger_golden_replay_preserve.py:80::test_signed_off_supplement_preserved_byte_identical` |  |  |
| `quality/tests/test_ledger_golden_replay_preserve.py:132::test_skeleton_and_draft_are_overwritten` | yes |  |
| `quality/tests/test_ledger_golden_replay_preserve.py:156::test_manifest_signoff_blocks_survive_regeneration` | yes |  |
| `quality/tests/test_ledger_golden_replay_preserve.py:175::test_determinism_without_preserved_files` |  |  |
| `quality/tests/test_memory_compactor.py:176::test_stage0_fixture_diff` |  |  |
| `quality/tests/test_memory_compactor.py:667::test_sensor_exposes_compactor_attrs` |  |  |
| `quality/tests/test_memory_mvp.py:932::test_wire_memory_called_from_both_db_init_sites` |  |  |
| `quality/tests/test_mmwave_fan_demotion.py:566::test_mutation_anchor_delimiters_present_in_coordinator` |  |  |
| `quality/tests/test_nm_cycle_a_preserved_signals.py:70::test_envoy_write_verify_critical_site_present` |  |  |
| `quality/tests/test_nm_cycle_a_preserved_signals.py:88::test_water_leak_binary_still_maps_to_water_leak_hazard` |  |  |
| `quality/tests/test_nm_cycle_a_preserved_signals.py:133::test_a1_tripped_breaker_still_emits_anomaly_event` |  |  |
| `quality/tests/test_nm_image_delivery.py:670::test_pending_digest_query_shape` |  |  |
| `quality/tests/test_nm_image_delivery.py:846::test_get_notifications_today_filters_audit_sentinel` |  |  |
| `quality/tests/test_nm_image_delivery.py:862::test_get_last_notification_filters_audit_sentinel` |  |  |
| `quality/tests/test_pathalpha_d2c_d3_observability.py:157::test_d3_reason_string_enriched_with_tracking_reason_at_source` |  |  |
| `quality/tests/test_pathalpha_d2c_d3_observability.py:171::test_d2c_person_location_sensor_init_has_provenance_defaults` |  |  |
| `quality/tests/test_pathalpha_d2c_d3_observability.py:177::test_d2c_person_location_sensor_attrs_publish_reason_and_sources` |  |  |
| `quality/tests/test_pathalpha_d2c_d3_observability.py:227::test_source_invariant_zone_bucket_default_comment_present` |  |  |
| `quality/tests/test_pathalpha_d2c_d3_observability.py:242::test_d2c_house_state_publishes_both_census_and_face_counts` |  |  |
| `quality/tests/test_prediction_sensor_kill_list.py:38::test_sensor_source_removes_killed_classes` | yes |  |
| `quality/tests/test_prediction_sensor_kill_list.py:49::test_sensor_source_drops_killed_classes_from_setup_entry` | yes |  |
| `quality/tests/test_prediction_sensor_kill_list.py:60::test_sensor_source_drops_unused_state_imports` | yes |  |
| `quality/tests/test_prediction_sensor_kill_list.py:73::test_init_carries_prediction_kill_list_cleanup_block` |  |  |
| `quality/tests/test_prediction_sensor_kill_list.py:151::test_init_sets_change_sentinels_source_check` |  |  |
| `quality/tests/test_presence_provenance_audit.py:28::test_audit_doc_exists` |  |  |
| `quality/tests/test_presence_provenance_docs.py:18::test_presence_coordinator_doc_has_tier1_provenance_section` |  |  |
| `quality/tests/test_presence_provenance_docs.py:33::test_tech_debt_marks_tier1_or_resolved` |  |  |
| `quality/tests/test_r1_consumption_regression_v1.py:367::test_compute_v1_matches_local_predict` |  |  |
| `quality/tests/test_reconcile_on_return.py:453::test_reconcile_module_does_not_import_database_daos` | yes |  |
| `quality/tests/test_resolver_accuracy.py:71::test_stem_alias_table_matches_const_module` |  |  |
| `quality/tests/test_resolver_legs.py:307::test_retirement_anchor_perimeter_helpers_deleted` | yes |  |
| `quality/tests/test_resolver_legs.py:321::test_kill_switch_rename_present_and_alias_retained` |  |  |
| `quality/tests/test_resolver_legs.py:650::test_coverage_info_log_site_in_production_source` |  |  |
| `quality/tests/test_safeword_window.py:605::test_wire_in_gate_present_in_async_notify` |  |  |
| `quality/tests/test_safeword_window.py:617::test_wire_in_parse_present_in_process_inbound_reply` |  |  |
| `quality/tests/test_sensor_exclusion.py:130::test_sensor_exclusion_scope_room_tier_only` | yes |  |
| `quality/tests/test_setup_unload_symmetry.py:104::test_every_registered_service_has_paired_async_remove` |  |  |
| `quality/tests/test_setup_unload_symmetry.py:174::test_v39_panel_has_paired_remove` |  |  |
| `quality/tests/test_setup_unload_symmetry.py:192::test_v3_dashboard_panel_has_paired_remove` |  |  |
| `quality/tests/test_setup_unload_symmetry.py:210::test_static_path_gap_is_documented_in_source` |  |  |
| `quality/tests/test_setup_unload_symmetry.py:424::test_service_registration_block_present` |  |  |
| `quality/tests/test_setup_unload_symmetry.py:438::test_panel_register_calls_present` |  |  |
| `quality/tests/test_setup_unload_symmetry.py:446::test_static_path_register_calls_present` |  |  |
| `quality/tests/test_tracking_reason_vocabulary_pin.py:193::test_row5_collapses_into_bermuda_authoritative` |  |  |
| `quality/tests/test_unavailable_entities_chatter.py:33::test_unavailable_entities_sensor_surfaces_chattering_sensor` |  |  |
| `quality/tests/test_unavailable_entities_chatter.py:55::test_unavailable_entities_sensor_no_chatter_when_set_empty` |  |  |
| `quality/tests/test_unavailable_entities_chatter.py:67::test_structural_chatter_diag_provenance_parity` |  |  |
| `quality/tests/test_v4521_hc_device_ordering.py:531::test_enabled_switch_hvac_prefix` |  |  |
| `quality/tests/test_v4615_threadsafety.py:87::test_v4615_fix_sites_use_direct_coroutine_passing` |  |  |
| `quality/tests/test_v4615_threadsafety.py:136::test_handle_db_ready_uses_add_job_not_async_create_task` |  |  |
| `quality/tests/test_v461_cleanup_anomaly_log.py:37::test_cleanup_anomaly_log_method_exists` |  |  |
| `quality/tests/test_v461_db_migration.py:18::test_migration_uses_pragma_table_info_anomaly_log` |  |  |
| `quality/tests/test_v461_db_migration.py:26::test_migration_adds_event_class_column` |  |  |
| `quality/tests/test_v461_db_migration.py:36::test_migration_adds_recovery_at_column` |  |  |
| `quality/tests/test_v461_db_migration.py:41::test_migration_adds_correlation_id_column` |  |  |
| `quality/tests/test_v461_db_migration.py:109::test_migration_backfills_old_text_severity_to_int` |  |  |
| `quality/tests/test_v461_db_migration.py:140::test_anomaly_event_recovery_clears_correctly` |  |  |
| `quality/tests/test_v461_store_event_writer.py:73::test_save_anomaly_event_dao_exists` |  |  |
| `quality/tests/test_v4622_guest_mode_hardening.py:195::test_census_signal_payload_includes_confidence` |  |  |
| `quality/tests/test_v4622_guest_mode_hardening.py:206::test_census_signal_payload_includes_source_agreement` |  |  |
| `quality/tests/test_v4622_guest_mode_hardening.py:236::test_guest_mode_config_defaults` | yes |  |
| `quality/tests/test_v4622_guest_mode_hardening.py:297::test_guest_mode_config_round_trip` | yes |  |
| `quality/tests/test_v4622_guest_mode_hardening.py:510::test_guest_gate_exit_is_immediate` | yes |  |
| `quality/tests/test_v4622_guest_mode_hardening.py:771::test_guest_gate_method_exists` |  |  |
| `quality/tests/test_v4622_guest_mode_hardening.py:800::test_inference_engine_infer_accepts_guest_gate_armed_param` |  |  |
| `quality/tests/test_v4622_guest_mode_hardening.py:814::test_confidence_rank_map_is_private` |  |  |
| `quality/tests/test_v4622_guest_mode_hardening.py:829::test_guest_persistence_handle_cleanup_registered` |  |  |
| `quality/tests/test_v4622_guest_mode_hardening.py:849::test_guest_mode_init_constants_in_init_py` | yes |  |
| `quality/tests/test_v462_regime_detector_dispatches_signals.py:33::test_signal_routine_status_update_declared` |  |  |
| `quality/tests/test_v462_regime_detector_dispatches_signals.py:43::test_signal_regime_event_emitted_declared` |  |  |
| `quality/tests/test_v462_regime_detector_dispatches_signals.py:58::test_regime_detector_dispatches_status_update_signal` |  |  |
| `quality/tests/test_v462_regime_detector_dispatches_signals.py:68::test_regime_detector_dispatches_regime_event_emitted_signal` |  |  |
| `quality/tests/test_v462_regime_detector_dispatches_signals.py:121::test_window_days_method_exists` |  |  |
| `quality/tests/test_v462_regime_detector_dispatches_signals.py:180::test_regime_detector_instantiated_with_entry` |  |  |
| `quality/tests/test_v462_regime_detector_dispatches_signals.py:219::test_vacation_skip_uses_configured_recent_window` |  |  |
| `quality/tests/test_v462_regime_detector_dispatches_signals.py:277::test_nm_reads_cooldown_from_entity_state` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:126::test_safety_hazard_uses_store_event` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:144::test_safety_hazard_activity_logger_called` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:153::test_safety_hazard_uses_build_context_json` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:177::test_safety_sensitivity_multiplier_wired` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:193::test_presence_no_store_anomaly_calls` | yes |  |
| `quality/tests/test_v463_anomaly_migration.py:242::test_presence_transition_count_daily_wired_and_recorded` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:290::test_presence_sensitivity_multiplier_wired` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:343::test_presence_census_count_persistence_suppressed` | yes |  |
| `quality/tests/test_v463_anomaly_migration.py:429::test_transitions_emits_invalid_transition_anomaly` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:437::test_transitions_invalid_anomaly_uses_event_class_and_saves_to_db` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:459::test_transitions_invalid_anomaly_calls_activity_logger` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:489::test_energy_emits_circuit_anomaly` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:504::test_energy_circuit_anomaly_calls_activity_logger` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:517::test_nm_dispatch_emits_correlation` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:525::test_nm_dispatch_type_distinct` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:534::test_nm_dispatch_saves_to_db_and_calls_activity_logger` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:570::test_compliance_violation_anomaly_exists` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:616::test_store_anomaly_wrapper_deleted` | yes |  |
| `quality/tests/test_v463_anomaly_migration.py:756::test_sensitivity_constants_exist` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:768::test_sensitivity_options_list_exists` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:776::test_sensitivity_conf_keys_per_coordinator` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:806::test_hvac_sensitivity_multiplier_wired` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:819::test_security_sensitivity_multiplier_wired` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:832::test_music_sensitivity_multiplier_wired` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:874::test_build_context_json_exists_and_has_canonical_keys` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:986::test_recent_anomalies_sensor_class_exists` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:994::test_recent_anomalies_sensor_subscribes_to_signal` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:1083::test_anomaly_diagnostic_dump_button_exists` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:1131::test_config_flow_has_sensitivity_dropdowns` |  |  |
| `quality/tests/test_v463_anomaly_migration.py:1147::test_config_flow_uses_select_selector` |  |  |
| `quality/tests/test_v465_observability_gap.py:197::test_hvac_anomaly_description_includes_z_score` |  |  |
| `quality/tests/test_v465_observability_gap.py:247::test_security_metrics_entry_anomaly_score_suppressed` |  |  |
| `quality/tests/test_v465_observability_gap.py:278::test_security_anomaly_description_includes_z_score` |  |  |
| `quality/tests/test_v465_observability_gap.py:299::test_security_handle_entry_intent_is_async` |  |  |
| `quality/tests/test_v465_observability_gap.py:351::test_music_following_has_persist_helper` |  |  |
| `quality/tests/test_v465_observability_gap.py:367::test_music_following_uses_async_create_task_for_persist` |  |  |
| `quality/tests/test_v465_observability_gap.py:391::test_music_following_anomaly_description_includes_z_score` |  |  |
| `quality/tests/test_v465_observability_gap.py:453::test_safety_detector_active_hazard_count_audit_documented` |  |  |
| `quality/tests/test_v465_observability_gap.py:530::test_presence_census_count_suppressed` | yes |  |
| `quality/tests/test_v465_observability_gap.py:597::test_presence_zone_occupied_count_suppressed` | yes |  |
| `quality/tests/test_v465_observability_gap.py:978::test_presence_hydrates_transitions_today_from_house_state_log` |  |  |
| `quality/tests/test_v465_observability_gap.py:1170::test_recent_anomalies_sensor_subscribes_to_database_ready_signal` | yes |  |
| `quality/tests/test_v466_severity_refactor.py:731::test_v466_d2_migration_uses_pragma_user_version_gate` |  |  |
| `quality/tests/test_v467_anomaly_log_null_relaxation.py:245::test_v467_migration_block_exists_with_pragma_gate` |  |  |
| `quality/tests/test_v4714_1_forgotten_phone_hotfix.py:713::test_h2_filter_present_in_source` |  |  |
| `quality/tests/test_v4714_1_forgotten_phone_hotfix.py:719::test_h2_filter_references_phone_left_behind_unique_id` |  |  |
| `quality/tests/test_v4714_1_forgotten_phone_hotfix.py:910::test_h3_filter_references_tracking_status` |  |  |
| `quality/tests/test_v4714_1_forgotten_phone_hotfix.py:916::test_h3_imports_tracking_status_active` |  |  |
| `quality/tests/test_v4714_1_forgotten_phone_hotfix.py:1032::test_am3_excluded_persons_attribute_present_in_coordinator` |  |  |
| `quality/tests/test_v4714_1_forgotten_phone_hotfix.py:1040::test_am1_am3_filter_loop_captures_reason` |  |  |
| `quality/tests/test_v4714_1_forgotten_phone_hotfix.py:1074::test_am2_raw_count_attribute_present` |  |  |
| `quality/tests/test_v4714_1_forgotten_phone_hotfix.py:1085::test_am2_trusted_count_attribute_present` |  |  |
| `quality/tests/test_v4714_1_forgotten_phone_hotfix.py:1094::test_am2_excluded_persons_attribute_present` |  |  |
| `quality/tests/test_v4714_1_forgotten_phone_hotfix.py:1103::test_am2_presence_coordinator_tracks_raw_count` |  |  |
| `quality/tests/test_v4714_1_forgotten_phone_hotfix.py:1118::test_am2_presence_coordinator_tracks_trusted_count` |  |  |
| `quality/tests/test_v4714_away_state_person_tracker_trust.py:183::test_computation_block_exists` |  |  |
| `quality/tests/test_v4714_away_state_person_tracker_trust.py:189::test_tracked_count_computed` |  |  |
| `quality/tests/test_v4714_away_state_person_tracker_trust.py:204::test_empty_config_failsafe_present` |  |  |
| `quality/tests/test_v4714_away_state_person_tracker_trust.py:260::test_diagnostic_attributes_stored_on_self` |  |  |
| `quality/tests/test_v4714_away_state_person_tracker_trust.py:517::test_house_state_sensor_exposes_tracked_persons_count` |  |  |
| `quality/tests/test_v4714_away_state_person_tracker_trust.py:523::test_house_state_sensor_exposes_all_tracked_persons_away` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:575::test_source_emits_one_shot_warn_on_length_mismatch` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:823::test_helper_is_public_method` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:826::test_veto_decision_dataclass_at_module_scope` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:829::test_helper_dispatches_on_scope` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:845::test_layer3_method_exists` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:923::test_first_positive_zone_occupied_since_field_exists` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:926::test_wake_blocked_ticks_counter_exists` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:946::test_guest_exit_quiet_since_field_exists` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:1031::test_public_method_on_presence` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:1036::test_old_hvac_method_deleted` | yes |  |
| `quality/tests/test_v4715_universalize_veto.py:1041::test_hvac_call_site_uses_presence_accessor` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:1087::test_new_sensor_class_exists` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:1092::test_new_sensor_unique_id` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:1097::test_new_sensor_registered_in_platform` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:1100::test_existing_house_state_confidence_sensor_preserved` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:1104::test_mirror_attributes_on_rich_sensor` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:1114::test_band_high_above_0_85` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:1118::test_band_constant_strings_present` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:1129::test_defer_gate_field_exists` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:1134::test_d6_deferrals_today_counter_exists` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:1153::test_compliance_defer_gate_field_exists` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:1176::test_hvac_consensus_defer_switch_exists` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:1182::test_compliance_consensus_defer_switch_exists` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:1195::test_v4713_sleep_fallback_warn_intact` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:1201::test_v4714_infer_kwarg_intact` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:1204::test_v4714_inference_engine_veto_branch_intact` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:1244::test_v4714_diagnostic_attributes_intact` |  |  |
| `quality/tests/test_v4715_universalize_veto.py:1557::test_sleep_path_still_routes_through_layer_2` |  |  |
| `quality/tests/test_v47181_sleep_wake_deadlock.py:537::test_sensor_exposes_wake_backstop_fires` |  |  |
| `quality/tests/test_v47181_sleep_wake_deadlock.py:547::test_wake_blocked_ticks_still_surfaced` |  |  |
| `quality/tests/test_v4_6_11_d3_persistence_and_dispatch.py:100::test_source_manager_py_has_load_baselines_call` |  |  |
| `quality/tests/test_v4_6_11_d3_persistence_and_dispatch.py:118::test_source_manager_py_guards_load_with_try_except` |  |  |
| `quality/tests/test_v4_6_11_d3_persistence_and_dispatch.py:486::test_init_py_has_map_diag_severity_import` |  |  |
| `quality/tests/test_v4_6_11_d3_persistence_and_dispatch.py:492::test_init_py_has_anomaly_event_construction` |  |  |
| `quality/tests/test_v4_6_11_d3_persistence_and_dispatch.py:519::test_init_py_no_scaffold_only_comment` | yes |  |
| `quality/tests/test_v4_6_11_dashboard_attrs.py:81::test_dt_util_imported_in_coordinator_diagnostics` |  |  |
| `quality/tests/test_v4_6_11_dashboard_attrs.py:101::test_asyncio_run_used_in_telemetry_test` |  |  |
| `quality/tests/test_v4_6_11_dashboard_attrs.py:120::test_source_get_summary_has_health_status` |  |  |
| `quality/tests/test_v4_6_11_dashboard_attrs.py:126::test_source_get_summary_has_status_per_coordinator` |  |  |
| `quality/tests/test_v4_6_11_dashboard_attrs.py:282::test_source_per_zone_breakdown_key_present` |  |  |
| `quality/tests/test_v4_6_11_dashboard_attrs.py:361::test_source_idle_duration_key_present` |  |  |
| `quality/tests/test_v4_6_11_dashboard_attrs.py:405::test_source_state_time_since_occupied_imported` |  |  |
| `quality/tests/test_v4_6_11_dashboard_attrs.py:421::test_source_current_persons_key_present` |  |  |
| `quality/tests/test_v4_6_11_dashboard_attrs.py:476::test_current_persons_uses_person_coordinator_key` |  |  |
| `quality/tests/test_v4_6_11_dashboard_attrs.py:492::test_source_source_breakdown_key_present` |  |  |
| `quality/tests/test_v4_6_11_dashboard_attrs.py:498::test_source_breakdown_has_three_sub_keys` |  |  |
| `quality/tests/test_v4_6_11_dashboard_attrs.py:566::test_source_zone_limits_key_present` |  |  |
| `quality/tests/test_v4_6_11_dashboard_attrs.py:572::test_source_zone_limits_uses_get_zone_status_attrs` |  |  |
| `quality/tests/test_v4_6_11_dashboard_attrs.py:653::test_class_exists_in_sensor_py` |  |  |
| `quality/tests/test_v4_6_11_dashboard_attrs.py:658::test_registered_in_async_setup_entry` |  |  |
| `quality/tests/test_v4_6_12_aggregator_sensors.py:691::test_zone_motion_window_constant_in_const` |  |  |
| `quality/tests/test_v4_6_12_aggregator_sensors.py:696::test_zone_motion_sensor_class_in_aggregation` |  |  |
| `quality/tests/test_v4_6_12_aggregator_sensors.py:700::test_house_system_demand_sensor_class_in_aggregation` |  |  |
| `quality/tests/test_v4_6_12_aggregator_sensors.py:704::test_energy_grid_demand_sensor_class_in_aggregation` |  |  |
| `quality/tests/test_v4_6_12_aggregator_sensors.py:708::test_all_three_registered_in_setup` |  |  |
| `quality/tests/test_v4_6_12_aggregator_sensors.py:714::test_get_hvac_coordinator_helper_present` |  |  |
| `quality/tests/test_v4_6_12_aggregator_sensors.py:754::test_zone_motion_window_imported_in_aggregation` |  |  |
| `quality/tests/test_v4_6_13_coordinator_telemetry.py:48::test_coordinator_emit_labels_defined` |  |  |
| `quality/tests/test_v4_6_13_coordinator_telemetry.py:52::test_all_five_ui_coordinators_keyed` |  |  |
| `quality/tests/test_v4_6_13_coordinator_telemetry.py:57::test_presence_rolls_up_three_labels` |  |  |
| `quality/tests/test_v4_6_13_coordinator_telemetry.py:96::test_interval_constants_present` |  |  |
| `quality/tests/test_v4_6_13_coordinator_telemetry.py:131::test_decisions_today_registered_five_times` |  |  |
| `quality/tests/test_v4_6_9_energy_recent_decisions.py:222::test_sensor_registered_in_cm_block` |  |  |
| `quality/tests/test_v4_6_9_energy_recent_decisions.py:232::test_decision_buffer_is_deque_maxlen_20` |  |  |
| `quality/tests/test_v4_6_9_energy_recent_decisions.py:337::test_collections_import_added` |  |  |
| `quality/tests/test_v4_6_9_energy_recent_decisions.py:408::test_deque_maxlen_is_20_in_source` |  |  |
| `quality/tests/test_v4_6_9_hvac_intent_attrs.py:241::test_get_intent_attrs_defined_in_hvac_predict` |  |  |
| `quality/tests/test_v4_6_9_hvac_intent_attrs.py:261::test_prior_day_todo_comment_present` |  |  |
| `quality/tests/test_v4_6_9_next_state_sensor.py:111::test_presence_next_state_sensor_registered_in_cm_block` |  |  |
| `quality/tests/test_v4_6_9_next_state_sensor.py:115::test_next_state_vocab_strEnum_defined` |  |  |
| `quality/tests/test_v4_6_9_next_state_sensor.py:167::test_placeholder_model_id` |  |  |
| `quality/tests/test_v4_6_9_next_state_sensor.py:171::test_todo_comment_for_v47x` |  |  |
| `quality/tests/test_v4_6_9_next_state_sensor.py:176::test_returns_flat_dict_keys` |  |  |
| `quality/tests/test_v4_6_9_next_state_sensor.py:405::test_presence_py_uses_isoformat_not_datetime_object` |  |  |
| `quality/tests/test_v4_6_9_safety_recent_events.py:257::test_sensor_registered_in_cm_block` |  |  |
| `quality/tests/test_v4_6_9_safety_recent_events.py:267::test_event_buffer_is_deque_maxlen_20` |  |  |
| `quality/tests/test_v4_6_9_safety_recent_events.py:274::test_event_severity_strenum_defined` |  |  |
| `quality/tests/test_v4_6_9_security_aggregator.py:203::test_aggregator_sensor_registered_in_cm_block` |  |  |
| `quality/tests/test_v4_6_9_security_aggregator.py:210::test_security_agg_status_strenum_defined` |  |  |
| `quality/tests/test_v4_7_18_2_boot_warning_logonce.py:291::test_warned_zones_set_keyed_by_self_zone` | yes |  |
| `quality/tests/test_v4_7_18_2_boot_warning_logonce.py:308::test_no_per_entity_log_once_flag_remnant` | yes |  |
| `quality/tests/test_v4_7_18_2_boot_warning_logonce.py:317::test_unload_clears_warned_zones` |  |  |
| `quality/tests/test_v4_7_18_dpm_drift_guard.py:341::test_validate_dynamic_preset_input_deleted` | yes |  |
| `quality/tests/test_v4_7_18_dpm_drift_guard.py:356::test_no_self_validate_calls_remain` | yes |  |
| `quality/tests/test_v570_fixup_wiring.py:74::test_source_invariant_sleep_exempt_unions_with_sleep_hour` |  |  |
| `quality/tests/test_v570_fixup_wiring.py:128::test_source_invariant_indoor_clear_debounce_present` |  |  |
| `quality/tests/test_v570_fixup_wiring.py:210::test_source_invariant_relaxed_predicate_wiring_retired_d2b` | yes |  |
| `quality/tests/test_v570_fixup_wiring.py:234::test_source_invariant_separate_lost_away_stamp_dict` | yes |  |
| `quality/tests/test_v570_fixup_wiring.py:290::test_c_high_1_a1_predicate_call_retired_d2b` | yes |  |
| `quality/tests/test_v570_fixup_wiring.py:300::test_c_high_1_a4_outdoor_snapshot_call_present_in_run_inference` | yes |  |
| `quality/tests/test_v570_fixup_wiring.py:353::test_source_invariant_grace_gated_on_youngest_stamp` | yes |  |
| `quality/tests/test_v570_fixup_wiring.py:447::test_source_invariant_lost_away_persons_attr_retired_d2b` | yes |  |
| `quality/tests/test_v570_fixup_wiring.py:457::test_source_invariant_grace_remaining_suppressed_on_sleep_exempt` |  |  |
| `quality/tests/test_v570_guest_detection_trust.py:618::test_source_invariant_a1_predicate_retired_d2b` | yes |  |
| `quality/tests/test_v570_guest_detection_trust.py:632::test_source_invariant_path_alpha_unchanged` | yes |  |
| `quality/tests/test_v570_guest_detection_trust.py:658::test_source_invariant_path_beta_indoor_guard_present` |  |  |
| `quality/tests/test_v570_guest_detection_trust.py:665::test_source_invariant_path_beta_grace_and_sleep_guards` |  |  |
| `quality/tests/test_v570_guest_detection_trust.py:673::test_source_invariant_a4_outdoor_zone_helper_exists` |  |  |
| `quality/tests/test_v570_guest_detection_trust.py:698::test_source_invariant_sensor_exposes_new_attrs` | yes |  |
| `quality/tests/test_v5_17_3_boundary_and_latch.py:352::test_removing_rearm_breaks_selfheal` |  | yes |
| `quality/tests/test_v5_17_3_boundary_and_latch.py:479::test_mutation_drop_reset_persist_trigger_red` | yes |  |
| `quality/tests/test_v5_17_3_boundary_and_latch.py:542::test_mutation_remove_ledger_fallback_red` |  | yes |
| `quality/tests/test_v5_7_1_energy_precool.py:404::test_should_solar_bank_deleted` | yes |  |
| `quality/tests/test_v5_7_1_energy_precool.py:412::test_should_energy_precool_exists` |  |  |
| `quality/tests/test_v5_7_1_energy_precool.py:442::test_switch_class_renamed` | yes |  |
| `quality/tests/test_v5_7_1_energy_precool.py:796::test_pre_arrival_block_unchanged` |  |  |
| `quality/tests/test_v5_7_1_energy_precool.py:806::test_pre_heat_dispatch_present` |  |  |
| `quality/tests/test_v5_7_1_energy_precool.py:1113::test_orphan_cleanup_helper_exists_and_idempotent` |  |  |
| `quality/tests/test_v5_7_1_energy_precool.py:1123::test_restore_state_helper_is_called_sync_not_awaited` | yes |  |
| `quality/tests/test_v5_7_1_energy_precool.py:1220::test_switch_factory_registers_energy_precool` |  |  |
| `quality/tests/test_v5_7_1_energy_precool.py:1227::test_offset_number_class_present` |  |  |
| `quality/tests/test_v5_7_1_energy_precool.py:1233::test_scope_select_class_present` |  |  |
| `quality/tests/test_v5_7_1_energy_precool.py:1239::test_energy_coordinator_has_three_setters` |  |  |
| `quality/tests/test_zone_delete_flow.py:800::test_signal_zm_zones_updated_wired_end_to_end` |  |  |
| `quality/tests/test_zone_delete_prune_guard.py:218::test_correct_import_path_for_conf_zone_thermostat` | yes |  |
| `quality/tests/test_zone_safety_alert.py:464::test_cleared_leak_options_override_not_defeated_by_data` | yes | yes |
| `quality/tests/test_zone_substrate_migration.py:48::test_area_sweep_path_deleted_no_substring_fallback` | yes |  |
