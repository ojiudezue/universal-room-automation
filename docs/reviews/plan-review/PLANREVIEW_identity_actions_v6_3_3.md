# Plan re-check: identity actions v6, rev 3.3 (§5.4-§5.6, §9, §10, §12 Q4)

- **Plan:** `docs/planning/PLANNING_identity_actions_v6.md` on `plan/identity-actions-v6-rev3` @ `02b213db`
- **Prior re-check:** `PLANREVIEW_identity_actions_v6_3_2.md` (`67374ce8`); rev 3.3 fixes listed in plan §15.4
- **Code checked:** develop `d0a25cbc` (v5.108.23 live); ship 3a as built, read-only (`feature/layer-ship3a`,
  worktree `agent-aa1d30dcca08c1676`, HEAD `0b7d5061` "ship 3a phase 2 (D2 F1 edges ..., final guard allowlist)");
  live config `/Users/okosisi/ha-config/.storage/core.config_entries` (room names, types, areas, zone membership
  and adjacency counts only; no secrets read or printed).
- **Mandatory reads done first:** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and
  `docs/architecture/SENSOR_FLEET_CLASSES.md`, both read completely. Nothing below re-asserts a claim in the presence
  §10 corrections ledger. No contradiction between that doc and the code was found in the areas checked.
- **Framings:** completeness (each 3.2 finding against the text and code), new-defect hunt in the fixes (restart and
  truncation in particular), G (goal fidelity).

## Verdict: FIX-PLAN (small)

No HIGH. Two MEDIUM and five LOW, all plan text; none needs new infrastructure, and neither MEDIUM changes the §10.1
parallel set. Every 3.2 finding is fixed in the text and the cites hold against code. The two MEDIUMs: the
departure-side rule passes when there is no departure edge at all, which includes a resident who never left the
house; and the post-restart dead window is real (15 minutes for `ble` / `camera_egress`, 10 for `geofence`) but is not
stated, and it contradicts one break case in INV-V6-ARRIVAL-REACHES. Once those two are edited in, D2-D4 may build
after ship 3a merges. A paragraph-level check of the edits is enough.

## 1. The 3.2 findings, re-verified

| Finding | Status | Evidence |
|---|---|---|
| H1 `camera_egress` departure-side rule | FIXED | §5.4 gate 5 second bullet; `RESIDENT_RETURN_MIN_AWAY_MIN = 15` at `const.py:4109`, read at `presence.py:5290` (`min_away_s` of the tracker). Lookback knob narrowed to `geofence` (§9). Fake rule in §10.1. New residual: MEDIUM-1. |
| H2 BLE S3 guard | FIXED as specified | S3 setter `person_coordinator.py:802-804` (no time test), overrule `:810-812`, LOST `:1216-1218`: all as cited on develop. Same rule applied to `ble` in the engine. MEDIUM-1 shows the LOST setter is the case the text misses. |
| H3 near check | FIXED | Default = same house zone via `get_room_zone` (`presence.py:3477-3487`, reads `_room_to_zone`, rebuilt at zone discovery `:3667-3671`, first writer wins). Adjacency table in §5.5, three side-effect readers named, §12 Q4. Live zone table in §2 below. |
| M1 entry clamp | FIXED | §5.4 "Entry-time clamp"; INV-V6-OCCUPIED break case; the residual sentence is gone. The clamp only raises the entry time, so it can only make the onset leg trip more, never less. |
| M2 room-relative wait | FIXED | §5.6 Arm; §9 margin 300 s (800 s in the 500 s rooms). |
| M3 `departure_kept_returned` | FIXED | §5.6 step 0, subtypes `edge` / `truncated`; INV-V6-DEPARTURE-REACHES dual. |
| M4 `scene_lost_restart` | FIXED | `intent_opened` carries `music_on` / `scene_on`; sweep writes both; outcome table. |
| LOW-1 one check per intent | FIXED | §5.4 "One music check per intent". |
| LOW-2 gate order | FIXED | Duplicate is gate 4, counted return gate 5. |
| LOW-3 guard wording | FIXED, matches 3a as built | See §3 below. |

## 2. The planner's open items

### 2.1 Live house-zone membership

From `core.config_entries`, Zone Manager `options.zones` (the source `_discover_zones` prefers, `presence.py:3613`),
room names from each room entry's `data.room_name` (the key `_room_to_zone` uses, `:3627`):

