# Plan re-review: identity actions v6, rev 3.2 (§5.4-§5.6, §10)

- **Plan:** `docs/planning/PLANNING_identity_actions_v6.md` on `plan/identity-actions-v6-rev3` @ `9d142590`
- **Prior review:** `PLANREVIEW_identity_actions_v6_3_1.md` (`1e4dfeab`); rev 3.2 fixes listed in plan §15.3
- **Code base checked:** develop `109cd0df` (v5.108.23 live, census-p2 included); repair base `c5685b5f`; ship 3 plan
  rev 3.4.1 `4d6a3daf`; ship 3a as built, read-only (`feature/layer-ship3a` worktree `agent-aa1d30dcca08c1676`,
  HEAD `6d763d88` plus its uncommitted D2 work); live config `/Users/okosisi/ha-config/.storage/core.config_entries`
  (room names, types, adjacency and timeouts only).
- **Mandatory reads done first:** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and
  `docs/architecture/SENSOR_FLEET_CLASSES.md`, both read completely. Nothing below re-asserts a claim in the
  presence §10 corrections ledger. No contradiction between that doc and the code was found in the areas checked.
- **Framings:** completeness (prior findings re-verified against code), new-defect hunt in the fixes, G (goal
  fidelity).

## Verdict: FIX-PLAN

Three HIGH and four MEDIUM findings. All of them are plan edits; none needs new infrastructure. Two of the HIGHs
come from the H1 fix itself: the counted-return gate can never pass for `camera_egress`, and the BLE guard the plan
leans on does not hold the 15-minute bar on one path. The third is goal fidelity: the H2 near check, under the live
adjacency config, gives two of the four residents almost no welcome scenes. The §10.1 parallel set is unaffected
and can keep building. D2-D4 wait for these fixes and for ship 3a D2.

## Prior findings, re-verified

| Finding | Status | Evidence |
|---|---|---|
| H1 shapes | VERIFIED | `ResidencyEvent` on develop carries `counted`, `source_stale`, `in_boot_window` and also `resident_set_resolved` (`domain_coordinators/residency.py:39-51`). Ship 3a's in-progress D2 matches ship 3 §5 D2: `edges_since` (`edge_ts >= t`, oldest first, plain tuple), `edges_truncated_since` (full ring with a newer oldest record, or `t < created_ts`), `subscribe_person_edges` (sync `@callback` closure, filters on `record.person` and `record.kind`). Geofence ordering holds: `_feed_residency` is the first statement of `_handle_geofence_change` (`presence.py:5644`) and the F5 send follows in the same call (`:5681-5685`); both sides use epoch seconds (`_residency_clock = time.time`, `:1887`). For geofence the gate works. It fails for `camera_egress` (HIGH-1) and the BLE side rests on a wrong claim (HIGH-2). |
| H2 adjacency | MECHANISM VERIFIED, COVERAGE FAILS | `get_adjacent_rooms` (`presence.py:3463-3475`) reads a cache of `CONF_ADJACENT_ROOMS` (`:3403-3461`). Live config: see HIGH-3. |
| M1 cursor | VERIFIED, one gap | The BLE F5 is sent inside `_async_update_data` (`person_coordinator.py:1186-1193`) after the move site (`:1093-1125`) and before commit, so `t_f - update_interval` (30 s, `const.py:55`) covers the same-tick move. Gap: double check (LOW-1). |
| M2 truncation | VERIFIED | Ship 3 `location_moves_truncated_since` is True on a full log with a newer oldest record, or when `t` predates the log (reload). Rev 3.2 calls it each pass. |
| M3 entry time | VERIFIED for the area flip; residual breaks an invariant | `previous_location_time` is set to `now` only when the resolved room changes and the old location is not `unknown` / empty (`person_coordinator.py:1093-1097`), so a Bermuda area flip inside the room keeps it. The `unknown -> room` path does not refresh it (MEDIUM-1). |
| M5 counted outcomes | MOSTLY VERIFIED | `intent_opened` / `intent_duplicate_source` / toggle re-reads are in. The restart sweep covers music only (MEDIUM-4); gate order mislabels a second F5 (LOW-2). |
| M6 seams | VERIFIED, two wording errors | Raw connect at `c5685b5f` `domain_coordinators/music_following.py:296` (develop `:282`); its handler `_handle_person_arriving` only logs at DEBUG (`c5685b5f:565-592`), so deleting it loses no behaviour. BLE-ARRIVAL-PRODUCER-HVAC-GATED-1 and G6-ONE-BLE-ROOM-READ-1 are on the board (`kanban.data.yaml:35600`, `:35663`). The guard-row wording does not match ship 3a as built (LOW-3). |
| M7 departure wait | VERIFIED as designed; two new defects | Arm through `subscribe_person_edges` departures; STALE self-exclusion is right (STALE confidence halves per tick, `person_coordinator.py:1229`, and `get_room_occupants` needs at least 0.3, `:2360-2366`, so the BLE chain hold ends within a tick or two). Timeout collision (MEDIUM-2), flap arming (MEDIUM-3). |
| L1 `entry_missed` re-read | VERIFIED | Every path that decides music fills the slot, so `unrecorded` fires only when no pass ever ran the check while the person was in the room. That is a real engine fault, which is what the trip-wire is for. No false trip found. |

