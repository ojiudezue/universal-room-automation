# D2 — Per-file alone-vs-suite delta (order-pollution map)

Every one of the **425** files under `quality/tests/` was run ALONE with `PYTHONDONTWRITEBYTECODE=1`,
`__pycache__` scrubbed, `-p no:cacheprovider`, 90 s per-file cap. In-suite counts come from the
prior-session full-suite capture (`develop_full.txt`). `delta = in_suite_fail - alone_fail`.

## Headline numbers

| quantity | value |
|---|---|
| test files swept alone | 425 |
| files where SUITE is worse than ALONE (pollution victims) | 20 |
| failures explained by pollution (sum of positive deltas) | 59 |
| baseline ids that PASS when their file runs alone | 60 |
| files where ALONE is worse than SUITE (reverse pollution) | 21 |
| failures that exist ONLY alone (sum of negative deltas) | 49 |
| files that HANG when run alone | 1 |

## The seed observation did NOT reproduce

The brief seeds `test_ac_ramp_pipeline_hardening.py` as "71/71 alone, 11 failed in suite".
Measured: **71/71 alone (confirmed)** — and **0 failures in suite**. The file appears in NONE of the
eight captured full-suite runs' failing sets (`grep -c ac_ramp_pipeline_hardening` = 0 in all eight).
The alone half of the seed reproduces exactly; the in-suite half does not exist in any captured run.
Either it was observed on an uncaptured run, or it has since been fixed. Per the plan's own
discriminator, D2 therefore proceeds on the 20 victims that DO reproduce, and the ac_ramp donor
hypothesis (async_call_later / dt_util.now replacement leakage) is **not confirmed by this data**.

## Donor mechanism — what the data DOES support

The dominant cross-file contamination surface in this suite is **`sys.modules` package stubbing**, not
`async_call_later` / `dt_util.now` monkeypatching. Measured (see D6):

- **95 sites in 49 files** assign `__path__ = []` to a stub module; **18 of those target process-global
  names** (`homeassistant`, `homeassistant.helpers`, `homeassistant.util`, `homeassistant.components`).
- **85 sites in 67 files** later read `<mod>.__path__[0]`.
- **33 of those reads in 18 files** repair the stub on PRESENCE (`if x is None` / `not hasattr(x,"__path__")`)
  rather than on CONTENT, so an already-present-but-emptied stub is trusted and `[0]` raises.

The repo already documents this mechanism in its own source: `test_hvac_vacancy_sweep_manual_on_guard.py:186`
carries the comment *"otherwise sibling test files that do `_ura.__path__[0]` will trip."*

## Named donors (files that empty a process-global `homeassistant*` `__path__`)

These are the files whose mere import mutates state every later file reads:

```
test_fan_recheck_deferred_surfaces.py:48   sys.modules["homeassistant"].__path__ = []
test_fan_recheck_mode2_cycle.py:56         sys.modules["homeassistant"].__path__ = []
test_freeze_floor.py:75,83,106,565         homeassistant / .helpers / .util / .components
test_heatcool_enforcer.py:60,68,91         homeassistant / .helpers / .util
test_hvac_offphase_integration.py:64,72,95 homeassistant / .helpers / .util
test_v4513_1_zone_dedup.py:76              sys.modules["homeassistant"].__path__ = []
test_v4513_gap_fixes.py:205                sys.modules["homeassistant"].__path__ = []
test_v4514_anomaly_visibility.py:65        sys.modules["homeassistant"].__path__ = []
test_v4519_transition_detector_teardown.py:235,248  homeassistant / .util
test_v478_egress_window.py:63              sys.modules["homeassistant"].__path__ = []
```
Note the symmetry with the reverse-pollution column below: `test_v4513_gap_fixes.py` (-9),
`test_v4514_anomaly_visibility.py` (-5), `test_freeze_floor.py`, `test_hvac_offphase_integration.py`
appear as BOTH donors and alone-only-failers — they emit stubs AND depend on siblings' stubs.

## DONOR ISOLATED — the mechanism is collection-order, not execution-order

The ten hand-picked donor candidates above produced **zero** victim failures across 50 two-file
selections. That is not because the leak is diffuse — it is because donor/victim status is decided by
ALPHABETICAL COLLECTION ORDER, and an arbitrary pair almost never lands in the right order.

An alphabetical-prefix bisect on the largest victim isolated a single file:

```
VICTIM  quality/tests/test_chatter_detector.py     (15 baseline failures)
PREFIX  43 files up to and incl. the victim   -> 15 victim failures
bisect  21 -> 10 -> 5 -> 2 -> 1
CULPRIT quality/tests/test_ac_ramp_master_option_persistence.py
```

Confirmed as a two-file selection (donor first), reproducing all 15:

```
ModuleNotFoundError: No module named 'homeassistant.helpers.entity_registry';
                     'homeassistant.helpers' is not a package
TypeError: 'NoneType' object is not callable
```

Guilty block, `quality/tests/test_ac_ramp_master_option_persistence.py:47-75`:

```python
_mods = {
    "homeassistant.helpers": {},                                   # no __path__ -> not a package
    "homeassistant.helpers.event": {
        "async_call_later": MagicMock(return_value=lambda: None),  # the seeded leak, verbatim
        "async_track_state_change_event": MagicMock(return_value=lambda: None),
    },
    ...
}
for _n, _a in _mods.items():
    sys.modules.setdefault(_n, _mock_module(_n, **_a))             # line 75 - process-global
```

Two leaks from one block, and the second one **is** the mechanism the brief seeded
(`async_call_later` replaced by a callable mock) — found one file over from where it was expected.

Why the naive drill missed it:

- `sys.modules.setdefault(...)` runs at **module import**, i.e. during COLLECTION. Pytest imports every
  selected file before running any test, so contamination is fixed by collection order (alphabetical),
  independent of test execution order.
- `setdefault` means **first writer wins**. Donor-vs-victim is purely a function of alphabetical
  position within the selection.

**Not every victim has a single donor.** The same bisect on `test_egress_face_identity_d1.py`
(10 failures) reproduced from the alphabetical prefix but narrowed to **11 files with no single
half reproducing** — that victim needs >= 2 cooperating donors. So both of the plan's discriminating
outcomes occur, on different victims: sometimes one file, sometimes a cooperating set.

## Pollution victims (delta > 0)

| file | alone_fail | in_suite_fail | delta |
|---|---|---|---|
| `quality/tests/test_chatter_detector.py` | 0 | 15 | +15 |
| `quality/tests/test_egress_face_identity_d1.py` | 0 | 10 | +10 |
| `quality/tests/test_v47x_dynamic_preset.py` | 0 | 6 | +6 |
| `quality/tests/test_d3_area_inherit.py` | 0 | 3 | +3 |
| `quality/tests/test_ev_offpeak_proactive.py` | 0 | 3 | +3 |
| `quality/tests/test_hvac_offphase_integration.py` | 0 | 2 | +2 |
| `quality/tests/test_nm_cycle_c2_fixup.py` | 0 | 2 | +2 |
| `quality/tests/test_nm_cycle_c_routing_matrix.py` | 0 | 2 | +2 |
| `quality/tests/test_room_rename_writethrough.py` | 0 | 2 | +2 |
| `quality/tests/test_runtime_smoke.py` | 0 | 2 | +2 |
| `quality/tests/test_v4715_universalize_veto.py` | 0 | 2 | +2 |
| `quality/tests/test_v4_7_18_dpm_drift_guard.py` | 0 | 2 | +2 |
| `quality/tests/test_chatter_d7_shadow_act.py` | 0 | 1 | +1 |
| `quality/tests/test_evse_drain_precedence_session_b2b_ii.py` | 0 | 1 | +1 |
| `quality/tests/test_nm_image_delivery.py` | 0 | 1 | +1 |
| `quality/tests/test_oc_pillar_b_admin_surface.py` | 1 | 2 | +1 |
| `quality/tests/test_perimeter_alert_nm_routing.py` | 0 | 1 | +1 |
| `quality/tests/test_v5110_optimizer_hardening.py` | 0 | 1 | +1 |
| `quality/tests/test_v5_7_1_energy_precool.py` | 0 | 1 | +1 |
| `quality/tests/test_zzz_v318_hvac_sensors.py` | 0 | 1 | +1 |

