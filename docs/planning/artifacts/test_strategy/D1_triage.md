# D1 — Baseline triage of the 158 failing test ids

Input: `baseline_158.txt`, extracted from the full-suite run captured in the prior session
(`develop_full.txt`, `141 failed, 9403 passed, 53 skipped, 2 xfailed, 17 errors in 228.50s`).
**No full-suite run was performed by this cycle.**

Method: every one of the 43 files carrying a baseline failure was re-run ALONE
(`PYTHONDONTWRITEBYTECODE=1`, `__pycache__` scrubbed, `-p no:cacheprovider`), as part of a
sweep of all 425 test files. Bucket assignment: an id that PASSES alone is B3; an id that
fails alone is bucketed by its alone-run traceback.

## Bucket counts

| bucket | meaning | count |
|---|---|---|
| B1 | real product defect nobody triaged | 16 |
| B2 | broken / stale test (incl. Bug Class #62 text anchors) | 72 |
| B3 | order-pollution victim (passes alone) | 60 |
| B4 | environment / collection error | 10 |
| B5 | flaky (nondeterministic) | 0 — **zero found after full sweep**: the 158-id set was identical across 8 independent full-suite runs (see below), and every alone-run was deterministic across the two sweeps performed. |
| **total** | | **158** |

## Determinism of the baseline (pre-condition check)

Eight full-suite runs were captured in the prior session (`develop_full`, `branch_full`,
`branch_full2`, `branch_full3`, `branch_final`, `item1_full`, `item1_rerun`, `develop_current`).
Failing-id set analysis:

```
STABLE core (fails in ALL 8 runs) : 158
UNION across 8 runs               : 173
UNSTABLE (in union, not in all)   :  15
```

The 158 is a genuine invariant core — every run's failing set is a SUPERSET of it. But the
operator's framing "158 failing IDs, IDENTICAL on develop and on feature branches" is only
true of the core: run totals were 141/141/141/141/143/143/143/154 failed, and 15 further ids
appeared in one or more runs. Those 15 are the true flaky/branch-specific population and are
OUT of the 158 by construction.

## Per-test classification

| test id | bucket | evidence |
|---|---|---|
| `quality/tests/test_chatter_d7_shadow_act.py::test_d7_room_telemetry_surfaces_burst_count_and_would_quarantine` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_chatter_detector.py::test_boot_settle_gate_suppresses_flagging` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_chatter_detector.py::test_chatter_auto_release_after_quiet_window` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_chatter_detector.py::test_chatter_detector_unsubscribe_called_on_teardown` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_chatter_detector.py::test_chatter_release_skipped_when_unavailable` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_chatter_detector.py::test_d2_low_2_operator_t_floor_override_takes_effect_live` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_chatter_detector.py::test_d_high_2_boot_transient_no_instant_quarantine_on_restart` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_chatter_detector.py::test_d_med_1_z2m_numeric_id_scored_via_device_class_fallback` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_chatter_detector.py::test_d_med_2_operator_burst_k_override_takes_effect` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_chatter_detector.py::test_healthy_busy_pir_not_flagged_despite_high_transition_rate` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_chatter_detector.py::test_isolated_sub_floor_artifacts_below_K_not_flagged` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_chatter_detector.py::test_mislabeled_frigate_entity_denied_by_integration_fallback` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_chatter_detector.py::test_ratgdo_shaped_sensor_flagged_chatter_after_burst` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_chatter_detector.py::test_recalibration_invisoutlet_shape_flagged_at_K10` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_chatter_detector.py::test_recalibration_meross_healthy_night_not_flagged` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_chatter_detector.py::test_unavailable_transitions_not_counted` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_cm_reload_suppression.py::test_d1_seed_cm_last_applied_options_seeds_at_setup` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs); reported as ERROR (fixture) not FAILED |
| `quality/tests/test_cm_reload_suppression.py::test_d1_snapshot_cleared_on_unload` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs); reported as ERROR (fixture) not FAILED |
| `quality/tests/test_cm_reload_suppression.py::test_d1_snapshot_is_a_copy_not_a_reference` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs); reported as ERROR (fixture) not FAILED |
| `quality/tests/test_cm_reload_suppression.py::test_d1_snapshot_reseeded_after_reload` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs); reported as ERROR (fixture) not FAILED |
| `quality/tests/test_cm_reload_suppression.py::test_d3_apply_in_place_defensive_clamp_when_constrained_exceeds_normal` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs); reported as ERROR (fixture) not FAILED |
| `quality/tests/test_cm_reload_suppression.py::test_d3_apply_in_place_dpm_dwell_treated_as_applied_when_hvac_missing` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs); reported as ERROR (fixture) not FAILED |
| `quality/tests/test_cm_reload_suppression.py::test_d3_apply_in_place_partial_apply_one_bad_value` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs); reported as ERROR (fixture) not FAILED |
| `quality/tests/test_cm_reload_suppression.py::test_d3_apply_in_place_safe_when_coordinator_missing` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs); reported as ERROR (fixture) not FAILED |
| `quality/tests/test_cm_reload_suppression.py::test_d3_apply_in_place_safe_when_manager_missing` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs); reported as ERROR (fixture) not FAILED |
| `quality/tests/test_cm_reload_suppression.py::test_d3_apply_in_place_updates_all_four_hvac_live_attrs` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs); reported as ERROR (fixture) not FAILED |
| `quality/tests/test_cm_reload_suppression.py::test_d3_clamp_invariant_holds_after_in_place_apply` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs); reported as ERROR (fixture) not FAILED |
| `quality/tests/test_cm_reload_suppression.py::test_d3_listener_handles_all_four_timers_via_reset_button` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs); reported as ERROR (fixture) not FAILED |
| `quality/tests/test_cm_reload_suppression.py::test_d3_listener_no_op_on_empty_diff` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs); reported as ERROR (fixture) not FAILED |
| `quality/tests/test_cm_reload_suppression.py::test_d3_listener_reloads_for_mixed_change` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs); reported as ERROR (fixture) not FAILED |
| `quality/tests/test_cm_reload_suppression.py::test_d3_listener_reloads_for_non_allowlisted_keys` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs); reported as ERROR (fixture) not FAILED |
| `quality/tests/test_cm_reload_suppression.py::test_d3_listener_suppresses_reload_for_allowlisted_keys` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs); reported as ERROR (fixture) not FAILED |
| `quality/tests/test_cm_reload_suppression.py::test_d3_listener_unchanged_for_room_entries` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs); reported as ERROR (fixture) not FAILED |
| `quality/tests/test_d3_area_inherit.py::test_existing_device_area_preserved` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_d3_area_inherit.py::test_fresh_device_inherits_configured_area` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_d3_area_inherit.py::test_options_overrides_data_for_area` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_deploy_scripts.py::test_v4710_trap_restores_clean_url_on_sigint` | B1/B4 | test_deploy_scripts.py:445 Failed: script did not exit after SIGINT — drives scripts/deploy.sh trap behaviour; real-or-environment, needs triage |
| `quality/tests/test_egress_face_identity_d1.py::test_resolver_fail_open_when_person_missing` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_egress_face_identity_d1.py::test_resolver_returns_fresh_name_as_canonical_slug` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_egress_face_identity_d1.py::test_resolver_returns_none_on_bad_state[]` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_egress_face_identity_d1.py::test_resolver_returns_none_on_bad_state[none]` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_egress_face_identity_d1.py::test_resolver_returns_none_on_bad_state[unavailable]` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_egress_face_identity_d1.py::test_resolver_returns_none_on_bad_state[unknown]` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_egress_face_identity_d1.py::test_resolver_returns_none_on_future_dated_face` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_egress_face_identity_d1.py::test_resolver_returns_none_when_no_face_sensor` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_egress_face_identity_d1.py::test_resolver_returns_none_when_stale` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_egress_face_identity_d1.py::test_resolver_vetoes_when_person_not_home_oracle_independent` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_energy_write_verification.py::test_c_med_1_h3_options_round_trip_source_anchor` | B1 | test_energy_write_verification.py:1717 AssertionError: kill-switch ... — behavioural assert against energy write-verify |
| `quality/tests/test_ev_offpeak_proactive.py::TestWS1PersistenceRoundTrip::test_force_charge_until_naive_datetime_does_not_crash` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_ev_offpeak_proactive.py::TestWS1PersistenceRoundTrip::test_force_charge_until_round_trip_kv` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_ev_offpeak_proactive.py::TestWS2OffpeakProactiveOn::test_force_charge_active_skips_proactive_on` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_evse_drain_precedence_session_b1.py::test_dp_enable_switch_registered_in_setup_entry` | B1 | test_evse_drain_precedence_session_b1.py:70 AssertionError: DP master ... — source-anchored registration check on the DP switch |
| `quality/tests/test_evse_drain_precedence_session_b2b_ii.py::test_must_start_by_timer_armed_on_transitioned_entry` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_exterior_cycle2.py::test_snapshot_resolver_strips_underscore_2_before_person_suffix` | B1 | raises inside custom_components/.../perimeter_alert.py — production traceback |
| `quality/tests/test_fan_recheck_observability.py::test_veto_sleep_state_counts` | B1 | test_fan_recheck_observability.py:89 AssertionError: assert None == ... — observability value never produced |
| `quality/tests/test_fan_trust_state_extension.py::TestD4_Mode2BleGate::test_comment_cross_references_planning_doc` | B2/C-62 | source-text asserts at :826/:829/:834 ('if house_state == Hou...', 'PLANNING_fan_trust_st...', 'FAN_TRUST_STATES' not in ...) — Bug Class #62 text anchors that drifted |
| `quality/tests/test_fan_trust_state_extension.py::TestD4_Mode2BleGate::test_does_not_extend_to_fan_trust_states` | B2/C-62 | source-text asserts at :826/:829/:834 ('if house_state == Hou...', 'PLANNING_fan_trust_st...', 'FAN_TRUST_STATES' not in ...) — Bug Class #62 text anchors that drifted |
| `quality/tests/test_fan_trust_state_extension.py::TestD4_Mode2BleGate::test_gate_remains_sleep_only` | B2/C-62 | source-text asserts at :826/:829/:834 ('if house_state == Hou...', 'PLANNING_fan_trust_st...', 'FAN_TRUST_STATES' not in ...) — Bug Class #62 text anchors that drifted |
| `quality/tests/test_freeze_floor.py::test_full_cycle_preset_then_preheat_final_low_floored` | B1 | raises inside custom_components/.../hvac_override.py:1xxx during the freeze-floor path — production traceback, not a test-harness error |
| `quality/tests/test_freeze_floor.py::test_override_compromise_floored_via_chokepoint` | B1 | raises inside custom_components/.../hvac_override.py:1xxx during the freeze-floor path — production traceback, not a test-harness error |
| `quality/tests/test_freeze_floor.py::test_predict_preheat_floored_via_chokepoint` | B1 | raises inside custom_components/.../hvac_override.py:1xxx during the freeze-floor path — production traceback, not a test-harness error |
| `quality/tests/test_freeze_floor.py::test_predict_preheat_no_freeze_unchanged` | B1 | raises inside custom_components/.../hvac_override.py:1xxx during the freeze-floor path — production traceback, not a test-harness error |
| `quality/tests/test_hvac_offphase_integration.py::test_stale_occupancy_short_circuit_writes_away` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_hvac_offphase_integration.py::test_vacant_past_grace_short_circuit_writes_away` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_low_cleanup.py::TestSwitchRestoreDeferredRetry::test_hvac_observation_switch_has_deferred_restore` | B2/C-62 | test_low_cleanup.py:735 assert '_deferred_restore = False' in '<class source>' — Bug Class #62 text anchor |
| `quality/tests/test_memory_compactor.py::test_actuation_conflict_rule_spot` | B4/WEDGE | tests finish (1 failed, 22 passed in 1.15s) but the pytest PROCESS NEVER EXITS when this file is run alone — reproduced twice (>600s, >180s). Only file in 425 that hangs alone. |
| `quality/tests/test_mmwave_fan_demotion.py::test_demote_when_house_state_home_day` | B1 | test_mmwave_fan_demotion.py:285/638/700/765/905 — behavioural asserts on the four D2 demotion legs return the inverted boolean; drives real code, code disagrees |
| `quality/tests/test_mmwave_fan_demotion.py::test_demotes_despite_active_interference_hold_and_clears_it` | B1 | test_mmwave_fan_demotion.py:285/638/700/765/905 — behavioural asserts on the four D2 demotion legs return the inverted boolean; drives real code, code disagrees |
| `quality/tests/test_mmwave_fan_demotion.py::test_positive_demote_sets_flap_latch` | B1 | test_mmwave_fan_demotion.py:285/638/700/765/905 — behavioural asserts on the four D2 demotion legs return the inverted boolean; drives real code, code disagrees |
| `quality/tests/test_mmwave_fan_demotion.py::test_positive_demote_uses_sustained_production_state` | B1 | test_mmwave_fan_demotion.py:285/638/700/765/905 — behavioural asserts on the four D2 demotion legs return the inverted boolean; drives real code, code disagrees |
| `quality/tests/test_mmwave_fan_demotion.py::test_studya_repro_all_legs_met_demotes` | B1 | test_mmwave_fan_demotion.py:285/638/700/765/905 — behavioural asserts on the four D2 demotion legs return the inverted boolean; drives real code, code disagrees |
| `quality/tests/test_nm_cycle_c2_fixup.py::test_repeat_path_extras_promoted_survives_mute` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_nm_cycle_c2_fixup.py::test_router_mute_exception_extras_promoted` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_nm_cycle_c_routing_matrix.py::TestC4MuteShortcut::test_mute_expiry_auto_clears` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_nm_cycle_c_routing_matrix.py::TestC4MuteShortcut::test_mute_pruned_when_past_expiry_on_restore` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_nm_image_delivery.py::TestD2ForceImmediateOverride::test_force_immediate_respects_silence_until` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_oc_pillar_b_admin_surface.py::test_kill_switch_engage_strips_pending_autonomy` | B4 | same switch.py:512 PEP-604 TypeError on python 3.9.6 |
| `quality/tests/test_oc_pillar_b_admin_surface.py::test_status_sensor_next_cycle_eta_non_negative` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_optimization_coordinator.py::test_optimizer_kill_switch_split_brain_fails_closed` | B4 | same switch.py:512 PEP-604 TypeError on python 3.9.6 |
| `quality/tests/test_part2_ec_hc_writeback.py::test_apply_in_place_dispatch_coverage` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d1_apply_in_place_routes_all_four_offpeak_quality_buckets` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d1_apply_in_place_routes_ec_setter_keys` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d1_apply_in_place_routes_offpeak_drain_to_setter` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d1_apply_in_place_safe_when_energy_missing` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d1_bayesian_marked_applied_no_live_attr` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d1_offpeak_drain_quality_mapping_complete` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d2_routine_keys_treated_as_no_live_attr[routine_event_cooldown_days]` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d2_routine_keys_treated_as_no_live_attr[routine_event_min_severity]` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d2_routine_keys_treated_as_no_live_attr[routine_regime_baseline_window_days]` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d2_routine_keys_treated_as_no_live_attr[routine_regime_recent_window_days]` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d3_apply_in_place_routes_hvac_tunable_keys[hvac_ac_detection_time_gate-_override_arrester-_detection_time_gate_min-15-True]` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d3_apply_in_place_routes_hvac_tunable_keys[hvac_ac_hard_reset_daily_limit-_override_arrester-_hard_reset_daily_limit-3-True]` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d3_apply_in_place_routes_hvac_tunable_keys[hvac_ac_hard_reset_min_interval-_override_arrester-_hard_reset_min_interval_min-120-True]` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d3_apply_in_place_routes_hvac_tunable_keys[hvac_ac_nudge_duration-_override_arrester-_nudge_duration_min-7-True]` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d3_apply_in_place_routes_hvac_tunable_keys[hvac_ac_nudge_eval_delay-_override_arrester-_nudge_eval_delay_s-900-True]` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d3_apply_in_place_routes_hvac_tunable_keys[hvac_ac_nudge_size-_override_arrester-_nudge_size_f-2.0-False]` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d3_apply_in_place_routes_hvac_tunable_keys[hvac_ac_sustained_samples-_override_arrester-_sustained_samples-4-True]` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d3_apply_in_place_routes_hvac_tunable_keys[hvac_cover_close_temp-_cover_controller-_cover_close_temp-84-False]` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d3_apply_in_place_routes_hvac_tunable_keys[hvac_cover_open_temp-_cover_controller-_cover_open_temp-76-False]` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d3_apply_in_place_routes_hvac_tunable_keys[hvac_cover_override_hours-_cover_controller-_cover_override_hours-5.0-False]` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d3_apply_in_place_routes_hvac_tunable_keys[hvac_fan_activation_delta-_fan_controller-_activation_delta-1.5-False]` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d3_apply_in_place_routes_hvac_tunable_keys[hvac_fan_hysteresis-_fan_controller-_deactivation_delta-2.0-False]` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d3_apply_in_place_routes_hvac_tunable_keys[hvac_occupied_cover_close_delta-_cover_controller-_occupied_close_delta-2.5-False]` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d3_apply_in_place_routes_hvac_tunable_keys[hvac_solar_bank_floor-_predictor-_solar_bank_floor-68-False]` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d3_apply_in_place_safe_when_hvac_sub_controller_missing` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d3_hvac_tunable_dispatch_cast_correct_int_vs_float` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d3_hvac_tunable_dispatch_table_covers_all_14_factory_outputs` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d5_dpm_hysteresis_treated_as_no_live_attr` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d5_egress_resume_delay_dispatch_calls_setter` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d5_egress_threshold_dispatch_calls_setter` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_d5_fan_interference_hold_dispatch_calls_setter` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_listener_still_reloads_for_mixed_change_with_part2_key` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_listener_suppresses_reload_for_hvac_tunable_change` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_listener_suppresses_reload_for_part2_only_change` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_options_reload_suppress_keys_count_matches_part2_scope` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_options_reload_suppress_keys_membership_exact` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_part2_ec_hc_writeback.py::test_part2_retrofit_does_not_break_v4_7_25_keys` | B2 | quality/tests/_ast_slice_guard.py:80 RuntimeError: AST-slice namespace missing symbols ['_CONF_CHATTER_*' ...] — loader keep-set stale after the v5.85.0 chatter cycle added CONF_CHATTER_* consts |
| `quality/tests/test_perimeter_alert_nm_routing.py::test_snapshot_id_ttl_expires` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_reload_watchdog_hazard.py::test_camera_person_entities_change_dispatches_transit_signal_once` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs) |
| `quality/tests/test_reload_watchdog_hazard.py::test_dispatch_call_site_is_load_bearing_for_transit_signal_dispatch` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs) |
| `quality/tests/test_reload_watchdog_hazard.py::test_egress_perimeter_keys_not_in_allowlist_v1` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs) |
| `quality/tests/test_reload_watchdog_hazard.py::test_integration_key_signal_table_uses_transit_config_changed_const` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs) |
| `quality/tests/test_reload_watchdog_hazard.py::test_integration_options_mixed_falls_through_to_reload` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs) |
| `quality/tests/test_reload_watchdog_hazard.py::test_integration_options_suppress_reload_on_camera_person_entities` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs) |
| `quality/tests/test_reload_watchdog_hazard.py::test_kill_switch_disables_suppress_and_skips_dispatch` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs) |
| `quality/tests/test_reload_watchdog_hazard.py::test_seed_helper_populates_snapshot_from_entry_options` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs) |
| `quality/tests/test_reload_watchdog_hazard.py::test_seed_helper_when_invoked_makes_first_save_suppress_reload` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs) |
| `quality/tests/test_reload_watchdog_hazard.py::test_wiring_table_entry_is_load_bearing_for_transit_signal_dispatch` | B2 | same _ast_slice_guard.py:80 RuntimeError (missing _CONF_CHATTER_* stubs) |
| `quality/tests/test_room_rename_writethrough.py::TestD1ZoneRenameWriteThrough::test_zone_rename_create_branch_updates_data` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_room_rename_writethrough.py::TestD1ZoneRenameWriteThrough::test_zone_rename_update_branch_updates_data` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_runtime_smoke.py::test_database_init_creates_v4511_tables` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_runtime_smoke.py::test_switch_platform_setup_does_not_raise` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_v4511_ac_energy_aware_ramp_down.py::TestImportResolution::test_button_imports_resolve` | B1 | test_v4511_ac_energy_aware_ramp_down.py:1332 AssertionError: button ... — import-resolution assert on the button surface |
| `quality/tests/test_v462_d3_away_typical.py::test_staleness_number_default_14` | B1 | test_v462_d3_away_typical.py:158 AssertionError: BayesianCellStaleness... default value |
| `quality/tests/test_v467_anomaly_log_null_relaxation.py::test_v467_null_metric_row_persists_and_round_trips` | B4 | :158/:207 sqlite3.ProgrammingError — cross-thread/closed-connection use in the test's own sqlite handling |
| `quality/tests/test_v467_anomaly_log_null_relaxation.py::test_v467_real_metric_values_still_round_trip` | B4 | :158/:207 sqlite3.ProgrammingError — cross-thread/closed-connection use in the test's own sqlite handling |
| `quality/tests/test_v4715_universalize_veto.py::TestD3InferenceOrchestration::test_guest_exit_fires_after_sustained_quiet` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_v4715_universalize_veto.py::TestD3InferenceOrchestration::test_waking_sustained_signal_persists_across_cycles` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_v472_dpm_surfaces.py::TestD2HvacDynamicPresetSwitch::test_ec_dynamic_preset_switch_not_in_setup_entry` | B2/C-62 | test_v472_dpm_surfaces.py:261 AssertionError: async_setup_entry must ... — structural/source assert |
| `quality/tests/test_v475_d3_canonical_runtime_only.py::test_v475_d3_canonical_callers_all_in_allowlist` | B2/C-62 | test_v475_d3_canonical_runtime_only.py:129 AssertionError: v4.7.5 D3 canonical-callers source assert |
| `quality/tests/test_v47x_dynamic_preset.py::TestGetZoneState::test_dwell_remaining_decreases` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_v47x_dynamic_preset.py::TestWinterGateCalendarBoundary::test_dec_is_winter` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_v47x_dynamic_preset.py::TestWinterGateCalendarBoundary::test_feb_is_winter` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_v47x_dynamic_preset.py::TestWinterGateCalendarBoundary::test_jan_is_winter` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_v47x_dynamic_preset.py::TestWinterGateCalendarBoundary::test_nov_1_is_winter` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_v47x_dynamic_preset.py::TestWinterGateIndependentOfPM::test_winter_gate_fires_with_no_coordinator_manager` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_v47x_ev_tou_hardening.py::TestD2SubSwitchRestoreAfterDelayedECInit::test_handle_ec_ready_noop_when_restore_not_pending` | B4 | custom_components/.../switch.py:512 TypeError: unsupported operand type(s) for |: 'type' and 'NoneType' — PEP-604 `str | None` evaluated at class-body time; host python is 3.9.6, no `from __future__ import annotations` in switch.py |
| `quality/tests/test_v47x_ev_tou_hardening.py::TestD2SubSwitchRestoreAfterDelayedECInit::test_no_untracked_tasks_from_retry_chain` | B4 | custom_components/.../switch.py:512 TypeError: unsupported operand type(s) for |: 'type' and 'NoneType' — PEP-604 `str | None` evaluated at class-body time; host python is 3.9.6, no `from __future__ import annotations` in switch.py |
| `quality/tests/test_v47x_ev_tou_hardening.py::TestD2SubSwitchRestoreAfterDelayedECInit::test_sub_switch_state_restore_after_delayed_ec_init` | B4 | custom_components/.../switch.py:512 TypeError: unsupported operand type(s) for |: 'type' and 'NoneType' — PEP-604 `str | None` evaluated at class-body time; host python is 3.9.6, no `from __future__ import annotations` in switch.py |
| `quality/tests/test_v47x_ev_tou_hardening.py::TestD2SubSwitchRestoreAfterDelayedECInit::test_sub_switch_state_restore_after_restart_mid_incident` | B4 | custom_components/.../switch.py:512 TypeError: unsupported operand type(s) for |: 'type' and 'NoneType' — PEP-604 `str | None` evaluated at class-body time; host python is 3.9.6, no `from __future__ import annotations` in switch.py |
| `quality/tests/test_v47x_ev_tou_hardening.py::TestFixupB1HassDataOrdering::test_handle_ec_ready_succeeds_when_coordinator_registered` | B4 | custom_components/.../switch.py:512 TypeError: unsupported operand type(s) for |: 'type' and 'NoneType' — PEP-604 `str | None` evaluated at class-body time; host python is 3.9.6, no `from __future__ import annotations` in switch.py |
| `quality/tests/test_v47x_weather_manager.py::TestProviderHealth::test_stale_entity` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_v4_7_17_2_dpm_simplified_frame.py::TestConfigFlowSurface::test_new_knobs_added_to_schema` | B2/C-62 | :321 assert 'vol.Range(min=0. ...' in schema source — Bug Class #62 text anchor (also ModuleNotFoundError on __init__.py:22 alone) |
| `quality/tests/test_v4_7_18_dpm_drift_guard.py::TestCounterRestartResilience::test_restore_handles_naive_datetime` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_v4_7_18_dpm_drift_guard.py::TestCounterRestartResilience::test_restore_rehydrates_counter` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_v5110_optimizer_hardening.py::TestD9WriteVolumeTripwire::test_rolling_window_evicts_old_timestamps` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_v5_7_1_energy_precool.py::TestD5Migration::test_restore_entity_off_overrides_options_true` | B3 | passes when its file is run alone; fails only in the full suite |
| `quality/tests/test_zzz_v318_hvac_sensors.py::TestZoneStatePersistence::test_restore_skips_stale_data` | B3 | passes when its file is run alone; fails only in the full suite |
