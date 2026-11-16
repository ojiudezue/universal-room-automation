# v5.108.26: music following repair

Shipping card: MUSIC-FOLLOWING-TRANSFER-REPAIR-1 (parent AUDIT-ROOM-AI-AUTOMATION-CHAINING-MUSIC-1; related TEST-MUSIC-SYSMODULES-LEAK-1, which stays open). Plan `docs/planning/PLANNING_music_following_repair.md`. Branch
`feature/music-following-repair`. Tier 2-DB (two new persisted episode shapes). Ships ON, no shadow stage.

## What changes for the house

Music now follows a person from a room with a playing speaker to a room with a speaker, however long they sat in
the first room. Before this, the gate rejected any walk after more than 60 s in a room (the "confidence" was dwell
arithmetic), and the two transfer calls that did run were malformed (join made the idle speaker the leader;
Music Assistant `transfer_queue` was called with keys it does not accept).

## Plan correction built in (operator brief 2026-11-14)

The plan gated on person BLE confidence / `closest_distance`; both are dead (constant 0.3 / 0.5; distance never
stored; per-scanner sensors gone since 10-20). The gate is re-based on LIVE inputs: the person's Bermuda area and
nearest-distance sensors resolved by registry, compared at decision time. Default certainty "normal" checks the
room only. The "strict" 8 ft distance check was dropped by the operator 2026-11-14 (a saved "strict" reads as
"normal"). A
dead or unresolved input never blocks a move; it is counted (`ble_input_missing`).

## D0 player inventory (read-only, `scripts/probes/mf_player_inventory.py`, live .storage 2026-11-14)

| Room | Primary | Platform | MA twin (match) | Bonus-eligible today |
|---|---|---|---|---|
| Garage B | `garage_b_3` | wiim | `garage_b_5` (MAC in MA id) | none (group_master entities are on the same device) |
| Guest Bedroom 1 | `guest_room_3` | wiim | `guest_room_5` (MAC) | none (TVs do not group) |
| Guest Bedroom 2 | `up_guest_room_3` | wiim | `up_guest_room_5` (MAC) | none |
| Kitchen | `kitchen_3` | wiim | `kitchen_5` (MAC) | none |
| Laundry | `utility_3` | wiim | `utility_5` (MAC) | none |
| Living Room | `living_room_2` | denonavr | none (HEOS id, not MAC) | none |
| Master Bathroom | `master_bathroom_3` | wiim | `master_bathroom_5` (MAC) | none |
| Master Bedroom | `master_bedroom_sonos_2` | music_assistant (Sonos) | itself | `move_2` (Sonos) only if it has an MA twin |
| Study A | `study_a_3` | wiim | `study_a_5` (MAC) | none |
| Study B | `study_b_3` | wiim | `study_b_5` (MAC) | none |

10 rooms have a primary; 9 are MA-covered; Living Room is play_media only (Denon AVR, no grouping); 37 rooms have
no player (`no_target_player`). The plan's discriminator held: MA mirrors sit on their OWN devices, so "same
device" finds none; the MAC carried in the MA identifier (`upc0f5352fc122`) is the join that works. MA devices have
no HA area, so wall tablets are not bonus-eligible by area today.

Not done in D0: (b) the recorder distribution of BLE confidence and hallway gap lengths and (c) per-day
player-to-player counts. (b) is moot (the confidence is a constant, measured by the BLE audit); the lookback
default stays 90 s unmeasured. (c) volume estimate stays the audit's ~75/day.

## Knobs (CM > Music Following)

Top: How music follows (Move / Play in both rooms), Not while the house sleeps, At night, Unusual-activity alerts.
Fine tuning: Stop the old room after (5 s), Wait before moving again (8), Ignore quick returns within (60), Check
the new room after (2), Remember the last playing room for (90), Ignore moves older than (15), Location
certainty (Normal), Seek ahead on cross-brand moves (3), Also play on the
room's other speakers (on). All apply without a reload. Rung 1: `MF_FADE_TARGET_VOLUME` 0.1,
`MF_NUDGE_SETTLE_S` 1, `MF_REVERSAL_WINDOW_S` 120, `MF_ZERO_TRANSFER_MIN_CANDIDATES` 3, `MF_EPISODE_LOG_PERSIST`,
`MF_MA_FIRST_ENABLED`, `MF_JOIN_LEADER_RELEASE_SAFE_PLATFORMS` (empty).

## Reviews

Tier 2-DB, three framing-disjoint reviews, then a review-C re-pass.

| Review | Framing | First verdict | Disposition |
|---|---|---|---|
| A (`docs/reviews/code-review/v_music_following_repair_A.md`) | local correctness | FIX-REQUIRED (A-H1 layer re-route, A-H2 extend on the MA path, A-M1, A-M2, A-L1, A-L2) | fixed in bf960874, 7f7b7f8d, c70b9316, c5685b5f |
| B (`v_music_following_repair_B.md`) | async, lifecycle, races | FIX-REQUIRED (B1-B3 MEDIUM; B4-B8 LOW) | all fixed in the same fix-up |
| C (`v_music_following_repair_C.md`) | per-site source mutation | FIX-REQUIRED (C-1 to C-14 GREEN sites) | 5a5d9d76 anchored every must-fix site; e31fe83a second pass anchored the lower-severity GREEN sites |

