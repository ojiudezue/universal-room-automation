# PLANNING: identity actions (arc step 8): named arrivals, the person profile, arrival music, welcome scene, departure pause

Cards: PERSON-PROFILE-PREFERENCES-1 (whole card, no longer a first slice), VISION-CROSSING-ANALYSIS-1 (P2-D9 arrival
record and count follow-up, built as specified in `PLANNING_crossing_vision.md` §5), DEPARTURE-ACTIONS-1 (first
consumer). Arc: identity / vision / census, step 8 of `ARC_identity_vision_census_map.md` §4. Charter:
`ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md` (goals section, 2026-11-14 additions, drift #17).
Status: rev 3, a clean rewrite after the operator's 2026-11-14 decisions. Rev 2 (reviewed in
`docs/reviews/plan-review/PLANREVIEW_identity_actions_v6.md`) is archived at
`docs/planning/archive/PLANNING_identity_actions_v6_rev2.md`, NOT A BUILD SPEC. §15 lists every change from rev 2 for
the equivalence review. Author ura-planner, 2026-11-14.

Read first, completely (CLAUDE.md): `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`,
`IDENTITY_FUSION_CAMERAS_MANUAL.md`, `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (to confirm no HVAC input changes; per-person
HVAC targeting already exists as `zone_persons`, `hvac.py:7198-7236`), `CONTRACT_person_awareness_layer.md`. No
corrections-ledger claim is re-asserted. This rev was written from the rev 2 reading plus the contract (§2.4a, §2.5,
§4, §5, §7); the builder re-reads all five.

## 1. What makes 6.0.0 true

Operator decisions, 2026-11-14, verbatim where quoted (card PERSON-PROFILE-PREFERENCES-1 `operator_2026_11_14_step8`):

- Tier 2-DB: "Agree with q1 and 2 and 4". 6.0.0 is redefined in CLAUDE.md as step 8 (Q2). v6.0.0 ships before the
  F-NOTIFY flip (Q4). Departure pause: "Departure pause is fine" (on, pause not stop).
- Profile extras are in, not parked: "Don't want to defer too much. Music is rarely exercised so it's not a good
  trigger. It's a really cool novelty. Demos well. When needed it's beautiful." "And the exclusion is fine":
  per-person temperature stays cut.
- Shared rooms: "don't do it when someone is already in that room including in your own room. Shares spaces, likely
  same." No shared-room exception; the rule applies to the welcome scene too.
- Music following's 8 ft distance gate is dropped. Arrival music uses the layer's room read, never a distance.
- Config: "Use form field hiding in 11.0 to keep config compact as needed."

Step 8 therefore delivers, keyed to a recognised resident:

1. **Named arrivals.** Step 7 names confirmed arrivals; this plan adds the arrival record (n came in, k recognised) and
   its count follow-up through the same amend function.
2. **The person profile.** My rooms (bedrooms, bathrooms; a room listed by two people is shared by them, e.g. the
   master), my music (a default, optionally varied by time of day and by room), my volume, my welcome scene, and which
   entry actions I want automated.
3. **Arrival music.** The resident walks into one of their rooms that has a speaker; their music starts at their
   volume if nobody else is in the room and it is not quiet hours.
4. **Welcome scene.** Same trigger and gates, applies their scene in that room.
5. **Departure pause.** When they leave, music URA started for them pauses if the room is now empty.

All of it ships ON on day 1 for every resident who opts in on the People step; there is no trial stage (memory
`feedback_no_shadow_mode_day1_correct`). The guest gate on door identity stays parked (GUEST-GATE-DOOR-IDENTITY-1).

Charter goals served: "assist arrivals accuracy and personalization"; "it's going to lead to OC and personalization and
Ai enhancements for rooms". Hard constraint "I need away to be fast acting": nothing here reads or writes house state
(INV-V6-AWAY). Layer constraint ("consumers can read and producers can feed"; "no leaks"): step 8 produces no fact,
reads F5 only through `dispatch_person_arriving` (layer ship 3, G4) and the person's room only through the layer's one
BLE-in-room read (G6). Short-clip constraint: untouched (no frame source here).

### 1.1 Drift check (ura-arc rule 7)

| Operator said | Where it drifted | Correction | Status |
|---|---|---|---|
| "Don't want to defer too much... not a good trigger" | Rev 2 parked the profile extras behind two weeks of arrival-music episodes (drift #17) | Rooms, owners, playlists by time and room, per-action opt-in, welcome scene are D1-D4 here | Fixed in rev 3 |
| "don't do it when someone is already in that room including in your own room" | Rev 2 had `ARRIVAL_MUSIC_ALLOW_SHARED_ROOM` as a knob with an open question | Knob removed; occupied rule has no exception and covers the scene | Fixed |
| 8 ft gate dropped | Repair plan keeps `CONF_MF_HIGH_CONFIDENCE_DISTANCE` (`PLANNING_music_following_repair.md:42, :138, :316`) | Arrival path never reads distance; repair plan amendment §10 | Fixed here; amendment pending on that plan |
| "consumers can read and producers can feed" | Rev 2 subscribed to raw `SIGNAL_PERSON_ARRIVING` and read `get_persons_in_room` | Reads go through G4 / G6 (layer ship 3) | Fixed |

## 2. Institutional context verified

Greps run 2026-11-14 on develop (`109ef2c9`). Rev 2 greps carried and re-checked where a row depends on them:
`SIGNAL_PERSON_ARRIVING`; `music_on_arrival|play_media|quiet|_enabled_persons|MIN_CONFIDENCE`;
`person_profile|PERSON_PREF|per_person` in `const.py` / `config_flow.py` (0 hits). New this rev:
`time_of_day|day_part|daypart|morning` (bayesian bins, notification wording only); `CONF_LIGHT_SCENE_|LIGHT_SLOT_`;
`owner|room_owner|assigned_person` in `const.py` (fan / entity owners only; no person-owns-room key);
`ROOM_TYPE_BATHROOM`; `MediaSelector` in `config_flow.py` (0 hits); `get_person_location|dispatch_person_arriving`;
`visible` in the test venv's `homeassistant/data_entry_flow.py` (0 hits); the HA core 2026.11.1 source (below).

| Piece | Verdict | Where |
|---|---|---|
| F5 intake | REUSED via layer ship 3 G4 | `signals.dispatch_person_arriving` (contract §2.5, `CONTRACT_person_awareness_layer.md:184`); the handler body is today's no-op `MusicFollowingCoordinator._handle_person_arriving` `domain_coordinators/music_following.py:549`, subscribed `:281` |
| Person's room | REUSED via layer G6 | `persons_in_room(room)` / `get_person_location(name)` (contract §2.4a, §4.1 `:281`); today `PersonCoordinator.get_person_location` `person_coordinator.py:1992` |
| Person room transitions | REUSED, new hook at the top | `MusicFollowing._on_person_transition` `music_following.py:473` (enabled-persons return `:511-518`, confidence return `:521-527`, `MIN_CONFIDENCE` 0.6 `:115`) |
| Room primary player; MA map; MA-first play; outcomes; decision log; episodes; preference hook | REUSED from MUSIC-FOLLOWING-TRANSFER-REPAIR-1 D0, D3-D7 | `PLANNING_music_following_repair.md` §6; `CONF_ROOM_MEDIA_PLAYER` `const.py:106`; `set_preference_provider` (`:279`) |
| Volume scale | REUSED | `CONF_ROOM_MEDIA_VOLUME_SCALE` `const.py:4250` |
| Quiet hours | REUSED | `NotificationManager.is_quiet_hours_active` `notification_manager.py:4772` |
| Time-of-day parts | REUSED | `lighting/resolver.py:309` `resolve_slot(is_sleep_hours, is_dark)` -> `LIGHT_SLOT_DAY` / `_EVENING` / `_SLEEP` (`const.py:1210-1212`); the room's own slot, already used for `CONF_LIGHT_SCENE_DAY/EVENING/SLEEP` (`config_flow.py:14078-14095`). Not the bayesian six bins (`bayesian_predictor.py:67`), which are a learning axis, not a user concept |
| Bathroom rooms | REUSED | `CONF_ROOM_TYPE` `const.py:457`, `ROOM_TYPE_BATHROOM` `:585` (filters the bathroom picker) |
| Scene picker pattern | REUSED | `EntitySelector(domain="scene")` `config_flow.py:14081` |
| Light write marking / manual hold | REUSED | `ura_context.URA_LIGHT_WRITE_DOMAINS` (includes `scene`, `const.py:1220` note); `ActuatorReconciler._note_manual_light_change` `actuator_reconciler.py:500` skips URA context (`:516`), light manual hold honoured `:673-681` |
| Room occupancy (any body) | REUSED | room coordinator `data[STATE_OCCUPIED]` (`coordinator.py:3613`); awareness count `get_house_census(view_for_class("comfort"))` (`presence.py:5952, :5984`) |
| Comfort class | REUSED | `CONSUMER_CLASS_COMFORT` `const.py:6498` |
| URA context, person ids | REUSED | `ura_ctx_kwargs` `ura_context.py:80`; `tracked_person_entity_id` `person_ids.py:25`, `display_of` `:56` |
| Arrival master toggle | REUSED (un-retire) | `CONF_MUSIC_ON_ARRIVAL_START` `const.py:4864` |
| Options save without reload | REUSED | `OPTIONS_RELOAD_SUPPRESS_KEYS` `__init__.py:7553`, `_NO_LIVE_ATTR_KEYS` `:7406` |
| Crossing / arrival record; amend function | REUSED | `get_last_crossing` `presence.py:6009`, `get_last_arrival_record` `:6021`; `notify_arrival_followup` (`PLANNING_egress_direction_aware_identity.md` §5.4) |
| Episodes | REUSED pattern | `MEMORY_EPISODE_TYPES` `const.py:6204`, `MEMORY_WRITER_BACKED_EPISODE_TYPES` `:6263` |
| Room suggestions | REUSED | `person_visits` `database.py:995`; `PatternLearner.predict_next_room` `pattern_learning.py:143` |
| Conditional fields | REUSED (HA core) | `data_entry_flow.Required/Optional(..., visible=...)`, core 2026.11 (verified below) |
| Media picker | REUSED (HA core) | `selector.MediaSelector` (test venv `helpers/selector.py:1142-1176`) |
| `person_profiles` store, People step, profile sensor | NEW | 0 hits; only `async_step_person_tracking` `config_flow.py:4804` exists |
| Room ownership | NEW, derived | No person-owns-room key exists. Owners are derived from profiles (a room's owners = the people who list it), so there is one store, not a room-entry field plus a profile field |
| Arrival intent, room-entry check, welcome-scene apply, departure pause | NEW in the `MusicFollowing` engine | no arrival-start code exists |

**HA conditional fields, verified against core 2026.11.1 source** (`homeassistant/data_entry_flow.py`,
`homeassistant/helpers/field_visibility.py`, and the 2026-10-21 contributors post):

- `data_entry_flow.Required` / `Optional` (subclasses of `probatio.Required` / `Optional`) take
  `visible: bool | FieldCondition | list[FieldCondition] | None`. A list is ANDed.
- `FieldCondition` = `{"field": str, "operator"?: eq | not_eq | in | not_in | exists | not_exists, "value"?: ...}`.
- A field whose condition fails is not rendered, is treated as optional, and its value is dropped from the submitted
  data (`_strip_hidden_fields`). Visibility resolves iteratively, so a chain works: hiding A hides B when B's condition
  reads A.
- `section` itself takes no `visible`, but fields inside a section may carry one (the serializer and the stripper both
  recurse into sections). Whether a condition can name a field in a different section is not stated in what I read;
  this plan keeps every condition and its controlling toggle in the same section, which needs no answer.
- The test venv is HA 2026.2.3: `data_entry_flow` there has no `Required` / `Optional` markers and no `visible`.
- Unverified, a build spike (D1 B0): mixing `data_entry_flow.Optional` markers inside URA's existing `vol.Schema`
  bodies on 2026.11 (core types `data_schema` as `probatio.Schema`). URA's forms render live on 2026.11.1 today, so
  `vol.Schema` is accepted; the spike confirms the new markers serialize their `visible` inside it.

**MediaSelector, verified in the test venv (2026.2.3) source only:** config keys `accept` (media classes) and
`multiple`; value `{entity_id?, media_content_id, media_content_type}`; without `accept` the form shows a player picker
and browses that player's media tree; with `accept` there is no entity. Context key `filter_entity` lets another
EntitySelector field on the form choose the player. There is no integration filter, so it cannot be scoped to Music
Assistant by config. Whether MA's player browse tree exposes playlists, radio, artists and albums with ids that play
on a different MA player is a live check (D1 B0), not a fact here.

Prior plans read: rev 2 and its plan review; `PLANNING_crossing_vision.md` §2-§8; contract (all); music repair (all);
egress direction-aware §5.4-§5.5; `AUDIT_pre_arrival_inventory_and_precool_standdown.md` (218 arrival signals / 14 d).
Card origin (PERSON-PROFILE-PREFERENCES-1, 2026-11-08): "a place to record personal preferences for identified home
people ie bedroom, bathroom, playlist, automate my entries vs not, etc. bedrooms may have a designated owner or owners
(master) so there can be a welcome scene"; predictions "as SUGGESTIONS... the operator confirms". Memory:
`project_hyper_personalization_person_profile`, `reference_identity_model_f1_f5`, `feedback_fire_check_and_forward_trace`,
`feedback_no_shadow_mode_day1_correct`, `feedback_parent_entry_reload_watchdog_hazard`, `feedback_portability_imperative`,
`feedback_registry_not_name_guessing`. Config-first: no setting starts music or a scene on a person's arrival.

## 3. Facts and consumer classes

Consumes F5 through `dispatch_person_arriving` (sources `geofence`, `ble`, and from step 7 `camera_egress`, dispatched
only for GPS-led confirmations of the person's own phone); F4 BLE room per person through G6; F1 `person.*` departure
edge; F2 awareness count (comfort class, `view_for_class`); F3 named exits and the arrival-record attribute. Produces no
fact. Arrival music, welcome scene, departure pause: **comfort**. Count follow-up: **notification** (names >= 0.75).
Profile sensor and room suggestions: **display**. Access, security, house state: none.

## 4. Measure first (D0, read-only, one probe, before build)

14 days of recorder + URA DB (`person_visits`, activity `pre_arrival` rows, media player and light history), per
resident with at least one room that has a primary player:
(a) arrivals per day by source; lag from the F5 signal to the first BLE room change into a room with a player; share
where that room's native player or MA entity was playing, the room was already occupied, or quiet hours were on; and
how often the first such room reached within 900 s was a plausible "own" room (from `person_visits` dwell). Sizes
`ARRIVAL_WINDOW_S`.
(b) departures per day per resident; how often the arrival room was empty within 5 min after.
(c) day / evening split of those arrivals under `resolve_slot` (tells whether per-part picks matter).
(d) after step 7 ships, the share of entries named at the crossing or confirmed.
**Go/no-go:** the operator ruled that a low fire rate is not a reason to defer ("rarely exercised... not a good
trigger"), so D0 sizes windows and seeds suggestions; it does not gate the build. A number that makes a gate look
wrong (for example most first rooms are not own rooms) goes to the operator with the number (charter rule 3).

## 5. Design

### 5.1 The profile store

CM entry options key `person_profiles`, keyed by `tracked_person_entity_id`:

```
"person.oji": {
  "rooms_bedroom":  ["<room entry_id>", ...],     # My bedroom(s)
  "rooms_bathroom": ["<room entry_id>", ...],     # My bathroom(s); picker lists ROOM_TYPE_BATHROOM rooms
  "auto_music": bool,                             # Automate my entries: play my music
  "auto_scene": bool,                             # Automate my entries: welcome scene
  "music_default": {"media_content_id": str, "media_content_type": str},
  "music_volume": float,                          # 0.05-1.0, default 0.30
  "music_vary_time": bool,
  "music_day":     {...} | absent,                # falls back to music_default
  "music_evening": {...} | absent,
  "music_vary_room": bool,
  "music_by_room": {"<room entry_id>": {...}},    # own rooms only; falls back to the time pick, then default
  "welcome_scene": "scene.<id>" | absent,
}
```

- **Rooms are stored by room config entry_id** (registry, not names; resolved to the room name at use). "My rooms" =
  bedrooms ∪ bathrooms.
- **Owners are derived, never stored twice:** `room_owners(room) = {p : room in p.rooms}`. A room with two owners is
  shared (the master). Shared ownership changes nothing in the gates; it only means either owner may trigger there.
- **Toggle-off semantics are the consumer's job.** On 2026.11 a hidden field is dropped from the submission; on older
  HA it is submitted. Either way the save merges into the stored profile, and the consumer reads a dependent field only
  when its toggle is on (`music_day` only when `music_vary_time`, and so on). Stale values under an off toggle are
  harmless and come back if the toggle is turned on again. One rule, both HA versions.
- **No reload.** `person_profiles` and `music_on_arrival_start` join `OPTIONS_RELOAD_SUPPRESS_KEYS` and
  `_NO_LIVE_ATTR_KEYS` in the same commit; the consumer fresh-reads the profile when an intent opens. Profiles reach
  music following through the repair's `set_preference_provider`, not a second path.
- **Display:** `sensor.ura_person_profile_<slug>` (state = number of automated actions on; attributes: rooms by name,
  owners of shared rooms, music labels, scene, `last_arrival_action`; attributes unrecorded). Visible to every HA user,
  accepted for this household.

### 5.2 The People step (CM options), mock

Menu entry "People" -> pick a tracked person (SelectSelector of `CONF_TRACKED_PERSONS`, shown by display name) ->
the form below -> if "Different music per room" is on and the person has rooms, a second step "Music by room".

```
People: Oji                                                    [description: "Suggested rooms from the
                                                                last 30 days: Master Bedroom (61%),
                                                                Master Bath (14%)."  display only]
▾ My rooms
    My bedroom(s)        [Master Bedroom ×]                     SelectSelector, multiple, URA rooms
    My bathroom(s)       [Master Bath ×]                        SelectSelector, multiple, bathroom rooms
▾ Automate my entries
    Play my music when I walk into my room     [on]             BooleanSelector  auto_music
    My music             [Music Assistant ▸ Playlists ▸ ...]    MediaSelector    visible: auto_music == True
    My volume            [0.30]                                 Number 0.05-1.0  visible: auto_music == True
    Different music by time of day             [off]            Boolean          visible: auto_music == True
      Daytime music      [ ... ]                                MediaSelector    visible: music_vary_time == True
      Evening music      [ ... ]                                MediaSelector    visible: music_vary_time == True
    Different music per room                   [off]            Boolean          visible: auto_music == True
    Set my welcome scene when I walk in        [off]            BooleanSelector  auto_scene
    My welcome scene     [scene.master_welcome]                 EntitySelector(domain=scene)
                                                                                 visible: auto_scene == True
```

All toggles and the fields they control sit in the same section ("Automate my entries"), so no condition crosses a
section. The time-of-day chain is two conditions: `[{"field": "auto_music", "value": True}, {"field":
"music_vary_time", "value": True}]` (AND), and the iterative resolution hides both picks when music is off.

"Music by room" step: one optional MediaSelector per room in My rooms that has a primary player (rooms without one are
named in the description: "Master Bath has no speaker"). Blank = use the time-of-day or default pick. A form cannot
grow fields from a selection made on the same form, so a variable room list is a sub-step built from the saved rooms.
It is short in practice (1-3 rooms per person).

Labels follow the style guide (short phrase, plain words). Field count with everything off: 5 visible.

**Portability (older HA, and the test venv).** One helper, `_cond(key, cond, default)`, in `config_flow.py`:

- If `homeassistant.data_entry_flow` has `Optional` and its `__init__` accepts `visible` (checked once with
  `inspect.signature`), return `data_entry_flow.Optional(key, default=..., visible=cond)`.
- Else return `vol.Optional(key, default=...)`. Every field shows; the descriptions say "used when X is on". Nothing
  else changes, because the consumer already ignores fields under an off toggle (§5.1).

Tests run on 2026.2.3 and exercise the fallback path for real. The `visible` path gets: a unit test of `_cond` against
a stub marker class whose `__init__` accepts `visible` (asserts the condition passed through unchanged), and a
serialization test marked `skipif` HA < 2026.11 that renders the form and asserts `visible` on the expected fields.
Live (2026.11.1) is the authority: the form shows 5 fields with everything off.

### 5.3 How a playlist is specified and chosen

- **Picking.** `MediaSelector()` with no `accept`. The person picks a player (any MA player; the description says
  "pick any Music Assistant speaker to browse your library"), browses, and picks a playlist, radio station, artist or
  album. URA stores `media_content_id` + `media_content_type` and drops `entity_id`: the pick is the item, not the
  player it was browsed on. This is the pair MA `play_media` and native `media_player.play_media` both take.
- **Fallback if the live spike fails** (MA ids not playable on another MA player, or the browse tree lacks playlists):
  the MediaSelector stays for native players, and a text field "or paste a Music Assistant URI" (e.g.
  `library://playlist/12`) is added under the same `visible` condition. Decided in D1 B0, recorded in the README.
- **Choosing at play time** (one pure function, `pick_media(profile, room_id, slot)`):
  1. `music_by_room[room_id]` if `music_vary_room` and set;
  2. else `music_day` / `music_evening` for the room's `resolve_slot(...)` if `music_vary_time` and set;
  3. else `music_default`.
  The slot is the target room's own (its sleep clock, house `sleep`, its darkness), so music and the room's lighting
  scenes agree on what "evening" means. The `sleep` slot never plays (quiet gate), so it has no pick.
- **Volume:** `music_volume` x the room's `CONF_ROOM_MEDIA_VOLUME_SCALE`, clamped 0..1. Per person, not per room.

### 5.4 Arrival intent and the room-entry check

- **Intent.** The F5 handler opens one intent per person (`_arrival_intents`, RAM, one owner: the `MusicFollowing`
  engine, cleared at teardown) for `ARRIVAL_WINDOW_S` when: master `music_on_arrival_start` on; the person is a tracked
  resident with `auto_music` or `auto_scene` on; music following is enabled and not in observation mode. First source
  wins and is recorded. A face or vision input alone never opens one: `camera_egress` reaches F5 only after a GPS-led
  confirmation of the person's own phone (step 7 §5.5), and `camera_face` arrivals are ignored by this consumer.
- **Where the check runs.** At the top of `_on_person_transition`, before the `_enabled_persons` return (`:511-518`)
  and the confidence return (`:521-527`), the engine calls `_arrival_check(person, room)`. It never reads transfer
  confidence (the first transition after hours away classifies at 0.50, below `MIN_CONFIDENCE` 0.6) and never reads a
  BLE distance. Its room input is the person's room from the layer's one BLE-in-room read (G6), confirmed by
  `persons_in_room(room)` containing the person when the check runs. Transfers continue below unchanged.
- **Target.** The room entered, if it is in the person's rooms. A room outside their rooms closes nothing; the intent
  waits for an own room until the window ends. A person with no rooms set gets no arrival action (counted
  `skipped_no_rooms`); the People step says so.

### 5.5 Shared gates (music and scene)

Checked once per entry, each a counted outcome, in this order:
1. quiet hours or house `sleep` / `waking` -> `skipped_quiet` / `skipped_sleep`;
2. room automation paused -> `skipped_paused`;
3. **occupied** -> `skipped_occupied`: before this person's entry the room coordinator read occupied, or any other
   tracked person is in it (G6), or a camera person body is there with no tracked occupant (comfort awareness view).
   Ownership does not matter: a co-owner already in the master blocks it. No knob, no exception;
4. one action set per person per `ARRIVAL_MIN_GAP_S` -> `skipped_gap`.

Then each action runs its own checks:

- **Music** (`auto_music` on, a pick resolves): primary player available (`skipped_no_player`); playing check, native
  primary OR its MA entity reads `playing` or is in a playing group -> `skipped_playing`; play MA-first, native when no
  MA entity, with `ura_ctx_kwargs`; verify the entity played reads `playing` within `ARRIVAL_VERIFY_S` -> `started`
  with stamp `{person, room, native_player, ma_entity, media_content_id, started_at}`, else `start_failed`. A
  non-URA pause, stop or volume 0 within `ARRIVAL_REVERSAL_S` -> `reversed`.
- **Welcome scene** (`auto_scene` on, scene set and available, else `scene_skipped_unavailable`): `scene.turn_on`
  with `ura_ctx_kwargs`, after the room's own entry lighting has run (ordered: the scene call waits for the room's
  entry light action or `ARRIVAL_SCENE_SETTLE_S`, whichever first). Because a URA-context write is not a manual change
  (`actuator_reconciler.py:516`), the reconciler would pull the lights back to the computed level on its next pass.
  The scene therefore places the room's existing light manual hold (`automation.note_manual_light`, the path at
  `actuator_reconciler.py:523`) on the scene's lights, so it lasts like a person's own change and ends the way that
  hold ends (vacancy). Verify: at least one scene light changes state within `ARRIVAL_VERIFY_S` -> `scene_applied`,
  else `scene_failed`. Departure undoes nothing; vacancy turns lights off as today.

