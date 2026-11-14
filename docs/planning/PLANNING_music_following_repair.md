# PLANNING: music following repair

Card: MUSIC-FOLLOWING-TRANSFER-REPAIR-1. Parent: AUDIT-ROOM-AI-AUTOMATION-CHAINING-MUSIC-1.
Related: AI-ROOM-RULES-TRUST-REPAIR-1 (shares the observability pattern), PERSON-PROFILE-PREFERENCES-1,
TEST-MUSIC-SYSMODULES-LEAK-1. Plan review: `docs/reviews/plan-review/PLANREVIEW_music_following_repair.md`.

## 0. Charter (operator 2026-11-13, verbatim)

- "No shadow mode... Treat the reformulations as full blown mission critical feature that must work on day 1. My
  trust just means get it right and make sure it's tested well. No delays. This is where our features die and are not
  switched on."
- "music following is key to personalization." "we already know the rooms everyone we know is in via dense ble.
  Again this is solved."
- "The thing to build into the 3 feature, now 2 is observability and logs that allow diagnostics and tuning. Maybe
  room memory entries as well to extend the memory feature."

- Operator answers 2026-11-13: (1) the old room follows the original design: fade the source to 10 percent,
  confirm the target plays, then remove the source after a short delay and restore its volume (named knob, confirmed
  on the weekend walk). (2) "We should check to see if every player is on MA. Then consolidate on MA. With backup of
  the native interfaces which are likely Wiim/linkplay, denon, Sonos and Apple?"

What that means here: the feature stays ON. Music Assistant is the primary path for every player it covers; native
paths are the fallback. When a person walks from a room with music to a room with a speaker, the
music moves, whatever time they spent in the first room. Every decision is visible in logs, stats, room memory and
the morning digest, so a miss can be diagnosed and tuned without reading code.

## 1. Institutional context verified

Read completely: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 ledger; no ledger claim is re-asserted) and
`SENSOR_FLEET_CLASSES.md`. HVAC code is not touched. Also read: both plan reviews, the board card (every
`operator_*` field, `amendment_pending`, `live_walk`), `ARCHITECTURE_hierarchical_memory.md` §4, §8, §10,
`AUDIT_room_memory_and_coordinator_request_apis_2026_10_21.md`, memories `feedback_label_style_guide.md`,
`feedback_configurability_clarity.md`, F1-F5, fire check, hollow test anchors. Code re-read on develop 3e17310a (no
code change since the review base 434a7aae).

