# Plan review: step 8 identity actions rev 3.5, framing 1 (completeness)

Plan: `docs/planning/PLANNING_identity_actions_v6.md` @ `f96ccf7c` (feature/step8-identity-actions). Code cites are at
`f96ccf7c` (read through `git show` / `git grep`; the worktree was not touched). Rev 3.4 compared at `f20f54bc`.
Read first: charter goals, `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (in full), `SENSOR_FLEET_CLASSES.md`, the F5 source
audit, card PERSON-PROFILE-PREFERENCES-1 decisions. No corrections-ledger claim re-asserted.

## Verdict: REVISE

One CRITICAL (the flap filter the whole trigger rests on does not exist in code), two HIGH, seven MEDIUM.

## Findings

### CRITICAL-1: `counted` does not mean "away at least 15 minutes". A GPS flap is a counted arrival.

Plan §0 (line 21), §2 row "Counted return", §5.4 gate 3, §7 ("19 flaps (all GPS) rejected by `counted`"),
INV-V6-ARRIVAL-START, D2 tests `::test_gps_flap_not_counted_opens_no_intent`,
`::test_uncounted_return_no_departure_seen_opens_no_intent`.

Code: `arrival_edges.counted_return` (`arrival_edges.py:141-156`):
```python
if old_val not in _UNREAL:
    return True  # not_home / named zone -> home
