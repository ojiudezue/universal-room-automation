# AUDIT: test suite serial vs parallel (TEST-SUITE-PARALLEL-1), 2026-11-10/11

Card: TEST-SUITE-PARALLEL-1 (Tier 1, test-only). Branch `test/suite-parallel-1` (cut from
`origin/develop` 650698c7). No file under `custom_components/` was changed.

Goal: `pytest quality/tests` gives the same failing-test names serially and with
`-n 6 --dist loadfile`, so the release gate can run in parallel.

All runs: `PYTHONDONTWRITEBYTECODE=1 URA_SOURCE_MUTATION=1 PYTHONPATH=quality .venv-ha/bin/python -m pytest quality/tests ...`
(source-mutation drills included).

## Result

| Run | Before (probe on 9894bc66) | After (this branch) |
|---|---|---|
| Serial | 18 failed, 33 min (1978 s) | **2 failed**, 41 min (2471 s) |
| `-n 6 --dist loadfile` | 91 failed, 19 min (1130 s); a second run gave 61 failed + 3 errors | **2 failed**, 11 min 16 s (677 s) |

The failing-name sets are identical (serial `ser_v2`, parallel `par_v5`):

- `test_ble_extend_not_create.py::test_MUTATION_m2_seeding_hoisted_above_predicate_makes_order_test_red`
- `test_snap1_at_detection_snapshots.py::test_snap1_frigate_capture_refuses_traversal_event_id`