Music and scene outcomes are independent: a playing speaker skips music but not the scene.

### 5.6 Departure pause

For a person with a live music stamp, the first of: a named exit at >= 0.75 (step 7 `departure_candidate` or
`attached`, via `get_last_crossing`) or their `person.*` `home -> not_home | zone` edge. Pause the stamped entity
(`media_player.media_pause`, URA context) only when it still plays the stamped `media_content_id`, the other entity of
the pair is not playing something else, the room coordinator reads not occupied, and no tracked person is in it (G6).
Else `departure_kept_*`. The stamp is RAM; a restart loses it, counted `departure_stamp_lost_restart` at setup from the
last `started` episode with no pause. Not built: last-resident arming (escalation, manual §5.5(a)); HVAC setback (AWAY
does it); lights off (vacancy does it).

### 5.7 Named arrivals and the count follow-up (P2-D9)

As `PLANNING_crossing_vision.md` §5, at that plan's own review bar, with three rules: (1) the follow-up calls
`notify_arrival_followup(crossing_ref, kind="count", names=..., guests=n - k)`; arrival sends stay <= 3 per crossing
and perimeter is unchanged; (2) a name renders only at the notification class (>= 0.75 or a step-7 confirmation);
window NVR face names count toward `k` but render "not recognised"; (3) the count follow-up sends only while
`notification` is in the active `CROSSING_VISION_CONSUMER_CLASSES` (census CD4 flip). The record is written and
displayed before the flip.

