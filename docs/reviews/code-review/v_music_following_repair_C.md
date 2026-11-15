# Review C: music following repair (test authority via real per-site source mutation)

Branch `feature/music-following-repair` @ 3c0ecaf8 (develop d0a25cbc merged in; `git merge-base HEAD d0a25cbc` = d0a25cbc,
three-dot diff 29 files). Framing C only. Plan: `docs/planning/PLANNING_music_following_repair.md`. Reviews A and B read.
Method: one production-source mutation per run (303 mutations), `PYTHONDONTWRITEBYTECODE=1`, `__pycache__` purged before every run,
file restored in a `finally`, `git status` clean after the run. Test set per mutation: the 4 music-following test files
(`test_music_following_repair.py`, `test_music_following.py`, `test_music_following_coordinator.py`, `test_v5100_music_following.py`),
plus, for mutations outside `music_following.py`, the reload-suppression / config-flow / memory-writer / person-awareness / detector-teardown files.
`-m ""` (drill-marked tests included), `--timeout=20` on the re-runs. Baseline 207 passed in 2.4 s.

Result: **189 RED, 114 GREEN** (T2 is RED only by hang: no named assertion). A GREEN is not always a defect: where the mutant is
behaviourally equivalent or a default-equal hardcode I say so below. Real untested load-bearing sites are listed first.

## Verdict: FIX-REQUIRED

The repair's core is well anchored: join direction, MA payload keys and MA-only-if-playing, extend-on-MA, the BLE gate (room mismatch, "any",
saved strict), source-has-others, lock-before-verify, saved-volume persist and hand-set respect, teardown orphan restore, bounce-during-source-stop,
generic cancel-during-start, DB trip-wire, parent-unload teardown, area-id lookup, opt-out both ways, one-outcome-per-transition, decision episode writer,
diag-listener unsub (coordinator side) and most dead knobs are each RED on a specific test. But the items below leave the suite GREEN when the site is neutered.
Given the operator standard ("features die"), the first group must have a test before ship.

## Must fix before ship (load-bearing site, mutation leaves suite GREEN)

| # | Site | Exact mutation (music_following.py unless noted) | Why it matters |
|---|---|---|---|
| C-1 | Hazard block expiry (H16) | `hazard_active`: `return self._hazard_until > 0 and self._monotonic() < self._hazard_until` -> `return self._hazard_until > 0` | After ONE hazard, music following is blocked forever (until restart). No test advances the clock past MF_HAZARD_BLOCK_S. |
| C-2 | Cooldown armed by a real success (Y17, Y18) | delete `self._last_transfer_time[rec.person_key] = dt_util.now()` / `self._last_transfer_target[...] = rec.to_room` | Cooldown tests seed those dicts directly (test file :1200, :1618), so production never arming the cooldown is invisible. |
| C-3 | Native join move releases the source (Y3) | `_release_source`: delete `await self._call(MEDIA_PLAYER_DOMAIN, "unjoin", {"entity_id": rec.source_player})` | Move mode on the join path never removes the old room from the group; every source player stays grouped, music plays in both rooms. |
| C-4 | MA and join cancel-during-start (S1, S2) | move `self._mark_started(rec)` after the awaited `transfer_queue` / `join` call (B6 fix undone) | Only the generic path (S3) is anchored. The MA/Sonos path the operator cares about regresses silently. |
| C-5 | Detector listener registered at init (K10) | `async_init`: `self.transition_detector.async_add_listener(self._on_person_transition)` -> `pass` | Whole feature dead; every test calls `_on_person_transition` directly. Test line 1731 registers on the detector, not via `async_init`. |
| C-6 | Sensor-side listener unsubscribe (K4-K8, `sensor.py`) | `if callable(_unsub): self.async_on_remove(_unsub)` -> `pass`, any of the 5 sensors | The reload-listener-leak fix is anchored only on the coordinator side (K2, K3, K9, T10 RED); the four+one sensor sites have no test. |
| C-7 | Bedroom via preference provider (Y36, Y37, Y38) | `_dwell_room_for_person`: `dwell = prefs.get("bedroom") ...` -> `dwell = None`; `{"purpose": "bedroom"}` -> `{}`; `_slug(dwell) != _slug(to_room)` -> `False` | Operator-requested item: NOT anchored. No test in any MF file exercises `dwell_only` with a provider. |
| C-8 | Producer event keys (G1, G2, G3, `person_coordinator.py`) | delete `"method"` / `"bermuda_area"` / `"area_sensor"` from the `ura_person_location_change` payload | The detector copy (G4-G6) is RED; the producer end is not. Note B9 and B11 are GREEN too, so after the gate drop these keys only feed a counter and logs: low impact, but unanchored. |
| C-9 | Source-room-others loop is not self-blocking (O3) | `if other_id == person_id or _person_key(other_id) == me: continue` -> `if False: continue` | GREEN. Mitigated in production because the mover's layer location is already `to_room`, but an unanchored self-exclusion. O2 (person-key variant) and O4 (slug compare) GREEN too. |
| C-10 | Two-person serialisation (L2, A9) | `_run`: delete `await self._lock(rec)` | `test_mf_two_people_bounce_same_rooms` passes with no lock. INV-MF-5 cross-person leg is unanchored. |
| C-11 | Hazard scope parts (H2, H3, H4, H6, H11, H13) | drop the `_active_groups` loop / `_bonus_joined` loop / MA-twin loop / zone-player branch; manual-transfer hazard check; hazard cancels reversal watches | A-M1 fix is anchored for started players (H1) and configured room players (H5) only. A hazard would not stop grouped followers, bonus players, MA twins or zone players with no test failing. |
| C-12 | Outcome booked for hazard-blocked transition (C8) | delete `self._finish(rec, "hazard_blocked")` before `return` in `_on_person_transition` | INV-MF-2 hole: the table-driven one-outcome test has no hazard case. |
| C-13 | Bonus failure swallowed (Z4) | in `_bonus_joins_after_success` except: replace the log with `raise` | A bonus failure would abort the release (source never stopped) with outcome still success. Existing test checks only the outcome. Z6, Z7, Z9, Z11, Z13 (bonus platform, primary-device exclusion, leader, unavailable, via_ma) GREEN too. |
| C-14 | Counted/observed wiring (Q13-Q17, C19, C20) | `sensor.py` TransfersToday `return mf.transfer_attempts()` -> `0`; Accuracy `native_value` -> `None`; drop `MusicFollowingAccuracySensor` from the platform list; `dc` anomaly feed `transfer_attempts()` -> `0` / `success_count()` -> `stats.get("success")`; `counters_today` -> `{}`; `transitions.py` `if callable(booker):` -> `if False:` | Display and anomaly-baseline consumers of the registry have no test; the success-nudged share of the anomaly rate (Q17) is the D4 invariant. |