Both fail the same way in both modes and alone; neither is an ordering problem (see "Remaining").
The 15 serial-only pollution failures are gone. Serial wall time on this machine varied run to run
(39-41 min with no other load on the second run vs the probe's 33 min); the comparison that
matters is serial vs parallel on the same tree: 41 min vs 11 min.

Pass/skip counts differ slightly (serial 20510 passed / 126 skipped; parallel 20508 / 128): two
tests skip under xdist. Failing names, the gate's comparison, are identical.

## What bounds wall time

Before: `--dist loadfile` puts a whole file on one worker. `test_house_state_sleep_mask_mutation_drills.py`
is 111 sandboxed source-mutation drills, ~1070 s of work on one worker. That one file set the whole
run's wall time (18-19 min), with `test_d7_donor_hygiene.py` (~500 s) and `test_chatter_wire_in.py`
(~330 s) next.

Fix: `quality/tests/_xdist_split.py` (registered in `conftest.py` `pytest_plugins`) implements
`pytest_xdist_make_scheduler`. It returns a `LoadFileScheduling` subclass whose `_split_scope`
makes each **subprocess-sandboxed drill** in those three files its own work unit. Every other
test, including the in-process tests of those same files, is still grouped by file. Only active
for `--dist loadfile`. Anchors: `test_xdist_split.py`.

After: the sum of per-test durations is ~3160 s over 6 workers (~530 s each) plus a full
collection per worker (~35 s). The run is now bounded by total work divided by worker count. The
longest single units left are `test_d7_donor_hygiene.py::test_drill_donor_leak_reintroduced_goes_red[test_optimization_coordinator.py]`
(135 s) and `test_snap1_frigate_capture_refuses_traversal_event_id` (120 s, failing). More
workers or splitting more drill files would help further.

## Method

Every xdist worker collects the WHOLE suite and then runs only its files. So in-process state at a
victim's first test is: collection-time state for all files, plus whatever the files that ran
earlier on the same worker did. Serial order is the same collection plus every alphabetically
earlier file. A difference between the two is a donor (a file that leaves state behind) or an
antidote (a file whose leftovers happen to repair a victim).

Tools (scratchpad, not committed): an order plugin that collects everything and runs only a chosen
list of files in a chosen order (`SP1_FILES`). With it:

1. **Collection-only triage:** full collection, run only the victim. RED means a collection-time
   donor, so bisect the collected file set (`cbisect`).
2. **Worker-prefix bisect:** take the victim's worker sequence from a `-v` parallel log and bisect
   that prefix with full collection (`bisect`).
3. Confirm the pair, fix, then re-run (1)/(2) and the file alone.

## Donor -> victim table

| Donor | Victim(s) | Kind | Fix (side) |
|---|---|---|---|
| `test_ac_ramp_pipeline_hardening.py` (import-time HA + URA stubs, never restored) | `test_unload_symmetry_task_hygiene`, `test_zone_migration_mint_guard` | collection | Donor: `_sysmodules_scope.ModuleScope(("custom_components","homeassistant"))` seal + fixture |
| `test_anomaly_baseline_periodic_save.py` (star-imports `test_domain_coordinators`'s import-time stubs) | same two, then `test_zone_orphan_device_guard` | collection | Victims: module fixture `occ_dwell_helpers.real_package()` (the stub graph behind `test_domain_coordinators` has many dependents; not scoped) |
| `test_v47x_ev_tou_hardening.py` (force-set `restore_state` stub with no `RestoredExtraData`) | `test_zone_power_rollup` (5), serial `test_energy_today_midnight_freeze` | collection | Donor: ModuleScope seal + fixture |
| `test_ac_ramp_master_option_persistence.py` (already scoped; its scope exposes the real HA `event`) | `test_opt_meta_boot_transient` (4) | collection | Victim was fragile (MockHass without `loop`). Pinned inert `async_track_*` on the optimization module (monkeypatch) |
| 44-file hvac_excursion..identity_fusion stub chain | `test_prediction_sensor_kill_list::test_next_occupancy_time_device_class_is_timestamp` | collection | Victim: compare against `sensor.py`'s own `SensorDeviceClass` |
| `test_fan_incident_2026_08_01_replay.py` (bare `RestoreEntity` stub) | `test_hvac_cpr_batch_c` (16), `test_low_cleanup` (1) | collection | Victims: `monkeypatch.setattr(RestoreEntity, ..., raising=False)` |
| `test_oc_pillar_b_admin_surface.py` (per-test URA eviction, never undone) | `test_hvac_excursion_{nudge,preheat,banking,compromise,egress,d1_auto_release,startup_audit,restore_failure_discharge}`, `test_cflow_timing_instrumentation`, `test_arrester_operator_immunity`, ... | run-time | Donor: eviction wrapped in `_d7_isolation.import_scope(("custom_components",), attrs=True)` |
| `test_oc_pillar_a_handshake.py` (same eviction) | `test_ble_absence_grace` | run-time | Donor: same |
| `test_optimization_coordinator.py` (same eviction) | `test_memory_mvp::test_kill_switch_disables_all_verbs` | run-time | Donor: same, plus its tests now install this file's inert `event`/`dispatcher` stubs inside the scope (the file failed 10 tests when run ALONE) |
| `test_safety_humidity_junk_floor.py` (`_install_aggregation_mocks` at run time) | `test_energy_today_midnight_freeze` (3) | run-time | Donor: module `file_scope()` fixture (same as `test_zone_safety_alert`) |
| `test_room_dwell_model.py` | `test_zone_power_rollup` | (bisect artifact: the victim failed with collection only; fixed by the v47x row) | none |
| 39-file combination (no single donor) | `test_ec_stage_e_fixup` (3) | run-time | Harness: `_reserve_governor_harness._dt_modules()` also pins the dt objects the production classes HOLD; `chi_clock` sets the zone on them |
| (same harness) | `test_ec_reserve_false_revert_fixup` (29) | run-time | same harness fix |
| `test_zone_house_advanced_fields.py` (+ collection) | `test_energy_history_kwh_integration`, `test_fan_layer_2_d2_fixup` (3) | run-time | Victims: patch the globals of the module the class under test was built from (`type(db).initialize.__globals__`, `RoomAutomation...__globals__["dt_util"]`) |
| `test_override_arrester_ttl_suppression.py` (+ collection) | `test_fan_oracle_w11_w12_behavioral::test_w12_...` | run-time | Victim: `_set_now` re-reads the held dt objects per test (hvac, hvac_predict, oracle `_ha_dt`, hvac_fans) |
| 131-file combination (module eviction) | `test_db_write_worker_boot_race`, `test_db_write_ready_lossless_timeout` mutation tests | run-time | Victims: restore by re-exec'ing the original source into the module namespace instead of `importlib.reload` (which needs the module to still be the sys.modules entry) |
| serial order | `test_house_energy_correctness` (4 across runs) | run-time (tz / dt copy) | Victim: `_freeze` patches the db class's module globals and pins `DEFAULT_TIME_ZONE` + the lru-cached `get_default_time_zone` (UTC, or Chicago for the local-midnight test) |
| serial order | `test_shared_power_read_staleness` kill-switch, `test_zone_safety_alert` CM knob drift (2) | run-time (parent attr vs sys.modules) | Victims: `importlib.import_module(...)` (what the production lazy `from . import` resolves) instead of `import a.b.c as x` (parent attribute walk) |
| serial order | `test_radar_tuning_phase_a` (6), `test_room_menu_adv_trim_and_room_rate` (2) | run-time | Not edited; green after the donor fixes above |
| xdist file split | `test_z_sysmodules_probe_A/B` (cross-file 0 -> A -> B chain) | parallel only | A/B seed the probe at import when absent. Drill (remove the conftest restore loop) still turns B RED, verified |
| wall clock | `test_perimeter_alert_nm_routing::test_MUTATION_kill_switch_gates_dispatch_byte_identical` | flake (second boundary) | Compare messages with HH:MM:SS masked |
| wall clock | `test_snap1_at_detection_snapshots::test_snap1_vehicle_dispatch_threads_snapshot_path` | time-of-day | Also neuter `_is_in_vehicle_alert_hours` (the neutered `_in_vehicle_night_window` is only an alias now) |

### test_d7_donor_hygiene updates

The slice-2 note said the eviction donors (oc_pillar_a/b, optimization_coordinator) were left
unscoped on purpose, because their eviction healed collection-time stubs for later files in the
serial order. Under `-n 6` that heal only happens on whichever worker runs them. That is a main
reason serial and parallel disagreed. They are now scoped. The victims this exposed are the rows
above; the final serial run is 2 failed.

- Added `DONOR_PROBES` (kind `ident` on the URA package and `domain_coordinators`) and `_DRILLS`
  (un-scope the eviction) for the three donors. All three drills are KILLED (verified).
- Retired the victim-side drills for `perimeter_alert_nm_routing`, `sleep_fans_and_flash` and
  `v4715_universalize_veto`. Their premise, an unscoped donor, no longer holds, so reverting the
  victim fix no longer reds the pair. This follows the slice-2 precedent. `sleep_fans_and_flash` was
  already failing in the probe baseline in both modes.

## Remaining failures (identical in both modes; not ordering)

1. `test_ble_extend_not_create.py::test_MUTATION_m2_seeding_hoisted_above_predicate_makes_order_test_red`.
   The drill's `swap_from` anchor (`if ble_persons:` followed by `# Check if this room has direct BLE coverage (Tier 1)`)
   no longer exists in `coordinator.py`. BLE-LOCATION-QUALITY-1 (b13a151e) inserted the absence-grace lines
   between them. Fixing it needs the drill re-pointed at the current seeding site, which is a judgement
   about the mutation, not an ordering fix. Needs a card.
2. `test_snap1_at_detection_snapshots.py::test_snap1_frigate_capture_refuses_traversal_event_id`
   fails with "traversal wrote outside tmp: .../front_yard_____etc_passwd.jpg" and takes ~120 s.
   It fails alone too. It looks like a real path-handling finding in `perimeter_alert.py`
   (production). It is out of scope for a test-only card and needs its own card.

## Files changed (tests only)

`quality/tests/`: `_xdist_split.py` (new), `test_xdist_split.py` (new), `conftest.py`,
`_reserve_governor_harness.py`, `_ec_stage_e_harness.py`, `test_ac_ramp_pipeline_hardening.py`,
`test_v47x_ev_tou_hardening.py`, `test_oc_pillar_a_handshake.py`, `test_oc_pillar_b_admin_surface.py`,
`test_optimization_coordinator.py`, `test_opt_meta_boot_transient.py`, `test_zone_migration_mint_guard.py`,
`test_unload_symmetry_task_hygiene.py`, `test_zone_orphan_device_guard.py`, `test_prediction_sensor_kill_list.py`,
`test_hvac_cpr_batch_c.py`, `test_low_cleanup.py`, `test_house_energy_correctness.py`,
`test_energy_history_kwh_integration.py`, `test_shared_power_read_staleness.py`, `test_zone_safety_alert.py`,
`test_safety_humidity_junk_floor.py`, `test_fan_layer_2_d2_fixup.py`, `test_fan_oracle_w11_w12_behavioral.py`,
`test_db_write_worker_boot_race.py`, `test_db_write_ready_lossless_timeout.py`,
`test_perimeter_alert_nm_routing.py`, `test_snap1_at_detection_snapshots.py`,
`test_z_sysmodules_probe_A.py`, `test_z_sysmodules_probe_B.py`, `test_d7_donor_hygiene.py`.

## Caveat

xdist assigns files to workers dynamically, so each parallel run exercises different
co-residencies. Over five parallel runs during this work the parallel-only set went
91 -> 42 -> 8 -> 4 -> 0 as each newly exposed pair was fixed. A future run may still turn up a pair
no run here put on the same worker. The triage loop above (collection-only, then worker-prefix
bisect from a `-v` log) is the way to handle one.