## 6. Falsifiable invariants

- **INV-V6-NO-FACE-ALONE.** Every `started` / `scene_applied` traces to a `geofence` / `ble` F5 or a step-7 GPS-led
  confirmation.
- **INV-V6-ARRIVAL-REACHES.** For any arrival followed within the window by the person's G6 room becoming one of their
  rooms, empty, idle player, outside quiet hours, the music outcome is `started`, whatever the transition's classified
  confidence, the person's transfer enablement, or any BLE distance. Break it with the 4-hours-away first-room case and
  with a distance reading of 20 ft.
- **INV-V6-NEVER-INTERRUPT.** No start on a room whose native player or MA entity is playing; no pause of playback URA
  did not start.
- **INV-V6-OCCUPIED.** No music start and no scene into a room occupied before the person's entry (room sensors,
  another tracked person including a co-owner, or a camera body). There is no knob that disables this.
- **INV-V6-QUIET.** No music and no scene in quiet hours or house `sleep` / `waking`.
- **INV-V6-OFF-MEANS-OFF.** With a toggle off, nothing under it acts, whether the HA version hid and dropped its fields
  or kept them.
- **INV-V6-SCENE-STICKS.** A welcome scene is not reverted by the reconciler while the room stays occupied.
- **INV-V6-NO-RELOAD.** A People save never reloads the CM entry.
- **INV-V6-AWAY.** No step-8 path reads or writes an `infer()` input, the census trust view, or HVAC.
- **INV-V6-LAYER.** Step 8 reads F5 only via `dispatch_person_arriving` subscribers and person-in-room only via G6;
  the layer guard test (ship 3) covers the music files.
