# PLANNING: identity actions (arc step 8): named arrivals, the person profile, arrival music, welcome scene, departure pause

Cards: PERSON-PROFILE-PREFERENCES-1 (whole card, no longer a first slice), VISION-CROSSING-ANALYSIS-1 (P2-D9 arrival
record and count follow-up, built as specified in `PLANNING_crossing_vision.md` §5), DEPARTURE-ACTIONS-1 (first
consumer). Arc: identity / vision / census, step 8 of `ARC_identity_vision_census_map.md` §4. Charter:
`ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md` (goals section, 2026-11-14 additions, drift #17).
Status: rev 3.4, 2026-11-14. Rev 3.3 (`02b213db`) was re-checked in
`docs/reviews/plan-review/PLANREVIEW_identity_actions_v6_3_3.md` (`94eb10c3`; FIX-PLAN small: 2 MEDIUM, 5 LOW), and
rev 3.2 (`9d142590`) in `PLANREVIEW_identity_actions_v6_3_2.md` (`67374ce8`); this rev fixes every finding in place and leaves the §10.1 parallel set's design unchanged (it is being built on
`feature/step8-identity-actions`). Rev 3.1 was re-reviewed in `PLANREVIEW_identity_actions_v6_3_1.md`, rev 3 in
`PLANREVIEW_identity_actions_v6_3.md`. Rev 2 is archived at `docs/planning/archive/PLANNING_identity_actions_v6_rev2.md`,
NOT A BUILD SPEC; rev 3 is commit `6282c9c9`, rev 3.1 is `72e4befd`, rev 3.2 is `9d142590`. §15 lists every change
from rev 2, rev 3, rev 3.1 and rev 3.2. Author ura-planner.

Read first, completely (CLAUDE.md): `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `SENSOR_FLEET_CLASSES.md` (both read
in full for rev 3.1 and again for rev 3.3), `IDENTITY_FUSION_CAMERAS_MANUAL.md`, `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (to confirm no HVAC
input changes; per-person HVAC targeting already exists as `zone_persons`, `hvac.py:7198-7236`),
`CONTRACT_person_awareness_layer.md`, `PLANNING_person_awareness_layer_ship3.md` (rev 3.4.1, branch
`plan/person-awareness-ship3` @ `4d6a3daf`; §5 D1, D2, D4 and §12 read for rev 3.2). No corrections-ledger claim is
re-asserted. The presence doc facts this plan leans on: BLE extends a room's occupancy but never creates it
(BLE-WARM-CREATE-1, §4.6), so a room's occupancy onset always comes from a body sensor or a camera, usually before the
person's BLE room flips; and `SIGNAL_PERSON_ARRIVING` is NOT a physical arrival (§1 table), so an F5 alone never
proves the person was away (§5.4).

Code lines in this plan are cited at `feature/music-following-repair` @ `c5685b5f`, the base the step 8 branch cuts
from (§10). Develop has moved past it (for example the master form is `config_flow.py:10509-10510` on develop and
`:10383-10384` on the repair branch); the builder re-greps every cite at build.

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
reads F5 only through `subscribe_person_arriving` (layer ship 3a D1), F1 edges only through `get_person_edges_since` /
`subscribe_person_edges` (3a D2), and person rooms only through the layer's person reads (§5.4). Short-clip
constraint: untouched (no frame source here).

### 1.1 Drift check (ura-arc rule 7)

