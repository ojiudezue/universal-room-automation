# Step 8 arrival engine: Review C (test authority, real per-site source mutation)

Branch `feature/step8-d2-engine` @ c05e2103, diff base `c67b8a78...HEAD` (three-dot).
Method: 436 single-site mutations of production source (music_following.py engine,
domain_coordinators/music_following.py, automation.py B2 retry, sensor.py, const.py), my own
enumeration (not the builder's list). Each: one edit, `__pycache__` purged, `-B` +
`PYTHONDONTWRITEBYTECODE=1`, `pytest -x` over test_arrival_music, test_arrival_fixpass,
test_welcome_scene, test_arrival_scene_entry_hook, test_mf_ma_twin_wiim_uuid, test_person_profile,
test_music_following, test_music_following_coordinator, test_music_following_repair,
test_v5100_music_following, test_person_awareness_layer_guard (baseline 659 passed, 2 skipped);
restored in `finally`, byte-identity asserted, `git status` clean at the end.
Drill scripts: `.claude/tmp/rvwc_drill.py`, `.claude/tmp/rvwc_drills_list.py`; raw output
`.claude/tmp/rvwc_out.txt` (one line per mutation: index, RED/GREEN, label, first failing test).

## Counts

| | n |
|---|---|
| mutations run | 436 |
| invalid (syntax error, redone as #434) | 1 (#312) |
| RED (specific test failed) | 266 (includes control #435) |
| GREEN (suite stayed green) | 169 |
| of which equivalent / redundant defense | ~15 (listed below) |
| of which untested (gap) | ~154: HIGH 8 groups (~14 sites), MEDIUM ~55, LOW ~85 (bucketing approximate) |

Verdict: **FIX-REQUIRED** (test additions only; no production defect was demonstrated, but eight
HIGH sites can be neutered with the suite green).

## HIGH gaps (neuter leaves suite green; production consequence is silent or unsafe)

| # | site | neuter | why it matters | test needed |
|---|---|---|---|---|
| 005-008 | `_async_arrival` gate 2: `resident_set_resolved`, `pc_key is None`, profile has an action on, `own_rooms(prof)` | each term replaced by False | no test mentions `skipped_no_rooms`/`skipped_no_presence`; a non-resident, an un-opted resident, or a resident without own rooms opens an intent (and writes rows / trip-wire inputs) | 4 negative cases: record with `resident_set_resolved=False`; person not in tracked_persons; profile with both actions off; profile with no own rooms: no `intent_opened`, count `skipped_no_rooms` |
| 099 | `_music_start_body` never-interrupt: `_any_playing((native, ma))` | `(native,)` only | `test_never_interrupts_native_or_ma_playing` plays the NATIVE; production plays via the MA twin (`*_7`) while native may read idle, so the start would interrupt the user's music | ma-twin-only playing, native idle: `skipped_playing`, no play_media |
| 104 | `_grouped` self-exclusion `any(m != eid ...)` | `if members:` | a solo Sonos/WiiM lists itself in `group_members`; the mutation makes every such player "grouped" and the start never happens. Not exercised | `group_members=[self]` starts; `[self, other]` skips |
| 113 | `play_media` exception branch -> `start_failed` | `raise` | no test makes play_media raise; `arrival_music_failing` trip-wire (#357, also GREEN) has no producer test | play_media raises: outcome `start_failed` with the error type; `inflight` claims released |
| 392/393 | `_arrival_teardown` clears `_arrival_intents` and `_arrival_stamps` | clear removed | after a CM reload the engine survives with stale intents (timers cancelled, never popped): every later arrival for that person is `intent_duplicate`; stale stamps keep a dead stamp | teardown with an open intent and stamp, restart, same person arrives again: opens an intent |
| 389 | teardown `stamp.cancel_listeners()` | removed | the player state listener outlives teardown (HA bus leak). `test_player_listener_removed_at_terminal_and_teardown` asserts only the terminal case; its name claims teardown but it never tears down (hollow anchor, Bug Class #62) | assert `stamp.player_unsub is None` / bus listener count after `async_teardown` |
| 276 | `_departure_end` -> `_end_stamp` | removed | the stamp is not ended after `departure_paused`; the final timer (#271 also GREEN) can fire a second check and a second pause | after `departure_paused`, fire the final timer: no second `media_pause`; stamp gone |
| 306/307 | `_scene_end`: `scene_done` set / idempotency guard | removed | the scene decision's terminal marker; duplicate outcome rows and re-consumption after a decision | call `_scene_end` twice / re-entry after `scene_confirmed`: one outcome row |

## MEDIUM gaps (grouped; each needs one targeted test)

Start path
- #032 `_latest_row_ts` person filter removed: another person's departure row satisfies gate 3b (test: only a different person's row present -> `departure_missing`). #030/#031 DB-path `short_absence` and boundary untested (only the left_at path is). #034 newest-row selection (two rows). #026 strictly-before.
- #044 bedroom-before-bathroom order: `test_target_room_bedroom_first_then_bathroom` actually tests the bathroom FALLBACK (bedroom list holds a player-less room); reversing the key order is GREEN. Needs bedroom AND bathroom both with players: bedroom wins.
- #079 `skipped_no_media` untested (play_media with an empty pick). #080 slot passed to `pick_media` (`resolve_slot(sleep_on, dark)`) untested.
- #081/#082 native player vanished/unavailable between target pick and start untested.
- #085 zone fallback player's room unresolved (`zone_room_unresolved`): the builder's drill "D5 zone player room unresolved" went RED only because its mutation (`zroom = None`) broke the occupied-room test; the branch itself is untested. #086/#087/#089/#090 zone room check_rooms membership, check_rooms add, zone-room backstop (and own-placement exception) untested; the only zone test covers `others_in_rooms`.
- #095/#096/#097 MA twin in-flight check/claim/claim list; #097 means a leaked MA claim (never discarded) is not detected: a second start on the same room after the first finished must still start.
- #106 `_started_players.add(play_eid)`: the hazard stop scope would miss an arrival-started player (safety); no test asserts a hazard stop reaches it.
- #111 `test_volume_scale_clamped` is hollow: with `music_volume=1.0` and scale 1.5 the mutated `volume = music_volume(prof)` also yields 1.0. Use 0.8 x 1.5 -> 1.0 and 0.5 x 0.8 -> 0.4.
- #124 `_music_end` idempotence; #135/#136 `_toggle_off` coordinator and observation re-reads (only master is tested mid-window).
- #163 ownership listener tracks `play_eid`: mutation listens to `native`; with an MA twin as `play_eid` foreign writes are invisible. Needs a start that plays on the MA twin, then a foreign pause on the twin.
- #155 stamped player removed (`new is None`) ends ownership.
- #190 placed_in_bedroom bedroom-only; #217 window end must not pop an intent in `pending_confirm`.

Window end / departure
- #234/#236/#237 `media_stop` vs `media_pause` selection by `supported_features` (only the default is observed; the pause-only player and the parse guard are untested).
- #239/#241/#243/#245/#247 acting release, failed-stop swallowing, listener drop on stop, and the ARRIVAL_REVERSAL_S watch timer / `_end_watch` (a stamp can linger forever).
- #250/#251 `_moved_into_own_room`: person filter and `to_room in own rooms` filter removed, suite stays green (only the positive case is tested). #249 interval offset.
- #256/#257/#258 `_coowner_arrived` handed-off-stamp branch entirely untested.
- #280 `get_person_edges_since(... persons={person})` scope removed: another person's arrival counts as this person's return and suppresses the pause. #271 final timer unsub not stored (teardown/stamp end cannot cancel it).
- #262-#264 departure guards (duplicate departure on the same stamp, `watch_until`).

Scene
- #314 `scene_on` filter, #315 `scene == ""` filter in `arrival_scene_for`: a second bedroom entry would re-decide (possible double welcome scene). #326 non-`scene.` value. #329/#330 `note_arrival_scene_result` match conditions (two intents). #338-#340 confirm-timeout branches.
- #424/#425 automation B2 retry: `slot_id` None and `slot_id != welcome` guards (the retry would re-run the same broken scene / a None scene).

Restart sweep, trip-wires, sensor
- #342/#348/#349 sweep negatives: an intent outside the window, an intent that already has a terminal outcome, and a stamp that already ended are still reported as `*_lost_restart`. #343 `opened is None`, #341 database None.
- #357 `arrival_music_failing` and #359 `arrival_entry_missed` trip-wires have no test at all (the other five do); #358 `scene_fallback_failed` inclusion.
- #365 `last_arrival_action` store untested end to end (sensor test stubs the engine); #367 episode node id.
- #379 `arrival_opted_in` scene-only profile; #397/#398 teardown flag pop and ownership check.

Lifecycle
- #392-#396 teardown clears (inflight rooms, inflight players, opening: belt-and-braces, LOW; intents/stamps are HIGH above); #391 teardown task cancel (teardown currently waits out the 5 s timeout instead; no assert); #401 spawn discard; #406 `async_init` wire-in of `async_start_arrival_actions` (only the coordinator-setup call site is anchored, #407/#408 RED).
- #419 MA twin `disabled_by` filter (a disabled MA entity can be chosen as the play target).

## LOW gaps and boundary/default variants (not individually test-worthy; one parametrised test each)

#001 gate-1 coordinator check (also caught later by `_toggle_off`, but an intent row is written); #004 presence None; #010/#012/#014 fail-open defaults on missing record attrs (`counted`/`source_stale`/`in_boot_window`); #018 `left_at < edge_ts`; #022 and #023 (equivalent outcome, subtype differs); #024 DB lookback window; #035 `started_at` fallback; #038/#043 scene-only person still targets/starts music (toggle catches it; row noise only); #041 window remaining from edge_ts; #053 `intent.music` reset on cancel; #057/#058 window_due; #059 `_stop_quietly` swallow; #077 gap boundary; #082 native state; #099-adjacent #103 MA twin in `_grouped` start check; #115 hazard verify stop call; #139 welcome_scene toggle key; #148 ambiguous area rooms; #151 ctx-id cap; #156 listener done guard; #160/#161 reversed labels (vol 0 / standby); #164; #169; #176/#178; #180/#182/#183 listener need terms (my #180 direction was loosening, treated equivalent); #195/#198/#200; #207; #212; #220/#222/#223/#225; #267; #275; #283/#284; #288; #291-#293 (`departure_kept_other_playing`: dead while `ARRIVAL_OURS_ATTR=None`, so unreachable by default); #301/#302; #308/#311/#322/#333; #352/#355/#358; #363; #376/#377; #403; #410/#411/#413/#416/#420.

## Equivalent or redundant (GREEN, not a finding)

- #046 empty room name: `_get_room_player("")` returns None, so `_player_available` is False anyway.
- #048 `start: no room`: the later native-player check still ends `skipped_no_player` (outcome identical; only an inert `None` in the in-flight set).
- #056/#262 stamp-done guards: `_async_departure` re-checks `stamp.done`; done stamps are also popped from the table (#198).
- #142 `_suite_rooms` including R: R is always an own room of its owner, so the owners' union already contains it.
- #144 `_others_in_rooms` empty-rooms early return: the loop yields False for an empty set.
- #154 truthy-id: `None` is never stored, so `cid in ids` is False anyway.
- #180 `pc: sync handed_off` as mutated only reduces need for non-handed-off stamps, which an open intent already covers; #183 done stamps are popped.
- #252 presence None in `_moved_into_own_room`: AttributeError is caught by the surrounding try and returns False.
- #265 `_async_departure` stamp-None: unreachable, both callers pre-check the stamp.
- #255 self-skip in `_coowner_arrived` first loop: the caller's intent is `waiting`, never `arrived`.
- #313 owners filter in `arrival_scene_for`: the bedroom membership test implies ownership.
- #072 `_backstop_hit` occupied pre-check: an unoccupied room has no onset.

## Comparison with the builder's drill (`.claude/tmp/step8fix_drill_out.txt`, 60 sites, all RED)

All 60 builder rows are consistent with my RED set for the same sites (ownership, hazard x3,
suite, group, in-flight room/native, MA wiim_uuid and live-first, D10, D6, D8, B-M2, A-4..A-7, B-L1/L2/L4/L6).
Sites the builder's list missed (my GREENs above): gate 2 (4 terms), MA-twin never-interrupt, group self-exclusion,
`start_failed` path, teardown intent/stamp clearing and player-listener cancel, stamp end after departure outcome,
`scene_done`/idempotence, DB-row person filter and short-absence, move-log person/room filters, return-edge person scope,
bedroom-first order, no-media, zone-room unresolved/backstop, MA in-flight claim leak, started_players/hazard scope,
stop-vs-pause selection, reversal watch timer, sweep negatives, two trip-wires, B2 retry guards, `disabled_by`.
One builder row is RED for the wrong reason: "D5 zone player room unresolved" (#085 is GREEN: the branch itself is untested).
`test_volume_scale_clamped` and `test_player_listener_removed_at_terminal_and_teardown` are hollow anchors (#111, #389).

## Must-fix list (before ship)

1. Gate 2 negative tests (005-008). 2. MA-twin-only playing never-interrupt (099). 3. `group_members=[self]` starts (104).
4. play_media raises -> `start_failed` + the two missing trip-wires (113, 357, 359). 5. Teardown then restart: intents,
stamps and player listener are gone (392, 393, 389; fix the hollow test). 6. No second pause after `departure_paused` (276).
7. `scene_done` idempotence and no second welcome scene on re-entry (306, 307, 314, 315).
Then the MEDIUM groups above, in particular the DB-row person filter (032), move-log filters (250/251), return-edge person
scope (280), MA claim leak (097), hazard scope (106), and ownership listener on the MA twin (163).

Tree left clean (`git status` empty before this file).