## Reverse pollution — files that FAIL alone but PASS in the suite (delta < 0)

This class is not in the plan's model. These tests are only green because a sibling ran first and left
a stub behind. They are as fragile as the B3 population, in the opposite direction, and they are invisible
to the 158 baseline entirely.

| file | alone_fail | in_suite_fail | delta | alone summary |
|---|---|---|---|---|
| `quality/tests/test_v4513_gap_fixes.py` | 9 | 0 | -9 | 9 failed, 17 passed in 4.35s |
| `quality/tests/test_perimeter_burst_demotion.py` | 8 | 0 | -8 | 8 failed, 3 passed in 0.21s |
| `quality/tests/test_data_pipeline.py` | 7 | 0 | -7 | 7 failed, 8 passed in 0.28s |
| `quality/tests/test_v4514_anomaly_visibility.py` | 5 | 0 | -5 | 5 failed, 6 passed in 0.50s |
| `quality/tests/test_fan_recheck_deferred_surfaces.py` | 2 | 0 | -2 | 2 failed, 13 passed in 0.12s |
| `quality/tests/test_v4_7_17_2_dpm_simplified_frame.py` | 3 | 1 | -2 | 3 failed, 41 passed in 0.20s |
| `quality/tests/test_v5_37_1_clear_sensor_fields.py` | 2 | 0 | -2 | 2 failed, 4 passed in 0.35s |
| `quality/tests/test_arriving_rearm_cooldown.py` | 1 | 0 | -1 | 1 failed, 13 passed in 0.20s |
| `quality/tests/test_bathroom_exhaust_intelligence_cycle.py` | 1 | 0 | -1 | 1 error in 0.15s |
| `quality/tests/test_coordinator_diagnostics.py` | 1 | 0 | -1 | 1 error in 0.12s |
| `quality/tests/test_cover_verify.py` | 1 | 0 | -1 | 1 error in 0.12s |
| `quality/tests/test_domain_coordinators.py` | 1 | 0 | -1 | 1 error in 0.12s |
| `quality/tests/test_fan_manual_off_cooldown_room_tier.py` | 1 | 0 | -1 | 1 error in 0.10s |
| `quality/tests/test_hvac_fan_control.py` | 1 | 0 | -1 | 1 error in 0.08s |
| `quality/tests/test_override_arrester_ttl_suppression.py` | 1 | 0 | -1 | 1 error in 0.15s |
| `quality/tests/test_snap1_at_detection_snapshots.py` | 1 | 0 | -1 | 1 failed, 25 passed in 2.55s |
| `quality/tests/test_v4621_humidity_fan_hardening.py` | 1 | 0 | -1 | 1 error in 0.10s |
| `quality/tests/test_v4623_humidity_fan_behavioral.py` | 1 | 0 | -1 | 1 error in 0.10s |
| `quality/tests/test_v4713_sleep_state_zone_presence_trust.py` | 1 | 0 | -1 | 1 error in 0.10s |
| `quality/tests/test_z_sysmodules_probe_A.py` | 1 | 0 | -1 | 1 failed in 0.02s |
| `quality/tests/test_z_sysmodules_probe_B.py` | 1 | 0 | -1 | 1 failed in 0.02s |

## Files failing identically alone and in suite (delta == 0, in_suite_fail > 0)

| file | failures (both) |
|---|---|
| `quality/tests/test_part2_ec_hc_writeback.py` | 38 |
| `quality/tests/test_cm_reload_suppression.py` | 17 |
| `quality/tests/test_reload_watchdog_hazard.py` | 10 |
| `quality/tests/test_mmwave_fan_demotion.py` | 5 |
| `quality/tests/test_v47x_ev_tou_hardening.py` | 5 |
| `quality/tests/test_freeze_floor.py` | 4 |
| `quality/tests/test_fan_trust_state_extension.py` | 3 |
| `quality/tests/test_v467_anomaly_log_null_relaxation.py` | 2 |
| `quality/tests/test_deploy_scripts.py` | 1 |
| `quality/tests/test_energy_write_verification.py` | 1 |
| `quality/tests/test_evse_drain_precedence_session_b1.py` | 1 |
| `quality/tests/test_exterior_cycle2.py` | 1 |
| `quality/tests/test_fan_recheck_observability.py` | 1 |
| `quality/tests/test_low_cleanup.py` | 1 |
| `quality/tests/test_memory_compactor.py` | 1 |
| `quality/tests/test_optimization_coordinator.py` | 1 |
| `quality/tests/test_v4511_ac_energy_aware_ramp_down.py` | 1 |
| `quality/tests/test_v462_d3_away_typical.py` | 1 |
| `quality/tests/test_v472_dpm_surfaces.py` | 1 |
| `quality/tests/test_v475_d3_canonical_runtime_only.py` | 1 |
| `quality/tests/test_v47x_weather_manager.py` | 1 |

## Full per-file table (all 425 files)