| Operator said | Where it drifted | Correction | Status |
|---|---|---|---|
| "Don't want to defer too much... not a good trigger" | Rev 2 parked the profile extras behind two weeks of arrival-music episodes (drift #17) | Rooms, owners, playlists by time and room, per-action opt-in, welcome scene are D1-D4 here | Fixed in rev 3 |
| "don't do it when someone is already in that room including in your own room" | Rev 2 had `ARRIVAL_MUSIC_ALLOW_SHARED_ROOM`; rev 3's occupied gate tripped on the arriving person's own motion (review H3), which would have turned the rule into "never fires" | Knob removed (rev 3); the gate compares occupancy onset with the person's BLE entry time minus a lead (rev 3.1) | Fixed |
| 8 ft gate dropped | Repair plan kept `CONF_MF_HIGH_CONFIDENCE_DISTANCE` | Removed on `feature/music-following-repair` (`706f7230`, operator 2026-11-14); arrival path never reads distance | Fixed (owned by the repair branch) |
| "consumers can read and producers can feed" | Rev 2 subscribed to raw `SIGNAL_PERSON_ARRIVING`; rev 3 assumed `persons_in_room`, which ship 3 does not build | Reads only what ship 3 delivers plus the existing `get_person_location`; §5.4 lists exactly what step 8 needs | Fixed |
| "When needed it's beautiful" | Rev 3's trigger sat in the transfer detector's listener list, which drops first-detection, ping-pong and post-restart entries (review H1) | Trigger is the layer's room read: an open-time check plus person-coordinator updates (§5.4) | Fixed |
| "get a move on" | Rev 3 hard-gated everything on ship 3; rev 3.1 sat with no re-review (drift #20) | §10.1 names the work that builds now; it is being built; rev 3.2 changes nothing in it | Fixed |
| "When needed it's beautiful" | Rev 3.1 opened an intent on any F5, so a GPS flap would start music on a resident who never left (re-review H1) | Intent opens only on a counted return (§5.4) | Fixed in rev 3.2 |
| "don't do it when someone is already in that room" | Rev 3.1's scene guard was blind at entry time, so the scene could go to a co-owner who walked in first (re-review H2) | Holder must be placed near the room (§5.5; rev 3.3 default near rule = same house zone, §12 Q4) | Fixed in rev 3.2, rule revised in rev 3.3 |
| "Departure pause is fine" | Rev 3.1 checked once at the exit edge, while the room still read occupied, so it would almost never fire (re-review M7) | Bounded vacancy wait, departing person excluded (§5.6) | Fixed in rev 3.2 |
| "consumers can read and producers can feed"; ship 3 Q4 "BLE-ARRIVAL-PRODUCER-HVAC-GATED-1 before v6.0.0" | F5 named as the send function; the raw connect kept; the card not referenced (re-review M6) | `subscribe_person_arriving`; raw R10 row retired; card in §10 | Fixed in rev 3.2 |
| `camera_egress` as an arrival source (step 7 seam) | Rev 3.2's counted-return gate asked an egress F5 for an arrival edge that step 7 guarantees does not exist yet, so the source was dead on arrival (re-check H1) | Departure-side rule: reject only if the person departed less than `RESIDENT_RETURN_MIN_AWAY_MIN` ago (§5.4) | Fixed in rev 3.3 |
| "When needed it's beautiful" | Rev 3.2 trusted the BLE producer's was-away guard, which its S3 arm sets with no 15-minute test (re-check H2) | Same departure-side rule applied to `ble` in the engine (§5.4) | Fixed in rev 3.3 |
| Per-person welcome scene (card) | Rev 3.2's adjacency near check, under live adjacency, reaches about one or two of four residents (re-check H3, framing G) | Default near rule = same house zone (`get_room_zone`); D0 (a2) measures three rules; §12 Q4 to the operator (§5.5) | Fixed in rev 3.3, pending Q4 |
| "Departure pause is fine" | A GPS flap armed a pause on a person who is home; a 600 s wait was thin over 500 s room timeouts (re-check M2, M3) | Wait = room timeout + knob; `departure_kept_returned` (§5.6) | Fixed in rev 3.3 |

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
`ura_person_location_change` (`person_coordinator.py:1069` repair branch); `location_moves_since` in ship 3 plan (D4).
New for rev 3.2 (repair branch `c5685b5f` and develop): `get_person_previous_location_time|get_person_previous_seen`
(`person_coordinator.py:2045`, `:2050`); `def get_adjacent_rooms|CONF_ADJACENT_ROOMS` (`presence.py:3415-3474`, the
only adjacency read; no path map exists for this use); `counted|source_stale|in_boot_window` in `residency.py`;
`SIGNAL_PERSON_ARRIVING` in `domain_coordinators/music_following.py` (`:42`, `:296`); `STATE_OCCUPIED|async_add_listener`
in both music files (only `transition_detector.async_add_listener`, `music_following.py:296`: no room-occupancy read
exists in the engine today); `"music_following"` / `"coordinator_manager"` in `__init__.py` (`:3433`, `:4643`);
`^SIGNAL_.*OCCUP` (only `SIGNAL_OCCUPANCY_ANOMALY`: no room-vacancy signal exists, so §5.6 polls).
New for rev 3.3: `RESIDENT_RETURN_MIN_AWAY_MIN` (develop `const.py:4109`, `presence.py:5290`); `get_room_zone`
(`presence.py:3477`); live `adjacent_rooms` and `occupancy_timeout` per room in `core.config_entries` (read-only, via
the re-check); ship 3a guard as built, read-only, worktree `agent-aa1d30dcca08c1676` (`feature/layer-ship3a`):
`LISTED` / `LISTED_RESERVED` in `quality/tests/person_awareness_layer_allowlist_PROVISIONAL.py`, the `_listed()`
filter in `test_person_awareness_layer_guard.py:46`, the total assertion `:62-63` (sum of `ROWS` max only), and
`READ_LIST["PRESENCE"]` in `quality/tests/_layer_guard_engine.py:84-94` (holds `get_person_edges_since`,
`person_edges_truncated_since`, `subscribe_person_edges`; not `get_adjacent_rooms`, not `get_room_zone`).

| Piece | Verdict | Where |
|---|---|---|
| F5 intake | REUSED via layer ship 3a D1 | `signals.subscribe_person_arriving(hass, cb)` (sync `@callback`, `cb(PersonArrivingPayload)`; ship 3 §5 D1). D2 replaces today's raw connect `MusicFollowingCoordinator.async_setup` `domain_coordinators/music_following.py:296` (`SIGNAL_PERSON_ARRIVING`) with it; handler body today is the no-op `_handle_person_arriving` (`:565`) |
| Counted return (H1) | REUSED via ship 3a D2 | `PresenceCoordinator.get_person_edges_since(t: float, *, persons, kinds)` -> plain tuple of `ResidencyEvent`, `edge_ts >= t`, epoch float, oldest first; truncation via `person_edges_truncated_since(t)` (ship 3 §5 D2, §12). `ResidencyEvent` already carries `counted`, `source_stale`, `in_boot_window`, `resident_set_resolved` (`domain_coordinators/residency.py:39-51` develop); `counted` is the lock regime's `arrival_edges.counted_return` (raw away >= 15 min). `geofence` reads arrival edges; `camera_egress` and `ble` read departure edges (§5.4, rev 3.3) |
| Return bar for `camera_egress` / `ble` (re-check H1, H2; rev 3.4 M1) | REUSED | `const.RESIDENT_RETURN_MIN_AWAY_MIN` (15, `const.py:4109` develop; read at `presence.py:5290` as the residency counted-return bar), applied to `get_residency_snapshot()` `left_at` / `arrived_at` (in `READ_LIST["PRESENCE"]`, ship 3a). Boot window `RESIDENT_RETURN_BOOT_WINDOW_S` (600, `const.py:4110`). No new knob |
| Step 7 `camera_egress` send condition | REUSED (seam) | `PLANNING_egress_direction_aware_identity.md:591-598`: the D2 egress branch skips raw `home`, and the dispatch fires only for a GPS-led confirmation "whose raw `person.*` is still not `home` at confirm time". So no residency arrival edge exists when that F5 lands |
| Departure edge (M7) | REUSED via ship 3a D2 | `residency.subscribe_person_edges(hass, cb, *, persons, kinds={"departure"})` (sync, O(1), schedules work; guard R14) |
| Person's current room | REUSED | `PersonCoordinator.get_person_location(name)` `person_coordinator.py:1998` (returns the resolved room name or `"unknown"`); contract G6 read |
| Person's room moves | REUSED via ship 3a D4 | `location_moves_since(t: datetime)` -> plain tuple of frozen `PersonMove(person_entity, from_room, to_room, ts, method)`, `ts >= t` (inclusive), oldest first; `location_moves_truncated_since(t: datetime) -> bool` (True when full and oldest `ts > t`, or `t` older than the log's creation: RAM, restart or reload). Appended at the one move site, same condition as the `ura_person_location_change` fire (`person_coordinator.py:1069`) |
| Person's entry time when there is no move (M3) | REUSED | `get_person_previous_location_time(name)` `person_coordinator.py:2050` (set only on a real room change; area flips inside a room leave it alone; a move from `"unknown"` does not set it). Fallback when None: `get_person_previous_seen(name)` `:2045` (Bermuda area sensor `last_changed`, which resets on an area flip inside the room, so it is the fallback only) |
| Update notification | REUSED pattern | `PersonCoordinator.async_add_listener` (DataUpdateCoordinator), the same listener the SC lock regime uses for Bermuda moves (presence state of play §1, "Review A fix-up, MED-1"); ship 3a reserves it as R10 row `('R10', 'music_following.py', '<step 8 §5.4 music listener>:async_add_listener[PC]')` |
| Room adjacency (H2) | REUSED, D0 measurement only by default | `PresenceCoordinator.get_adjacent_rooms(room_name)` `domain_coordinators/presence.py:3463-3475` develop (cache over each room's `CONF_ADJACENT_ROOMS`, `:3403-3461`; room names; one-directional as configured). Live config is sparse (§5.5 table). Other readers, which is why adding adjacency is not free: fan recheck L2 veto (`presence_fan_recheck.py:1396-1409`), the presence fan-interference gate (`presence.py` around `:4774`), NM panel targeting (`notification_manager.py:6325-6327`) |
| House-zone membership (re-check H3) | REUSED | `PresenceCoordinator.get_room_zone(room_name)` `presence.py:3477` develop (reads `_room_to_zone`; membership only, no side effects; NM panel targeting precedent, presence state of play §1). Default scene near rule (§5.5) |
| Presence lookup | REUSED | `hass.data[DOMAIN]["coordinator_manager"]` (`__init__.py:4643`) `.coordinators["presence"]`, the path step 1a uses (presence ledger #36); None -> fail closed (no intent, counted `skipped_no_presence`) |
| Engine lookup from the entry path (L6) | REUSED | `hass.data[DOMAIN].get("music_following")` (`__init__.py:3433`); None -> no override, slot scene as today. Room key = `self._config_entry.entry_id` (`automation.py:499`) |
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
| Arrival master option | REUSED (un-retire) | `CONF_MUSIC_ON_ARRIVAL_START` `const.py:4951`, form `config_flow.py:10383-10384` (default `False` today); develop `const.py:4935`, `config_flow.py:10509-10510`; strings `strings.json:1889, :1898` (re-grep) |
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
also skips moves from `"unknown"` (the `old_location not in ("unknown", "")` condition at the move site), so `location_moves_since` misses the same
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
F1 residency arrival edges (the `geofence` counted-return gate, the departure wait's return check) and departure edges
(the departure arm) and the residency snapshot's `left_at` / `arrived_at` (the `camera_egress` / `ble` absence rule),
through ship 3a D2; F3 named exits and the arrival-record attribute. Produces no fact. Arrival music,
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
Also, by source, the share of F5 signals the §5.4 gate 5 rule would admit: for `geofence`, a counted, non-stale,
out-of-boot-window residency arrival for the same person within `ARRIVAL_COUNTED_EDGE_LOOKBACK_S` before the signal
(`memory_episodes` `person_arrival` rows) and the lag between the two; for `camera_egress` and `ble`, a last
residency departure (`person_departure` rows) at least `RESIDENT_RETURN_MIN_AWAY_MIN` before the signal with no later
arrival, and the distribution of "F5 minus last departure". BLE F5s are also split by "raw `person.*` read `home` for
the whole prior 15 minutes" (the LOST-at-home case the rule now rejects, and the overrule-only case it gives up).
Sizes the geofence lookback; tells how many geofence F5s are flaps the gate drops, how many BLE F5s are short trips
the S3 arm let through, and how many were never away.
(a2) per own room: the distribution of room occupancy onset minus the person's BLE room entry (both signs), and the
person coordinator's update cadence. Sizes `ARRIVAL_OCCUPIED_LEAD_S` (default = p95 of "own motion before BLE" plus
margin) and `ARRIVAL_SCENE_CONFIRM_S`. Also, at each own-room onset during an arrival window, where BLE placed the
arriving person: this room, another room, or `away` / `unknown`; and, per bedroom, the share of onsets the §5.5 near
check passes under each of three near rules:
  - (i) adjacency as configured (`get_adjacent_rooms`, either direction);
  - (ii) adjacency plus the approach hall (the hall or staircase the person was placed in just before, added
    hypothetically; nothing is written to config);
  - (iii) same house zone (`get_room_zone`, the §5.5 default).
  Also the holder's placed room at each bedroom onset (so a miss from the Staircase, which sits in Back Hallway and
  no zone rule can pass for an upstairs bedroom, is visible), and the BLE-after-body lag itself.
  The three shares go to the operator with §12 Q4; the rule is not widened or narrowed silently.
(b) departures per day per resident; how often the arrival room was empty within 5 min after, and the distribution of
departure edge to the room's next occupied-to-vacant edge, split by arming source (named exit at the door vs residency
departure edge, which lands minutes later) and by room (the room's `occupancy_timeout` is the main term: 500 s in Jaya
Bedroom and Ziri Bedroom, 300 s in the master, guest bedrooms and media, live config). Sizes the margin knob
`ARRIVAL_DEPARTURE_VACANCY_WAIT_S` per arming source; the wait itself is the room's timeout plus that margin (§5.6).
Also the share of departures whose room never reads vacant inside the wait while a fan runs (Jaya's LD2410 fan
phantom, presence state of play §6), which ends `departure_kept_occupied` honestly.
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
  becomes `True` (`config_flow.py:10384` repair branch). Live has no stored value (§2), so the master reads on at the first boot with
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

- **F5 read.** The engine subscribes once at setup with `subscribe_person_arriving(hass, self._on_person_arriving)`
  (a sync `@callback`; it only records `t_f = dt_util.now()` and schedules the intent work, never awaits). D2 deletes
  the raw `SIGNAL_PERSON_ARRIVING` connect in `MusicFollowingCoordinator.async_setup`
  (`domain_coordinators/music_following.py:296`) in the same commit (§10, guard rows).
- **Intent gates, in this order** (each rejection is a counter, with no decision line, like `skipped_master_off`):
  1. the master is on (`skipped_master_off`); music following is enabled (`_coordinator_enabled()`, the same read as
     the transfer path) and not in observation mode (`skipped_master_off`);
  2. the source is `geofence`, `ble` or `camera_egress`. `camera_face` and any unknown source are ignored
     (`skipped_source`); `camera_egress` reaches F5 only after a GPS-led confirmation of the person's own phone (step 7
     §5.5), so a face or vision input alone never opens an intent;
  3. the person is a tracked resident with `auto_music` or `auto_scene` on and at least one room set
     (`skipped_no_rooms`; the People step says so);
  4. no intent already open for this person. A second F5 inside the window keeps the first source (recorded) and is
     counted `intent_duplicate_source` with the second source (re-review M5). This runs BEFORE the counted-return gate
     (re-check LOW-2), so a late geofence F5 after a `camera_egress` open is recorded as the second source, not as
     `skipped_not_counted_return`;
  5. **counted return (re-review H1; rev 3.3 re-check H1, H2).** F5 is not a physical arrival (presence state of play
     §1), and 218 F5 signals in 14 days for four residents include geofence flaps with no real absence. One bar for all
     three sources: the person was away at least `RESIDENT_RETURN_MIN_AWAY_MIN` (15 minutes, REUSED, the residency and
     lock bar). How each source proves it:
     - `geofence`: the engine reads `get_person_edges_since(t_f.timestamp() - ARRIVAL_COUNTED_EDGE_LOOKBACK_S,
       persons={person_entity}, kinds={"arrival"})` and needs at least one record with `counted is True`,
       `source_stale is False` and `in_boot_window is False` (`arrival_edges.counted_return`: raw `not_home` of at least
       15 minutes, or the restore exceptions, which `in_boot_window` and `counted` already exclude). The residency record
       is written inside the same `_handle_geofence_change` call before the F5 send (`presence.py:5644` feed,
       `:5681-5685` send), so it is present when the callback runs, and 120 s is ample. Otherwise
       `skipped_not_counted_return`.
     - `camera_egress` and `ble` (positive evidence of an absence; rev 3.4 re-check M1): these F5s land BEFORE the
       person's raw `person.*` reads `home` (step 7 sends `camera_egress` only while raw `person.*` is still not
       `home`, `PLANNING_egress_direction_aware_identity.md:591-598`; a BLE F5 can precede GPS), so no arrival edge
       exists yet. The engine reads `get_residency_snapshot()["persons"][<person key>]` (the key form ship 3a uses; the builder re-reads it; already in `READ_LIST["PRESENCE"]`;
       not limited by the 32-record ring) and passes only when `left_at` is set, is at least
       `RESIDENT_RETURN_MIN_AWAY_MIN` before `t_f`, and `arrived_at` is absent or older than `left_at` (the most recent
       residency edge is that departure). An empty or missing entry, or no `left_at`, NEVER passes:
       `skipped_not_counted_return`, subtype `no_departure_seen`. A departure newer than the bar, or an arrival after
       it: `skipped_not_counted_return`, subtype `recent_departure`. (A counted geofence arrival in the lookback would
       also prove it, but the duplicate gate catches that case first.)
       - Why positive evidence: "no departure edge" also means "never left". The LOST branch sets `_person_was_away`
         after 15 minutes with no `person.state` test (`person_coordinator.py:1204-1218` develop), so 20 minutes on the
         patio or in a garage out of scanner range, GPS `home` throughout, gives a BLE F5 with no departure edge.
         Residency writes a departure only from `old == "home"` to a real value (`residency.py:127-128`), so
         `home -> unknown -> not_home` writes none either. Both now open no intent. The S3 arm sets
         `_person_was_away` with no time test (`:802-804`; repair base `c5685b5f:766-768`), but S3 needs `person.state`
         away, so its absence has a `left_at` and a short trip fails the 15-minute test. The rule lives in the engine,
         not the producer.
       - **Cost, stated:** an absence seen only by the BLE overrule (GPS stuck `home` while really away) no longer opens
         through `ble`. That needs a second GPS device or a frozen app (one GPS tracker per person since 11-11); the
         geofence F5 still opens the intent once GPS catches up.
       - `camera_egress`: step 7's GPS prior-fix test stays the producer's guard; this rule adds the consumer's bar.
     - **Truncation (`geofence`).** If `person_edges_truncated_since(<the read's t>)` is True and no qualifying arrival
       is found, the intent is not opened (fail closed), counted `skipped_edges_truncated`. Subtype `boot` when the
       read's `t` predates the residency tracker's `created_ts` (restart or presence reload), else `ring`.
     - **Post-restart dead window (re-check M2), fails closed.** The residency tracker is RAM and starts empty at
       presence setup. After a restart or presence reload no intent opens:
       - `ble` / `camera_egress`: for `RESIDENT_RETURN_MIN_AWAY_MIN` (15 min). The snapshot has no `left_at` from
         before setup, so the rule reads `no_departure_seen`; counted as `skipped_edges_truncated` subtype `boot` while
         `t_f - 15 min` predates `created_ts`;
       - `geofence`: for `RESIDENT_RETURN_BOOT_WINDOW_S` (600 s, `const.py:4110`): every arrival edge carries
         `in_boot_window = True`;
       - the departure pause is unaffected (§5.6: any armed wait belongs to music started after setup).
       Bound: one window per restart, about 1 % of arrivals at today's restart rate. The `boot` subtype is counted in
       the NM digest, so the window is visible without a log line per F5.
