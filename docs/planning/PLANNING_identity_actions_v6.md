# PLANNING: identity actions (arc step 8): named arrivals, the person profile, arrival music, welcome scene, departure pause

Cards: PERSON-PROFILE-PREFERENCES-1 (whole card, no longer a first slice), VISION-CROSSING-ANALYSIS-1 (P2-D9 arrival
record and count follow-up, built as specified in `PLANNING_crossing_vision.md` §5), DEPARTURE-ACTIONS-1 (first
consumer). Arc: identity / vision / census, step 8 of `ARC_identity_vision_census_map.md` §4. Charter:
`ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md` (goals section, 2026-11-14 additions, drift #17).
Status: rev 3.1, 2026-11-14. Rev 3 was reviewed in `docs/reviews/plan-review/PLANREVIEW_identity_actions_v6_3.md`
(FIX-PLAN: 3 HIGH, 7 MEDIUM, 8 LOW); this rev fixes every finding in place. Rev 2 is archived at
`docs/planning/archive/PLANNING_identity_actions_v6_rev2.md`, NOT A BUILD SPEC. Rev 3 is not archived separately
(it is commit `6282c9c9`). §15 lists every change from rev 2 and from rev 3. Author ura-planner.

Read first, completely (CLAUDE.md): `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `SENSOR_FLEET_CLASSES.md` (both read
in full for rev 3.1), `IDENTITY_FUSION_CAMERAS_MANUAL.md`, `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (to confirm no HVAC
input changes; per-person HVAC targeting already exists as `zone_persons`, `hvac.py:7198-7236`),
`CONTRACT_person_awareness_layer.md`, `PLANNING_person_awareness_layer_ship3.md` (branch `plan/person-awareness-ship3`,
`50f15517`). No corrections-ledger claim is re-asserted. The presence doc's §4.6 fact this plan leans on: BLE extends
a room's occupancy but never creates it (BLE-WARM-CREATE-1), so a room's occupancy onset always comes from a body
sensor or a camera, usually before the person's BLE room flips.

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
- Schedule: v6.0.0 = step 8, "get a move on".

Step 8 therefore delivers, keyed to a recognised resident:

1. **Named arrivals.** Step 7 names confirmed arrivals; this plan adds the arrival record (n came in, k recognised) and
   its count follow-up through the same amend function.
2. **The person profile.** My rooms (bedrooms, bathrooms; a room listed by two people is shared by them, e.g. the
   master), my music (a default, optionally varied by time of day and by room), my volume, my welcome scene, and which
   entry actions I want automated.
3. **Arrival music.** The resident walks into one of their rooms that has a speaker; their music starts at their
   volume if nobody else is in the room and it is not quiet hours.
4. **Welcome scene.** When the resident's arrival lights their own room, the room's entry lighting uses their scene
   instead of the room's time-of-day scene, under the same gates.
5. **Departure pause.** When they leave, music URA started for them pauses if the room is now empty.

All of it ships ON on day 1 for every resident who opts in on the People step; there is no trial stage (memory
`feedback_no_shadow_mode_day1_correct`, "no shadow mode; on day 1"). The house master is on by default (§5.1, live
value read). The guest gate on door identity stays parked (GUEST-GATE-DOOR-IDENTITY-1).

Charter goals served: "assist arrivals accuracy and personalization"; "it's going to lead to OC and personalization and
Ai enhancements for rooms". Hard constraint "I need away to be fast acting": nothing here reads or writes house state
(INV-V6-AWAY). Layer constraint ("consumers can read and producers can feed"; "no leaks"): step 8 produces no fact,
reads F5 only through `dispatch_person_arriving` (layer ship 3, G4) and person rooms only through the layer's person
reads (§5.4). Short-clip constraint: untouched (no frame source here).

### 1.1 Drift check (ura-arc rule 7)

| Operator said | Where it drifted | Correction | Status |
|---|---|---|---|
| "Don't want to defer too much... not a good trigger" | Rev 2 parked the profile extras behind two weeks of arrival-music episodes (drift #17) | Rooms, owners, playlists by time and room, per-action opt-in, welcome scene are D1-D4 here | Fixed in rev 3 |
| "don't do it when someone is already in that room including in your own room" | Rev 2 had `ARRIVAL_MUSIC_ALLOW_SHARED_ROOM`; rev 3's occupied gate tripped on the arriving person's own motion (review H3), which would have turned the rule into "never fires" | Knob removed (rev 3); the gate compares occupancy onset with the person's BLE entry time minus a lead (rev 3.1) | Fixed |
| 8 ft gate dropped | Repair plan kept `CONF_MF_HIGH_CONFIDENCE_DISTANCE` | Removed on `feature/music-following-repair` (`706f7230`, operator 2026-11-14); arrival path never reads distance | Fixed (owned by the repair branch) |
| "consumers can read and producers can feed" | Rev 2 subscribed to raw `SIGNAL_PERSON_ARRIVING`; rev 3 assumed `persons_in_room`, which ship 3 does not build | Reads only what ship 3 delivers plus the existing `get_person_location`; §5.4 lists exactly what step 8 needs | Fixed |
| "When needed it's beautiful" | Rev 3's trigger sat in the transfer detector's listener list, which drops first-detection, ping-pong and post-restart entries (review H1) | Trigger is the layer's room read: an open-time check plus person-coordinator updates (§5.4) | Fixed |
| "get a move on" | Rev 3 hard-gated everything on ship 3 | §10.1 names the work that builds now | Fixed |

## 2. Institutional context verified

Greps run 2026-11-14 on develop (`109ef2c9`) unless marked. Rev 2 greps carried and re-checked where a row depends on
them: `SIGNAL_PERSON_ARRIVING`; `music_on_arrival|play_media|quiet|_enabled_persons|MIN_CONFIDENCE`;
`person_profile|PERSON_PREF|per_person` in `const.py` / `config_flow.py` (0 hits); `time_of_day|day_part|daypart|morning`
(bayesian bins, notification wording only); `CONF_LIGHT_SCENE_|LIGHT_SLOT_`; `owner|room_owner|assigned_person` in
`const.py` (fan / entity owners only); `ROOM_TYPE_BATHROOM`; `MediaSelector` in `config_flow.py` (0 hits);
`get_person_location|dispatch_person_arriving`; `visible` in the test venv's `homeassistant/data_entry_flow.py` (0 hits).
New for rev 3.1: `music_arrival_start|music_on_arrival_start` across the integration (const, config_flow, strings,
one docstring; no switch); `_maybe_activate_slot_scene` (`automation.py:1482`, `:1585`, def `:1740`);
`_became_occupied_time` (`coordinator.py:4213`, `:4283`, `:4463`, `:5422`, `:5471`; no public reader);
`ura_person_location_change` (`person_coordinator.py:1063`); `location_moves_since` in ship 3 plan (D4).

| Piece | Verdict | Where |
|---|---|---|
| F5 intake | REUSED via layer ship 3 G4 | `signals.dispatch_person_arriving` (contract §2.5); handler body is today's no-op `MusicFollowingCoordinator._handle_person_arriving` `domain_coordinators/music_following.py:549`, subscribed `:281` |
| Person's current room | REUSED | `PersonCoordinator.get_person_location(name)` `person_coordinator.py:1992` (returns the resolved room name or `"unknown"`); contract G6 read |
| Person's room moves | REUSED via ship 3 D4 | `PersonTrackingCoordinator.location_moves_since(t)` (ship 3 plan D4: frozen `(person_entity, from_room, to_room, ts, method)`, appended at the one move site, today `person_coordinator.py:1047-1077`) |
| Person's entry time when there is no move | REUSED | `get_person_previous_seen(name)` `person_coordinator.py:2039` (Bermuda area sensor `last_changed`, written `:1096`) |
| Update notification | REUSED pattern | `PersonCoordinator.async_add_listener` (DataUpdateCoordinator), the same listener the SC lock regime uses for Bermuda moves (presence state of play §1, "Review A fix-up, MED-1") |
| Room occupancy onset | REUSED value, NEW read-only accessor | room coordinator `_became_occupied_time` (set `coordinator.py:4213`, camera override `:4283`); accessor `occupied_since()` returns it |
| Room entry scene path | REUSED, extended | `AutomationEngine._maybe_activate_slot_scene` `automation.py:1740-1806` (manual-hold check `:1766`, scene state guard `:1777`, URA-context `scene.turn_on` `:1796`); callers `:1482` (sleep slot) and `:1585` (day / evening) |
| Room primary player; MA map; MA-first play; outcomes; decision log; episodes; preference hook | REUSED from MUSIC-FOLLOWING-TRANSFER-REPAIR-1 D0, D3-D7 | `PLANNING_music_following_repair.md` §6; `CONF_ROOM_MEDIA_PLAYER` `const.py:106`; `set_preference_provider` (`:279`) |
| Volume scale | REUSED | `CONF_ROOM_MEDIA_VOLUME_SCALE` `const.py:4250` |
| Quiet hours | REUSED | `NotificationManager.is_quiet_hours_active` `notification_manager.py:4772`, looked up as `hass.data[DOMAIN].get("notification_manager")` (as `transit_validator.py:2679`) |
| Time-of-day parts | REUSED | `lighting/resolver.py:309` `resolve_slot(is_sleep_hours, is_dark)` -> `LIGHT_SLOT_DAY` / `_EVENING` / `_SLEEP` (`const.py:1210-1212`), the room's own slot already used for `CONF_LIGHT_SCENE_DAY/EVENING/SLEEP` (`config_flow.py:14078-14095`). Not the bayesian six bins (`bayesian_predictor.py:67`) |
| Bathroom rooms | REUSED | `CONF_ROOM_TYPE` `const.py:457`, `ROOM_TYPE_BATHROOM` `:585` |
| Scene picker pattern | REUSED | `EntitySelector(domain="scene")` `config_flow.py:14081` |
| URA-context light writes | REUSED | `ura_context.URA_LIGHT_WRITE_DOMAINS` (includes `scene`, `const.py:1220` note): the entry path's scene call already carries URA context, so the reconciler's manual-change listener ignores it (`actuator_reconciler.py:516`). No manual hold is placed or faked |
| Room occupancy (any body) | REUSED | room coordinator `data[STATE_OCCUPIED]` (`coordinator.py:3613`); the v3.5.1 camera override sets it and stamps the onset (`coordinator.py:4262-4283`), so a camera-seen body is inside the room-occupancy leg |
| Comfort class | REUSED | `CONSUMER_CLASS_COMFORT` `const.py:6498` |
| URA context, person ids | REUSED | `ura_ctx_kwargs` `ura_context.py:80`; `tracked_person_entity_id` `person_ids.py:25`, `display_of` `:56` |
| Arrival master option | REUSED (un-retire) | `CONF_MUSIC_ON_ARRIVAL_START` `const.py:4864`, form `config_flow.py:10414-10415` (default `False` today); strings `strings.json:1889, :1898` |
| `switch.ura_music_arrival_start` | Not built | Rev 3 called it REUSED; it does not exist (review M1). Dropped: the per-person toggles are the live control, and one more CM switch is config surface with no use case (§15) |
| Options save without reload | REUSED | `OPTIONS_RELOAD_SUPPRESS_KEYS` `__init__.py:7553`, `_NO_LIVE_ATTR_KEYS` `:7406`, subset decision `:8826` |
| Crossing / arrival record; amend function | REUSED | `get_last_crossing` `presence.py:6009`, `get_last_arrival_record` `:6021`; `notify_arrival_followup` (`PLANNING_egress_direction_aware_identity.md` §5.4) |
| Episodes | REUSED pattern | `MEMORY_EPISODE_TYPES` `const.py:6204`, `MEMORY_WRITER_BACKED_EPISODE_TYPES` `:6263` |
| Room suggestions | REUSED | `person_visits` `database.py:995`; `PatternLearner.predict_next_room` `pattern_learning.py:143` |
| Conditional fields | REUSED (HA core) | `data_entry_flow.Required/Optional(..., visible=...)`, core 2026.11.1 (below) |
| Media picker | REUSED (HA core) | `selector.MediaSelector` (test venv `helpers/selector.py:1142-1176`) |
| `person_profiles` store, People step, profile sensor | NEW | 0 hits; only `async_step_person_tracking` `config_flow.py:4804` exists |
| Room ownership | NEW, derived | No person-owns-room key. Owners derive from profiles: one store |
| Arrival intent, room-entry check, scene override read, departure pause | NEW in the `MusicFollowing` engine | no arrival-start code exists |

**Transition-detector suppressors (why the trigger is not `_on_person_transition`).** `PersonTransitionDetector` never
notifies listeners on first detection (`previous_location` None or `"unknown"`, `transitions.py:182-185`, the
post-restart case), on a detection exception (`:206-212`) or on a ping-pong return leg (`:240-253`). Inside
`_on_person_transition` the coordinator-disabled return (`music_following.py:485`) and the same-room return (`:496`)
come before the enabled-persons (`:511-518`) and confidence (`:521-527`) returns. The person coordinator's move record
also skips moves from `"unknown"` (`person_coordinator.py:1047`), so `location_moves_since` misses the same
first-detection case; the open-time read in §5.4 covers it.

**HA conditional fields, verified against core 2026.11.1 source** (`homeassistant/data_entry_flow.py`,
`homeassistant/helpers/field_visibility.py`, and the 2026-10-21 contributors post; re-verified by the rev 3 review):

- `data_entry_flow.Required` / `Optional` (subclasses of `probatio.Required` / `Optional`) take
  `visible: bool | FieldCondition | list[FieldCondition] | None`. A list is ANDed.
- `FieldCondition` = `{"field": str, "operator"?: eq | not_eq | in | not_in | exists | not_exists, "value"?: ...}`.
- A field whose condition fails is not rendered, is treated as optional, and its value is dropped from the submitted
  data (`_strip_hidden_fields`). Visibility resolves iteratively, so hiding A hides B when B's condition reads A.
- `section` itself takes no `visible`; fields inside a section may. Every condition here names a field in its own
  section.
- The test venv is HA 2026.2.3: no `Required` / `Optional` markers and no `visible` there.
- Unverified until the D1 B0 spike: a `data_entry_flow.Optional` marker inside URA's existing `vol.Schema` body
  serializes its `visible` on 2026.11.1 (core types `data_schema` as `probatio.Schema`).

**MediaSelector, verified in the test venv (2026.2.3) source only:** config keys `accept` and `multiple`; value
`{entity_id?, media_content_id, media_content_type}`; without `accept` the form shows a player picker and browses that
player's media tree. No integration filter. Its options-flow render on 2026.11.1, the value shape there, whether
`entity_id` is required in the submitted value, and whether MA's browse tree yields ids that play on a different MA
player are D1 B0 checks, not facts here.

Prior plans read: rev 2, rev 3 and both plan reviews; `PLANNING_crossing_vision.md` §2-§8; contract (all); ship 3
plan (all; D4 and §11 Q1 decide what step 8 can read); music repair (all, plus commit `706f7230` on
`feature/music-following-repair`); egress direction-aware §5.4-§5.5; `AUDIT_pre_arrival_inventory_and_precool_standdown.md`
(218 arrival signals / 14 d). Card origin (PERSON-PROFILE-PREFERENCES-1, 2026-11-08): "a place to record personal
preferences for identified home people ie bedroom, bathroom, playlist, automate my entries vs not, etc. bedrooms may
have a designated owner or owners (master) so there can be a welcome scene"; predictions "as SUGGESTIONS... the
operator confirms". Memory: `project_hyper_personalization_person_profile`, `reference_identity_model_f1_f5`,
`feedback_fire_check_and_forward_trace`, `feedback_no_shadow_mode_day1_correct`,
`feedback_parent_entry_reload_watchdog_hazard`, `feedback_portability_imperative`, `feedback_registry_not_name_guessing`.

**Config-first.** No setting starts music or a scene on a person's arrival. Live read 2026-11-14 of
`/Users/okosisi/ha-config/.storage/core.config_entries` (read-only, key names and this one value only): no URA entry
stores `music_on_arrival_start`; the CM entry holds only `music_following_coordinator_enabled` among music keys. The
master has never been saved, so the consumer's default decides its day-1 value (§5.1).

## 3. Facts and consumer classes

Consumes F5 through `dispatch_person_arriving` (sources `geofence`, `ble`, and from step 7 `camera_egress`, dispatched
only for GPS-led confirmations of the person's own phone); F4 BLE room per person through the person reads in §5.4;
F1 `person.*` departure edge; F3 named exits and the arrival-record attribute. Produces no fact. Arrival music,
welcome scene, departure pause: **comfort**. Count follow-up: **notification** (names >= 0.75). Profile sensor and room
suggestions: **display**. Access, security, house state: none. The comfort-class awareness count (F2,
`view_for_class`) equals trust until F-LEAD; rev 3.1 no longer reads it (the occupied gate is room-level, §5.5).

## 4. Measure first (D0, read-only, one probe, before build)

14 days of recorder + URA DB (`person_visits`, activity `pre_arrival` rows, media player, light and room occupancy
history), per resident with at least one room that has a primary player:
(a) arrivals per day by source; lag from the F5 signal to the first BLE room change into a room with a player; the
classified confidence of that first transition (expected 0.50, evidence that the trigger cannot be the transfer path);
share where that room's native player or MA entity was playing, the room was already occupied, or quiet hours were on;
how often the first such room within 900 s was a plausible own room (`person_visits` dwell). Sizes `ARRIVAL_WINDOW_S`.
(a2) per own room: the distribution of room occupancy onset minus the person's BLE room entry (both signs), and the
person coordinator's update cadence. Sizes `ARRIVAL_OCCUPIED_LEAD_S` (default = p95 of "own motion before BLE" plus
margin) and `ARRIVAL_SCENE_CONFIRM_S`.
(b) departures per day per resident; how often the arrival room was empty within 5 min after.
(c) day / evening split of those arrivals under `resolve_slot` (tells whether per-part picks matter).
(d) after step 7 ships, the share of entries named at the crossing or confirmed (F-NOTIFY identity bar 0.50).
**Go/no-go:** none. The operator ruled that a low fire rate is not a reason to defer ("rarely exercised... not a good
trigger"), so D0 sizes windows and seeds suggestions; it does not gate the build. A number that makes a gate look
wrong (for example most first rooms are not own rooms, or own motion leads BLE by minutes) goes to the operator with
the number (charter rule 3).

## 5. Design

### 5.1 The profile store and the master

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

- **Rooms are stored by room config entry_id** (registry, not names). "My rooms" = bedrooms ∪ bathrooms. The layer's
  person reads return a room NAME (`person_coordinator.py:1045` `resolved_room`); the engine maps it to an entry_id
  through the room entries' own `room_name` (URA's own config, the one allowed string match), cached and rebuilt on
  `SIGNAL_ROOM_ENTRY_LIFECYCLE`. An unmapped name never matches an own room.
- **Owners are derived, never stored twice:** `room_owners(room) = {p : room in p.rooms}`. A room with two owners is
  shared (the master). Shared ownership changes nothing in the gates; either owner may trigger there.
- **Toggle-off semantics are the consumer's job.** On 2026.11 a hidden field is dropped from the submission; on older
  HA it is submitted. Either way the save merges into the stored profile, and the consumer reads a dependent field only
  when its toggle is on. Stale values under an off toggle are harmless and return if the toggle is turned on.
- **No reload.** `person_profiles` and `music_on_arrival_start` join `OPTIONS_RELOAD_SUPPRESS_KEYS` and
  `_NO_LIVE_ATTR_KEYS` in the same commit; the consumer fresh-reads the profile when an intent opens. Profiles reach
  music following through the repair's `set_preference_provider`, not a second path.
- **Master, day 1 = ON.** The consumer reads `options.get(CONF_MUSIC_ON_ARRIVAL_START, True)` and the form default
  becomes `True` (`config_flow.py:10415`). Live has no stored value (§2), so the master reads on at the first boot with
  no migration and no operator step. A stored `False` (none exists today) would be respected. Relabel
  `strings.json:1889, :1898` and `translations/en.json` to "Arrival actions" / "When a resident walks into their own
  room after arriving home, play their music and set their welcome scene (each person opts in under People)."
- **Display:** `sensor.ura_person_profile_<slug>` (state = number of automated actions on; attributes: rooms by name,
  owners of shared rooms, music labels, scene, `last_arrival_action`; attributes unrecorded).

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

Every toggle and the fields it controls sit in the same section. The time-of-day chain is two ANDed conditions:
`[{"field": "auto_music", "value": True}, {"field": "music_vary_time", "value": True}]`.

"Music by room" step: one optional MediaSelector per room in My rooms that has a primary player (rooms without one are
named in the description: "Master Bath has no speaker"). Blank = use the time-of-day or default pick.

Labels follow the style guide. Field count with everything off: 5 visible.

**Portability (older HA, and the test venv).** One helper, `_cond(key, cond, default)`, in `config_flow.py`:

- If `homeassistant.data_entry_flow` has `Optional` and its `__init__` accepts `visible` (checked once with
  `inspect.signature`), return `data_entry_flow.Optional(key, default=..., visible=cond)`.
- Else return `vol.Optional(key, default=...)`. Every field shows; descriptions say "used when X is on".

**Tests that run on the 2026.2.3 venv** (review M5): the fallback path for real; `_cond` against a stub marker class
(a `vol.Optional` subclass whose `__init__` accepts `visible`) monkeypatched in as `data_entry_flow.Optional`, asserting
the marker and its condition land inside the actual People `vol.Schema` and that `voluptuous_serialize.convert(schema,
custom_serializer=cv.custom_serializer)` runs without raising; and a fixture test comparing the conditions `_cond`
emits per field with the serialized `visible` keys recorded live in D1 B0 (`quality/tests/fixtures/people_form_visible_2026_11_1.json`).
A `skipif` HA < 2026.11 render test stays as an extra, not the only coverage.

### 5.3 How a playlist is specified and chosen

- **Picking.** `MediaSelector()` with no `accept`. The person picks any MA player to browse, then a playlist, radio
  station, artist or album. URA stores `media_content_id` + `media_content_type` and drops `entity_id`.
- **Fallback if the live spike fails** (MA ids not playable on another MA player, browse tree lacks playlists, or the
  options flow will not submit without `entity_id`): the MediaSelector stays for native players, and a text field "or
  paste a Music Assistant URI" (e.g. `library://playlist/12`) is added under the same `visible` condition. Decided in
  D1 B0, recorded in the README.
- **Choosing at play time** (one pure function, `pick_media(profile, room_id, slot)`):
  1. `music_by_room[room_id]` if `music_vary_room` and set;
  2. else `music_day` / `music_evening` for the room's `resolve_slot(...)` if `music_vary_time` and set;
  3. else `music_default`.
  The slot is the target room's own, so music and the room's lighting scenes agree on "evening". The `sleep` slot never
  plays (quiet gate), so it has no pick.
- **Volume:** `music_volume` x the room's `CONF_ROOM_MEDIA_VOLUME_SCALE`, clamped 0..1. Per person.
- **No bonus joins.** Play on the room's MA entity (MA-first) or native player; never group-join other players.

### 5.4 Arrival intent and the room-entry trigger

- **Intent.** The F5 handler opens one intent per person (`_arrival_intents`, RAM, owned by the `MusicFollowing`
  engine, cleared at teardown) for `ARRIVAL_WINDOW_S` when: the master is on; the person is a tracked resident with
  `auto_music` or `auto_scene` on; music following is enabled (`_coordinator_enabled()`, the same read as
  `music_following.py:485`) and not in observation mode. First source wins and is recorded. A face or vision input
  alone never opens one: `camera_egress` reaches F5 only after a GPS-led confirmation of the person's own phone (step 7
  §5.5), and `camera_face` arrivals are ignored by this consumer. A person with no rooms set opens no intent (counted
  `skipped_no_rooms`; the People step says so).
- **The trigger is the person's room, read from the layer, not the transfer detector** (review H1). The engine never
  hooks `_on_person_transition`, so the detector's suppressors (§2) cannot hide an arrival entry. Two reads, and
  nothing else:
  1. **At intent open:** `get_person_location(name)` once. If it maps to an own room, the music check runs now with
     entry time = `get_person_previous_seen(name)`. This covers the person already in their room when the slow
     geofence lands, and the post-restart first detection (from `"unknown"`, which neither the detector nor the move
     ring records).
  2. **While any intent is open:** a `PersonCoordinator.async_add_listener` callback (registered when the first intent
     opens, removed when the last closes and at teardown) reads `location_moves_since(cursor)` for intent holders,
     oldest first, and advances the cursor. The first move whose `to_room` maps to an own room runs the music check
     with entry time = the move's `ts`. A ping-pong return leg is a move like any other. Then it reads
     `get_person_location(name)` once more, which catches an `"unknown" -> room` change the ring does not record.
- **Room precedence (review M2).** The music target is the room the layer reports for the person; nothing reads
  `transition.to_room`. The scene target is the room whose own entry lighting is running (§5.5), confirmed later by the
  layer read; the layer wins the confirmation (`scene_unconfirmed` when it never places the person there).
- **Window end.** When the window closes with music not yet decided: `window_expired` if the move ring holds no own-room
  entry for the person inside the window, or `entry_missed` if it does (an own-room entry the engine failed to act on;
  this is the H1 failure counted). Same for the scene: `scene_window_expired` / `scene_entry_missed`.
- **What step 8 needs from the layer.** Ship 3 builds `dispatch_person_arriving` (G4) and `location_moves_since` (D4).
  `get_person_location` and `get_person_previous_seen` exist today. Ship 3 does not build `persons_in_room` (ship 3
  §11 Q1, split to G6-ONE-BLE-ROOM-READ-1), so "another tracked person is in room R" is computed by the engine as: any
  other tracked person whose `get_person_location` maps to R. That is the one site to swap to `persons_in_room` when
  G6-ONE-BLE-ROOM-READ-1 lands; until then the guard test pins those three reads as the music files' only
  person-coordinator calls. Nothing else is needed from ship 3.

### 5.5 Gates and actions

**Occupied gate (review H3).** A room is "occupied before this person" when either:
- its occupancy onset (`occupied_since()`, the room coordinator's `_became_occupied_time`) is earlier than the person's
  entry time minus `ARRIVAL_OCCUPIED_LEAD_S`. The arriving person's own motion, radar or camera body starts the onset a
  few seconds to tens of seconds before BLE moves them in, inside the lead, so it never blocks. A camera-seen body is
  inside this leg because the camera override stamps the onset (`coordinator.py:4262-4283`), so there is no separate
  camera read; or
- another tracked person's layer room is this room (§5.4). Ownership does not matter: a co-owner already in the master
  blocks it.
No knob disables the gate; the lead only sizes "before".

**Music**, checked once per intent at the own-room entry found in §5.4, in this order, each a counted outcome:
1. quiet hours (`is_quiet_hours_active`, §2 lookup) or house `sleep` / `waking` -> `skipped_quiet` / `skipped_sleep`;
2. room automation paused (`const.room_automation_paused`) -> `skipped_paused`;
3. occupied gate -> `skipped_occupied`;
4. one music start per person per `ARRIVAL_MIN_GAP_S` -> `skipped_gap`;
5. no pick resolves -> `skipped_no_media`; primary player unavailable -> `skipped_no_player`;
6. native primary or its MA entity reads `playing` or is in a playing group -> `skipped_playing`;
7. play MA-first, native when no MA entity, with `ura_ctx_kwargs`; verify the entity played reads `playing` within
   `ARRIVAL_VERIFY_S` -> `started` with stamp `{person, room, native_player, ma_entity, media_content_id, started_at}`,
   else `start_failed`. A non-URA pause, stop or volume 0 within `ARRIVAL_REVERSAL_S` -> `reversed`.

**Welcome scene (review H2): a per-person override inside the room's own entry scene path.** No second scene call, no
new lighting writer, no manual hold.
- The engine exposes a read-only, synchronous `arrival_scene_for(room_entry_id) -> str | None`. In
  `_maybe_activate_slot_scene` (`automation.py:1740`), on the day / evening caller (`:1585`) only, the engine reads it
  before `slot_scene(...)`: `scene_id = arrival_scene_for(room) or slot_scene(self.config, slot)`. Everything after is
  the existing path: the manual-hold check (`:1766`, a held light skips the scene and the per-light path runs), the
  scene-state guard (`:1777`), one URA-context `scene.turn_on` (`:1796`). The sleep caller (`:1482`) never reads it.
- `arrival_scene_for(room)` returns the scene when all hold, else None: exactly one owner of this room has an open
  intent with `auto_scene` on, a `welcome_scene` set and the scene not yet decided; no other tracked person's layer room
  is this room; not quiet hours, not house `sleep` / `waking`; that owner had no welcome scene within
  `ARRIVAL_MIN_GAP_S`; and the room is one the scene may run in (§12 Q1 default: bedrooms only). The entry path itself
  runs only on the room's vacant-to-occupied edge and only when the room is not paused, so "occupied before" is false
  by construction and the paused gate is the room's own.
- At return the engine records the decision: `scene_applied` when it returned a scene and the entry path's hold check
  and state guard passed (the engine learns this from a second call, `note_arrival_scene_result(room, applied: bool)`,
  made by `_maybe_activate_slot_scene` right after its decision), `scene_skipped_hold` when the hold check fell back,
  `scene_skipped_unavailable` when the state guard fell back, and `scene_skipped_ambiguous` when two owners of the room
  hold open intents. Then within `ARRIVAL_SCENE_CONFIRM_S` the layer must place the person in the room
  (`scene_confirmed`), else `scene_unconfirmed` (a co-owner or a guest walked in; the lights came on either way).
- If the room's entry rule turns no lights on (bright daytime, no lights configured), the entry path never reaches the
  override and the scene outcome is `scene_window_expired` / `scene_entry_missed` at window end.
- Survival: nothing in URA re-applies a slot scene mid-occupancy and the reconciler acts only on an availability edge
  or a quarantine release (`actuator_reconciler.py:461-467`, `:1208`), so the welcome scene stays until vacancy turns
  the lights off as today, or a person changes them.

Music and scene outcomes are independent: a playing speaker skips music but not the scene.

**Outcome contract (review M3).** One decision-log line and one episode (`arrival_music` or `welcome_scene`) per
outcome, and outcomes in the NM digest:

| Path | Outcomes |
|---|---|
| Intent | `intent_opened` (source), `skipped_no_rooms`, `skipped_master_off` (not logged per arrival; counter only) |
| Music | `started`, `start_failed`, `reversed`, `skipped_quiet`, `skipped_sleep`, `skipped_paused`, `skipped_occupied`, `skipped_gap`, `skipped_no_media`, `skipped_no_player`, `skipped_playing`, `window_expired`, `entry_missed` |
| Scene | `scene_applied`, `scene_confirmed`, `scene_unconfirmed`, `scene_skipped_hold`, `scene_skipped_unavailable`, `scene_skipped_ambiguous`, `scene_skipped_quiet`, `scene_skipped_sleep`, `scene_skipped_occupied`, `scene_skipped_gap`, `scene_window_expired`, `scene_entry_missed` |
| Departure | `departure_paused`, `departure_kept_shared`, `departure_kept_occupied`, `departure_kept_not_ours`, `departure_kept_other_playing`, `departure_stamp_lost_restart` |

`room_disagree` (review M3) does not exist: there is one room source per action (§5.4), and the scene's disagreement is
`scene_unconfirmed`.

### 5.6 Departure pause

For a person with a live music stamp, the first of: a named exit at >= 0.75 (step 7 `departure_candidate` or
`attached`, via `get_last_crossing`) or their `person.*` `home -> not_home | zone` edge. Pause the stamped entity
(`media_player.media_pause`, URA context) only when it still plays the stamped `media_content_id`
(`departure_kept_not_ours`), the other entity of the pair is not playing something else
(`departure_kept_other_playing`), the room coordinator reads not occupied (`departure_kept_occupied`), and no tracked
person's layer room is it (`departure_kept_shared`). The stamp is RAM; a restart loses it, counted
`departure_stamp_lost_restart` at setup from the last `started` episode with no pause. Not built: last-resident arming
(escalation, manual §5.5(a)); HVAC setback (AWAY does it); lights off (vacancy does it).

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
- **INV-V6-ARRIVAL-REACHES.** For any arrival whose window contains the person's layer room being one of their rooms
  (whether they were already there at intent open, moved in after, came from `"unknown"` after a restart, or returned
  on a ping-pong leg), with no other body there earlier than the lead, an idle player and no quiet hours, the music
  outcome is `started`, whatever the transition's classified confidence, the person's transfer enablement, any BLE
  distance, or whether the transfer detector notified. Break it with: the 4-hours-away first room, already-in-room at
  open, `previous_location="unknown"`, a ping-pong return leg, own motion 40 s before BLE, and a 20 ft distance.
- **INV-V6-COUNTED.** Every opened intent ends in exactly one music outcome and one scene outcome (when the action is
  on) from §5.5; none ends silent.
- **INV-V6-NEVER-INTERRUPT.** No start on a room whose native player or MA entity is playing; no pause of playback URA
  did not start.
- **INV-V6-OCCUPIED.** No music start and no welcome scene into a room whose occupancy began earlier than the person's
  entry minus the lead, or in which another tracked person is placed (co-owner included). No knob disables this.
- **INV-V6-QUIET.** No music and no welcome scene in quiet hours or house `sleep` / `waking`.
- **INV-V6-OFF-MEANS-OFF.** With a toggle off, nothing under it acts, whether the HA version hid and dropped its fields
  or kept them.
- **INV-V6-ONE-SCENE.** A room entry issues at most one `scene.turn_on`; the welcome scene replaces the slot scene when
  eligible, and a manual hold beats both.
- **INV-V6-NO-RELOAD.** A People save never reloads the CM entry.
- **INV-V6-AWAY.** No step-8 path reads or writes an `infer()` input, the census trust view, or HVAC.
- **INV-V6-LAYER.** Step 8 reads F5 only via `dispatch_person_arriving` subscribers and person rooms only via
  `get_person_location`, `get_person_previous_seen` and `location_moves_since`; the layer guard test (ship 3) covers
  the music files.
- **INV-V6-ONE-AMEND / NAME-BAR.** Arrival follow-ups only through the amend function; no text names below 0.75.

## 7. Producer and consumer checks; sites

Producers: geofence, BLE pre-arrival, step-7 `camera_egress`, all through `dispatch_person_arriving`. Fire check: 218
arrival signals / 14 d (AUDIT_pre_arrival); BLE room moves fire continuously; the arrival path itself has fired zero
times (no-op handler). Trip-wires: `arrival_action_zero` (HIGH NM: >= 10 intents with an own-room entry in 7 days and
0 `started` + `scene_applied`), `arrival_entry_missed` (HIGH NM: >= `ARRIVAL_ENTRY_MISSED_NM` `entry_missed` +
`scene_entry_missed` in 7 days; this one sees the H1 class directly, where `window_expired` alone is benign: most
arrivals go to the kitchen), `arrival_music_failing` (HIGH NM: >= 3 `start_failed` in 24 h), `welcome_scene_failing`
(>= 3 `scene_unconfirmed` + `scene_skipped_unavailable` in 24 h). Forward trace: F5 -> intent -> layer room read ->
gates -> play / scene override -> verify -> episode -> departure -> pause. Consumers of the new store: the music
engine, the entry scene path (through `arrival_scene_for`), the profile sensor, the People step, and later OC and AI
room rules (read-only, through the sensor or `get_person_profile(person)`; no second store).

**Site enumeration (independent re-run of the review's list):**
1. `_handle_person_arriving` `domain_coordinators/music_following.py:549` (intent open).
2. The new person-coordinator listener and the open-time read (§5.4). `_on_person_transition` `music_following.py:473`
   is NOT a site: no arrival code goes there (mutation drill below).
3. Detector suppressors `transitions.py:177`, `:182`, `:188`, `:206`, `:240`: untouched, and irrelevant by design;
   tests drive each to prove the arrival still starts.
4. `_maybe_activate_slot_scene` `automation.py:1740` (override read and result note), callers `:1585` (reads) and
   `:1482` (must not read).
5. The LightPolicyOracle writer `automation.py:811` `note_manual_light`: must have no new caller (guard grep test).
6. Every `media_player.*` / `music_assistant.*` / `scene.turn_on` call in both music files (all with `ura_ctx_kwargs`).
7. The options-save path `__init__.py:8826` and the master form `config_flow.py:10414-10415`.
8. Every read of `person_profiles`, the amend function.

## 8. Deliverables

Numbering note: rev 3 renumbered rev 2's D3-D6 to D4-D7 when the welcome scene became D3; rev 2 review dispositions
that cite D3-D6 refer to today's D4-D7.

**D0 probe.** Report committed with (a), (a2), (b)-(d). Live: n/a.

**D1 profile store, People step, sensor, no-reload, master, portability.** B0 spike first, in the live CM options flow
on HA 2026.11.1 (not the venv), recorded in the README: (i) a `data_entry_flow.Optional` with `visible` inside URA's
`vol.Schema` renders and its serialized `visible` keys per field are saved as the D1 fixture; (ii) MediaSelector in
the options flow: render, submitted value shape, whether `entity_id` is required; (iii) browse through an MA player
and playback of the stored id on a different MA player; picks the §5.3 fallback if needed. **If (i) fails to serialize,
stop and redesign with the operator; do not fall back silently** (the fallback is for older HA, not a broken 2026.11).
Verify: a save applies on the next intent with zero CM reloads (today a new CM key reloads the entry: discriminates);
display-name and entity-id `tracked_persons` key the same profile; suggestions never stored; owners derived (two people
listing the master -> both owners, no room-entry field written); master reads on with no stored value. Tests:
`test_person_profile.py::test_profile_keyed_by_one_id_rule`, `::test_owners_derived_shared_master`,
`::test_people_save_in_reload_suppress_allowlist`, `::test_people_save_no_reload_real_options_update`,
`::test_suggestions_never_stored`, `::test_master_defaults_on_when_unset`, `::test_master_false_respected`,
`::test_cond_helper_falls_back_without_visible`, `::test_cond_helper_passes_visible`,
`::test_people_schema_with_marker_serializes` (stub marker, runs on the venv), `::test_people_form_matches_live_fixture`,
`::test_people_form_visible_conditions` (skipif HA < 2026.11), `::test_room_step_one_field_per_player_room`,
`::test_toggle_off_ignores_stale_fields`, `::test_room_name_maps_to_entry_id`. Live: form shows 5 fields with
everything off, music fields appear when "Play my music" is ticked; profile sensor shows the saved fields; no reload
in the log on save; master label reads "Arrival actions".

**D2 arrival music.** Verify: Oji not_home 4 h, geofence arrival, layer room `master_bedroom` (classified 0.50,
distance 20 ft), idle Sonos -> `started` (a hook on the transfer path, or any distance read: nothing plays:
discriminates). Already in the master when the geofence lands -> `started` from the open-time read (a transitions-only
trigger: no outcome until `window_expired`: discriminates). Restart, `previous_location="unknown"`, walks into the
master -> `started`. Own motion 40 s before BLE -> `started` (lead 0: `skipped_occupied`: discriminates). Room
occupied 10 min before entry -> `skipped_occupied`. Native idle but MA playing -> `skipped_playing`. Ezinne already in
the master -> `skipped_occupied`. 23:30 -> `skipped_quiet`. Hall then master -> starts in the master. Kitchen only for
15 min -> `window_expired`; own-room move in the ring but never acted on (listener detached in the test) ->
`entry_missed`. Tests: `test_arrival_music.py::test_first_room_after_hours_away_starts`,
`::test_intent_opens_with_person_already_in_own_room`, `::test_entry_after_restart_unknown_previous_location`,
`::test_ping_pong_return_leg_still_starts`, `::test_no_hook_in_on_person_transition`,
`::test_no_distance_read_on_arrival_path`, `::test_own_motion_before_ble_does_not_block`,
`::test_occupant_before_lead_blocks`, `::test_only_own_rooms_trigger`, `::test_never_interrupts_native_or_ma_playing`,
`::test_coowner_present_skips`, `::test_quiet_and_sleep_skip`, `::test_face_alone_opens_no_intent`,
`::test_gps_confirmed_camera_egress_opens_intent`, `::test_pick_media_precedence`, `::test_slot_from_room_resolve_slot`,
`::test_verify_on_player_state`, `::test_ma_first_native_fallback`, `::test_no_bonus_joins`, `::test_reversal_counted`,
`::test_window_expired_vs_entry_missed`, `::test_every_intent_ends_counted`, `::test_zero_fire_tripwire`,
`::test_entry_missed_tripwire`, `::test_listener_removed_when_no_intents_and_at_teardown`. Config extremes: window 0;
lead 0 and lead 600; volume 0.05 / 1.0 with scale 1.5; rooms empty; own room with no player. Live: first opted-in
arrival gives `started` (music audible) or a named skip in the decision log; zero `entry_missed`.

**D3 welcome scene.** Verify: same arrival with `auto_scene` and a slot scene configured for the master -> exactly one
`scene.turn_on`, the welcome scene (without the override: the slot scene applies: discriminates) -> `scene_applied`
then `scene_confirmed`; no slot scene configured -> the welcome scene still applies; a light under a manual hold ->
`scene_skipped_hold` and the per-light path runs; co-owner placed in the room -> `scene_skipped_occupied`, slot scene
applies; speaker playing -> scene applied, music skipped; bathroom entry -> slot scene (§12 Q1 default); sleep caller
never reads the override; nobody confirmed in the room within the window -> `scene_unconfirmed`. Tests:
`test_welcome_scene.py::test_entry_override_replaces_slot_scene`, `::test_one_scene_call_per_entry`,
`::test_welcome_without_slot_scene`, `::test_manual_hold_blocks_welcome_scene`, `::test_scene_shared_gates`,
`::test_scene_independent_of_music_outcome`, `::test_sleep_caller_never_reads_override`,
`::test_scene_unconfirmed_counted`, `::test_scene_ambiguous_two_owner_intents`, `::test_no_new_note_manual_light_caller`,
`::test_scene_rooms_default_bedrooms_only`. Live: first opted-in arrival gives `scene_applied` + `scene_confirmed` and
one "Room entry [...]: activating ... scene=<welcome>" log line, no second scene line.

**D4 departure pause.** Verify: named exit at 0.9, stamp live, room empty -> pause; another person -> kept_shared;
track changed -> kept_not_ours; restart in between -> `departure_stamp_lost_restart`. Tests:
`::test_departure_pauses_own_playback`, `::test_departure_never_pauses_others`, `::test_departure_on_tracker_edge`,
`::test_stamp_lost_restart_counted`. Live: first departure after a start gives a pause or a kept reason.

**D5 arrival record + count follow-up (P2-D9).** Crossing-vision tests plus
`::test_count_followup_via_amend_function`, `::test_r7_and_perimeter_followup_same_crossing` (at most 3 sends per
crossing), `::test_low_confidence_names_render_unrecognised`, `::test_count_followup_dark_until_f_notify`. Live: one
`crossing_vision_arrival` row with n, k, `guests_unnamed`; `get_last_arrival_record` returns it.

**D6 episodes.** `arrival_music` and `welcome_scene` in `MEMORY_EPISODE_TYPES` and
`MEMORY_WRITER_BACKED_EPISODE_TYPES` (exempt with reason when the master is off). Outcomes in the NM digest.

**D7 docs, same commit.** `MUSIC_FOLLOWING.md` arrival + scene section; manual §5.5 comfort rows; presence state of
play §1 F5 consumers and the new `occupied_since()` reader; CLAUDE.md 6.0.0 = step 8 (named arrivals, person profile,
arrival music, welcome scene, departure pause), quoting "step 8 is fine"; repair plan amendment (§10).

Mutation drills (RED then restore): move the music check into `_on_person_transition` and remove the open-time read
(evaluate only on transitions); drop the listener's `get_person_location` re-read; re-add a distance read; set the lead
to 0 in the gate; drop the MA playing check; drop the occupied gate or let ownership bypass it; read `music_day`
without its toggle; issue the slot scene instead of the override when eligible; call `scene.turn_on` a second time from
the engine; let the sleep caller read the override; remove `person_profiles` from the allowlist; let `camera_face`
open an intent; pause without the content-id match; skip the window-end outcome; bypass the amend function; render a
0.6 name.

## 9. Knobs

| Knob | Default | Rung | Why / kill |
|---|---|---|---|
| `CONF_MUSIC_ON_ARRIVAL_START` (REUSED, relabelled "Arrival actions") | on (consumer and form default; unset live) | 2 | House master for music and scene; off = no intents |
| Profile fields (§5.1) | all off / empty; volume 0.30 | 2 (People) | Per-person opt-in per action |
| `ARRIVAL_WINDOW_S` | 900 (D0 sizes) | 1 | 0 = never act |
| `ARRIVAL_OCCUPIED_LEAD_S` | 120 (D0 a2 sizes) | 1 | How far before the person's BLE entry a room onset counts as "someone else first". Review-only: too large lets an earlier occupant through. Not a kill switch; the occupied rule has none |
| `ARRIVAL_SCENE_CONFIRM_S` | 120 (D0 a2 sizes) | 1 | Wait for the layer to place the person after a scene; counting only |
| `ARRIVAL_MIN_GAP_S` | 3600 | 1 | No repeat on a door bounce; per person per action |
| `ARRIVAL_VERIFY_S` / `ARRIVAL_REVERSAL_S` | 20 / 120 | 1 | Ground-truth windows |
| `ARRIVAL_MUSIC_DEPARTURE_PAUSE` | True | 1 | False = no departure action |
| Trip-wire thresholds | 10 / 7 d; `ARRIVAL_ENTRY_MISSED_NM` 3 / 7 d; 3 / 24 h | 1 | 0 = off |

Removed: `ARRIVAL_MUSIC_ALLOW_SHARED_ROOM` (rev 3; operator: no exception), `ARRIVAL_SCENE_SETTLE_S` (rev 3.1; the
scene now rides the entry path, nothing to wait for), `switch.ura_music_arrival_start` (rev 3.1; never existed).

## 10. Dependencies, seams, sequence

Must ship before v6.0.0: step 6 census deconfliction; step 7 (amend function, confirmed names, `camera_egress`,
`departure_candidate`); **layer ship 3** (G4 `dispatch_person_arriving`, D4 `location_moves_since`, guard test);
MUSIC-FOLLOWING-TRANSFER-REPAIR-1 D0, D3-D7.
**Repair-plan seam (arc rule 6).** (1) D7 item 3 keeps `music_on_arrival_start` as the arrival master, relabelled
(amendment to `PLANNING_music_following_repair.md`, applied by this plan's D7). (2) The 8 ft gate is owned by the
repair: commit `706f7230` on `feature/music-following-repair` removed `ble_too_far`, the distance knob's form field,
live key and plumbing; the repair's room check reads `get_person_location` (`c5685b5f`). This plan's only obligation
is that the arrival path never reads distance (drill above). Seam with lighting: the welcome scene is a read inside
the existing entry scene path; no new lighting writer, no manual hold. Seam with G6-ONE-BLE-ROOM-READ-1: one call site
to swap (§5.4). Seam with AI room rules / OC: they read the profile, never write it. Arc map M11 updated at approval.
F-NOTIFY: the count follow-up waits for CD4; v6.0.0 does not.

### 10.1 What builds now (review G1)

Parallel with ship 3 and step 7, against stub signatures, on one branch: **D0** (probe, no code dependency); **D1**
(People step, store, sensor, master default, `_cond`, the B0 live spike); `pick_media` and its tests; the
`occupied_since()` accessor; `arrival_scene_for` / `note_arrival_scene_result` with the entry-path read in
`automation.py` (against a stubbed engine); D6 episode types. **D5** builds when step 7's amend function lands.
D2-D4's engine wiring builds against a fake `dispatch_person_arriving` and a fake `location_moves_since` with ship 3's
D4 tuple shape, and switches to the real calls when ship 3 merges; the layer guard test lands with ship 3. No raw
signal path is added as a fallback (that would recreate drift #16). If ship 3 slips, v6.0.0 slips with it, and the
orchestrator tells the operator with the date rather than shipping a raw-signal variant.

## 11. Tier

Tier 2-DB (operator yes): three framing-disjoint code reviews (A gates, payloads, pick precedence, outcome contract;
B integration, restart, options save, listener lifecycle, entry scene path; C per-site mutation) plus a focused plan
re-review of §5.4-§5.5 and framing G before build. P2-D9 keeps the crossing-vision plan's own bar. Release v6.0.0 at
deploy.

## 12. Remaining operator questions (recommended defaults; built as the defaults until answered)

1. Bathrooms trigger arrival actions? Default: bathrooms get music only; the welcome scene runs in bedrooms only.
2. Should an arrival into a room that is not yours but empty (the family room) play anything? Default no: own rooms
   only. Saying yes adds one toggle "Also in empty shared spaces".
3. Welcome scene outside an arrival (any entry into your room after 15 min away)? Default no: arrival only.

## 13. Non-goals

Per-person temperature (cut; "the exclusion is fine"); guest-gate door identity; predictions writing profile fields
(they suggest only); actions for guests or untracked people; transfers (the music repair owns them, and the 8 ft gate's
removal); any security, lock, HVAC or house-state consumer; Protect names; interior vision (step 9); a trial or shadow
stage; a room-entry "owners" field; re-applying the welcome scene mid-occupancy (nothing re-applies a slot scene
either); building `persons_in_room` (G6-ONE-BLE-ROOM-READ-1).

## 14. Plan completion tracking

Built here: the full PERSON-PROFILE-PREFERENCES-1 scope (rooms, owners, music by time and room, per-action opt-in,
welcome scene), arrival music, departure pause, P2-D9 wiring, episodes, docs. Nothing from the card is parked.
DEPARTURE-ACTIONS-1: only the pause; the rest decomposed in §5.6. The count follow-up flip is census CD4.

## 15. Changes (for the equivalence review)

### 15.1 Rev 2 -> rev 3

| Rev 2 | Rev 3 | Why | Still true in 3.1? |
|---|---|---|---|
| Profile = 4 fields; extras parked (§12 Q3) | Full profile, People step with conditional fields, room sub-step | Operator 2026-11-14 | Yes |
| `rooms` empty = any room with a speaker | Own rooms only; no rooms = no action | Card text; §12 Q2 | Yes, pending Q2 |
| `ARRIVAL_MUSIC_ALLOW_SHARED_ROOM` knob, `skipped_shared` | Removed; occupied rule covers co-owners and the scene | Operator: "including in your own room" | Yes |
| Raw `SIGNAL_PERSON_ARRIVING`, `get_persons_in_room`, repair D1 BLE/path gate + BERMUDA-DISTANCE-SENSORS-DEAD-1 prerequisite | G4 / G6 layer reads; no distance | Layer contract; 8 ft gate dropped | G4 yes; room reads replaced (15.2) |
| Read API ship 1 prerequisite | Dropped | Shipped | Yes |
| Welcome scene parked | D3 with reconciler hold | Operator | Mechanism replaced (15.2) |
| Knob prefix `ARRIVAL_MUSIC_*` | `ARRIVAL_*` where shared | Two actions, one set of gates | Yes |
| §4 go/no-go: >= 3 eligible starts per week | Removed | Operator: low fire rate "not a good trigger" | Yes (listed here per review) |
| `window_expired`, full outcome list, one log line + episode each (§5.2) | Lost silently | (none: an omission) | Restored, §5.5 |
| `test_r7_and_perimeter_followup_same_crossing` | Lost silently | omission | Restored, D5 |
| D1 "today a new CM key reloads the entry: discriminates" | Lost silently | omission | Restored, D1 |
| D4 live "`get_last_arrival_record` returns it" | Lost silently | omission | Restored, D5 |
| "No bonus joins" | Lost silently | omission | Restored, §5.3 |
| Quiet-hours lookup path | Lost silently | omission | Restored, §2 |
| D0(a) first-transition confidence (0.50) | Lost silently | omission | Restored, §4 |
| D0(c) F-NOTIFY bar 0.50; §3 "equals trust until F-LEAD" | Lost silently | omission | Restored, §4(d), §3 |
| Deliverables D3-D6 | Renumbered D4-D7 (scene became D3) | New deliverable | Note in §8 |
| §12 Q1-Q6 | Answered; three new questions | Operator | Yes |

Rev 2 review dispositions: H1 (top-of-function check) is superseded by the layer trigger (15.2, H1); H2 -> §5.1
no-reload (held); M2 -> §5.4 GPS-led wording (held); M3 -> §5.5 both entities (held); M4 -> §5.5 occupied check
(rewritten, 15.2 H3); the rest as in the archived §15.

### 15.2 Rev 3 -> rev 3.1 (review `PLANREVIEW_identity_actions_v6_3.md`)

| Finding | Rev 3 | Rev 3.1 |
|---|---|---|
| H1 trigger site | Check at the top of `_on_person_transition` | Layer trigger: `get_person_location` at intent open + person-coordinator listener reading `location_moves_since` and re-reading location; no arrival code in `_on_person_transition`; `window_expired` / `entry_missed`; tests for already-in-room, restart `"unknown"`, ping-pong; drill "evaluate only on transitions" (§5.4, D2) |
| H1 ship 3 scope | Assumed `persons_in_room` | Uses only G4, `location_moves_since`, and the existing `get_person_location` / `get_person_previous_seen`; one swap site for G6-ONE-BLE-ROOM-READ-1 (§5.4) |
| H2 scene mechanism | Second `scene.turn_on` after `ARRIVAL_SCENE_SETTLE_S` plus a manual hold via `note_manual_light`; "reconciler pulls lights back" | Per-person override read inside `_maybe_activate_slot_scene`; one scene per entry; no hold, no new writer; reconciler claim and `ARRIVAL_SCENE_SETTLE_S` dropped; INV-V6-SCENE-STICKS replaced by INV-V6-ONE-SCENE; D3 discriminator re-derived (§5.5, D3, §2 row corrected) |
| H3 self-occupancy | "Before this person's entry the room read occupied", undefined | Onset earlier than BLE entry minus `ARRIVAL_OCCUPIED_LEAD_S` (rung 1, D0 a2 sizes); `occupied_since()` accessor; camera leg folded into room onset because the camera override stamps it (`coordinator.py:4262-4283`); the house-level comfort count was never per-room (§5.5, §4) |
| M1 master | `switch.ura_music_arrival_start` "REUSED", default on vs form `False` | Switch does not exist and is not built; live value read (unset); consumer and form default `True`; strings relabelled (§2, §5.1) |
| M2 room source | G6 "confirmed by" a transition carrying `to_room` | Precedence rule stated: layer room for music, entry-path room confirmed by the layer for the scene (§5.4) |
| M3 outcome contract | Partial list | Full table, one log line + one episode each, `room_disagree` explained away, `entry_missed` trip-wire (§5.5, §7) |
| M4 MediaSelector | 2026.2.3 only | B0 (ii) in the live options flow on 2026.11.1 (D1) |
| M5 visible coverage | skipif only | Venv stub-marker serialization test + live-fixture test; serialization failure = stop and redesign (§5.2, D1) |
| M6 8 ft gate | This plan amended the repair | Owned by `feature/music-following-repair` (`706f7230`); referenced, not owned (§10) |
| G1 schedule | Everything gated on ship 3 | §10.1 parallel work; no raw-signal fallback |
| L1-L6 | Lost from rev 2 | Restored (15.1) |
| L7 knobs | `ARRIVAL_SCENE_SETTLE_S` present | Removed; `ARRIVAL_OCCUPIED_LEAD_S`, `ARRIVAL_SCENE_CONFIRM_S`, `ARRIVAL_ENTRY_MISSED_NM` added (§9) |
| G2 narrowing | Q1/Q2 defaults | Kept as questions with defaults, built as defaults until answered (§12) |
| New outcome | n/a | `skipped_no_media` (profile with `auto_music` but no pick) named so it is not silent |
