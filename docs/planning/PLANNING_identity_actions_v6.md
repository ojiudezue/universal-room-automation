# PLANNING: identity actions (arc step 8): named arrivals, arrival music, departure pause

Cards: VISION-CROSSING-ANALYSIS-1 (P2-D9 arrival record and its count follow-up, built here as specified in
`PLANNING_crossing_vision.md` §5), PERSON-PROFILE-PREFERENCES-1 (first slice), DEPARTURE-ACTIONS-1 (first consumer).
Arc: identity / vision / census, step 8 of `ARC_identity_vision_census_map.md` §4. This is the release the operator
named the identity-driven-autonomy milestone (2026-11-14: "the last ship of this arc should move to v6.x... it's going
to lead to OC and personalization and Ai enhancements for rooms"; "step 8 is fine. You better get a move on").
Tier 2-DB (argued in §11). Status: plan, not reviewed. Author ura-planner, 2026-11-14, develop @ fd893bbc.

Read first, completely (CLAUDE.md): `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`,
`IDENTITY_FUSION_CAMERAS_MANUAL.md`, and `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (to confirm this plan changes no HVAC
input; per-person HVAC targeting already exists as `zone_persons`, `hvac.py:7198-7236`). No ledger claim re-asserted.

## 1. What makes 6.0.0 true, and why this behaviour

CLAUDE.md: 6.0.0 is "the census/identity arc reaching real actuation: guest gate consuming door-identity,
arrival/departure keyed to `person_id`, egress identity". The smallest real behaviour that makes that true, after
step 7 ships, is three things keyed to a recognised person:

1. **Named arrivals.** Step 7 already names confirmed arrivals ("That was Oji"). This plan adds the arrival record
   (n people came in, k recognised) and its count follow-up through the same amend function.
2. **Arrival music (the first personalization).** When a resident who opted in arrives, their own music starts in the
   first of their rooms they walk into that has a speaker, at their volume, if nobody else is there and it is not
   quiet hours.
3. **Departure pause.** When that person leaves, the music URA started for them pauses if their room is now empty.

Why arrival music, by value and readiness (alternatives priced):

| Candidate | Value | Readiness | Verdict |
|---|---|---|---|
| Arrival music | Operator asked for it twice (card `scope_add_2026_11_12_arrival_music`; "music following is key to personalization"); the only `SIGNAL_PERSON_ARRIVING` consumer that is a no-op today (`domain_coordinators/music_following.py:549-583`) | Needs a 4-field profile, a play call on an existing player, the repaired music-following player model | **Build** |
| Per-person HVAC preference | Per-person setpoints PERMANENTLY CUT (ROADMAP_v11:39/266); per-person zone pre-arrival already live (`zone_persons`, 52 writes / 14 d) | Nothing new to deliver | No |
| Welcome lighting scene | Lights already follow room occupancy; margin near zero | Scene per room per person, new UI | Park (trigger: operator asks for a scene) |
| Guest gate on door identity | Stays parked (GUEST-GATE-DOOR-IDENTITY-1; house-state rung not legal) | Not legal on the ladder | No |

Charter goals served, verbatim: "assist arrivals accuracy and personalization"; "it's going to lead to OC and
personalization and Ai enhancements for rooms". Hard constraint "I need away to be fast acting": nothing here reads or
writes house state (INV-V6-AWAY). Short-clip constraint: this plan consumes the vision outcome only and fixes no frame
source. Drift check: zero drift; one tradeoff surfaced (§12 Q3, count follow-up stays dark until the F-NOTIFY bars).

## 2. Institutional context verified

Greps run 2026-11-14 on develop: `SIGNAL_PERSON_ARRIVING` (16 files), `music_on_arrival|play_media|quiet` in both
music files, `person_profile|PERSON_PREF|per_person` in `const.py` / `config_flow.py` (0 hits), `CONF_ROOM_MEDIA_PLAYER`,
`CONF_ROOM_MEDIA_VOLUME_SCALE`, `is_quiet_hours_active`, `get_room_occupants|get_persons_in_room`, `ura_ctx_kwargs`,
`MEMORY_EPISODE_TYPES`, `get_last_arrival_record|get_last_crossing|view_for_class`.

| Piece | Verdict | Where |
|---|---|---|
| Arrival signal intake | REUSED (fill the no-op) | `MusicFollowingCoordinator._handle_person_arriving` `domain_coordinators/music_following.py:549`, subscribed `:281` |
| Person room transitions | REUSED | `music_following.py:211` listener, `_on_person_transition(RoomTransition)` `:473` |
| Room primary player | REUSED | `CONF_ROOM_MEDIA_PLAYER` `const.py:106`; primary-player rule INV-MF-6 (`PLANNING_music_following_repair.md`) |
| Player to MA entity map, MA-first play, outcome registry, decision log, room memory pattern | REUSED from MUSIC-FOLLOWING-TRANSFER-REPAIR-1 D0, D3, D4, D5, D6 | that plan §6 |
| Volume scale | REUSED | `CONF_ROOM_MEDIA_VOLUME_SCALE` `const.py:4250` (0.5-1.5) |
| Quiet hours | REUSED | `NotificationManager.is_quiet_hours_active` `notification_manager.py:4772` |
| Occupants in a room | REUSED | `PersonCoordinator.get_persons_in_room` `person_coordinator.py:2199` |
| URA context stamp (reversal detection) | REUSED | `ura_context.ura_ctx_kwargs` `ura_context.py:80`, `is_ura_context` `:87` |
| Person ids | REUSED | `person_ids.tracked_person_entity_id` `:25`, `slug_of` `:40`, `display_of` `:56` |
| Arrival-start master toggle | REUSED (un-retire) | `CONF_MUSIC_ON_ARRIVAL_START` `const.py:4864` (music repair D7 item 3 planned to retire it; amended, §10) |
| Crossing record / arrival record reads | REUSED | `PresenceCoordinator.get_last_crossing` `presence.py:6009`, `get_last_arrival_record` `:6021` |
| Notification class threshold | REUSED | `CONSUMER_CLASS_MIN_CONFIDENCE` `const.py:6512` (notification 0.75) |
| Promotion ladder gate | REUSED | `view_for_class` `presence.py:5984`; `CROSSING_VISION_CONSUMER_CLASSES` (census plan CD3) |
| Amend function | REUSED (step 7) | `EgressDirectionTracker.notify_arrival_followup` (`PLANNING_egress_direction_aware_identity.md` §5.4) |
| Episode registration | REUSED pattern | `MEMORY_EPISODE_TYPES` `const.py:6204`, `MEMORY_WRITER_BACKED_EPISODE_TYPES` `:6263` |
| Room dwell / next-room learner for suggestions | REUSED | `PatternLearner.predict_next_room`; `person_visits` (presence state of play §9 PREDICT row) |
| Person profile store `person_profiles` (CM options) + "People" options step | NEW | 0 hits; card adjacency sweep 2026-11-08 found none; NM per-person channels are delivery config, not preferences |
| Arrival intent, start, departure pause logic | NEW, inside the music-following coordinator | no arrival-start code exists ("never implemented", `:573-583`) |

Prior plans read: `PLANNING_crossing_vision.md` (§2-§8, P2-D9, INV-NOTIFY-LATENCY), `PLANNING_census_deconfliction.md`
§3.2 (rung 2 bars), `PLANNING_person_awareness_read_api.md`, `PLANNING_person_sighting_layer.md` §2A / §2B.6 / §15
headings, `PLANNING_nvr_witness_layer.md` (card body; NVR names feed `k` only through F3), `PLANNING_music_following_repair.md`
(§1-§13 headings, D0-D9), `PLANNING_known_person_annotation.md` (header; annotate-only doctrine),
`AUDIT_pre_arrival_inventory_and_precool_standdown.md` (218 arrival signals / 14 d; music handler no-op).
Memory: `project_hyper_personalization_person_profile`, `reference_identity_model_f1_f5`, `feedback_fire_check_and_forward_trace`.
Config-first: no setting starts music on arrival (the toggle is a no-op); no profile exists to configure.

## 3. Facts and consumer classes

Consumes F5 (`SIGNAL_PERSON_ARRIVING`, any source: `geofence`, `ble`, and from step 7 `camera_egress`), F1 (raw
`person.*` departure edge; BLE room per person), F3 (crossing record: named exits, `departure_candidate`), F3
attribute (arrival record). Produces no F fact. Classes: arrival music and departure pause are **comfort** (reversible,
not security, not house state; trust view; acts only on person-keyed phone or confirmed evidence, never on a face
alone); the count follow-up is **notification** (rung 2; names >= 0.75); profile suggestions and the profile sensor are
**display**. Access, security, house state: none.

## 4. Measure first (P8-0, read-only, one probe, before build)

Over 14 days of recorder + URA DB (`person_visits`, activity log `pre_arrival` rows, media player history):
(a) per resident, arrivals per day by source and the lag from the F5 signal to the first BLE room transition into a
room with a configured primary player; share where that player was already playing, another person was in the room,
or quiet hours were on. This sizes `ARRIVAL_MUSIC_WINDOW_S` and the expected starts per day.
(b) departures per day per resident and how often the person's arrival room was empty within 5 min after.
(c) After step 7 ships, the share of entry crossings named at the crossing or confirmed (the F-NOTIFY identity bar,
target 0.50) from `egress_identity_outcome` rows.
**Go/no-go:** arrival music builds if (a) shows at least 3 eligible starts per week house-wide for the residents the
operator opts in. Below that the plan returns to the operator with the measured number (charter rule 3), it is not
silently swapped for another behaviour.

## 5. Design

### 5.1 Person profile, first slice (PERSON-PROFILE-PREFERENCES-1)

CM entry options key `person_profiles`: `{ "person.<slug>": {arrival_music, arrival_media, arrival_volume, rooms} }`,
keyed through `tracked_person_entity_id` (one id rule). Fields, nothing else in this slice (no dead knobs):
`arrival_music` (bool, default off: "Play my music when I get home"); `arrival_media` (text: a Music Assistant item,
playlist or radio URI, the same string MA `play_media` takes); `arrival_volume` (0.05-1.0, default 0.30); `rooms`
(room multi-select: "My rooms", e.g. bedroom, bathroom, study; empty = any room with a speaker). Edited in a new CM
options step "People" (pick a tracked person, then the form). The form description shows suggested rooms from that
person's `person_visits` top dwell rooms (display only; the operator confirms; predictions never fill a field). A
display sensor `sensor.ura_person_profile_<slug>` exposes the stored fields and `last_arrival_music` (attributes
unrecorded). Shared owners (the master bedroom) fall out of two profiles listing the same room.

### 5.2 Arrival music (comfort consumer)

- **Intent.** `_handle_person_arriving` opens one arrival intent per person for `ARRIVAL_MUSIC_WINDOW_S` (900, P8-0
  sets) when: master `CONF_MUSIC_ON_ARRIVAL_START` on; profile `arrival_music` on with media set; the person is a
  tracked resident; music following enabled and not in observation mode. A second signal inside the window refreshes
  nothing (first source wins; source recorded). Any source opens it; `camera_egress` exists only after phone-free
  confirmation (step 7 D2), so a face alone never opens an intent (consumer policy, not a producer switch).
- **Start.** On the person's next room transitions inside the window (`_on_person_transition`), the first room that
  is in `rooms` (or any room when `rooms` is empty) and has a primary player becomes the target. Gates, each a counted
  outcome: quiet hours (`is_quiet_hours_active`) or house state `sleep` / `waking`; room paused
  (`room_automation_paused`); primary player unavailable; player already playing (never interrupt); another tracked
  person in the room (`get_persons_in_room`) unless `ARRIVAL_MUSIC_ALLOW_SHARED_ROOM`; one start per person per
  `ARRIVAL_MUSIC_MIN_GAP_S` (3600). Action with `ura_ctx_kwargs`: volume = `arrival_volume` x the room's volume scale,
  clamped 0..1, then MA `play_media` on the mapped MA entity (repair D0 map), native `media_player.play_media` when the
  player has no MA entity. Bonus players never join an arrival start.
- **Verify on ground truth.** The primary reads `playing` within `ARRIVAL_MUSIC_VERIFY_S` (20) -> outcome `started`,
  stamp `{person, player, media_content_id, started_at}`; else `start_failed`. Outcomes: `started`, `start_failed`,
  `skipped_quiet`, `skipped_sleep`, `skipped_paused`, `skipped_playing`, `skipped_shared`, `skipped_no_player`,
  `skipped_gap`, `window_expired`; one decision log line and one `arrival_music` room-memory episode each.
- **Reversal (accuracy signal).** A non-URA pause, stop or volume-to-0 on that player within
  `ARRIVAL_MUSIC_REVERSAL_S` (120) of a start counts `reversed` on the episode and the counter.

### 5.3 Departure pause (DEPARTURE-ACTIONS-1, first consumer)

For a person with a live `started` stamp, the first of: a named exit crossing for them at >= 0.75 (`attached` exit
or step 7's `departure_candidate`, read through `get_last_crossing` on `ura_person_egress_event`), or their raw
`person.*` `home -> not_home | zone` edge. Pause (`media_player.media_pause`, URA context) only when the stamped player
still plays the stamped `media_content_id`, the room coordinator reads not occupied (room data, not an entity name),
and no other tracked person is in the room. Else counted `departure_kept_*`. The stamp then clears. Other departure
consumers, decomposed and NOT built: last-resident arming (LAST-RESIDENT-EGRESS-ARM-1 stays parked: arming from
identity is escalation, forbidden by manual §5.5(a)); HVAC setback (AWAY already does it; departure must never feed
house state); lights off (room vacancy already does it).

### 5.4 Named arrivals and the count follow-up (P2-D9, crossing-vision plan)

Build P2-D9 as written in `PLANNING_crossing_vision.md` §5 with three step-8 rules: (1) its follow-up calls
`notify_arrival_followup(crossing_ref, kind="count", names=..., guests=n - k)`, never `async_notify` directly; the old
test `test_r7_and_perimeter_followup_same_crossing` now asserts arrival sends <= 3 (original + 2 amends) and the
perimeter sends unchanged; (2) a name is rendered only when its evidence reaches the notification class (F3 attach
>= 0.75 or a step-7 confirmation); NVR face-entity names in the window count toward `k` for display but render as
"not recognised" in text (a single face leg is 0.6 on the egress ladder); (3) the count follow-up sends only while
`notification` is in the active `CROSSING_VISION_CONSUMER_CLASSES` (F-NOTIFY, census plan CD4 checkpoint after bars a,
b, c, d, e and exact >= 0.90 on 30 graded). Until that flip the record is written and shown (display), and only
step 7's name follow-ups go out. INV-NOTIFY-LATENCY holds: the first message is never delayed.

## 6. Falsifiable invariants

- **INV-V6-NO-FACE-ALONE.** No arrival music start is caused by a face or vision input alone: every `started`
  outcome traces to a `geofence` / `ble` signal or a step-7 confirmation. Break it with a sighting or an unconfirmed
  candidate that opens an intent.
- **INV-V6-NEVER-INTERRUPT.** URA never starts arrival music on a player that reads `playing`, and never pauses
  playback it did not start (stamp + `media_content_id` match). Break it with any legal sequence (two people arriving,
  person changes the track, restart) that pauses someone else's music.
- **INV-V6-QUIET.** No start while quiet hours are active or the house reads `sleep` / `waking`.
- **INV-V6-AWAY.** No step-8 code path reads or writes any input of `infer()`, the census trust view, or HVAC. Break
  it by any change to AWAY entry time on a replay with arrival music on vs off.
- **INV-V6-ONE-AMEND.** Every arrival follow-up goes through `notify_arrival_followup` (inherits step 7 INV-AMEND-ONE).
- **INV-V6-NAME-BAR.** No notification text names a person below the notification threshold.

## 7. Producer and consumer checks; emission sites

Producers read: F5 dispatch sites `presence.py` geofence (`:5575` handler), `person_coordinator.py` ble, D2
`camera_egress` (step 7); fire check: 218 arrival signals / 14 d measured (audit), so the intake is live; the music
handler has fired its DEBUG no-op on every one. Forward trace: signal -> intent -> transition -> start -> verify ->
episode -> departure -> pause. New producers get trip-wires: `arrival_music_zero` (HIGH NM when >= 10 intents with a
qualifying transition in 7 days and 0 `started`), `arrival_music_failing` (HIGH NM on >= 3 `start_failed` in 24 h).
Sites to enumerate at review: every `media_player.*` / `music_assistant.*` call in both music files (the new start and
pause sites plus the repair's sites must all carry `ura_ctx_kwargs`); the one amend function; the CM options save
path (re-read profiles live, no reload, INV-MF-4 style).

## 8. Deliverables

**D0 probe (P8-0).** Verify: report with (a)-(c) committed; go/no-go stated. Live: none.

**D1 profile store, People step, profile sensor.** Verify: saving a profile changes the next intent without reload;
a display-name `tracked_persons` entry keys the same profile as the entity-id form; suggested rooms render and are
never written. Tests: `test_person_profile.py::test_profile_keyed_by_one_id_rule`, `::test_profile_save_live_no_reload`,
`::test_suggestions_never_stored`, `::test_unknown_person_profile_ignored`. Live: `sensor.ura_person_profile_<slug>`
shows the operator's saved fields.

**D2 arrival music.** Verify: geofence arrival, person walks into their bedroom with an idle Sonos -> volume set, MA
play, `playing` within 20 s, outcome `started` (today: DEBUG log only, nothing plays: discriminates). Same walk with the
player already playing -> `skipped_playing`, no call. At 23:30 (quiet) -> `skipped_quiet`. A sighting with no phone
-> no intent. Restart mid-window -> intent dropped, counted. Tests: `test_arrival_music.py::test_geofence_then_room_starts`,
`::test_never_interrupts_playing`, `::test_quiet_and_sleep_skip`, `::test_shared_room_skip`, `::test_face_alone_opens_no_intent`,
`::test_camera_egress_confirmed_opens_intent`, `::test_verify_on_player_state`, `::test_ma_first_native_fallback`
(asserts the exact service payloads), `::test_reversal_counted`, `::test_zero_fire_tripwire`. Config extremes: window 0,
volume 0.05 and 1.0 with scale 1.5 (clamped), `rooms` empty vs one room without a player. Live: one `started` episode
on the operator's first arrival after opting in, music audible, or a counted skip reason.

**D3 departure pause.** Verify: named exit at 0.9 with the stamp live and the room empty -> pause; another person in
the room -> `departure_kept_shared`; the person changed the track -> `departure_kept_not_ours`. Tests:
`test_arrival_music.py::test_departure_pauses_own_playback`, `::test_departure_never_pauses_others`,
`::test_departure_on_tracker_edge_without_crossing`. Live: first departure after a `started` gives a pause or a kept
reason.

**D4 arrival record + count follow-up (P2-D9).** Verify and tests as in the crossing-vision plan plus
`::test_count_followup_via_amend_function`, `::test_low_confidence_names_render_unrecognised`,
`::test_count_followup_dark_until_f_notify`. Live: one `crossing_vision_arrival` row with n, k, `guests_unnamed`.

**D5 episodes, docs.** `arrival_music` in `MEMORY_EPISODE_TYPES` and `MEMORY_WRITER_BACKED_EPISODE_TYPES` (or exempt
with reason when the master is off); `docs/Coordinator/MUSIC_FOLLOWING.md` arrival section; manual §5.5 consumer table
gains the comfort row; presence state of play §1 `SIGNAL_PERSON_ARRIVING` consumers row (music no longer a no-op).

Mutation drills (RED then restore): skip the `playing` gate; drop the quiet gate; let a sighting open an intent;
pause without the `media_content_id` match; bypass the amend function in P2-D9; render a 0.6 name.

## 9. Knobs

| Knob | Default | Rung | Why / kill |
|---|---|---|---|
| `CONF_MUSIC_ON_ARRIVAL_START` (REUSED key) | on at ship | 2 + switch `switch.ura_music_arrival_start` (3) | House master; off = no intents |
| profile `arrival_music` / `arrival_media` / `arrival_volume` / `rooms` | off / empty / 0.30 / empty | 2 (People step) | Per-person opt-in is the real gate |
| `ARRIVAL_MUSIC_WINDOW_S` | 900 (P8-0 sets) | 1 | 0 = never start |
| `ARRIVAL_MUSIC_MIN_GAP_S` | 3600 | 1 | No re-start on a door bounce |
| `ARRIVAL_MUSIC_VERIFY_S` / `_REVERSAL_S` | 20 / 120 | 1 | Ground-truth windows |
| `ARRIVAL_MUSIC_ALLOW_SHARED_ROOM` | False | 1 | Never blast music on someone already in the room |
| `ARRIVAL_MUSIC_DEPARTURE_PAUSE` | True | 1 | False = no departure action |
| Trip-wire thresholds (10 intents / 7 d; 3 failures / 24 h) | as stated | 1 | 0 = off |

## 10. Dependencies, seams, sequence

Must ship first: step 6 census deconfliction (CD1-CD3: legal class set incl. `notification`, ledger term `n` for
P2-D9); step 7 (`notify_arrival_followup`, confirmed names, `camera_egress`, `departure_candidate`); read API ship 1
(shipped v5.108.21); MUSIC-FOLLOWING-TRANSFER-REPAIR-1 D0, D3, D4, D5, D6 (player map, MA play path, outcomes,
episodes; its D1 BLE-confidence gate is not needed here and stays blocked on BERMUDA-DISTANCE-SENSORS-DEAD-1).
**F-NOTIFY dependency:** step 7 shipping meets its identity half; the count follow-up stays dark until the operator's
CD4 flip on measured bars. v6.0.0 does not wait for that flip (§12 Q3).
Seams (arc rule 6): music repair D7 item 3 ("`music_on_arrival_start` leaves the form") is amended: the key stays as
the house master, relabelled; the repair's `set_preference_provider` hook is where D1 profiles plug in (no second
preference path). AI-ROOM-RULES-TRUST-REPAIR-1 shares the observability pattern only; no shared write. Arc map row
M11 updated at plan approval.

## 11. Tier

Tier 2-DB: new actuation keyed on identity across presence and music, a new episode type, a config-flow step; comfort
class, reversible, no house-state, security or energy reach. The arc map pencilled Tier 3 for the profile; pushback:
nothing here can lose money or safety through one missed path, and the operator asked for speed. Three framing-disjoint
code reviews (A local correctness of gates and payloads; B integration, restart, options-save, listener lifecycle; C
per-site mutation) plus a goal-fidelity framing G on the plan; one adversarial plan review (Tier 2 rule) plus G.
Release: v6.0.0 at deploy (operator-named milestone; not assigned in this plan's title).

## 12. Open operator questions (recommended defaults)

1. Who opts in and with what media? Default: Oji only first (media from his MA library), others after one week of
   episodes.
2. Arrival music in shared rooms (the master with Ezinne there)? Default off.
3. Ship v6.0.0 before the F-NOTIFY flip? Default yes: named follow-ups (step 7) and arrival music make the milestone;
   the count follow-up flips at its own checkpoint.
4. Departure pause on? Default on, pause not stop.

## 13. Non-goals

Per-person temperature (cut); welcome scenes; guest-gate door identity; predictions filling profile fields; arrival
music for guests or untracked people; transfers (music repair owns them); any security, lock, HVAC or house-state
consumer; Protect names; interior vision (step 9).

## 14. Plan completion tracking

PERSON-PROFILE-PREFERENCES-1 fields not in this slice, carded with triggers at approval: bathroom, welcome scene,
"automate my entries" beyond music, playlists per room or time of day (trigger: two weeks of `arrival_music` episodes
with a reversal rate under 10 percent, or an operator ask). DEPARTURE-ACTIONS-1 decomposition above; only the pause is
built. Arrival count follow-up flip is CD4, not this plan.
