# Rev 3.2 review C: test authority by per-site source mutation

Delta dad3bf6e7..2244661c3, worktree rev32-review-C. Files: quality/tests/test_zone_tracker_per_entity.py, quality/tests/test_house_state_sleep_mask_ble_memory.py. Baseline 125 passed (85 passed + 40 skipped under `--per-entity-off`). Each row: PYTHONDONTWRITEBYTECODE=1, __pycache__ cleared, one-site mutation, restore in finally, tree verified clean. Run with `-m ""` so drill-marked tests are included.

| # | Site | Mutation | Mode | First RED test(s) | Result |
|---|---|---|---|---|---|
| 1 | `_kind_on_now` event-state source | event_state branch -> `if False` | on | test_substrate_single_entity_dispatch_sequence_identical; test_seed_and_live_share_kind_on_now; test_callback_before_state_store_uses_payload (3) | RED |
| 2 | `_kind_on_now` sibling OR | sibling `on` -> never True | on | test_substrate_same_kind_sibling_off_keeps_kind_on; test_substrate_same_kind_last_off_dispatches_false (19) | RED |
| 3 | `_kind_on_now` explicit map | seed passes `self._entity_to_room_kind` not desired map | on | test_options_save_removing_on_sensor_releases_room; test_options_save_adding_on_sensor_sets_kind; test_refresh_retry_after_failure_emits_edges (3) | RED |
| 4 | deleted-entity-off | `new_state is None and not per_entity` -> `new_state is None` | on | test_deleted_entity_while_on_releases_room | RED |
| 5 | scratch-copy swap | drop `self._raw_state = seed_target` | on | test_options_save_removing_on_sensor_releases_room (+2) | RED |
| 6 | scratch-copy creation | seed in place (`seed_target = self._raw_state`) | on | test_refresh_subscribe_failure_leaves_state_untouched; test_refresh_retry_after_failure_emits_edges | RED |
| 7 | room-removed walk | `walk_rooms = desired_rooms` | on | test_removed_room_true_kinds_get_false_edges; test_room_delete_via_config_entries_async_remove_releases_kinds | RED |
| 8 | `async_remove_entry` dispatch | early `return` before dispatch | on | test_room_delete_via_config_entries_async_remove_releases_kinds | RED |
| 9 | tracker kind-only pop | `bucket.pop(kind)` -> `bucket.clear()` | on | test_tracker_kind_off_clears_only_that_kind; test_tier1_sentinel_survives_kind_specific_false; test_last_kind_popped_only_when_room_empty (7) | RED |
| 10 | boot reconcile differing-slots-only | `if have != value` -> `if True` | on | test_release_reconcile_writes_only_differing_slots | RED |
| 11 | boot reconcile guard | try/except neutered | on | test_release_reconcile_exception_does_not_abort_tick | RED |
| 12 | boot reconcile call | call removed | on | test_boot_settle_replay_unchanged; test_release_clears_kind_that_went_off_during_settle; test_release_reconcile_removed_room_during_settle (4) | RED |
| 13 | gate `async_remove_entry` | gate -> `if False` | --per-entity-off | test_zone_per_entity_switch_read_by_attribute (lint only; no behavioural off-mode test) | RED (weak) |
| 14 | gate tracker kind-only pop | forced on (off-run) | --per-entity-off | test_tracker_kill_constant_false_full_clear; test_kill_switch_off_dh1_repro_holds_sleep; test_kill_switch_off_matches_branch_trace (4) | RED |
| 15 | gate tracker kind-only pop | forced off (on-run) | on | test_tracker_kind_off_clears_only_that_kind (8) | RED |
| 16 | gate boot reconcile | forced on (off-run) | --per-entity-off | none (85 passed, 40 skipped) | **GREEN** |
| 17 | gate boot reconcile | forced off (on-run) | on | test_boot_settle_replay_unchanged (+3) | RED |
| 18 | gate D4d | forced on (off-run) | --per-entity-off | test_d4d_silent_when_kill_switch_off | RED |
| 19 | gate night-rooms live limb | limb always runs (`if True`) | on | none (125 passed) | **GREEN** |
| 20 | gate night-rooms live limb | limb always skipped | --per-entity-off | test_kill_switch_off_dh1_repro_holds_sleep (+4) | RED |
| 21 | gate `any_zone_raw_occupied` | line always runs | on | test_manual_occupied_zone_override_does_not_force_waking_gate | RED |
| 22 | gate `any_zone_raw_occupied` | line always skipped | --per-entity-off | test_wigton_shape_multi_sensor_master_ends_via_waking_switch_off | RED |
| 23 | gate substrate live handler | forced on (off-run) | --per-entity-off | test_kill_constant_false_restores_last_writer; test_kill_switch_off_matches_branch_trace | RED |
| 24 | gate substrate live handler | forced off (on-run) | on | test_substrate_same_kind_sibling_off_keeps_kind_on (+4) | RED |
| 25 | gate substrate refresh | forced on (off-run) | --per-entity-off | none (85 passed, 40 skipped) | **GREEN** |
| 26 | gate substrate refresh | forced off (on-run) | on | test_removed_room_true_kinds_get_false_edges (+3) | RED |
| 27 | D4d bound (never fires) | `held_s <= bound` -> `if True` | on | test_zone_hold_all_away_fires_once_past_bound (+2) | RED |
| 28 | D4d bound (always fires) | -> `if False` | on | test_zone_hold_all_away_fires_once_past_bound; test_d4d_clock_resets_on_blip | RED |
| 29 | D4d bound<=0 disable | drop `bound <= 0` | on | test_zone_hold_all_away_bound_zero_disables | RED |
| 30 | D4d latch | drop `_fired` check | on | test_zone_hold_all_away_fires_once_past_bound; test_zone_hold_all_away_rearms_after_clear; test_d4d_clock_resets_on_blip | RED |
| 31 | D4d severity | "HIGH" -> "LOW" (D4d copy) | on | test_zone_hold_all_away_fires_once_past_bound | RED |
| 32 | D4d clock reset on non-held | drop reset | on | test_zone_hold_all_away_rearms_after_clear; test_d4d_clock_resets_on_blip | RED |

## Findings (3 GREEN rows, all switch-off semantics)

- MEDIUM, rows 16/25: nothing asserts the switch-OFF path does NOT reconcile at boot release, and does NOT use the scratch-copy seed in refresh. Forcing either on while the switch is off leaves the suite green, so the kill-switch's byte-identity claim (R3.1.1) is untested at these two sites. Add `per_entity_off_only` tests: boot release with a settle-time off-edge leaves the tracker slot True (old behaviour); failed-subscribe refresh with switch off keeps the in-place seed.
- LOW, row 19: night-rooms live-sensor limb running while the switch is ON is invisible to the suite (the limb is redundant when the tracker is exact, so a test needs a deliberately divergent tracker/live state to prove it is skipped).
- LOW, row 13: the `async_remove_entry` switch gate is caught only by the attribute-read lint, not by a behavioural off-mode test (switch off -> no "removed" dispatch).

Verdict for framing C: all 12 requested site groups are RED on a named test; 3 untested off-mode gate directions (above) should be closed before ship.