- **INV-V6-ONE-AMEND / NAME-BAR.** Arrival follow-ups only through the amend function; no text names below 0.75.

## 7. Producer and consumer checks; sites

Producers: geofence, BLE pre-arrival, step-7 `camera_egress`, all through `dispatch_person_arriving`. Fire check: 218
arrival signals / 14 d (AUDIT_pre_arrival); BLE room moves fire continuously. The repaired arrival path itself has
fired zero times (no-op handler), so it gets trip-wires: `arrival_action_zero` (HIGH NM: >= 10 intents with a
qualifying own-room entry in 7 days and 0 `started` + `scene_applied`), `arrival_music_failing` (HIGH NM: >= 3
`start_failed` in 24 h), `welcome_scene_failing` (same shape). Forward trace: F5 -> intent -> own-room entry (G6) ->
gates -> play / scene -> verify -> episode -> departure -> pause. Consumers of the new store: the music engine, the
profile sensor, the People step (suggestions), and later OC and AI room rules (read-only, through the profile sensor
or a `get_person_profile(person)` accessor on the engine; no second store). Site enumeration for review: every
`media_player.*` / `music_assistant.*` / `scene.turn_on` call in both music files (all with `ura_ctx_kwargs`), every
read of `person_profiles`, the amend function, the options-save path.

