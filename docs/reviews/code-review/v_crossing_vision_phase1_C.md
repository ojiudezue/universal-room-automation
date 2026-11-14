# Review C (mutation), crossing vision Phase 1 shadow

Branch `feature/crossing-vision-shadow`, HEAD 23b89886, diff base `git merge-base develop HEAD` = 6e03ec09. Reviewer: framing C, real per-site source mutation.

Method: one production-source mutation at a time (write mutant, run, restore in `finally`, `git status` clean after every row). Test set per mutation (ONE pytest process, `-m ""`): `test_crossing_vision_shadow.py`, `test_crossing_vision_setup_wirein.py`, `test_transit_validator_peak_on_bus.py`, `test_egress_direction_aware.py` (baseline 55 passed). `__pycache__` purged before every run, `PYTHONDONTWRITEBYTECODE=1`. 220 mutations defined, 219 applied (F05 anchor non-unique, skipped), plus 4 paired mutations. No full suite run. The 3 known name-diff failures and the pending rebase are not re-reported.

## Verdict: FIX-REQUIRED

137 of 219 mutations went RED (a specific named test failed). 82 stayed GREEN. Of the GREEN rows, 2 are HIGH, the rest MEDIUM/LOW/INFO (equivalent or redundant). The core producer logic (gates, matching, cluster, cap, parse clamps, trip-wires, D2 bus/DB single-sample) is well anchored. The gaps cluster in three places: (1) the module-level setup/teardown entrypoints and the platform registration (wire-in), (2) lifecycle/bounds (day roll, ring/request pruning, task tracking, teardown gather), (3) pinned semantics of the scoring label and failure classification.