| Piece | Verdict | Where |
|---|---|---|
| Person room input | REUSE | `person_coordinator.py:1059-1068` fires `ura_person_location_change`; `transitions.py:157` builds `RoomTransition`; MF subscribes `music_following.py:211` |
| BLE confidence | REUSE, carried in event | computed `person_coordinator.py:1045` (`_calculate_confidence` `:1821`, 0.5 when no distance data); added as `ble_confidence` to the event payload at `:1059` (additive key) |
| BLE distance gate | REUSE | `music_following.py:533-546`, knob `CONF_MF_HIGH_CONFIDENCE_DISTANCE` |
| Dwell-time "confidence" | STOP GATING ON IT | `transitions.py:288-381`: `duration` = time since entering `from_room`, >60 s gives 0.50; gate `music_following.py:521` |
| Person key | REUSE | `_person_key` `music_following.py:44` |
| Platform dispatch, MA, join, generic | FIX | `_transfer_media` `:1359`, MA `:1537/:1553`, join `:1485/:1505`, generic `:1609-1640` |
| Verify, cleanup | FIX | `_verify_transfer` `:958` (nudge `:984`), `_schedule_group_cleanup` `:1007` |
| Manual transfer | FIX (route through verify) | `manual_transfer` `:1659-1691` |
| Outcome stats | FIX (one registry) | `_transfer_stats` `:168-183`, `_SKIP_OUTCOMES` `:356`, `_record_stat` `:370` (drops unknown keys `:381`), `_TRANSFER_KEYS` `:411`, `get_diagnostic_data` `:413` |
| Anomaly feed | REUSE | `_on_transfer_outcome` `domain_coordinators/music_following.py:306` |
| Live knobs | FIX | `update_gate_config` `:311`; CM in-place allowlist `__init__.py:7643-7645`, apply block `:8393`, seed `:3875-3905`; monkey-assign `dc:145-146` |
| URA context stamp | REUSE | `ura_context.ura_ctx_kwargs` `ura_context.py:80`, `is_ura_context` `:87`; MF stamps nothing today |
| Memory writer | REUSE | `database.log_memory_episode` `database.py:10686`, `MEMORY_EPISODE_TYPES` `const.py:6092`, `MEMORY_WRITER_BACKED_EPISODE_TYPES` `:6147`, `MEMORY_WRITER_HEALTH_ABSENCE_EXEMPT_TYPES` `:6200`; read via `memory_query` (`__init__.py:6439`) |
| Digest | REUSE | `NotificationManager._fire_digest` `notification_manager.py:5620`, section pattern `_build_optimizer_digest_section` `:5788`, called `:5640` |
| Zero-fire page | REUSE | `fire_stuck_signal` `domain_coordinators/_stuck_signal_nm.py:165` |
| Nightly hook | REUSE | `nightly_maintenance.py` op list (`memory_writer_health` row) |
| Collapsed form section | REUSE | `_advanced_section` `config_flow.py:53` |
| Health sensors | REUSE | `MusicFollowingHealthSensor` `sensor.py:8129` (+ 3 more at `8359, 8430, 8510`) |
| Source lookback, outcome registry, accuracy sensor, follow-mode knob | NEW | grep `lookback`, `follow_mode`, `accuracy` in `music_following.py`, `const.py`, `config_flow.py`, `sensor.py` = 0 |

MA schema verified upstream (review table): `music_assistant.transfer_queue` targets the destination `media_player`;
data `source_player`, `auto_play`. `media_player.join`: `entity_id` is the leader, `group_members` follow.

Config-first: no setting fixes the dwell gate, the payloads or the leak. Lowering `mf_min_confidence` to 0.5 would
pass long dwells, but it gates on the wrong quantity and still blocks nothing useful; code is needed.

## 2. Identity model and consumer class

MF consumes F4-shaped per-person room location from dense BLE (PersonCoordinator), plus F1 (tracked persons). It reads
no F2, F3 or F5 and produces no identity fact. Consumer class: comfort. Policy (BLE thresholds, sleep, night) lives
in MF. Cameras are not an input.

## 3. Falsifiable invariants

- **INV-MF-1 (no silent loss).** No MF-issued call stops, pauses or ungroups a source player unless MF has read the
  target as `playing` after its own transfer call; a fade issued before verify is always undone (saved volume
  restored) when the target does not play, and every saved volume is restored after a release. MA path: MA stops the source queue itself when it
  moves it; MF only takes that path when the MA source entity reads `playing`, so the queue that moves is the music
  the person hears. Break it with any path where the source goes quiet while the target is not playing.
- **INV-MF-2 (one outcome each).** Every transition `_on_person_transition` receives ends in exactly one outcome
  from `MF_OUTCOMES`, counted in stats, written to the log, and (when a player is involved) to room memory. This
  includes coordinator off, person not enabled and exceptions.
- **INV-MF-3 (dwell never blocks).** A person who spent any time in a room with music playing and then walks to a
  room with a speaker, directly or through one room without a speaker within the lookback, gets a transfer attempt.
  Time spent in the first room is never a skip reason.
- **INV-MF-4 (knobs are live).** Every knob in §7 changes behaviour on options save without a reload or restart.

## 4. Producer and consumer checks