Post-merge (develop at v5.108.25 merged in 62df917e) every existing drill script re-ran with no unexpected result.
Remaining GREEN drills are recorded equivalent or redundant mutants (H3 alone / A7 alone, X10, X16, X18, Y10, Y25).
The merge lowered the person-awareness layer guard total 259 -> 256: the three music_following.py
person_coordinator.data reads now go through the public `get_person_location` API.

## Not delivered

- D0 (b) BLE confidence / hallway-gap distribution: moot, confidence is a constant; the 90 s lookback default is unmeasured.
- D0 (c) per-day player-to-player counts: uses the audit estimate (~75/day).
- Strict location certainty (8 ft distance gate): dropped by the operator 2026-11-14; a saved "strict" reads as "normal".
- Compactor fact for music episodes: parked per plan.
- TEST-MUSIC-SYSMODULES-LEAK-1: not closed; the three legacy test files keep module-level `sys.modules.setdefault` stubs.
- Native join in move mode stays disabled for unverified platforms until the live WiiM walk (`MF_JOIN_LEADER_RELEASE_SAFE_PLATFORMS` empty).
- D10 live walk: operator.

## Validated 2026-11-15 (restart 15:47 CST)

| Criterion | Result | Evidence |
|---|---|---|
| Installed and booted | PASS | manifest v5.108.26 (66 files) at 15:45:37; `update.universal_room_automation_update` installed_version v5.108.26 at 15:47:21 |
| No URA errors | PASS | `system_log` ERROR filter for universal_room_automation: 0 entries after restart |
| Health sensor carries the new outcome registry and knobs | PASS | `sensor.universal_room_automation_music_following_health` (the README below says `sensor.ura_music_following_health`; the real id is this one): `outcomes_today` has all 23 outcome keys, `counters_today` present, `knobs` (follow_mode move, lookback 90 s, cooldown 8 s, ping_pong 60 s, verify 2 s, position_offset 3 s) applied at 15:47:37 |
| Followers enabled | PASS | `switch.ura_music_following_enabled` on; per-person switches on for all four |
| Transfers | PENDING | house AWAY at restart; the walk below (D10) needs the operator |

## Live acceptance (prospective; walk with the operator)

- **Live:** music in Kitchen for 5+ minutes, walk to Study A: `MF decision ... outcome=success path=ma` in the log;
  `media_player.study_a_3` reads `playing` within the verify delay; Kitchen drops to 10 %, stops about 5 s after
  Study A plays, and reads its original `volume_level` afterwards.
- **Live:** Study A -> Study B (MA again): same.
- **Live:** Kitchen -> hallway (no speaker) -> Study A within 90 s: first leg `no_target_player`, second leg
  `success` with `source_room=Kitchen` in the decision.
- **Live:** into Master Bedroom: `master_bedroom_sonos_2` reads `playing` and is the leader; a bonus join appears
  only if the Move has an MA twin; nothing else joins.
- **Live:** bounce Kitchen <-> Study A four times within 30 s (ping-pong may suppress return legs at 60 s; set
  "Ignore quick returns" to 0 to test the in-flight rule): exactly one room plays at its own volume; the log shows
  `superseded` / `returned_in_flight`.
- **Live (WiiM-to-WiiM native check):** with "Play in both rooms", Garage B -> Laundry with MA off is not
  reachable from the UI; instead read `group_members` on both after an extend move: the source must be the leader.
  If releasing a WiiM leader keeps the follower playing, add `wiim` to `MF_JOIN_LEADER_RELEASE_SAFE_PLATFORMS`.
- **Sensor:** `sensor.ura_music_following_health` `outcomes_today.success` increments; `knobs` shows the form
  values; "Music Follow Accuracy" shows a percent after the first success.
- **DB:** one `music_follow_decision` row per leg (`memory_query` episodes, node `room:<slug>`).
- **Digest:** next morning carries "Music following, last 24 h: ...".
- **Discriminates:** a pass through the nudge shows `success_nudged`; a reversed leader shows the source in the
  target's `group_members` as a follower; a walk with nothing playing records `source_not_playing` (or
  `source_has_others` / `target_unavailable` when those apply first).

## Plan completion

| Item | Status |
|---|---|
| D0 inventory (a) | done (table above); (b),(c) deferred: (b) moot, (c) uses the audit estimate |
| D1 gate re-based on live BLE | done (deviation from plan text, per operator brief) |
| D2 lookback source | done |
| D3 paths, modes, bonus | done; native join in move mode disabled for unverified platforms (walk decides) |
| D3b bounce | done |
| D4 registry, verify, manual | done |
| D5 log, stats, accuracy, digest, trip-wire | done; nightly op named `run_music_following_health_check` (plan said `run_room_ai_health_check`, a shared name not yet built) |
| D6 episodes | done; compactor fact parked (plan) |
| D7 knobs, leak, hazard scope, preference hook | done; `music_on_arrival_start` KEPT (arc step 8 amendment M1) |
| D8 tests | done (`test_music_following_repair.py`, real HA + upstream schemas + real DB); TEST-MUSIC-SYSMODULES-LEAK-1 not closed: the three legacy files still use module-level `sys.modules.setdefault` stubs |
| D9 docs | done (`MUSIC_FOLLOWING.md` rewritten, presence state-of-play row) |
| D10 live walk | operator, weekend |
| Per-room "Music follows into this room" | was a dead knob; now read (target opt-out -> `no_target_player` reason `room_opted_out`) |
