# PLANNING: music following repair

Card: MUSIC-FOLLOWING-TRANSFER-REPAIR-1. Parent: AUDIT-ROOM-AI-AUTOMATION-CHAINING-MUSIC-1.
Related: TEST-MUSIC-SYSMODULES-LEAK-1, PERSON-PROFILE-PREFERENCES-1, TRUST-APPROVE-UNDO-DIGEST-1.
Written 2026-11-13 by ura-planner. One clean build spec. Design history (not a spec):
`DESIGN_reimagine_room_ai_chaining_music_2026_11_13.md`.

## 0. Charter (operator 2026-11-13, verbatim)

- "No shadow mode. I tested music following like 2 a long time ago. And it worked which was mind blowing. Treat the
  reformulations as full blown mission critical feature that must work on day 1. My trust just means get it right and
  make sure it's tested well. No delays. This is where our features die and are not switched on."
- "We will fix the AI automation and the AI [chaining] and music following. We will not retire them... Also, music
  following is key to personalization."
- "Note that we already know the rooms everyone we know is in via dense ble. Again this is solved... Ble is literal,
  Vision adds depth."

Consequences: no shadow, offer or probation stage. The feature ships ON (master switch and the four enabled persons
stay as they are) and must move music correctly on day 1. Trust = correct code + tests that assert real service
payloads + one live walk. Decision logging is observability only, never a gate.

## 1. Institutional context verified