**Producer: person room (BLE).** Healthy: 8,126 `room_transitions` in 14 days (audit). Its `ble_confidence` and
`closest_distance` are BLE facts; the transition `confidence` is dwell arithmetic (G-1) and is logged, never gated.
**Producer: transfer outcome.** Fire check: last observed success 2026-10-11, `transfers_today 0`, `low_confidence 21`
on audit day, which matches the dwell gate rejecting real moves. Skips and successes were not separable; D4 fixes it.
**Consumers:** stats feed four sensors (display) and the anomaly baseline (observability). New consumers: digest,
nightly trip-wire, room memory, PERSON-PROFILE-PREFERENCES-1 later (reads episodes, display/suggestion only).
**Forward trace:** location event -> `TransitionDetector` -> `_on_person_transition` (gates) -> source resolution ->
`_execute_transfer` -> path call -> verify -> source release -> outcome record -> stats, log, episode -> digest and
trip-wire. Every link is a deliverable below.

## 5. Emission and decision sites

Service calls in `music_following.py`: `:945` volume restore, `:984` verify nudge, `:1018` cleanup unjoin, `:1467`
source fade/stop, `:1505/:1517` join + volume, `:1553/:1565` MA transfer + volume, `:1609/:1621/:1640` generic
play/volume/seek, and `domain_coordinators/music_following.py:666` hazard stop. Callers of `_transfer_media`:
`_execute_transfer` `:726` and `manual_transfer` `:1689`. `_record_stat` call sites: every `self._record_stat(` in
the file plus the silent returns at `:485, :511, :814-826, :861-873`. Outcome readers: `:381, :411, :413-447`,
`dc:306`, sensors `8129/8359/8430/8510`. Builder re-greps each list and pastes the result in the README.

## 6. Deliverables