## 8. Deliverables

**D0 probe.** Report committed with (a)-(d). Live: n/a.

**D1 profile store, People step, sensor, no-reload, portability.** B0 spike first (live 2026.11.1 UI, recorded in the
README): `data_entry_flow.Optional` with `visible` inside URA's `vol.Schema`; MediaSelector browse through an MA player
and playback of the stored id on a different MA player; picks the §5.3 fallback if needed.
Verify: a save applies on the next intent with zero CM reloads; display-name and entity-id `tracked_persons` key the
same profile; suggestions never stored; owners derived (two people listing the master -> both are owners, no
room-entry field written). Tests: `test_person_profile.py::test_profile_keyed_by_one_id_rule`,
`::test_owners_derived_shared_master`, `::test_people_save_in_reload_suppress_allowlist`,
`::test_people_save_no_reload_real_options_update`, `::test_suggestions_never_stored`,
`::test_cond_helper_falls_back_without_visible` (runs on the venv), `::test_cond_helper_passes_visible` (stub marker),
`::test_people_form_visible_conditions` (skipif HA < 2026.11), `::test_room_step_one_field_per_player_room`,
`::test_toggle_off_ignores_stale_fields`. Live: form shows 5 fields with everything off, the music fields appear when
"Play my music" is ticked; profile sensor shows the saved fields; no reload in the log on save.