| House zone | Rooms | Bedrooms in it | Halls / approach in it |
|---|---|---|---|
| Master Suite (11) | Master Bedroom, Master Bathroom, Master Bath Toilet, Oji Vanity, Master Closet, Master Closet Storage, Master Hallway, Study A, Study A Closet, Study B, AV Closet | Master Bedroom | Master Hallway |
| Upstairs (14) | Jaya Bedroom, Jaya Bathroom, Ziri Bedroom (Bedroom 5), Ziri Bathroom, Guest Bedroom 2, Guest Bedroom 2 Bathroom, Guest Bedroom 2 Hallway, Up Guestbedroom Closet, Game Room, Media, Media Room Closet, Exercise Room, Exercise Room Closet, Upstairs Hallway | Jaya, Ziri, Guest Bedroom 2 | Upstairs Hallway, Guest Bedroom 2 Hallway |
| Back Hallway (16) | Guest Bedroom 1 (+ Bathroom, Closet), Kitchen, Kitchen Hallway, Kitchen Hallway Garage, Garage Hallway, Staircase, Breakfast Nook, Dining Room, Kitchen Pantry, Butler Pantry, Laundry, Laundry Closet, Stair Closet, Powder | Guest Bedroom 1 | Staircase, Garage Hallway, Kitchen Hallways |
| Entertainment (3) | Living Room, Receiving Room, Foyer | none | Foyer |
| Outside (1) | Patio | none | none |
| (no zone) | Garage A, Garage B | none | none |

No room is in two zones. The person coordinator's location is the room name for a mapped area (`_area_id_to_room`,
`person_coordinator.py:1614-1616`), so names line up with `_room_to_zone`.

How the default rule behaves:
- **Master (Oji and Ezinne, co-owners).** The rule passes when the holder is placed anywhere in the master suite,
  Study A and Study B included. Wrong-recipient case: the holder arrives and sits in a study, and the co-owner, who is
  home and not yet re-placed by BLE, walks into the bedroom first and gets the holder's scene. The operator's "Shares
  spaces, likely same" covers this for a co-owner. An untracked guest entering the master is the same shape and is
  rare.
- **Jaya and Ziri.** Both bedrooms share the 14-room Upstairs zone with Guest Bedroom 2, the Game Room, Media and the
  Exercise Room. This is the zone where the cost is real. Repro: Jaya arrives (her intent is open), goes to the Game
  Room, and Ziri walks into Jaya's empty bedroom first; BLE has not placed Ziri there yet, so item 4 passes and Ziri
  gets Jaya's welcome scene. It needs the holder upstairs but not in her room inside her 900 s window, and someone
  else entering her empty room first. That is uncommon, the lights come on either way, and it is recorded as
  `scene_unconfirmed` unless Jaya walks in within 120 s.
- **The approach to the upstairs bedrooms is not in their zone.** The Staircase, Kitchen Hallway and Garage Hallway
  are in Back Hallway. If BLE still has Jaya or Ziri on the stairs when the bedroom lights up, the zone rule says
  `scene_skipped_not_near`. So the zone rule can still miss in the upstairs rooms, for the same reason adjacency
  did; D0 (a2) will show by how much (LOW-3).
- **Guest Bedroom 1 and Guest Bedroom 2.** Guests are not tracked and have no profile (non-goal), so these rooms get
  no welcome scene whatever the rule. Zone size matters only if a resident lists a guest room as their own; GB1's zone
  then includes the kitchen and every downstairs hall, which is close to "anywhere downstairs".
- **Garages** have no zone, so a holder placed in a garage reads `scene_skipped_not_near`, which is correct.

Answer to the question asked: yes, Master Suite (11) and Upstairs (14) are large enough that a person elsewhere in
them can receive the holder's scene. For the master it is the co-owner and the operator has accepted that shape. For
Upstairs it is a sibling or a guest, which §12 Q4 (a) states in general terms but without naming the zones (LOW-3).
I would keep the zone rule as the default: it is the only option that delivers scenes to Jaya and Ziri today, and the
miss it allows is visible as `scene_unconfirmed`.

### 2.2 Ship 3a guard entries, by name (worktree HEAD `0b7d5061`)

- `('R10', 'domain_coordinators/music_following.py', 'MusicFollowingCoordinator.async_setup:ura_person_arriving')`
  is a `LISTED` key (`person_awareness_layer_allowlist_PROVISIONAL.py:308`). Matches §10's first bullet.