## Process incident (not a code finding)
Mid-run the machine hit 2000+ processes. Cause: `scratchpad/bisect.py` (the orchestrator's name-diff bisect script) shadows the stdlib `bisect`; any `python`/`python -m pytest` started with the shared scratchpad as cwd/script dir imports it and recursively launches pytest (a fork bomb). I stopped and killed only the processes matching that bisect command line (process count 2352 -> 602), then ran the remaining mutations from an isolated directory with `python -I`. Recommend renaming `scratchpad/bisect.py` (and any other stdlib-named file there, e.g. check `ls | grep -E '^(random|json|bisect|types|queue)\.py'`) before it fires again. This likely is what killed the previous Review C.

## GREEN rows (untested sites = findings)

| ID | Site | Mutation | Result | Sev | Note |
|---|---|---|---|---|---|
| M04 | crossing_vision.py | switch default True | GREEN | MEDIUM | INV-OFF default: producer treats absent switch key as ON; boot-before-restore window unpinned (switch default False tested nowhere) |
| M05 | crossing_vision.py | cap clamp max(0) removed | GREEN | INFO | equivalent: cap<=0 already disables via _enabled() |
| M09 | crossing_vision.py | egress: no _roll_day | GREEN | LOW | egress-path day roll; rolled again in _run/diag |
| M16 | crossing_vision.py | cluster: no early return | GREEN | MEDIUM | cluster join falls through to match/schedule: duplicate/phantom rows possible; tests assert call count, not exactly-one-row-per-crossing |
| M18 | crossing_vision.py | no match -> still proceeds | GREEN | LOW | missing return after no_frigate_event row raises AttributeError in the bus callback; tests do not assert clean callback |
| M21 | crossing_vision.py | prior primary missing -> no clustered row | GREEN | LOW | analysed-event whose primary request was pruned: clustered row branch untested |
| M32 | crossing_vision.py | frigate label filter dropped | GREEN | MEDIUM | label==person filter untested: a non-person event on a door camera would be ring-matched and analysed (cost/INV-SCOPE) |
| M34 | crossing_vision.py | type end sets end time dropped | GREEN | LOW | Frigate 'end' fallback end-time stamp untested |
| M35 | crossing_vision.py | ring bound dropped | GREEN | MEDIUM | per-camera ring bound untested (K19 RING->1 is RED, but removing the eviction is GREEN): unbounded memory |
| M36 | crossing_vision.py | top_score max -> last | GREEN | LOW | top_score max-accumulation untested (match tie-break input) |
| M44 | crossing_vision.py | events_in_window: all stems | GREEN | LOW | frigate_events_in_window scoping untested (display attr) |
| M45 | crossing_vision.py | prune: never prune | GREEN | MEDIUM | completed requests never pruned: unbounded growth + stale cluster anchors, untested |
| M46 | crossing_vision.py | prune: prune non-done | GREEN | MEDIUM | prune of calling/waiting requests (status guard) untested |
| M47 | crossing_vision.py | fire_request: no status guard | GREEN | INFO | redundant with M48 (pair M47+M48 also GREEN: double fire timer+end event untested) -> LOW pair gap |
| M48 | crossing_vision.py | fire_request: no timer cancel | GREEN | INFO | redundant with M47 (see pair) |
| M49 | crossing_vision.py | fire_request: waiting_by_event not popped | GREEN | LOW | stale _waiting_by_event entry after fire; harmless via status guard |
| M51 | crossing_vision.py | run: call-time torn_down dropped | GREEN | LOW | call-time _torn_down check redundant with timer cancel + latch |
| M56 | crossing_vision.py | run: reply None refund dropped | GREEN | LOW | kill-between-gate-and-call counter refund unreachable in rig |
| M62 | crossing_vision.py | run: except swallow -> raise | GREEN | LOW | run() never-raise guard: only analyzer failure classes tested, not an internal exception |
| M63 | crossing_vision.py | run: latency recorded None | GREEN | LOW | latency_s attr unasserted |
| M68 | crossing_vision.py | run: timeout const wrong | GREEN | MEDIUM | timeout_s passed to analyzer unpinned; plan F6 requires > llmvision 60s; K14 TIMEOUT 90->1 also GREEN |
| M71 | crossing_vision.py | run: event_id preference | GREEN | INFO | equivalent |
| M73 | crossing_vision.py | clip_ref: unsafe instance check dropped | GREEN | MEDIUM | unsafe instance-id (URL path component) check untested; only event-id check (M72) is |
| M74 | crossing_vision.py | clip_ref: single-instance fallback dropped | GREEN | MEDIUM | single-Frigate-instance fallback for clip URL untested |
| M77 | crossing_vision.py | record: dedup_source_ref True | GREEN | LOW | dedup_source_ref=False untested (source_ref unique per crossing, so mostly equivalent) |
| M80 | crossing_vision.py | record: torn_down guard dropped | GREEN | INFO | redundant with M117 (pair GREEN) |
| M81 | crossing_vision.py | record: write untracked (create_task) | GREEN | MEDIUM | row write spawned untracked (hass.async_create_task) is GREEN; pair with M118 task-tracking also GREEN: in-flight row writes/calls at teardown untested |
| M83 | crossing_vision.py | record: agreement_case args swapped | GREEN | MEDIUM | agreement_case(people,camera) arg order / B-vs-C labels unpinned (same as P18); scorer relies on A/B/C/D |
| M86 | crossing_vision.py | record: person_id attr dropped | GREEN | LOW | person_id attr on row unasserted |
| M87 | crossing_vision.py | record: model attr when no call | GREEN | LOW | model attr on no-call rows unasserted |
| M88 | crossing_vision.py | record: ts_iso source | GREEN | LOW | started_at on row unasserted |
| M89 | crossing_vision.py | record: db None guard | GREEN | LOW | database None guard unreached (rig always has DB) |
| M91 | crossing_vision.py | roll_day: no reset | GREEN | MEDIUM | daily cap never resets at local midnight: no test crosses a day boundary (cap hit once = no calls until restart) |
| M92 | crossing_vision.py | roll_day: compare wrong | GREEN | MEDIUM | same: day-compare predicate unpinned |
| M94 | crossing_vision.py | tripwire: seen prune dropped | GREEN | LOW | seen-window prune unpinned (K23 window const GREEN too) |
| M102 | crossing_vision.py | tripwire: failed set | GREEN | MEDIUM | FAILED_CALL_OUTCOMES set: error-rate page tested with 'error' only; timeout/unparseable/refused not counted -> untested |
| M103 | crossing_vision.py | tripwire: error rate >= | GREEN | LOW | error-rate boundary >= vs > unpinned |
| M105 | crossing_vision.py | tripwire: errors latch reset dropped | GREEN | MEDIUM | error page re-arm untested: once latched it could stay silent forever |
| M112 | crossing_vision.py | teardown: latch dropped | GREEN | INFO | redundant with M114: pair M112+M114 is RED (test_teardown_cancels_pending) -> OK |
| M114 | crossing_vision.py | teardown: request timers not cancelled | GREEN | INFO | see M112 pair: RED together |
| M115 | crossing_vision.py | teardown: tasks not gathered/cancelled | GREEN | MEDIUM | teardown gather of in-flight tasks untested (pair M115+M118 GREEN): in-flight llmvision call survives unload |
| M116 | crossing_vision.py | teardown: cancel on timeout dropped | GREEN | LOW | cancel-after-gather-timeout untested |
| M117 | crossing_vision.py | spawn: torn_down guard dropped | GREEN | INFO | redundant with M80 |
| M118 | crossing_vision.py | spawn: task tracking dropped | GREEN | MEDIUM | spawned task tracking set untested (see M115) |
| M119 | crossing_vision.py | wiring: setup teardown-prior dropped | GREEN | MEDIUM | async_setup_crossing_vision prior-instance teardown (partial reload) untested |
| M120 | crossing_vision.py | wiring: hass.data key not set | GREEN | HIGH | async_setup_crossing_vision does not publish hass.data[DOMAIN][CROSSING_VISION_HASS_KEY]: rig sets it itself; real wiring untested; diag sensor would be empty and unload could never find the producer |
| M121 | crossing_vision.py | wiring: teardown pop -> get | GREEN | MEDIUM | teardown pop vs get untested (stale producer after unload) |
| M122 | crossing_vision.py | wiring: teardown not awaited | GREEN | HIGH | async_teardown_crossing_vision never awaits cv.async_teardown(): bus listener / Frigate consumer / timers leak across unload+reload; wirein tests monkeypatch the function and never run the real one |
| P04 | crossing_vision.py | parse: json error unparseable | GREEN | INFO | equivalent (falls to unparseable via frames check) |
| P06 | crossing_vision.py | parse: frames not list | GREEN | MEDIUM | response without frames list should be 'unparseable' (counted failure) but becomes 'blank' (uncounted) unpinned |
| P07 | crossing_vision.py | parse: frame non-mapping | GREEN | LOW | non-mapping frame entry unparseable vs skipped unpinned |
| P12 | crossing_vision.py | parse: total None default | GREEN | INFO | equivalent |
| P13 | crossing_vision.py | parse: desc truncation dropped | GREEN | LOW | desc truncation unpinned (K18 DESC_MAX also GREEN): storage bound |
| P14 | crossing_vision.py | parse: group bool check | GREEN | LOW | group bool coercion unpinned |
| P15 | crossing_vision.py | parse: _as_nonneg_int bool | GREEN | LOW | bool-as-int people count rejected: unpinned |
| P17 | crossing_vision.py | parse: non-mapping result | GREEN | LOW | non-mapping service response: AttributeError path, row lost; unpinned |
| P18 | crossing_vision.py | agreement: A/B/C swapped | GREEN | MEDIUM | agreement_case B vs C direction unpinned (see M83) |
| P20 | crossing_vision.py | frigate_camera_stem: strip | GREEN | LOW | camera.strip() unpinned |
| E01 | perimeter_enrichment.py | enrich: kill check dropped | GREEN | LOW | kill check inside analyze_crossing_frames redundant with producer _enabled; untested in isolation |
| E02 | perimeter_enrichment.py | enrich: no-clip-ref guard dropped | GREEN | LOW | no-clip guard inside analyzer redundant with _clip_reference |
| E09 | perimeter_enrichment.py | enrich: CancelledError swallowed | GREEN | INFO | equivalent (CancelledError is BaseException) |
| E10 | perimeter_enrichment.py | enrich: error text slice | GREEN | LOW | error text [:200] bound unpinned |
| E17 | perimeter_enrichment.py | enrich: max_tokens | GREEN | LOW | max_tokens cost cap from perimeter config unpinned |
| F01 | frigate_ingress.py | instance_ids: client_id empty guard | GREEN | LOW | instance-id discovery: blank client_id guard has no direct test |
| F02 | frigate_ingress.py | instance_ids: prefix rstrip | GREEN | MEDIUM | instance-id discovery: topic_prefix strip/rstrip('/') has no direct test; mismatch silently drops instance scoping |
| F03 | frigate_ingress.py | instance_ids: exception -> partial | GREEN | LOW | discovery exception returns partial dict instead of {}; untested |
| F04 | frigate_ingress.py | instance_ids: client_id strip | GREEN | LOW | client_id strip untested |
| F05 | frigate_ingress.py | instance_ids: runtime mapping guard | NONUNIQUE | ? |  |
| T06 | transit_validator.py | tv: door_group_members self-add dropped | GREEN | INFO | equivalent |
| S03 | switch.py | switch: is_on default True | GREEN | LOW | switch.is_on default True unpinned (producer-side default M04 is the load-bearing one) |
| S06 | switch.py | switch: not registered | GREEN | MEDIUM | CrossingVisionShadowSwitch not in async_setup_entry entity list: no wire-in anchor (tests instantiate the class directly); entity would never exist, producer stays off |
| S08 | switch.py | switch: unique id | GREEN | LOW | unique_id unpinned |
| N01 | number.py | number: not registered | GREEN | MEDIUM | CrossingVisionDailyCallsNumber not in async_setup_entry entity list: no wire-in anchor; cap Number never published (producer falls back to const default 40) |
| N03 | number.py | number: clamp dropped | GREEN | LOW | stored value clamp to [0,MAX] on load unpinned |
| N06 | number.py | number: default const | GREEN | LOW | bad-stored-value fallback unpinned |
| K03 | const.py | const: type missing from ABSENCE_EXEMPT | GREEN | MEDIUM | MEMORY_WRITER_HEALTH_ABSENCE_EXEMPT membership untested (false writer-health page during vacation) |
| K06 | const.py | const: MAX_CONCURRENT 2->50 | GREEN | LOW | MAX_CONCURRENT default 2 unpinned (tests override) |
| K09 | const.py | const: SWITCH key | GREEN | LOW | SWITCH_HASS_KEY collides with producer HASS_KEY -> bool(cv) turns shadow ON; no key-distinctness test |
| K12 | const.py | const: TEARDOWN_GATHER 5->0 | GREEN | LOW | TEARDOWN_GATHER_S unpinned |
| K14 | const.py | const: TIMEOUT 90->1 | GREEN | MEDIUM | TIMEOUT_S 90 unpinned (see M68) |
| K15 | const.py | const: EVENT_END_WAIT 120->1 | GREEN | LOW | EVENT_END_WAIT_S 120 default unpinned (tests override) |
| K18 | const.py | const: DESC_MAX 200->5 | GREEN | LOW | DESC_MAX unpinned |
| K23 | const.py | const: TRIPWIRE_WINDOW 86400->1 | GREEN | LOW | TRIPWIRE_WINDOW unpinned |

Paired mutations: M112+M114 (teardown latch + request timers) RED `test_teardown_cancels_pending`; M47+M48 (double fire guard + timer cancel) GREEN; M80+M117 (record + spawn torn-down guards) GREEN; M115+M118 (teardown gather + task tracking) GREEN.

## Must-fix (tests to add; no production change is required unless a test then exposes one)

1. HIGH M120/M122: real-function test for `async_setup_crossing_vision` / `async_teardown_crossing_vision` (hass.data key published; teardown pops AND awaits `async_teardown`; listener and consumer unsubscribed afterwards). The wirein tests stub both.
2. MEDIUM S06/N01: wire-in anchors that `async_setup_entry` in switch.py/number.py yields `CrossingVisionShadowSwitch` / `CrossingVisionDailyCallsNumber` (entity platform setup, not direct instantiation).
3. MEDIUM M04: producer default OFF when the switch key is absent (boot-before-restore).
4. MEDIUM M91/M92/M09: day-boundary test: cap hit, advance past local midnight, a call is allowed again.
5. MEDIUM M16/M45/M46/M35: exactly one row per crossing under cluster fall-through; request and ring bounds; prune only `done`.
6. MEDIUM M32: non-person Frigate label never enters the ring.
7. MEDIUM M73/M74/F02: instance-id safety, single-instance fallback, topic-prefix keyed discovery (direct tests of `discover_frigate_instance_ids`).
8. MEDIUM P18/M83: pin agreement_case B vs C and D on counts (the scorer's label).
9. MEDIUM M102/M105/P06: error-rate page counts timeout/unparseable/refused, re-arms, and a response with no `frames` is `unparseable` not `blank`.
10. MEDIUM M115/M118/M81: teardown with an in-flight call: task gathered/cancelled, no row after teardown.
11. MEDIUM M68/K14: assert `timeout_s` passed to the analyzer equals `CROSSING_VISION_TIMEOUT_S` and that the const exceeds llmvision's 60 s (plan F6); K03 absence-exempt membership.
LOW rows are optional hardening (fix in the same pass if cheap).

## RED rows (each killed by a named test)

| ID | Site | Mutation | First failing test(s) |
|---|---|---|---|
| M01 | crossing_vision.py | enabled: ignore switch | test_switch_off_no_call_no_row, test_switch_off_after_schedule_no_call |
| M02 | crossing_vision.py | enabled: ignore kill | test_kill_const_no_call |
| M03 | crossing_vision.py | enabled: ignore cap>0 | test_cap_zero_no_call_no_row, test_cap_rechecked_at_call_time |
| M06 | crossing_vision.py | cap hass key ignored | test_cap_zero_no_call_no_row, test_cap_skip_recorded, test_cap_counts_pending_requests (+2 more) |
| M07 | crossing_vision.py | egress: accept ambiguous | test_ambiguous_ignored |
| M08 | crossing_vision.py | egress: no _enabled gate at schedule | test_switch_off_no_call_no_row, test_cap_zero_no_call_no_row |
| M10 | crossing_vision.py | seen sample dropped | test_zero_fire_pages_once, test_zero_fire_rearms_after_ok, test_tripwire_timer_registered_and_runs |
| M11 | crossing_vision.py | group_key ignore group | test_cluster_one_call, test_cluster_completed_request_no_second_call |
| M12 | crossing_vision.py | door_group_members fallback | test_one_call_one_row_per_crossing, test_same_group_doorbell_event_matches, test_cluster_one_call (+1 more) |
| M13 | crossing_vision.py | camera_peak not read | test_one_call_one_row_per_crossing, test_diag_status_shape |
| M14 | crossing_vision.py | cluster: window inf | test_failure_classes_recorded_never_raise, test_error_rate_pages |
| M15 | crossing_vision.py | cluster: group check dropped | test_people_count_clamped_to_frame_bounds, test_cap_skip_recorded, test_cap_counts_pending_requests (+3 more) |
| M17 | crossing_vision.py | no match -> no row | test_interior_camera_event_never_matched, test_event_outside_match_window_not_matched, test_no_frigate_event_no_call (+1 more) |
| M19 | crossing_vision.py | analysed_by prior ignored | test_cluster_completed_request_no_second_call |
| M20 | crossing_vision.py | analysed_by not stamped | test_cluster_completed_request_no_second_call |
| M22 | crossing_vision.py | cap gate at schedule: ignore pending | test_cap_counts_pending_requests |
| M23 | crossing_vision.py | cap gate at schedule dropped | test_cap_counts_pending_requests |
| M24 | crossing_vision.py | cap gate off-by-one > | test_cap_counts_pending_requests |
| M25 | crossing_vision.py | busy gate dropped | test_busy_skip_recorded |
| M26 | crossing_vision.py | busy gate off-by-one | test_busy_skip_recorded |
| M27 | crossing_vision.py | end known -> don't fire immediately | test_one_call_one_row_per_crossing, test_people_count_clamped_to_frame_bounds, test_same_group_doorbell_event_matches (+16 more) |
| M28 | crossing_vision.py | end-wait timer not armed | test_end_wait_timeout_fires_call |
| M29 | crossing_vision.py | timeout callback no fire | test_end_wait_timeout_fires_call |
| M30 | crossing_vision.py | waiting_by_event not registered | test_cap_counts_pending_requests, test_cap_lowered_after_schedule_records_skip, test_cluster_one_call |
| M31 | crossing_vision.py | frigate end doesn't fire waiting | test_cap_counts_pending_requests, test_cap_lowered_after_schedule_records_skip, test_cluster_one_call |
| M33 | crossing_vision.py | door-stem filter dropped | test_interior_camera_event_never_matched |
| M37 | crossing_vision.py | instance capture dropped | test_clip_url_instance_scoped |
| M38 | crossing_vision.py | instance_from_source prefix strip | test_clip_url_instance_scoped |
| M39 | crossing_vision.py | match: window ignored | test_event_outside_match_window_not_matched, test_failure_classes_recorded_never_raise, test_clip_url_instance_scoped (+1 more) |
| M40 | crossing_vision.py | match: prefers lowest score | test_match_picks_highest_score_then_longest |
| M41 | crossing_vision.py | match: tie-break duration ignored | test_match_picks_highest_score_then_longest |
| M42 | crossing_vision.py | match: ring of members -> all stems | test_people_count_clamped_to_frame_bounds, test_interior_camera_event_never_matched, test_cap_skip_recorded (+4 more) |
| M43 | crossing_vision.py | events_in_window: wrong hi bound | test_one_call_one_row_per_crossing, test_match_picks_highest_score_then_longest |
| M50 | crossing_vision.py | run: call-time enabled gate dropped | test_switch_off_after_schedule_no_call, test_cap_rechecked_at_call_time |
| M52 | crossing_vision.py | run: call-time cap recheck dropped | test_cap_lowered_after_schedule_records_skip |
| M53 | crossing_vision.py | run: no_clip_url -> proceeds | test_clip_url_instance_scoped, test_unsafe_event_id_never_sent |
| M54 | crossing_vision.py | run: calls_today not incremented | test_cap_skip_recorded, test_cap_lowered_after_schedule_records_skip |
| M55 | crossing_vision.py | run: today calls counter dropped | test_cap_skip_recorded, test_diag_status_shape |
| M57 | crossing_vision.py | run: timeout status -> error | test_failure_classes_recorded_never_raise |
| M58 | crossing_vision.py | run: other status -> ok?? (error->unparseable) | test_failure_classes_recorded_never_raise |
| M59 | crossing_vision.py | run: calls deque append dropped | test_zero_fire_rearms_after_ok, test_error_rate_pages |
| M60 | crossing_vision.py | run: zero_latched reset on ok dropped | test_zero_fire_rearms_after_ok |
| M61 | crossing_vision.py | run: finally status done dropped | test_failure_classes_recorded_never_raise, test_clip_url_instance_scoped, test_error_rate_pages |
| M64 | crossing_vision.py | run: frame_source dropped | test_one_call_one_row_per_crossing |
| M65 | crossing_vision.py | run: crossing_keys not passed on call row | test_cluster_one_call |
| M66 | crossing_vision.py | run: model const wrong | test_one_call_one_row_per_crossing |
| M67 | crossing_vision.py | run: max_frames wrong | test_one_call_one_row_per_crossing |
| M69 | crossing_vision.py | run: structure not passed schema | test_one_call_one_row_per_crossing |
| M70 | crossing_vision.py | run: expose_images | test_use_memory_false |
| M72 | crossing_vision.py | clip_ref: unsafe event id check dropped | test_unsafe_event_id_never_sent |
| M75 | crossing_vision.py | clip_ref: n_entries==1 -> always | test_clip_url_instance_scoped |
| M76 | crossing_vision.py | clip_ref: instance path wrong | test_one_call_one_row_per_crossing, test_match_picks_highest_score_then_longest, test_cap_counts_pending_requests (+1 more) |
| M78 | crossing_vision.py | record: node_id constant | test_one_call_one_row_per_crossing, test_people_count_clamped_to_frame_bounds, test_event_outside_match_window_not_matched (+10 more) |
| M79 | crossing_vision.py | record: episode type | test_one_call_one_row_per_crossing, test_people_count_clamped_to_frame_bounds, test_interior_camera_event_never_matched (+20 more) |
| M82 | crossing_vision.py | record: camera_peak attr dropped | test_one_call_one_row_per_crossing |
| M84 | crossing_vision.py | record: count() dropped | test_cap_skip_recorded, test_blank_not_zero, test_failure_classes_recorded_never_raise (+2 more) |
| M85 | crossing_vision.py | record: _last dropped | test_diag_status_shape, test_open_tracks_sensor_carries_diag_unrecorded |
| M90 | crossing_vision.py | count: errors mapping dropped | test_failure_classes_recorded_never_raise |
| M93 | crossing_vision.py | tripwire: switch gate dropped | test_switch_off_no_page |
| M95 | crossing_vision.py | tripwire: calls prune dropped | test_zero_fire_rearms_after_ok |
| M96 | crossing_vision.py | tripwire: settle ignored | test_zero_fire_ignores_unsettled_crossings, test_error_rate_needs_min_calls |
| M97 | crossing_vision.py | tripwire: zero latch not set | test_zero_fire_pages_once |
| M98 | crossing_vision.py | tripwire: zero min crossing > | test_zero_fire_pages_once, test_zero_fire_rearms_after_ok, test_tripwire_timer_registered_and_runs |
| M99 | crossing_vision.py | tripwire: zero ok==0 dropped | test_zero_fire_rearms_after_ok |
| M100 | crossing_vision.py | tripwire: zero severity | test_zero_fire_pages_once |
| M101 | crossing_vision.py | tripwire: zero stuck name | test_zero_fire_pages_once, test_zero_fire_rearms_after_ok, test_tripwire_timer_registered_and_runs |
| M104 | crossing_vision.py | tripwire: error min calls dropped | test_zero_fire_pages_once, test_zero_fire_needs_min_crossings, test_zero_fire_rearms_after_ok (+2 more) |
| M106 | crossing_vision.py | tripwire: errors latch set dropped | test_error_rate_pages |
| M107 | crossing_vision.py | tripwire: not-zero_latched check dropped | test_zero_fire_pages_once |
| M108 | crossing_vision.py | tick: spawn dropped | test_tripwire_timer_registered_and_runs |
| M109 | crossing_vision.py | setup: bus listener not registered | test_one_call_one_row_per_crossing, test_people_count_clamped_to_frame_bounds, test_interior_camera_event_never_matched (+27 more) |
| M110 | crossing_vision.py | setup: ingress consumer not registered | test_one_call_one_row_per_crossing, test_people_count_clamped_to_frame_bounds, test_switch_off_after_schedule_no_call (+26 more) |
| M111 | crossing_vision.py | setup: tripwire timer not registered | test_tripwire_timer_registered_and_runs |
| M113 | crossing_vision.py | teardown: unsubs not called | test_setup_entry_creates_crossing_vision_after_linker, test_unload_entry_tears_down_crossing_vision_before_ingress |
| P01 | crossing_vision.py | parse: unwrap service_response dropped | test_failure_classes_recorded_never_raise |
| P02 | crossing_vision.py | parse: structured empty -> refused dropped | test_failure_classes_recorded_never_raise |
| P03 | crossing_vision.py | parse: response_text empty refused | test_failure_classes_recorded_never_raise |
| P05 | crossing_vision.py | parse: empty dict refused | test_failure_classes_recorded_never_raise |
| P08 | crossing_vision.py | parse: bad people -> 0 | test_failure_classes_recorded_never_raise |
| P09 | crossing_vision.py | parse: blank -> 0 count | test_blank_not_zero |
| P10 | crossing_vision.py | parse: upper clamp dropped | test_people_count_clamped_to_frame_bounds |
| P11 | crossing_vision.py | parse: lower clamp dropped | test_people_count_clamped_to_frame_bounds |
| P16 | crossing_vision.py | parse: _as_nonneg_int neg | test_failure_classes_recorded_never_raise |
| P19 | crossing_vision.py | agreement: missing->agree | test_interior_camera_event_never_matched, test_event_outside_match_window_not_matched, test_cap_skip_recorded (+11 more) |
| P21 | crossing_vision.py | diag: today dropped | test_switch_off_no_call_no_row, test_cap_skip_recorded, test_blank_not_zero (+3 more) |
| P22 | crossing_vision.py | diag: age_s | test_diag_status_shape |
| E03 | perimeter_enrichment.py | enrich: store_in_timeline True | test_use_memory_false |
| E04 | perimeter_enrichment.py | enrich: use_memory True | test_use_memory_false |
| E05 | perimeter_enrichment.py | enrich: video_file wins dropped | test_one_call_one_row_per_crossing |
| E06 | perimeter_enrichment.py | enrich: provider dropped | test_one_call_one_row_per_crossing |
| E07 | perimeter_enrichment.py | enrich: blocking False | test_one_call_one_row_per_crossing, test_people_count_clamped_to_frame_bounds, test_same_group_doorbell_event_matches (+19 more) |
| E08 | perimeter_enrichment.py | enrich: timeout -> error | test_failure_classes_recorded_never_raise |
| E11 | perimeter_enrichment.py | enrich: response_format | test_one_call_one_row_per_crossing |
| E12 | perimeter_enrichment.py | enrich: structure not sent | test_one_call_one_row_per_crossing |
| E13 | perimeter_enrichment.py | enrich: message prompt | test_one_call_one_row_per_crossing |
| E14 | perimeter_enrichment.py | enrich: wait_for timeout ignored | test_failure_classes_recorded_never_raise |
| E15 | perimeter_enrichment.py | enrich: service name | test_one_call_one_row_per_crossing, test_people_count_clamped_to_frame_bounds, test_same_group_doorbell_event_matches (+19 more) |
| E16 | perimeter_enrichment.py | enrich: include_filename | test_use_memory_false |
| T01 | transit_validator.py | tv: peak bus key dropped | test_bus_and_db_peak_identical, test_sampler_called_once_both_sinks_first_value, test_ambiguous_peak_none_no_sample (+3 more) |
| T02 | transit_validator.py | tv: peak ambiguous sampling | test_ambiguous_peak_none_no_sample |
| T03 | transit_validator.py | tv: sampler except -> raise | test_sampler_exception_none_both |
| T04 | transit_validator.py | tv: db row peak -> resample | test_sampler_called_once_both_sinks_first_value, test_sampler_exception_none_both |
| T05 | transit_validator.py | tv: peak forced None on bus | test_bus_and_db_peak_identical, test_sampler_called_once_both_sinks_first_value |
| T07 | transit_validator.py | tv: door_group_members no-group | test_door_group_members_and_door_camera_stems |
| T08 | transit_validator.py | tv: door_group_members empty stem | test_door_group_members_and_door_camera_stems |
| T09 | transit_validator.py | tv: door_camera_stems egress entities dropped | test_door_group_members_and_door_camera_stems |
| T10 | transit_validator.py | tv: door_camera_stems group keys dropped | test_same_group_doorbell_event_matches, test_door_group_members_and_door_camera_stems |
| S01 | switch.py | switch: restore always on | test_switch_restore_only_on |
| S02 | switch.py | switch: restore ignores last | test_switch_restore_only_on |
| S04 | switch.py | switch: turn_on doesn't apply | test_switch_restore_only_on |
| S05 | switch.py | switch: turn_off doesn't apply | test_switch_restore_only_on |
| S07 | switch.py | switch: entity_id | test_switch_restore_only_on |
| N02 | number.py | number: publish dropped in init | test_daily_cap_number_publishes_and_persists |
| N04 | number.py | number: set publish dropped | test_daily_cap_number_publishes_and_persists |
| N05 | number.py | number: persist dropped | test_daily_cap_number_publishes_and_persists |
| N07 | number.py | number: key published wrong | test_daily_cap_number_publishes_and_persists |
| I01 | __init__.py | init: setup call dropped | test_setup_entry_creates_crossing_vision_after_linker |
| I02 | __init__.py | init: teardown call dropped | test_unload_entry_tears_down_crossing_vision_before_ingress |
| I03 | __init__.py | init: _NO_LIVE_ATTR_KEYS entry dropped | test_cap_key_reload_suppressed |
| I04 | __init__.py | init: RELOAD_SUPPRESS entry dropped | test_cap_key_reload_suppressed |
| X01 | sensor.py | sensor: attrs unrecorded | test_open_tracks_sensor_carries_diag_unrecorded |
| X02 | sensor.py | sensor: diag merge dropped | test_open_tracks_sensor_carries_diag_unrecorded |
| K01 | const.py | const: type missing from MEMORY_EPISODE_TYPES | test_one_call_one_row_per_crossing, test_people_count_clamped_to_frame_bounds, test_interior_camera_event_never_matched (+21 more) |
| K02 | const.py | const: type missing from WRITER_BACKED | test_registered_episode_type_and_writer_health |
| K04 | const.py | const: CLUSTER_S 60->0 | test_cluster_one_call, test_cluster_completed_request_no_second_call |
| K05 | const.py | const: DAILY 40->0 | test_one_call_one_row_per_crossing, test_people_count_clamped_to_frame_bounds, test_interior_camera_event_never_matched (+25 more) |
| K07 | const.py | const: MATCH_S 10->1000 | test_event_outside_match_window_not_matched, test_failure_classes_recorded_never_raise, test_clip_url_instance_scoped (+1 more) |
| K08 | const.py | const: EPISODE_TYPE | test_one_call_one_row_per_crossing, test_people_count_clamped_to_frame_bounds, test_interior_camera_event_never_matched (+20 more) |
| K10 | const.py | const: ERROR_RATE_MAX 0.25->2 | test_error_rate_pages |
| K11 | const.py | const: DAILY_MAX 200->10 | test_daily_cap_number_publishes_and_persists |
| K13 | const.py | const: MAX_FRAMES 4->1 | test_one_call_one_row_per_crossing |
| K16 | const.py | const: ZERO_MIN 5->1 | test_zero_fire_needs_min_crossings |
| K17 | const.py | const: ERROR_MIN_CALLS 8->1 | test_error_rate_needs_min_calls |
| K19 | const.py | const: RING 20->1 | test_match_picks_highest_score_then_longest |
| K20 | const.py | const: KEEP_FRAMES True->False | test_use_memory_false |
| K21 | const.py | const: TARGET_WIDTH 768->1 | test_one_call_one_row_per_crossing |
| K22 | const.py | const: MODEL | test_one_call_one_row_per_crossing |