| file | alone_fail | alone_pass | in_suite_fail | delta | hung |
|---|---|---|---|---|---|
| `quality/tests/perimeter/test_circling_diag_sensor.py` | 0 | 8 | 0 | +0 |  |
| `quality/tests/perimeter/test_circling_founding_case.py` | 0 | 5 | 0 | +0 |  |
| `quality/tests/perimeter/test_circling_founding_case_transition.py` | 0 | 6 | 0 | +0 |  |
| `quality/tests/perimeter/test_circling_label_transition.py` | 0 | 18 | 0 | +0 |  |
| `quality/tests/perimeter/test_circling_severity_per_state.py` | 0 | 27 | 0 | +0 |  |
| `quality/tests/test_ac_ramp_master_option_persistence.py` | 0 | 8 | 0 | +0 |  |
| `quality/tests/test_ac_ramp_pipeline_hardening.py` | 0 | 71 | 0 | +0 |  |
| `quality/tests/test_activity_logger.py` | 0 | 19 | 0 | +0 |  |
| `quality/tests/test_aggregation.py` | 0 | 27 | 0 | +0 |  |
| `quality/tests/test_ai_automation.py` | 0 | 46 | 0 | +0 |  |
| `quality/tests/test_arbitrage_chunk_latch_persistence.py` | 0 | 6 | 0 | +0 |  |
| `quality/tests/test_arbitrage_completed_chunk_hold_precedence.py` | 0 | 5 | 0 | +0 |  |
| `quality/tests/test_arbitrage_grid_import_guard_expose.py` | 0 | 24 | 0 | +0 |  |
| `quality/tests/test_arbitrage_reason_map_invariant.py` | 0 | 4 | 0 | +0 |  |
| `quality/tests/test_arbitrage_rung_gate_observability.py` | 0 | 8 | 0 | +0 |  |
| `quality/tests/test_arbitrage_solar_attainability_ladder.py` | 0 | 43 | 0 | +0 |  |
| `quality/tests/test_arrester_comfort_delay.py` | 0 | 50 | 0 | +0 |  |
| `quality/tests/test_arrester_operator_immunity.py` | 0 | 60 | 0 | +0 |  |
| `quality/tests/test_arrester_override_expiry_notify.py` | 0 | 8 | 0 | +0 |  |
| `quality/tests/test_arrester_teardown_and_engage.py` | 0 | 3 | 0 | +0 |  |
| `quality/tests/test_arriving_rearm_cooldown.py` | 1 | 13 | 0 | -1 |  |
| `quality/tests/test_attain_hold_reason_wording.py` | 0 | 3 | 0 | +0 |  |
| `quality/tests/test_attainability_branch.py` | 0 | 56 | 0 | +0 |  |
| `quality/tests/test_automation_chaining.py` | 0 | 49 | 0 | +0 |  |
| `quality/tests/test_automations.py` | 0 | 40 | 0 | +0 |  |
| `quality/tests/test_b4_energy_integration.py` | 0 | 30 | 0 | +0 |  |
| `quality/tests/test_b4_live_health.py` | 0 | 17 | 0 | +0 |  |
| `quality/tests/test_baec_config_flow_round_trip.py` | 0 | 7 | 0 | +0 |  |
| `quality/tests/test_baec_shadow_eval.py` | 0 | 6 | 0 | +0 |  |
| `quality/tests/test_bathroom_exhaust_intelligence_cycle.py` | 1 | 0 | 0 | -1 |  |
| `quality/tests/test_battery_inclement_arbitrage_floor.py` | 0 | 25 | 0 | +0 |  |
| `quality/tests/test_battery_inclement_precedence.py` | 0 | 21 | 0 | +0 |  |
| `quality/tests/test_bayesian_b2_prediction_sensors.py` | 0 | 45 | 0 | +0 |  |
| `quality/tests/test_bayesian_predictor.py` | 0 | 55 | 0 | +0 |  |
| `quality/tests/test_ble_extend_not_create.py` | 0 | 22 | 0 | +0 |  |
| `quality/tests/test_blind_window_evse_guard.py` | 0 | 94 | 0 | +0 |  |
| `quality/tests/test_boot_settle_gate.py` | 0 | 27 | 0 | +0 |  |
| `quality/tests/test_camera_census.py` | 0 | 51 | 0 | +0 |  |
| `quality/tests/test_camera_resolver.py` | 0 | 43 | 0 | +0 |  |
| `quality/tests/test_census_accuracy_d1_d2.py` | 0 | 19 | 0 | +0 |  |
| `quality/tests/test_census_ble_cancel_unrecognized.py` | 0 | 36 | 0 | +0 |  |
| `quality/tests/test_census_device_switches.py` | 0 | 21 | 0 | +0 |  |
| `quality/tests/test_census_fusion_policy.py` | 0 | 12 | 0 | +0 |  |
| `quality/tests/test_census_overcount_v5_9_0.py` | 0 | 17 | 0 | +0 |  |
| `quality/tests/test_census_suffix_disambiguation.py` | 0 | 4 | 0 | +0 |  |
| `quality/tests/test_census_v2.py` | 0 | 98 | 0 | +0 |  |
| `quality/tests/test_chatter_d7_shadow_act.py` | 0 | 9 | 1 | +1 |  |
| `quality/tests/test_chatter_detector.py` | 0 | 18 | 15 | +15 |  |
| `quality/tests/test_chatter_tick_helper.py` | 0 | 7 | 0 | +0 |  |
| `quality/tests/test_chatter_wire_in.py` | 0 | 25 | 0 | +0 |  |
| `quality/tests/test_cloud_reliance_d2.py` | 0 | 21 | 0 | +0 |  |
| `quality/tests/test_cm_reload_suppression.py` | 17 | 14 | 17 | +0 |  |
| `quality/tests/test_comfort_fan_away_veto.py` | 0 | 25 | 0 | +0 |  |
| `quality/tests/test_comfort_fan_away_veto_behavioral.py` | 0 | 17 | 0 | +0 |  |
| `quality/tests/test_compliance_sensor_async_cache.py` | 0 | 8 | 0 | +0 |  |
| `quality/tests/test_consol1_contextual_severity_and_migration.py` | 0 | 37 | 0 | +0 |  |
| `quality/tests/test_consol1_perimeter_enrichment.py` | 0 | 14 | 0 | +0 |  |
| `quality/tests/test_consol1_tripwire_and_button.py` | 0 | 6 | 0 | +0 |  |
| `quality/tests/test_consol1_wire_in_anchors.py` | 0 | 7 | 0 | +0 |  |
| `quality/tests/test_coordinator_diagnostics.py` | 1 | 0 | 0 | -1 |  |
| `quality/tests/test_cover_verify.py` | 1 | 0 | 0 | -1 |  |
| `quality/tests/test_coverage_delta_tier_semantics.py` | 0 | 13 | 0 | +0 |  |
| `quality/tests/test_coverage_rating_bounds.py` | 0 | 0 | 0 | +0 |  |
| `quality/tests/test_cycle4_slim.py` | 0 | 95 | 0 | +0 |  |
| `quality/tests/test_cycle_a_room_resilience.py` | 0 | 66 | 0 | +0 |  |
| `quality/tests/test_cycle_b_config_flow.py` | 0 | 31 | 0 | +0 |  |
| `quality/tests/test_cycle_c_stub_cleanup.py` | 0 | 24 | 0 | +0 |  |
| `quality/tests/test_cycle_d_coordinator_hardening.py` | 0 | 44 | 0 | +0 |  |
| `quality/tests/test_cycle_e_observability.py` | 0 | 76 | 0 | +0 |  |
| `quality/tests/test_cycle_f_signal_wiring.py` | 0 | 69 | 0 | +0 |  |
| `quality/tests/test_d3_area_inherit.py` | 0 | 1 | 3 | +3 |  |
| `quality/tests/test_d3_registry_resolution_behaviour.py` | 0 | 5 | 0 | +0 |  |
| `quality/tests/test_d6_confidence_check.py` | 0 | 33 | 0 | +0 |  |
| `quality/tests/test_data_pipeline.py` | 7 | 8 | 0 | -7 |  |
| `quality/tests/test_database_resilience.py` | 0 | 16 | 0 | +0 |  |
| `quality/tests/test_day_boundary_tou.py` | 0 | 17 | 0 | +0 |  |
| `quality/tests/test_db_incremental_vacuum.py` | 0 | 21 | 0 | +0 |  |
| `quality/tests/test_db_write_ready_lossless_timeout.py` | 0 | 7 | 0 | +0 |  |
| `quality/tests/test_db_write_worker_boot_race.py` | 0 | 2 | 0 | +0 |  |
| `quality/tests/test_dead_energy_sensor_observability.py` | 0 | 8 | 0 | +0 |  |
| `quality/tests/test_deploy_scripts.py` | 1 | 11 | 1 | +0 |  |
| `quality/tests/test_domain_coordinators.py` | 1 | 0 | 0 | -1 |  |
| `quality/tests/test_dp_observability_1.py` | 0 | 17 | 0 | +0 |  |
| `quality/tests/test_dp_reason_null_1.py` | 0 | 2 | 0 | +0 |  |
| `quality/tests/test_dp_yields_to_excess_solar.py` | 0 | 28 | 0 | +0 |  |
| `quality/tests/test_dpm_cleanup_and_labels.py` | 0 | 51 | 0 | +0 |  |
| `quality/tests/test_egress_camera_dead_config.py` | 0 | 8 | 0 | +0 |  |
| `quality/tests/test_egress_face_identity_d1.py` | 0 | 29 | 10 | +10 |  |
| `quality/tests/test_energy_battery.py` | 0 | 166 | 0 | +0 |  |
| `quality/tests/test_energy_behavioral_write_verify.py` | 0 | 34 | 0 | +0 |  |
| `quality/tests/test_energy_consumption.py` | 0 | 36 | 0 | +0 |  |
| `quality/tests/test_energy_drain_precedence_state_machine.py` | 0 | 29 | 0 | +0 |  |
| `quality/tests/test_energy_evse.py` | 0 | 18 | 0 | +0 |  |
| `quality/tests/test_energy_load_shedding_correctness.py` | 0 | 27 | 0 | +0 |  |
| `quality/tests/test_energy_module_import_smoke.py` | 0 | 2 | 0 | +0 |  |
| `quality/tests/test_energy_pause_release_hygiene.py` | 0 | 29 | 0 | +0 |  |
| `quality/tests/test_energy_pool_drain.py` | 0 | 12 | 0 | +0 |  |
| `quality/tests/test_energy_pool_drain_release.py` | 0 | 43 | 0 | +0 |  |
| `quality/tests/test_energy_pool_fill_priority.py` | 0 | 8 | 0 | +0 |  |
| `quality/tests/test_energy_projector_grep_singleton.py` | 0 | 9 | 0 | +0 |  |
| `quality/tests/test_energy_projector_parity.py` | 0 | 9 | 0 | +0 |  |
| `quality/tests/test_energy_restart_resilience.py` | 0 | 24 | 0 | +0 |  |
| `quality/tests/test_energy_savings_unification.py` | 0 | 17 | 0 | +0 |  |
| `quality/tests/test_energy_tou.py` | 0 | 30 | 0 | +0 |  |
| `quality/tests/test_energy_unit_normalization.py` | 0 | 46 | 0 | +0 |  |
| `quality/tests/test_energy_write_verification.py` | 1 | 98 | 1 | +0 |  |
| `quality/tests/test_envoy_auto_derive.py` | 0 | 22 | 0 | +0 |  |
| `quality/tests/test_envoy_boot_decoupling.py` | 0 | 23 | 0 | +0 |  |
| `quality/tests/test_ev_grid_cap.py` | 0 | 7 | 0 | +0 |  |
| `quality/tests/test_ev_offpeak_proactive.py` | 0 | 32 | 3 | +3 |  |
| `quality/tests/test_evse_drain_precedence_session_b1.py` | 1 | 19 | 1 | +0 |  |
| `quality/tests/test_evse_drain_precedence_session_b2a.py` | 0 | 35 | 0 | +0 |  |
| `quality/tests/test_evse_drain_precedence_session_b2b_i.py` | 0 | 12 | 0 | +0 |  |
| `quality/tests/test_evse_drain_precedence_session_b2b_ii.py` | 0 | 17 | 1 | +1 |  |
| `quality/tests/test_evse_drain_precedence_session_b2b_iii.py` | 0 | 7 | 0 | +0 |  |
| `quality/tests/test_evse_drain_precedence_session_b2c1_fixup.py` | 0 | 20 | 0 | +0 |  |
| `quality/tests/test_evse_drain_precedence_session_b2c2_fixup.py` | 0 | 11 | 0 | +0 |  |
| `quality/tests/test_evse_drain_precedence_session_b2c3_fixup.py` | 0 | 6 | 0 | +0 |  |
| `quality/tests/test_evse_offpeak_fill_release.py` | 0 | 25 | 0 | +0 |  |
| `quality/tests/test_evse_solar_aware_ux.py` | 0 | 59 | 0 | +0 |  |
| `quality/tests/test_exterior_cycle2.py` | 1 | 22 | 1 | +0 |  |
| `quality/tests/test_exterior_track_linker.py` | 0 | 27 | 0 | +0 |  |
| `quality/tests/test_face_cross_check_behavioral.py` | 0 | 3 | 0 | +0 |  |
| `quality/tests/test_face_resolver_migrate.py` | 0 | 4 | 0 | +0 |  |
| `quality/tests/test_fan_adjacency_audit.py` | 0 | 1 | 0 | +0 |  |
| `quality/tests/test_fan_adjacency_reverse_scan.py` | 0 | 3 | 0 | +0 |  |
| `quality/tests/test_fan_control_v318.py` | 0 | 49 | 0 | +0 |  |
| `quality/tests/test_fan_humidity_toggle_symmetry.py` | 0 | 7 | 0 | +0 |  |
| `quality/tests/test_fan_incident_2026_08_01_replay.py` | 0 | 10 | 0 | +0 |  |
| `quality/tests/test_fan_interference_gate_layer1.py` | 0 | 22 | 0 | +0 |  |
| `quality/tests/test_fan_layer_2_b_low_1_orphan_sweep.py` | 0 | 6 | 0 | +0 |  |
| `quality/tests/test_fan_layer_2_d1.py` | 0 | 15 | 0 | +0 |  |
| `quality/tests/test_fan_layer_2_d2_fixup.py` | 0 | 20 | 0 | +0 |  |
| `quality/tests/test_fan_layer_2_uniqueness_gate.py` | 0 | 5 | 0 | +0 |  |
| `quality/tests/test_fan_manual_off_cooldown_room_tier.py` | 1 | 0 | 0 | -1 |  |
| `quality/tests/test_fan_manual_on_hold_hvac_tier.py` | 0 | 13 | 0 | +0 |  |
| `quality/tests/test_fan_manual_on_hold_room_tier.py` | 0 | 13 | 0 | +0 |  |
| `quality/tests/test_fan_oracle_delegation.py` | 0 | 12 | 0 | +0 |  |
| `quality/tests/test_fan_oracle_session3_writers.py` | 0 | 4 | 0 | +0 |  |
| `quality/tests/test_fan_oracle_w11_w12_behavioral.py` | 0 | 13 | 0 | +0 |  |
| `quality/tests/test_fan_policy_oracle.py` | 0 | 18 | 0 | +0 |  |
| `quality/tests/test_fan_recheck_d2_deadlock.py` | 0 | 10 | 0 | +0 |  |
| `quality/tests/test_fan_recheck_db_schema.py` | 0 | 4 | 0 | +0 |  |
| `quality/tests/test_fan_recheck_deferred_surfaces.py` | 2 | 13 | 0 | -2 |  |
| `quality/tests/test_fan_recheck_mode2_cycle.py` | 0 | 48 | 0 | +0 |  |
| `quality/tests/test_fan_recheck_observability.py` | 1 | 16 | 1 | +0 |  |
| `quality/tests/test_fan_recheck_silent_exit.py` | 0 | 14 | 0 | +0 |  |
| `quality/tests/test_fan_sweep_trio.py` | 0 | 22 | 0 | +0 |  |
| `quality/tests/test_fan_transition_gate.py` | 0 | 19 | 0 | +0 |  |
| `quality/tests/test_fan_trust_state_extension.py` | 3 | 51 | 3 | +0 |  |
| `quality/tests/test_fill_priority_daylight_restoration.py` | 0 | 23 | 0 | +0 |  |
| `quality/tests/test_forecast_service_migration.py` | 0 | 6 | 0 | +0 |  |
| `quality/tests/test_freeze_floor.py` | 4 | 21 | 4 | +0 |  |
| `quality/tests/test_fused_sensor_boot_reresolve.py` | 0 | 7 | 0 | +0 |  |
| `quality/tests/test_g1_room_control_list_attrs.py` | 0 | 5 | 0 | +0 |  |
| `quality/tests/test_guest_census_correctness.py` | 0 | 33 | 0 | +0 |  |
| `quality/tests/test_guest_count_dedup_migrate.py` | 0 | 18 | 0 | +0 |  |
| `quality/tests/test_hc_precool_oc_observability.py` | 0 | 30 | 0 | +0 |  |
| `quality/tests/test_heatcool_enforcer.py` | 0 | 6 | 0 | +0 |  |
| `quality/tests/test_hotfix_sleep_occupied_fan_trust.py` | 0 | 13 | 0 | +0 |  |
| `quality/tests/test_hotfix_v4_7_16_3_dpm_baseline.py` | 0 | 12 | 0 | +0 |  |
| `quality/tests/test_hotfix_v4_7_16_5_energy_import_state_class.py` | 0 | 2 | 0 | +0 |  |
| `quality/tests/test_house_state_rung1.py` | 0 | 3 | 0 | +0 |  |
| `quality/tests/test_house_state_rung2a.py` | 0 | 17 | 0 | +0 |  |
| `quality/tests/test_hvac_ac_ramp_savings.py` | 0 | 19 | 0 | +0 |  |
| `quality/tests/test_hvac_excursion_banking_migration.py` | 0 | 3 | 0 | +0 |  |
| `quality/tests/test_hvac_excursion_cm_adoption.py` | 0 | 6 | 0 | +0 |  |
| `quality/tests/test_hvac_excursion_compromise_migration.py` | 0 | 9 | 0 | +0 |  |
| `quality/tests/test_hvac_excursion_config_flow_field.py` | 0 | 8 | 0 | +0 |  |
| `quality/tests/test_hvac_excursion_d1_observability.py` | 0 | 11 | 0 | +0 |  |
| `quality/tests/test_hvac_excursion_egress_migration.py` | 0 | 5 | 0 | +0 |  |
| `quality/tests/test_hvac_excursion_import_guard_warning.py` | 0 | 1 | 0 | +0 |  |
| `quality/tests/test_hvac_excursion_nudge_migration.py` | 0 | 8 | 0 | +0 |  |
| `quality/tests/test_hvac_excursion_preheat_migration.py` | 0 | 7 | 0 | +0 |  |
| `quality/tests/test_hvac_excursion_primitive.py` | 0 | 10 | 0 | +0 |  |
| `quality/tests/test_hvac_excursion_restore_failure_discharge.py` | 0 | 3 | 0 | +0 |  |
| `quality/tests/test_hvac_excursion_restore_failure_surface.py` | 0 | 8 | 0 | +0 |  |
| `quality/tests/test_hvac_excursion_startup_audit.py` | 0 | 3 | 0 | +0 |  |
| `quality/tests/test_hvac_fan_control.py` | 1 | 0 | 0 | -1 |  |
| `quality/tests/test_hvac_offphase.py` | 0 | 21 | 0 | +0 |  |
| `quality/tests/test_hvac_offphase_integration.py` | 0 | 24 | 2 | +2 |  |
| `quality/tests/test_hvac_post_peak_coast_release.py` | 0 | 7 | 0 | +0 |  |
| `quality/tests/test_hvac_presence_timer_knobs.py` | 0 | 36 | 0 | +0 |  |
| `quality/tests/test_hvac_tunable_runtime_seeding.py` | 0 | 12 | 0 | +0 |  |
| `quality/tests/test_hvac_vacancy_sweep_manual_on_guard.py` | 0 | 2 | 0 | +0 |  |
| `quality/tests/test_hvac_zone_intelligence.py` | 0 | 53 | 0 | +0 |  |
| `quality/tests/test_imsg_audit_fix_1.py` | 0 | 9 | 0 | +0 |  |
| `quality/tests/test_inclement_alert_classifier.py` | 0 | 20 | 0 | +0 |  |
| `quality/tests/test_inclement_solar_horizon.py` | 0 | 14 | 0 | +0 |  |
| `quality/tests/test_inclement_state_sensor.py` | 0 | 9 | 0 | +0 |  |
| `quality/tests/test_kanban_render.py` | 0 | 14 | 0 | +0 |  |
| `quality/tests/test_kanban_ship.py` | 0 | 14 | 0 | +0 |  |
| `quality/tests/test_ledger_golden_replay.py` | 0 | 3 | 0 | +0 |  |
| `quality/tests/test_ledger_golden_replay_preserve.py` | 0 | 5 | 0 | +0 |  |
| `quality/tests/test_lkg_primitive.py` | 0 | 10 | 0 | +0 |  |
| `quality/tests/test_low_cleanup.py` | 1 | 47 | 1 | +0 |  |
| `quality/tests/test_memory_compactor.py` | 1 | 22 | 1 | +0 | YES |
| `quality/tests/test_memory_mvp.py` | 0 | 36 | 0 | +0 |  |
| `quality/tests/test_memory_writers.py` | 0 | 25 | 0 | +0 |  |
| `quality/tests/test_metric_baseline_integration.py` | 0 | 33 | 0 | +0 |  |
| `quality/tests/test_mmwave_fan_demotion.py` | 5 | 18 | 5 | +0 |  |
| `quality/tests/test_music_following.py` | 0 | 32 | 0 | +0 |  |
| `quality/tests/test_music_following_coordinator.py` | 0 | 23 | 0 | +0 |  |
| `quality/tests/test_nm_cycle_a2_knob_surface.py` | 0 | 15 | 0 | +0 |  |
| `quality/tests/test_nm_cycle_a_preserved_signals.py` | 0 | 6 | 0 | +0 |  |
| `quality/tests/test_nm_cycle_b_safety_rails.py` | 0 | 50 | 0 | +0 |  |
| `quality/tests/test_nm_cycle_c2_fixup.py` | 0 | 14 | 2 | +2 |  |
| `quality/tests/test_nm_cycle_c2_life_safety_union.py` | 0 | 11 | 0 | +0 |  |
| `quality/tests/test_nm_cycle_c_routing_matrix.py` | 0 | 46 | 2 | +2 |  |
| `quality/tests/test_nm_echo_guard.py` | 0 | 14 | 0 | +0 |  |
| `quality/tests/test_nm_image_delivery.py` | 0 | 23 | 1 | +1 |  |
| `quality/tests/test_nm_mute_service.py` | 0 | 2 | 0 | +0 |  |
| `quality/tests/test_nm_recovery_agebound.py` | 0 | 5 | 0 | +0 |  |
| `quality/tests/test_nm_repage_image.py` | 0 | 5 | 0 | +0 |  |
| `quality/tests/test_nm_suppression_visibility.py` | 0 | 13 | 0 | +0 |  |
| `quality/tests/test_notification_hygiene.py` | 0 | 32 | 0 | +0 |  |
| `quality/tests/test_notification_manager.py` | 0 | 108 | 0 | +0 |  |
| `quality/tests/test_oc_pillar_a_handshake.py` | 0 | 41 | 0 | +0 |  |
| `quality/tests/test_oc_pillar_b_admin_surface.py` | 1 | 23 | 2 | +1 |  |
| `quality/tests/test_occupancy.py` | 0 | 18 | 0 | +0 |  |
| `quality/tests/test_occupied_fan_off_guard.py` | 0 | 7 | 0 | +0 |  |
| `quality/tests/test_opt_meta_boot_transient.py` | 0 | 6 | 0 | +0 |  |
| `quality/tests/test_optimization_coordinator.py` | 1 | 95 | 1 | +0 |  |
| `quality/tests/test_override_arrester_ttl_suppression.py` | 1 | 0 | 0 | -1 |  |
| `quality/tests/test_owner_registry_golden.py` | 0 | 4 | 0 | +0 |  |
| `quality/tests/test_owner_registry_mutation_matrix.py` | 0 | 8 | 0 | +0 |  |
| `quality/tests/test_owner_registry_persistence.py` | 0 | 7 | 0 | +0 |  |
| `quality/tests/test_part2_ec_hc_writeback.py` | 38 | 29 | 38 | +0 |  |
| `quality/tests/test_path_alpha_d2a_matrix_classifier.py` | 0 | 22 | 0 | +0 |  |
| `quality/tests/test_path_alpha_d8_gap_a_face_only.py` | 0 | 5 | 0 | +0 |  |
| `quality/tests/test_path_alpha_d9_room_corroboration.py` | 0 | 4 | 0 | +0 |  |
| `quality/tests/test_pathalpha_d2c_d3_observability.py` | 0 | 19 | 0 | +0 |  |
| `quality/tests/test_pc_observability_kill_switches.py` | 0 | 27 | 0 | +0 |  |
| `quality/tests/test_perimeter_alert_nm_routing.py` | 0 | 60 | 1 | +1 |  |
| `quality/tests/test_perimeter_burst_demotion.py` | 8 | 3 | 0 | -8 |  |
| `quality/tests/test_perimeter_linker_ready_signal.py` | 0 | 10 | 0 | +0 |  |
| `quality/tests/test_person_tracking.py` | 0 | 42 | 0 | +0 |  |
| `quality/tests/test_predicted_energy_tomorrow.py` | 0 | 4 | 0 | +0 |  |
| `quality/tests/test_prediction_sensor_kill_list.py` | 0 | 5 | 0 | +0 |  |
| `quality/tests/test_presence_coordinator.py` | 0 | 67 | 0 | +0 |  |
| `quality/tests/test_presence_fan_interference_layer1.py` | 0 | 8 | 0 | +0 |  |
| `quality/tests/test_presence_guest_latch_and_veto_gap.py` | 0 | 23 | 0 | +0 |  |
| `quality/tests/test_presence_provenance_audit.py` | 0 | 4 | 0 | +0 |  |
| `quality/tests/test_presence_provenance_docs.py` | 0 | 2 | 0 | +0 |  |
| `quality/tests/test_presence_provenance_split.py` | 0 | 16 | 0 | +0 |  |
| `quality/tests/test_presence_provenance_surface.py` | 0 | 6 | 0 | +0 |  |
| `quality/tests/test_r1_consumption_regression_v1.py` | 0 | 16 | 0 | +0 |  |
| `quality/tests/test_r7_1_attain_reason_mirrors_decision.py` | 0 | 3 | 0 | +0 |  |
| `quality/tests/test_r7_attain_raw_consumption.py` | 0 | 4 | 0 | +0 |  |
| `quality/tests/test_reboot_pickup_d2.py` | 0 | 5 | 0 | +0 |  |
| `quality/tests/test_reconcile_on_return.py` | 0 | 57 | 0 | +0 |  |
| `quality/tests/test_reconciler_fan_manual_on_guards.py` | 0 | 4 | 0 | +0 |  |
| `quality/tests/test_recorder_bloat_logflood.py` | 0 | 8 | 0 | +0 |  |
| `quality/tests/test_regressions.py` | 0 | 26 | 0 | +0 |  |
| `quality/tests/test_reload_watchdog_hazard.py` | 10 | 4 | 10 | +0 |  |
| `quality/tests/test_resolver_accuracy.py` | 0 | 45 | 0 | +0 |  |
| `quality/tests/test_resolver_legs.py` | 0 | 24 | 0 | +0 |  |
| `quality/tests/test_restart_safety_doctrine_1.py` | 0 | 117 | 0 | +0 |  |
| `quality/tests/test_room_energy_baseline_migration.py` | 0 | 9 | 0 | +0 |  |
| `quality/tests/test_room_rename_writethrough.py` | 0 | 18 | 2 | +2 |  |
| `quality/tests/test_room_substrate_integration.py` | 0 | 4 | 0 | +0 |  |
| `quality/tests/test_routine_forecaster.py` | 0 | 27 | 0 | +0 |  |
| `quality/tests/test_runtime_smoke.py` | 0 | 0 | 2 | +2 |  |
| `quality/tests/test_safety_coordinator.py` | 0 | 105 | 0 | +0 |  |
| `quality/tests/test_safeword_window.py` | 0 | 25 | 0 | +0 |  |
| `quality/tests/test_scenarios.py` | 0 | 0 | 0 | +0 |  |
| `quality/tests/test_senscap_orphan_removal.py` | 0 | 4 | 0 | +0 |  |
| `quality/tests/test_sensor_capability_and_role.py` | 0 | 34 | 0 | +0 |  |
| `quality/tests/test_sensor_exclusion.py` | 0 | 13 | 0 | +0 |  |
| `quality/tests/test_sensors.py` | 0 | 25 | 0 | +0 |  |
| `quality/tests/test_setup_unload_symmetry.py` | 0 | 11 | 0 | +0 |  |
| `quality/tests/test_sleep_fans_and_flash.py` | 0 | 43 | 0 | +0 |  |
| `quality/tests/test_snap1_at_detection_snapshots.py` | 1 | 25 | 0 | -1 |  |
| `quality/tests/test_solar_envelope.py` | 0 | 17 | 0 | +0 |  |
| `quality/tests/test_span_circuit_rekey.py` | 0 | 40 | 0 | +0 |  |
| `quality/tests/test_strings_en_translation_parity.py` | 0 | 78 | 0 | +0 |  |
| `quality/tests/test_stuck_sensor_consequence.py` | 0 | 9 | 0 | +0 |  |
| `quality/tests/test_stuck_sensor_consequence_prod.py` | 0 | 7 | 0 | +0 |  |
| `quality/tests/test_stuck_signal_watchdog.py` | 0 | 20 | 0 | +0 |  |
| `quality/tests/test_substrate_backcompat.py` | 0 | 5 | 0 | +0 |  |
| `quality/tests/test_substrate_boot_settle.py` | 0 | 4 | 0 | +0 |  |
| `quality/tests/test_substrate_classification.py` | 0 | 2 | 0 | +0 |  |
| `quality/tests/test_substrate_discovery.py` | 0 | 3 | 0 | +0 |  |
| `quality/tests/test_substrate_gap_canary.py` | 0 | 4 | 0 | +0 |  |
| `quality/tests/test_substrate_lifecycle.py` | 0 | 3 | 0 | +0 |  |
| `quality/tests/test_substrate_no_conf_lists_fallback.py` | 0 | 1 | 0 | +0 |  |
| `quality/tests/test_substrate_resubscribe.py` | 0 | 7 | 0 | +0 |  |
| `quality/tests/test_substrate_resubscribe_fixup.py` | 0 | 9 | 0 | +0 |  |
| `quality/tests/test_substrate_seed.py` | 0 | 3 | 0 | +0 |  |
| `quality/tests/test_tracking_reason_vocabulary_pin.py` | 0 | 7 | 0 | +0 |  |
| `quality/tests/test_transit_protect_sourced.py` | 0 | 21 | 0 | +0 |  |
| `quality/tests/test_unavailable_entities_chatter.py` | 0 | 3 | 0 | +0 |  |
| `quality/tests/test_update_listener_async.py` | 0 | 1 | 0 | +0 |  |
| `quality/tests/test_v4503_ec_switch_restore.py` | 0 | 14 | 0 | +0 |  |
| `quality/tests/test_v4504_blind_tilt.py` | 0 | 24 | 0 | +0 |  |
| `quality/tests/test_v450_d2_migration.py` | 0 | 8 | 0 | +0 |  |
| `quality/tests/test_v450_d4_arbitrage_ev.py` | 0 | 10 | 0 | +0 |  |
| `quality/tests/test_v4510_hvac_tunables_and_labels.py` | 0 | 93 | 0 | +0 |  |
| `quality/tests/test_v4511_ac_energy_aware_ramp_down.py` | 1 | 162 | 1 | +0 |  |
| `quality/tests/test_v4512_observability.py` | 0 | 81 | 0 | +0 |  |
| `quality/tests/test_v4513_1_zone_dedup.py` | 0 | 16 | 0 | +0 |  |
| `quality/tests/test_v4513_gap_fixes.py` | 9 | 17 | 0 | -9 |  |
| `quality/tests/test_v4514_anomaly_visibility.py` | 5 | 6 | 0 | -5 |  |
| `quality/tests/test_v4515_closet_bathroom_failsafe.py` | 0 | 22 | 0 | +0 |  |
| `quality/tests/test_v4516_failsafe_freshness.py` | 0 | 21 | 0 | +0 |  |
| `quality/tests/test_v4517_bayesian_eval_dt_util.py` | 0 | 5 | 0 | +0 |  |
| `quality/tests/test_v4518_dedup_key_widen.py` | 0 | 15 | 0 | +0 |  |
| `quality/tests/test_v4519_transition_detector_teardown.py` | 0 | 11 | 0 | +0 |  |
| `quality/tests/test_v4520_anomaly_refresh_signals.py` | 0 | 15 | 0 | +0 |  |
| `quality/tests/test_v4520_swallow_escalations.py` | 0 | 13 | 0 | +0 |  |
| `quality/tests/test_v4521_hc_device_ordering.py` | 0 | 67 | 0 | +0 |  |
| `quality/tests/test_v454_room_config_cleanup.py` | 0 | 28 | 0 | +0 |  |
| `quality/tests/test_v455_person_coord_none_data.py` | 0 | 2 | 0 | +0 |  |
| `quality/tests/test_v456_cover_gate_tilt.py` | 0 | 22 | 0 | +0 |  |
| `quality/tests/test_v458_signal_handler_gating.py` | 0 | 8 | 0 | +0 |  |
| `quality/tests/test_v4592_strings_and_delta.py` | 0 | 15 | 0 | +0 |  |
| `quality/tests/test_v459_hvac_cover_intent.py` | 0 | 53 | 0 | +0 |  |
| `quality/tests/test_v460_d4_d5_registration.py` | 0 | 8 | 0 | +0 |  |
| `quality/tests/test_v460_db_migration.py` | 0 | 5 | 0 | +0 |  |
| `quality/tests/test_v460_house_accuracy_sensor.py` | 0 | 16 | 0 | +0 |  |
| `quality/tests/test_v460_next_room_cache_write.py` | 0 | 10 | 0 | +0 |  |
| `quality/tests/test_v460_person_accuracy_sensor.py` | 0 | 18 | 0 | +0 |  |
| `quality/tests/test_v460_save_next_room_helper.py` | 0 | 13 | 0 | +0 |  |
| `quality/tests/test_v460_score_on_transition.py` | 0 | 13 | 0 | +0 |  |
| `quality/tests/test_v460_signal_constant.py` | 0 | 5 | 0 | +0 |  |
| `quality/tests/test_v4615_threadsafety.py` | 0 | 3 | 0 | +0 |  |
| `quality/tests/test_v461_anomaly_event_dataclass.py` | 0 | 12 | 0 | +0 |  |
| `quality/tests/test_v461_canary_migrations.py` | 0 | 18 | 0 | +0 |  |
| `quality/tests/test_v461_cleanup_anomaly_log.py` | 0 | 13 | 0 | +0 |  |
| `quality/tests/test_v461_db_migration.py` | 0 | 12 | 0 | +0 |  |
| `quality/tests/test_v461_severity_unification.py` | 0 | 11 | 0 | +0 |  |
| `quality/tests/test_v461_store_event_writer.py` | 0 | 14 | 0 | +0 |  |
| `quality/tests/test_v4621_humidity_fan_hardening.py` | 1 | 0 | 0 | -1 |  |
| `quality/tests/test_v4622_guest_mode_hardening.py` | 0 | 38 | 0 | +0 |  |
| `quality/tests/test_v4623_humidity_fan_behavioral.py` | 1 | 0 | 0 | -1 |  |
| `quality/tests/test_v462_d3_away_typical.py` | 1 | 12 | 1 | +0 |  |
| `quality/tests/test_v462_d4_js_divergence_math.py` | 0 | 10 | 0 | +0 |  |
| `quality/tests/test_v462_d4_regime_detector.py` | 0 | 21 | 0 | +0 |  |
| `quality/tests/test_v462_d4_schema_migration.py` | 0 | 8 | 0 | +0 |  |
| `quality/tests/test_v462_d5_acknowledge_button.py` | 0 | 6 | 0 | +0 |  |
| `quality/tests/test_v462_d5_routine_status_sensors.py` | 0 | 15 | 0 | +0 |  |
| `quality/tests/test_v462_d6_notification_dispatch.py` | 0 | 8 | 0 | +0 |  |
| `quality/tests/test_v462_d6_number_entities.py` | 0 | 15 | 0 | +0 |  |
| `quality/tests/test_v462_d6_schema.py` | 0 | 10 | 0 | +0 |  |
| `quality/tests/test_v462_d6_select.py` | 0 | 7 | 0 | +0 |  |
| `quality/tests/test_v462_d7_accuracy_consumer.py` | 0 | 11 | 0 | +0 |  |
| `quality/tests/test_v462_regime_detector_dispatches_signals.py` | 0 | 16 | 0 | +0 |  |
| `quality/tests/test_v462_single_registration_invariant.py` | 0 | 5 | 0 | +0 |  |
| `quality/tests/test_v463_anomaly_migration.py` | 0 | 64 | 0 | +0 |  |
| `quality/tests/test_v463_behavioral_dao.py` | 0 | 29 | 0 | +0 |  |
| `quality/tests/test_v465_observability_gap.py` | 0 | 37 | 0 | +0 |  |
| `quality/tests/test_v466_severity_refactor.py` | 0 | 22 | 0 | +0 |  |
| `quality/tests/test_v467_anomaly_log_null_relaxation.py` | 2 | 6 | 2 | +0 |  |
| `quality/tests/test_v4712_anomaly_type_discriminator.py` | 0 | 20 | 0 | +0 |  |
| `quality/tests/test_v4713_sleep_state_zone_presence_trust.py` | 1 | 0 | 0 | -1 |  |
| `quality/tests/test_v4714_1_forgotten_phone_hotfix.py` | 0 | 42 | 0 | +0 |  |
| `quality/tests/test_v4714_away_state_person_tracker_trust.py` | 0 | 24 | 0 | +0 |  |
| `quality/tests/test_v4715_universalize_veto.py` | 0 | 93 | 2 | +2 |  |
| `quality/tests/test_v4716_room_veto_density.py` | 0 | 38 | 0 | +0 |  |
| `quality/tests/test_v47181_sleep_wake_deadlock.py` | 0 | 33 | 0 | +0 |  |
| `quality/tests/test_v471_fixup_d2_d3_d4.py` | 0 | 14 | 0 | +0 |  |
| `quality/tests/test_v4721_occupancy_weighted_restore.py` | 0 | 13 | 0 | +0 |  |
| `quality/tests/test_v472_dpm_surfaces.py` | 1 | 34 | 1 | +0 |  |
| `quality/tests/test_v472_feature_b_guest_signal.py` | 0 | 44 | 0 | +0 |  |
| `quality/tests/test_v4731_hvac_switches_restore.py` | 0 | 45 | 0 | +0 |  |
| `quality/tests/test_v4732_heat_cool_and_span_prune.py` | 0 | 12 | 0 | +0 |  |
| `quality/tests/test_v473_baseline_preset_editor.py` | 0 | 28 | 0 | +0 |  |
| `quality/tests/test_v473_dpm_number_migration.py` | 0 | 17 | 0 | +0 |  |
| `quality/tests/test_v4742_dead_import_removed.py` | 0 | 1 | 0 | +0 |  |
| `quality/tests/test_v4743_no_eager_migration.py` | 0 | 3 | 0 | +0 |  |
| `quality/tests/test_v474_dpm_ui.py` | 0 | 26 | 0 | +0 |  |
| `quality/tests/test_v474_translation_coverage.py` | 0 | 19 | 0 | +0 |  |
| `quality/tests/test_v475_d1_picker_list_mode.py` | 0 | 1 | 0 | +0 |  |
| `quality/tests/test_v475_d2_picker_house_zones.py` | 0 | 3 | 0 | +0 |  |
| `quality/tests/test_v475_d3_canonical_runtime_only.py` | 1 | 4 | 1 | +0 |  |
| `quality/tests/test_v475_d4_auto_mirror.py` | 0 | 19 | 0 | +0 |  |
| `quality/tests/test_v475_d5_config_flow_runtime_smoke.py` | 0 | 9 | 0 | +0 |  |
| `quality/tests/test_v4761_labels_helpers_excess_solar_number.py` | 0 | 34 | 0 | +0 |  |
| `quality/tests/test_v477_ac_nudge_decouple_and_dpm_cleanup.py` | 0 | 82 | 0 | +0 |  |
| `quality/tests/test_v478_egress_db_schema.py` | 0 | 7 | 0 | +0 |  |
| `quality/tests/test_v478_egress_window.py` | 0 | 56 | 0 | +0 |  |
| `quality/tests/test_v479_hygiene_bundle.py` | 0 | 61 | 0 | +0 |  |
| `quality/tests/test_v47x_dynamic_preset.py` | 0 | 81 | 6 | +6 |  |
| `quality/tests/test_v47x_ev_tou_hardening.py` | 5 | 28 | 5 | +0 |  |
| `quality/tests/test_v47x_weather_manager.py` | 1 | 0 | 1 | +0 |  |
| `quality/tests/test_v4_6_10_setup_telemetry.py` | 0 | 38 | 0 | +0 |  |
| `quality/tests/test_v4_6_11_d3_persistence_and_dispatch.py` | 0 | 17 | 0 | +0 |  |
| `quality/tests/test_v4_6_11_dashboard_attrs.py` | 0 | 43 | 0 | +0 |  |
| `quality/tests/test_v4_6_12_aggregator_sensors.py` | 0 | 43 | 0 | +0 |  |
| `quality/tests/test_v4_6_13_coordinator_telemetry.py` | 0 | 47 | 0 | +0 |  |
| `quality/tests/test_v4_6_8_rate_reconciliation.py` | 0 | 19 | 0 | +0 |  |
| `quality/tests/test_v4_6_9_boot_state_robustness.py` | 0 | 37 | 0 | +0 |  |
| `quality/tests/test_v4_6_9_energy_recent_decisions.py` | 0 | 48 | 0 | +0 |  |
| `quality/tests/test_v4_6_9_hvac_intent_attrs.py` | 0 | 38 | 0 | +0 |  |
| `quality/tests/test_v4_6_9_next_state_sensor.py` | 0 | 27 | 0 | +0 |  |
| `quality/tests/test_v4_6_9_safety_recent_events.py` | 0 | 57 | 0 | +0 |  |
| `quality/tests/test_v4_6_9_security_aggregator.py` | 0 | 41 | 0 | +0 |  |
| `quality/tests/test_v4_7_17_1_ac_nudge_eval_window.py` | 0 | 36 | 0 | +0 |  |
| `quality/tests/test_v4_7_17_2_dpm_simplified_frame.py` | 3 | 41 | 1 | -2 |  |
| `quality/tests/test_v4_7_18_2_boot_warning_logonce.py` | 0 | 8 | 0 | +0 |  |
| `quality/tests/test_v4_7_18_dpm_drift_guard.py` | 0 | 20 | 2 | +2 |  |
| `quality/tests/test_v4_7_20_1_dispatcher_unbound_regression.py` | 0 | 2 | 0 | +0 |  |
| `quality/tests/test_v5100_music_following.py` | 0 | 54 | 0 | +0 |  |
| `quality/tests/test_v5110_optimizer_hardening.py` | 0 | 31 | 1 | +1 |  |
| `quality/tests/test_v570_fixup_wiring.py` | 0 | 25 | 0 | +0 |  |
| `quality/tests/test_v570_guest_detection_trust.py` | 0 | 24 | 0 | +0 |  |
| `quality/tests/test_v5_17_1_part3_seams.py` | 0 | 6 | 0 | +0 |  |
| `quality/tests/test_v5_17_3_boundary_and_latch.py` | 0 | 17 | 0 | +0 |  |
| `quality/tests/test_v5_37_1_clear_sensor_fields.py` | 2 | 4 | 0 | -2 |  |
| `quality/tests/test_v5_7_1_energy_precool.py` | 0 | 49 | 1 | +1 |  |
| `quality/tests/test_websocket_api.py` | 0 | 18 | 0 | +0 |  |
| `quality/tests/test_writer_b_removal_and_reason_ledger.py` | 0 | 25 | 0 | +0 |  |
| `quality/tests/test_z_sysmodules_probe_0.py` | 0 | 1 | 0 | +0 |  |
| `quality/tests/test_z_sysmodules_probe_A.py` | 1 | 0 | 0 | -1 |  |
| `quality/tests/test_z_sysmodules_probe_B.py` | 1 | 0 | 0 | -1 |  |
| `quality/tests/test_zone_confidence_doc.py` | 0 | 1 | 0 | +0 |  |
| `quality/tests/test_zone_delete_dispatch_snapshot.py` | 0 | 2 | 0 | +0 |  |
| `quality/tests/test_zone_delete_flow.py` | 0 | 17 | 0 | +0 |  |
| `quality/tests/test_zone_delete_prune_guard.py` | 0 | 7 | 0 | +0 |  |
| `quality/tests/test_zone_migration_mint_guard.py` | 0 | 7 | 0 | +0 |  |
| `quality/tests/test_zone_name_resolution.py` | 0 | 9 | 0 | +0 |  |
| `quality/tests/test_zone_prune_hotfix_source.py` | 0 | 2 | 0 | +0 |  |
| `quality/tests/test_zone_safety_alert.py` | 0 | 38 | 0 | +0 |  |
| `quality/tests/test_zone_substrate_migration.py` | 0 | 3 | 0 | +0 |  |
| `quality/tests/test_zzz_v318_hvac_sensors.py` | 0 | 9 | 1 | +1 |  |
