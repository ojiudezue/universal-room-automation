# Music following repair (DRAFT, version set at deploy)

Card MUSIC-FOLLOWING-TRANSFER-REPAIR-1. Plan `docs/planning/PLANNING_music_following_repair.md`. Branch
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
area only; the distance check runs only under "strict" (the audit measured 11-38 % of transitions over 8 ft). A
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
the new room after (2), Remember the last playing room for (90), Ignore moves older than (15), Phone must be
within (8 ft, strict only), Location certainty (Normal), Seek ahead on cross-brand moves (3), Also play on the
room's other speakers (on). All apply without a reload. Rung 1: `MF_FADE_TARGET_VOLUME` 0.1,
`MF_NUDGE_SETTLE_S` 1, `MF_REVERSAL_WINDOW_S` 120, `MF_ZERO_TRANSFER_MIN_CANDIDATES` 3, `MF_EPISODE_LOG_PERSIST`,
`MF_MA_FIRST_ENABLED`, `MF_JOIN_LEADER_RELEASE_SAFE_PLATFORMS` (empty).

## Live acceptance (weekend walk, Sat/Sun)

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