**D2 arrival music.** Verify: Oji not_home 4 h, geofence arrival, G6 room `master_bedroom` (classified 0.50,
distance 20 ft), idle Sonos -> `started` (with the hook below the gates, or a distance gate on the path: nothing
plays, `low_confidence` / `ble_too_far`: discriminates). Native idle but MA playing -> `skipped_playing`. Ezinne
already in the master -> `skipped_occupied`. Untracked camera body -> `skipped_occupied`. 23:30 -> `skipped_quiet`.
Hall (not his room) then master -> starts in the master. Evening slot with `music_vary_time` -> evening pick; with the
toggle off and a stale evening pick stored -> default. Tests: `test_arrival_music.py::test_first_room_after_hours_away_starts`,
`::test_check_runs_before_enabled_and_confidence_gates`, `::test_no_distance_read_on_arrival_path`,
`::test_only_own_rooms_trigger`, `::test_never_interrupts_native_or_ma_playing`, `::test_coowner_present_skips`,
`::test_untracked_occupant_skips`, `::test_quiet_and_sleep_skip`, `::test_face_alone_opens_no_intent`,
`::test_gps_confirmed_camera_egress_opens_intent`, `::test_pick_media_precedence`, `::test_slot_from_room_resolve_slot`,
`::test_verify_on_player_state`, `::test_ma_first_native_fallback`, `::test_reversal_counted`, `::test_zero_fire_tripwire`.
Config extremes: window 0; volume 0.05 / 1.0 with scale 1.5; rooms empty; own room with no player.
Live: first opted-in arrival gives `started` (music audible) or a named skip in the decision log.