- **Intent.** An intent that passes is stored per person (`_arrival_intents`, RAM, owned by the `MusicFollowing`
  engine, cleared at teardown) for `ARRIVAL_WINDOW_S`, with its source, `t_f`, a cursor (below) and its music and
  scene outcome slots. The engine writes an `intent_opened` episode (`arrival_music`, `outcome: intent_opened`,
  `source`, `opened_at`, `window_s`, `music_on`, `scene_on`: the person's `auto_music` / `auto_scene` at open) at open
  (re-review M5; re-check M4; §5.5 restart rule).
- **One music check per intent (re-check LOW-1).** Every path below (open-time read, listener moves, location re-read)
  runs the music check only while the intent's music slot is undecided. The first check that runs fills the slot with
  its outcome; later paths see it filled and do nothing.
- **The trigger is the person's room, read from the layer, not the transfer detector** (review H1 of rev 3). The
  engine never hooks `_on_person_transition`, so the detector's suppressors (§2) cannot hide an arrival entry.
  Person-coordinator reads are exactly `get_person_location`, `get_person_previous_location_time`,
  `get_person_previous_seen`, `location_moves_since`, `location_moves_truncated_since` and `async_add_listener`; the
  engine reads no `person_coord.data` (guard R2).
  1. **At intent open:** `get_person_location(name)` once. If it maps to an own room, the music check runs now (the
     slot is undecided by construction) with
     entry time = `get_person_previous_location_time(name)`, or `get_person_previous_seen(name)` when that is None
     (re-review M3: the area sensor's `last_changed` resets on an area flip inside the room, which would make the
     person's own session onset read as "someone else first"). This covers the person already in their room when the
     slow geofence lands, and the post-restart first detection from `"unknown"`, which neither the detector nor the
     move log records.
  2. **While any intent is open:** a `PersonCoordinator.async_add_listener` callback (registered when the first intent
     or departure wait opens, removed when the last closes and at teardown; the reserved R10 row, §10) runs one pass
     per update, per intent holder:
     - **Cursor (re-review M1).** A BLE F5 is sent inside `_async_update_data` before `self.data` is committed, so the
       arrival's own move carries the tick's `now`, which is at or before `t_f`. The cursor therefore starts at
       `t_f - interval`, where `interval` is the person coordinator's `update_interval` (a `timedelta`; the same
       `datetime` type and clock as `PersonMove.ts`). The first pass reads `location_moves_since(cursor)` and keeps
       every move of this person (`move.person_entity == person_entity`), since the read is inclusive. After a pass the
       cursor becomes the newest processed `move.ts`, and later passes keep only `move.ts > cursor` (ship 3 §12: `>=`
       includes the cursor record). A person has at most one move per tick, so `>` never drops a same-person move.
     - The first kept move whose `to_room` maps to an own room runs the music check (while undecided) with entry time =
       max(`move.ts`, cursor at open). A ping-pong return leg is a move like any other.
     - **Truncation (re-review M2).** Each pass also calls `location_moves_truncated_since(cursor)`. On True (the log is
       RAM: a person-coordinator reload, or a full log), the intent is marked `moves_truncated` and the location re-read
       below decides alone.
     - **Location re-read.** Then `get_person_location(name)` once more. If it maps to an own room and the music slot
       is still undecided, the music check runs with entry time = max(`get_person_previous_location_time(name)`, falling
       back to `get_person_previous_seen(name)`, cursor at open). This catches an `"unknown" -> room` change the log does
       not record.
     - **Entry-time clamp (re-check M1).** On both in-window paths (listener moves and the re-read) the person was not
       in an own room at open, so their entry is no earlier than the cursor at open (`t_f - interval`). The clamp
       matters on the re-read: `previous_location_time` is refreshed only when the old location is not `unknown`
       (`person_coordinator.py:1093-1097`), so after an `unknown -> room` change it can be hours old, and without the
       clamp the onset leg ("onset earlier than entry minus the lead") could never trip. The open-time path (item 1)
       keeps the unclamped value: there the person really was in the room before the F5. INV-V6-OCCUPIED therefore has
       no residual.
- **Room precedence (review M2 of rev 3).** The music target is the room the layer reports for the person; nothing
  reads `transition.to_room`. The scene target is the room whose own entry lighting is running (§5.5), gated on the
  holder being placed near it (§5.5 near rule), and confirmed later by the layer read (`scene_unconfirmed` when it never
  places the person there).
- **Window end.** A timer (`async_call_later`, cancelled on teardown) closes each intent at `t_f + ARRIVAL_WINDOW_S`.
  With music not yet decided:
  1. **Independent re-read first (re-review L1).** `get_person_location(name)` once more. If it maps to an own room,
     record `entry_missed` with subtype `unrecorded`: the person is in their room and the engine never acted, seen
     through a read the move-log path does not share.
  2. Else, if the intent is marked `moves_truncated`: `window_expired_truncated` (the log cannot say whether an entry
     was missed).
  3. Else `entry_missed` (subtype `logged`) if `location_moves_since(cursor at open)` holds an own-room move of this
     person inside the window, or `window_expired` if it does not.
  Same for the scene: `scene_entry_missed` / `scene_window_expired_truncated` / `scene_window_expired`. Both
  `entry_missed` subtypes feed the `arrival_entry_missed` trip-wire (§7).
- **What step 8 needs from the layer.** Ship 3a builds `subscribe_person_arriving` (D1), `get_person_edges_since` /
  `person_edges_truncated_since` / `subscribe_person_edges` (D2) and `location_moves_since` /
  `location_moves_truncated_since` (D4). `get_person_location`, `get_person_previous_location_time` and
  `get_person_previous_seen` exist today. Ship 3 does not build `persons_in_room` (ship 3 §14 Q1, split to
  G6-ONE-BLE-ROOM-READ-1), so "another tracked person is in room R" is computed by the engine as: any other tracked
  person whose `get_person_location` maps to R. That is the one site to swap to `persons_in_room` when
  G6-ONE-BLE-ROOM-READ-1 lands. Accepted by name (re-review L4): that read includes a STALE location, kept for
  `decay_timeout` (300 s), so a resident who left the room minutes ago still blocks music and scene. That is the
  conservative direction. Timing: D4's moves land in ship 3a phase 1; D2's edge reads land in ship 3a phase 2, after
  census-p2 (ship 3 §11), so the H1 gate and the departure edge switch to real calls then (§10.1).

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
0. toggles re-read at check time (re-review M5): the master, `_coordinator_enabled()`, and the person's fresh profile
   `auto_music`. Any off -> `skipped_toggled_off` (INV-V6-OFF-MEANS-OFF holds mid-window, not only at open);
1. quiet hours (`is_quiet_hours_active`, §2 lookup) or house `sleep` / `waking` -> `skipped_quiet` / `skipped_sleep`;
2. room automation paused (`const.room_automation_paused`) -> `skipped_paused`;
3. occupied gate -> `skipped_occupied`;
4. one music start per person per `ARRIVAL_MIN_GAP_S` -> `skipped_gap`;
5. no pick resolves -> `skipped_no_media`; primary player unavailable -> `skipped_no_player`;
6. native primary or its MA entity reads `playing` or is in a playing group -> `skipped_playing`;
7. play MA-first, native when no MA entity, with `ura_ctx_kwargs`; verify the entity played reads `playing` within
   `ARRIVAL_VERIFY_S` -> `started` with stamp `{person, room, native_player, ma_entity, media_content_id, started_at}`,
   else `start_failed`. A non-URA pause, stop or volume 0 within `ARRIVAL_REVERSAL_S` -> `reversed`.

**Two owners, music (re-review L3).** Music has no two-owner rule: if both owners of the master arrive together and
both intents are open, the first check to pass starts music and the second gets `skipped_playing` (or
`skipped_occupied` once the first is placed). The operator said "Shares spaces, likely same", so that is accepted. The
scene differs on purpose (`scene_skipped_ambiguous`, below). A builder must not "align" the two; pinned by
`::test_two_owner_intents_music_once_scene_ambiguous`.

**Welcome scene (review H2 of rev 3): a per-person override inside the room's own entry scene path.** No second scene
call, no new lighting writer, no manual hold.
- The engine exposes a synchronous decision call, `arrival_scene_for(room_entry_id) -> str | None` (re-review L6: it
  is not read-only; a non-None return marks that intent's scene as decided-pending-result). In
  `_maybe_activate_slot_scene` (`automation.py:1740`), on the day / evening caller (`:1585`) only, the entry path looks
  up the engine as `hass.data[DOMAIN].get("music_following")` (None -> no override, today's path) and calls it with
  `self._config_entry.entry_id`, the room entry_id the engine already holds, before `slot_scene(...)`:
  `scene_id = arrival_scene_for(room) or slot_scene(self.config, slot)`. Everything after is the existing path: the
  manual-hold check (`:1766`, a held light skips the scene and the per-light path runs), the scene-state guard
  (`:1777`), one URA-context `scene.turn_on` (`:1796`). The sleep caller (`:1482`) never calls it.
- `arrival_scene_for(room)` returns the scene when all hold, else None:
  1. exactly one owner of this room has an open intent with the scene not yet decided (two -> None,
     `scene_skipped_ambiguous`);
  2. toggles re-read now (re-review M5): master, `_coordinator_enabled()`, that owner's fresh `auto_scene` and
     `welcome_scene` set; any off -> None, `scene_skipped_toggled_off`;
  3. **near check (re-review H2; rev 3.3 re-check H3).** The room's vacant-to-occupied edge comes from a body sensor
     (BLE extends occupancy but never creates it, presence state of play §4.6), so BLE usually has not placed the
     person in the room yet at that moment (the lag is measured by D0 a2), and "nobody else placed here" alone is
     blind: a co-owner or a guest walking in first would get the holder's scene. So the holder's own
     layer room R, read now (`get_person_location`), must be near this room:
     - **Default rule (until §12 Q4 is answered): same house zone.** R is this room, or `presence.get_room_zone(R)` is
       not None and equals `presence.get_room_zone(this_room_name)` (`presence.py:3477`; membership only, the NM panel
       targeting precedent, no side effects, no other consumer touched). `this_room_name` is the room entry's
       `data[CONF_ROOM_NAME]`, the key `_room_to_zone` uses (`presence.py:3627`), not the title or options; R is the
       person coordinator's room name, which uses the same names (`person_coordinator.py:1614-1616`). A room renamed
       through options keeps its old name in the zone map (presence §9, ZONE-ROOM-NAME-DRIFT-1), so the lookup returns
       None and reads `scene_skipped_not_near`: fails safe.
     - Not the default: adjacency (`get_adjacent_rooms`, both directions). Live `CONF_ADJACENT_ROOMS` is too sparse to
       carry the scene (table below): only the master has its hallway mapped, so under adjacency Ziri's scene runs only
       when BLE beats the radar into the room and Jaya's only when she comes in through her bathroom.
     - Any other room, a room with no zone, or `away` / `unknown` -> None, `scene_skipped_not_near`.
     - D0 (a2) reports the pass share per bedroom under adjacency as configured, adjacency plus the approach hall, and
       same house zone; the operator picks under §12 Q4.

     Live `adjacent_rooms` (`core.config_entries`, read 2026-11-14 by the re-check):

     | Room | Adjacency (configured) |
     |---|---|
     | Master Bedroom | Master Hallway, Master Bathroom |
     | Master Bathroom | Master Bath Toilet, Master Bedroom |
     | Jaya Bathroom | Jaya Bedroom |
     | Jaya Bedroom | none (adjacent only through the reverse read of Jaya Bathroom) |
     | Ziri Bedroom (Bedroom 5) | none |
     | Guest Bedroom 1, Guest Bedroom 2 | none |
     | every hall, staircase and other room | none |

     Live house zones (Zone Manager `options.zones`, read by the 3.3 re-check), bedroom rows and their approaches:

     | House zone | Bedrooms | Halls / approach in the zone | Approach NOT in the zone |
     |---|---|---|---|
     | Master Suite (11 rooms, incl. Study A, Study B) | Master Bedroom | Master Hallway | none |
     | Upstairs (14 rooms, incl. Game Room, Media, Exercise Room) | Jaya Bedroom, Ziri Bedroom, Guest Bedroom 2 | Upstairs Hallway, Guest Bedroom 2 Hallway | Staircase, Kitchen / Garage Hallway (Back Hallway) |
     | Back Hallway (16, incl. Kitchen) | Guest Bedroom 1 | Staircase, Garage Hallway, Kitchen Hallways | none |
     | (no zone) | none | Garage A, Garage B | — |

     Zone-rule cost by zone: in the Master Suite, a co-owner entering first while the holder is in a study gets the
     holder's scene (the shape "Shares spaces, likely same" accepts); in Upstairs, a sibling or guest entering Jaya's
     or Ziri's empty bedroom first while she is in the Game Room gets her scene (`scene_unconfirmed` unless she walks in
     within `ARRIVAL_SCENE_CONFIRM_S`). Guest rooms get no welcome scene (guests have no profile).

     Why adding adjacency config is not the default fix: `CONF_ADJACENT_ROOMS` has three other readers, and adding a
     hall to a bedroom changes each. The fan recheck L2 veto (a trusted phone in an adjacent room vetoes the bedroom's
     fan probe, `presence_fan_recheck.py:1396-1409`); the presence fan-interference gate's adjacency read (`presence.py`
     around `:4774`); NM wall-panel targeting (`notification_manager.py:6325-6327`). The zone rule reads a getter and
     changes none of them. Cost of the zone rule, stated: a holder placed anywhere in the bedroom's house zone (for
     example a hall or a sibling's room upstairs) passes, so a co-owner or guest entering first while the holder is
     elsewhere in that zone gets the holder's scene; item 4 (no other tracked person placed here) and
     `scene_unconfirmed` still apply;
  4. no other tracked person's layer room is this room (`scene_skipped_occupied`);
  5. not quiet hours, not house `sleep` / `waking` (`scene_skipped_quiet` / `scene_skipped_sleep`);
  6. that owner had no welcome scene within `ARRIVAL_MIN_GAP_S` (`scene_skipped_gap`);
  7. the room is one the scene may run in (§12 Q1 default: bedrooms only; a bathroom returns None with no scene
     outcome, so the scene ends at window end as `scene_window_expired`).
  The entry path itself runs only on the room's vacant-to-occupied edge and only when the room is not paused, so the
  onset leg of "occupied before" is false by construction and the paused gate is the room's own. A skip in 1-6 is the
  intent's terminal scene outcome: this entry was the room's one vacant-to-occupied edge, and the room now reads
  occupied, so no later entry follows inside the window.
- At return the engine records the decision: `scene_applied` when it returned a scene and the entry path's hold check
  and state guard passed (the engine learns this from a second call, `note_arrival_scene_result(room, applied: bool)`,
  made by `_maybe_activate_slot_scene` right after its decision), `scene_skipped_hold` when the hold check fell back,
  `scene_skipped_unavailable` when the state guard fell back. Then within `ARRIVAL_SCENE_CONFIRM_S` the layer must place the person in the room
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
| Intent (episode + line) | `intent_opened` (source, `music_on`, `scene_on`), `intent_lost_restart`, `scene_lost_restart` |
| Intent (counter only, no line) | `skipped_master_off`, `skipped_source`, `skipped_no_rooms`, `skipped_not_counted_return` (subtypes `no_departure_seen` / `recent_departure` / `not_counted`), `skipped_edges_truncated` (subtypes `boot` / `ring`; `boot` in the NM digest), `skipped_no_presence`, `intent_duplicate_source` (second source recorded) |
| Music | `started`, `start_failed`, `reversed`, `skipped_toggled_off`, `skipped_quiet`, `skipped_sleep`, `skipped_paused`, `skipped_occupied`, `skipped_gap`, `skipped_no_media`, `skipped_no_player`, `skipped_playing`, `window_expired`, `window_expired_truncated`, `entry_missed` (subtype `logged` / `unrecorded`) |
| Scene | `scene_applied`, `scene_confirmed`, `scene_unconfirmed`, `scene_skipped_hold`, `scene_skipped_unavailable`, `scene_skipped_ambiguous`, `scene_skipped_toggled_off`, `scene_skipped_not_near`, `scene_skipped_quiet`, `scene_skipped_sleep`, `scene_skipped_occupied`, `scene_skipped_gap`, `scene_window_expired`, `scene_window_expired_truncated`, `scene_entry_missed` |
| Departure | `departure_paused`, `departure_kept_returned`, `departure_kept_shared`, `departure_kept_occupied`, `departure_kept_not_ours`, `departure_kept_other_playing`, `departure_kept_toggled_off`, `departure_stamp_lost_restart` |

**Restart mid-window (re-review M5).** Intents are RAM. At engine setup, after the episode store is readable, the
engine reads `arrival_music` and `welcome_scene` episodes from the last `ARRIVAL_WINDOW_S` + 1 h. For every
`intent_opened` (same person and `opened_at`):
- with `music_on` and no later terminal music outcome -> `intent_lost_restart` (`arrival_music` episode and line);
- with `scene_on` and no later terminal scene outcome -> `scene_lost_restart` (`welcome_scene` episode and line;
  re-check M4).
Each is written once (the `departure_stamp_lost_restart` pattern). After setup, new F5s face the dead window in §5.4
gate 5 (15 min `ble` / `camera_egress`, 10 min `geofence`; fails closed, `skipped_edges_truncated` subtype `boot` in
the NM digest); departure pauses are unaffected. A restart therefore never leaves an opened intent without an outcome; the
action itself is not resumed (no music after a restart on a pre-restart F5).

**Every intent ends counted.** Exits and their outcomes: gates fire (§5.5 list); the window timer (§5.4 window end);
a second F5 (`intent_duplicate_source` on the second; the first intent runs on); a toggle turned off mid-window
(`skipped_toggled_off` / `scene_skipped_toggled_off` at the next check, or at window end if no check came); teardown
or reload (the restart rule above on next setup, music and scene); music following disabled (the toggle rule).

`room_disagree` (review M3 of rev 3) does not exist: there is one room source per action (§5.4), and the scene's
disagreement is `scene_unconfirmed`.

### 5.6 Departure pause

**Arm.** For a person with a live music stamp, the first of: a named exit at >= 0.75 (step 7 `departure_candidate`
or `attached`, via `get_last_crossing`) or their residency departure edge, delivered by
`subscribe_person_edges(hass, cb, persons={person_entity}, kinds={"departure"})` (ship 3a D2; the callback is sync and
only schedules, guard R14; no raw `person.*` listener). The edge arms a departure wait for that stamp (re-review M7)
of length = the stamped room's own `occupancy_timeout` (its room config, read at arm time) +
`ARRIVAL_DEPARTURE_VACANCY_WAIT_S` (the margin; re-check M2). Vacancy is roughly last body signal + room timeout, so a
fixed wait would be thin in the 500 s rooms (Jaya Bedroom, Ziri Bedroom: an LD2410 clear of up to 132 s p90 plus
500 s ≈ 10.5 min after she walks out, while a named exit at the garage arms 1-3 minutes after she leaves the bedroom).
The departure time recorded on the wait, `departure_ts`, is epoch seconds: the residency edge's `edge_ts` as is, or
the named exit's crossing time (a `datetime`) as `.timestamp()`, since step 0 passes it to `get_person_edges_since`. A second edge for the same stamp while armed is
ignored.

**Why a wait.** At the exit edge the room almost always still reads occupied: the bedroom's occupancy timeout, the BLE
chain hold and the 90 s absence grace (presence state of play §4.6) are still running when the person crosses the
garage door a minute or two later, and the person's own location stays on the room as STALE for up to
`decay_timeout`. A check only at the edge would end in `departure_kept_occupied` / `departure_kept_shared` on the
person themselves, and "Departure pause is fine" would be delivered in name only.

**Check.** While armed, on every person-coordinator update (the same listener as §5.4, kept registered while any wait
is armed; no new listener and no room-vacancy signal exists, §2) and once more at the wait's end (`async_call_later`,
cancelled at teardown), the engine checks in this order:
0. **returned (re-check M3).** `get_person_edges_since(departure_ts, persons={person_entity}, kinds={"arrival"})` is
   non-empty (any arrival edge, counted or not: a GPS flap `home -> not_home -> home` is exactly the case) ->
   `departure_kept_returned` (terminal). Without this a flap arms the wait, the person walks downstairs inside it, the
   room goes vacant and their music is paused while they are home. If `person_edges_truncated_since(departure_ts)` is
   True and the read is empty, the engine cannot rule a return out, so it fails closed the same way as the arrival
   side (no action on doubt): `departure_kept_returned` with subtype `truncated` (terminal; the plain case is subtype
   `edge`);