Read in full: CLAUDE.md, the design doc, `AUDIT_room_ai_automation_chaining_music_2026_11_13.md`, the four board
cards (fields incl. `delivery_2026_11_13`, `live_walk`), `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (complete, incl.
§10 ledger), `SENSOR_FLEET_CLASSES.md` (complete). No §10 claim is re-asserted. No HVAC code is touched.
Prior plans skimmed: `PLANNING_audit_music_following.md`, `CRITIQUE_audit_music_following_2026-07-10.md`,
`DRAFT_README_music_following_name_match.md`. Memory: identity model F1-F5, extend-don't-rebuild, fire check,
hollow test anchors, numbers get knobs.

Prior-art scan (code re-grepped on develop 00f678b9), REUSE or NEW per piece:

| Piece | Verdict | Where |
|---|---|---|
| Person room input | REUSE | `person_coordinator.py:1059-1068` fires `ura_person_location_change` from the dense-BLE three-tier resolver; `transitions.py:157` `_on_location_change` builds `RoomTransition` (`transitions.py:28`); MF subscribes at `music_following.py:211` |
| Person id matching | REUSE | `music_following._person_key` `music_following.py:44` |
| Platform dispatch | REUSE + FIX | `_transfer_media` `music_following.py:1359`, `_get_player_platform` `:1040` |
| MA transfer | FIX | `_transfer_mass_queue` `:1537` (call at `:1553`) |
| Native join | FIX | `_transfer_same_platform_join` `:1485` (call at `:1505`) |
| Cleanup | FIX | `_schedule_group_cleanup` `:1007` |
| Verify | FIX | `_verify_transfer` `:958` (nudge `:984`) |
| Skip counters | REUSE + EXTEND | `_SKIP_OUTCOMES` `:356`, `_record_stat` `:370` |
| Live knob push | REUSE + EXTEND | `update_gate_config` `:311`, called from `domain_coordinators/music_following.py:149` |
| Knob constants | REUSE | `const.py:4090-4109` (`MUSIC_TRANSFER_COOLDOWN_SECONDS`, `PING_PONG_WINDOW_SECONDS`, `TRANSFER_VERIFY_DELAY_SECONDS`, `GROUP_UNJOIN_DELAY_SECONDS`, `CONF_MF_*`) |
| Stale-transition knob | REUSE const, NEW field | `DEFAULT_MF_STALE_TRANSITION_SECONDS` `const.py:4156`; no CONF field (grep config_flow = 0) |
| Diagnostic listeners | FIX | `add_diagnostic_listener` `music_following.py:349`; registrants `domain_coordinators/music_following.py:264`, `sensor.py:8157, 8359, 8430, 8510` (four sensors, not one as the audit said) |
| Health sensor | REUSE | `MusicFollowingHealthSensor` `sensor.py:8129` |
| Hazard stop | FIX scope | `_stop_all_playback` `domain_coordinators/music_following.py:655` |
| Arrival toggle | DELETE from form | `CONF_MUSIC_ON_ARRIVAL_START` `const.py:4776`, `strings.json:1889,1898`; handler no-op `domain_coordinators/music_following.py:549` |
| Real-path test harness | REUSE + FIX | `quality/tests/test_v5100_music_following.py` (`FakeServices.async_call` `:231` lacks `target=`) |
| Preferences store | NOT HERE | owned by PERSON-PROFILE-PREFERENCES-1; this plan adds an interface only |

MA schema verified against HA core source (dev, fetched 2026-11-13):
https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/music_assistant/services.py .
`transfer_queue` is a platform ENTITY service on `media_player` (target = the destination player), schema
`source_player: cv.entity_id` (optional), `auto_play: bool` (optional, no default set, so the queue may move
without playing unless we send `True`). Doc: https://www.home-assistant.io/actions/music_assistant.transfer_queue/ .
Join semantics: https://www.home-assistant.io/actions/media_player.join/ ("The target plays the audio, and the group
members follow it").

Config-first: no setting fixes a wrong service payload or a leak. The five knobs being dead is itself the finding.

## 2. Identity model and consumer class

MF consumes per-person room location from dense BLE (PersonCoordinator resolution, emitted as
`ura_person_location_change`). In the F model this is F4 shaped ("P is at X at T") from BLE, not cameras, plus F1
implicitly (tracked persons only). It does not read F2 (census), F3 (crossings) or F5 (arrival). It produces no identity fact. Consumer
class: comfort. A wrong move is an annoyance, never access or safety. Policy (confidence 0.6, stale 15 s, ping-pong,
BLE distance, SLEEP) lives in MF, not in the producer. Vision is not an input in this plan (operator: BLE is literal;
vision adds depth later).

## 3. Falsifiable invariants

- **INV-MF-1 (no silent loss).** On any transfer path (MA, native join, generic), MF never stops, pauses, ungroups or
  fades the source unless the target has been read as `playing` after the call. Break it by finding any reachable
  path where the source goes quiet while the target is not `playing`.
- **INV-MF-2 (honest outcome).** Every evaluated transition ends in exactly one recorded outcome (success or a named
  skip/fail). `success` is recorded only when the target state is `playing` at verify time and that came from our
  call, not from a blind `media_play` nudge on an idle target with no media of ours.
- **INV-MF-3 (knobs are live).** Changing any of the six timing knobs in the CM options changes engine behaviour
  without restart (options-update path) and after reload.

## 4. Producer and consumer checks

**Producer: person room.** `person_coordinator.py` resolves each tracked person's room every ~30 s and fires
`ura_person_location_change` on change (`:1059-1068`). Health measured by the audit: 8,126 `room_transitions` rows in
14 days, 1,039 eligible player-to-player transitions at confidence 0.6 or more. Fire check: healthy.
**Producer: transfer outcome.** Fire check: `transfers_today 0` on audit day; last observed success 2026-10-11;
whether any success happened since is unknown because skips and successes both bump `sample_count` (M2). This plan
makes it measurable.
**Consumers of MF outcomes:** `_record_stat` feeds the four sensors (display) and `_on_transfer_outcome`
(`domain_coordinators/music_following.py:306`) feeds the anomaly baseline (observability). No trust consumer.
**Forward trace:** transition -> `_on_person_transition` (`:473`) gates -> `_execute_transfer` (`:726`) ->
`_transfer_media` (`:1359`) -> one of three service paths -> `_verify_transfer` -> cleanup and source fade. Every link
is in scope below; nothing downstream is left unread.

## 5. Emission-site enumeration (every `hass.services.async_call` in `music_following.py`)

`:945` volume restore, `:984` verify nudge, `:1018` cleanup unjoin, `:1467` source fade/stop in `_transfer_media`,
`:1505` and `:1517` join + volume, `:1553` and `:1565` MA transfer + volume, `:1609`, `:1621`, `:1640` generic
play/volume/seek. Plus `domain_coordinators/music_following.py:666` hazard `media_stop`. Builder re-greps before
editing and each site gets a payload assertion (D5).

## 6. Deliverables

### D0: read-only probe (first, no HA writes)
Map each of the 10 configured `room_media_player` entities to its Music Assistant `media_player` (if any) via the
device and entity registries over the Samba mount, and record whether MA mirrors share the native device or sit on
their own MA device. Output: a table in this plan's README. This picks D1's resolution rule (same device, or
explicit field).
- **Verify:** table lists all 10 rooms with native entity, MA entity or none, and the registry link used.
- **Discriminates:** if MA mirrors sit on their own device, "same device" resolution returns none for every room; the
  table shows that before any code assumes it.

### D1: MA-first transfer with the correct schema
Resolve source and target to MA entities (D0 rule). If both resolve, call
`music_assistant.transfer_queue` with `target={"entity_id": to_ma}`, data `{"source_player": from_ma,
"auto_play": True}`, `blocking=True`. If either does not resolve, fall to D2 or generic. Room-level resolution is
one helper used by `_get_room_player` callers, so the player shown in sensors and the one moved agree.
- **Verify:** payload exactly as above; no `source`/`target` keys in data.
- **Test:** `test_mf_ma_transfer_payload_target_and_source_player`, `test_mf_ma_unresolved_falls_back_generic`.
- **Discriminates:** under the old bug the call raises in production; the test FakeServices now validates the HA
  schema (`source_player`, `auto_play` only), so the old payload fails the test, the fixed one passes.

### D2: correct native join direction and cleanup
`media_player.join` with `entity_id=from_player` (the playing leader), `group_members=[to_player]`. Before calling,
check `MediaPlayerEntityFeature.GROUPING` on both entities; without it, go generic. Cleanup is re-decided: the
source stays leader while the person is in the target room; when the source room is later empty of that person and
of others (`_source_has_other_occupants` `:570`), the group is left alone (no delayed unjoin of the leader, which
dissolves the group on WiiM). The 5 s source unjoin at `:1014-1025` is removed. Whether a follower-only WiiM can be
promoted to leader is checked on the live walk (D7); if it can, an unjoin-of-source policy can return as a knob later.
- **Test:** `test_mf_join_leader_is_source`, `test_mf_join_requires_grouping_feature`, `test_mf_no_unjoin_of_leader`.
- **Discriminates:** old code puts `to_player` in `entity_id`; the payload test fails on it.

### D3: verify on ground truth, then release the source
After any path, wait `verify_delay`, read the target. `success` iff target state is `playing`. Only then fade or stop
the source (INV-MF-1). The blind `media_play` nudge is kept only on the generic path, where we issued `play_media`
ourselves, and only if the target's `media_content_id` matches what we sent; a nudge result records outcome
`success_nudged`. Otherwise outcome `verify_failed` and the source is untouched.
- **Test:** `test_mf_source_untouched_when_target_not_playing` (each of 3 paths),
  `test_mf_nudge_only_on_own_generic_media`, `test_mf_success_requires_playing`.
- **Discriminates:** with the H1 bug, the target stays idle and the source goes quiet; the new test asserts no source
  stop call and outcome `verify_failed`, which the old code fails.

### D4: count every outcome; wire or delete knobs; fix the leak; trim dead weight
1. Add `no_player`, `source_not_playing`, `ble_too_far`, `verify_failed` to `_SKIP_OUTCOMES` and record them at
   `:814-826`, `:861-873`, `:545` (BLE distance stops being booked as `low_confidence`).
2. Wire the five dead knobs plus stale seconds through `update_gate_config` (extended signature) and a new
   `TransitionDetector.set_ping_pong_window`. Engine reads instance values, constants become defaults only. Pushed at
   setup and on options update. Add the stale-seconds field to the CM form.
3. Listener leak: `add_diagnostic_listener` returns an unsubscribe callable; the coordinator stores and calls it in
   `async_teardown` (`:677`); each of the four sensors wraps it in `async_on_remove`.
4. Remove `music_on_arrival_start` from the CM form and strings (constant kept, comment "retired, arrival music moves to
   PERSON-PROFILE-PREFERENCES-1"). The no-op handler log stays at DEBUG.
5. `_stop_all_playback` scoped to players configured on room entries (`room_media_player` and zone players) instead
   of every `media_player`.
6. Preferences hook: `MusicFollowing.set_preference_provider(callable)` returning `None` today; called with
   `(person_key, to_room)` before the volume decision; `None` = current behaviour. No store, no UI.
- **Test:** `test_mf_every_transition_has_one_outcome` (table-driven over every gate), `test_mf_knobs_live_after_options_update`,
  `test_mf_reload_does_not_duplicate_listeners`, `test_mf_hazard_stop_scoped_to_room_players`,
  `test_mf_preference_provider_none_is_identity`.
- **Config-extreme tests:** verify_delay 0 and 30; cooldown 0 and 600; ping-pong 0 (suppression off) with cooldown 0
  (no flap loop: a back-and-forth walk produces at most one transfer per leg); unjoin delay is gone, so its field is
  deleted (see §7).

### D5: tests drive production paths and assert payloads
Fix `FakeServices.async_call(domain, service, data=None, blocking=False, target=None, return_response=False, **kw)`
to record `(domain, service, data, target)` and to validate the MA and join schemas above. Every site in §5 gets an
assertion on domain, service, data and target. Delete the tautologies in `test_music_following.py` (`:290`, `:309`)
and the test at `test_music_following_coordinator.py:260-283` that enshrines dead knobs. Close
TEST-MUSIC-SYSMODULES-LEAK-1 (restore `sys.modules` in a fixture).
- **Test (Review C):** per-site source mutation on `:1505`, `:1553`, verify gate, source-release gate: each mutation
  turns a named test red.

### D6: docs
Update `docs/Coordinator/MUSIC_FOLLOWING.md` (§Tunables, dispatch order, gate 0 kill switch, `_person_key`) and the
presence state-of-play §1 consumer row for `ura_person_location_change` (MF as comfort consumer).

### D7: live validation (operator walk, Saturday or Sunday)
With music playing on a WiiM in room A, operator walks to room B (WiiM), then to an MA room if D0 shows one.
- **Live:** target `media_player` reads `playing` within verify delay; source per D2 policy (leader still playing in
  group, or faded only after target playing); `group_members` read on both players; health sensor `last_transfer`
  shows `success` with path; walk with nothing playing records `source_not_playing`, not silence.
- **Discriminates:** a pass via the blind nudge shows `success_nudged`, not `success`; a reverse-leader join shows the
  source in `group_members` of the target.

## 7. Numbers get knobs

| Knob | Rung | Default | Why / kill semantics |
|---|---|---|---|
| `CONF_MF_COOLDOWN_SECONDS` | 2 (CM options, existing) | 8 | per-person re-transfer guard; 0 = no cooldown |
| `CONF_MF_PING_PONG_WINDOW` | 2 (existing) | 60 | A-B-A suppression; 0 = off |
| `CONF_MF_VERIFY_DELAY` | 2 (existing) | 2 | wait before ground-truth read |
| `CONF_MF_POSITION_OFFSET` | 2 (existing) | 3 | generic-path seek lead |
| `CONF_MF_STALE_TRANSITION_SECONDS` | 2 (NEW field, existing const default) | 15 | drop old transitions; was rung 1 by accident |
| `CONF_MF_UNJOIN_DELAY` | deleted | n/a | D2 removes the delayed unjoin; field and const removed with a one-line note |
| `MF_MA_FIRST_ENABLED` | 1 | True | revert to native/generic only if MA misbehaves; review-gated |

## 8. Non-goals

Shadow, offer, undo or probation stages. Group-instead-of-move for two people. Camera sightings as location.
Arrival music. A preferences store or UI. A Sendspin-specific path (MA-first already reaches Sendspin players). New DB
tables. Changes to the transition producer or person_coordinator.

## 9. Tier

Tier 2-DB strength by operator ruling (mission critical): three framing-disjoint reviews, A = payload and gate
correctness per path, B = lifecycle (listener unsub, reload, options-update, task cancel, restart), C = per-site
source mutation (`ura-reviewer-mutation`), plus framing G (goal fidelity: ships ON, works day 1, no shadow). Not Tier
3: comfort-class, no shared state machine, no cost or safety path. The one invariant with a one-missed-site shape
(INV-MF-1) is covered by C mutating each source-release site. Live validation (D7) and README write-back mandatory.

## 10. Plan completion tracking

The build README lists each D0-D7 item as done, deferred (with reason and card) or dropped. Known carry-outs at
plan time: arrival music and preference store (PERSON-PROFILE-PREFERENCES-1); approve/undo and digest
(TRUST-APPROVE-UNDO-DIGEST-1, now optional per the no-shadow ruling); per-pair ping-pong (L9) stays open.

## 11. Open questions for the operator

1. Group policy after a native join: keep the group (source keeps playing in both rooms) or stop the source once the
   target plays? This plan defaults to "keep" for WiiM and confirms on the walk.
2. For rooms with both a native player and an MA mirror, always prefer MA? Default yes.
