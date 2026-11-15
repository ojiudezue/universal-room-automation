# Layer ship 3b, review C: test authority by real per-site source mutation

Candidate `feature/layer-ship3b` @ 00bba209 (develop v5.108.24 + the 3b commits). Framing C only.
Read first: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` completely (its ship 3b entry and ledger #41), plan §6 / §6.10 as cited in the brief, and reviews A / B / D / G / D2 for context. The builder's drill scripts (`.claude/tmp/b3b_drills.py`, `b3fx_drills.py`) were not used; the 544 mutations below were enumerated from `git diff 28978d2a..00bba209` over `custom_components/` and written fresh.

## Method

- One mutation = one edit of one production site (file written, test run, file restored in a `finally`; `git status` clean after every batch, only the untracked `.claude/tmp` that already existed).
- `__pycache__` purged before every run, `python -B`, `PYTHONDONTWRITEBYTECODE=1`.
- Test set per mutation: the four cycle files `test_camera_twin_health.py`, `test_camera_twin_health_setup_wirein.py`, `test_camera_stream_health.py`, `test_camera_stream_health_s2.py` (278 tests, green baseline); sites in `_stuck_signal_nm.py`, `camera_resolver.py`, `diagnostics.py` also ran `test_stuck_signal_watchdog.py`, `test_camera_resolver.py`, `test_person_awareness_layer_ship3a.py`; the guard read-list rows ran `test_person_awareness_layer_guard.py`.
- Every row that stayed GREEN was then re-run against a wider "EXT" set (the other consumers of the module: `test_crossing_ledger_wiring`, `test_zone_tracker_per_entity`, `test_camera_census`, `test_stuck_signal_watchdog`, `test_camera_resolver`, `test_room_substrate_integration`, `test_zone_substrate_migration`; 245 tests). EXT killed none of the 188 GREEN rows, so none of them is covered elsewhere.
- Two of my mutations were invalid and are excluded: Z44 (a syntax error from my edit, re-done as Z44b) and Z9 (a no-op edit). W17 and Z51 first mis-matched their anchor and were redone as W17a and Z51b.
- Totals: 542 valid mutations, 354 RED, 188 GREEN. Of the GREEN rows, roughly 70 are equivalent mutants or double-guarded defences (section 3); the rest are test gaps (section 2).

## Verdict: FIX-REQUIRED (test gaps; no production defect found by mutation)

Two HIGH test gaps, both load-bearing production paths that no test pins. Nothing in this pass shows the production code to be wrong; the gaps are places where a later edit could silently break a page path and the suite would stay green.

### Must-fix list (HIGH)

1. **TG-1 The owner's tick is never asserted to be scheduled** (`camera_twin_health.py:214`, `async_track_time_interval(...)` in `async_setup`; row X118 GREEN, plus F8 `CAMERA_TWIN_HEALTH_TICK_S` 30 -> 3000 GREEN). Every test calls `owner.tick(now)` by hand. Deleting the scheduling leaves a house tracker that never evaluates, no U stamps, no group pages, no LOW, with a fully green suite. The CM wire-in tests pin creation and teardown (Z30 / Z31 RED) but not that the created owner ticks. Needs a wire-in anchor: after `async_setup`, the interval is registered with the right period, and firing it calls `tick`. (Same family as the registry-listener rows X116 / X117, which ARE RED.)
2. **TG-2 `send_page_and_mark` ALREADY_SENT latch is untested** (`camera_stream_health.py:1033`, `if result in (SENT, ALREADY_SENT)`; rows S1 GREEN; owner twin at `camera_twin_health.py:1030` X91 GREEN). No test calls `send_page_and_mark` with an ALREADY_SENT result through a room tracker. Mutated to `SENT` only, an ALREADY_SENT room page is never latched: `_paged_episode` stays empty, so `evaluate` re-offers the candidate every tick and never emits the LOW (`to_recover` iterates `_paged_episode`), and the NM notified-set keeps `(kind, key)`, so the next outage reads ALREADY_SENT forever: a silent missed page. Legal-config repro: a page sent by the old room tracker or the owner, then a room reload (RAM latches reset, notified set survives). Needs a test driving a room through ALREADY_SENT and asserting the episode latch, the LOW at recovery and a fresh HIGH on the next outage.

### Should-fix (MEDIUM)

3. **TG-3 Page key vs own camera on the S2 LOW round trip** (rows L6 `csh:548`, H11 `csh:514`, S5 `csh:1034`, Z20 `coordinator.py` hold-page call, Z5 `coordinator.py` S1 group key all GREEN). The room stores the page key it sent (`_hold_paged[pid] = (ident, page_key or ident)`) so the LOW uses the same key; with the key replaced by the own camera the LOW goes to a key that was never notified, `fire_stuck_signal_recovered` returns False, the HIGH stays latched and the next outage is silent. Only differs when the pure page key (the Frigate camera) is not the device's own camera, i.e. a Protect device in a W1 pair whose room pages (owner absent, group out of scope, or past the bounded DEFER). No fixture has a room paging a paired Protect device and recovering it.
4. **TG-4 The room input list is only half pinned** (`camera_stream_health.py:944-950`, `room_stream_input_entities`). I1 (`{**data, **options}` flipped to data-over-options) GREEN, I2 (`CONF_OCCUPANCY_SENSORS` dropped) GREEN, I4 (`CONF_MOTION_SENSORS` dropped) GREEN; only the mmwave list (I3) is pinned. This is "THE one room-input list" feeding Wr, so a missed list or a wrong merge order makes the owner treat a watched device as unwatched (it enters U) or page twice. Same data-vs-options order for the zone picks in `presence.zone_camera_entities` (Z41 GREEN; Z40, the zone-manager entry-type filter, is equivalent). Bug class #53 (one missed site of three).
5. **TG-5 Restored placeholder input is not tested as "not held"** (`camera_stream_health.py:643-647`, the `_is_restored(st)` clause of `is_unavailable_held`, row U10 GREEN; the same clause in `_classify_unavailable_inputs`, U3 GREEN). Without it, a Frigate input reading `unavailable` + `restored: True` (integration in setup retry) with a live-or-no-opinion camera is HELD from t0, and a restored camera never becomes live, so the hold has no end (the cap only runs from a dead stamp). The plan's both-NVRs-in-setup-retry fixture covers cameras, not the input entity.
6. **TG-6 Cross-group isolation of room keys** (`camera_twin_health.py:688-689`, `_member_room_keys` loses its `if dev in group` filter, W102 GREEN). Then `_room_s1_latched(group)` reads every room's S1 latch in the house: any one unrecovered room S1 page makes every group "adopt" it (the owner suppresses its own HIGH), and `_end_episode` sends a LOW for every room input. No test has two unrelated devices with one latched room page.
7. **TG-7 Debounce re-arm** (`camera_twin_health.py:301`, `self._debounce_unsub = None` at the top of `_on_debounce`, X123 GREEN; `:304` pending-event reset X125 GREEN; relevance filter bypass X126 GREEN). Without the reset, after the first fired debounce `_queue_event` returns early forever and the map is never rebuilt again until restart. All map-rebuild tests do one event cycle.
8. **TG-8 Owner teardown does not prove cleanup** (X100 / X101 `_track` bookkeeping, X109 / X110 task cancel and clear, X108 debounce cancel, X107 unsub clear, X111 state getter clear, X105 `data.get(KEY) is self`, X146 the old owner's teardown in `async_setup_camera_twin_health`, all GREEN). `test_unload_mid_debounce_no_rebuild` passes only through the `torn_down` guard, so a leaked timer or an uncancelled in-flight send after unload is invisible (untracked-background-task class). Pop-only-if-self matters when a new owner is created before the old one is torn down.
9. **TG-9 LOW recoveries for caps-0 pages** (`cth:993` owner S1 LOW X78 GREEN; `cth:999-1000` room S1 keys at episode end X81 GREEN; `cth:793-799` adoption-sweep room clause W113 GREEN, W111 GREEN). Only the S2 LOW is asserted. Non-default config (both caps 0) but the failure is the same latched-forever shape as TG-2.
10. **TG-10 Bug class #63: zone cap == census cap (900 == 900) masks which one is used** (H2 `csh:496` `min(caps)` vs max, H5 `csh:500-503` zone-only expiry test, X25 `cth:771` min vs max, X27 / X28 `cth:79-80` each cap alone, all GREEN; E11 / E12 are RED). Tests that set the caps to different values (e.g. 600 / 900, and one of them 0) are missing for the page timing and the page cap text.
11. **TG-11 `CAMERA_INPUT_STREAM_DEAD_NM_AFTER_S = 0` test is masked** (P1 `csh:391` GREEN). `test_nm_after_zero_disables_page_not_exclusion` runs with the default 900 s caps, so the S2 hold page pre-empts the S1 loop (`_hold_due_keys`) and the test passes whether or not the `nm_after_s > 0` gate exists. It needs caps 0 as well. Related room S1 rows: P3 (`csh:395`, episode skip across a local-day change: harmless today because `fire_stuck_signal_ex` returns ALREADY_SENT, but untested), P9 / P10 (input removed mid-episode drops silently, drops its adoption).
12. **TG-12 Fail direction of the error paths is unpinned** (Q9 `csh:1086` an exception in the house tracker returns True = dead instead of no opinion; Y11 `csh:1009-1011` and Z23 `coordinator.py` policy `except` returning SUPPRESS instead of PAGE; Z25 `_camera_stream_page_key` `except` and Z27 the `or own_camera` fallback; T20 `pure_twin_groups` error swallow). Each mutant moves a failure toward "a camera reads dead" or "a page is suppressed": exactly the silent direction. One test per `except` that makes the callee raise.

### Lower (LOW; fix with the above if cheap)

- X14 (`cth:807`, `false_since` not reset when a flapping group goes dead again): a blip then re-death then live ends the episode early. X4 (`cth:780`, `groups = scope | episodes`, an out-of-scope episode is never ended/LOWed). X20 (scope gate before paging). X6 (live stamps not pruned for out-of-scope devices), W42 (`cth:501-503` live stamps survive a long not-ready stretch), W76, W85 (`>=` vs `>` at exactly 600 s settle; grace has 119 / 120 / 121 pins, settle has none).
- Y6 (`csh:1005`, the not-in-map PAGE branch of `room_page_policy`: without it an unpaired device would DEFER while the owner is not sets-ready, up to 600 s from setup; the tests only cover in-map groups and a not-map-ready owner).
- Z29 (`coordinator.py`, the real `_camera_stream_device_registry` HA seam is always monkeypatched; a bad import there is swallowed and rooms silently fall back to the own camera key, which defeats the shared page key). Z44b (`camera_resolver.py` `sorted(...)` on the member set: the canonical camera is `members[0]`; fixtures insert in sorted order so unordered HA iteration would flip it).
- Q26 (`csh:1213`, camera-keyed hold expiry has no house fallback: a camera.* key in U would be HELD forever; callers today pass the person sensor, not a camera entity). W65 / W64 (`cth:589`, `house_tracker_for` keeps answering from stale sets after the camera manager disappears; the reload-window test is green without the guard).
- K10 / K13 (`derived` flag and reason text only feed the unresolved-input WARNING), K15 (`camera_device_for_entity` loses the has-a-camera check: ordinary non-camera room inputs would join Wr and the watched count; harmless to decisions, untested), K17 (resolution cache ignores a runtime flip of the device-level knob), P10, L13, U4 / U6 / U7 (newly-plain bookkeeping), R11 (`dead_stamps` diagnostics), R12 / X111 (state getter clear), X93 / X151 / X152 / X153 / X154 / X155 / X11 (diagnostic counters and fields, untested individually), T7 / T8 / T9 / T10 (`NVR_TWIN_PLATFORMS` membership: only unifiprotect is admitted by a test, esphome rejected; reolink / amcrest / dahua rows are unpinned, and so is a generic non-NVR platform), T1 / T2 / T4 / T5 (`twin_pair_admissible` edge guards, defence in depth behind the W1 pairing; a mixed-platform sibling is not constructible from live data), F7 (`CAMERA_TWIN_MAP_REBUILD_DEBOUNCE_S` 10 -> 0 not pinned), X8 / X9 / X139 (adoption-sweep re-arm on rebuild), X12, X16, X53 (member LOW without the one-grace wait), X67 (MEDIUM text uses the group key), Z47 (`RESOLVER_FRIGATE_OBJECT_NAME_EVIDENCE` off in `frigate_object_name_pairs`), Z50.

## 1. Sites well covered (RED with a specific named test)

Per the brief's list, every site below has at least one RED row in the table (section 4): device resolution and `_key_reading` (K1, K2, K5-K7, K9, K16, K18-K20); evaluate's dead classification (E1-E10, E13); the group clock `_latest_loss` and `_lost` / `_group_dead` (W81-W84, W86-W91, W93); twin-map build and the NVR filter (T3, T6, T11-T17, T26, T28, `test_twin_map_rejects_non_nvr_sibling`); the house-tracker fallback (Q3, Q4, Q10, Q11, W66, W69-W71); page sites S1 (P2, P4-P8, P11-P13), S2 (H1, H3, H4, H6-H8, H10, H12, X30, X31, X33, X34, X37-X41), MEDIUM (X52, X54, X55, X57, X59-X61, X63-X66, X68, X70-X74), LOW (X75-X77, X79, X82, X83) and dissolve (X1-X3); `fire_stuck_signal_ex` SENT / ALREADY_SENT / NOT_SENT and `_SEND_INFLIGHT` (N1, N5-N9, N11); `mark_paged` after send only (S2 always-latch RED, N9 RED, L5, L7, L8, L10); `room_page_policy` / `pages_device` / `not_ready_defer` (Y4, Y5, Y7-Y10, W12, W14-W23, W25-W27); the `_DEAD_ENTRY_STATES` skip (W1-W5, W7); stamp keep / clear on ready (W37-W41, W43); adoption A-L4 (W106-W108, W115, W116, X79) and D-L2 (L11, L12, L14, Z3, Z4, Z10, Z13, Z14); CM setup / unload wiring (Z30, Z31); the coordinator send sites (Z1-Z4, Z6-Z8, Z10, Z13-Z19, Z22, Z24, Z26, Z28); the diagnostics wire-in (Z32, Z34, Z35); the guard read-list entries (G1, G2); const flags F1-F6.

## 2. GREEN rows that are real test gaps

See the must-fix, should-fix and lower lists above; each row id appears in the table below.

## 3. Equivalent mutants and double guards (no test needed), with reasons

- K3 (no `break` after a live member): the value only feeds a `None` / `unknown` / `unavailable` comparison, any live string is equivalent. K4 (`or (key,)` fallback): `_key_members` always holds the key when a resolution has one, unreachable. K21, Y3, T19 and the other `None` guards (X143, X150, Q6, Q7): a `None` registry / owner / tracker raises `AttributeError`, which the surrounding `try` turns into the same no-opinion answer. K12 / K14 / T21 / T27 (device-id guards): duplicated downstream (`camera_device_for_entity`, `page_camera_key`); real HA's device index returns nothing for `None`. T22 (default group `frozenset()`): `page_camera_key` falls through to the own camera either way. T24 / T25 / T29 (all-vs-any platform checks): no mixed-platform device exists. T13 / T18 (registry prime order, pair sort): diagnostics order only. Y12 / Y13 / W11 (`torn_down` on `twin_owner` / `pages_device`): `async_teardown` pops the key itself, so a torn owner is unreachable through `hass.data`. W8 / I9 (`is_room_entry`): non-room entries carry none of the three input lists. W9 (twin rule re-read in `in_map`): a flip leaves the last map but a rebuild under the rule-off returns `{}`. W13 (`in_map` inside `pages_device`): `room_page_policy` already gated on `in_map`. W24 / X32 / X35 / X36 / X47 / X85 / X86 / X69 (duplicate guards: `_send` has the same `torn_down` / `in inflight` test as its callers; `_group_dead` implies a loss stamp). W28 / X112 / X113 / X97 (`tick` and `_on_interval` both test `torn_down`; HA's interval helper already contains a raising callback). W30 / W67 / W68 / W64 / W65 (master-switch off or empty key: rooms have no dead inputs and the tracker is never evaluated, so the answer is the same None / False). W53 / W54 / W52 (sticky bookkeeping is re-set after the prune, and readers filter on `until > now`). W59 / W60 / X145 / X142 / X133 / X134 / X130-X132 (the `_events_relevant` predicates overlap pairwise: any one removed still leaves another that fires on the same events; the filter as a whole is X126 above). W72 (`break` in `_update_loss`: same result). W92 / W94 / W104 / X13 / X24 / X58 / X62 / X80 / X84 / X150 (unreachable empty group, singleton notices, a member that is both dead and alive, duplicated `own != key`). S3 / X90 / N10 / N4 (`fire_stuck_signal_ex` and `fire_stuck_signal` never raise, so the outer `except` is unreachable). Z11 / Z12 (a room LOW for a key it never notified is a no-op in `fire_stuck_signal_recovered`). Z33 (owner popped on teardown). Z9 (my no-op). N12 (test hygiene only). Q12 / Q19 / Q30 (callee returns the same `None` / `False` for a non-camera key, a `None` dead answer and an empty id). A2 (duplicate watched id collapses in the resolution dict).

## 4. Site x mutation x RED test x result (542 rows)

| site (file:line) | mutation | RED test (first) | result |
|---|---|---|---|
| dc/camera_stream_health.py:272 | K1_keyreading_dead_never | test_device_dead_needs_every_channel[two] | RED |
| dc/camera_stream_health.py:270 | K2_keyreading_anylive_lives | test_device_live_if_any_channel_live | RED |
| dc/camera_stream_health.py:266 | K3_keyreading_live_break_removed | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:259 | K4_keyreading_fallback_key | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:712 | K5_member_unknown_is_live | test_physical_dead_requires_every_device[twin_unknown] | RED |
| dc/camera_stream_health.py:715 | K6_member_restored_is_dead | test_one_camera_device_rule_unchanged[device] | RED |
| dc/camera_stream_health.py:712 | K7_member_none_is_dead | test_physical_dead_requires_every_device[twin_missing] | RED |
| dc/camera_stream_health.py:1260 | K8_isrestored_false | test_one_camera_device_rule_unchanged[device] | RED |
| dc/camera_stream_health.py:240 | K9_own_camera_last | test_member_set_change_rebuilds_device_rule[enable_while_dead] | RED |
| dc/camera_stream_health.py:765 | K10_resolve_platform_frigate_only | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:775 | K11_resolve_no_camera_resolves | test_unresolved_camera_byte_identical[disabled_camera] | RED |
| dc/camera_stream_health.py:767 | K12_resolve_no_device_skip | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:762 | K13_resolve_noentry_skip | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:721 | K14_devmembers_nodevice | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:741 | K15_camdev_requires_members | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:747 | K16_owndev_first | test_twin_map_rejects_non_nvr_sibling[two_camera] | RED |
| dc/camera_stream_health.py:182 | K17_ensure_cache_devlevel_check | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:181 | K18_ensure_cache_inputs_check | test_camera_leaving_unwatched_set_pruned_after_grace | RED |
| dc/camera_stream_health.py:180 | K19_ensure_cache_dirty_check | test_member_set_change_rebuilds_device_rule[enable_live] | RED |
| dc/camera_stream_health.py:198 | K20_ensure_members_set | test_device_dead_needs_every_channel[two] | RED |
| dc/camera_stream_health.py:192 | K21_ensure_registry_none | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:171 | K22_invalidate_noop | test_member_set_change_rebuilds_device_rule[enable_live] | RED |
| dc/camera_stream_health.py:228 | K23_warn_unresolved_once | test_unresolved_camera_derived_input_warns_once | RED |
| dc/camera_stream_health.py:360 | E1_dead_ignores_tick_reading | test_one_camera_device_rule_unchanged[device] | RED |
| dc/camera_stream_health.py:365 | E2_dead_grace_zero | test_device_dead_needs_every_channel[two] | RED |
| dc/camera_stream_health.py:366 | E3_dead_camera_is_key | test_member_set_change_rebuilds_device_rule[enable_while_dead] | RED |
| dc/camera_stream_health.py:355 | E4_enabled_ignored | test_kill_switch_matrix[master_off] | RED |
| dc/camera_stream_health.py:338 | E5_no_restart_on_gap | test_one_camera_device_rule_unchanged[device] | RED |
| dc/camera_stream_health.py:333 | E6_no_gap_seen_add | test_one_camera_device_rule_unchanged[device] | RED |
| dc/camera_stream_health.py:333 | E7_unknown_clears_stamp | test_one_camera_device_rule_unchanged[device] | RED |
| dc/camera_stream_health.py:348 | E8_live_no_clear | test_restart_blip_not_excluded | RED |
| dc/camera_stream_health.py:323 | E9_no_prune | test_camera_leaving_unwatched_set_pruned_after_grace | RED |
| dc/camera_stream_health.py:345 | E10_since_not_stamped_first | test_device_dead_needs_every_channel[two] | RED |
| dc/camera_stream_health.py:377 | E11_hold_uses_census | test_zone_hold_knob_zero_releases_at_once | RED |
| dc/camera_stream_health.py:382 | E12_census_uses_hold | test_caps_are_independent_constants | RED |
| dc/camera_stream_health.py:384 | E13_dead_key_unset | test_watched_device_non_input_entity_answers | RED |
| dc/camera_stream_health.py:391 | P1_s1_nm_after_gate | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:393 | P2_s1_configured_only | test_kill_switch_caps_zero_bullet | RED |
| dc/camera_stream_health.py:395 | P3_s1_paged_episode_skip | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:397 | P4_s1_hold_paged_skip | test_am1_no_camera_manager_rooms_page_after_settle | RED |
| dc/camera_stream_health.py:401 | P5_s1_hold_due_skip | test_dm1_owner_absent_reload_room_s1_skipped | RED |
| dc/camera_stream_health.py:406 | P6_s1_paged_day_skip | test_nm_after_threshold_and_recovery | RED |
| dc/camera_stream_health.py:408 | P7_s1_inflight_skip | test_nm_one_page_per_episode_across_midnight | RED |
| dc/camera_stream_health.py:410 | P8_s1_nm_after_elapsed | test_am1_no_camera_manager_rooms_page_after_settle | RED |
| dc/camera_stream_health.py:415 | P9_recover_configured_drop | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:418 | P10_recover_adopted_pop | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:421 | P11_recover_when_not_dead | test_dl2_caps0_room_adopts_owner_group_s1 | RED |
| dc/camera_stream_health.py:423 | P12_recover_discard | test_dl2_caps0_room_adopts_owner_group_s1 | RED |
| dc/camera_stream_health.py:423 | P13_recover_prevcam | test_nm_after_threshold_and_recovery | RED |
| dc/camera_stream_health.py:455 | U1_classify_key_state_cmp | test_protect_census_entry_held_from_t0 | RED |
| dc/camera_stream_health.py:463 | U2_classify_newly_plain_noadd | test_unavailable_input_with_live_camera_turns_off_on_next_tick | RED |
| dc/camera_stream_health.py:450 | U3_classify_restored_ignore | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:449 | U4_classify_enabled_ignore | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:464 | U5_classify_episode_store | test_classifier_mixed_members[live_unavailable] | RED |
| dc/camera_stream_health.py:466 | U6_classify_confirmed_skip | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:460 | U7_classify_newly_plain_clear | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:475 | U8_newly_plain_property | test_unavailable_input_with_live_camera_turns_off_on_next_tick | RED |
| dc/camera_stream_health.py:649 | U9_isunavail_held_confirmed | test_classifier_mixed_members[live_unavailable] | RED |
| dc/camera_stream_health.py:644 | U10_isunavail_held_restored | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:640 | U11_isunavail_held_enabled | test_unavailable_hold_kill_switch_off_is_develop | RED |
| dc/camera_stream_health.py:488 | H1_caps_positive | test_owner_adopts_room_s1_key_caps_0 | RED |
| dc/camera_stream_health.py:496 | H2_cap_min_to_max | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:498 | H3_hold_paged_skip | test_failed_first_build_rooms_page | RED |
| dc/camera_stream_health.py:500 | H4_expired_check | test_no_twin_pages_as_today | RED |
| dc/camera_stream_health.py:501 | H5_expired_zone_only | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:506 | H6_due_add | test_dm1_owner_absent_reload_room_s1_skipped | RED |
| dc/camera_stream_health.py:507 | H7_inflight_skip | test_hold_release_pages_once_per_outage | RED |
| dc/camera_stream_health.py:509 | H8_hold_pages_cam | test_failed_first_build_rooms_page | RED |
| dc/camera_stream_health.py:493 | H9_dead_keys_earliest | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:512 | H10_recoveries_when_gone | test_device_leaves_map_room_sends_low | RED |
| dc/camera_stream_health.py:513 | H11_recoveries_uses_cam | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:510 | H12_due_keys_store | test_dm1_owner_absent_reload_room_s1_skipped | RED |
| dc/camera_stream_health.py:524 | L1_page_ident_map | test_failed_first_build_rooms_page | RED |
| dc/camera_stream_health.py:531 | L2_begin_inflight_add | test_nm_one_page_per_episode_across_midnight | RED |
| dc/camera_stream_health.py:531 | L3_begin_freeze | test_al3_latch_key_frozen_at_begin_send | RED |
| dc/camera_stream_health.py:535 | L4_frozen_pid_recompute | test_al3_latch_key_frozen_at_begin_send | RED |
| dc/camera_stream_health.py:545 | L5_mark_paged_inflight_discard | test_nm_after_threshold_and_recovery | RED |
| dc/camera_stream_health.py:548 | L6_mark_paged_s2_pagekey | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:548 | L7_mark_paged_s2_latch | test_failed_first_build_rooms_page | RED |
| dc/camera_stream_health.py:550 | L8_mark_paged_s1_episode | test_nm_after_threshold_and_recovery | RED |
| dc/camera_stream_health.py:550 | L9_mark_paged_s1_day | test_nm_after_threshold_and_recovery | RED |
| dc/camera_stream_health.py:556 | L10_mark_not_sent_discard | test_not_sent_retries_next_tick[s1] | RED |
| dc/camera_stream_health.py:563 | L11_adopt_episode | test_dl2_caps0_room_adopts_owner_group_s1 | RED |
| dc/camera_stream_health.py:565 | L12_adopt_key | test_dl2_caps0_room_adopts_owner_group_s1 | RED |
| dc/camera_stream_health.py:564 | L13_adopt_day | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:569 | L14_pop_adopted | test_dl2_caps0_room_adopts_owner_group_s1 | RED |
| dc/camera_stream_health.py:585 | R1_is_dead_resnone | test_watched_device_non_input_entity_answers | RED |
| dc/camera_stream_health.py:601 | R2_camera_is_dead_any | test_camera_is_dead_is_keyed_by_camera | RED |
| dc/camera_stream_health.py:598 | R3_camera_is_dead_keyfor | test_device_level_off_is_today | RED |
| dc/camera_stream_health.py:248 | R4_key_for_camera_nontwin | test_watched_device_non_input_entity_answers | RED |
| dc/camera_stream_health.py:611 | R5_is_hold_expired_census | test_caps_are_independent_constants | RED |
| dc/camera_stream_health.py:609 | R6_is_hold_expired_none | test_unwatched_census_camera_held_then_released | RED |
| dc/camera_stream_health.py:623 | R7_cam_hold_expired_census | test_census_reads_the_census_cap_not_the_zone_cap[own_camera] | RED |
| dc/camera_stream_health.py:628 | R8_cam_hold_key_match | test_camera_is_dead_is_keyed_by_camera | RED |
| dc/camera_stream_health.py:670 | R9_snapshot_configured | test_camera_override_sensor_outside_inputs_watched_not_paged | RED |
| dc/camera_stream_health.py:675 | R10_snapshot_resolved_cfg | test_camera_override_sensor_outside_inputs_watched_not_paged | RED |
| dc/camera_stream_health.py:661 | R11_dead_stamps | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:653 | R12_clear_state_getter | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:574 | R13_hold_expired_now_prop | test_zone_hold_failsafe_releases_at_cap | RED |
| dc/camera_stream_health.py:809 | T1_admiss_either_empty | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:811 | T2_admiss_frigate_side | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:813 | T3_admiss_sibling_nvr | test_twin_map_rejects_non_nvr_sibling[one_camera] | RED |
| dc/camera_stream_health.py:813 | T4_admiss_all_to_any | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:811 | T5_admiss_frig_any | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:698 | T6_nvr_no_unifiprotect | test_loss_counts_restored_after_boot_settle | RED |
| dc/camera_stream_health.py:698 | T7_nvr_no_reolink | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:698 | T8_nvr_no_amcrest | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:698 | T9_nvr_no_dahua | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:698 | T10_nvr_plus_generic | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:827 | T11_build_rule_off_gate | test_kill_switch_matrix[twin_off_stamps_off] | RED |
| dc/camera_stream_health.py:832 | T12_build_registry_prime_dev | test_failed_rebuild_keeps_old_map | RED |
| dc/camera_stream_health.py:833 | T13_build_registry_prime_ent | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:839 | T14_build_admit_always | test_twin_map_rejects_non_nvr_sibling[one_camera] | RED |
| dc/camera_stream_health.py:841 | T15_build_groups_one_dir | test_watched_device_non_input_entity_answers | RED |
| dc/camera_stream_health.py:845 | T16_build_rejected_append | test_twin_map_rejects_non_nvr_sibling[one_camera] | RED |
| dc/camera_stream_health.py:843 | T17_build_admitted_append | test_twin_map_multi_channel_protect[2] | RED |
| dc/camera_stream_health.py:838 | T18_build_sorted | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:856 | T19_pure_groups_nodr | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:860 | T20_pure_groups_except | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:873 | T21_pair_for_device_nodev | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:877 | T22_pair_for_device_default | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:875 | T23_pair_for_device_groups_param | test_bl5_pure_pairing_built_once_per_tick | RED |
| dc/camera_stream_health.py:886 | T24_frigate_member_all | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:886 | T25_frigate_member_plats | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:904 | T26_pagekey_group_branch | test_failed_first_build_rooms_page | RED |
| dc/camera_stream_health.py:899 | T27_pagekey_nodevice | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:902 | T28_pagekey_groups_pass | test_bl5_pure_pairing_built_once_per_tick | RED |
| dc/camera_stream_health.py:797 | T29_device_platform_single | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:944 | I1_inputs_options_over_data | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:947 | I2_inputs_no_occupancy | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:947 | I3_inputs_no_mmwave | test_unwatched_set_from_public_reads | RED |
| dc/camera_stream_health.py:947 | I4_inputs_no_motion | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:956 | I5_inputs_extras_dedupe | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:955 | I6_inputs_extras_area | test_loss_counts_restored_after_boot_settle | RED |
| dc/camera_stream_health.py:951 | I7_inputs_dedupe_cfg | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:959 | I8_inputs_room_name | test_owner_adopts_room_s1_key_caps_0 | RED |
| dc/camera_stream_health.py:931 | I9_is_room_entry_fallback | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:929 | I10_is_room_entry_type | test_loss_counts_restored_after_boot_settle | RED |
| dc/camera_stream_health.py:914 | I11_override_sensors_noarea | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:921 | I12_override_sensors_get | test_device_live_if_any_channel_live | RED |
| dc/camera_stream_health.py:995 | Y1_policy_nodevice | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:997 | Y2_policy_rule_off | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:1000 | Y3_policy_owner_none | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:1004 | Y4_policy_notready_page | test_rooms_defer_until_map_ready_bounded | RED |
| dc/camera_stream_health.py:1004 | Y5_policy_notready_defer_always | test_rooms_defer_until_map_ready_bounded | RED |
| dc/camera_stream_health.py:1005 | Y6_policy_not_in_map | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:1007 | Y7_policy_pages_suppress | test_am1_no_camera_manager_rooms_page_after_settle | RED |
| dc/camera_stream_health.py:1007 | Y8_policy_pages_suppress_gone | test_twin_blip_under_grace_no_high | RED |
| dc/camera_stream_health.py:1009 | Y9_policy_defer_notready | test_owner_reload_mid_outage_no_false_high | RED |
| dc/camera_stream_health.py:1009 | Y10_policy_defer_always | test_am1_no_camera_manager_rooms_page_after_settle | RED |
| dc/camera_stream_health.py:1009 | Y11_policy_except_defer | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:978 | Y12_owner_torndown_default | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:978 | Y13_owner_torndown_ignored | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:1033 | S1_send_already_latches | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:1033 | S2_send_always_latch | test_not_sent_retries_next_tick[s1] | RED |
| dc/camera_stream_health.py:1030 | S3_send_exception_result | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:1035 | S4_send_notsent_mark | test_not_sent_retries_next_tick[s1] | RED |
| dc/camera_stream_health.py:1034 | S5_send_pagekey_pass | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:1021 | S6_send_kind | test_device_leaves_map_room_sends_low | RED |
| dc/camera_stream_health.py:1067 | Q1_fold_true_wins | test_member_set_change_rebuilds_device_rule[enable_while_dead] | RED |
| dc/camera_stream_health.py:1067 | Q2_fold_nonbool | test_house_fold_any_true_wins | RED |
| dc/camera_stream_health.py:1101 | Q3_ask_house_fallback | test_watched_camera_getters_unchanged[camera_stream_dead] | RED |
| dc/camera_stream_health.py:1101 | Q4_ask_house_always | test_member_set_change_rebuilds_device_rule[enable_while_dead] | RED |
| dc/camera_stream_health.py:1097 | Q5_ask_room_exception | test_entity_stream_dead_direct_false_wins | RED |
| dc/camera_stream_health.py:1078 | Q6_house_answer_owner | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:1083 | Q7_house_answer_trackernone | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:1088 | Q8_house_answer_bool | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:1086 | Q9_house_answer_except | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:1112 | Q10_input_dead_house | test_watched_camera_getters_unchanged[entity_stream_dead] | RED |
| dc/camera_stream_health.py:1128 | Q11_cam_dead_house | test_watched_camera_getters_unchanged[camera_stream_dead] | RED |
| dc/camera_stream_health.py:1126 | Q12_cam_dead_prefix | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:1138 | Q13_own_route_devlevel | test_watched_device_non_input_entity_answers | RED |
| dc/camera_stream_health.py:1140 | Q14_own_route_registry_entity | test_watched_device_non_input_entity_answers | RED |
| dc/camera_stream_health.py:1152 | Q15_entity_dead_camera_branch | test_zone_camera_tier_camera_entity_key | RED |
| dc/camera_stream_health.py:1154 | Q16_entity_dead_direct | test_watched_camera_getters_unchanged[entity_stream_dead] | RED |
| dc/camera_stream_health.py:1160 | Q17_entity_dead_camroute | test_watched_device_non_input_entity_answers | RED |
| dc/camera_stream_health.py:1188 | Q18_view_dm1_held | test_protect_census_entry_held_from_t0 | RED |
| dc/camera_stream_health.py:1188 | Q19_view_dm1_dead_false | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:1189 | Q20_view_dm1_house | test_unwatched_unavailable_with_camera_held_from_t0 | RED |
| dc/camera_stream_health.py:1195 | Q21_view_expired_census_arg | test_caps_are_independent_constants | RED |
| dc/camera_stream_health.py:1196 | Q22_view_expired_house | test_unwatched_census_camera_held_then_released | RED |
| dc/camera_stream_health.py:1198 | Q23_view_released | test_member_set_change_rebuilds_device_rule[enable_while_dead] | RED |
| dc/camera_stream_health.py:1209 | Q24_eview_cam_branch_none | test_watched_camera_getters_unchanged[camera_stream_hold_expired] | RED |
| dc/camera_stream_health.py:1212 | Q25_eview_cam_expired_census | test_census_reads_the_census_cap_not_the_zone_cap[own_camera] | RED |
| dc/camera_stream_health.py:1213 | Q26_eview_cam_house | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:1216 | Q27_eview_input_route | test_protect_zone_camera_tier_held_then_released | RED |
| dc/camera_stream_health.py:1230 | Q28_eview_cam_route | test_watched_device_non_input_entity_answers | RED |
| dc/camera_stream_health.py:1242 | Q29_quarantined_true | test_quarantined_live_sensor_does_not_end_hold | RED |
| dc/camera_stream_health.py:1240 | Q30_quarantined_empty | - | GREEN (also GREEN on EXT set) |
| dc/camera_stream_health.py:1059 | Q31_room_coordinators_attr | test_owner_not_in_room_coordinators | RED |
| dc/camera_stream_health.py:704 | Q32_device_level_default | test_device_live_if_any_channel_live | RED |
| dc/camera_stream_health.py:1249 | Q33_safe_state | test_state_getter_raise_is_no_opinion | RED |
| const.py:6107 | F1_const_device_level_false | test_device_live_if_any_channel_live | RED |
| const.py:6089 | F2_const_twin_rule_false | test_loss_counts_restored_after_boot_settle | RED |
| const.py:6094 | F3_const_unwatched_false | test_watched_camera_getters_unchanged[camera_stream_dead] | RED |
| const.py:6097 | F4_const_notice_false | test_s1_page_silent_while_twin_live | RED |
| const.py:6112 | F5_const_boot_settle_0 | test_loss_counts_restored_after_boot_settle | RED |
| const.py:6112 | F6_const_boot_settle_big | test_loss_counts_restored_after_boot_settle | RED |
| const.py:6115 | F7_const_debounce_0 | - | GREEN (also GREEN on EXT set) |
| const.py:6100 | F8_const_tick | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:57 | W1_dead_states_no_setup_error | test_dm2_room_entry_state_and_unwatched[setup_error] | RED |
| dc/camera_twin_health.py:57 | W2_dead_states_no_migration | test_dm2_room_entry_state_and_unwatched[migration_error] | RED |
| dc/camera_twin_health.py:57 | W3_dead_states_no_setup_retry | test_dm2_room_entry_state_and_unwatched[setup_retry] | RED |
| dc/camera_twin_health.py:57 | W4_dead_states_plus_not_loaded | test_dm2_room_entry_state_and_unwatched[not_loaded] | RED |
| dc/camera_twin_health.py:515 | W5_dead_states_check_removed | test_dm2_room_entry_state_and_unwatched[setup_error] | RED |
| dc/camera_twin_health.py:515 | W6_state_value_unwrap | test_loss_counts_restored_after_boot_settle | RED |
| dc/camera_twin_health.py:512 | W7_disabled_by_skip | test_dm2_room_entry_state_and_unwatched[disabled] | RED |
| dc/camera_twin_health.py:510 | W8_is_room_entry_skip | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:384 | W9_in_map_rule | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:384 | W10_in_map_device | test_twin_map_rejects_non_nvr_sibling[one_camera] | RED |
| dc/camera_twin_health.py:393 | W11_pages_torn | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:393 | W12_pages_sets_ready | test_am1_owner_without_registry_rooms_defer_then_page | RED |
| dc/camera_twin_health.py:393 | W13_pages_in_map | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:395 | W14_pages_cm_present | test_am1_integration_reload_window_policy | RED |
| dc/camera_twin_health.py:397 | W15_pages_scope | test_am1_in_map_group_out_of_scope_room_pages | RED |
| dc/camera_twin_health.py:406 | W16_nrd_sets_ready_branch | test_am1_integration_reload_window_policy | RED |
| dc/camera_twin_health.py:408 | W17_nrd_since_not_ready | - | GREEN |
| dc/camera_twin_health.py:413 | W18_nrd_elapsed_cmp | test_am1_no_camera_manager_rooms_page_after_settle | RED |
| dc/camera_twin_health.py:413 | W19_nrd_elapsed_always | test_am1_no_camera_manager_rooms_page_after_settle | RED |
| dc/camera_twin_health.py:416 | W20_mark_not_ready_stamp | test_am1_integration_reload_window_policy | RED |
| dc/camera_twin_health.py:416 | W21_mark_not_ready_always_stamp | test_am1_no_camera_manager_rooms_page_after_settle | RED |
| dc/camera_twin_health.py:417 | W22_not_ready_set_false | test_am1_integration_reload_window_policy | RED |
| dc/camera_twin_health.py:422 | W23_candidate | test_twin_map_rejects_non_nvr_sibling[one_camera] | RED |
| dc/camera_twin_health.py:427 | W24_deferral_mapready | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:433 | W25_deferral_bound | test_rooms_defer_until_map_ready_bounded | RED |
| dc/camera_twin_health.py:438 | W26_group_for_rule | test_kill_switch_matrix[twin_off_stamps_on] | RED |
| dc/camera_twin_health.py:440 | W27_group_for_default | test_unwatched_no_twin_pages_like_room | RED |
| dc/camera_twin_health.py:446 | W28_tick_torn | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:450 | W29_tick_killswitch | test_kill_switch_matrix[master_off] | RED |
| dc/camera_twin_health.py:453 | W30_tick_killswitch_markready | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:456 | W31_tick_er_none | test_am1_owner_without_registry_rooms_defer_then_page | RED |
| dc/camera_twin_health.py:457 | W32_tick_er_none_markready | test_am1_owner_without_registry_rooms_defer_then_page | RED |
| dc/camera_twin_health.py:467 | W33_tick_house_evaluate | test_watched_camera_getters_unchanged[camera_stream_dead] | RED |
| dc/camera_twin_health.py:462 | W34_tick_inputs_active | test_watched_camera_getters_unchanged[camera_stream_dead] | RED |
| dc/camera_twin_health.py:472 | W35_tick_groups | test_loss_counts_restored_after_boot_settle | RED |
| dc/camera_twin_health.py:473 | W36_tick_cache_reset | test_bl5_pure_pairing_built_once_per_tick | RED |
| dc/camera_twin_health.py:483 | W37_sets_cm_none | test_no_house_answers_before_camera_manager | RED |
| dc/camera_twin_health.py:484 | W38_sets_cm_none_mark | test_am1_integration_reload_window_policy | RED |
| dc/camera_twin_health.py:497 | W39_sets_adoption_due | test_am1_reload_window_owner_adopts_room_page_and_sends_low | RED |
| dc/camera_twin_health.py:500 | W40_sets_clear_never | test_bl2_ready_again_restamps_loss | RED |
| dc/camera_twin_health.py:500 | W41_sets_clear_always | test_d2_low1_short_not_ready_blip_keeps_owner_clock | RED |
| dc/camera_twin_health.py:501 | W42_sets_clear_live_only | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:498 | W43_sets_clear_since | test_d2_low1_short_not_ready_blip_keeps_owner_clock | RED |
| dc/camera_twin_health.py:522 | W44_sets_wr_add | test_loss_counts_restored_after_boot_settle | RED |
| dc/camera_twin_health.py:524 | W45_sets_roominputs | test_owner_adopts_room_s1_key_caps_0 | RED |
| dc/camera_twin_health.py:520 | W46_sets_extras | test_loss_counts_restored_after_boot_settle | RED |
| dc/camera_twin_health.py:525 | W47_sets_candidates_census | test_unwatched_set_from_public_reads | RED |
| dc/camera_twin_health.py:525 | W48_sets_candidates_zone | test_unwatched_set_from_public_reads | RED |
| dc/camera_twin_health.py:530 | W49_sets_unwatched_notwr | test_unwatched_set_from_public_reads | RED |
| dc/camera_twin_health.py:535 | W50_sets_sticky_add | test_watched_camera_getters_unchanged[camera_stream_dead] | RED |
| dc/camera_twin_health.py:536 | W51_sets_sticky_dur | test_watched_camera_getters_unchanged[camera_stream_dead] | RED |
| dc/camera_twin_health.py:537 | W52_sets_sticky_pop_new | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:540 | W53_sets_sticky_expire | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:541 | W54_sets_active_dev_pop | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:543 | W55_sets_active_dev_set | test_watched_camera_getters_unchanged[camera_stream_dead] | RED |
| dc/camera_twin_health.py:546 | W56_sets_unwatched_devices | test_twin_dies_after_medium_pages_high[unwatched] | RED |
| dc/camera_twin_health.py:547 | W57_sets_wr_store | test_loss_counts_restored_after_boot_settle | RED |
| dc/camera_twin_health.py:548 | W58_sets_ready | test_loss_counts_restored_after_boot_settle | RED |
| dc/camera_twin_health.py:554 | W59_census_entities_callable | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:556 | W60_census_entities_str | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:564 | W61_zone_entities_presence | test_unwatched_set_from_public_reads | RED |
| dc/camera_twin_health.py:579 | W62_active_entities_expiry | test_watched_camera_getters_unchanged[camera_stream_dead] | RED |
| dc/camera_twin_health.py:578 | W63_active_entities_sticky | test_watched_camera_getters_unchanged[camera_stream_dead] | RED |
| dc/camera_twin_health.py:589 | W64_htf_torn | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:589 | W65_htf_sets_ready | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:590 | W66_htf_unwatched_knob | test_kill_switch_matrix[twin_off_stamps_off] | RED |
| dc/camera_twin_health.py:591 | W67_htf_master_knob | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:592 | W68_htf_key_empty | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:597 | W69_htf_key_active | test_watched_camera_getters_unchanged[entity_stream_dead] | RED |
| dc/camera_twin_health.py:599 | W70_htf_camera_branch | test_watched_camera_getters_unchanged[camera_stream_dead] | RED |
| dc/camera_twin_health.py:602 | W71_htf_camera_device | test_watched_camera_getters_unchanged[camera_stream_dead] | RED |
| dc/camera_twin_health.py:614 | W72_loss_break_live | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:620 | W73_loss_live_notlive_pop | test_twin_blip_under_grace_no_high | RED |
| dc/camera_twin_health.py:621 | W74_loss_live_since_set | test_medium_once_per_member_episode | RED |
| dc/camera_twin_health.py:621 | W75_loss_live_since_none | test_s1_page_silent_while_twin_live | RED |
| dc/camera_twin_health.py:622 | W76_loss_seen_live | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:625 | W77_loss_nl_setdefault | test_loss_counts_restored_after_boot_settle | RED |
| dc/camera_twin_health.py:624 | W78_loss_live_pop | test_medium_once_per_member_episode | RED |
| dc/camera_twin_health.py:626 | W79_loss_seen_dead | test_physical_dead_requires_every_device[twin_lost] | RED |
| dc/camera_twin_health.py:625 | W80_loss_nl_missing | test_loss_counts_restored_after_boot_settle | RED |
| dc/camera_twin_health.py:633 | W81_lost_none | test_loss_counts_restored_after_boot_settle | RED |
| dc/camera_twin_health.py:636 | W82_lost_grace | test_physical_dead_requires_every_device[twin_lost] | RED |
| dc/camera_twin_health.py:638 | W83_lost_seen_real | test_loss_counts_restored_after_boot_settle | RED |
| dc/camera_twin_health.py:638 | W84_lost_seen_real_removed | test_physical_dead_requires_every_device[twin_lost] | RED |
| dc/camera_twin_health.py:641 | W85_lost_settle_cmp | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:641 | W86_lost_settle_always | test_loss_counts_restored_after_boot_settle | RED |
| dc/camera_twin_health.py:641 | W87_lost_settle_never | test_loss_counts_restored_after_boot_settle | RED |
| dc/camera_twin_health.py:647 | W88_latest_loss_min | test_staggered_deaths_clock | RED |
| dc/camera_twin_health.py:646 | W89_latest_loss_carry | test_staggered_deaths_clock | RED |
| dc/camera_twin_health.py:651 | W90_group_alive | test_s1_page_silent_while_twin_live | RED |
| dc/camera_twin_health.py:654 | W91_group_dead_all_any | test_house_tracker_pages_discarded | RED |
| dc/camera_twin_health.py:654 | W92_group_dead_bool | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:660 | W93_phys_dead_er | test_physical_dead_requires_every_device[twin_lost] | RED |
| dc/camera_twin_health.py:663 | W94_phys_dead_none | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:665 | W95_phys_dead_group | test_physical_dead_requires_every_device[twin_live] | RED |
| dc/camera_twin_health.py:674 | W96_scope_readers_wr | test_loss_counts_restored_after_boot_settle | RED |
| dc/camera_twin_health.py:674 | W97_scope_readers_u | test_twin_dies_after_medium_pages_high[unwatched] | RED |
| dc/camera_twin_health.py:678 | W98_scope_group_readers | test_reader_less_group_never_pages | RED |
| dc/camera_twin_health.py:676 | W99_scope_twin_rule | test_kill_switch_matrix[twin_off_stamps_off] | RED |
| dc/camera_twin_health.py:680 | W100_scope_unwatched_knob | test_kill_switch_matrix[twin_off_stamps_off] | RED |
| dc/camera_twin_health.py:682 | W101_scope_singleton | test_house_tracker_pages_discarded | RED |
| dc/camera_twin_health.py:688 | W102_member_room_keys_filter | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:695 | W103_pure_groups_cache | test_bl5_pure_pairing_built_once_per_tick | RED |
| dc/camera_twin_health.py:703 | W104_group_page_key_frig | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:704 | W105_group_page_key_groups | test_kill_switch_matrix[twin_off_stamps_on] | RED |
| dc/camera_twin_health.py:711 | W106_member_own_keys | test_al4_room_own_key_page_adopted[dead_at_takeover] | RED |
| dc/camera_twin_health.py:720 | W107_own_s2_neq_key | test_suppressed_by_shared_key_not_resent_after_midnight | RED |
| dc/camera_twin_health.py:719 | W108_own_s2_kind | test_al4_room_own_key_page_adopted[dead_at_takeover] | RED |
| dc/camera_twin_health.py:728 | W109_room_s1_latched | test_owner_adopts_room_s1_key_caps_0 | RED |
| dc/camera_twin_health.py:738 | W110_any_latched_s2 | test_room_paged_then_owner_takeover_next_outage_pages | RED |
| dc/camera_twin_health.py:738 | W111_any_latched_s1 | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:742 | W112_any_latched_own | test_al4_room_own_key_page_adopted[alive_at_takeover] | RED |
| dc/camera_twin_health.py:741 | W113_any_latched_room | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:765 | W114_start_ep_high_sent | test_owner_adopts_room_s1_key_caps_0 | RED |
| dc/camera_twin_health.py:762 | W115_start_ep_room_s1 | test_owner_adopts_room_s1_key_caps_0 | RED |
| dc/camera_twin_health.py:762 | W116_start_ep_own_s2 | test_al4_room_own_key_page_adopted[dead_at_takeover] | RED |
| dc/camera_twin_health.py:766 | W117_start_ep_store | test_permanently_dead_twin_does_not_mask_next_outage | RED |
| dc/camera_twin_health.py:750 | W118_start_ep_key | test_staggered_deaths_clock | RED |
| dc/camera_twin_health.py:778 | X1_eval_dissolve_check | test_pair_dissolves_mid_outage_no_spurious_low | RED |
| dc/camera_twin_health.py:779 | X2_eval_dissolve_flag | test_pair_dissolves_mid_outage_no_spurious_low | RED |
| dc/camera_twin_health.py:777 | X3_eval_current_first | test_pair_dissolves_mid_outage_no_spurious_low | RED |
| dc/camera_twin_health.py:780 | X4_eval_groups_union_eps | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:786 | X5_eval_observed_drop | test_bl2_device_reenters_scope_fresh_clock | RED |
| dc/camera_twin_health.py:785 | X6_eval_observed_live_only | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:788 | X7_eval_update_loss | test_loss_counts_restored_after_boot_settle | RED |
| dc/camera_twin_health.py:792 | X8_eval_adoption_sweep_flag | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:794 | X9_eval_adoption_no_episode | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:794 | X10_eval_adoption_latched | test_owner_page_texts | RED |
| dc/camera_twin_health.py:797 | X11_eval_adoption_adopted | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:798 | X12_eval_adoption_alive_false_since | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:805 | X13_eval_dead_start | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:806 | X14_eval_dead_false_since_none | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:808 | X15_eval_alive_guard | test_takeover_mid_outage_no_spurious_low[unknown] | RED |
| dc/camera_twin_health.py:812 | X16_eval_false_since_set | test_permanently_dead_twin_does_not_mask_next_outage | RED |
| dc/camera_twin_health.py:814 | X17_eval_end_grace | test_low_on_episode_end | RED |
| dc/camera_twin_health.py:814 | X18_eval_end_never | test_permanently_dead_twin_does_not_mask_next_outage | RED |
| dc/camera_twin_health.py:816 | X19_eval_bl3_reset | test_bl3_flapping_twin_does_not_end_episode_early | RED |
| dc/camera_twin_health.py:821 | X20_eval_scope_gate | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:823 | X21_eval_cap_branch | test_one_high_per_outage[caps_0] | RED |
| dc/camera_twin_health.py:825 | X22_eval_s1_branch_dropped | test_one_high_per_outage[caps_0] | RED |
| dc/camera_twin_health.py:827 | X23_eval_notices | test_s1_page_silent_while_twin_live | RED |
| dc/camera_twin_health.py:827 | X24_eval_notices_len | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:771 | X25_eval_cap_min | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:81 | X26_positive_caps_gt | test_one_high_per_outage[caps_0] | RED |
| dc/camera_twin_health.py:79 | X27_positive_caps_zone | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:79 | X28_positive_caps_census | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:833 | X29_ensure_episode | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:845 | X30_s2_high_sent_guard | test_one_high_per_outage[caps_900] | RED |
| dc/camera_twin_health.py:847 | X31_s2_group_dead | test_house_tracker_pages_discarded | RED |
| dc/camera_twin_health.py:850 | X32_s2_latest_none | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:850 | X33_s2_cap_gate | test_staggered_deaths_clock | RED |
| dc/camera_twin_health.py:850 | X34_s2_cap_cmp | test_staggered_deaths_clock | RED |
| dc/camera_twin_health.py:854 | X35_s2_ident_inflight | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:854 | X36_s2_key_required | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:859 | X37_s2_on_sent | test_one_high_per_outage[caps_900] | RED |
| dc/camera_twin_health.py:860 | X38_s2_kind | test_staggered_deaths_clock | RED |
| dc/camera_twin_health.py:860 | X39_s2_key | test_staggered_deaths_clock | RED |
| dc/camera_twin_health.py:867 | X40_s2_severity | test_owner_page_texts | RED |
| dc/camera_twin_health.py:857 | X41_s2_minutes | test_owner_page_texts | RED |
| dc/camera_twin_health.py:877 | X42_s1_nm_after_gate | test_kill_switch_nm_after_zero_bullet | RED |
| dc/camera_twin_health.py:877 | X43_s1_high_sent_guard | test_owner_adopts_room_s1_key_caps_0 | RED |
| dc/camera_twin_health.py:879 | X44_s1_day_guard | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:881 | X45_s1_group_dead | test_owner_s1_silent_while_twin_live[caps_0] | RED |
| dc/camera_twin_health.py:884 | X46_s1_after_gate | test_s1_page_fires_when_both_lost | RED |
| dc/camera_twin_health.py:888 | X47_s1_ident_inflight | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:893 | X48_s1_done_high | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:893 | X49_s1_done_day | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:897 | X50_s1_key | test_one_high_per_outage[caps_0] | RED |
| dc/camera_twin_health.py:904 | X51_s1_severity | test_s1_page_fires_when_both_lost | RED |
| dc/camera_twin_health.py:920 | X52_notice_live_branch | test_medium_once_per_member_episode | RED |
| dc/camera_twin_health.py:921 | X53_notice_live_grace | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:922 | X54_notice_live_pop | test_medium_once_per_member_episode | RED |
| dc/camera_twin_health.py:923 | X55_notice_live_sent | test_twin_blip_under_grace_no_high | RED |
| dc/camera_twin_health.py:928 | X56_notice_live_continue | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:930 | X57_notice_new_st | test_s1_page_silent_while_twin_live | RED |
| dc/camera_twin_health.py:934 | X58_notice_dead | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:934 | X59_notice_cap_none | test_owner_s1_silent_while_twin_live[caps_0] | RED |
| dc/camera_twin_health.py:934 | X60_notice_sent | test_s1_page_silent_while_twin_live | RED |
| dc/camera_twin_health.py:935 | X61_notice_knob | test_kill_switch_notice_off_bullet | RED |
| dc/camera_twin_health.py:936 | X62_notice_lost | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:939 | X63_notice_alive | test_al2_medium_needs_a_live_twin | RED |
| dc/camera_twin_health.py:942 | X64_notice_since | test_medium_for_member_in_setup_retry | RED |
| dc/camera_twin_health.py:943 | X65_notice_cap_cmp | test_medium_for_member_in_setup_retry | RED |
| dc/camera_twin_health.py:945 | X66_notice_own | test_medium_once_per_member_episode | RED |
| dc/camera_twin_health.py:946 | X67_notice_camera | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:947 | X68_notice_others | test_owner_page_texts | RED |
| dc/camera_twin_health.py:948 | X69_notice_inflight | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:951 | X70_notice_st_key | test_medium_once_per_member_episode | RED |
| dc/camera_twin_health.py:954 | X71_notice_done | test_s1_page_silent_while_twin_live | RED |
| dc/camera_twin_health.py:958 | X72_notice_kind | test_house_tracker_pages_discarded | RED |
| dc/camera_twin_health.py:966 | X73_notice_severity | test_medium_once_per_member_episode | RED |
| dc/camera_twin_health.py:925 | X74_notice_low_kind | test_medium_once_per_member_episode | RED |
| dc/camera_twin_health.py:976 | X75_end_pop_ep | test_permanently_dead_twin_does_not_mask_next_outage | RED |
| dc/camera_twin_health.py:977 | X76_end_pop_high | test_permanently_dead_twin_does_not_mask_next_outage | RED |
| dc/camera_twin_health.py:992 | X77_end_recover_s2 | test_permanently_dead_twin_does_not_mask_next_outage | RED |
| dc/camera_twin_health.py:992 | X78_end_recover_s1 | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:997 | X79_end_recover_own | test_al4_room_own_key_page_adopted[dead_at_takeover] | RED |
| dc/camera_twin_health.py:997 | X80_end_recover_own_neq | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:999 | X81_end_recover_room | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:980 | X82_end_dissolve_msg | test_pair_dissolves_mid_outage_no_spurious_low | RED |
| dc/camera_twin_health.py:982 | X83_end_live_down | test_low_on_episode_end | RED |
| dc/camera_twin_health.py:991 | X84_end_key_guard | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:1007 | X85_send_torn | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:1007 | X86_send_inflight | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:1010 | X87_send_dispatch_ready | test_bl6_nm_off_schedules_no_send[owner] | RED |
| dc/camera_twin_health.py:1012 | X88_send_inflight_add | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:1028 | X89_send_task_inflight_discard | test_permanently_dead_twin_does_not_mask_next_outage | RED |
| dc/camera_twin_health.py:1026 | X90_send_task_exception | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:1030 | X91_send_task_already | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:1030 | X92_send_task_always | test_latch_not_set_when_send_fails | RED |
| dc/camera_twin_health.py:1031 | X93_send_task_count | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:1034 | X94_send_task_torn | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:1034 | X95_send_task_on_sent | test_one_high_per_outage[caps_900] | RED |
| dc/camera_twin_health.py:1029 | X96_send_task_last_results | test_suppressed_by_shared_key_not_resent_after_midnight | RED |
| dc/camera_twin_health.py:1037 | X97_recover_torn | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:1052 | X98_recover_go | test_permanently_dead_twin_does_not_mask_next_outage | RED |
| dc/camera_twin_health.py:1047 | X99_recover_args | test_low_on_episode_end | RED |
| dc/camera_twin_health.py:1064 | X100_track_add | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:1067 | X101_track_done | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:1058 | X102_track_close | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:226 | X103_td_flag | test_unload_mid_debounce_no_rebuild | RED |
| dc/camera_twin_health.py:228 | X104_td_pop | test_unload_mid_debounce_no_rebuild | RED |
| dc/camera_twin_health.py:228 | X105_td_pop_is | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:230 | X106_td_unsubs | test_unload_mid_debounce_no_rebuild | RED |
| dc/camera_twin_health.py:235 | X107_td_unsubs_clear | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:236 | X108_td_debounce | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:242 | X109_td_tasks | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:247 | X110_td_tasks_clear | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:247 | X111_td_clear_getter | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:251 | X112_interval_torn | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:254 | X113_interval_except | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:193 | X114_setup_rebuild | test_twin_map_built_once_per_invalidation | RED |
| dc/camera_twin_health.py:193 | X115_setup_at | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:202 | X116_setup_dev_listener | test_twin_map_rebuilt_on_device_rename | RED |
| dc/camera_twin_health.py:205 | X117_setup_ent_listener | test_twin_map_built_once_per_invalidation | RED |
| dc/camera_twin_health.py:214 | X118_setup_tick | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:272 | X119_ent_event_invalidate | test_bl1_house_tracker_rereads_members_on_entity_event | RED |
| dc/camera_twin_health.py:275 | X120_queue_torn | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:282 | X121_queue_pending | test_twin_map_built_once_per_invalidation | RED |
| dc/camera_twin_health.py:283 | X122_queue_debounce_guard | test_twin_map_boot_storm_bounded | RED |
| dc/camera_twin_health.py:301 | X123_debounce_unsub_none | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:302 | X124_debounce_torn | test_unload_mid_debounce_no_rebuild | RED |
| dc/camera_twin_health.py:304 | X125_debounce_pending_reset | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:305 | X126_debounce_relevant | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:316 | X127_rel_device_create | test_rebuild_debounce_zero_still_one_build_per_fire | RED |
| dc/camera_twin_health.py:319 | X128_rel_device_watched | test_twin_map_rebuilt_on_device_rename | RED |
| dc/camera_twin_health.py:319 | X129_rel_device_members | test_twin_map_rebuilt_on_new_device | RED |
| dc/camera_twin_health.py:326 | X130_rel_entity_camera | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:324 | X131_rel_entity_old | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:335 | X132_rel_entity_watched | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:310 | X133_rel_watched_known | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:310 | X134_rel_watched_cands | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:366 | X135_rebuild_fail_ready | test_failed_first_build_rooms_page | RED |
| dc/camera_twin_health.py:353 | X136_rebuild_fail_stale | test_failed_rebuild_sets_map_stale_since | RED |
| dc/camera_twin_health.py:352 | X137_rebuild_fail_failures | test_failed_rebuild_keeps_old_map | RED |
| dc/camera_twin_health.py:375 | X138_rebuild_ok_stale_clear | test_failed_rebuild_sets_map_stale_since | RED |
| dc/camera_twin_health.py:376 | X139_rebuild_ok_adoption | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:371 | X140_rebuild_ok_candidates | test_twin_map_rejects_non_nvr_sibling[one_camera] | RED |
| dc/camera_twin_health.py:368 | X141_rebuild_ok_groups | test_loss_counts_restored_after_boot_settle | RED |
| dc/camera_twin_health.py:374 | X142_rebuild_known | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:347 | X143_rebuild_er_none | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:345 | X144_rebuild_count | test_twin_map_built_once_per_invalidation | RED |
| dc/camera_twin_health.py:1155 | X145_camera_devices_prefix | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:1182 | X146_setup_fn_old_teardown | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:1188 | X147_setup_fn_store | test_owner_setup_and_teardown_real | RED |
| dc/camera_twin_health.py:1199 | X148_teardown_fn | test_owner_setup_and_teardown_real | RED |
| dc/camera_twin_health.py:1162 | X149_nvr_name | test_low_on_episode_end | RED |
| dc/camera_twin_health.py:1169 | X150_phys_fn_none | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:1138 | X151_diag_counters_sent | - | GREEN (also GREEN on EXT set) |
| dc/camera_twin_health.py:1136 | X152_diag_group_high | test_diagnostics_download_carries_twin_counters_only | RED |
| dc/camera_twin_health.py:1139 | X153_diag_page_counts | test_diagnostics_download_carries_twin_counters_only | RED |
| dc/camera_twin_health.py:1121 | X154_diag_results | test_diagnostics_download_carries_twin_counters_only | RED |
| dc/camera_twin_health.py:1091 | X155_diag_sticky | - | GREEN (also GREEN on EXT set) |
| coordinator.py:2667 | Z1_co_s1_policy | test_deferred_page_not_marked_hold_paged[s1_caps_0] | RED |
| coordinator.py:2667 | Z2_co_s1_policy_defer_only | test_deferred_page_not_marked_hold_paged[s1_caps_0] | RED |
| coordinator.py:2673 | Z3_co_s1_adopt_check | test_dl2_caps0_room_adopts_owner_group_s1 | RED |
| coordinator.py:2676 | Z4_co_s1_adopt_call | test_dl2_caps0_room_adopts_owner_group_s1 | RED |
| coordinator.py:2672 | Z5_co_s1_gkey | - | GREEN (also GREEN on EXT set) |
| coordinator.py:2678 | Z6_co_s1_dispatch_ready | test_bl6_nm_off_schedules_no_send[room_s1] | RED |
| coordinator.py:2680 | Z7_co_s1_begin_send | test_nm_one_page_per_episode_across_midnight | RED |
| coordinator.py:2682 | Z8_co_s1_today | test_nm_after_threshold_and_recovery | RED |
| coordinator.py:2696 | Z10_co_rec_pop_adopted | test_dl2_caps0_room_adopts_owner_group_s1 | RED |
| coordinator.py:2698 | Z11_co_rec_suppress | - | GREEN (also GREEN on EXT set) |
| coordinator.py:2698 | Z12_co_rec_cam_guard | - | GREEN (also GREEN on EXT set) |
| coordinator.py:2713 | Z13_co_rec_gkey_low | test_dl2_caps0_room_adopts_owner_group_s1 | RED |
| coordinator.py:2718 | Z14_co_rec_gkey_key | test_dl2_caps0_room_adopts_owner_group_s1 | RED |
| coordinator.py:2709 | Z15_co_rec_room_low | test_nm_after_threshold_and_recovery | RED |
| coordinator.py:2748 | Z16_co_hold_policy | test_rooms_defer_until_map_ready_bounded | RED |
| coordinator.py:2750 | Z17_co_hold_dispatch_ready | test_bl6_nm_off_schedules_no_send[room_s2] | RED |
| coordinator.py:2752 | Z18_co_hold_pagekey | test_failed_first_build_rooms_page | RED |
| coordinator.py:2754 | Z19_co_hold_begin_send | test_hold_release_pages_once_per_outage | RED |
| coordinator.py:2756 | Z20_co_hold_page_key_pass | - | GREEN (also GREEN on EXT set) |
| coordinator.py:2756 | Z21_co_hold_today | - | GREEN (also GREEN on EXT set) |
| coordinator.py:2775 | Z22_co_hold_rec_suppress | test_am1_reload_window_owner_adopts_room_page_and_sends_low | RED |
| coordinator.py:2825 | Z23_co_policy_except | - | GREEN (also GREEN on EXT set) |
| coordinator.py:2822 | Z24_co_policy_device | test_twin_blip_under_grace_no_high | RED |
| coordinator.py:2843 | Z25_co_pagekey_except | - | GREEN (also GREEN on EXT set) |
| coordinator.py:2843 | Z26_co_pagekey_dreg | test_failed_first_build_rooms_page | RED |
| coordinator.py:2843 | Z27_co_pagekey_fallback | - | GREEN (also GREEN on EXT set) |
| coordinator.py:2857 | Z28_co_override_delegate | test_device_live_if_any_channel_live | RED |
| coordinator.py:2811 | Z29_co_devreg | - | GREEN (also GREEN on EXT set) |
| __init__.py:5457 | Z30_init_setup | test_cm_setup_entry_creates_camera_twin_owner | RED |
| __init__.py:6078 | Z31_init_unload | test_cm_unload_entry_tears_down_camera_twin_owner | RED |
| diagnostics.py:55 | Z32_diag_owner | test_diagnostics_download_carries_twin_counters_only | RED |
| diagnostics.py:56 | Z33_diag_torn | - | GREEN (also GREEN on EXT set) |
| diagnostics.py:57 | Z34_diag_counters | test_diagnostics_download_carries_twin_counters_only | RED |
| diagnostics.py:33 | Z35_diag_key | test_diagnostics_download_carries_twin_counters_only | RED |
| camera_census.py:2713 | Z36_census_interior | test_real_census_interior_camera_entities | RED |
| dc/presence.py:5172 | Z37_presence_trackers | test_real_presence_zone_camera_entities | RED |
| dc/presence.py:5186 | Z38_presence_zonepicks | test_real_presence_zone_camera_entities | RED |
| dc/presence.py:5190 | Z39_presence_sorted | test_real_presence_zone_camera_entities | RED |
| dc/presence.py:5180 | Z40_presence_zm_filter | - | GREEN (also GREEN on EXT set) |
| dc/presence.py:5183 | Z41_presence_opts_over_data | - | GREEN (also GREEN on EXT set) |
| camera_resolver.py:891 | Z42_cr_disabled | test_member_set_change_rebuilds_device_rule[enable_live] | RED |
| camera_resolver.py:891 | Z43_cr_prefix | test_device_dead_needs_every_channel[two] | RED |
| camera_resolver.py:879 | Z45_cr_by_device_index | test_dead_stream_excludes_input_after_grace | RED |
| camera_resolver.py:886 | Z46_cr_fallback_filter | test_own_camera_resolved_only_from_own_device[FakeEntityRegistry] | RED |
| camera_resolver.py:901 | Z47_cr_pairs_flag | - | GREEN (also GREEN on EXT set) |
| camera_resolver.py:907 | Z48_cr_pairs_seen | - | GREEN (also GREEN on EXT set) |
| camera_resolver.py:914 | Z49_cr_pairs_sib | test_loss_counts_restored_after_boot_settle | RED |
| camera_resolver.py:912 | Z50_cr_pairs_exception | - | GREEN (also GREEN on EXT set) |
| camera_resolver.py:0 | Z51_cr_own_multi | - | GREEN |
| camera_resolver.py:860 | Z52_cr_own_derived | test_own_camera_reasons_and_derived_truth_table | RED |
| dc/_stuck_signal_nm.py:296 | N1_nm_notified | test_suppressed_by_shared_key_not_resent_after_midnight | RED |
| dc/_stuck_signal_nm.py:308 | N2_nm_ready_kill | test_bl6_dispatch_ready_reads_nm_and_kill_switch[kill_off] | RED |
| dc/_stuck_signal_nm.py:310 | N3_nm_ready_nm | test_bl6_dispatch_ready_reads_nm_and_kill_switch[no_nm] | RED |
| dc/_stuck_signal_nm.py:310 | N4_nm_ready_except | - | GREEN (also GREEN on EXT set) |
| dc/_stuck_signal_nm.py:337 | N5_nm_ex_already | test_suppressed_by_shared_key_not_resent_after_midnight | RED |
| dc/_stuck_signal_nm.py:340 | N6_nm_ex_inflight_check | test_bl4_concurrent_same_key_one_dispatch | RED |
| dc/_stuck_signal_nm.py:342 | N7_nm_ex_inflight_add | test_bl4_concurrent_same_key_one_dispatch | RED |
| dc/_stuck_signal_nm.py:349 | N8_nm_ex_inflight_discard | test_failed_first_build_rooms_page | RED |
| dc/_stuck_signal_nm.py:353 | N9_nm_ex_sent | test_latch_not_set_when_send_fails | RED |
| dc/_stuck_signal_nm.py:351 | N10_nm_ex_exception | - | GREEN (also GREEN on EXT set) |
| dc/_stuck_signal_nm.py:345 | N11_nm_ex_passthrough | test_s1_page_fires_when_both_lost | RED |
| dc/_stuck_signal_nm.py:415 | N12_nm_reset_inflight | - | GREEN (also GREEN on EXT set) |
| quality/tests/_layer_guard_engine.py:115 | G1_guard_zone_camera | test_ship3b_evidence_reads_on_read_list[def | RED |
| quality/tests/_layer_guard_engine.py:126 | G2_guard_interior_camera | test_ship3b_evidence_reads_on_read_list[def | RED |
| dc/camera_twin_health.py:408 | W17a_nrd_since_not_ready | test_am1_integration_reload_window_policy | RED |
| camera_resolver.py:889 | Z44b_cr_sorted | - | GREEN |
| camera_resolver.py:863 | Z51b_cr_own_multi | test_device_level_off_is_today | RED |
| dc/camera_stream_health.py:307 | A1_eval_extras_ignored | test_device_live_if_any_channel_live | RED |
| dc/camera_stream_health.py:308 | A2_eval_extras_dup | - | GREEN |

## 5. Fix-up drill (builder, tests only; no production change)

Each listed GREEN mutation was re-applied to production source (one at a time: `__pycache__` purged,
`PYTHONDONTWRITEBYTECODE=1`, restored in a `finally`, tracked tree clean after the run; script
`.claude/tmp/b3c_drills.py`) and the named new test went RED. All 50 RED. The earlier drill sets
(`b3b_drills.py`, `b3fx_drills.py`) were re-run on the same tree: all RED.

| mutation | gap | test | RED |
|---|---|---|---|
| X118 | TG-1 | `test_tg1_setup_schedules_owner_tick_every_30s` | RED |
| F8 | TG-1 | `test_tg1_setup_schedules_owner_tick_every_30s` | RED |
| S1 | TG-2 | `test_tg2_room_reload_already_sent_latched_then_low` | RED |
| X91 | TG-2 | `test_tg2_owner_already_sent_latched` | RED |
| L6 | TG-3 | `test_tg3_room_paged_protect_low_on_page_key` | RED |
| H11 | TG-3 | `test_tg3_room_paged_protect_low_on_page_key` | RED |
| S5 | TG-3 | `test_tg3_room_paged_protect_low_on_page_key` | RED |
| Z20 | TG-3 | `test_tg3_room_paged_protect_low_on_page_key` | RED |
| I1 | TG-4 | `test_tg4_room_input_list_options_over_data_all_lists` | RED |
| I2 | TG-4 | `test_tg4_room_input_list_options_over_data_all_lists` | RED |
| I4 | TG-4 | `test_tg4_room_input_list_options_over_data_all_lists` | RED |
| Z41 | TG-4 | `test_tg4_zone_picks_options_over_data` | RED |
| U10 | TG-5 | `test_tg5_restored_input_not_held` | RED |
| U3 | TG-5 | `test_tg5_restored_input_not_held` | RED |
| W102 | TG-6 | `test_tg6_other_groups_room_s1_not_adopted_or_recovered` | RED |
| X123 | TG-7 | `test_tg7_debounce_rearms_and_filters` | RED |
| X125 | TG-7 | `test_tg7_debounce_rearms_and_filters` | RED |
| X126 | TG-7 | `test_tg7_debounce_rearms_and_filters` | RED |
| F7 | LOW (TG-7 test) | `test_tg7_debounce_rearms_and_filters` | RED |
| X100 | TG-8 | `test_tg8_teardown_cancels_tracked_tasks_debounce_listeners` | RED |
| X101 | TG-8 | `test_tg8_teardown_cancels_tracked_tasks_debounce_listeners` | RED |
| X105 | TG-8 | `test_tg8_resetup_tears_old_owner_and_pop_only_self` | RED |
| X107 | TG-8 | `test_tg8_teardown_cancels_tracked_tasks_debounce_listeners` | RED |
| X108 | TG-8 | `test_tg8_teardown_cancels_tracked_tasks_debounce_listeners` | RED |
| X109 | TG-8 | `test_tg8_teardown_cancels_tracked_tasks_debounce_listeners` | RED |
| X110 | TG-8 | `test_tg8_teardown_cancels_tracked_tasks_debounce_listeners` | RED |
| X111 | TG-8 | `test_tg8_teardown_cancels_tracked_tasks_debounce_listeners` | RED |
| X146 | TG-8 | `test_tg8_resetup_tears_old_owner_and_pop_only_self` | RED |
| X78 | TG-9 | `test_tg9_owner_group_s1_low_caps0` | RED |
| X81 | TG-9 | `test_tg9_owner_recovers_member_room_s1_at_episode_end` | RED |
| W113 | TG-9 | `test_tg9_sweep_adopts_room_s1_when_alive` | RED |
| W111 | TG-9 | `test_tg9_sweep_adopts_old_owner_group_s1` | RED |
| H2 | TG-10 | `test_tg10_room_s2_at_the_lower_cap[zone_lower]` | RED |
| H5 | TG-10 | `test_tg10_room_s2_at_the_lower_cap[census_lower]` | RED |
| X25 | TG-10 | `test_tg10_owner_s2_at_the_lower_cap[zone_lower]` | RED |
| X27 | TG-10 | `test_tg10_owner_s2_at_the_lower_cap[zone_lower]` | RED |
| X28 | TG-10 | `test_tg10_owner_s2_at_the_lower_cap[census_lower]` | RED |
| P1 | TG-11 | `test_tg11_nm_after_zero_no_s1_with_caps_zero` | RED |
| Q9 | TG-12 | `test_tg12_house_tracker_error_is_no_opinion` | RED |
| Y11 | TG-12 | `test_tg12_policy_error_pages` | RED |
| Z23 | TG-12 | `test_tg12_room_policy_and_page_key_errors` | RED |
| Z25 | TG-12 | `test_tg12_room_policy_and_page_key_errors` | RED |
| Z27 | TG-12 | `test_tg12_room_policy_and_page_key_errors` | RED |
| T20 | TG-12 | `test_tg12_pure_groups_registry_error_is_empty` | RED |
| T7 | LOW | `test_low_nvr_twin_platform_membership[reolink-True]` | RED |
| T8 | LOW | `test_low_nvr_twin_platform_membership[amcrest-True]` | RED |
| T9 | LOW | `test_low_nvr_twin_platform_membership[dahua-True]` | RED |
| T10 | LOW | `test_low_nvr_twin_platform_membership[generic-False]` | RED |
| X151 | LOW | `test_low_diagnostic_counters_notice_and_sticky` | RED |
| X155 | LOW | `test_low_diagnostic_counters_notice_and_sticky` | RED |

Not closed by a test (documented):
- X14: masked by the B-L3 reset (a dead tick is always preceded by a not-alive, not-dead tick that already
  clears `false_since`, since a member becomes lost only one grace after an observed not-live tick); equivalent today.
- Z5 (coordinator S1 group key = pure page key): the D-L2 test uses the Frigate input, whose own camera is the
  page key; a Protect-input caps-0 adoption fixture is a follow-up.
- Remaining LOW rows (X4, X6, X20, W42, W76, W85, Y6, Z29, Z44b, Q26, W64/W65, K10/K13/K15/K17, P3, P9, P10, L13,
  U4/U6/U7, R11, R12, X93, X11, X12, X16, X53, X67, X8/X9/X139, T1/T2/T4/T5, Z47, Z50): unchanged, as listed in
  the LOW section above (defence in depth, diagnostics-only fields, or behaviour that no reachable config exercises).