1. `ARRIVAL_MUSIC_DEPARTURE_PAUSE` and the master still on, and the person's fresh `auto_music` on; else
   `departure_kept_toggled_off` (terminal);
2. the stamped entity still plays the stamped `media_content_id`; else `departure_kept_not_ours` (terminal);
3. the other entity of the pair is not playing something else; else `departure_kept_other_playing` (terminal);
4. no tracked person OTHER than the departing one has this room as their layer room; the departing person's own
   (possibly STALE) location is excluded. If another is placed: wait on (not terminal; a co-owner may leave too);
5. the room coordinator reads not occupied (`data[STATE_OCCUPIED]` is not True, the read NM panel targeting uses). If
   it reads occupied: wait on.
When 0 does not end it, 1-3 hold and 4-5 pass on the same check: `media_player.media_pause` on the stamped entity,
URA context -> `departure_paused`. The first check that sees 4 and 5 pass after the room has been read occupied is the room's
occupied-to-vacant edge, so the pause lands within one person-coordinator interval of vacancy. At the wait's end with
4 or 5 still failing: `departure_kept_shared` (another person placed) or `departure_kept_occupied` (room occupied).

**Fan phantom, named (re-check M2).** Jaya Bedroom's LD2410 holds the empty room occupied 68 % of the time with the
fan on (presence state of play §6, ledger #1). A departure from that room with the fan running will often end
`departure_kept_occupied` with nobody home. That is the honest outcome (the engine cannot tell a phantom from a
person), not a defect of the wait; D0 (b) reports its share. Music left playing
in an empty room is the cost; AWAY handling does not change.

**Restart.** The stamp is RAM; a restart loses it, counted `departure_stamp_lost_restart` at setup from the last
`started` episode with no pause (unchanged). An armed wait lost to a restart is the same outcome. Not built:
last-resident arming (escalation, manual §5.5(a)); HVAC setback (AWAY does it); lights off (vacancy does it).

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
  (whether they were already there at intent open, moved in after, came from `"unknown"` after a restart for an F5
  outside the §5.4 post-restart dead window (at least 15 minutes after setup for `ble` / `camera_egress`, 10 for
  `geofence`), or returned
  on a ping-pong leg), with no other body there earlier than the lead, an idle player and no quiet hours, the music
  outcome is `started`, whatever the transition's classified confidence, the person's transfer enablement, any BLE
  distance, or whether the transfer detector notified. Break it with: the 4-hours-away first room, already-in-room at
  open, `previous_location="unknown"`, a ping-pong return leg, own motion 40 s before BLE, an area flip inside the
  room just before the F5, a BLE F5 whose move carries the same tick's `now`, and a 20 ft distance.
  **Dual (re-review H1; rev 3.3):** no `started` and no `scene_applied` for an F5 whose person was away less than
  `RESIDENT_RETURN_MIN_AWAY_MIN`: for `geofence`, no counted, non-stale, out-of-boot-window residency arrival within
  `ARRIVAL_COUNTED_EDGE_LOOKBACK_S` before it; for `camera_egress` and `ble`, no residency `left_at` at least
  `RESIDENT_RETURN_MIN_AWAY_MIN` before it with no later arrival (no departure seen at all included); for any source, a
  truncated edge log or the post-restart window. Break it with: Oji in the master an hour, GPS `home -> not_home ->
  home` in 40 s, geofence F5, idle speaker; Oji walks the dog 6 minutes, GPS `not_home`, Bermuda loses him > 300 s (S3
  sets `_person_was_away`), BLE F5 on return; Oji 20 minutes on the patio, BLE LOST, GPS `home` throughout, BLE F5 on
  coming in; a 6-minute walk whose person state goes `home -> unknown -> not_home`.
  **`camera_egress` reachability (rev 3.3):** a GPS-led step-7 confirmation for a person whose `left_at` is older than
  15 minutes, with no later arrival, opens an intent, although no arrival edge exists yet.
- **INV-V6-COUNTED.** Every F5 that passes the master is counted, and every opened intent ends in exactly one terminal
  music outcome and one terminal scene outcome (when the action is on) from §5.5, including across a restart or reload
  mid-window (`intent_lost_restart`, `scene_lost_restart`), a second F5 (`intent_duplicate_source`) and a toggle turned off mid-window
  (`skipped_toggled_off`); none ends silent.
- **INV-V6-NEVER-INTERRUPT.** No start on a room whose native player or MA entity is playing; no pause of playback URA
  did not start.
- **INV-V6-OCCUPIED.** No music start and no welcome scene into a room whose occupancy began earlier than the person's
  entry minus the lead, or in which another tracked person is placed (co-owner included). The entry time on an
  in-window path is never earlier than the cursor at open (§5.4 clamp), so a stale `previous_location_time` cannot
  hide an earlier occupant. No knob disables this. Break it with: resident `unavailable` while out (`location =
  unknown`), an untracked guest in their room 30 minutes, resident returns and BLE places them there.
- **INV-V6-QUIET.** No music and no welcome scene in quiet hours or house `sleep` / `waking`.
- **INV-V6-OFF-MEANS-OFF.** With a toggle off, nothing under it acts, whether the HA version hid and dropped its fields
  or kept them, and whether it was turned off before the intent opened or inside the window.
- **INV-V6-SCENE-OWNER.** A welcome scene applies only while its owner's layer room is near the room under the active
  near rule (default: the room or the same house zone, §5.5); a co-owner, guest or child walking in first while the
  owner is placed outside that rule or not placed gets the slot scene.
- **INV-V6-ONE-SCENE.** A room entry issues at most one `scene.turn_on`; the welcome scene replaces the slot scene when
  eligible, and a manual hold beats both.
- **INV-V6-NO-RELOAD.** A People save never reloads the CM entry.
- **INV-V6-AWAY.** No step-8 path reads or writes an `infer()` input, the census trust view, or HVAC.
- **INV-V6-LAYER.** Step 8 reads F5 only via `subscribe_person_arriving`; F1 edges only via `get_person_edges_since`,
  `person_edges_truncated_since`, `subscribe_person_edges` and `get_residency_snapshot`; person rooms only via `get_person_location`,
  `get_person_previous_location_time`, `get_person_previous_seen`, `location_moves_since` and
  `location_moves_truncated_since`, plus the reserved `async_add_listener`; room nearness only via `get_room_zone`
  (and `get_adjacent_rooms` if §12 Q4 picks adjacency). No
  raw `SIGNAL_PERSON_ARRIVING` connect, no raw `person.*` listener and no `person_coord.data` read remains in either
  music file; the layer guard test (ship 3a D7) covers both.
- **INV-V6-DEPARTURE-REACHES.** For a live stamp whose owner departs, with the stamp's content still playing, the
  other entity idle, no arrival edge of the owner since the departure, and the room going vacant with no other tracked
  person placed in it inside the wait (room `occupancy_timeout` + `ARRIVAL_DEPARTURE_VACANCY_WAIT_S`), the outcome is
  `departure_paused`, even though the room read occupied and the departing person's own location read this room at
  the exit edge. Break it with: room vacant 3 min after the exit, the person STALE in the room for 5 min, and a check
  only at the edge; and Jaya's named exit at the garage 2 min after she leaves her 500 s room, slow radar clear, room
  vacant 11 min after the arm. **Dual:** no `departure_paused` after an arrival edge of the owner since the departure. Break it
  with: GPS flap `home -> not_home -> home`, then Oji walks downstairs and the master goes vacant.
- **INV-V6-ONE-AMEND / NAME-BAR.** Arrival follow-ups only through the amend function; no text names below 0.75.

## 7. Producer and consumer checks; sites

Producers: geofence, BLE pre-arrival, step-7 `camera_egress`, all sent through `dispatch_person_arriving` and read
through `subscribe_person_arriving`; residency arrival and departure records (the counted-return gate and the
departure arm). Producer semantics (re-review H1): F5 means "a source thinks P is arriving", not "P was away"; the
counted-return gate is what makes it a physical return here. Producer health: the BLE F5 is gated today by
`pc._pre_arrival_enabled` (`person_coordinator.py:1128`, written from the HVAC pre-arrival switch), so with that switch
off BLE arrivals never reach step 8 until BLE-ARRIVAL-PRODUCER-HVAC-GATED-1 lands (§10). Fire check: 218 arrival
signals / 14 d (AUDIT_pre_arrival); D0 (a) measures how many are counted returns; BLE room moves fire continuously; the
arrival path itself has fired zero times (no-op handler). Trip-wires: `arrival_action_zero` (HIGH NM: >= 10 intents
with an own-room entry in 7 days and 0 `started` + `scene_applied`), `arrival_entry_missed` (HIGH NM: >=
`ARRIVAL_ENTRY_MISSED_NM` `entry_missed` (both subtypes) + `scene_entry_missed` in 7 days; this one sees the H1 class
directly, and its `unrecorded` subtype comes from a window-end location read the move-log path does not share, so the
trip-wire is not blind in the same place as the trigger; `window_expired` alone is benign: most arrivals go to the
kitchen), `arrival_music_failing` (HIGH NM: >= 3 `start_failed` in 24 h), `welcome_scene_failing`
(>= 3 `scene_unconfirmed` + `scene_skipped_unavailable` in 24 h). Forward trace: F5 -> intent -> layer room read ->
gates -> play / scene override -> verify -> episode -> departure -> pause. Consumers of the new store: the music
engine, the entry scene path (through `arrival_scene_for`), the profile sensor, the People step, and later OC and AI
room rules (read-only, through the sensor or `get_person_profile(person)`; no second store).

**Site enumeration (independent re-run of the review's list):**
1. The F5 read: the raw connect `MusicFollowingCoordinator.async_setup` `domain_coordinators/music_following.py:296`
   (deleted) and its handler `_handle_person_arriving` `:565`, replaced by the `subscribe_person_arriving` callback
   (intent open, counted-return gate).
2. The new person-coordinator listener, the open-time read and the window-end re-read (§5.4); the departure checks on
   the same listener (§5.6). `_on_person_transition` (`music_following.py`) is NOT a site: no arrival code goes there
   (mutation drill below).
2a. The `subscribe_person_edges` departure callback (§5.6); the `get_person_edges_since` reads: arrival kinds for
    `geofence` (§5.4 gate 5), the `get_residency_snapshot` `left_at` / `arrived_at` read for `camera_egress` / `ble`, arrival kinds for the departure wait's
    return check (§5.6 step 0); `person_edges_truncated_since` beside each.
2b. `arrival_scene_for`'s near check and its `get_room_zone` reads (§5.5; `get_adjacent_rooms` only if §12 Q4 picks
    adjacency).
2c. The departure wait length read of the room's `occupancy_timeout` (§5.6).
3. Detector suppressors `transitions.py:177`, `:182`, `:188`, `:206`, `:240`: untouched, and irrelevant by design;
   tests drive each to prove the arrival still starts.
4. `_maybe_activate_slot_scene` `automation.py:1740` (override read and result note), callers `:1585` (reads) and
   `:1482` (must not read).
5. The LightPolicyOracle writer `automation.py:811` `note_manual_light`: must have no new caller (guard grep test).
6. Every `media_player.*` / `music_assistant.*` / `scene.turn_on` call in both music files (all with `ura_ctx_kwargs`).
7. The options-save path (`__init__.py`, subset decision; re-grep) and the master form `config_flow.py:10383-10384`
   (repair branch; develop `:10509-10510`).
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
`entry_missed`. Oji in the master an hour, GPS flaps `home -> not_home -> home`, geofence F5 -> no intent,
`skipped_not_counted_return`, nothing plays (without the gate: `started` on a person who never left: discriminates).
Step-7 `camera_egress` F5, raw `person.*` still `not_home`, last departure 2 h ago, no arrival edge yet -> intent opens
and music starts in the master (an arrival-edge test: `skipped_not_counted_return` on every egress F5: discriminates).
Oji walks the dog 6 min, S3 sets `_person_was_away`, BLE F5 on return -> `skipped_not_counted_return` (trusting the
producer guard: `started`: discriminates). Oji 20 min on the patio, BLE LOST, GPS `home` throughout, BLE F5 on coming
in -> `skipped_not_counted_return` subtype `no_departure_seen`, nothing plays (empty read passes: `started` on a
person who never left: discriminates). `home -> unknown -> not_home` walk, BLE F5 -> same. GPS stuck `home`, BLE
overrule held 20 min, BLE F5 -> no intent (accepted cost); the later geofence F5 opens it. BLE F5 10 min after a
restart -> `skipped_edges_truncated` subtype `boot`. Geofence F5 arrives while a `camera_egress` intent is open -> `intent_duplicate_source` (gate order
reversed: `skipped_not_counted_return`: discriminates). Resident `unavailable` while out, guest in their room 30 min,
BLE places them there -> `skipped_occupied` (unclamped entry time: `started`: discriminates). Geofence F5 whose move
into the master landed 20 s before `t_f` -> one music outcome (no "only while undecided": a second `skipped_gap` /
`skipped_playing`: discriminates).
BLE F5 whose move carries the same tick's `now`, earlier than `t_f` -> the move is kept and music starts (cursor at
`t_f`: the move is excluded and only the re-read saves it, with no entry time: discriminates). Area flip inside the
master 10 s before the F5 -> `started` (entry time from `previous_seen`: `skipped_occupied` on himself:
discriminates). Person-coordinator reload mid-window -> `moves_truncated`, and window end with no own room ->
`window_expired_truncated`. Person in the master at window end but the log never recorded the entry ->
`entry_missed` subtype `unrecorded`. Restart mid-window -> `intent_lost_restart` at setup. Second F5 (BLE after
geofence) -> `intent_duplicate_source`, one intent. `auto_music` turned off after the intent opened ->
`skipped_toggled_off`. Tests: `test_arrival_music.py::test_first_room_after_hours_away_starts`,
`::test_gps_flap_while_in_room_opens_no_intent`, `::test_edges_truncated_fails_closed`, `::test_ble_f5_same_tick_move_not_lost`,
`::test_cursor_strictly_after_first_read`, `::test_area_flip_inside_room_does_not_self_block`,
`::test_moves_truncated_window_expired_truncated`, `::test_window_end_reread_entry_missed_unrecorded`,
`::test_intent_lost_restart_counted`, `::test_second_f5_duplicate_source_counted`,
`::test_toggle_off_mid_window_skips`, `::test_two_owner_intents_music_once_scene_ambiguous`,
`::test_camera_egress_departure_older_than_bar_opens_intent` (replaces the rev 3.2
`::test_counted_return_required_for_geofence_and_camera_egress`, which could not pass against step 7 semantics),
`::test_counted_return_required_for_geofence`, `::test_camera_egress_recent_departure_skipped`,
`::test_short_walk_ble_f5_opens_no_intent`, `::test_ble_lost_at_home_no_departure_opens_no_intent`,
`::test_departure_via_unknown_opens_no_intent`, `::test_ble_overrule_only_absence_opens_no_intent_accepted`,
`::test_ble_f5_within_15min_of_setup_fails_closed`, `::test_geofence_within_boot_window_fails_closed`,
`::test_edges_truncated_boot_subtype_in_digest`, `::test_duplicate_checked_before_counted_return`,
`::test_unknown_to_room_mid_window_prior_occupant_blocks`, `::test_music_check_runs_once_per_intent`,
`::test_scene_lost_restart_counted`,
`::test_stale_resident_blocks_accepted`, `::test_subscribe_person_arriving_only_no_raw_connect`,
`::test_intent_opens_with_person_already_in_own_room`, `::test_entry_after_restart_unknown_previous_location`,
`::test_ping_pong_return_leg_still_starts`, `::test_no_hook_in_on_person_transition`,
`::test_no_distance_read_on_arrival_path`, `::test_own_motion_before_ble_does_not_block`,
`::test_occupant_before_lead_blocks`, `::test_only_own_rooms_trigger`, `::test_never_interrupts_native_or_ma_playing`,
`::test_coowner_present_skips`, `::test_quiet_and_sleep_skip`, `::test_face_alone_opens_no_intent`,
`::test_gps_confirmed_camera_egress_opens_intent`, `::test_pick_media_precedence`, `::test_slot_from_room_resolve_slot`,
`::test_verify_on_player_state`, `::test_ma_first_native_fallback`, `::test_no_bonus_joins`, `::test_reversal_counted`,
`::test_window_expired_vs_entry_missed`, `::test_every_intent_ends_counted`, `::test_zero_fire_tripwire`,
`::test_entry_missed_tripwire`, `::test_listener_removed_when_no_intents_and_at_teardown`. Restart with `auto_scene` on
before the room entry -> `intent_lost_restart` and `scene_lost_restart` at setup. Config extremes: window 0;
lead 0 and lead 600; lookback 0 (no geofence intent ever opens) and 900; volume 0.05 / 1.0 with scale 1.5; rooms
empty; own room with no player. Live: first opted-in arrival gives `started` (music audible) or a named skip in the
decision log; zero `entry_missed`; the diagnostics counters show `skipped_not_counted_return` for any geofence flap
that day and no `started` paired with it.