**D3 welcome scene.** Verify: same entry as D2 with `auto_scene` -> `scene_applied`, lights hold through a reconciler
pass (without the hold: lights return to the computed level: discriminates); co-owner present -> skipped; speaker
playing -> scene still applied, music skipped. Tests: `test_welcome_scene.py::test_scene_on_own_room_entry`,
`::test_scene_survives_reconciler`, `::test_scene_shared_gates`, `::test_scene_independent_of_music_outcome`,
`::test_scene_after_room_entry_lighting`. Live: first opted-in arrival gives `scene_applied` and the lights stay.

**D4 departure pause.** Verify: named exit at 0.9, stamp live, room empty -> pause; another person -> kept_shared;
track changed -> kept_not_ours; restart in between -> `departure_stamp_lost_restart`. Tests:
`::test_departure_pauses_own_playback`, `::test_departure_never_pauses_others`, `::test_departure_on_tracker_edge`,
`::test_stamp_lost_restart_counted`. Live: first departure after a start gives a pause or a kept reason.

**D5 arrival record + count follow-up (P2-D9).** Crossing-vision tests plus
`::test_count_followup_via_amend_function`, `::test_low_confidence_names_render_unrecognised`,
`::test_count_followup_dark_until_f_notify`. Live: one `crossing_vision_arrival` row with n, k, `guests_unnamed`.

**D6 episodes.** `arrival_music` and `welcome_scene` in `MEMORY_EPISODE_TYPES` and
`MEMORY_WRITER_BACKED_EPISODE_TYPES` (exempt with reason when the master is off). Outcomes in the NM digest.

**D7 docs, same commit.** `MUSIC_FOLLOWING.md` arrival + scene section; manual §5.5 comfort rows; presence state of
play §1 F5 consumers; CLAUDE.md 6.0.0 = step 8 (named arrivals, person profile, arrival music, welcome scene,
departure pause), quoting "step 8 is fine"; repair plan amendments (§10).

Mutation drills (RED then restore): move the hook below the confidence return; re-add a distance read; drop the MA
playing check; drop the occupied check or let ownership bypass it; read `music_day` without its toggle; drop the scene
hold; remove `person_profiles` from the allowlist; let `camera_face` open an intent; pause without the content-id
match; bypass the amend function; render a 0.6 name.

## 9. Knobs