## Findings

### HIGH-1: the counted-return gate makes `camera_egress` unreachable

Step 7 sends `camera_egress` only for a GPS-led confirmation "whose raw `person.*` is still not `home` at confirm
time" (`PLANNING_egress_direction_aware_identity.md:598`). Its D2 egress branch also "skips raw `home`"
(`:591-594`). So when that F5 arrives, the person has no residency arrival edge yet: their `person.*` has not gone
home. Gate 4 (§5.4) needs a counted arrival record in `[t_f - 120 s, t_f]`, so every `camera_egress` F5 ends
`skipped_not_counted_return`. The arrival is still served later by the geofence F5, if one comes. But the
`camera_egress` source, which §5.4 gate 2, INV-V6-NO-FACE-ALONE, INV-V6-ARRIVAL-REACHES and §7 all count on, is dead
on arrival. That is a silent deferral. The two tests `::test_gps_confirmed_camera_egress_opens_intent` and
`::test_counted_return_required_for_geofence_and_camera_egress` cannot both pass against real step 7 semantics; a
fake that writes an arrival record before the egress F5 would hide this.

**Fix.** Do not ask an egress F5 for an arrival edge. Ask the departure side instead, with the same 15-minute bar
the residency rule uses: reject when `get_person_edges_since(t_f.timestamp() - RESIDENT_RETURN_MIN_AWAY_MIN * 60,
persons={p}, kinds={"departure"})` holds a departure of that person (they left less than 15 minutes ago). Fail
closed with `skipped_edges_truncated` when `person_edges_truncated_since` is True and nothing qualifies. The bar is
the existing `RESIDENT_RETURN_MIN_AWAY_MIN` (REUSED; read at `presence.py:5290`; no new knob). Step 7's GPS
prior-fix test stays the producer's guard. `ARRIVAL_COUNTED_EDGE_LOOKBACK_S` then applies to `geofence` only, where
the edge is written in the same call, so 120 s is ample. Update the knob row, the INV-V6-ARRIVAL-REACHES dual, D0 (a)
("by source") and the test names.

### HIGH-2: the BLE was-away guard is not "the same bar"

§5.4 gate 4 says the BLE producer sends F5 only after `_person_was_away`, "set after 15 minutes away". Only two of
the three setters hold that bar: the LOST branch (`person_coordinator.py:1216-1218`) and the BLE overrule
(`:810-812`). The S3 away arm, reached when Bermuda resolves no room past `decay_timeout` and `person.state` reads
`not_home` or a named zone (`:1343-1349`, twin `:1424-1428`), sets it on the first such tick with no time test
(`:802-804`; repair base `c5685b5f:766-768`). The plan's own cite (`:767-791`) covers that line.