### D0: read-only probe and player inventory (first; no HA writes)
(a) Inventory every room's configured `room_media_player` (and zone players). For each: native platform from the
entity registry `platform` field (`wiim`/`linkplay`, `denonavr`/`heos`, `sonos`, `apple_tv`/airplay, other); whether a
`music_assistant` platform entity exists for the same physical device, joined by device registry (same `device_id`,
or MA device `connections`/`identifiers` matching the native device's MAC or serial; record which join matched);
`supported_features` bits for `GROUPING` and `PLAY_MEDIA` on both entities. MA provider support to confirm per
device (provider list https://www.music-assistant.io/player-support/ ; WiiM/LinkPlay
https://www.music-assistant.io/player-support/wiim/ ; HEOS (Denon) https://www.music-assistant.io/player-support/heos/ ;
Sonos https://www.music-assistant.io/player-support/sonos/ ; AirPlay https://www.music-assistant.io/player-support/airplay/ ).
Apple TV has no provider page of its own; MA reaches it, if at all, through AirPlay (UNVERIFIED until D0). Grouping
support per provider is not stated on that page; D0 reads the MA entity's `supported_features`. Output: a table of
every player with MA coverage yes/no and, for each "no", what it would take (enable the MA provider, re-add the
player in MA, or native-only). (b) From the recorder, for 7 days of room changes, the
`ble_confidence` distribution and how often a walk passes through a player-less room between two player rooms, with
the gap length. (c) Count transitions per day where both rooms resolve a player (sizes episode volume).
- **Verify:** the README carries the three tables. (b) sets the defaults of `CONF_MF_MIN_BLE_CONFIDENCE` and
  `CONF_MF_SOURCE_LOOKBACK_SECONDS`: chosen so at least 95 percent of real moves pass. If the measured gap p95 is
  above 180 s, the plan's default changes before build.
- **Discriminates:** if MA mirrors sit on their own devices, "same device" resolution finds none; the table shows it.

### D1: replace the dwell gate with BLE gates (fixes G-1)
Delete the `transition.confidence < MIN_CONFIDENCE` gate. The transition's `confidence`, `path_type` and
`duration_seconds` are logged as inputs only. Gates on BLE facts: `ble_confidence` from the event payload against
`CONF_MF_MIN_BLE_CONFIDENCE` (outcome `ble_low_confidence`), and the existing distance gate (outcome `ble_too_far`,
no longer booked as `low_confidence`). The producer change is one additive key pair in the event at
`person_coordinator.py:1059` (`ble_confidence`, `closest_distance`), captured at fire time so MF never reads a
mid-update `person_coord.data`. `transitions.py` ignores extra keys; no other consumer changes.
- **Test:** `test_mf_five_minute_dwell_then_walk_transfers` (duration 300 s, confidence 0.50, ble 0.8 -> transfer),
  `test_mf_ble_low_confidence_skips`, `test_mf_ble_too_far_booked_as_ble_too_far`.
- **Discriminates:** the old gate records `low_confidence` for the 5-minute walk; the new code issues a transfer call.

### D2: source = the person's most recent room with a playing player (fixes G-2)
On each transition, if `from_room`'s player is playing, stamp `_recent_source[person] = (room, player, ts)`. When
`from_room` has no player or its player is not playing, use the stamp if it is younger than
`CONF_MF_SOURCE_LOOKBACK_SECONDS`, its player still reads `playing`, and its room has no other occupants
(`_source_has_other_occupants` `:570`). A walk A (music) -> hall -> B records `no_target_player` on the first leg and
transfers A -> B on the second. Gate order is fixed and documented: coordinator, person, same room, BLE, stale,
cooldown, source resolution, target player, target unavailable, source others, source playing, target already playing.
- **Test:** `test_mf_hallway_walk_through_transfers_from_last_playing_room`,
  `test_mf_lookback_expired_records_source_not_playing`, `test_mf_lookback_source_with_others_skips`.

### D3: three correct paths, follow policy, chained moves (fixes C-1, C-2, C-3, G-3)
- **MA path** only when both rooms resolve MA entities AND the MA source entity reads `playing`:
  `transfer_queue` with `target={"entity_id": to_ma}`, data `{"source_player": from_ma, "auto_play": True}`,
  `blocking=True`. Otherwise native or generic.
- **Native join** when both players support `GROUPING`: leader = the source. If the source is a follower in a group
  MF formed (`_active_groups`), the leader is that group's leader; else `group_members[0]` of the source (marked
  `leader_from_attr` in the decision; the live walk confirms it). Call `join(entity_id=leader, group_members=[to])`.
- **Generic** otherwise: `play_media` of the source's content on the target, seek by `CONF_MF_POSITION_OFFSET`
  (the literal `+ 3` at `:1634` goes).
- **Path order:** MA for every player D0 shows MA covers (when the MA source is the thing playing), then native
  join, then generic. One resolver returns the path and the reason; the reason is logged.
- **Follow policy** `CONF_MF_FOLLOW_MODE`, default `move` (the original design, operator 2026-11-13): save the
  source volume, fade the source to `MF_FADE_TARGET_VOLUME` (10 percent), verify the target reads `playing`, then
  after `CONF_MF_RELEASE_DELAY` (5 s, the old unjoin delay knob, now wired) remove the source (MA: already moved,
  nothing to do; join: unjoin the source; generic: `media_stop`) and restore its saved volume, so the next local
  play is not at 10 percent. If the target does not play, the fade is undone at once (volume restored, source keeps
  playing). Native join with the source as leader: if unjoining the leader would stop the target (WiiM risk, checked
  on the walk), the move uses MA or generic instead; the decision log names the reason. `extend` mode joins or plays
  and never fades or removes the source. `_saved_volumes` is cleared at every restore site (no leak).
- **Test:** `test_mf_ma_payload_target_and_source_player`, `test_mf_ma_skipped_when_ma_source_not_playing`,
  `test_mf_join_leader_is_source`, `test_mf_chained_move_joins_to_group_leader`, `test_mf_move_mode_quiets_source_after_target_playing`
  (each path), `test_mf_extend_mode_never_quiets_source`, `test_mf_fade_undone_when_target_not_playing`,
  `test_mf_source_volume_restored_after_release`, `test_mf_saved_volumes_empty_after_restore`,
  `test_mf_path_order_ma_then_native_then_generic`.
- **Discriminates:** the old join puts the idle target in `entity_id`; the old MA call sends `source`/`target` keys;
  both fail the payload tests against a FakeServices that validates the upstream schema.

### D4: verify on ground truth; one outcome registry (fixes C-4, C-5, C-6, C-10)
After any path, wait `CONF_MF_VERIFY_DELAY` and read the target. `success` iff `playing`. Only then release the
source. The `media_play` nudge stays only on the generic path when the target's `media_content_id` matches what MF
sent (outcome `success_nudged`, counted as a success in the rate). Otherwise `verify_failed`, source untouched.
`unverified` is retired (renamed to `verify_failed`). `manual_transfer` goes through the same
`_transfer_then_release` helper as automatic moves.
One tuple `MF_OUTCOMES` in `music_following.py` is the single source for `_transfer_stats` init, `_SKIP_OUTCOMES`,
`_TRANSFER_KEYS` and an `outcomes_today` dict in `get_diagnostic_data`. `_record_stat` with an unknown name logs
WARNING and counts `unknown_outcome`. Names: `success`, `success_nudged`, `verify_failed`, `failed`,
`coordinator_disabled`, `person_not_enabled`, `same_room`, `ble_low_confidence`, `ble_too_far`, `stale_transition`,
`cooldown_blocked`, `ping_pong_suppressed`, `no_source_player`, `no_target_player`, `target_unavailable`,
`source_has_others`, `source_not_playing`, `active_playback_blocked`, `sleep_suppressed`, `night_suppressed`,
`exception`. The anomaly consumer (`dc:306`) reads the success rate from the same registry.
- **Test:** `test_mf_every_transition_has_exactly_one_outcome` (table-driven: one case per name, drives the real
  `_on_person_transition`), `test_mf_record_stat_unknown_name_is_counted`, `test_mf_source_untouched_when_target_not_playing`
  (3 paths), `test_mf_manual_transfer_verifies_before_release`, `test_mf_nudge_only_on_own_generic_media`.

### D5: observability (operator requirement)
1. **Decision log.** One INFO line per transition received, key=value: person, from, to, source_room, source_player,
   target_player, path, outcome, reason detail, ble_confidence, closest_ft, dwell_s, path_type, follow_mode,
   call_ms, verify_ms, target_state, and the knob that decided a skip with its value (e.g. `cooldown=8 left=5`).
   Prefix `MF decision`, so one log grep returns the full trail.
2. **Stats.** `outcomes_today` (every name) on `MusicFollowingHealthSensor`; `last_decision` attribute holds the
   last decision dict; `knobs` attribute holds live knob values and `knobs_applied_at`.
3. **Accuracy from implicit reversal.** After a `success`, for `MF_REVERSAL_WINDOW_S`: the target paused or stopped
   by a non-URA context, or the source resumed playing by a non-URA context, is a reversal. A walk back is not (that
   is a new transition). All MF calls now pass `**ura_ctx_kwargs("media_player")` so `is_ura_context` tells them apart
   (the lighting manual-hold detector `actuator_reconciler.py:500` uses the same test; it covers room lights only, so
   MF uses a one-shot `async_track_state_change_event` on the two players for the window). New sensor
   `sensor.ura_music_following_accuracy` ("Music Follow Accuracy", CM device): state = percent of successes not
   reversed over 7 days (nightly from room memory, plus a since-start live count); attributes successes, reversals,
   by kind, by room pair.
4. **Digest.** `_build_music_following_digest_section` beside `:5788`, called at `:5640`. Example: "Music following,
   last 24 h: 12 moves, 11 played, 1 verify failed, 1 moved back by hand. Most common skip: source_has_others (6)."
   Empty string when there were no candidate transitions.
5. **Zero-fire trip-wire.** Nightly op `run_room_ai_health_check` in `nightly_maintenance.py`: if the trailing 24 h
   had at least `MF_ZERO_TRANSFER_MIN_CANDIDATES` transitions with a playing source and a target player, and zero
   `success`, call `fire_stuck_signal` kind `music_follow_silent` with the top skip reasons.
- **Test:** `test_mf_decision_log_line_has_all_fields`, `test_mf_reversal_target_paused_by_person`,
  `test_mf_own_call_is_not_reversal`, `test_mf_digest_section_counts`, `test_mf_silent_tripwire_fires_on_zero_success`,
  `test_mf_silent_tripwire_quiet_without_candidates`.
- **Discriminates:** a feature that skipped every move for a day pages; a day with no music does not.

### D6: room memory episodes (Tier 2-DB trigger: new persisted record shape)
- `music_follow_decision`: one row per transition where a source candidate (direct or lookback) and a target player
  both exist. node `room:<target slug>`; attrs = the D5 decision fields; `source_ref` = `mf:<person_key>:<ts>`;
  `window_dedup=False`, `dedup_source_ref=True` (the 60 s window would drop real moves). Volume: about 75 a day
  (audit: 1,039 player-to-player transitions in 14 days); D0 (c) confirms before build.
- `music_follow_reversal`: one row per reversal, node `room:<target slug>`, attrs person_key, kind, seconds_after,
  `decision_ref`. A few a day at most.
- Both added to `MEMORY_EPISODE_TYPES`. `music_follow_decision` added to `MEMORY_WRITER_BACKED_EPISODE_TYPES` and to
  `MEMORY_WRITER_HEALTH_ABSENCE_EXEMPT_TYPES` (a week away has no moves). `music_follow_reversal` is not writer-backed:
  zero reversals is the good case.
- Writes are tracked tasks, gathered at MF teardown. Kill switch `MF_EPISODE_LOG_PERSIST` (rung 1).
- Query: `memory_query` verb `episodes` with node `room:<slug>` and the type; `narrative` lists them.
- **Compactor:** parked. A `music_follow_reliability` fact per room pair (success and reversal rate, 30 days) is
  useful to PERSON-PROFILE-PREFERENCES-1. Revival trigger: that card starts its build, or 30 days of episodes exist
  and the operator asks for per-room tuning.
- **Test:** `test_mf_episode_written_per_decision`, `test_mf_episode_not_written_without_players`,
  `test_mf_episode_types_registered_and_writer_backed`, `test_mf_episode_survives_window_dedup` (two moves 10 s apart
  both written). Fixture schema from production DDL.

### D7: knobs live, leak fixed, dead weight trimmed (fixes C-7, C-8, C-9)
1. All rung-2 knobs in §7 go into the CM in-place allowlist (`__init__.py:7643`) and apply block (`:8393`), are seeded
   at `:3875-3905`, and reach the engine through `update_gate_config` (extended) and
   `TransitionDetector.set_ping_pong_window`. The monkey-assign at `dc:145-146` is replaced by the same call.
2. `add_diagnostic_listener` returns an unsubscribe; the coordinator calls it in `async_teardown` (`dc:677`); the four
   sensors wrap it in `async_on_remove`.
3. `music_on_arrival_start` leaves the form and strings (constant kept, comment "retired; arrival music moves to
   PERSON-PROFILE-PREFERENCES-1").
4. `_stop_all_playback` (`dc:655`) stops only configured room and zone players.
5. `set_preference_provider(callable)` hook, `None` today = current behaviour.
- **Test:** `test_mf_knobs_live_after_options_update` (in-place, no reload), `test_mf_reload_does_not_duplicate_listeners`,
  `test_mf_hazard_stop_scoped_to_room_players`, `test_mf_preference_provider_none_is_identity`. Config extremes: verify 0
  and 30; cooldown 0 with ping-pong 0 (a back-and-forth walk gives at most one move per leg); lookback 0 (D2 off).

### D8: tests drive production paths
`FakeServices.async_call(domain, service, data=None, blocking=False, target=None, context=None, **kw)` records all
of them and validates the MA and join schemas. Every §5 site gets a payload assertion including the URA context.
Delete the tautologies (`test_music_following.py:290, :309`) and the dead-knob test (`test_music_following_coordinator.py:260-283`).
Close TEST-MUSIC-SYSMODULES-LEAK-1 (fixture restores `sys.modules`).
- **Test (Review C):** per-site source mutation on the join payload, MA payload, MA-only-if-playing check, verify gate,
  source release, lookback, BLE gate, outcome registry: each turns a named test red.

### D9: options-flow UI and docs
UI in §8. Update `docs/Coordinator/MUSIC_FOLLOWING.md` (gates, paths, follow mode, outcomes, episodes) and the
presence state-of-play §1 consumer row for `ura_person_location_change` (new payload keys; MF as comfort consumer).

### D10: live validation (operator walk, Saturday or Sunday)
Music on a WiiM in room A for at least 5 minutes, walk to WiiM room B; then B -> C; then A -> hallway -> B; then an
MA room if D0 found one.
- **Live:** target reads `playing` within the verify delay; in `move` mode the source drops to 10 percent, is
  removed about 5 s after the target plays, and reads its original `volume_level` afterwards; `group_members` read on both players and the leader matches the decision log;
  `outcomes_today.success` increments; one `music_follow_decision` row per leg in room memory; the digest shows the
  line next morning. A walk with nothing playing records `source_not_playing`, or `source_has_others` /
  `target_unavailable` when those gates apply first (order in D2).
- **Discriminates:** a pass through the nudge shows `success_nudged`; a reversed leader shows the source in the
  target's `group_members` as a follower.

## 7. Numbers get knobs

| Knob | Rung | Default | Why / kill semantics |
|---|---|---|---|
| `CONF_MF_FOLLOW_MODE` | 2 NEW | `move` | move (fade, verify, remove, restore) vs play in both rooms; operator confirms on the walk |
| `CONF_MF_RELEASE_DELAY` | 2 (existing `CONF_MF_UNJOIN_DELAY` key, now wired) | 5 | seconds after the target plays before the source is removed; 0 = at once |
| `CONF_MF_MIN_BLE_CONFIDENCE` | 2 NEW | 0.5 (D0 sets) | BLE room confidence floor; 0 = off |
| `CONF_MF_HIGH_CONFIDENCE_DISTANCE` | 2 existing | 8 ft | BLE bleed guard; 0 = off; now pushed live |
| `CONF_MF_SOURCE_LOOKBACK_SECONDS` | 2 NEW | 90 (D0 sets) | hallway walk-through; 0 = off |
| `CONF_MF_COOLDOWN_SECONDS` | 2 existing | 8 | per-person re-move guard; 0 = off |
| `CONF_MF_PING_PONG_WINDOW` | 2 existing | 60 | quick-return suppression; 0 = off |
| `CONF_MF_VERIFY_DELAY` | 2 existing | 2 | wait before the ground-truth read |
| `CONF_MF_POSITION_OFFSET` | 2 existing | 3 | generic-path seek lead |
| `CONF_MF_STALE_TRANSITION_SECONDS` | 2 NEW field, existing const | 15 | drop old transitions |
| `CONF_MF_MIN_CONFIDENCE` | retired | n/a | gated on dwell; key ignored, field removed |
| `MF_FADE_TARGET_VOLUME` | 1 | 0.1 | was `FADE_OUT_VOLUME` `:113` (original design) |
| `MF_NUDGE_SETTLE_S` | 1 | 1 | was literal `:994` |
| `MF_REVERSAL_WINDOW_S` | 1 | 120 | accuracy window; 0 = no reversal tracking |
| `MF_ZERO_TRANSFER_MIN_CANDIDATES` | 1 | 3 | trip-wire floor; 0 = trip-wire off |
| `MF_EPISODE_LOG_PERSIST` | 1 | True | room memory writes; False = off (move type to exempt) |
| `MF_MA_FIRST_ENABLED` | 1 | True | MA path off if MA misbehaves |

## 8. UI (Coordinator Manager, Music Following)

Before: one form, ten fields, timing numbers first, "Minimum transition confidence" and "Source speaker release
delay" among them; arrival-start toggle on another form. After: two everyday choices on top, the numbers in a
collapsed "Fine tuning" section (`_advanced_section`), helper text in plain sentences.

```
Music Following
  How music follows          [Move music (recommended) | Play in both rooms]
      "Move music: the music starts in the room you walk into; the old room fades, then stops once the new room
       is playing, and its volume is put back for next time."
  Not while the house sleeps [on]
  At night                   [Follow as normal | Only to your bedroom | Do not follow]
  Unusual-activity alerts    [Normal ...]                      (existing bucket select)
  > Fine tuning (collapsed)
      Stop the old room after (s)            5
      Wait before moving again (s)           8
      Ignore quick returns within (s)        60
      Check the new room after (s)           2
      Remember the last playing room for (s) 90
      Ignore moves older than (s)            15
      Phone must be within (ft)              8
      Location certainty needed              [Any | Normal (recommended) | Strict]   (0 / 0.5 / 0.7)
      Seek ahead on cross-brand moves (s)    3
```
Per-room form (room options, "Music following"): labels become "Music follows into this room", "Room speaker",
"Speaker loudness"; no other change. The sensor names stay at three words or fewer.

## 9. Non-goals

Shadow, offer, approve or undo stages. Grouping for two people in different rooms. Cameras as location. Arrival
music. A preference store or UI. A Sendspin-specific path. New DB tables. Changes to how PersonCoordinator resolves
rooms (only two additive event keys). Compactor facts (parked, D6).

## 10. Tier

Tier 2-DB: two new persisted episode shapes (trigger: payload shape of a persisted record) and operator ruling
(mission critical). Three framing-disjoint reviews: A = gates and payload per path (incl. MA-only-if-playing,
chained leader, follow-mode restore sites); B = lifecycle (listener unsub, in-place options apply, reload, task
cancel, episode tasks at teardown, restart); C = per-site mutation (`ura-reviewer-mutation`). Plus framing G (moves
music on day 1 for long dwells and hallway walks; no shadow). Not Tier 3: comfort class, no shared state machine,
no cost or safety path. Live validation (D10) and README write-back required.

## 11. Plan-review findings disposition

All fixed: G-1 (D1), G-2 (D2), G-3 (D3 follow mode, default move), C-1, C-2, C-3 (D3), C-4, C-5, C-6, C-10 (D4,
§3), C-7, C-8, C-9 (D7, §7), C-11 (D10 conditional outcome with gate order). Declined: none.

## 12. Plan completion tracking

The build README lists D0-D10 as done, deferred (reason, card) or dropped. Carry-outs at plan time: compactor fact
(parked, trigger in D6); arrival music and preferences (PERSON-PROFILE-PREFERENCES-1); per-pair ping-pong (L9).

## 13. Open questions for the operator

1. Follow mode `move` as specified (fade to 10 percent, verify, stop after 5 s, restore volume). Recommended: yes;
   confirm on the weekend walk.
2. Players D0 finds without MA coverage: add them to MA, or accept native-only for them? Recommended: add to MA
   where the provider exists; native-only for the rest, named in the README.
3. If a WiiM leader cannot be unjoined without stopping the group, use MA or generic for that move. Recommended: yes.
4. Should the digest line appear every morning, or only when something failed or was reversed? Recommended: every
   morning for the first two weeks, then only on failures (knob in the digest builder, rung 1).