**D3 welcome scene.** Verify: same arrival with `auto_scene` and a slot scene configured for the master -> exactly one
`scene.turn_on`, the welcome scene (without the override: the slot scene applies: discriminates) -> `scene_applied`
then `scene_confirmed`; no slot scene configured -> the welcome scene still applies; a light under a manual hold ->
`scene_skipped_hold` and the per-light path runs; co-owner placed in the room -> `scene_skipped_occupied`, slot scene
applies; speaker playing -> scene applied, music skipped; bathroom entry -> slot scene (§12 Q1 default); sleep caller
never reads the override; nobody confirmed in the room within the window -> `scene_unconfirmed`. Oji's intent open,
Oji placed in a room outside the master's house zone, Ezinne walks into the master first -> `scene_skipped_not_near`, slot scene
applies (without the near check: Oji's scene for Ezinne: discriminates); Ziri placed in a hall in Ziri Bedroom's house
zone (no adjacency configured, fixture zone map) when the radar fires -> welcome scene (adjacency rule:
`scene_skipped_not_near`: discriminates); Oji placed in a room of another house zone -> `scene_skipped_not_near`; R
with no zone -> `scene_skipped_not_near`; Oji `unknown` -> `scene_skipped_not_near`; `auto_scene` turned off mid-window -> `scene_skipped_toggled_off`; no engine in
`hass.data` -> slot scene, no error. Tests: `::test_coowner_enters_first_holder_elsewhere_slot_scene`,
`::test_holder_same_house_zone_gets_scene`, `::test_holder_other_zone_not_near`, `::test_room_without_zone_not_near`,
`::test_near_rule_reads_no_adjacency_by_default`, `::test_holder_unknown_not_near`, `::test_scene_toggle_off_mid_window`, `::test_no_engine_falls_back_to_slot_scene`,
`test_welcome_scene.py::test_entry_override_replaces_slot_scene`, `::test_one_scene_call_per_entry`,
`::test_welcome_without_slot_scene`, `::test_manual_hold_blocks_welcome_scene`, `::test_scene_shared_gates`,
`::test_scene_independent_of_music_outcome`, `::test_sleep_caller_never_reads_override`,
`::test_scene_unconfirmed_counted`, `::test_scene_ambiguous_two_owner_intents`, `::test_no_new_note_manual_light_caller`,
`::test_scene_rooms_default_bedrooms_only`. Live: first opted-in arrival gives `scene_applied` + `scene_confirmed` and
one "Room entry [...]: activating ... scene=<welcome>" log line, no second scene line.

**D4 departure pause.** Verify: named exit at 0.9, stamp live, room still occupied at the edge and the person STALE
in it, room goes vacant 3 min later -> `departure_paused` within one person-coordinator interval of vacancy (a check
only at the edge: `departure_kept_occupied`: discriminates); room still occupied at the wait's end ->
`departure_kept_occupied`; another person placed through the wait -> `departure_kept_shared`; track changed ->
`departure_kept_not_ours`; pause toggle turned off during the wait -> `departure_kept_toggled_off`; residency
departure edge (no named exit) arms the same wait; restart in between -> `departure_stamp_lost_restart`. Jaya's named
exit 2 min after she leaves her 500 s room, slow radar clear, room vacant 11 min after the arm -> `departure_paused`
inside the 800 s wait (rev 3.2's fixed 600 s wait: `departure_kept_occupied`: discriminates). GPS flap arms the wait, Oji walks
downstairs, master vacant -> `departure_kept_returned`, nothing paused (no return check: `departure_paused` on a person
at home: discriminates). Edge log truncated and empty at the return check -> `departure_kept_returned` subtype
`truncated`. Tests: `::test_departure_named_exit_arm_room_timeout_500`, `::test_flap_departure_then_return_does_not_pause`,
`::test_departure_return_check_truncated_fails_closed`, `::test_departure_wait_is_room_timeout_plus_margin`,
`::test_named_exit_arm_return_check_uses_epoch`, `::test_departure_pause_after_restart_not_blocked_by_truncation`,
`::test_departure_pauses_when_room_empties_after_exit`, `::test_departing_person_stale_ble_excluded`,
`::test_departure_wait_ends_kept_occupied`, `::test_departure_pauses_own_playback`,
`::test_departure_never_pauses_others`, `::test_departure_on_residency_edge_via_subscribe`,
`::test_departure_toggle_off_during_wait`, `::test_stamp_lost_restart_counted`. Config extremes: margin 0 (wait =
room timeout) and 3600; a room with `occupancy_timeout` 0 and margin 0 (one check at the edge, rev 3.1 behaviour). Live: first departure after a start gives `departure_paused` or a kept reason with the room's
occupied state at the wait's end in the decision line.

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
0.6 name. Added in rev 3.2: drop the counted-return check (open on any geofence F5); start the cursor at `t_f`; use
`>=` on later passes (double read); ignore `location_moves_truncated_since`; read `previous_seen` first for entry
time; drop the window-end location re-read; drop `intent_lost_restart` at setup; read toggles only at open; drop the
near check from `arrival_scene_for`; check departure only at the edge; count the departing person in the "tracked
person here" check. Added in rev 3.3: test arrival edges (not departure edges) for `camera_egress`; trust the BLE
producer's guard (skip the departure read for `ble`); pass on a truncated empty departure read; move the duplicate
check after the counted-return gate; drop the entry-time clamp on the re-read; let the listener run the music check
when the slot is decided; drop `scene_lost_restart` from the sweep; use a fixed wait without the room timeout; drop
the departure return check; compare zones with `None == None` passing (room without zone). Added in rev 3.4: pass
on an empty departure read / missing `left_at` (the patio LOST case must go RED); ignore `arrived_at` newer than
`left_at`; drop the `boot` subtype; pass the named exit's `datetime` to the edge read. The rev 3.2 drill "read
adjacency in one direction only" is retired with the default (it returns if §12 Q4 picks adjacency).

## 9. Knobs

| Knob | Default | Rung | Why / kill |
|---|---|---|---|
| `CONF_MUSIC_ON_ARRIVAL_START` (REUSED, relabelled "Arrival actions") | on (consumer and form default; unset live) | 2 | House master for music and scene; off = no intents |
| Profile fields (§5.1) | all off / empty; volume 0.30 | 2 (People) | Per-person opt-in per action |
| `ARRIVAL_WINDOW_S` | 900 (D0 sizes) | 1 | 0 = never act |
| `ARRIVAL_OCCUPIED_LEAD_S` | 120 (D0 a2 sizes) | 1 | How far before the person's BLE entry a room onset counts as "someone else first". Review-only: too large lets an earlier occupant through. Not a kill switch; the occupied rule has none |
| `ARRIVAL_SCENE_CONFIRM_S` | 120 (D0 a2 sizes) | 1 | Wait for the layer to place the person after a scene; counting only |
| `ARRIVAL_MIN_GAP_S` | 3600 | 1 | No repeat on a door bounce; per person per action |
| `ARRIVAL_COUNTED_EDGE_LOOKBACK_S` | 120 (D0 a sizes) | 1 | How far before a `geofence` F5 a counted residency arrival may sit (the edge is written in the same call). Review-only: too large lets an old return vouch for a later flap. 0 = no geofence intent ever opens (`camera_egress` and `ble` unaffected; they use the departure-side bar) |
| `RESIDENT_RETURN_MIN_AWAY_MIN` (REUSED, `const.py:4109`) | 15 | 1 | The `camera_egress` / `ble` bar: `left_at` must be at least this old, no later arrival; also the post-restart dead window for those sources. Shared with residency and the lock; not re-tuned here |
| `RESIDENT_RETURN_BOOT_WINDOW_S` (REUSED, `const.py:4110`) | 600 | 1 | Post-restart `geofence` dead window (arrivals carry `in_boot_window`). Shared; not re-tuned here |
| `ARRIVAL_DEPARTURE_VACANCY_WAIT_S` | 300 (D0 b sizes, per arming source) | 1 | Margin added to the stamped room's own `occupancy_timeout`: wait = timeout + margin. 0 = wait exactly the room timeout. The pause's kill switch stays `ARRIVAL_MUSIC_DEPARTURE_PAUSE`. Default 300 gives 800 s in the 500 s rooms and 600 s in the 300 s rooms (rev 3.2's flat 600 in those) |
| `ARRIVAL_VERIFY_S` / `ARRIVAL_REVERSAL_S` | 20 / 120 | 1 | Ground-truth windows |
| `ARRIVAL_MUSIC_DEPARTURE_PAUSE` | True | 1 | False = no departure action |
| Trip-wire thresholds | 10 / 7 d; `ARRIVAL_ENTRY_MISSED_NM` 3 / 7 d; 3 / 24 h | 1 | 0 = off |

Removed: `ARRIVAL_MUSIC_ALLOW_SHARED_ROOM` (rev 3; operator: no exception), `ARRIVAL_SCENE_SETTLE_S` (rev 3.1; the
scene now rides the entry path, nothing to wait for), `switch.ura_music_arrival_start` (rev 3.1; never existed).

## 10. Dependencies, seams, sequence

Must ship before v6.0.0: step 6 census deconfliction; step 7 (amend function, confirmed names, `camera_egress`,
`departure_candidate`); **layer ship 3a** (D1 `subscribe_person_arriving`; D2 `get_person_edges_since`,
`person_edges_truncated_since`, `subscribe_person_edges`; D4 `location_moves_since`, `location_moves_truncated_since`;
D7 guard test); MUSIC-FOLLOWING-TRANSFER-REPAIR-1 D0, D3-D7; **BLE-ARRIVAL-PRODUCER-HVAC-GATED-1** (operator pick A,
ship 3 §14 Q4). Today the BLE F5 is sent only while `pc._pre_arrival_enabled` (`person_coordinator.py:1128`), which
mirrors the HVAC pre-arrival switch, so with that switch off no BLE arrival reaches step 8. The card makes the BLE
producer independent of the HVAC switch; it lands before v6.0.0, and step 8 adds no workaround (it does not read the
HVAC switch or `_pre_arrival_enabled`).

**Guard entries (ship 3a D7 allowlist), changed in step 8's D2 commit, never in the §10.1 parallel set.** Checked
against ship 3a as built (read-only, worktree `agent-aa1d30dcca08c1676`, `feature/layer-ship3a`; re-check LOW-3). The
allowlist file `quality/tests/person_awareness_layer_allowlist_PROVISIONAL.py` has two structures: `ROWS` (dict of
`{'max', 'group', 'reserved', 'explained'}`, whose `max` values sum to `LAYER_ALLOWLIST_TOTAL`, asserted at
`test_person_awareness_layer_guard.py:62-63`) and `LISTED` (plain key -> count), with `LISTED_RESERVED` naming `LISTED`
keys that `_listed()` filters out (`test_person_awareness_layer_guard.py:46`). Both R10 entries step 8 touches are in
`LISTED`, so neither changes the total:
- retire the `LISTED` key `('R10', 'domain_coordinators/music_following.py',
  'MusicFollowingCoordinator.async_setup:ura_person_arriving')` (the raw connect is deleted). This does not lower
  `LAYER_ALLOWLIST_TOTAL`, which counts `ROWS` only;
- un-reserve the `LISTED` key `('R10', 'music_following.py', '<step 8 §5.4 music listener>:async_add_listener[PC]')`:
  rename the key to the real qualified symbol of the function that registers the listener and remove its entry from
  `LISTED_RESERVED`, in the same commit. Until that commit the real listener is an unlisted hit, which matches §10.1
  (registration and entry change land together after 3a merges);
- the `subscribe_person_arriving` and `subscribe_person_edges` callbacks are listed under their own rules as ship 3a
  defines them (R10 / R14);
- `get_person_edges_since`, `person_edges_truncated_since` and `subscribe_person_edges` are already in
  `READ_LIST["PRESENCE"]` (`quality/tests/_layer_guard_engine.py:84-94`). `get_room_zone` (the §5.5 default) and
  `get_adjacent_rooms` (only if §12 Q4 picks it) are NOT; ship 3a phase 2 landed its final allowlist without them
  (`0b7d5061`). **Owner: step 8's D2 commit** adds `get_room_zone` to `READ_LIST["PRESENCE"]` in
  `quality/tests/_layer_guard_engine.py` (not the PROVISIONAL allowlist file §10.1 forbids) and to the contract §4
  PRESENCE read list (`CONTRACT_person_awareness_layer.md`) together, as a membership read with the NM panel targeting
  precedent; `get_adjacent_rooms` the same way only if Q4 picks adjacency. Not a new `ROWS` row: a new row would raise
  a total that may only fall. `get_residency_snapshot` is already listed.
**Repair-plan seam (arc rule 6).** (1) D7 item 3 keeps `music_on_arrival_start` as the arrival master, relabelled
(amendment to `PLANNING_music_following_repair.md`, applied by this plan's D7). (2) The 8 ft gate is owned by the
repair: commit `706f7230` on `feature/music-following-repair` removed `ble_too_far`, the distance knob's form field,
live key and plumbing; the repair's room check reads `get_person_location` (`c5685b5f`). This plan's only obligation
is that the arrival path never reads distance (drill above). Seam with lighting: the welcome scene is a read inside
the existing entry scene path; no new lighting writer, no manual hold. Seam with G6-ONE-BLE-ROOM-READ-1: one call site
to swap (§5.4). Seam with AI room rules / OC: they read the profile, never write it. Arc map M11 updated at approval.
F-NOTIFY: the count follow-up waits for CD4; v6.0.0 does not.

### 10.1 What builds now (review G1)

**Base branch (re-review M4).** The step 8 branch (`feature/step8-identity-actions`) cuts from
`feature/music-following-repair` (`c5685b5f`), because the repair owns the music files, the music form
(`config_flow.py:10383-10384`), and already adds `music_on_arrival_start` to the reload-suppress set (`__init__.py`
`:7706` / `:8456` on that branch). If the repair has merged when a later step 8 branch is cut, cut from develop. D1
must not re-add `music_on_arrival_start` to the suppress set (it adds only `person_profiles`). No step 8 commit edits
the ship 3a allowlist file while 3a is PROVISIONAL; the D2 commit makes the guard-row changes above after 3a merges.
New step 8 code reads no `person_coord.data` (R2 group #23), only the named methods. The repair and 3a collide with
each other at the move site (`person_coordinator.py` `ura_person_location_change` payload versus the move log); that
merge belongs to whichever merges second, not to step 8.

Parallel with ship 3 and step 7, against stub signatures, on one branch: **D0** (probe, no code dependency); **D1**
(People step, store, sensor, master default, `_cond`, the B0 live spike); `pick_media` and its tests; the
`occupied_since()` accessor; `arrival_scene_for` / `note_arrival_scene_result` with the entry-path read in
`automation.py` (against a stubbed engine); D6 episode types. **D5** builds when step 7's amend function lands.
D2-D4's engine wiring builds against fakes with ship 3a's exact shapes (§2 rows; ship 3 §12): `subscribe_person_arriving`
(D1), `location_moves_since` / `location_moves_truncated_since` (D4, `datetime`), and `get_person_edges_since` /
`person_edges_truncated_since` / `subscribe_person_edges` (D2, epoch float, `ResidencyEvent` with `counted`,
`source_stale`, `in_boot_window`), plus `get_room_zone` (exists today). It starts only once rev 3.3 has the cursor,
gates and outcomes the fakes must encode (re-review §5 caution). Fakes must honour step 7 semantics: a
`camera_egress` F5 arrives with no residency arrival record for that person (re-check H1: a fake that writes one
first would hide the defect). Real calls switch in two steps: D1 and D4 reads when ship 3a phase 1 is on the base;
the counted-return gate and the departure edge when ship 3a D2 lands, which is phase 2, after census-p2 (ship 3 §11).
The layer guard test lands with ship 3a. No raw
signal path is added as a fallback (that would recreate drift #16). If ship 3 slips, v6.0.0 slips with it, and the
orchestrator tells the operator with the date rather than shipping a raw-signal variant.

## 11. Tier

Tier 2-DB (operator yes): three framing-disjoint code reviews (A gates, payloads, pick precedence, outcome contract;
B integration, restart, options save, listener lifecycle, entry scene path, cursor and truncation, departure wait;
C per-site mutation) plus a focused check of the rev 3.3 edits (§5.4 gates 4-5 and entry clamp, §5.5 near check and
restart, §5.6, §9, §10) with framing G before the D2-D4 wiring builds. P2-D9 keeps the crossing-vision plan's own bar. Release v6.0.0 at
deploy.

## 12. Remaining operator questions (recommended defaults; built as the defaults until answered)

1. Bathrooms trigger arrival actions? Default: bathrooms get music only; the welcome scene runs in bedrooms only.
2. Should an arrival into a room that is not yours but empty (the family room) play anything? Default no: own rooms
   only. Saying yes adds one toggle "Also in empty shared spaces".
3. Welcome scene outside an arrival (any entry into your room after 15 min away)? Default no: arrival only.
4. **How near must the scene's holder be when their bedroom lights up?** (rev 3.3, re-check H3.) Under today's sparse
   `CONF_ADJACENT_ROOMS` (§5.5 table), "this room or an adjacent room" gives Ziri and Jaya almost no welcome scenes.
   Options:
   - (a) **same house zone** (`get_room_zone`): reuses a getter, touches no other consumer. It trades against Q5 ("don't
     do it when someone is already in that room") for the scene: in the Master Suite a co-owner, in Upstairs a sibling
     or guest, entering first while the holder is elsewhere in the zone can get the holder's scene (§5.5 zone table).
     It still misses when BLE has an upstairs resident on the Staircase (Back Hallway);
   - (b) **add adjacency** (map each bedroom's approach hall in the room options): tighter, but `CONF_ADJACENT_ROOMS`
     also drives the fan recheck L2 veto (a phone in the hall would veto the bedroom's fan probe), the presence
     fan-interference gate and NM wall-panel targeting, so all three change too;
   - (c) **accept fewer scenes** under adjacency as configured.
   **Default, built until answered: (a) same house zone.** D0 (a2) reports the per-bedroom pass share under all three
   so the answer rests on numbers.

## 13. Non-goals

Per-person temperature (cut; "the exclusion is fine"); guest-gate door identity; predictions writing profile fields
(they suggest only); actions for guests or untracked people; transfers (the music repair owns them, and the 8 ft gate's
removal); any security, lock, HVAC or house-state consumer; Protect names; interior vision (step 9); a trial or shadow
stage; a room-entry "owners" field; re-applying the welcome scene mid-occupancy (nothing re-applies a slot scene
either); building `persons_in_room` (G6-ONE-BLE-ROOM-READ-1).

## 14. Plan completion tracking

Built here: the full PERSON-PROFILE-PREFERENCES-1 scope (rooms, owners, music by time and room, per-action opt-in,
welcome scene), arrival music, departure pause, P2-D9 wiring, episodes, docs. Nothing from the card is parked
(rev 3.3: `camera_egress` reaches arrival actions again, and the welcome scene reaches every bedroom resident under
the §12 Q4 default).
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

### 15.3 Changes from rev 3.1 (review `PLANREVIEW_identity_actions_v6_3_1.md`)

The §10.1 parallel set's design is unchanged: D0's (a) and (a2) and (b) gain measurement rows only, the D1 People
step, store, sensor, `_cond`, `pick_media`, `occupied_since()`, the automation-path call and D6 types are as in rev
3.1. Every rev 3.1 operator ruling holds: Q1 Tier 2-DB, Q2 6.0.0 = step 8, Q4 v6.0.0 before F-NOTIFY, Q5 no action
when anyone else is in the room (now also for the scene at entry time), Q6 departure pause on (now delivered), the
profile pull-ins, the temperature cut, form field hiding, and the three §12 defaults.

| Finding | Rev 3.1 | Rev 3.2 |
|---|---|---|
| H1 non-arrival F5 | Intent on any `geofence` / `ble` F5 | Intent only on a counted return: `geofence` / `camera_egress` need a `get_person_edges_since` record with `counted`, not `source_stale`, not `in_boot_window` within `ARRIVAL_COUNTED_EDGE_LOOKBACK_S`; `ble` relies on the producer's was-away guard; truncated edges fail closed; `skipped_not_counted_return` / `skipped_edges_truncated`; D0 (a) row; dual of INV-V6-ARRIVAL-REACHES; test `::test_gps_flap_while_in_room_opens_no_intent`; drill. Lands with ship 3a D2, phase 2 (§5.4, §10.1) |
| H2 scene recipient | "No other tracked person placed" only, blind at entry time | Near check: holder's layer room is this room or adjacent under `get_adjacent_rooms`, both directions (existing `CONF_ADJACENT_ROOMS`, no new map); `scene_skipped_not_near`; D0 (a2) coverage row, a large miss goes to the operator; INV-V6-SCENE-OWNER; test `::test_coowner_enters_first_holder_elsewhere_slot_scene`; drill (§5.5) |
| M1 cursor | Unspecified | Start `t_f - update_interval` (BLE F5 is sent before the tick commits); first read inclusive, then `move.ts > cursor`; entry time on the re-read path named; test `::test_ble_f5_same_tick_move_not_lost` (§5.4) |
| M2 truncation; stale cite | Not called; ship 3 cited at `50f15517` | `location_moves_truncated_since(cursor)` each pass; `moves_truncated`; `window_expired_truncated` / `scene_window_expired_truncated`; added to INV-V6-LAYER; ship 3 cited at rev 3.4.1 `4d6a3daf` |
| M3 entry time | `get_person_previous_seen` (area sensor, resets on an area flip) | `get_person_previous_location_time`, fallback `previous_seen` when None; test `::test_area_flip_inside_room_does_not_self_block` |
| M4 base branch | Unnamed | §10.1: cut from `feature/music-following-repair`; develop once merged; no duplicate suppress-key add; no allowlist edits in the parallel set; no `person_coord.data` reads |
| M5 silent exits | Restart, second F5, toggle-off mid-window ended silent | `intent_opened` episode at open and `intent_lost_restart` at setup; `intent_duplicate_source`; toggles re-read at check time (`skipped_toggled_off`, `scene_skipped_toggled_off`, `departure_kept_toggled_off`); INV-V6-COUNTED and INV-V6-OFF-MEANS-OFF widened |
| M6 layer seam | F5 named as the send; raw connect kept; reserved row unnamed; HVAC-gated BLE card absent | `subscribe_person_arriving`; raw R10 row retired; reserved listener row un-reserved by its real symbol in the D2 commit; BLE-ARRIVAL-PRODUCER-HVAC-GATED-1 in §10's before-v6.0.0 list |
| M7 departure pause | One check at the edge | Arm on named exit or `subscribe_person_edges` departure; wait `ARRIVAL_DEPARTURE_VACANCY_WAIT_S` (rung 1, 600, D0 b sizes); pause at the room's occupied-to-vacant edge; departing person's own STALE location excluded; INV-V6-DEPARTURE-REACHES; test `::test_departure_pauses_when_room_empties_after_exit`; drill. Departure edge is now the layer F1 read, not a raw `person.*` listener |
| L1 `entry_missed` blind spot | Same move log as the trigger | Window-end `get_person_location` re-read: `entry_missed` subtype `unrecorded`, same trip-wire |
| L2 `skipped_no_media` at save | Outcome only | Outcome kept. The save-time refusal / description warning is a D1 People-step change, so it is NOT edited here (D1 is being built); offered to the D1 builder through the orchestrator as an optional LOW |
| L3 two owners, music | Unstated | Asymmetry stated in §5.5 and pinned by `::test_two_owner_intents_music_once_scene_ambiguous` |
| L4 stale persons block | Implicit | Accepted by name in §5.4; test `::test_stale_resident_blocks_accepted` |
| L5 stale cites | `109ef2c9` lines | Re-cited at the repair base `c5685b5f` (develop lines given where they differ: master form `config_flow.py:10509-10510`, `const.py:4935`); builder re-greps |
| L6 wording | "read-only" `arrival_scene_for`; lookup unnamed | Named a decision call; lookup `hass.data[DOMAIN].get("music_following")`, None -> slot scene; room key `self._config_entry.entry_id` |
| Tier | Re-review of §5.4-§5.5 | Re-review of §5.4-§5.6 and §10 |

### 15.4 Changes from rev 3.2 (re-check `PLANREVIEW_identity_actions_v6_3_2.md`, `67374ce8`)

The §10.1 parallel set's design is unchanged: D0 gains measurement rows only ((a) by source on the departure side,
(a2) three near rules per bedroom, (b) split by arming source and room); the D1 People step, store, sensor, `_cond`,
`pick_media`, `occupied_since()`, the `automation.py` entry-path call and D6 types are as in rev 3.2. Every confirmed
operator ruling holds: Q1 Tier 2-DB, Q2 6.0.0 = step 8, Q4 v6.0.0 before F-NOTIFY, Q5 no action when anyone else is
in the room (now also for an untracked occupant on the re-read path, M1), Q6 departure pause on, the profile pull-ins,
the temperature cut, form field hiding, and §12 Q1-Q3 defaults. New §12 Q4 (default same house zone).

| Finding | Rev 3.2 | Rev 3.3 |
|---|---|---|
| H1 `camera_egress` unreachable | Gate needed a counted arrival edge in `[t_f - 120 s, t_f]`; step 7 sends only while raw `person.*` is not `home` (`PLANNING_egress_direction_aware_identity.md:591-598`), so none exists | Departure-side rule: reject if `get_person_edges_since(t_f - RESIDENT_RETURN_MIN_AWAY_MIN*60, kinds={"departure"})` holds a departure of the person; truncated + empty fails closed `skipped_edges_truncated`; lookback knob now `geofence` only; INV dual and reachability line; D0 (a) by source; test `::test_camera_egress_departure_older_than_bar_opens_intent` replaces the unpassable `::test_counted_return_required_for_geofence_and_camera_egress`; fakes must not pre-write an arrival record |
| H2 BLE S3 guard | "Same bar" via `_person_was_away` | Same departure-side rule for `ble`, in the engine; S3 setter cited (`person_coordinator.py:802-804` develop, `c5685b5f:766-768`); overrule-only absence keeps the overrule's 15-min guard (stated); test `::test_short_walk_ble_f5_opens_no_intent`, `::test_ble_overrule_only_absence_no_edge_opens_intent`; drill. `::test_ble_f5_skips_edge_read` removed |
| H3 (G) near check vs live adjacency | Adjacency only; remedy "configure adjacency" | Live adjacency table in §5.5; default near rule = same house zone via `get_room_zone`; D0 (a2) measures adjacency, adjacency + approach hall, same zone; §12 Q4 with the three readers adjacency config would also change; INV-V6-SCENE-OWNER and INV-V6-LAYER reworded; D3 tests re-derived |
| M1 unknown-entry onset hole | Residual "less likely to trip" | Entry time on in-window paths = max(value read, cursor at open); residual deleted; INV-V6-OCCUPIED break case; test `::test_unknown_to_room_mid_window_prior_occupant_blocks` |
| M2 wait vs 500 s timeouts | Flat 600 s | Wait = room `occupancy_timeout` + `ARRIVAL_DEPARTURE_VACANCY_WAIT_S` (margin, default 300); D0 (b) split by arming source and room; fan-phantom `departure_kept_occupied` named; test `::test_departure_named_exit_arm_room_timeout_500` |
| M3 flap-armed pause | No return exit | Step 0 return check: any arrival edge since the departure -> `departure_kept_returned` (truncated + empty -> subtype `truncated`); INV dual; test `::test_flap_departure_then_return_does_not_pause` |
| M4 scene restart outcome | Sweep wrote music only | `intent_opened` records `music_on` / `scene_on`; sweep also writes `scene_lost_restart`; outcome table; test `::test_scene_lost_restart_counted` |
| LOW-1 double music check | "Only while undecided" on the re-read only | One rule for every path; test `::test_music_check_runs_once_per_intent` |
| LOW-2 gate order | Duplicate check after counted return | Duplicate check is gate 4, counted return gate 5; test `::test_duplicate_checked_before_counted_return` |
| LOW-3 guard wording | `ROWS` entry with `reserved: False`; retiring lowers the total; adjacency row | `LISTED` key rename + `LISTED_RESERVED` removal; retiring changes no total (`ROWS` only); `get_room_zone` / `get_adjacent_rooms` proposed for the contract §4 PRESENCE read list, no new row (§10) |

### 15.5 Changes from rev 3.3 (re-check `PLANREVIEW_identity_actions_v6_3_3.md`, `94eb10c3`)

The §10.1 parallel set is unchanged (D0 gains rows only). Every confirmed operator ruling holds; §12 Q4 now states its
trade against Q5.

| Finding | Rev 3.3 | Rev 3.4 |
|---|---|---|
| M1 empty departure read passes | `ble` / `camera_egress` passed when no departure edge in the last 15 min | Positive evidence: `get_residency_snapshot` `left_at` ≥ 15 min before `t_f`, no later `arrived_at`; empty never passes (`no_departure_seen`); cost stated (overrule-only GPS-stuck-home absence no longer opens via `ble`; geofence covers it); D0 (a) split; tests `::test_ble_lost_at_home_no_departure_opens_no_intent`, `::test_departure_via_unknown_opens_no_intent`; drill |
| M2 post-restart dead window | Unstated; INV break case contradicted it | §5.4 gate 5 and §5.5 restart: 15 min `ble` / `camera_egress`, 10 min `geofence` (`RESIDENT_RETURN_BOOT_WINDOW_S`), pauses unaffected, fails closed; INV-V6-ARRIVAL-REACHES case qualified; `skipped_edges_truncated` subtype `boot` in the NM digest; tests |
| LOW-1 named-exit ts | "the arming edge's `ts`" | `departure_ts` epoch; named exit `.timestamp()`; test |
| LOW-2 zone lookup name | Unnamed | `data[CONF_ROOM_NAME]` (`presence.py:3627`); renamed room fails safe to `scene_skipped_not_near` |
| LOW-3 live zones | Not shown | Zone table in §5.5; Q4 (a) tied to Q5 by zone; D0 (a2) reports holder's room at onset |
| LOW-4 read-list owner | "whoever owns the contract" | Step 8's D2 commit adds `get_room_zone` to `READ_LIST["PRESENCE"]` (`_layer_guard_engine.py`) and contract §4 |
| LOW-5 §4.6 cite | Cited for the lag figure | Cited for "BLE never creates occupancy"; lag left to D0 (a2) |
