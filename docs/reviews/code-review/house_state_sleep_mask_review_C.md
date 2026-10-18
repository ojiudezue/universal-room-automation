# Review C: house-state sleep-mask / BLE memory / AWAY observability (Tier 3, test authority)

Branch feature/house-state-sleep-mask-ble-memory, head 2e10e3a09. Framing C: one real
source mutation per site, run `quality/tests/test_house_state_sleep_mask_ble_memory.py`
(60 tests, GREEN baseline), restore, tree clean. PYTHONDONTWRITEBYTECODE=1, `__pycache__`
cleared before every run. Mutations were hand-written (not taken from the builder's drills file).

| # | Site (presence.py unless noted) | Mutation | Result | First RED tests |
|---|---|---|---|---|
| M1 | infer() call-site kwarg `any_zone_occupied_for_empty=` | kwarg removed | RED (8) | test_nobody_home_blocked_in_sleep_when_zone_raw_occupied, test_radar_only_sleeper_with_fan_on_holds |
| M2 | raw-occupancy limb `and self._zone_night_raw(t)` | `and False` | RED (11) | test_night_raw_ble_and_camera_limbs, test_zone_sleep_pin_survives_home_override_raw_limb_applies |
| M3 | AWAY-override carve-out (`t.mode == SLEEP` keyed limb) | `t.mode != OCCUPIED` | RED (1) | test_zone_away_override_carve_out |
| M4a | D1b wake disjunct | `and False` | RED (3) | test_sleep_leaves_after_window_with_raw_occupancy, test_infer_wake_disjunct_engine_level, test_wigton_shape_sleep_ends_via_waking |
| M4b | D1b wake disjunct, `not self._is_sleep_hour(hour)` conjunct dropped | removed | GREEN (equivalent mutant) | none |
| M5a | trip-wire sleep-window gate `if engine._is_sleep_hour(...)` | `if False` | RED (3) | test_sleep_raw_hold_tripwire_silent_during_sleep_window |
| M5b | trip-wire window-end yesterday roll `if window_end > now_local` | `if False` | **GREEN** | none |
| M5c | trip-wire bound compare `held_s <= bound` | `if False` | RED (3) | test_sleep_raw_hold_tripwire_fires_once_after_window_end_plus_bound |
| M5d | trip-wire fired latch | latch removed | RED (2) | test_sleep_raw_hold_tripwire_fires_once_after_window_end_plus_bound |
| M5e | trip-wire held predicate `census == 0` | conjunct dropped | RED (1) | test_sleep_raw_hold_tripwire_not_when_census_positive |
| M6 | D2 STALE predicate | `and False` | RED (9) | test_stale_resident_blocks_alpha, test_stale_hold_ends_after_decay_timeout |
| M7 | phone_left_behind precedence `phone_ok and track_ok` | `track_ok` only | RED (1) | test_d2_preserves_phone_left_behind_precedence |
| M8a | counter no-op gate (`old != AWAY`) | gate dropped | RED (1) | test_no_restore_branch_value_emitted |
| M8b | counter placed before boot-settle return | moved up | RED (8) | test_gated_dispatch_not_counted[boot_settle] |
| M8c | counter placed before observation-mode return | moved up | RED (1) | test_gated_dispatch_not_counted[observation_mode] |
| M9a | getter day check (midnight bound) | `if False` | RED (1) | test_away_entries_today_getter_zero_after_local_midnight |
| M9b | `_roll_away_count_day` reset | `if False` | RED (7) | test_away_entries_today_getter_zero_after_local_midnight |
| M9c | hydrate bound (start of local day) | minus 1 day | RED (2) | test_away_count_hydration_naive_utc_bound_includes_boundary_row |
| M9d | hydrate `exclude_same_previous` | False | RED (2) | test_away_count_excludes_away_to_away_rows |
| M9e | hydrate `state=AWAY` filter | removed | RED (2) | test_setup_hydrates_away_entries_today |
| M9f | `_periodic_inference` roll call | removed | RED (1) | test_periodic_rolls_away_count_at_midnight |
| M10 | sensor.py `_unrecorded_attributes` entry `nobody_home_zone_input` | entry removed | RED (1) | test_unrecorded_attributes_set |
| M10b | sensor.py `_unrecorded_attributes` | emptied | RED (1) | test_unrecorded_attributes_set |
| M11 | `_veto_path = "nobody_home"` label | removed | RED (7) | test_last_away_branch_nobody_home, test_already_away_tick_keeps_veto_path_none |
| M12 | database.py `AND state = ?` SQL filter | removed | RED (2) | test_away_count_excludes_away_to_away_rows |

26 mutations: 24 RED, 2 GREEN. After every run the file was restored; `git status --short` was empty.

## Findings

- **M5b, LOW/MEDIUM, untested site (Bug Class #62-adjacent, config-extreme untested).**
  `_check_sleep_raw_hold` rolls `window_end` back a day when `sleep_end_hour` is later today
  (the `if window_end > now_local` line, near presence.py:4075-4079). With the default wrapping window
  (23-6, 22-7) every non-sleep hour is >= sleep_end, so the branch is dead. It is reachable only for a
  legal non-wrapping window (e.g. start 1, end 7) at a non-sleep hour before the start
  (00:30: window_end 07:00 today > now). Neutering it leaves the suite GREEN, so no test pins it.
  Remedy: one test with a non-wrapping window and `now` before `sleep_end` asserting
  `held_s` is measured from yesterday's end. This is a config-extreme test, not a prod bug found here.
- **M4b, INFO, equivalent mutant.** The `not self._is_sleep_hour(hour)` conjunct in the D1b disjunct is
  redundant: with it dropped, a SLEEP-hour tick sets `has_people=True` and the later
  `if self._is_sleep_hour(hour)` branch (presence.py ~1370) returns None, the same result as
  `not has_people -> None`. No behaviour differs, so no test can catch it. Either keep as defence in depth
  or delete; it is not an untested load-bearing site.
- **Note (not a finding in the cycle's code).** `quality/tests/test_v4714_away_state_person_tracker_trust.py`
  fails at collection when run alone in this worktree
  (`No module named ...universal_room_automation.database`, stub-order dependent, raised from
  `coordinator_diagnostics.py:34`). I did not run it standalone as a mutation target; the builder's
  edit to it (61 lines) was therefore not independently drilled here.
- The builder's drill file `test_house_state_sleep_mask_mutation_drills.py` was not used.

## Verdict (framing C)

FIX-REQUIRED (minor): add one non-wrapping-window test for M5b. Everything else named in the
brief (call-site kwarg, raw limb, AWAY carve-out, wake disjunct, trip-wire window-end gate, STALE
predicate, phone_left_behind precedence, counter placement vs both early returns, midnight bound,
`_unrecorded_attributes`) goes RED on a specific named test.