## Other GREEN rows (lower severity, add tests in the same fix-up where cheap)

- **Default-equal hardcodes (#63, tests run at defaults):** N14 release delay 5, N16 stale 15, N18 cooldown 8, N20 lookback 90, N21 nudge settle 3, N24 ping-pong window, N26 options seed `options=dict(cm_config)` -> `{}`. A knob-wired value is only proven when a test sets a NON-default value and sees behaviour change (the N13, N15, N19 and N23 tests do this; copy the pattern). N17 is equivalent (`cooldown_s > 0` guard is redundant with `since < cooldown`).
- **Saved-volume replay details:** V2 (persist on restore), V6 (unloaded speaker stays pending), V9 (replay at next transition), V10 (replay skipped while a move is in flight), V11 (first pre-fade volume kept on a second remember), V12. The main restart paths V1, V3, V4, V5, V7, V8 are RED.
- **Bounce details:** X8 (new move waits for old cleanup), X9 (return window), X10 (cancel outcome booking inside `_run`; on_done backs it up, likely equivalent), X14 (join undo unjoin), X16 (undo gated on target_started), X18 (inflight pop in finally).
- **MA candidate resolution:** MA10 `same_device`, MA11 `is_ma`, MA12 `ha_provider_wrap` GREEN (only `mac_in_ma_id`, MA13, is anchored). The D0 join kinds are the primary-path selector; add one rig per kind. Also MA6 (same-kind target), MA7 (playing source pick), MA9 (MA move must not fade the source), E2/E3 (extend MA leader, `via_ma`), MA3 (target in data vs `target=`; functionally equivalent in HA, fake does not forbid it).
- **Join path:** J3 (`leader_from_attr`), J5 (GROUPING on the target), J6 (same-platform requirement: a cross-brand pair would join), J7 (join target volume).
- **BLE gate:** B6 (slug-normalised compare), B9 (`no_event_ble` counted), B11 (`ble_confidence` stamp).
- **Teardown:** T4 (episode flush), T6 (lookback stamps cleared). T7, T7b (await after cancel) equivalent. T2 is RED only by suite hang.
- **Trip-wire DB window:** W5 (candidate = source_playing), W6 (window start), W7 (DB vs memory prefer rule).
- **Room speaker:** R4 (multiroom rank), R6 (zone player), R7 (disabled entity skipped).
- **Registry/episodes:** C12 (transfer keys include failed), C18 (failed vs verify_failed on path error), D3 (`dedup_source_ref`), D5 (`MF_EPISODE_LOG_PERSIST` switch), D11 (episode tasks tracked).
- **Moves:** Y10 (nudge generic only), Y14 (MA path remembers source volume), Y15 (no content -> failed), Y21 (reversal watch cancelled at next move), Y22 (per-room volume scaling), Y23 (same-speaker block), Y25 (source None), Y42/Y43/Y44 (lookback room/playing checks, direct-source playing check), Q3 (source-resumed reversal kind), Q5 (reversal window expiry), Q11 (digest most-common-skip).
- **apply_config validation:** A10 (invalid follow mode), A11 (negative clamp), A12 (invalid certainty); A7 (bonus players tracked for hazard), A8 (exception restores saved volumes); V17 equivalent (exception type in restore).

## Requested confirmations

| Item | Result |
|---|---|
| `person_coordinator._calculate_confidence` and distance | Byte-identical to develop: `git diff d0a25cbc...HEAD -- person_coordinator.py` is one hunk (the three additive event keys), zero mentions of `_calculate_confidence` or `closest_distance`. Nothing to anchor. |
| Producer event keys (`method`, `bermuda_area`, `area_sensor`) | NOT anchored at the producer (G1-G3 GREEN); anchored at the detector copy (G4-G6 RED via `test_mf_event_carries_ble_facts_to_listeners`). |
| Bedroom read via preference provider | NOT anchored (Y36-Y38 GREEN). Add a `dwell_only` test with a provider returning `{"bedroom": ...}`: bedroom target passes, other room `night_suppressed`, no provider -> `night_suppressed`. |
| Dwell gate really gone | G7 (reinstate a transition.confidence gate) RED: `test_mf_five_minute_dwell_then_walk_transfers`. |

## Required-site coverage (RED = a specific test fails)

| Required site | Rows | Result |
|---|---|---|
| Join direction / leader | J1, J2, J4 | RED `test_mf_join_leader_is_source`, `test_mf_chained_move_joins_to_group_leader`, `test_mf_move_mode_skips_join_when_leader_release_unsafe`; J3, J5-J7 GREEN |
| MA transfer_queue keys | MA1, MA2, MA4, MA5 | RED (`test_mf_ma_payload_target_and_source_player`, `test_mf_ma_skipped_when_ma_source_not_playing`); MA3 equivalent |
| Extend joins target to playing source | E1, E4, E5 | RED (`test_mf_extend_mode_on_ma_pair_keeps_source_playing`, `test_mf_extend_mode_never_quiets_source`); E2, E3 GREEN |
| BLE gate: room mismatch, any, saved strict | B1, B2, B3 | RED (`test_mf_ble_low_confidence_skips`, `test_mf_ble_any_mode_skips_check`, `test_mf_knobs_live_after_options_update`) |
| Source-room-others guard | O1, O5-O7 | RED; O2-O4 GREEN |
| Hazard scope / in-flight cancel / block | H1, H5, H7-H10, H12, H14, H15 | RED; H16, H2-H4, H6, H11, H13 GREEN |
| Lock released before verify | L1 | RED `test_mf_lock_released_before_verify_wait`; L2 GREEN |
| Saved volumes persisted / replayed / hand-set respected | V1, V3, V4, V5, V7, V8 | RED; V2, V6, V9-V12 GREEN |
| Teardown restores orphan volumes | T1 | RED `test_mf_teardown_restores_orphan_saved_volume` |
| Bounce during source stop | X1, X2 | RED `test_mf_bounce_during_source_stop_keeps_one_room_playing` |
| Cancel during start call | S3, S4 | RED (generic only); S1, S2 GREEN |
| Trip-wire counted from persisted rows | W1 | RED `test_mf_tripwire_counts_persisted_decisions_after_restart` |
| Parent-unload teardown | T8, T9 | RED `test_mf_parent_unload_tears_music_following_down` |
| Room speaker by area id | R1, R2, R3, R5 | RED `test_mf_room_player_by_area_id_not_name` |
| Per-room opt-out both directions | P1, P2, P3 | RED |
| Counted outcomes (one per transition) | C1-C7, C9-C11, C13-C17 | RED; C8 GREEN |
| Decision episode writer | D1, D2, D4, D6-D10, D12, D13 | RED; D3, D5, D11 GREEN |
| Reload listener leak | K2, K3, K9, T10 | RED; K4-K8 (sensors) GREEN |
| Dead timing knobs wired | N1-N13, N15, N19, N22, N23, N25, N27-N29 | RED; N14, N16-N18, N20, N21, N24, N26 GREEN |

## Full mutation table (id | site | result | first RED test)

| id | site | result | test |
|---|---|---|---|
| J1 | join direction (leader=source) | RED | test_mf_join_leader_is_source |
| J2 | chained leader (mf_group) | RED | test_mf_chained_move_joins_to_group_leader |
| J3 | leader_from_attr | GREEN |  |
| J4 | leader-release-unsafe -> generic | RED | test_mf_ma_skipped_when_ma_source_not_playing |
| J5 | join needs GROUPING on both | GREEN |  |
| J6 | join same platform | GREEN |  |
| J7 | join target volume = source volume | GREEN |  |
| MA1 | MA payload source_player key | RED | test_mf_five_minute_dwell_then_walk_transfers |
| MA2 | MA auto_play | RED | test_mf_ma_payload_target_and_source_player |
| MA3 | MA target via target= (not data) | GREEN |  |
| MA4 | MA only if MA source reads playing | RED | test_mf_ma_skipped_when_ma_source_not_playing |
| MA5 | MA-first knob | RED | test_mf_five_minute_dwell_then_walk_transfers |
| MA6 | MA target same-kind pick | GREEN |  |
| MA7 | MA source = the playing candidate | GREEN |  |
| MA8 | MA blocking service call | RED | test_mf_bonus_join_failure_does_not_fail_move |
| MA9 | MA path does not fade/stop source (volume only remembered) | GREEN |  |
| MA10 | MA candidate: same_device match | GREEN |  |
| MA11 | MA candidate: is_ma entity | GREEN |  |
| MA12 | MA candidate: ha_provider_wrap | GREEN |  |
| MA13 | MA candidate: mac_in_ma_id | RED | test_mf_five_minute_dwell_then_walk_transfers |
| E1 | extend on MA pair: branch | RED | test_mf_extend_mode_on_ma_pair_keeps_source_playing |
| E2 | extend MA join leader = MA source | GREEN |  |
| E3 | extend via_ma flag (bonus platform) | GREEN |  |
| E4 | extend: no fade (move-only fade) | RED | test_mf_extend_mode_never_quiets_source |
| E5 | extend: no release | RED | test_mf_chained_move_joins_to_group_leader |
| B1 | BLE room mismatch skip | RED | test_mf_ble_low_confidence_skips |
| B2 | BLE any mode skips check | RED | test_mf_ble_any_mode_skips_check |
| B3 | saved strict reads as normal | RED | test_mf_knobs_live_after_options_update |
| B4 | BLE no-location fails open | RED | test_mf_ble_no_location_fails_open_counted_once |
| B5 | BLE input_missing counted | RED | test_mf_ble_no_location_fails_open_counted_once |
| B6 | BLE slug-normalised room compare | GREEN |  |
| B7 | layer unknown/unavailable -> None | RED | test_mf_ble_no_location_fails_open_counted_once |
| B8 | BLE gate called in pipeline | RED | test_mf_ble_low_confidence_skips |
| B9 | BLE no_event_ble counted | GREEN |  |
| B10 | layer read via public get_person_location | RED | test_mf_ble_low_confidence_skips |
| B11 | any-mode decision still stamps certainty | GREEN |  |
| O1 | source_has_others guard | RED | test_mf_lookback_source_with_others_skips |
| O2 | others: skip self (person key) | GREEN |  |
| O3 | others: self never skipped | GREEN |  |
| O4 | others: slug compare room | GREEN |  |
| O5 | others: substrate secondary | RED | test_secondary_untracked_occupancy_kind_suppresses |
| O6 | others: layer tracked_persons loop | RED | test_mf_lookback_source_with_others_skips |
| O7 | others: layer match returns True | RED | test_mf_lookback_source_with_others_skips |
| H1 | hazard scope: started players | RED | test_mf_hazard_stop_reaches_area_resolved_primary |
| H2 | hazard scope: active groups | GREEN |  |
| H3 | hazard scope: bonus joined | GREEN |  |
| H4 | hazard scope: MA twins | GREEN |  |
| H5 | hazard scope: configured room player | RED | test_mf_hazard_stop_scoped_to_room_players |
| H6 | hazard scope: zone player | GREEN |  |
| H7 | hazard in-flight cancel | RED | test_mf_hazard_cancels_inflight_and_blocks_new_moves |
| H8 | hazard cancel outcome hazard_blocked | RED | test_mf_hazard_cancels_inflight_and_blocks_new_moves |
| H9 | hazard block window set | RED | test_mf_hazard_cancels_inflight_and_blocks_new_moves |
| H10 | hazard blocks new moves (transition) | RED | test_mf_hazard_cancels_inflight_and_blocks_new_moves |
| H11 | hazard blocks manual transfer | GREEN |  |
| H12 | hazard stops only playing/paused | RED | test_mf_hazard_stop_scoped_to_room_players |
| H13 | hazard cancels reversal watches | GREEN |  |
| H14 | hazard stop issues media_stop | RED | test_mf_hazard_stop_scoped_to_room_players |
| H15 | hazard stop wired from coordinator | RED | test_mf_hazard_stop_scoped_to_room_players |
| H16 | hazard stop unblocks after window (monotonic) | GREEN |  |
| H17 | hazard: the single-block-check at _pipeline-time (cancel -> hazard outcome reason) | GREEN |  |
| L1 | lock released before verify wait | RED | test_mf_lock_released_before_verify_wait |
| L2 | lock held for gates + start call (house-wide lock) | GREEN |  |
| L3 | unlock idempotent only when held | RED | test_mf_manual_transfer_verifies_before_release |
| V1 | persist on remember | RED | test_mf_saved_volume_survives_restart |
| V2 | persist on restore | GREEN |  |
| V3 | persist writes the store | RED | test_mf_saved_volume_survives_restart |
| V4 | replay: tolerance (hand-set respected) | RED | test_mf_restart_replay_leaves_hand_set_volume |
| V5 | replay: hand-set dropped from saved | RED | test_mf_restart_replay_leaves_hand_set_volume |
| V6 | replay: unloaded speaker stays pending | GREEN |  |
| V7 | replay at init | RED | test_mf_init_replays_saved_volumes |
| V8 | replay loads persisted store | RED | test_mf_saved_volume_survives_restart |
| V9 | replay on next transition | GREEN |  |
| V10 | replay not while a move is in flight | GREEN |  |
| V11 | remember keeps first (pre-fade) volume | GREEN |  |
| V12 | replay persists after hand-set drop | GREEN |  |
| V13 | restore pops saved (no leak) | RED | test_mf_fade_undone_when_target_not_playing |
| V14 | restore_saved restores each player | RED | test_mf_move_mode_quiets_source_after_target_playing[generic] |
| V15 | volume set call uses entity+level | RED | test_mf_move_mode_quiets_source_after_target_playing[ma] |
| V16 | fade target volume knob | RED | test_mf_move_mode_quiets_source_after_target_playing[generic] |
| V17 | restore volume survives service error | GREEN |  |
| T1 | teardown restores orphan volumes | RED | test_mf_teardown_restores_orphan_saved_volume |
| T2 | teardown cancels in-flight tasks | RED(hang) | no named assertion: suite hangs at teardown (20 s timeout) |
| T3 | teardown unsubscribes reversal watches | RED | test_mf_five_minute_dwell_then_walk_transfers |
| T4 | teardown flushes episode writes | GREEN |  |
| T5 | teardown clears groups | RED | test_async_teardown_clears_state |
| T6 | teardown clears lookback stamp | GREEN |  |
| T7 | teardown awaits cancelled tasks | GREEN |  |
| T8 | parent unload tears MF down | RED | test_mf_parent_unload_tears_music_following_down |
| T9 | parent-unload helper calls teardown | RED | test_mf_parent_unload_tears_music_following_down |
| T10 | coordinator teardown cleans MF | RED | test_mf_reload_does_not_duplicate_listeners |
| X1 | bounce: source_released flag set before stop | RED | test_mf_bounce_during_source_stop_keeps_one_room_playing |
| X2 | bounce: released-source branch keeps target | RED | test_mf_bounce_during_source_stop_keeps_one_room_playing |
| X3 | bounce: cleanup undoes target (non-release phase) | RED | test_mf_bounce_during_fade_restores_and_keeps_queue |
| X4 | bounce: cleanup restores volume (non-release phase) | RED | test_mf_bounce_during_fade_restores_and_keeps_queue |
| X5 | bounce: records last_superseded | RED | test_mf_bounce_during_fade_restores_and_keeps_queue |
| X6 | bounce: returned_in_flight when playing | RED | test_mf_bounce_during_fade_restores_and_keeps_queue |
| X7 | bounce: newer change cancels older | RED | test_mf_bounce_during_fade_restores_and_keeps_queue |
| X8 | bounce: new waits for old cleanup | GREEN |  |
| X9 | bounce: return match window fresh | GREEN |  |
| X10 | bounce: superseded outcome booked on cancel | GREEN |  |
| X11 | bounce: cleanup runs on cancel | RED | test_mf_bounce_during_fade_restores_and_keeps_queue |
| X12 | bounce: releasing-phase other room completes release | RED | test_mf_bounce_to_third_room_during_release_completes_move |
| X13 | bounce: releasing-phase back to source undo | RED | test_mf_bounce_after_target_plays_before_release |
| X14 | bounce: undo_target join unjoin | GREEN |  |
| X15 | bounce: undo_target generic stop | RED | test_mf_bounce_during_fade_restores_and_keeps_queue |
| X16 | bounce: undo gated on target_started | GREEN |  |
| X17 | bounce: on_done books cancelled-before-start | RED | test_mf_rapid_triple_bounce_one_room_playing_volumes_restored |
| X18 | bounce: inflight cleared in finally | GREEN |  |
| S1 | cancel during MA start: mark before call | GREEN |  |
| S2 | cancel during join start: mark before call | GREEN |  |
| S3 | cancel during generic start: mark before call | RED | test_mf_cancel_during_start_call_undoes_target |
| S4 | start-call cancel propagates (not swallowed) | RED | test_mf_cancel_during_start_call_undoes_target |
| W1 | tripwire: DB window source | RED | test_mf_tripwire_counts_persisted_decisions_after_restart |
| W2 | tripwire: fires on zero success | RED | test_mf_silent_tripwire_fires_on_zero_success |
| W3 | tripwire: floor boundary | RED | test_mf_silent_tripwire_fires_on_zero_success |
| W4 | tripwire: success counts | RED | test_mf_silent_tripwire_quiet_with_one_success |
| W5 | tripwire: DB candidate = source_playing | GREEN |  |
| W6 | tripwire: DB read passes since window | GREEN |  |
| W7 | tripwire: DB out-counted-by-memory fallback | GREEN |  |
| W8 | tripwire: fire_stuck_signal kind | RED | test_mf_silent_tripwire_fires_on_zero_success |
| W9 | tripwire: top skip reasons | RED | test_mf_silent_tripwire_fires_on_zero_success |
| W10 | nightly op registered | RED | test_mf_nightly_op_registered |
| W11 | nightly DB wrapper delegates | RED | test_mf_nightly_accuracy_rollup_from_db |
| W12 | accuracy 7d rollup successes from rows | RED | test_mf_nightly_accuracy_rollup_from_db |
| W13 | accuracy 7d rollup reversals | RED | test_mf_nightly_accuracy_rollup_from_db |
| W14 | decision recorded to recent window | RED | test_mf_digest_section_counts |
| R1 | room player by area_id | RED | test_mf_room_player_by_area_id_not_name |
| R2 | room player: area membership test | RED | test_mf_hallway_walk_through_transfers_from_last_playing_room |
| R3 | room player: device-area fallback | RED | test_mf_room_player_by_area_id_not_name |
| R4 | room player: multiroom ranked first | GREEN |  |
| R5 | room player: configured entity wins | RED | test_mf_bonus_joins_after_primary_success |
| R6 | room player: zone player | GREEN |  |
| R7 | room player: disabled entities skipped | GREEN |  |
| P1 | opt-out: source room | RED | test_mf_source_room_opted_out_never_moves_music_out |
| P2 | opt-out: target room | RED | test_mf_room_opted_out_is_no_target_player |
| P3 | opt-out: source outcome reason (no_source_player) | RED | test_mf_source_room_opted_out_never_moves_music_out |
| C1 | one outcome: _finish idempotent | RED | test_mf_bounce_during_fade_restores_and_keeps_queue |
| C2 | outcome counted in stats | RED | test_mf_bounce_during_fade_restores_and_keeps_queue |
| C3 | outcome: coordinator_disabled | RED | test_mf_every_transition_has_exactly_one_outcome |
| C4 | outcome: person_not_enabled | RED | test_mf_every_transition_has_exactly_one_outcome |
| C5 | outcome: same_room | RED | test_mf_every_transition_has_exactly_one_outcome |
| C6 | outcome: exception | RED | test_mf_every_transition_has_exactly_one_outcome |
| C7 | outcome: ping_pong_suppressed | RED | test_mf_ping_pong_suppression_books_one_decision |
| C8 | outcome: hazard_blocked (transition) | GREEN |  |
| C9 | unknown outcome counted | RED | test_mf_record_stat_unknown_name_is_counted |
| C10 | registry: returned_in_flight member | RED | test_mf_bounce_during_fade_restores_and_keeps_queue |
| C11 | registry: skip set | RED | test_mf_registry_is_single_source |
| C12 | registry: transfer keys include failed | GREEN |  |
| C13 | registry: success outcomes include nudged | RED | test_mf_registry_is_single_source |
| C14 | registry: outcomes_today | RED | test_mf_registry_is_single_source |
| C15 | outcome: stale_transition | RED | test_mf_stale_transition_outcome |
| C16 | outcome: success books at verify (before release) | RED | test_mf_five_minute_dwell_then_walk_transfers |
| C17 | outcome: verify_failed | RED | test_mf_fade_undone_when_target_not_playing |
| C18 | outcome: failed on path error | GREEN |  |
| C19 | counters in diagnostics | GREEN |  |
| C20 | ping-pong booker in detector | GREEN |  |
| D1 | episode: written per candidate decision | RED | test_mf_episode_written_per_decision |
| D2 | episode: window_dedup False | RED | test_mf_episode_survives_window_dedup |
| D3 | episode: dedup_source_ref True | GREEN |  |
| D4 | episode: node = target room | RED | test_mf_episode_written_per_decision |
| D5 | episode: persist kill switch honoured | GREEN |  |
| D6 | episode: attrs carry decision fields | RED | test_mf_episode_written_per_decision |
| D7 | episode: candidate = both players | RED | test_mf_episode_not_written_without_players |
| D8 | episode: reversal episode written | RED | test_mf_nightly_accuracy_rollup_from_db |
| D9 | episode: source_playing attr (tripwire candidate) | RED | test_mf_tripwire_counts_persisted_decisions_after_restart |
| D10 | episode: source_ref deterministic | RED | test_mf_episode_written_per_decision |
| D11 | episode: tracked task flushed | GREEN |  |
| D12 | episode types registered (const) | RED | test_mf_episode_written_per_decision |
| D13 | episode: DAO read-by-type | RED | test_mf_nightly_accuracy_rollup_from_db |
| K2 | listener: unsub removes | RED | test_mf_reload_does_not_duplicate_listeners |
| K3 | listener: coordinator stores unsub | RED | test_mf_reload_does_not_duplicate_listeners |
| K4 | listener: Health sensor async_on_remove | GREEN |  |
| K5 | listener: TransfersToday sensor async_on_remove | GREEN |  |
| K6 | listener: ActiveRooms sensor async_on_remove | GREEN |  |
| K7 | listener: Accuracy sensor async_on_remove | GREEN |  |
| K8 | listener: LastTransfer sensor async_on_remove | GREEN |  |
| K9 | listener: coordinator teardown invokes unsub | RED | test_mf_reload_does_not_duplicate_listeners |
| K10 | transition detector listener registered at init | GREEN |  |
| N1 | knob apply: verify delay | RED | test_mf_bounce_after_target_plays_before_release |
| N2 | knob apply: release delay | RED | test_mf_knobs_live_after_options_update |
| N3 | knob apply: position offset | RED | test_mf_generic_seek_uses_position_offset_knob |
| N4 | knob apply: stale | RED | test_mf_knobs_live_after_options_update |
| N5 | knob apply: cooldown | RED | test_mf_path_order_ma_then_native_then_generic |
| N6 | knob apply: lookback | RED | test_mf_lookback_zero_disables |
| N7 | knob apply: follow mode | RED | test_mf_join_leader_is_source |
| N8 | knob apply: bonus joins | RED | test_mf_bonus_off_knob |
| N9 | knob apply: ble certainty | RED | test_mf_ble_any_mode_skips_check |
| N10 | knob apply: sleep suppress | RED | test_mf_knobs_live_after_options_update |
| N11 | knob apply: night mode | RED | test_mf_every_transition_has_exactly_one_outcome |
| N12 | knob apply: ping-pong pushed to detector | RED | test_mf_knobs_live_after_options_update |
| N13 | knob use: verify delay | RED | test_mf_bounce_after_target_plays_before_release |
| N14 | knob use: release delay | GREEN |  |
| N15 | knob use: position offset | RED | test_mf_generic_seek_uses_position_offset_knob |
| N16 | knob use: stale | GREEN |  |
| N17 | knob use: cooldown enable | GREEN |  |
| N18 | knob use: cooldown value | GREEN |  |
| N19 | knob use: lookback enable | RED | test_mf_lookback_zero_disables |
| N20 | knob use: lookback value | GREEN |  |
| N21 | knob use: nudge settle | GREEN |  |
| N22 | knob: detector ping-pong window setter | RED | test_mf_knobs_live_after_options_update |
| N23 | knob: detector ping-pong 0 = off | RED | test_mf_ping_pong_window_live_and_zero_disables |
| N24 | knob: detector ping-pong uses window | GREEN |  |
| N25 | live keys: apply_config dispatch in _apply_in_place | RED | test_mf_knobs_live_after_options_update |
| N26 | live keys: seed options into coordinator | GREEN |  |
| N27 | live keys: coordinator merges options | RED | test_mf_coordinator_setup_pushes_knobs_into_engine |
| N28 | live keys: coordinator pushes apply_config at setup | RED | test_mf_coordinator_setup_pushes_knobs_into_engine |
| N29 | live keys: arrival switch applied | RED | test_mf_knobs_live_after_options_update |
| Y1 | verify gate: target must read playing | RED | test_mf_fade_undone_when_target_not_playing |
| Y2 | release: runs after success | RED | test_mf_move_mode_quiets_source_after_target_playing[generic] |
| Y3 | release: join unjoin source | GREEN |  |
| Y4 | release: generic media_stop source | RED | test_mf_move_mode_quiets_source_after_target_playing[generic] |
| Y5 | release: restore volume in finally | RED | test_mf_move_mode_quiets_source_after_target_playing[generic] |
| Y6 | release: bonus unjoin on move out | RED | test_mf_bonus_released_on_next_move_out |
| Y7 | verify fail: fade undone | RED | test_mf_fade_undone_when_target_not_playing |
| Y8 | verify: primary only | RED | test_mf_verify_reads_native_primary_not_ma_twin |
| Y9 | nudge: own media only (content match) | RED | test_mf_nudge_only_on_own_generic_media |
| Y10 | nudge: generic path only | GREEN |  |
| Y11 | nudge: success_nudged outcome | RED | test_mf_nudge_only_on_own_generic_media |
| Y12 | nudge: media_play issued | RED | test_mf_fade_undone_when_target_not_playing |
| Y13 | move: fade after start call only (never before) | RED | test_mf_move_mode_quiets_source_after_target_playing[generic] |
| Y14 | move: MA path remembers source volume | GREEN |  |
| Y15 | start: generic content absent -> failed | GREEN |  |
| Y16 | start: generic seek | RED | test_mf_generic_seek_uses_position_offset_knob |
| Y17 | success records cooldown time | GREEN |  |
| Y18 | success records cooldown target | GREEN |  |
| Y19 | success: active group recorded for join | RED | test_mf_chained_move_joins_to_group_leader |
| Y20 | success: reversal watch started | RED | test_mf_reversal_target_paused_by_person |
| Y21 | move: reversal watch cancelled at next move | GREEN |  |
| Y22 | target volume scaled per room | GREEN |  |
| Y23 | active playback: same speaker | GREEN |  |
| Y24 | active playback: target playing | RED | test_mf_active_playback_blocked_when_target_playing |
| Y25 | source must be playing | GREEN |  |
| Y26 | target unavailable | RED | test_mf_every_transition_has_exactly_one_outcome |
| Y27 | no target player | RED | test_mf_hallway_walk_through_transfers_from_last_playing_room |
| Y28 | manual transfer result | RED | test_mf_manual_transfer_verifies_before_release |
| Y29 | manual transfer: runs helper | RED | test_mf_manual_transfer_verifies_before_release |
| Y30 | pipeline: house state gate | RED | test_mf_every_transition_has_exactly_one_outcome |
| Y31 | pipeline: stale gate | RED | test_mf_stale_transition_outcome |
| Y32 | pipeline: cooldown gate | RED | test_mf_every_transition_has_exactly_one_outcome |
| Y33 | pipeline: preference follow_mode | RED | test_mf_preference_provider_overrides_mode_and_volume |
| Y34 | pipeline: preference target_volume | RED | test_mf_preference_provider_overrides_mode_and_volume |
| Y35 | pipeline: preferences consulted | RED | test_mf_preference_provider_overrides_mode_and_volume |
| Y36 | bedroom via preference provider | GREEN |  |
| Y37 | bedroom: provider purpose key | GREEN |  |
| Y38 | bedroom: dwell_only compare | GREEN |  |
| Y39 | house-state: sleep gate | RED | test_mf_every_transition_has_exactly_one_outcome |
| Y40 | house-state: night block_all | RED | test_mf_every_transition_has_exactly_one_outcome |
| Y41 | source stamped (lookback) | RED | test_mf_hallway_walk_through_transfers_from_last_playing_room |
| Y42 | lookback: room must differ from target | GREEN |  |
| Y43 | lookback: stamp still playing | GREEN |  |
| Y44 | source: from-room direct playing | GREEN |  |
| Y45 | source: no source player outcome | RED | test_mf_lookback_expired_records_no_source_player |
| Z1 | bonus: knob off | RED | test_mf_bonus_off_knob |
| Z2 | bonus: after success | RED | test_mf_bonus_joins_after_primary_success |
| Z3 | bonus: failure counted | RED | test_mf_bonus_join_failure_does_not_fail_move |
| Z4 | bonus: failure swallowed | GREEN |  |
| Z5 | bonus: grouping feature required | RED | test_mf_bonus_never_joins_non_grouping_speaker |
| Z6 | bonus: same-platform filter | GREEN |  |
| Z7 | bonus: primary device excluded | GREEN |  |
| Z8 | bonus: area filter | RED | test_mf_join_leader_is_source |
| Z9 | bonus: leader = group leader | GREEN |  |
| Z10 | bonus: joined recorded for release | RED | test_mf_bonus_released_on_next_move_out |
| Z11 | bonus: unavailable skipped | GREEN |  |
| Z12 | bonus: MA candidate mapping when MA path | RED | test_mf_bonus_joins_after_primary_success |
| Z13 | bonus: platform want MA when MA/via_ma | GREEN |  |
| Q1 | reversal: URA context ignored | RED | test_mf_ura_context_stop_of_target_is_not_reversal |
| Q2 | reversal: target stopped kind | RED | test_mf_reversal_target_paused_by_person |
| Q3 | reversal: source resumed kind | GREEN |  |
| Q4 | reversal: recorded | RED | test_mf_reversal_target_paused_by_person |
| Q5 | reversal: window expiry | GREEN |  |
| Q6 | reversal: accuracy pct | RED | test_mf_reversal_target_paused_by_person |
| Q7 | accuracy: live successes counted | RED | test_mf_reversal_target_paused_by_person |
| Q8 | accuracy: by pair/kind | RED | test_mf_reversal_target_paused_by_person |
| Q9 | digest: empty with no candidates | RED | test_mf_digest_section_counts |
| Q10 | digest: wired into NM digest | RED | test_mf_digest_line_reaches_delivered_nm_digest |
| Q11 | digest: most common skip | GREEN |  |
| Q12 | digest: played count | RED | test_mf_digest_section_counts |
| Q13 | sensor: transfer attempts | GREEN |  |
| Q14 | sensor: accuracy pct | GREEN |  |
| Q15 | sensor: accuracy registered | GREEN |  |
| Q16 | anomaly feed: attempts from registry | GREEN |  |
| Q17 | anomaly feed: success from registry | GREEN |  |
| G1 | event: method key | GREEN |  |
| G2 | event: bermuda_area key | GREEN |  |
| G3 | event: area_sensor key | GREEN |  |
| G4 | transition carries ble_method | RED | test_mf_event_carries_ble_facts_to_listeners |
| G5 | transition carries ble_area | RED | test_mf_event_carries_ble_facts_to_listeners |
| G6 | transition carries ble_area_sensor | RED | test_mf_event_carries_ble_facts_to_listeners |
| G7 | dwell gate gone: transition.confidence not gated | RED | test_mf_five_minute_dwell_then_walk_transfers |
| A1 | decision log line | RED | test_mf_decision_log_line_has_all_fields |
| A2 | last_decision stored | RED | test_mf_five_minute_dwell_then_walk_transfers |
| A3 | per-person enabled gate | RED | test_mf_every_transition_has_exactly_one_outcome |
| A4 | coordinator kill switch gate | RED | test_mf_every_transition_has_exactly_one_outcome |
| A5 | same-room gate | RED | test_mf_every_transition_has_exactly_one_outcome |
| A6 | started players tracked | RED | test_mf_hazard_stop_reaches_area_resolved_primary |
| A7 | bonus players tracked for hazard | GREEN |  |
| A8 | run: exception restores saved | GREEN |  |
| A9 | run: lock held across pipeline start | GREEN |  |
| A10 | apply_config: invalid ignored (follow mode) | GREEN |  |
| A11 | apply_config: lower-bound clamp | GREEN |  |
| A12 | apply_config: invalid certainty ignored | GREEN |  |
| A13 | extend-mode record snapshot per move | RED | test_mf_join_leader_is_source |
| T7b | hazard awaits cancelled in-flight tasks | GREEN |  |

Notes: `T2` hangs the suite at teardown (RED by hang, no named assertion). `T7`/`T7b` and `V17`, `N17`, `MA3` are equivalent mutants. Tree left clean (`git status` shows only the untracked `.claude/tmp/`); reviewer drill scripts deleted.

## Must-fix list

C-1 to C-14 above. Minimum new tests: hazard-expiry with fake clock (C-1); real success arms cooldown then a second move is `cooldown_blocked` (C-2); join-path move asserts `unjoin` on the source (C-3); MA and join cancel-during-start undo the target (C-4); `async_init` registers on the detector (C-5); sensor `async_on_remove` called for all 5 sensors (C-6); `dwell_only` with a bedroom provider (C-7); non-default knob values for release delay, stale, cooldown, lookback (default-equal hardcodes); hazard stop reaches group followers, bonus players, MA twins, zone player; hazard-blocked outcome in the one-outcome table; two-person lock.