return really_away(...)
```
The 15-minute test (`really_away`, `:126-140`) runs ONLY for `unknown` / `unavailable -> home`. Every
`not_home -> home` edge is `counted = True`, whatever the absence length. The residency tracker uses exactly this
(`residency.py:133-142`). The presence state of play says the same (§1 table, lock regime: "`→ home` from
`not_home`/zone counts; from `unknown`/`unavailable` only if ..."). The "19 flaps rejected" figure is the D0 probe's
own computation, not this flag.

Also wrong: "no departure seen" is not uncounted. `really_away` returns True when the ledger entry is missing or
restored (`:135-136`, M-2 (ii)), so `unknown -> home` with no real transition since a restore is COUNTED.

Repro (legal, live shape): Oji in the master an hour, phone GPS `home -> not_home` (40 s) `-> home`. The second edge is
`counted=True, source_stale=False, in_boot_window=False`. Intent opens. Music starts in the master he is sitting in
(gate 3: he is placed there, so the backstop is skipped; nobody else placed; no guest), and `arrived` fires at once.
19 of 80 arrival edges in 7 days were such flaps (audit §3), so roughly one in four "arrivals" plays music on someone
already home. `ARRIVAL_MIN_GAP_S` caps it to once an hour per person.

Fix in the plan: the engine computes the absence itself from the F1 log it already may read:
`get_person_edges_since(edge_ts - RESIDENT_RETURN_MIN_AWAY_MIN*60, persons={p}, kinds={"departure"})` non-empty means
away under 15 min, so not an arrival; truncated means fail closed (the rev 3.4 shape, minus the F5 part). Changing
`counted_return` is not an option here: the lock regime shares it (INV-RULE). The tests must drive the real
`ResidencyTracker` with a timed `home -> not_home -> home` sequence; a hand-built `ResidencyEvent(counted=False)`
passes while production fails (Bug Class #62 / #63). Restate §0, §2, §5.4, §7, §14 ("the `counted` flag on the edge
carries the 15-minute bar for every arrival" is false) and the D0b split.

### HIGH-1: the window-end stop can cut off music another person is listening to

§5.5.2 stops when P was never seen in R. "Nothing else is re-checked during the wait." Gate 3 is a start rule only.

Repro: Oji and Ezinne both list the master (shared). They arrive together; Oji's intent starts the music; Ezinne's
start reads `skipped_playing`. Ezinne goes up to the master at minute 3 and listens; Oji stays in the kitchen. At
minute 15 Oji's wait finds no Oji in the master and calls `media_stop` on music Ezinne is playing. Same with Jaya or an
untracked guest walking in during the window. This breaks the review question "no path stops music the person is
listening to": the person need not be P. The co-owner case is the operator's own named case ("Shares spaces,
likely same").

Fix: at window end, skip the stop (outcome e.g. `wait_kept_occupied`) when any tracked person is placed in R, a
co-owner's intent reached R, or the room coordinator reads occupied with an onset after `t_a`. Add the shared-master
test (rev 3.4 had `::test_two_owner_intents_music_once_scene_ambiguous`; it was dropped, see MEDIUM-7).

### HIGH-2: the content-id guard is unverified and likely mismatches for a playlist pick

The stop, `wait_ended_not_ours` and the departure pause all compare the player's `media_content_id` with the stamped
`media_content_id` (the pick sent). Music following itself treats that attribute as the item now playing and replays
it as such (`music_following.py:1408-1416`). For an MA playlist, album or station pick, the player most likely reports
the current track, not the playlist URI. I have not verified MA's attribute behaviour; I would be guessing on the exact
value. If it differs, the first listener pass reads `wait_ended_not_ours`: no stop ever happens, a never-reached room
plays forever, and `departure_kept_not_ours` is the only departure outcome. The guard fails safe for interruption but
silently disables INV-V6-ARRIVAL-WAIT's stop and INV-V6-DEPARTURE-REACHES.

Fix: add to D2 B0 (operator present): read the native and MA entities' `media_content_id` immediately after start and
after a track change. Stamp what the verified player reports (and the MA queue / source id if that is the stable
field), and say in the plan which attribute is compared.

### MEDIUM-1: paths that leave music playing in an empty room with no end

The plan does not show the "never forever" half of review item 4. Paths found:
- hand-off with music following off for P: music stays "until someone stops it" (§5.5.3). Oji arrives, reaches the
  master, goes downstairs for the evening: music plays in the empty master until bedtime or a house departure. No
  room-vacancy media stop exists (`automation.py`, `coordinator.py`: no `media_stop` / `media_pause`).
- hand-off with music following on, transfer refused: next room has no player (`no_target_player`,
  `music_following.py:973-975`), room opted out, cooldown, hazard, house-state gate, target playing. Same result.
- restart mid-wait: `wait_lost_restart` leaves it playing (§5.9); the departure stamp is lost too.
- HIGH-2's mismatch.
Operator #2 accepted "music following owns it", but not "plays to an empty room for hours". Either add a cheap end
(the departure-pause check machinery already exists: pause when R goes vacant for its `occupancy_timeout` + margin
with the stamped content still playing, until the stamp is cleared) or put the trade to the operator as a §12
question with the repro above. The restart sweep can stop a `wait_lost_restart` whose window has passed if the
player still reports the stamped content (the episode carries entity and content id).

### MEDIUM-2: the reach check accepts only the target room, so an ensuite counts as "never arrived"

`arrived` / `late_seen` require P placed in the target room (§5.5.2). Repro: Oji, `rooms_bedroom=[master]`,
`rooms_bathroom=[master bath]`; he arrives and showers for 15 minutes; BLE places him in the master bath; the music in
the master is stopped while he can hear it. Accept any of P's own rooms (or rooms sharing the target's scanner area)
as reached, or say why not.

### MEDIUM-3: a toggle turned off mid-wait does not stop the stop

§5.5.2 re-reads nothing at window end; §5.5.1 gate 0 runs only at open. INV-V6-OFF-MEANS-OFF says nothing under an off
toggle acts "whether it was turned off before the intent opened or inside the window". The window-end `media_stop`
is an action. Repro: start at minute 0, operator turns the master (or `auto_music`, or the music-following coordinator)
off at minute 5, P never reaches R, stop at minute 15. Add a toggle read at window end (outcome e.g.
`wait_ended_toggled_off`, no stop) and a test; rev 3.4's `::test_toggle_off_mid_window_skips` was dropped and only
`::test_toggle_off_before_start_skips` remains. Same question for a room paused mid-wait (gate 2 is start-only).

### MEDIUM-4: INV-V6-HANDOFF is false as worded and its tests do not discriminate

"The music follows P to the next room iff `_person_enabled(P)`." Music following is room-based: the source is
whatever plays in the room the transitioning person left (`_resolve_source`, `music_following.py:1103-1112`). So:
(a) with `_person_enabled(P)` True the transfer can still be refused by the gates listed in MEDIUM-1; (b) with it False,
another enabled person leaving R after P carries P's music (once P is gone `_source_has_other_occupants` no longer
blocks, `:1823`). That is fine behaviour, but the invariant claims otherwise. Restate it as: step 8 adds no transfer
and no state; whether the music moves is music following's own decision for whoever leaves R. Test (b) explicitly.

Hand-off visibility itself holds: engine-started music in R is a valid transfer source because the source is
room-based and `_person_enabled` is read at `:821` (`music_following.py:410`). The repair's `_ble_gate` and
stale/cooldown gates apply as for user-started music.

### MEDIUM-5: the guests read has no None rule

`get_house_census(...)` returns None with no census, no result yet or any error (`census_view.py:84-130`,
`presence.py:6051`). §5.5.1 gate 3 and §5.6 gate 4 do not say whether None blocks or passes. Fail closed means an
install with no cameras never gets arrival music (portability rule); fail open means a census outage plays music on
guests. Pick one, name the outcome (`guests_unknown`), and test it.

### MEDIUM-6: the named-exit departure arm has no trigger

§5.7 arms on "the first of" a named exit via `get_last_crossing` (a pull read, `presence.py:6067`) or the residency
departure push. Nothing says when the engine pulls: on each person-coordinator update? on
`SIGNAL_EGRESS_RECORD_AMENDED`? `get_last_crossing` returns only the latest crossing, so a second crossing can replace a
named one before a poll. Name the trigger (a push is available: the amend signal, ship 3a G3) and the read
(`get_crossings_since` is the windowed pull, ship 3a G2). Also state the lifecycle of the per-stamp
`subscribe_person_edges(persons={p})` subscriptions (one per stamp, or one shared with a filter).

### MEDIUM-7: Plan Completion table is incomplete

Rev 3.4 tests not in rev 3.5 and not accounted for in §14 (beyond the BLE / entry-time / near-rule rows):
- `::test_face_alone_opens_no_intent`: INV-V6-NO-FACE-ALONE is still asserted and now has no test. Keep it (drive a
  `camera_face` / `camera_egress` F5 and a sighting; assert no intent).
- `::test_toggle_off_mid_window_skips`: see MEDIUM-3.
- `::test_two_owner_intents_music_once_scene_ambiguous`: see HIGH-1 (the scene half survives as
  `::test_scene_ambiguous_two_owner_intents`; the music half is gone).
- `::test_no_hook_in_on_person_transition`: §7 site 3 still says `_on_person_transition` is NOT a site; keep its guard.
- `::test_people_form_visible_conditions`: exists at `quality/tests/test_person_profile.py:347` but is missing from
  the D1 list.
Nothing removed in §14 is still referenced elsewhere in rev 3.5 (`ARRIVAL_OCCUPIED_LEAD_S`,
`ARRIVAL_COUNTED_EDGE_LOOKBACK_S`, `get_room_zone`, `intent_duplicate_source`: 0 live references in the plan body).

## LOW

- L1 `get_person_location(person_name)` is keyed by the person coordinator's own keys (display names live,
  `person_coordinator.py:2220-2223`); the trigger carries `person.<slug>`. Name the mapping (the tracked-persons list
  through `tracked_person_entity_id`), not a slug guess.
- L2 `location_moves_since(t: datetime)` (`presence.py:6119`) but §5.5.2 passes `t_a - update_interval` with `t_a`
  an epoch float. Same class as the named-exit `datetime` drill; add a drill/test for it.
- L3 Gate 1 "not in observation mode": `observation_mode` lives on the domain wrapper
  (`domain_coordinators/music_following.py:528, :571`), the engine is `music_following.MusicFollowing`. Name the read.
- L4 Knobs without a name: the restart sweep's "+ 1 h"; trip-wire thresholds `arrival_action_zero` (10 / 7 d),
  `arrival_music_failing` / `welcome_scene_failing` (3 / 24 h), `arrival_guest_block_high` min intents (10). Give
  each a constant (rung 1). The rest of §9 is complete: every named knob has a rung and a reason;
  `ARRIVAL_*` constants are all NEW except the reused master (`const.py:5022, :5033`) and the two residency constants
  (`const.py:4109-4110`).
- L5 With CRITICAL-1 unfixed, a GPS flap also opens a scene window: walking out of and back into the bedroom inside
  15 minutes re-applies the welcome scene over a scene the person may have changed.

## Item-by-item

1. Arrival trigger. Producer: `presence._handle_geofence_change` -> `_feed_residency` (`presence.py:5684`, `:5361`);
   push `residency.subscribe_person_edges` (`residency.py:233`), presence delegate `presence.py:6081`; only other
   subscriber `crossing_vision.py:426`. Record fields exist (`residency.py:39-51`); `in_boot_window` and
   `source_stale` behave as described (`:93`, `:150-151`). `counted` does NOT (CRITICAL-1).
2. Gates. Placed person: `person_coordinator.py:2220` (STALE included, as the plan says). Guests:
   `presence.py:6051` -> `census_view.py:115` (awareness) / `:127` (trust = `unidentified_count`); None case open
   (MEDIUM-5). Backstop onset: `coordinator.py:6383` / `:6396`. Quiet hours `notification_manager.py:4774`; paused
   `const.py:1467`. 480 s backstop: NEW, absent as expected.
3. Hand-off: visible to music following (room-based source); invariant wording wrong (MEDIUM-4).
4. Stop paths: timer (HIGH-1, HIGH-2, MEDIUM-2, MEDIUM-3); late arrival (counted, no restart, by design); restart
   (MEDIUM-1); operator pause (MEDIUM-3); music following moving it (`wait_ended_not_ours`, safe). Empty-room-forever
   paths exist (MEDIUM-1).
5. Welcome scene: hook built (`automation.py:1746-1803`, override only on the day / evening caller `:1591`, sleep
   caller `:1488` passes none). Own-bedroom, guests and B2 retry are D3 work, specified adequately; B2 retry absent in
   code as expected.
6. Knobs: L4.
7. Plan Completion: MEDIUM-7.
8. Invariants: ARRIVAL-START is falsifiable but its flap clause is false against code (CRITICAL-1) and its flap test
   discriminates only if it drives the real tracker. ARRIVAL-WAIT is falsifiable; it needs the third-party listener
   case (HIGH-1). HANDOFF is false as worded (MEDIUM-4). SCENE-ROOM is falsifiable and its listed breaks discriminate.

## Must fix before D2 dispatch

CRITICAL-1, HIGH-1, HIGH-2 (as a D2 B0 item), MEDIUM-1 (decision or operator question), MEDIUM-3, MEDIUM-4,
MEDIUM-5, MEDIUM-6, MEDIUM-7. MEDIUM-2 and the LOWs can land in the same revision.
