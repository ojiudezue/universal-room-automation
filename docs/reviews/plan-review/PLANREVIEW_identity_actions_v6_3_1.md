# Plan re-review: PLANNING_identity_actions_v6.md rev 3.1 (arc step 8, v6.0.0)

Reviewer: ura-planner (Mode 2, focused re-review). 2026-11-14.
Target: `plan/identity-actions-v6-rev3` @ `72e4befd`. Prior review: `PLANREVIEW_identity_actions_v6_3.md` (FIX-PLAN).
Code base checked: `develop` @ `d6861dc0` (descends from `2f3ee354`; v5.108.22 live), `feature/layer-ship3a` @ `9d61a315`,
`feature/music-following-repair` @ `c5685b5f` (contains `706f7230`). Ship 3 plan: `plan/person-awareness-ship3` @
`aa6cd900` (rev 3.4).

Read first, completely: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and
`docs/architecture/SENSOR_FLEET_CLASSES.md`. No corrections-ledger claim is re-asserted here. Skill `ura-arc` loaded;
charter `ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md` (goals, 2026-11-14 additions, drift #20).

**Verdict: FIX-PLAN for D2-D4 (§5.4-§5.6). The §10.1 parallel set may start now** (D0, D1, `pick_media`,
`occupied_since()`, the `automation.py` override read, D6 episode types), on the base named in M4. 2 HIGH, 7 MEDIUM, 6 LOW.
None of the HIGHs touches the parallel set, so the build does not need to wait for the fixes, which matches "you better
get a move on". The fixes are spec edits in §5.4-§5.6 plus one D0 row.

---

## 1. Prior findings: verified against code

| ID | Claimed fix | Verified | Verdict |
|---|---|---|---|
| H1 trigger | Open-time `get_person_location` plus a person-coordinator listener reading `location_moves_since`, then a location re-read; nothing in `_on_person_transition` | Move site records only when `old_location not in ("unknown", "")` (`person_coordinator.py:1095` develop), so the re-read is needed for `unknown -> room`, as the plan says. 3a builds `location_moves_since(t: datetime)` with `ts >= t`, oldest first, plain tuple (`feature/layer-ship3a` `person_coordinator.py:2306`), and a reserved R10 listener row `('R10', 'music_following.py', '<step 8 §5.4 music listener>:async_add_listener[PC]')` (allowlist l.320, l.334) | Fixed in design. Gaps in M1 (cursor), M2 (truncation) |
| H2 scene | Override inside `_maybe_activate_slot_scene`, day/evening caller only | `automation.py:1740` (def), hold check `:1766`, state guard `:1777`, `scene.turn_on` `:1796`, callers `:1482` sleep and `:1585` day/evening; `if not scene_id: return False` means `arrival_scene_for(room) or slot_scene(...)` gives "welcome without a slot scene", as D3 claims | Fixed. Attribution gap in H2 below |
| H3 self-occupancy | `occupied_since()` onset vs entry minus `ARRIVAL_OCCUPIED_LEAD_S` | `_became_occupied_time` is set on the vacant tick (`coordinator.py:4340`), the camera override sets it only when None (`:4409-4410`), it is deliberately NOT cleared at motion timeout (P24, `:4354`) and it is restored across restart (`__init__.py:5532-5538`). So it is a session start, which is what the gate needs. The entry-time side is wrong in one path (M3) | Fixed for the move path; M3 for the open-time path |
| M1 master | Consumer `options.get(..., True)`, form default True, switch dropped | Live read: no URA entry stores `music_on_arrival_start` (only `music_following_coordinator_enabled: true`). Form default today is `False` at `config_flow.py:10499` (develop) and `:10384` (repair branch); the plan's `:10415` is stale. Consumer default True needs no migration | Fixed |
| M2 room source | Layer room for music; entry path room confirmed by layer for the scene | Stated in §5.4 | Fixed |
| M3 outcomes | Full table, one line + one episode each, `entry_missed` trip-wire | Table present; two holes (M5) | Mostly fixed |
| M4 MediaSelector | B0 (ii) on 2026.11.1 options flow | In D1 | Fixed |
| M5 `visible` coverage | Stub-marker venv test, live fixture, stop on serialize failure | In §5.2 and D1 | Fixed |
| M6 8 ft gate | Owned by the repair branch | `706f7230` is on `feature/music-following-repair` and removes `ble_too_far`, the form field and the distance plumbing (`person_coordinator.py`, `transitions.py`, both music files) | Fixed |
| G1 schedule | §10.1 parallel set, no raw fallback | Present; base branch unnamed (M4) | Fixed with M4 |
| L1-L7 | Restored | Quiet lookup, `test_r7_and_perimeter_followup_same_crossing`, D1 discriminator, D5 live line, no bonus joins, D0 0.50 confidence all present; knob table updated | Fixed |

---

## 2. Findings (ranked)

**H1 (HIGH). An F5 that is not a physical arrival opens an intent, and the open-time read then starts music on a
resident who never left.**
The presence doc §1 says it outright: "`SIGNAL_PERSON_ARRIVING` is NOT a physical arrival". The plan's own fire check
counts 218 F5 signals in 14 days, about 15 a day for four residents. Some of them are geofence returns with no real absence.
Two examples: the 78 iPad blips in 7 days (corrections ledger #33), and a `not_home -> home` that HA's restore stamps.
§5.4 opens an intent on any `geofence` / `ble` F5 that passes the master and opt-in gates. There is no really-away test.
Repro (legal config, any time of day outside quiet hours): Oji has sat in the master for an hour. His GPS axis flaps
`home -> not_home -> home`, and presence dispatches F5 `geofence`. The intent opens. The open-time read returns
`master_bedroom`, an own room. Entry time is `get_person_previous_seen`, about an hour ago. The onset is his own session
start, also about an hour ago, which is not earlier than entry minus 120 s. The speaker is idle. Result: `started`, and
music begins on a person who never left. The BLE producer has its 15-minute `_person_was_away` guard
(`person_coordinator.py:1162-1170`). The geofence path has no such guard.
Fix:
- Open an intent only for a counted return, using the rule the lock regime and residency already share.
  `arrival_edges.counted_return` over the residency ledger, read through 3a's A1 `get_person_edges_since(t, persons, kinds)`
  with the A1b `counted` field. It needs a raw `not_home` of at least 15 minutes, `source_stale` False, and the edge
  outside the 600 s boot window.
- For `ble`, the producer's was-away guard already holds.
- A rejected F5 is counted as `skipped_not_counted_return`, with no decision line, like `skipped_master_off`.
- Add D0(a) "share of F5 by source that are counted returns".
- Add a D2 test `::test_gps_flap_while_in_room_opens_no_intent`, and the drill "drop the counted-return check".
- Add to INV-V6-ARRIVAL-REACHES's dual: no `started` for an F5 whose person had no counted return in the window.

**H2 (HIGH). The welcome scene goes to whoever walks into the shared master first, because the tracked-person guard is
blind at entry time.**
`arrival_scene_for(room)` asks two things: exactly one owner has an open intent, and "no other tracked person's layer
room is this room". It runs on the room's vacant-to-occupied edge, which is a body sensor. §4.6 says BLE trails that
edge by seconds to tens of seconds (BLE-WARM-CREATE-1; the same fact behind H3). So at that moment no BLE has placed
anyone, the second condition is always true, and the scene's "occupied" protection reduces to the vacant edge itself.
Repro: Oji arrives and his intent opens. Ezinne is home, a co-owner of the master with no open intent, and walks into the
master first. The room goes vacant to occupied on her motion. `arrival_scene_for` returns Oji's welcome scene, which logs
`scene_applied` and then `scene_unconfirmed`. Rule Q5 ("don't do it when someone is already in that room including in
your own room") is about protecting the person already there. Here the person who gets the action is someone other than
its owner, and nothing stops it. The same shape applies to a guest or a child.
Fix:
- Require the intent holder's layer room, at the moment of the call, to be this room or a room adjacent to it
  (`get_adjacent_rooms`, both directions, as NM panel targeting uses).
- Return None when the holder's layer room is any other known room, or when the person reads `away` or `unknown` and has
  had no move in the window. Count that as `scene_skipped_not_near`.
- If D0 (a2) shows the hall-to-bedroom path is often not adjacency-mapped, take the number to the operator instead of
  widening silently.
- Add a D3 test `::test_coowner_enters_first_holder_elsewhere_slot_scene` and a drill "drop the near check".

**M1 (MEDIUM). Cursor rule unspecified, with two failure modes.**
1. A BLE F5 is dispatched inside `_async_update_data` (`person_coordinator.py:1170+`), before `self.data` is committed.
   The intent-open `get_person_location` therefore reads the previous tick, and the arrival's own move has
   `ts = now` of that tick, which is earlier than the intent-open time. If the cursor starts at intent open, that move
   is excluded (`ts >= t` fails). Only the listener's re-read saves it, and §5.4 does not give that path an entry time.
2. `location_moves_since` is inclusive (`>=`). A cursor advanced to the last `ts` reads that move again.
Fix:
- Cursor start = the F5 timestamp minus one person-coordinator interval. For the BLE source, that is the tick's own `now`.
- Keep only `move.ts > cursor` after the first read, as ship 3 §12 tells step 7 to do.
- Entry time on the re-read path = `get_person_previous_location_time` (M3).
- Add a test `::test_ble_f5_same_tick_move_not_lost`.

**M2 (MEDIUM). No truncation handling, and the plan still cites ship 3 at `50f15517`.**
Ship 3 rev 3.4 §12 says: "Step 8 (3a): §5.4 moves shape and unit as above (on truncation, re-read
`get_person_location`)". Its `location_moves_truncated_since(t)` is True after a restart or reload, because the log is
RAM. Rev 3.1 never calls it. A truncated ring also makes `window_expired` versus `entry_missed` undecidable.
Fix:
- Cite `aa6cd900`.
- On each listener pass, call `location_moves_truncated_since(cursor)`. On True, re-read location and record
  `moves_truncated` on the outcome.
- At window end, a truncated window is classified as `window_expired_truncated`, not `window_expired`.
- Add `location_moves_truncated_since` to INV-V6-LAYER's read list and to the guard's music read set.

**M3 (MEDIUM). Open-time entry time uses the Bermuda AREA sensor's `last_changed`, which resets on area flicker inside
a room.**
`get_person_previous_seen` returns `area_state.last_changed` (`person_coordinator.py:2235`, written `:1143`). Several
Bermuda areas can resolve to one room: tier 2 `CONF_SCANNER_AREAS`, and tier 3 shared scanners. A flip between two
areas inside the master moves `last_changed` to now while the room session is older. The person's own session onset
then reads as earlier than entry minus the lead, so `skipped_occupied` fires on themselves. That is H3 again, in the
open-time path.
Fix: use `get_person_previous_location_time(name)` (`:2240`). It is set to `now` only on a real room change, and area
flips inside the room leave it alone. Fall back to `previous_seen` only when it is None. A move from `"unknown"` does
not set it, so the fallback covers the post-restart case.
Add a test `::test_area_flip_inside_room_does_not_self_block`.

**M4 (MEDIUM). §10.1 names no base branch. The real collision is the unmerged music repair branch, not 3a.**
Checked against `feature/layer-ship3a` (12 integration files):

| Parallel item | 3a overlap | Repair overlap |
|---|---|---|
| D0 | none | none |
| `occupied_since()` (`coordinator.py`) | none | none |
| `automation.py` override read | none | none |
| D1 | `sensor.py` (3a 15 lines, profile sensor) and `const.py` (3a 16 lines): textual only | `config_flow.py` (the same music form `:10384`), `__init__.py` (repair already adds `music_on_arrival_start` to the suppress set, `:7706` / `:8456`), `strings.json`, `translations/en.json`, `const.py`, `sensor.py` |
| `pick_media`, D2-D4 against fakes | none | `music_following.py` (3278 lines changed), `domain_coordinators/music_following.py` (the F5 handler) |
| D6 | `const.py` | `const.py` |

Nothing in the set touches `presence.py` or `person_coordinator.py`, so there is no conflict with the 3a builder there.
The repair and 3a do collide with each other at the move site: the repair adds `method` / `bermuda_area` /
`area_sensor` to the `ura_person_location_change` payload at `person_coordinator.py:1057`, and 3a appends its move log
at the same site. That merge belongs to whoever merges second, not to step 8.
Fix: in §10.1, state that the step 8 branch cuts from `feature/music-following-repair`. If the repair has merged by
then, cut from develop. D1 must not re-add `music_on_arrival_start` to the suppress set. The step 8 branch must not
edit the 3a allowlist file, which is PROVISIONAL. New step 8 code reads no `person_coord.data` (R2 group #23), only the
named methods.

**M5 (MEDIUM). INV-V6-COUNTED has three silent exits.**
1. A restart or reload mid-window loses the RAM intent, and no outcome is written.
2. A second F5 for the same person in the window: "first source wins", but the second F5 gets no outcome or counter.
3. A person turns `auto_music` off mid-window. The profile is read only at open, so the action still runs, which also
   breaks INV-V6-OFF-MEANS-OFF.
Fix:
- Write the `intent_opened` episode at open. At setup, count `intent_lost_restart` from `intent_opened` episodes with no
  outcome, the same pattern as `departure_stamp_lost_restart`.
- Count `intent_duplicate_source` for the second F5.
- Re-read the toggles at check time. Off means `skipped_toggled_off`.

**LOW.**
- **L1 `window_expired` paging nothing is right; the reason given is partly wrong.** Most arrivals end in a non-own
  room, so paging on it would be noise. Agreed. But `entry_missed` is computed from the same move ring the trigger
  reads, so it cannot see an `unknown -> room` entry that the ring never recorded.
  Fix: at window end, read `get_person_location` once more. An own room with the music still undecided records
  `entry_missed` (subtype `unrecorded`) and feeds the same trip-wire. That gives the trip-wire one reading the trigger
  does not share.
- **L2 `skipped_no_media` is fine, but it is better caught at save.** Keep the outcome. Also make the People step
  refuse `auto_music` on with no pick, or warn in the description. A hidden-but-required pick is the likely way it
  happens.
- **L3 music has no two-owner rule; the scene does.** Two owners arrive together, both intents are open, and neither
  BLE has placed the other yet. The first check starts music, while the scene gets `scene_skipped_ambiguous`. Operator
  said "Shares spaces, likely same", so music may proceed. State the asymmetry in §5.5 and pin it in a test, so a builder
  does not "align" it.
- **L4 the gate counts stale persons.** "Another tracked person whose `get_person_location` maps to R" includes a STALE
  location, which is kept for `decay_timeout` (300 s, `person_coordinator.py:1220-1226`). So a resident who left the
  room minutes ago blocks. That is conservative; accept it by name.
- **L5 stale line citations.** The plan cites `109ef2c9` lines; develop has moved. `get_person_location` is `:2188` (not
  `:1992`), `get_person_previous_seen` `:2235` (not `:2039`), the location-change fire `:1111` (not `:1063`), the
  master form `config_flow.py:10498-10499` (not `:10414-10415`), `CONF_MUSIC_ON_ARRIVAL_START` `const.py:4890`, and the
  `_became_occupied_time` sets are `:4340` / `:4409`. Re-cite them at build. The builder re-greps.
- **L6 wording.** §5.5 calls `arrival_scene_for` "read-only", but it marks the scene decided. Name it a decision call.
  Also name the lookup path from `AutomationEngine` to the engine (which `hass.data` key, and None when absent), and
  that the room key is the room entry_id the engine already holds.

---

## 3. Ship 3a seam (focus item 3)

| Requirement | Plan rev 3.1 | Finding |
|---|---|---|
| F5 read = `subscribe_person_arriving` (3a D1) | Says "via `dispatch_person_arriving` subscribers"; §2 row still names the raw subscribe at `domain_coordinators/music_following.py:281` | **M6 (MEDIUM).** Name `subscribe_person_arriving` as the read. Say D2 replaces the raw `SIGNAL_PERSON_ARRIVING` connect and retires the R10 row `('R10', 'domain_coordinators/music_following.py', 'MusicFollowingCoordinator.async_setup:ura_person_arriving')` (allowlist l.316; ratchet). Fix the INV-V6-LAYER text |
| Moves: plain tuple, `datetime`, separate truncation check | Shape right, no truncation | M2 |
| Reserved rows | Not mentioned | Part of M6: step 8 replaces the reserved placeholder `<step 8 §5.4 music listener>` with the real qualified symbol and sets `reserved: False` in the same commit |
| BLE-ARRIVAL-PRODUCER-HVAC-GATED-1 before v6.0.0 | 0 hits in the plan | Part of M6: add it to §10 "must ship before v6.0.0". Today `pc._pre_arrival_enabled` (`person_coordinator.py:1170`, written by `hvac.py:1241`) gates the BLE F5, so with the HVAC pre-arrival switch off, BLE arrivals never reach step 8 (ship 3 §14 Q4, operator pick A) |
| Never read a distance | Drill present; repair removed the gate | Holds |

M6 counts as one MEDIUM.

---

## 4. Departure pause (outside the asked sections, found while checking Q6)

**M7 (MEDIUM, fix before D4 builds). Departure pause almost never fires.** §5.6 checks once,
at the first of the named exit or the `person.*` departure edge. It requires two things:
1. The room reads not occupied. A bedroom's occupancy timeout, plus the BLE chain hold and the 90 s absence grace, is
   still running when the person crosses the garage door a minute or two later.
2. No tracked person's layer room is the room. The departing person's own location stays on the room for up to
   `decay_timeout` (STALE, `person_coordinator.py:1220-1226`).
In the common case this ends in `departure_kept_occupied` or `departure_kept_shared` on the person themselves.
Q6 ("Departure pause is fine", on) would then be delivered in name only. D0 (b) already measures "how often the arrival
room was empty within 5 min after".
Fix:
- On the departure edge, arm a wait of `ARRIVAL_DEPARTURE_VACANCY_WAIT_S` (rung 1, D0 (b) sizes it, default 600).
- Pause at the room's occupied-to-vacant edge inside the wait if the stamp is still ours.
- Exclude the departing person from the "tracked person here" check.
- Window end with the room still occupied → `departure_kept_occupied`.
- Add a test `::test_departure_pauses_when_room_empties_after_exit`, and the drill "check only at the edge".


---

## 5. §10.1 parallel set (focus item 4)

The set is genuinely independent of ship 3a:
- D0 is read-only.
- D1 and `pick_media` read no layer call.
- `occupied_since()` lives in `coordinator.py`.
- The override read lives in `automation.py`.
- D6 is constants.

None of it edits `presence.py` or `person_coordinator.py`, so there is no textual or semantic conflict with the 3a
builder. The only shared files are `const.py` and `sensor.py`, both additive. The collision to manage is the unmerged
music repair branch (M4).

Two cautions:
- The D2-D4 wiring against fakes should wait for H1, H2, M1-M3, M5 and M7 to land in the plan. Otherwise the fakes
  encode the wrong cursor and gates.
- The H1 fix adds one more 3a read, `get_person_edges_since`. 3a builds it in D2, which waits for census-p2. So the
  real-call switch for H1 lands with 3a's D2, not D4. Say so in §10.1.

---

## 6. Framing G: goal fidelity

| Operator ruling | Rev 3.1 | Verdict |
|---|---|---|
| Q1 Tier 2-DB | §11 | Held |
| Q2 6.0.0 = step 8 | D7 CLAUDE.md edit | Held |
| Q4 v6.0.0 before F-NOTIFY | Count follow-up dark until CD4 (§5.7, §10) | Held |
| Q5 "don't do it when someone is already in that room including in your own room" | Occupied gate, no knob, co-owner included | Held for music. H2 opens a hole for the scene (wrong recipient) |
| Q6 departure pause on | `ARRIVAL_MUSIC_DEPARTURE_PAUSE` True | Delivered in name, near-never fires (M7) |
| Profile pull-ins (bedroom, bathroom, owners, playlists by time and room, opt-in, welcome scene) | D1-D3, §14 "nothing parked" | Held |
| Per-person temperature cut | §13 | Held |
| Form field hiding on 2026.11 with fallback | `_cond`, B0 spike, stop-and-redesign on serialize failure | Held |
| Q1 open default: bathrooms music only, scene in bedrooms | §12, `arrival_scene_for` bedrooms only, D3 test | Held, built as default |
| Q2 open default: own rooms only | §5.4 | Held |
| Q3 open default: scene on arrival only | §12, §13 | Held |
| "When needed it's beautiful" | | At risk from H1 (music on a person who never left) and M3 (self-block) |
| "get a move on" (drift #20) | §10.1 | Served: the parallel set starts now |
| Hard constraint "I need away to be fast acting" | INV-V6-AWAY | Held. Nothing reads or writes `infer()` inputs. The H1 fix reads the residency ledger, which is not an `infer()` input |

No risk reduction in rev 3.1 changed what is delivered. The fixes above keep every ruling. H1 narrows what counts as
an arrival to physical ones. That is a correctness narrowing, not a product change: the operator's rulings all assume
a real arrival.

### Drift check (ura-arc rule 7)

| Operator said | Where it drifted | Correction | Status |
|---|---|---|---|
| "step 8 is fine. You better get a move on" | Rev 3.1 sat with no re-review (drift #20) | This review. §10.1 starts now | Fixed by this review |
| "consumers can read and producers can feed" | F5 read named as the send function; the raw connect is kept in §2 | M6 | Open (plan edit) |
| Ship 3 Q4 "BLE-ARRIVAL-PRODUCER-HVAC-GATED-1 before v6.0.0" | Not referenced | M6 | Open (plan edit) |
| "Departure pause is fine" | Delivered in name | M7 | Open (plan edit) |

---

## 7. Exactly what to fix in the plan

1. H1: counted-return gate on intent open (A1b `counted`), a skip counter, a D0(a) row, a test, a drill, and the dual
   invariant.
2. H2: near check (holder's layer room is this room or adjacent), `scene_skipped_not_near`, a test, a drill.
3. M1: cursor start at the F5 timestamp minus one interval; `ts > cursor` after the first read; entry time on the
   re-read path; a test.
4. M2: cite `aa6cd900`; truncation check per pass and at window end; `window_expired_truncated`; add it to the
   INV-V6-LAYER list.
5. M3: entry time = `get_person_previous_location_time`, falling back to `previous_seen`; a test.
6. M4: §10.1 base branch = `feature/music-following-repair` (or develop once merged); no duplicate suppress-key
   add; no allowlist edits.
7. M5: `intent_lost_restart`, `intent_duplicate_source`, toggles re-read at check time.
8. M6: `subscribe_person_arriving`; retire the raw R10 row; un-reserve the listener row by its real symbol; add
   BLE-ARRIVAL-PRODUCER-HVAC-GATED-1 to §10's before-v6.0.0 list.
9. M7: departure vacancy wait, departing person excluded, new knob, test, drill.
10. L1-L6 as written. Then extend §15 with a 3.1 -> 3.2 table.

A re-review of §5.4-§5.6 and §10 only is enough after these edits.

## Summary

| Severity | Count | IDs |
|---|---|---|
| CRITICAL | 0 | |
| HIGH | 2 | H1 non-arrival F5 opens an intent, H2 scene goes to the first walker-in |
| MEDIUM | 7 | M1 cursor, M2 truncation, M3 entry time, M4 base branch, M5 silent exits, M6 layer seam, M7 departure pause |
| LOW | 6 | L1-L6 |

Bug classes: stale/ordering race (M1, M3), producer semantics misread at the consumer (H1: F5 is not a physical arrival),
blind guard at decision time (H2), computed-but-not-consumed (M2 truncation read), silent outcome (M5), goal delivered
in name only (M7).
