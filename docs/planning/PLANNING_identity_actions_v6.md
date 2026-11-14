# PLANNING: identity actions (arc step 8): named arrivals, arrival music, departure pause

Cards: VISION-CROSSING-ANALYSIS-1 (P2-D9 arrival record and its count follow-up, built as specified in
`PLANNING_crossing_vision.md` §5), PERSON-PROFILE-PREFERENCES-1 (first slice), DEPARTURE-ACTIONS-1 (first consumer).
Arc: identity / vision / census, step 8 of `ARC_identity_vision_census_map.md` §4. The operator named this the
identity-driven-autonomy release (2026-11-14: "the last ship of this arc should move to v6.x... it's going to lead to
OC and personalization and Ai enhancements for rooms"; "step 8 is fine. You better get a move on").
Status: rev 2, rewritten for plan review `docs/reviews/plan-review/PLANREVIEW_identity_actions_v6.md` (FIX-PLAN, 2 HIGH,
6 MEDIUM, 5 LOW; all addressed, §15). Author ura-planner, 2026-11-14.

Read first, completely (CLAUDE.md): `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`,
`IDENTITY_FUSION_CAMERAS_MANUAL.md`, `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (to confirm no HVAC input changes; per-person
HVAC targeting already exists as `zone_persons`, `hvac.py:7198-7236`). No ledger claim re-asserted.

## 1. What makes 6.0.0 true, and why this behaviour

CLAUDE.md today defines 6.0.0 as "guest gate consuming door-identity, arrival/departure keyed to `person_id`, egress
identity". The operator's 2026-11-14 decision ("step 8 is fine") sets the milestone to step 8, which delivers three
things keyed to a recognised person (the guest-gate item stays parked, GUEST-GATE-DOOR-IDENTITY-1):

1. **Named arrivals.** Step 7 names confirmed arrivals ("That was Oji"); this plan adds the arrival record (n came in,
   k recognised) and its count follow-up through the same amend function.
2. **Arrival music (first personalization).** A resident who opted in walks into the first of their rooms that has a
   speaker; their music starts at their volume if nobody else is there and it is not quiet hours. Ships ON on day 1
   for every resident who sets it in the People step (no trial stage; memory `feedback_no_shadow_mode_day1_correct`).
3. **Departure pause.** When that person leaves, the music URA started for them pauses if the room is now empty.

The CLAUDE.md "Version-level cadence" text is updated in the D6 commit to this definition, quoting "step 8 is fine"
(pending §12 Q2).

| Candidate | Value | Readiness | Verdict |
|---|---|---|---|
| Arrival music | Operator asked twice (card `scope_add_2026_11_12_arrival_music`; "music following is key to personalization"); the arrival handler is a no-op today (`domain_coordinators/music_following.py:549-583`) | 4-field profile, a play call, the repaired player model | **Build** |
| Per-person HVAC | Per-person setpoints CUT (ROADMAP_v11:39/266); per-person zone pre-arrival already live (52 writes / 14 d) | nothing new | No |
| Welcome lighting scene | Lights already follow occupancy | new UI | Park (§12 Q3) |
| Guest gate on door identity | House-state rung not legal on the ladder | not legal | No |

Charter goals served, verbatim: "assist arrivals accuracy and personalization"; "it's going to lead to OC and
personalization and Ai enhancements for rooms". Hard constraint "I need away to be fast acting": nothing here reads or
writes house state (INV-V6-AWAY). Short-clip constraint: this plan consumes the vision outcome only and fixes no
frame source. Drift check: zero drift.

## 2. Institutional context verified

Greps run 2026-11-14 on develop: `SIGNAL_PERSON_ARRIVING`; `music_on_arrival|play_media|quiet|_enabled_persons|MIN_CONFIDENCE`
in both music files; `person_profile|PERSON_PREF|per_person` in `const.py` / `config_flow.py` (0 hits);
`OPTIONS_RELOAD_SUPPRESS_KEYS|_NO_LIVE_ATTR_KEYS` in `__init__.py`; `CONSUMER_CLASS_COMFORT`; `get_persons_in_room`;
`ura_ctx_kwargs`; `MEMORY_EPISODE_TYPES`; `get_last_arrival_record|get_last_crossing|view_for_class`.

| Piece | Verdict | Where |
|---|---|---|
| Arrival signal intake | REUSED (fill the no-op) | `MusicFollowingCoordinator._handle_person_arriving` `domain_coordinators/music_following.py:549`, subscribed `:281` |
| Person room transitions | REUSED, new hook at the TOP | `MusicFollowing._on_person_transition` `music_following.py:473` (enabled-persons return `:511-518`, confidence return `:521-527`, `MIN_CONFIDENCE` 0.6 `:115`) |
| Room primary player; MA map; MA-first play; outcomes; decision log; episodes | REUSED from MUSIC-FOLLOWING-TRANSFER-REPAIR-1 D0, D1, D3, D4, D5, D6, D7 | `PLANNING_music_following_repair.md` §6; `CONF_ROOM_MEDIA_PLAYER` `const.py:106` |
| Preference hook | REUSED | repair D7 item 5 `set_preference_provider(callable)` (`PLANNING_music_following_repair.md:279`) |
| Volume scale | REUSED | `CONF_ROOM_MEDIA_VOLUME_SCALE` `const.py:4250` (0.5-1.5) |
| Quiet hours | REUSED | `NotificationManager.is_quiet_hours_active` `domain_coordinators/notification_manager.py:4772`, reached as `hass.data[DOMAIN]["notification_manager"]` (same lookup as `transit_validator.py:2679`) |
| Room occupancy (any body) | REUSED | room coordinator `data[STATE_OCCUPIED]` (`coordinator.py:3613`), awareness count via `get_house_census(view_for_class("comfort"))` (`presence.py:5952`, `:5984`) |
| Tracked occupants | REUSED | `PersonCoordinator.get_persons_in_room` `person_coordinator.py:2199` |
| Comfort class | REUSED | `CONSUMER_CLASS_COMFORT` `const.py:6498` (no identity threshold, table `:6512`) |
| URA context stamp | REUSED | `ura_context.ura_ctx_kwargs` `:80`, `is_ura_context` `:87` |
| Person ids | REUSED | `person_ids.tracked_person_entity_id` `:25`, `display_of` `:56` |
| Arrival master toggle | REUSED (un-retire) | `CONF_MUSIC_ON_ARRIVAL_START` `const.py:4864` |
| CM options save without reload | REUSED mechanism | `OPTIONS_RELOAD_SUPPRESS_KEYS` `__init__.py:7553` (subset test `:8826`), `_NO_LIVE_ATTR_KEYS` `:7406` (snapshot advance `:8116`) |
| Crossing / arrival record reads | REUSED | `get_last_crossing` `presence.py:6009`; `get_last_arrival_record` `:6021` (None today; D4 fills it) |
| Amend function | REUSED (step 7) | `EgressDirectionTracker.notify_arrival_followup` (`PLANNING_egress_direction_aware_identity.md` §5.4) |
| Episode registration | REUSED pattern | `MEMORY_EPISODE_TYPES` `const.py:6204`, `MEMORY_WRITER_BACKED_EPISODE_TYPES` `:6263` |
| Suggestions | REUSED | `PatternLearner.predict_next_room` `pattern_learning.py:143`; `person_visits` `database.py:995` |
| `person_profiles` store + "People" CM options step | NEW | 0 hits; only `async_step_person_tracking` `config_flow.py:4804` exists |
| Arrival intent / start / departure pause | NEW in the `MusicFollowing` engine | no arrival-start code exists |

Prior plans read: crossing-vision (§2-§8, P2-D9, INV-NOTIFY-LATENCY), census deconfliction §3.2, read API, sighting
plan §2A / §2B.6, NVR witness (card), music repair (all deliverables), known-person annotation (header),
`AUDIT_pre_arrival_inventory_and_precool_standdown.md` (218 arrival signals / 14 d). Memory:
`project_hyper_personalization_person_profile`, `reference_identity_model_f1_f5`, `feedback_fire_check_and_forward_trace`,
`feedback_no_shadow_mode_day1_correct`, `feedback_parent_entry_reload_watchdog_hazard`. Config-first: no setting
starts music on arrival; no profile exists.

## 3. Facts and consumer classes

Consumes F5 (`SIGNAL_PERSON_ARRIVING`: `geofence`, `ble`, and from step 7 `camera_egress`, which step 7 dispatches
only for GPS-led confirmations of the person's own phone), F1 (raw `person.*` departure edge; BLE room per person), F2
awareness count (comfort class, through `view_for_class`; equals trust until F-LEAD), F3 (named exits), F3 attribute
(arrival record). Produces no F fact. Arrival music and departure pause: **comfort**. Count follow-up:
**notification** (rung 2; names >= 0.75). Profile sensor and suggestions: **display**. Access, security, house state:
none.

## 4. Measure first (P8-0, read-only, one probe, before build)

14 days of recorder + URA DB (`person_visits`, activity log `pre_arrival` rows, media player history), over ALL
residents whose rooms have a primary player, reported per resident:
(a) arrivals per day by source; lag from the F5 signal to the first BLE room transition into a primary-player room;
the classified confidence of that first transition (expected 0.50, the H1 case); share where the native player or its
MA entity was playing, the room was already occupied, or quiet hours were on; and how often the first player room
reached was not in a plausible `rooms` set within 900 s (sizes `ARRIVAL_MUSIC_WINDOW_S`, L5).
(b) departures per day per resident; how often the arrival room was empty within 5 min after.
(c) after step 7 ships, the share of entries named at the crossing or confirmed (F-NOTIFY identity bar 0.50).
**Go/no-go:** build if (a) shows >= 3 eligible starts per week house-wide; below that the plan returns to the operator
with the number (charter rule 3), never a silent swap.

## 5. Design

### 5.1 Person profile, first slice

CM entry options key `person_profiles`: `{ "person.<slug>": {arrival_music, arrival_media, arrival_volume, rooms} }`,
keyed through `tracked_person_entity_id`. Fields: `arrival_music` (bool, "Play my music when I get home"), `arrival_media`
(the string MA `play_media` takes), `arrival_volume` (0.05-1.0, default 0.30), `rooms` ("My rooms"; empty = any room
with a speaker). Edited in a new CM options step "People" (pick a tracked person, then the form). The form shows
suggested rooms from that person's `person_visits` dwell (display only; never written). Display sensor
`sensor.ura_person_profile_<slug>` (fields and `last_arrival_music`, attributes unrecorded; visible to every HA user,
accepted for this household, L4).
**No reload (H2):** `person_profiles` and `music_on_arrival_start` join `OPTIONS_RELOAD_SUPPRESS_KEYS` and
`_NO_LIVE_ATTR_KEYS` in the same commit, so a People save applies in place and advances the snapshot; the consumer
fresh-reads `person_profiles` from the CM entry options when it opens an intent (no cached copy to discharge). Profiles
reach music following through the repair's `set_preference_provider` (M1), not a second path.

### 5.2 Arrival music

- **Intent.** `_handle_person_arriving` opens one intent per person in the `MusicFollowing` engine (one owner;
  `_arrival_intents: dict[person_entity, Intent]`, RAM, cleared at teardown) for `ARRIVAL_MUSIC_WINDOW_S` when: master
  on; profile `arrival_music` on with media set; tracked resident; music following enabled and not in observation mode.
  First source wins and is recorded. Any F5 source may open it; `camera_egress` exists only after a GPS-led
  confirmation of the person's own phone (step 7 §5.5), so a face or vision input alone never opens one (M2).
- **Where the check runs (H1).** At the TOP of `_on_person_transition`, before the `_enabled_persons` return
  (`:511-518`) and the confidence return (`:521-527`), the engine calls `_arrival_music_check(transition)`. That check
  has its own gates and never reads the transfer confidence, because the first transition after hours away is
  classified `separate` / no history at 0.50 (`transitions.py:275-381`), below `MIN_CONFIDENCE` 0.6. Its room input is
  the BLE room the transition reports, under the BLE/path gate that repair D1 installs in place of the dwell gate
  (prerequisite, §10); the arrival check applies that gate's room test only, not its transfer confidence. Transfers
  continue below unchanged.
- **Start gates**, each a counted outcome: target = first room in `rooms` (or any room when empty) with a primary
  player; quiet hours or house `sleep` / `waking`; room paused (`room_automation_paused`); primary unavailable; **playing
  check (M3):** skip if the native primary OR its mapped MA entity reads `playing`, or either is a member of a playing
  group; **occupied check (M4):** skip if, before this person's entry, the room coordinator read occupied, any other
  tracked person is in it, or a camera person body is in the room with no tracked occupant (comfort-class awareness
  view), unless `ARRIVAL_MUSIC_ALLOW_SHARED_ROOM`; one start per person per `ARRIVAL_MUSIC_MIN_GAP_S`.
- **Action** with `ura_ctx_kwargs`: volume = `arrival_volume` x room scale, clamped 0..1, then MA `play_media` on the
  MA entity, native `media_player.play_media` when the player has none. No bonus joins.
- **Verify on ground truth:** the entity played reads `playing` within `ARRIVAL_MUSIC_VERIFY_S` -> `started`, stamp
  `{person, native_player, ma_entity, media_content_id (of the entity played), started_at}`; else `start_failed`.
  Outcomes: `started`, `start_failed`, `skipped_quiet`, `skipped_sleep`, `skipped_paused`, `skipped_playing`,
  `skipped_occupied`, `skipped_shared`, `skipped_no_player`, `skipped_gap`, `window_expired`; one decision-log line, one
  `arrival_music` episode each; outcomes in the NM digest (L5).
- **Reversal:** a non-URA pause, stop or volume 0 on either entity within `ARRIVAL_MUSIC_REVERSAL_S` counts `reversed`.

### 5.3 Departure pause

For a person with a live stamp, the first of: a named exit at >= 0.75 (step 7 `departure_candidate` or `attached` exit,
via `get_last_crossing`) or their raw `person.*` `home -> not_home | zone` edge. Pause the stamped entity
(`media_player.media_pause`, URA context) only when it still plays the stamped `media_content_id` (read on that same
entity; the other entity of the pair must not be playing something else), the room coordinator reads not occupied,
and no tracked person is in the room. Else counted `departure_kept_*`. The stamp is RAM: a restart loses it, counted
`departure_stamp_lost_restart` at setup from the last `started` episode with no pause (L2). Not built (decomposed):
last-resident arming (stays parked, identity arming is escalation, manual §5.5(a)); HVAC setback (AWAY does it);
lights off (vacancy does it).

### 5.4 Named arrivals and the count follow-up (P2-D9)

Built as in `PLANNING_crossing_vision.md` §5, under that plan's own review bar, with three rules: (1) the follow-up
calls `notify_arrival_followup(crossing_ref, kind="count", names=..., guests=n - k)`; `test_r7_and_perimeter_followup_same_crossing`
asserts arrival sends <= 3 (original + 2 amends), perimeter unchanged; (2) a name renders only at the notification
class (F3 attach >= 0.75 or a step-7 confirmation); window NVR face names count toward `k` but render "not
recognised"; (3) the count follow-up sends only while `notification` is in the active `CROSSING_VISION_CONSUMER_CLASSES`
(census CD4 flip on measured bars). Until then the record is written and displayed and step 7's name follow-ups go out.

## 6. Falsifiable invariants

- **INV-V6-NO-FACE-ALONE.** Every `started` traces to a `geofence` / `ble` signal or a step-7 GPS-led confirmation.
- **INV-V6-ARRIVAL-REACHES.** For any arrival (any source) followed within the window by a BLE transition into an
  eligible empty room with an idle player outside quiet hours, the outcome is `started`, whatever that transition's
  classified confidence or the person's transfer enablement. Break it with the 4-hours-away first-room case.
- **INV-V6-NEVER-INTERRUPT.** URA never starts on a room whose native player or MA entity is playing, and never pauses
  playback it did not start.
- **INV-V6-OCCUPIED.** No start into a room that was occupied (room sensors, tracked person, or camera body) before
  the person's entry, with the shared-room knob off.
- **INV-V6-QUIET.** No start in quiet hours or house `sleep` / `waking`.
- **INV-V6-NO-RELOAD.** A People save never reloads the CM entry.
- **INV-V6-AWAY.** No step-8 path reads or writes an `infer()` input, the census trust view, or HVAC.
- **INV-V6-ONE-AMEND / NAME-BAR.** Arrival follow-ups go only through the amend function; no text names below 0.75.

## 7. Producer and consumer checks; sites

Producers: geofence `presence.py:5575`, `person_coordinator.py` ble, step-7 D2 `camera_egress`; fire check: 218 arrival
signals / 14 d. Forward trace: signal -> intent -> transition (top-of-function hook) -> start -> verify -> episode ->
departure -> pause. Trip-wires: `arrival_music_zero` (HIGH NM: >= 10 intents with a qualifying transition in 7 days and
0 `started`), `arrival_music_failing` (HIGH NM: >= 3 `start_failed` in 24 h). Review enumerates every `media_player.*` /
`music_assistant.*` call in both music files (all carry `ura_ctx_kwargs`), the amend function, and the options-save
path.

## 8. Deliverables

**D0 probe (P8-0).** Report committed with (a)-(c); go/no-go stated.

**D1 profile store, People step, profile sensor, no-reload admission.** Verify: a save takes effect on the next intent
with zero CM reloads (today a new CM key reloads the entry: discriminates); display-name and entity-id
`tracked_persons` key the same profile; suggestions never stored. Tests: `test_person_profile.py::test_profile_keyed_by_one_id_rule`,
`::test_people_save_in_reload_suppress_allowlist` (asserts both keys in `OPTIONS_RELOAD_SUPPRESS_KEYS` and
`_NO_LIVE_ATTR_KEYS`), `::test_people_save_no_reload_real_options_update` (drives the CM update listener; asserts no
`async_reload`), `::test_suggestions_never_stored`. Live: profile sensor shows saved fields; no reload in the log on save.

**D2 arrival music.** Verify: Oji not_home 4 h, geofence arrival, BLE `away -> master_bedroom` classified 0.50,
idle Sonos -> `started` (with the hook after the gates: `low_confidence`, nothing plays: discriminates). Native idle but
MA entity playing -> `skipped_playing`. Room occupied by an untracked guest body -> `skipped_occupied`. 23:30 ->
`skipped_quiet`. Sighting with no phone -> no intent. Tests: `test_arrival_music.py::test_first_room_after_hours_away_starts`,
`::test_check_runs_before_enabled_and_confidence_gates`, `::test_never_interrupts_native_or_ma_playing`,
`::test_untracked_occupant_skips`, `::test_quiet_and_sleep_skip`, `::test_face_alone_opens_no_intent`,
`::test_gps_confirmed_camera_egress_opens_intent`, `::test_verify_on_player_state`, `::test_ma_first_native_fallback`
(exact payloads), `::test_reversal_counted`, `::test_zero_fire_tripwire`. Config extremes: window 0; volume 0.05 / 1.0
with scale 1.5; `rooms` empty vs a room with no player. Live: first resident arrival after opt-in gives `started`
(music audible) or a named skip.

**D3 departure pause.** Verify: named exit at 0.9, stamp live, room empty -> pause; another person -> kept_shared;
track changed -> kept_not_ours; restart in between -> `departure_stamp_lost_restart`. Tests:
`::test_departure_pauses_own_playback`, `::test_departure_never_pauses_others`, `::test_departure_on_tracker_edge`,
`::test_stamp_lost_restart_counted`. Live: first departure after a start gives a pause or a kept reason.

**D4 arrival record + count follow-up (P2-D9).** Crossing-vision tests plus `::test_count_followup_via_amend_function`,
`::test_low_confidence_names_render_unrecognised`, `::test_count_followup_dark_until_f_notify`. Live: one
`crossing_vision_arrival` row with n, k, `guests_unnamed`; `get_last_arrival_record` returns it.

**D5 episodes.** `arrival_music` in `MEMORY_EPISODE_TYPES` and `MEMORY_WRITER_BACKED_EPISODE_TYPES` (exempt with reason
when the master is off).

**D6 docs, same commit.** `MUSIC_FOLLOWING.md` arrival section; manual §5.5 comfort row; presence state of play §1
`SIGNAL_PERSON_ARRIVING` consumers (music no longer a no-op); CLAUDE.md 6.0.0 definition (on §12 Q2 yes); repair plan
D7 item 3 amendment (§10).

Mutation drills (RED then restore): move the hook below the confidence return; drop the MA-entity playing check; drop
the occupied check; remove `person_profiles` from the allowlist; let a sighting open an intent; pause without the
`media_content_id` match; bypass the amend function; render a 0.6 name.

## 9. Knobs

| Knob | Default | Rung | Why / kill |
|---|---|---|---|
| `CONF_MUSIC_ON_ARRIVAL_START` (REUSED) + `switch.ura_music_arrival_start` | on | 2 + 3 | House master; off = no intents |
| profile `arrival_music` / `arrival_media` / `arrival_volume` / `rooms` | off / empty / 0.30 / empty | 2 (People) | Per-person opt-in; ON for anyone who sets it |
| `ARRIVAL_MUSIC_WINDOW_S` | 900 (P8-0 sets) | 1 | 0 = never start |
| `ARRIVAL_MUSIC_MIN_GAP_S` | 3600 | 1 | No re-start on a door bounce |
| `ARRIVAL_MUSIC_VERIFY_S` / `_REVERSAL_S` | 20 / 120 | 1 | Ground-truth windows |
| `ARRIVAL_MUSIC_ALLOW_SHARED_ROOM` | False | 1 | Never start on someone already there |
| `ARRIVAL_MUSIC_DEPARTURE_PAUSE` | True | 1 | False = no departure action |
| Trip-wire thresholds | 10 / 7 d; 3 / 24 h | 1 | 0 = off |

## 10. Dependencies, seams, sequence

Must ship first: step 6 census deconfliction (legal class set; ledger term `n`); step 7 (amend function, confirmed
names, `camera_egress`, `departure_candidate`); read API ship 1 (shipped v5.108.21); MUSIC-FOLLOWING-TRANSFER-REPAIR-1
D0, **D1** (BLE/path gate replacing the dwell gate; itself blocked on BERMUDA-DISTANCE-SENSORS-DEAD-1, so the
re-based gate there must use live inputs), D3, D4, D5, D6, **D7** (`set_preference_provider`). **Repair-plan amendment
(arc rule 6, applied to `PLANNING_music_following_repair.md` before the repair ships):** D7 item 3 keeps
`music_on_arrival_start` as the arrival master in the form, relabelled, instead of retiring it.
**F-NOTIFY:** step 7 meets the identity half; the count follow-up stays dark until the CD4 flip; v6.0.0 does not wait
for it (§12 Q4). AI-ROOM-RULES-TRUST-REPAIR-1 shares the observability pattern only. Arc map M11 updated at approval.

## 11. Tier (operator question, §12 Q1)

Recommended Tier 2-DB: new actuation keyed on identity across presence and music, a new episode type, a config-flow
step; comfort class, reversible, no house-state, security or energy reach. The arc map pencilled the profile at Tier 3;
P2-D9 keeps the crossing-vision plan's own review bar. Reviews: one adversarial plan re-review plus framing G; three
framing-disjoint code reviews (A gates and payloads; B integration, restart, options save, listener lifecycle; C
per-site mutation). Release v6.0.0 at deploy.

## 12. Open operator questions (recommended defaults)

1. Tier for step 8? Default Tier 2-DB (§11); P2-D9 at its own plan's bar.
2. Redefine 6.0.0 in CLAUDE.md as step 8 (named arrivals + arrival music + departure pause), quoting "step 8 is fine"?
   Default yes, in the D6 commit; the guest-gate item stays parked.
3. Park the profile extras (bathroom, welcome scene, "automate my entries" beyond music, per-room / time-of-day
   playlists) with trigger "two weeks of `arrival_music` episodes with reversal < 10 percent, or an operator ask"?
   Default yes (charter rule 4 needs the yes).
4. Ship v6.0.0 before the F-NOTIFY flip? Default yes.
5. Shared rooms (e.g. the master with Ezinne there)? Default skip.
6. Departure pause on? Default on, pause not stop.

## 13. Non-goals

Per-person temperature (cut); welcome scenes; guest-gate door identity; predictions filling profile fields; music for
guests or untracked people; transfers (music repair owns them); any security, lock, HVAC or house-state consumer;
Protect names; interior vision (step 9); a trial or shadow stage.

## 14. Plan completion tracking

Built here: profile slice, arrival music, departure pause, P2-D9 wiring, episodes, docs. Pending operator yes (§12 Q3):
the profile extras, carded with the trigger above. DEPARTURE-ACTIONS-1: only the pause; the rest decomposed in §5.3.
Count follow-up flip is census CD4.

## 15. Review disposition (`PLANREVIEW_identity_actions_v6.md`)

H1 -> §5.2 top-of-function check, repair D1 prerequisite, INV-V6-ARRIVAL-REACHES, D2 first-room test. H2 -> §5.1
allowlist + fresh read, INV-V6-NO-RELOAD, D1 tests. M1 -> §10 D7 prerequisite and repair amendment. M2 -> §3, §5.2 GPS-led
wording. M3 -> §5.2 / §5.3 both entities. M4 -> §5.2 occupied check (room, tracked, camera body), INV-V6-OCCUPIED. M5 ->
§11, §12 Q1. M6 -> §1, §12 Q2, D6. L1 -> §2 rows. L2 -> §5.3 counter. L3 -> §4 all residents. L4 -> §5.1 privacy note.
L5 -> §4 (a), digest outcome. Framing G: trial stage dropped (§1, §13); extras to §12 Q3.