**Legal repro.** Oji has music on and the master as his room. He walks the dog for 6 minutes. GPS goes `not_home`,
which writes a residency departure. Bermuda loses him for more than 300 s, so S3 sets `_person_was_away = True`. He
returns, Bermuda places him in the master, and the BLE F5 fires (pre-arrival on). The intent opens and music starts.
On the same return the geofence F5 is correctly rejected (counted False, 6 < 15 min). This breaks the H1 dual of
INV-V6-ARRIVAL-REACHES through `ble`.

**Fix.** Apply HIGH-1's departure-side rule to `ble` as well, in the engine, not in the producer. An S3 absence
always has a residency departure edge (S3 needs `person.state` away), so a short trip is caught. A BLE-overrule-only
absence (GPS stuck `home`) has no edge and keeps the overrule's own 15-minute guard, which the plan should say.
Correct the §5.4 sentence. Add test `::test_short_walk_ble_f5_opens_no_intent` and a mutation drill on the rule.

### HIGH-3 (framing G): under live adjacency the near check withholds most bedroom scenes

Live `adjacent_rooms` in `core.config_entries`:

| Room | Adjacency (configured) |
|---|---|
| Master Bedroom | Master Hallway, Master Bathroom |
| Master Bathroom | Master Bath Toilet, Master Bedroom |
| Jaya Bathroom | Jaya Bedroom |
| Jaya Bedroom | none (adjacent only through the reverse read of Jaya Bathroom) |
| Ziri Bedroom (Bedroom 5) | none |
| Guest Bedroom 1, Guest Bedroom 2 | none |
| every hall, staircase and other room | none |

The near check passes only when, at the bedroom's vacant-to-occupied edge, BLE already places the holder in the
bedroom or an adjacent room. The plan states (§5.5 item 3, presence §4.6) that BLE trails the body sensor by seconds
to tens of seconds, so at that edge the holder is usually still placed on the approach (Upstairs Hallway, Staircase)
or not yet re-placed after arriving (`away` / `unknown`). Under this config, Ziri's scene runs only when BLE beats
the radar into the room, which is the rare case, and Jaya's runs only when she comes in through her bathroom. Only
the master has its hallway mapped. The operator asked for a per-person welcome scene. As specified, it reaches about
one or two of the four residents.

The plan does send a large miss to the operator (§4 a2). But its remedy, "configure `CONF_ADJACENT_ROOMS` on the
room, which is config", is not free. Adjacency has three other readers, and adding a hall to a bedroom changes each:
- fan recheck L2: a trusted phone in an adjacent room vetoes the bedroom's fan probe
  (`presence_fan_recheck.py:1396-1409`);
- the presence fan-interference gate's adjacency read (`presence.py` around `:4774`);
- NM wall-panel targeting (`notification_manager.py:6325-6327`).

**Fix (plan edit, before the D3 wiring builds).**
1. Put the table above in §5.5 so the gap is stated now, not discovered at D0.
2. Have D0 (a2) report the near-pass share per bedroom under three rules:
   - adjacency as configured;
   - adjacency plus the approach hall;
   - same house zone, through the existing `PresenceCoordinator.get_room_zone` (`presence.py:3477`; membership only,
     the NM precedent, no side effects).
3. Add a §12 question with the side effects named: add adjacency (changes fan probes and panels), use house-zone
   membership for the scene only, or accept fewer scenes.

Default until answered: the zone rule. It reuses a getter and touches no other consumer. This is the third option
the plan's binary (configure adjacency or accept fewer scenes) leaves out.

### MEDIUM-1: the M3 residual breaks INV-V6-OCCUPIED

