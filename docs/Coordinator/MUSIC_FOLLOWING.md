# Music Following — Design Doc

Rewritten 2026-11-14 for MUSIC-FOLLOWING-TRANSFER-REPAIR-1 (`docs/planning/PLANNING_music_following_repair.md`).
Code wins: `music_following.py` (engine), `domain_coordinators/music_following.py` (coordinator wrapper).

## What it does

When a person walks from a room with music to a room with a speaker, the music moves with them. It ships ON.
Comfort-class consumer of the person's dense-BLE room (F4-shaped; identity model F1-F5, no identity fact
produced). Cameras are not an input.

## Input

`person_coordinator` fires `ura_person_location_change` only from its Bermuda branch. Additive keys since this
cycle: `method` (`"bermuda"`), `bermuda_area` (the area state that produced the change), `area_sensor`.
`TransitionDetector` copies them onto `RoomTransition.ble_area / ble_area_sensor / ble_method`. The transition's
`confidence`, `path_type` and `duration_seconds` are dwell arithmetic: logged, never gated.

## Gates (fixed order; each skip is an outcome)

1. `coordinator_disabled` (CM switch), 2. `person_not_enabled`, 3. `same_room` — in `_on_person_transition`.
Then, inside the per-transfer task under the house lock:
4. BLE certainty `ble_low_confidence` (below), 5. `stale_transition`, 6. `sleep_suppressed` /
`night_suppressed`, 7. `cooldown_blocked`, 8. `returned_in_flight` (bounce back to the room a superseded move
came from, music already there), 9. source: `no_source_player` / `source_not_playing`, 10. `no_target_player`
(incl. reason `room_opted_out` when the room's "Music follows into this room" is off), 11. `target_unavailable`,
12. `source_has_others`, 13. `active_playback_blocked`.

Ping-pong suppression runs before MF in `TransitionDetector` (`ping_pong_suppressed`, booked via
`record_ping_pong_suppressed`). Time spent in a room is never a skip reason (INV-MF-3).

### BLE certainty on live inputs (re-based 2026-11-14)

The person BLE confidence is a constant and `closest_distance` is never stored
(`AUDIT_ble_person_sensor_resolution_2026_11_14.md`). MF does NOT read Bermuda sensors, person entities or the
layer's `data` store (review A-H1, INV-LAYER-READ). It reads only the person-awareness layer's public methods on
`hass.data[DOMAIN]["person_coordinator"]` (`_person_layer`, music_following.py:1016):
`get_person_location` via `_layer_location` (music_following.py:1028; "unknown"/"unavailable" = no location), and
`tracked_persons` for the source-room-others check (`_source_has_other_occupants`, music_following.py:1807: another
tracked person whose layer room is `from_room` suppresses as `source_has_others`; secondary = substrate `occupancy`
kind). `CONF_MF_MIN_BLE_CONFIDENCE` buckets (`_ble_gate`, music_following.py:1041): `any` (no check), `normal`
(default: the layer's room for the person is still the target room at decision time). The `strict`
distance gate (8 ft, `CONF_MF_HIGH_CONFIDENCE_DISTANCE`, outcome `ble_too_far`) was DROPPED by the operator
2026-11-14; a saved `strict` reads as `normal`. Parked until wrong-room moves are measured and a distance input
exists (BERMUDA-DISTANCE-SENSORS-DEAD-1 option A). A missing / dead / unresolved input
fails OPEN and increments `ble_input_missing`. Per-person Bermuda sensor resolution belongs to the layer
(`BLE-PERSON-SENSOR-REGISTRY-RESOLVE-1`), not to MF.

## Source

The room the person left if its speaker plays; else the last room they left with a playing speaker within
`CONF_MF_SOURCE_LOOKBACK_SECONDS` (default 90, 0 = off) whose speaker still plays (hallway walk-through).

## Paths (one resolver, reason logged)

1. **Music Assistant** when both speakers resolve MA players and the MA source player reads `playing`:
   `music_assistant.transfer_queue`, target = destination MA player, data `source_player`, `auto_play: true`.
   MA twin resolution: the entity itself is MA; an MA entity on the same device; an MA device whose
   `music_assistant` identifier names an HA entity on this device; an MA device whose identifier carries this
   device's MAC (live 2026-11-14: 9 of 10 room speakers are covered this way, e.g. `kitchen_3` -> `kitchen_5`).
   Kill switch `MF_MA_FIRST_ENABLED`.
2. **Native join** when both share a grouping platform: `media_player.join(entity_id=<leader>,
   group_members=[target])`; leader = the source, or the leader of an MF-formed group (chained move), or the
   source's `group_members[0]`. In `move` mode a join whose leader is the source is skipped unless the platform is
   in `MF_JOIN_LEADER_RELEASE_SAFE_PLATFORMS` (empty until the walk proves releasing a leader does not stop the
   followers).
3. **Generic** `play_media` of the source content + seek `position + CONF_MF_POSITION_OFFSET`.

## Verify, follow mode, release

Success only when the room's configured speaker (`room_media_player`, the primary) reads `playing` after
`CONF_MF_VERIFY_DELAY`. Generic path only: if the target loaded MF's content but is not playing, one
`media_play` nudge -> `success_nudged`. Otherwise `verify_failed`, fade undone, source untouched.

`CONF_MF_FOLLOW_MODE` `move` (default): after MF's call the source fades to `MF_FADE_TARGET_VOLUME` (10 %); on
success, after `CONF_MF_RELEASE_DELAY` the source is removed (generic: `media_stop`; join: `unjoin`; MA: MA
already stopped the queue) and its saved volume restored. `extend`: never fades or removes.

## Bonus speakers (INV-MF-6)

After success, other enabled media players in the target room's HA area that group on the same path (MA twins
for an MA move; same platform for native) join the primary, best effort (`bonus_join_failed` counter). Never on
the primary's own device, never a non-grouping player (TVs). `CONF_MF_BONUS_JOINS` (default on). Released on the
next move out of that room. Live 2026-11-14: Master Bedroom's Sonos Move qualifies only if it has an MA twin.

## Fast bounce (INV-MF-5)

One transfer in flight per person. A newer room change cancels it; the cancelled transfer's cleanup restores
every volume it took and takes back MF's start of the target, or, if the target was already confirmed and the
person did not walk back, completes the release. The cancelled one books `superseded`; a walk back to its source
books `returned_in_flight`. A transfer cancelled before its first step still books `superseded`.

## Outcomes and observability

`MF_OUTCOMES` is the single registry (stats, skip set, `outcomes_today`); counters `bonus_join_failed`,
`ble_input_missing`, `unknown_outcome`. One INFO line per room change: `MF decision person=... outcome=...`.
`sensor.ura_music_following_health` attributes: `outcomes_today`, `counters_today`, `last_decision`, `knobs`,
`knobs_applied_at`, `accuracy_pct`. All MF service calls carry the URA write context.

Accuracy: after a success, for `MF_REVERSAL_WINDOW_S` (120 s) a non-URA pause/stop of the target, or a non-URA
resume of the source, is a reversal. Sensor "Music Follow Accuracy" (percent not reversed; 7-day nightly roll-up
from room memory, else since start).

Room memory: `music_follow_decision` (one row per room change with both speakers, node `room:<target slug>`,
`window_dedup=False`, `dedup_source_ref=True`; writer-backed, absence-exempt) and `music_follow_reversal`.
Kill switch `MF_EPISODE_LOG_PERSIST`.

Digest: one line in the NM morning/evening digest (empty with no candidates). Nightly op
`run_music_following_health_check`: HIGH stuck-signal `music_follow_silent` when the trailing 24 h had at least
`MF_ZERO_TRANSFER_MIN_CANDIDATES` (3) room changes with music playing and a speaker ahead and zero successes
(in-memory window: a restart shortens it, so it can only under-fire).

## Knobs

All rung-2 knobs live in the CM "Music Following" form (two choices on top, the rest under "Fine tuning") and
apply in place through `MusicFollowing.apply_config` (`_MF_LIVE_KEYS`; no CM reload). The ping-pong window is
pushed to `TransitionDetector.set_ping_pong_window` (0 = off). `CONF_MF_MIN_CONFIDENCE` is retired (key
ignored). `music_on_arrival_start` is KEPT as the house-level arrival-music master switch for arc step 8
(handler a no-op today; reload-suppressed).

## Other surfaces

Hazard / security stop: only the configured room and zone players (`configured_players()`), not every
media_player in the house. `set_preference_provider(callable)`: `provider(person_key, ctx) -> {follow_mode,
target_volume}` or None (default None = unchanged behaviour); arrival music and PERSON-PROFILE-PREFERENCES-1 build
on it. Diagnostic listeners return an unsubscribe; the coordinator and the five sensors remove theirs.

Arc step 8 seam (branch `feature/step8-identity-actions`, NOT deployed): `arrival_scene_for(room_entry_id)`
is the decision call the room entry path (`automation._maybe_activate_slot_scene`, day / evening caller)
makes before the slot scene, and `note_arrival_scene_result(room_entry_id, applied)` is its report back.
Both are stubs (None / no-op) until D3. Person profiles live in the CM option `person_profiles`
(`person_profiles.py`: `get_person_profile`, `pick_media`, `arrival_master_on`, default ON).