- `('R10', 'music_following.py', '<step 8 §5.4 music listener>:async_add_listener[PC]')` is a `LISTED` key (`:313`)
  and the only `LISTED_RESERVED` entry (`:327`). Matches the second bullet. The two keys name different files on
  purpose (the coordinator vs the engine).
- `LAYER_ALLOWLIST_TOTAL = 259` (`:26`); the test asserts it equals the sum of `ROWS` max and `len(ROWS) == 231`
  (`test_person_awareness_layer_guard.py:62-63`); `_listed()` filters `LISTED_RESERVED` (`:45-46`). So neither
  `LISTED` change touches the total, as §10 says.
- `READ_LIST["PRESENCE"]` (`_layer_guard_engine.py:84-94`) holds `subscribe_person_edges`, `get_person_edges_since`,
  `person_edges_truncated_since` and `get_residency_snapshot`, and holds neither `get_room_zone` nor
  `get_adjacent_rooms`. Correct as stated. Who adds `get_room_zone` is still open (LOW-4).

### 2.3 Presence state of play cites

- §5.4 gate 5 "F5 is not a physical arrival (presence state of play §1)": holds (§1 table, `person.*` row:
  "`SIGNAL_PERSON_ARRIVING` is NOT a physical arrival").
- §2 row "the same listener the SC lock regime uses for Bermuda moves (§1, Review A fix-up, MED-1)": holds.
- §2 row and §5.5 "NM panel targeting precedent (§1)" for `get_room_zone`: holds (§1 table, room occupancy row).
- §5.6 fan phantom "(§6, ledger #1)": holds (§6 measured efficacy, §10 #1).
- §5.5 item 3 "BLE trails it by seconds to tens of seconds (presence state of play §4.6)": half-true. §4.6 says BLE
  extends occupancy and never creates it, which supports "the body sensor fires first". It gives no lag figure. LOW-5.

## 3. New findings

### MEDIUM-1: the departure-side rule treats "no departure edge" as "was away"

§5.4 gate 5 passes a `ble` or `camera_egress` F5 when `get_person_edges_since(t_f - 15 min, kinds={"departure"})` is
empty. Empty also means "never left". The text names one such case, the BLE overrule with GPS stuck `home`, and says
it keeps the overrule's own 15-minute guard. Two other paths reach an empty read with no real absence:

1. **BLE LOST at home.** The LOST branch sets `_person_was_away` after 15 minutes with no `person.state` test
   (`person_coordinator.py:1204-1218`: Bermuda sensor present, no room resolved, `TRACKING_STATUS_LOST`). Repro: Oji
   spends 20 minutes on the patio or in a garage where no scanner hears his phone. GPS stays `home`, so no departure
   edge is written. He comes back in, Bermuda places him, the BLE F5 fires (`:1163-1193`), gate 5 reads no departure
   and passes, and when he walks into the master his music starts. He never left the house. This is the BLE
   producer's pre-arrival behaviour since v3.18.6; the consumer's gate is meant to filter it and does not.
2. **A departure through `unknown`.** Residency writes a departure only for `old == "home"` and a real new value
   (`residency.py:127-128`). `home -> unknown -> not_home` writes none, so a 6-minute walk that goes through an
   `unknown` person state followed by an S3 BLE return passes too. Rarer; how often `person.*` goes through
   `unknown` is not measured.

This breaks the INV-V6-ARRIVAL-REACHES dual in spirit ("no started for an F5 whose person was away less than 15
minutes": the person was never away), and it is the case the operator's "when needed it's beautiful" argues against:
music on coming in from the garden is not needed.

**Fix (plan edit).** Require positive evidence of an absence for `ble` and `camera_egress`, read from what the layer
already exposes:
- pass when the person's most recent residency edge is a departure at least `RESIDENT_RETURN_MIN_AWAY_MIN` before
  `t_f` (`get_residency_snapshot()["persons"][slug]["left_at"]`, with `arrived_at` absent or older; this read is in
  `READ_LIST["PRESENCE"]` and is not limited by the 32-record ring), or when a counted, non-stale, out-of-boot arrival
  sits within `ARRIVAL_COUNTED_EDGE_LOOKBACK_S` (the geofence rule; in practice the duplicate gate catches this case
  first);
- otherwise `skipped_not_counted_return`, with a counter subtype `no_departure_seen`.

Cost, to state: an overrule-only absence (GPS stuck `home` while really away) no longer opens through `ble`. That
case needs a second GPS device or a frozen app, and the house runs one GPS tracker per person since 11-11 (presence
§1, suspicious-arrival hold: "fires 0 times" today). Its geofence F5 still opens the intent when GPS catches up.
D0 (a) should split BLE F5s by "raw `person.*` read `home` for the whole prior 15 minutes", which measures case 1
directly and decides whether the cost is worth naming further. Replace `::test_ble_overrule_only_absence_no_edge_opens_intent`
with `::test_ble_lost_at_home_no_departure_opens_no_intent` and `::test_departure_via_unknown_opens_no_intent`, plus
a mutation drill: "pass on an empty departure read".

### MEDIUM-2: the post-restart dead window is real but not stated, and one break case contradicts it

Ship 3a as built: `edges_truncated_since` is True when `t < tracker.created_ts` (`residency.py:320-326`), and
`created_ts` is the presence setup time (`presence.py:5298` in the worktree, `setup_ts=self._residency_clock()`; RAM, empty at start).
`location_moves_truncated_since` has the same rule against `_moves_created_at` (`person_coordinator.py:2313-2321`).
Consequences, worked through:

- **Arrival, `ble` / `camera_egress`.** The read starts at `t_f - 900 s`. For every F5 in the first 15 minutes after
  a restart (or a presence reload) that read is truncated, and an empty read fails closed: `skipped_edges_truncated`.
  No intent, no music, no scene. After 15 minutes the read starts after `created_ts` and is not truncated.
- **Arrival, `geofence`.** Truncation covers only the first 120 s, but every arrival edge in the first 600 s carries
  `in_boot_window = True` and fails `counted` anyway (`residency.py:132`). So geofence is dead for 10 minutes.
- **Move log.** Truncated only when `t_f - 30 s` predates the person coordinator's creation, i.e. an F5 in the first
  30 s. It only marks `moves_truncated`; the location re-read still decides. Not a kill.
- **Departure pause.** Not killed after a restart. The stamp is RAM and lost at restart
  (`departure_stamp_lost_restart`), so any armed wait belongs to music started after the restart, and its
  `departure_ts` is after `created_ts`. `departure_kept_returned` subtype `truncated` can occur only if presence's
  tracker is rebuilt while a wait runs (a presence reload without a music-engine reload), or if 32 residency records
  land inside one wait (a flap storm). Both fail toward music left playing, which is the safe direction.

So music and scene are dead for 15 minutes (`ble` / `camera_egress`) and 10 minutes (`geofence`) after every restart
and every presence reload. Pauses are not. That is acceptable: one 15-minute window per restart, at most about 1 % of
arrivals at today's restart rate, and it fails closed. But the plan does not say it. §5.4 says only that an empty
truncated log cannot prove the bar. INV-V6-ARRIVAL-REACHES lists "came from `unknown` after a restart" as a case that
must reach `started`, which is false for any F5 inside the window. And `skipped_edges_truncated` is a counter with no
decision line, so a resident whose music did not start after a deploy has nothing to look at.

**Fix (plan edit).** (1) State the window and its bound in §5.4 and §5.5 "Restart mid-window": after a restart or
presence reload no intent opens for `RESIDENT_RETURN_MIN_AWAY_MIN` (ble / camera_egress) and
`RESIDENT_RETURN_BOOT_WINDOW_S` (geofence; `const.py:4110`, 600 s), and pauses are unaffected. (2) Qualify the
INV-V6-ARRIVAL-REACHES break case: "from `unknown` after a restart, for an F5 at least 15 minutes after setup". (3)
Give `skipped_edges_truncated` a `boot` subtype (truncated because `t` predates the tracker) and count it in the NM
digest, so the window is visible without a log line per F5. Test `::test_ble_f5_within_15min_of_setup_fails_closed`
and `::test_departure_pause_after_restart_not_blocked_by_truncation`. If MEDIUM-1's snapshot rule is adopted, the same
statement applies: an empty snapshot after setup is "no departure seen", not "away".

### LOW-1: named-exit `departure_ts` type

§5.6 says the wait's departure time is "the arming edge's `ts`". For a residency edge that is epoch seconds; for a
named exit it is a `CrossingRecord` time (`get_crossings_since` takes a `datetime`, `presence.py:6092` in the
worktree). Step 0 passes it to `get_person_edges_since`, which wants a float. Say `.timestamp()` for the named exit,
the same care §5.4 takes with the cursor's type. Test `::test_named_exit_arm_return_check_uses_epoch`.

### LOW-2: room name for the zone lookup

`arrival_scene_for` receives a room entry_id and must call `get_room_zone` with a name. `_room_to_zone` keys on
`entry.data[room_name]` (`presence.py:3627`), not the title or options. Say which name the engine uses. A room
renamed through options keeps its old name in the zone map (presence §9, ZONE-ROOM-NAME-DRIFT-1), so the lookup
returns None and the scene reads `scene_skipped_not_near`: the safe direction, but name it.

### LOW-3: D0 (a2) and §12 Q4 should show the live zones

Put the §2.1 table (or its bedroom rows) next to the adjacency table in §5.5, and name the cost in §12 Q4 (a) by zone:
co-owner in the Master Suite (accepted shape), sibling or guest in Upstairs. Have D0 (a2) also report the holder's
placed room at the bedroom's onset, so the operator can see whether misses come from the Staircase (Back Hallway),
which no zone rule can pass for an upstairs bedroom.

### LOW-4: owner of the `get_room_zone` read-list entry

§10 says the read-list addition is made "by whoever owns the contract (ship 3a or its follow-up)". Ship 3a phase 2
has landed its final allowlist without it (`_layer_guard_engine.py:84-94` at `0b7d5061`). `READ_LIST` lives in
`_layer_guard_engine.py`, not in the PROVISIONAL allowlist file that §10.1 forbids step 8 to edit. Name the owner:
step 8's D2 commit adds `get_room_zone` to `READ_LIST["PRESENCE"]` and the contract §4 read list together, as a
membership read with the NM precedent; or ship 3a adds it before merge. Otherwise the D2 wiring stops on an
unexplained hit, as §10 already warns.

### LOW-5: the §4.6 cite

§5.5 item 3 cites presence §4.6 for "BLE trails the body sensor by seconds to tens of seconds". §4.6 supports only
"BLE extends occupancy and never creates it". Cite it for that, and leave the lag figure to D0 (a2), which measures
it.

## 4. Framing G

| Operator ruling (kanban `PERSON-PROFILE-PREFERENCES-1`, `operator_2026_11_14_step8`) | Holds in rev 3.3? |
|---|---|
| Q1 Tier 2-DB | Yes (§11) |
| Q2 6.0.0 = step 8; Q4 v6.0.0 before F-NOTIFY | Yes (§10) |
| "Don't want to defer too much" | Yes: `camera_egress` reaches actions again, scenes reach Jaya and Ziri under the zone default, §14 parks nothing. MEDIUM-1's fix drops only the rare overrule-only `ble` path, and geofence still serves it |
| "Don't do it when someone is already in that room, including your own room" (Q5) | Music: yes, now including an untracked occupant on the re-read path (M1). Scene: held only as precisely as the near rule. §15.4 says "Every confirmed operator ruling holds ... Q5"; for the scene that is the zone rule's stated cost. §12 Q4 (a) should say it trades against Q5 so the operator answers both at once (folded into LOW-3) |
| "Shares spaces, likely same" | Supports the zone default in the Master Suite; the co-owner-gets-the-scene case is the shape the operator accepted |
| "When needed it's beautiful" | The arrival actions must be right when they fire. The post-restart window (MEDIUM-2) fails toward no action, which fits. MEDIUM-1's patio and garage case fires when not needed and should be closed |
| Q6 departure pause on | Yes; the wait is room-relative, a flap cannot pause, and restart does not kill pauses (MEDIUM-2 analysis) |

Nothing is deferred silently.

## 5. Summary

| Severity | Count | Items |
|---|---|---|
| HIGH | 0 | |
| MEDIUM | 2 | empty departure read passes a resident who never left (BLE LOST at home, departure through `unknown`); post-restart dead window unstated and contradicting an INV break case |
| LOW | 5 | named-exit ts type; room name for the zone lookup; live zone table and Q4/Q5 wording plus D0 onset room; owner of the read-list entry; §4.6 cite |

Verdict: FIX-PLAN. Fix MEDIUM-1 and MEDIUM-2 in §5.4, §5.5, §6, §9 and D0 (a), and fold in the LOWs. A
paragraph-level check of those edits is enough; then D2-D4 may build once ship 3a merges.