On the location re-read path the entry time is `get_person_previous_location_time`. For an `unknown -> room` change
that value is stale: it is refreshed only when the old location is not `unknown` (`person_coordinator.py:1095-1097`).
That move is also never logged: the bus fire and the move site sit inside that same condition (`:1095-1125`), so the
re-read is the only path. The entry time can then be hours old, and the onset leg ("onset earlier than entry minus
the lead") can never trip. Repro: a resident's `person.state` is `unavailable` while out (S5, `location = unknown`).
A guest with no phone has been in the resident's room for 30 minutes. The resident comes home, BLE places them in the
room, and music starts. §5.4 names this as a residual that makes the gate "less likely to trip". INV-V6-OCCUPIED is
stated without exceptions ("No knob disables this").

**Fix.** On the in-window paths (the listener's moves and the re-read, where the person was not in an own room at
open), use entry time = max(the value read, the cursor at open), so it is never earlier than `t_f - interval`. Keep
the open-time path as is: there the person really was in the room. Delete the residual sentence and add
`::test_unknown_to_room_mid_window_prior_occupant_blocks`.

### MEDIUM-2: the 600 s vacancy wait has thin margin over 500 s room timeouts

Live timeouts: Jaya Bedroom and Ziri Bedroom `occupancy_timeout` 500 s, each with an LD2410 plus a Zigbee radar;
Master, Guest Bedrooms and Media 300 s. Vacancy is roughly last body signal + timeout. The BLE STALE extension is
short (see M7 above). The LD2410 clears in 28 / 132 s (p50 / p90, SENSOR_FLEET_CLASSES), so Jaya's room goes vacant
about 2 + 8.3 ≈ 10.5 minutes after she walks out. A named-exit arm at the garage door lands 1-3 minutes after she
leaves the bedroom, leaving about 1-2 minutes of margin inside the wait; any slower radar clear ends
`departure_kept_occupied` with nobody home. D0 (b) measures "departure edge to next occupied-to-vacant edge" without
splitting by arming source, though the named exit arms minutes earlier than the geofence edge. Separately, Jaya's
LD2410 holds an empty room 68 % of the time with the fan on (presence §6). There `departure_kept_occupied` is the
honest outcome, and the plan should name it.

**Fix.** Define the wait relative to the room: wait = that room's `occupancy_timeout` + `ARRIVAL_DEPARTURE_VACANCY_WAIT_S`,
with the knob as the margin (rung 1; D0 b sizes it per arming source; 0 keeps rev 3.1's single check). Split D0 (b)
by arming source and by room. Add `::test_departure_named_exit_arm_room_timeout_500` and name the fan-phantom case
in §5.6.

### MEDIUM-3: a GPS flap arms a departure pause for a person who is home

Departure edges are not counted, and §5.6 has no exit for a return. Repro: Oji has music on in the master. GPS flaps
`home -> not_home -> home` (the flap class H1 exists for). That arms the wait. Within 10 minutes he walks downstairs,
the master goes vacant, nobody else is placed there, and his music is paused while he is home.

**Fix.** At every check, first read `get_person_edges_since(departure_ts, persons={p}, kinds={"arrival"})`. If it is
non-empty, end with the terminal outcome `departure_kept_returned`. Add the outcome to the §5.5 table and the test
`::test_flap_departure_then_return_does_not_pause`.

### MEDIUM-4: the restart sweep leaves the scene outcome silent

The setup sweep (§5.5 "Restart mid-window") reads only `arrival_music` episodes and writes `intent_lost_restart`
for music. INV-V6-COUNTED requires one terminal scene outcome too "across a restart". Repro: the person has
`auto_scene` on, the intent opens, and HA restarts before the room entry. Music gets `intent_lost_restart`; the
scene gets nothing.

**Fix.** Record whether the scene action was on in the `intent_opened` episode. Have the sweep also write
`scene_lost_restart` (a `welcome_scene` episode and log line) when there is no terminal scene outcome. Add it to the
table.

### LOW-1: a music check can run twice on one intent

At open, if `get_person_location` maps to an own room, the check runs. The first listener pass then reads moves
inclusively from `t_f - interval`, and §5.4 does not say "only while undecided" for the move path (it says so only
for the re-read). A geofence F5 whose move into the room landed under 30 s before `t_f` runs the check twice, and
the second run ends `skipped_gap` or `skipped_playing`, giving two outcomes. **Fix:** one sentence, "every path runs
the music check only while the intent's music slot is undecided", plus a test.

### LOW-2: gate order loses the second source

Gate 4 runs before gate 5, so a second F5 that fails gate 4 is counted `skipped_not_counted_return`, not
`intent_duplicate_source`, and M5's "second source recorded" is lost. After HIGH-1 this is mostly a late geofence
after a `camera_egress` open. **Fix:** check for an open intent before the counted-return gate.

### LOW-3: the guard-row wording does not match ship 3a as built

- The reserved listener is not a `ROWS` entry with a `reserved` field. It is a `LISTED` key
  (`person_awareness_layer_allowlist_PROVISIONAL.py:311`) plus an entry in `LISTED_RESERVED` (`:325`), filtered out
  by `test_person_awareness_layer_guard.py:46`. Un-reserving means renaming the `LISTED` key to the real symbol and
  removing the `LISTED_RESERVED` entry. "Set `reserved: False`" has no target.
- The raw connect row (`:306`) is also `LISTED`, and `LAYER_ALLOWLIST_TOTAL` sums `ROWS` only (`_layer_guard_engine.py`
  `compare`; the test asserts the total equals that sum), so retiring it does not lower the total.
- `get_adjacent_rooms` is not in `READ_LIST["PRESENCE"]` (`_layer_guard_engine.py:84-93`). A new row would raise a
  total that may only fall.

**Fix:** reword §10. Propose `get_adjacent_rooms` (and `get_room_zone` if HIGH-3 picks it) for the contract §4
read list, as membership reads with the NM precedent, instead of adding a row.

## Interactions asked about

- **Counted-return gate × BLE was-away guard:** they disagree on short trips. Geofence holds 15 minutes; BLE does not
  on the S3 path (HIGH-2). With both fixed by the one departure-side rule, the three sources share one bar. For a
  real return the order is fine: geofence opens, BLE is `intent_duplicate_source` (after LOW-2).
- **600 s wait × occupancy timeout:** they collide in the 500 s rooms (MEDIUM-2).
- **D2 un-reserve × ship 3a guard as built:** compatible in sequence. The real listener hit is "unlisted" until the
  same commit renames the `LISTED` key. That matches §10.1's rule that the listener registration and the row change
  land together after 3a merges. The wording is fixed by LOW-3.

## Framing G

| Operator ruling | Holds in rev 3.2? |
|---|---|
| Q1 Tier 2-DB | Yes (§11) |
| Q2 6.0.0 = step 8; Q4 v6.0.0 before F-NOTIFY | Yes (§10) |
| Q5 no action when anyone else is in the room | Yes for tracked persons; the onset leg has the MEDIUM-1 hole for untracked occupants |
| Q6 departure pause on | Delivered by design; MEDIUM-2 and MEDIUM-3 decide whether it pauses at the right times |
| Per-person welcome scene (card) | At risk: HIGH-3 |
| `camera_egress` as an arrival source (step 7 seam) | Silently dead: HIGH-1 |
| Temperature cut, form hiding, §12 defaults, profile pull-ins | Unchanged |

Nothing else is deferred silently. §14 ("nothing from the card is parked") is true only once HIGH-1 and HIGH-3
are fixed.

## Summary

| Severity | Count | Items |
|---|---|---|
| HIGH | 3 | camera_egress unreachable; BLE S3 guard has no 15-min bar; near check vs live adjacency (G) |
| MEDIUM | 4 | unknown-entry onset hole; wait vs 500 s timeout; flap-armed pause; scene restart outcome |
| LOW | 3 | double check; gate order; guard wording / read list |

D2-D4 may build once these are fixed in the plan and ship 3a D2 lands. A focused check of the edited paragraphs
(§5.4 gate 4, §5.5 near check and restart, §5.6, §9, §10) is enough; no full re-review is needed.