| Knob | Default | Rung | Why / kill |
|---|---|---|---|
| `CONF_MUSIC_ON_ARRIVAL_START` (REUSED, relabelled "Arrival actions") + `switch.ura_music_arrival_start` | on | 2 + 3 | House master for music and scene; off = no intents |
| Profile fields (§5.1) | all off / empty; volume 0.30 | 2 (People) | Per-person opt-in per action; on for whoever ticks it |
| `ARRIVAL_WINDOW_S` | 900 (D0 sizes) | 1 | 0 = never act |
| `ARRIVAL_MIN_GAP_S` | 3600 | 1 | No repeat on a door bounce |
| `ARRIVAL_VERIFY_S` / `ARRIVAL_REVERSAL_S` | 20 / 120 | 1 | Ground-truth windows |
| `ARRIVAL_SCENE_SETTLE_S` | 5 | 1 | Max wait for the room's entry lighting before the scene |
| `ARRIVAL_MUSIC_DEPARTURE_PAUSE` | True | 1 | False = no departure action |
| Trip-wire thresholds | 10 / 7 d; 3 / 24 h | 1 | 0 = off |

Removed from rev 2: `ARRIVAL_MUSIC_ALLOW_SHARED_ROOM` (operator: no exception). The occupied rule is not a knob.

## 10. Dependencies, seams, sequence

Must ship first: step 6 census deconfliction; step 7 (amend function, confirmed names, `camera_egress`,
`departure_candidate`); **layer ship 3** (G4 `dispatch_person_arriving`, G6 `persons_in_room`, guard test; plan being
written now); MUSIC-FOLLOWING-TRANSFER-REPAIR-1 D0, D3-D7.
**Repair-plan amendments (arc rule 6, applied to `PLANNING_music_following_repair.md` before it ships):** (1) D7 item 3
keeps `music_on_arrival_start` as the arrival master, relabelled; (2) the 8 ft distance gate (`ble_too_far`,
`CONF_MF_HIGH_CONFIDENCE_DISTANCE`, `:42, :138, :316`) is dropped from transfers too, per the operator; the repair's
D1 room gate reads G6. If the repair keeps any distance read on transfers, the arrival check above still never calls it.
Seam with lighting: the welcome scene uses the room's existing manual-hold path; no new lighting owner. Seam with AI
room rules / OC: they read the profile, never write it. Arc map M11 updated at approval. F-NOTIFY: the count
follow-up waits for CD4; v6.0.0 does not.

## 11. Tier

Tier 2-DB (operator yes): three framing-disjoint code reviews (A gates, payloads, pick precedence; B integration,
restart, options save, listener lifecycle, reconciler interaction; C per-site mutation) plus one adversarial plan
re-review and framing G before build. P2-D9 keeps the crossing-vision plan's own bar. Release v6.0.0 at deploy.

## 12. Remaining operator questions (recommended defaults)

1. Bathrooms trigger arrival actions? Music in a bathroom is common with a speaker there; a welcome scene there is
   odd. Default: bathrooms trigger music only; the scene runs in bedrooms only.
2. Should an arrival into a room that is not yours but empty (the family room) play anything? Default no (own rooms
   only, as the card's "their arrival room / owned room" reads most narrowly). Saying yes adds one toggle "Also in
   empty shared spaces".
3. Welcome scene outside an arrival (any entry into your room after 15 min away)? Default no: arrival only, matching
   "automate my entries" as the operator first wrote it on the card. Revisit when OC consumes the profile.

## 13. Non-goals

Per-person temperature (cut; "the exclusion is fine"); guest-gate door identity; predictions writing profile fields
(they suggest only); actions for guests or untracked people; transfers (the music repair owns them); any security,
lock, HVAC or house-state consumer; Protect names; interior vision (step 9); a trial or shadow stage; a room-entry
"owners" field (owners derive from profiles).

## 14. Plan completion tracking

Built here: the full PERSON-PROFILE-PREFERENCES-1 scope (rooms, owners, music by time and room, per-action opt-in,
welcome scene), arrival music, departure pause, P2-D9 wiring, episodes, docs. Nothing from the card is parked.
DEPARTURE-ACTIONS-1: only the pause; the rest decomposed in §5.6. The count follow-up flip is census CD4.

## 15. Changes from rev 2 (for the equivalence review)

| Rev 2 | Rev 3 | Why |
|---|---|---|
| Profile = 4 fields; extras parked (§12 Q3) | Full profile, People step with conditional fields, room sub-step | Operator 2026-11-14 |
| `rooms` empty = any room with a speaker | Own rooms only; no rooms = no action | Card text "their arrival room / owned room"; Q2 above |
| `ARRIVAL_MUSIC_ALLOW_SHARED_ROOM` knob | Removed; occupied rule covers co-owners and the scene | Operator: "including in your own room" |
| Raw `SIGNAL_PERSON_ARRIVING`, `get_persons_in_room`, repair D1 BLE/path gate | G4 / G6 layer reads; no distance | Layer contract; 8 ft gate dropped |
| Welcome scene parked | D3 with reconciler hold | Operator |
| Knob prefix `ARRIVAL_MUSIC_*` | `ARRIVAL_*` where shared by music and scene | Two actions, one set of gates |
| §12 Q1-Q6 | Answered; three new questions | Operator |

Rev 2 review dispositions (H1, H2, M1-M6, L1-L5) still hold: H1 -> §5.4 top-of-function check; H2 -> §5.1 no-reload;
M2 -> §5.4 GPS-led wording; M3 -> §5.5 both entities; M4 -> §5.5 occupied check; the rest as in the archived §15.
