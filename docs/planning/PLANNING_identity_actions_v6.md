# PLANNING: identity actions (arc step 8): named arrivals, the person profile, arrival music, welcome scene, departure pause

Cards: PERSON-PROFILE-PREFERENCES-1 (whole card), VISION-CROSSING-ANALYSIS-1 (P2-D9 arrival record and count follow-up,
built as specified in `PLANNING_crossing_vision.md` §5), DEPARTURE-ACTIONS-1 (first consumer). Arc: identity / vision /
census, step 8 of `ARC_identity_vision_census_map.md` §4. Charter: `ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`
(goals section, 2026-11-14 and 2026-11-15 additions, drifts #17, #20, #23).

Status: rev 3.5, 2026-11-15. Author ura-planner. This rev carries the operator decisions of 2026-11-15 (§1.1) and the
F5 source audit's verdict (`AUDIT_step8_f5_source_semantics_2026_11_15.md`, develop `f303c177`). The arrival design is
rewritten, not layered: §5.4-§5.9, §6, §8, §9, §10 and §12 replace their rev 3.4 text. Rev 3.4 is commit `f20f54bc`
(plus the §10.1 deviations table, `25e671db`); its change history (§15.1-§15.5 of that rev, the rev 2 to 3.4 review
dispositions) lives there and in `docs/planning/archive/PLANNING_identity_actions_v6_rev2.md`. Neither is a build spec.
§14 lists what this rev removed.

Read first, completely (CLAUDE.md), and read for rev 3.5: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and
`SENSOR_FLEET_CLASSES.md` (both in full, 2026-11-15), the charter (in full), `IDENTITY_FUSION_CAMERAS_MANUAL.md`,
`HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (no HVAC input changes here; per-person HVAC targeting already exists as
`zone_persons`), `CONTRACT_person_awareness_layer.md`, `PLANNING_person_awareness_layer_ship3.md`. No corrections-ledger
claim is re-asserted. Presence facts this plan leans on: BLE extends a room's occupancy but never creates it (§4.6), so a
room's occupancy onset comes from a body sensor or a camera; `SIGNAL_PERSON_ARRIVING` is NOT a physical arrival (§1
table); residency writes one `person_arrival` record per raw `person.*` `-> home` edge and carries `counted` (away at
least 15 minutes, the lock's own rule), `source_stale` and `in_boot_window` (§1 table, residency producer row).

Code lines are cited at the step 8 branch `feature/step8-identity-actions` @ `470b760c` unless marked; the builder
re-greps every cite at build.

## 1. What makes 6.0.0 true

Step 8 delivers, keyed to a recognised resident:

1. **Named arrivals.** Step 7 names confirmed arrivals; this plan adds the arrival record (n came in, k recognised) and
   its count follow-up through the same amend function.
2. **The person profile.** My rooms (bedrooms, bathrooms; a room listed by two people is shared by them, e.g. the
   master), my music (a default, optionally varied by time of day and by room), my volume, my welcome scene, and which
   entry actions I want automated.
3. **Arrival music.** On a confirmed arrival home, the resident's pick starts on their OWN room's player and waits for
   them. If they reach that room within 15 minutes it keeps playing until someone stops it, and from then on music
   following owns it. If they do not, it stops at 15 minutes. It does not start when another tracked person or a guest
   is already in that room.
4. **Welcome scene.** When the resident's own bedroom lights up during their arrival window, the room's entry lighting
   uses their scene instead of the room's time-of-day scene, under the same gates.
5. **Departure pause.** When they leave, music URA started for them pauses once the room is empty.

All of it ships ON on day 1 for every resident who opts in on the People step; there is no trial stage (memory
`feedback_no_shadow_mode_day1_correct`). The house master is on by default (§5.1). The guest gate on door identity stays
parked (GUEST-GATE-DOOR-IDENTITY-1).

Charter goals served: "assist arrivals accuracy and personalization"; "it's going to lead to OC and personalization and
Ai enhancements for rooms". Hard constraint "I need away to be fast acting": nothing here reads or writes house-state
inference inputs (INV-V6-AWAY). Layer constraint ("consumers can read and producers can feed"; "no leaks"): step 8
produces no fact; it reads F1 edges only through `subscribe_person_edges` / `get_person_edges_since` /
`person_edges_truncated_since`, person rooms only through the layer's person reads, and the house census only through
`get_house_census` (§5.4-§5.5). Short-clip constraint: untouched (no frame source here).

### 1.1 Decided by operator 2026-11-15

Verbatim from card PERSON-PROFILE-PREFERENCES-1 (main checkout `kanban.data.yaml`, `operator_2026_11_15_*` and
`finding_2026_11_15_f5_sources`). The parenthesised part of a card field is the orchestrator's reading, recorded on the
card with the quote.

| # | Topic | Operator's words | What the plan does |
|---|---|---|---|
| 1 | Arrival music default | "This can be an option. The simplest thing is play in your room and just wait for you to arrive." | §5.5: start in the person's own room at the confirmed arrival; keep playing if they reach it within `ARRIVAL_WINDOW_S` (900 s); stop at window end if not. The §12 Q4 near / same-zone / approach rule is deleted. Follow-me is an option, off (§5.5.4) |
| 2 | After the person reaches their room | "If music following is on, yes. That way we don't have too much state to track." | §5.5.3 hand-off: music following owns the music from arrival in the room on; no arrival state remains (the departure stamp is departure state, §12 Q4) |
| 3 | Welcome scene scope | "Long run. Let's nail the room first." | §5.6: own bedroom only. Anywhere-the-arrival-leads is later work (card WELCOME-SCENE-ARRIVAL-PATH-1, to mint; §13). Review B2 carried into D3 |
| 4 | Occupied rule (Q2) | "B (drop the time rule; rely on no-other-tracked-person + guest detection; 8 min kept as backstop for phoneless guests)" | §5.5.1 gate 3. `ARRIVAL_OCCUPIED_LEAD_S` deleted; `ARRIVAL_OCCUPIED_BACKSTOP_S` 480 added (§9). Your own motion never blocks you |
| 5 | Arrival source | Operator caution: "Be sure geofence doesn't just wrap gps and ble and you're measuring the wrong thing with this. Has home uses both underneath I think". Q5: "B (BLE may start the arrival when a geofence arrival follows within a few minutes)" | §5.4: the trigger is ONE counted `person.*` arrival edge per physical arrival (the audit: `person.*` composes GPS and BLE; the `ble` F5 follows that edge 31 of 31 times, 2-60 s later). No F5 is read. BLE-led arrivals already open it through the composed edge, which is Q5 "B" |
| 6 | Ship order (Q4) | "ship the People screen first (§10.1 dark, B0 live check right after install, rollback if the form misbehaves)" | §10.1: People screen ships alone with the review fix list; B0 runs right after install |
| 7 | MA playback test (Q3) | "MA music check on another player: yes (operator present)" | D2 B0 (§8): a live test with the operator present, before the D2 build |
| 8 | Speakers | (orchestrator, 2026-11-15) Jaya's and Ziri's bedrooms now have speakers | Verified live, read-only: `Jaya Bedroom (Bedroom 4)` `room_media_player` = `media_player.jayas_room_3`, `Ziri Bedroom (Bedroom 5)` = `media_player.ziris_room_3` (`core.config_entries`, 2026-11-15). The "no speakers" note is removed |

Carried from 2026-11-14 and still binding: Tier 2-DB ("Agree with q1 and 2 and 4"); 6.0.0 = step 8, shipped before the
F-NOTIFY flip; "Departure pause is fine" (on, pause not stop); "Don't want to defer too much. Music is rarely exercised
so it's not a good trigger... When needed it's beautiful"; per-person temperature cut ("the exclusion is fine"); shared
rooms: "don't do it when someone is already in that room including in your own room. Shares spaces, likely same";
music following's 8 ft gate dropped; "Use form field hiding in 11.0 to keep config compact as needed"; "get a move on".

### 1.2 Drift check (ura-arc rule 7)

| Operator said | Where it drifted | Correction | Status |
|---|---|---|---|
| "Has home uses both underneath" | Rev 3.2-3.4 treated `geofence` and `ble` F5 as independent sources and built a departure-side bar, eight `ble` tests and drills, and a v6.0.0 dependency on BLE-ARRIVAL-PRODUCER-HVAC-GATED-1 for a source that duplicates the `person.*` edge | One counted `person.*` edge triggers (§5.4); BLE-specific gates, tests and the dependency removed (§14) | Fixed in rev 3.5 |
| "The simplest thing is play in your room and just wait" | Rev 3.1-3.4 started music at the moment of room entry, which needed a move-log cursor, an entry-time clamp, an occupancy lead and the D0 (a2) lead sizing; D0 measured own motion leading BLE by 3-7 minutes, so the 120 s lead would have blocked most real entries (review A/G G4) | Start at the arrival, in the own room (§5.5); entry-time machinery deleted | Fixed in rev 3.5 |
| "don't do it when someone is already in that room" | The welcome scene near rule (same house zone) passed about 1 master entry in 3 (D0 a2) | Near rule deleted (operator #1); scene gates on no other tracked person placed and no guests detected (§5.6) | Fixed in rev 3.5 |
| "get a move on" | Step 8 untouched all day 11-15 (drift #23) | People screen ships first (§10.1); D2-D4 dispatch after this rev's plan review | Open, sequenced |
| "Don't want to defer too much" | Rev 2 parked the profile extras (drift #17) | All in D1-D4 | Fixed in rev 3 |

## 2. Institutional context verified

Greps for rev 3.5, on `feature/step8-identity-actions` @ `470b760c` unless marked:
`_person_enabled|enable_for_person|sync_enabled_persons` (`music_following.py:377-414`: `_person_enabled(person_id)` at
`:410` is the per-person music-following read the hand-off uses); `class HouseCensusView` (`census_view.py:24-49`:
`identified`, `unidentified_or_guests`, `total`, `confidence`); `def subscribe_person_edges` (`residency.py:233`, sync,
O(1), no I/O, guard R14); live `room_media_player` for Jaya / Ziri bedrooms (`core.config_entries`, read-only). Rev 3.4
greps that still back a row are carried (cites re-grepped at build). The F5 audit's code cites (`presence.py:5684-5720`
`_handle_geofence_change`, `person_coordinator.py:1219-1226` BLE F5, HA `person/__init__.py:516-545` composition) are
develop lines from that audit.

| Piece | Verdict | Where |
|---|---|---|
| Arrival trigger | REUSED via ship 3a D2 (phase 2, built) | `residency.subscribe_person_edges(hass, cb, *, persons=None, kinds={"arrival"})` (`residency.py:233`; presence delegate). `cb(ResidencyEvent)` runs inline in `_feed_residency`, in the same `_handle_geofence_change` call that sends the `geofence` F5. `ResidencyEvent` carries `person`, `kind`, `edge_ts` (epoch float), `counted`, `source_stale`, `in_boot_window`, `resident_set_resolved` (`residency.py:39-51`) |
| Counted return | REUSED | `counted` = `arrival_edges.counted_return` (raw away at least `RESIDENT_RETURN_MIN_AWAY_MIN` 15 min, `const.py:4109` develop; from `unknown` / `unavailable` only if the last real state was not home at least 15 min). `in_boot_window` = `RESIDENT_RETURN_BOOT_WINDOW_S` 600 (`const.py:4110`). No new knob |
| F5 (`SIGNAL_PERSON_ARRIVING`) | NOT READ | The raw connect `MusicFollowingCoordinator.async_setup` (`domain_coordinators/music_following.py:296` repair base) and its no-op handler `_handle_person_arriving` (`:565`) are deleted in D2. No `subscribe_person_arriving` call is added (§5.4) |
| Departure edge | REUSED via ship 3a D2 | `subscribe_person_edges(..., kinds={"departure"})`; the departure wait's return check reads `get_person_edges_since(departure_ts, persons, kinds={"arrival"})` and `person_edges_truncated_since` |
| Person's current room | REUSED | `PersonCoordinator.get_person_location(name)` (`person_coordinator.py:1998` repair base; returns the resolved room name or `"unknown"`); contract G6 read |
| Person's room moves | REUSED via ship 3a D4 | `location_moves_since(t: datetime)` / `location_moves_truncated_since(t)` (window-end reach check only, §5.5.2) |
| Update notification | REUSED pattern | `PersonCoordinator.async_add_listener`, the same listener the SC lock regime uses (presence state of play §1, "Review A fix-up, MED-1"); ship 3a reserves it as the `LISTED` R10 key `('R10', 'music_following.py', '<step 8 §5.4 music listener>:async_add_listener[PC]')` |
| Per-person music following | REUSED | `MusicFollowing._person_enabled(person_id)` `music_following.py:410` (the engine's own enabled set; switches per person). The hand-off reads it; no copy |
| Guests detected | REUSED | `PresenceCoordinator.get_house_census("trust", cls=CONSUMER_CLASS_COMFORT)` (ship 3a D4 class read; `HouseCensusView.unidentified_or_guests`, `census_view.py:24-49`) plus house state `guest`. Comfort reads trust until F-LEAD (§3). Its rate at arrival is measured before D2 (D0b) |
| Presence lookup | REUSED | `hass.data[DOMAIN]["coordinator_manager"].coordinators["presence"]` (the path step 1a uses, presence ledger #36); None -> fail closed (no intent, `skipped_no_presence`) |
| Engine lookup from the entry path | REUSED (built in §10.1) | `hass.data[DOMAIN].get("music_following")` (`__init__.py:3432`); None -> slot scene as today |
| Room occupancy and onset | REUSED (built in §10.1) | room coordinator `data[STATE_OCCUPIED]` (`coordinator.py:3613`); `occupied_since()` delegates to `get_became_occupied_time()` (`coordinator.py:6396-6404`); the v3.5.1 camera override stamps the onset, so a camera-seen body is inside it |
| Room entry scene path | REUSED, extended (hook built in §10.1) | `AutomationEngine._maybe_activate_slot_scene` (`automation.py` around `:1740`; day / evening caller passes `arrival_override=True` at `:1591`, sleep caller `:1488` does not); `note_arrival_scene_result(room, result)` with `const.ARRIVAL_SCENE_RESULT_*` (§10.1 deviations) |
| Room primary player; MA map; MA-first play; outcomes; decision log; episodes; preference hook | REUSED from MUSIC-FOLLOWING-TRANSFER-REPAIR-1 (shipped) | `PLANNING_music_following_repair.md` §6; `CONF_ROOM_MEDIA_PLAYER` `const.py:106`; `set_preference_provider` |
| Volume scale; quiet hours; time-of-day parts; bathroom rooms; scene picker; URA-context writes; comfort class; person ids | REUSED | `CONF_ROOM_MEDIA_VOLUME_SCALE` (`const.py:4250`); `NotificationManager.is_quiet_hours_active` (`notification_manager.py:4772`); `lighting/resolver.py:309` `resolve_slot`; `ROOM_TYPE_BATHROOM` (`const.py:585`); `EntitySelector(domain="scene")`; `ura_ctx_kwargs` (`ura_context.py:80`), `URA_LIGHT_WRITE_DOMAINS` includes `scene`; `CONSUMER_CLASS_COMFORT` (`const.py:6498`); `tracked_person_entity_id` / `display_of` (`person_ids.py`) |
| Arrival master option | REUSED (un-retired, built in §10.1) | `CONF_MUSIC_ON_ARRIVAL_START`, `DEFAULT_MUSIC_ON_ARRIVAL_START = True` (`const.py:5033`), form default and consumer `person_profiles.arrival_master_on` |
| Options save without reload | REUSED (built in §10.1) | `person_profiles` in `OPTIONS_RELOAD_SUPPRESS_KEYS` (`__init__.py:7735`) and `_NO_LIVE_ATTR_KEYS` (`:7591`) |
| Crossing / arrival record; amend function | REUSED | `get_last_crossing`, `get_last_arrival_record`; `notify_arrival_followup` (`PLANNING_egress_direction_aware_identity.md` §5.4) |
| Episodes | REUSED pattern (types built in §10.1) | `MEMORY_EPISODE_TYPES` has `arrival_music`, `welcome_scene`; D2/D3 add them to `MEMORY_WRITER_BACKED_EPISODE_TYPES` with their writers |
| Room suggestions | REUSED (built in §10.1) | `person_visits`; display-only description placeholder |
| Conditional fields; media picker | REUSED (HA core) | `data_entry_flow.Optional(..., visible=...)` (core 2026.11.1), feature-detected by `_cond`; `selector.MediaSelector` |
| `person_profiles` store, People step, profile sensor | NEW, built in §10.1 | `person_profiles.py`, `config_flow.py` People steps, `sensor.ura_person_profile_<slug>` |
| Arrival intent, music wait and hand-off, scene decision, departure pause | NEW in the `MusicFollowing` engine | no arrival-start code exists (the F5 handler is a no-op) |
| Follow-me option | NEW | `CONF_ARRIVAL_MUSIC_FOLLOW_ME`; 0 hits for `follow_me|ARRIVAL_MUSIC_FOLLOW` in const / config_flow |
| Occupied backstop | NEW | `ARRIVAL_OCCUPIED_BACKSTOP_S`; 0 hits for `OCCUPIED_BACKSTOP` |

**Why the trigger is the residency edge and not an F5 (the audit, `AUDIT_step8_f5_source_semantics_2026_11_15.md`).**
HA's `person.*` composes its trackers: any non-GPS tracker reading `home` wins, and GPS decides only when no BLE tracker
is home (`person/__init__.py:516-545`). So `person.* == home` means "GPS home OR any BLE tracker home"; for Jaya and Ziri
(no GPS tracker) it is BLE only. The `geofence` F5 is that composed edge, sent in the same call (lag 0 s in 78 of 78);
the `ble` F5 followed a `person.*` arrival edge in 31 of 31 cases, 2-60 s later, and no `ble` F5 arrived without one.
The residency arrival record is written in the same call as the `geofence` F5 (`presence.py:5644` feed, `:5681-5685`
send, rev 3.4 cite), so subscribing to the record is subscribing to the one physical arrival. Of the 80 arrival edges,
the 19 away-under-15-minute flaps were all GPS, and every BLE-family edge was a counted return: `counted` is the flap
filter.

**HA conditional fields and MediaSelector** (verified against core 2026.11.1 source and the 2026.2.3 test venv; rev 3.4
§2 detail is carried in the code and tests built in §10.1): `data_entry_flow.Required` / `Optional` take
`visible: bool | FieldCondition | list[FieldCondition] | None` (list = AND); a hidden field is not rendered and is
dropped from the submission; `section` takes no `visible`. The test venv has no `visible`. Without `accept`,
`MediaSelector.__call__` requires `entity_id` (HA 2026.2.3, `helpers/selector.py`), which is why the stored pick keeps
the browse player (§10.1 deviations). Live behaviour on 2026.11.1 is the B0 check (§10.1).

Prior plans read: rev 3.4 and its re-checks; `PLANNING_crossing_vision.md` §5; contract (all); ship 3 plan;
music repair; egress direction-aware §5.4-§5.5. Review records read for rev 3.5:
`docs/reviews/code-review/v_step8_10_1_review_A_G.md` and `v_step8_10_1_review_B.md` (main checkout). D0 report:
`AUDIT_identity_actions_d0_2026_11_15.md` (this branch). Memory: `project_hyper_personalization_person_profile`,
`reference_identity_model_f1_f5`, `feedback_fire_check_and_forward_trace`, `feedback_no_shadow_mode_day1_correct`,
`feedback_registry_not_name_guessing`, `feedback_marginal_benefit_pushback`.

**Config-first.** No setting starts music or a scene on a person's arrival; the arrival master is unset live (consumer
default ON, D0). Music following's per-person switches decide the hand-off and need no change.

## 3. Facts and consumer classes

Consumes: **F1** residency arrival records (the trigger, §5.4) and departure records (the departure arm, §5.7), through
`subscribe_person_edges` / `get_person_edges_since`; **F2** the comfort-class house census view (guests detected), which
reads trust until F-LEAD; **F4** each tracked person's BLE room through the layer's person reads (§5.5); **F3** named
exits and the arrival-record attribute (§5.7, §5.8). Reads no **F5**: every F5 is a second view of an arrival whose
`person.*` edge this plan reads (§2). Produces no fact. Arrival music, welcome scene, departure pause: **comfort**. Count
follow-up: **notification** (names >= 0.75). Profile sensor and room suggestions: **display**. Access, security, house
state: none.

## 4. Evidence (D0, run 2026-11-15) and what it changed

D0 ran read-only on live HA (`AUDIT_identity_actions_d0_2026_11_15.md`, probe `scripts/probes/identity_actions_d0.py`).
The F5 source audit re-read its arrival split. The numbers this plan uses:

| Item | D0 / audit number | Consequence here |
|---|---|---|
| Arrival sources | Corrected framing (audit §4-§5): the D0 split "geofence 9 of 15 pass, ble 0 of 9" is NOT evidence that BLE is weak. The geofence figure judged the one `person.*` edge by its own residency record (same call, 0 s); the `ble` figure judged the same arrivals by "a later arrival edge exists", which is always true because the edge precedes every `ble` F5. The 0 of 9 is an ordering artefact. The geofence 9 of 15 is mostly the GPS-flap filter (all 19 sub-15-minute flaps were GPS) | One trigger, the counted edge (§5.4). Arrivals per day are restated by the edge's source tracker (registry platform): 62 GPS-led, 16 BLE-led, 1 iCloud3 of 79 edges in 7 days |
| F5 to first room with a player | n 54, p50 190 s, p95 720 s, max 757 s | `ARRIVAL_WINDOW_S` 900 covers the walk to the own room |
| At that first entry | room occupied before 18.5 %, quiet 3.7 %, already playing 0 % | Gates sized; occupied share is now judged by rule B, not onset |
| Own motion before BLE entry, bedrooms | p50 3-7 minutes | The entry-time lead rule could not work (review G4); deleted with operator #4 |
| Near rule pass shares | Master 16 / 59 / 34 % (adjacency / plus approach / zone) | Moot: rule deleted (operator #1) |
| Departures | Departure room already vacant at the edge, p50 0 s, n 1-5 per resident | The departure wait rarely matters; kept as specified (§5.7) |
| Day / evening split | 36 / 18 | Per-part picks matter (§5.3) |
| Egress entries named at the crossing | 30 of 94 (31.9 %) | D5 / step 7 context |
| Rooms with a primary player | D0 listed Jaya and Ziri bedrooms without one | Superseded: both now have WiiM players (§1.1 #8) |

**D0b, before the D2 build (read-only, same probe file, recorder + URA DB).** Two numbers decide whether rule B behaves
as the operator expects, so they are measured first (measure before build): (1) at each counted arrival edge of the last
7 days, the share where the comfort census view read `unidentified_or_guests >= 1` or house state `guest` at `edge_ts`
and over the next 60 s, split by whether a real visitor was home (operator ground truth on the party night 11-14 and the
guest stays); a high share with no visitor means guests-detected would block the resident's own arrival (their body seen
before their face or phone counts) and goes to the operator before D2 builds; (2) per resident, the share of counted
arrivals whose layer room reached their own speaker room within 900 s (the music keep-or-stop split), and the
distribution of that reach time. Go/no-go: none (operator ruling: a low fire rate is not a reason to defer); a number that
makes a gate look wrong goes to the operator with the number (charter rule 3).

## 5. Design

### 5.1 The profile store and the master

CM entry options key `person_profiles`, keyed by `tracked_person_entity_id` (built in §10.1):

```
"person.oji": {
  "rooms_bedroom":  ["<room entry_id>", ...],     # My bedroom(s)
  "rooms_bathroom": ["<room entry_id>", ...],     # My bathroom(s); picker lists ROOM_TYPE_BATHROOM rooms
  "auto_music": bool,                             # Automate my entries: play my music
  "auto_scene": bool,                             # Automate my entries: welcome scene
  "music_default": {"media_content_id": str, "media_content_type": str, "entity_id": str},
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
  person reads return a room NAME; the engine maps it to an entry_id through the room entries' own `room_name` (URA's
  own config, the one allowed string match). A cached map rebuilt on `SIGNAL_ROOM_ENTRY_LIFECYCLE` is a D2 item (review
  A7; only the pure lookup is built). An unmapped name never matches an own room.
- **Owners are derived, never stored twice:** `room_owners(room) = {p : room in p.rooms}`. A room with two owners is
  shared (the master).
- **The stored pick keeps the browse player's `entity_id`**; playback strips it (`person_profiles.play_pick`), so music
  always plays on the room's own player (§10.1 deviations).
- **Toggle-off semantics are the consumer's job.** The consumer reads a dependent field only when its toggle is on.
- **No reload.** `person_profiles` is in `OPTIONS_RELOAD_SUPPRESS_KEYS` and `_NO_LIVE_ATTR_KEYS`; the consumer
  fresh-reads the profile at each decision.
- **Master, day 1 = ON.** `options.get(CONF_MUSIC_ON_ARRIVAL_START, DEFAULT_MUSIC_ON_ARRIVAL_START)`, default True; live
  has no stored value. Label "Arrival actions".
- **Display:** `sensor.ura_person_profile_<slug>` (state = number of automated actions on; attributes unrecorded: rooms
  by name, owners of shared rooms, music labels, scene, `last_arrival_action`).

### 5.2 The People step (CM options)

Built in §10.1 as specified in rev 3.4 §5.2: menu "People" -> pick a tracked person (display name) -> sections "My
rooms" and "Automate my entries" with conditional fields (`_cond`, `visible` on HA 2026.11, every field shown on older
HA) -> optional "Music by room" step, one MediaSelector per own room that has a primary player. Five fields show with
everything off. Save-time validation refuses music on with no usable default pick, or scene on with no scene. The §10.1
fix list (§10.1) changes the room-step labels, the room-field defaults and the clear semantics.

### 5.3 How a playlist is specified and chosen

- **Picking.** `MediaSelector()` with no `accept`: browse any MA player, pick a playlist, station, artist or album. The
  fallback "paste a Music Assistant URI" field exists behind `PEOPLE_MUSIC_URI_FALLBACK_ENABLED` (False); D2 B0 decides
  whether it is needed (§8).
- **Choosing at play time** (`pick_media(profile, room_id, slot)`, built): `music_by_room[room_id]` if `music_vary_room`
  and set; else `music_day` / `music_evening` for the target room's `resolve_slot(...)` if `music_vary_time` and set;
  else `music_default`. The `sleep` slot never plays.
- **Volume:** `music_volume` x the room's `CONF_ROOM_MEDIA_VOLUME_SCALE`, clamped 0..1.
- **No bonus joins.** Play on the room's MA entity (MA-first) or native player; never group-join other players.

### 5.4 The arrival trigger: one counted `person.*` edge

- **Subscription.** At engine setup, `subscribe_person_edges(hass, self._on_arrival_edge, persons=None,
  kinds={"arrival"})`, unsubscribed at teardown. The callback is sync and O(1): it copies the `ResidencyEvent` and
  schedules the intent work (`hass.async_create_task` on a tracked task set, cancelled at teardown); it never awaits and
  never reads a coordinator (guard R14, INV-AWAY-LATENCY).
- **No F5 is read.** D2 deletes the raw `SIGNAL_PERSON_ARRIVING` connect in `MusicFollowingCoordinator.async_setup` and
  its handler, and adds no `subscribe_person_arriving` call. The `ble` F5 is therefore deduplicated by construction:
  the engine sees each physical arrival once, as its `person.*` edge, whether GPS or BLE led it. Step 7's `camera_egress`
  F5 (a GPS-led confirmation sent while raw `person.*` is not yet `home`) is also a second view: the arrival opens when
  the edge follows. Cost, stated: the minutes between a step-7 door confirmation and HA's `person.*` flip. Music waits in
  the room anyway (§5.5), so the cost is a later start, not a missed one.
- **Intent gates, in this order** (each rejection is a counter with no decision line):
  1. the master is on, music following is enabled (`_coordinator_enabled()`) and not in observation mode
     (`skipped_master_off`);
  2. presence resolvable (`skipped_no_presence`); the record's `resident_set_resolved` is True and its person is a
     tracked resident with `auto_music` or `auto_scene` on and at least one own room (`skipped_no_rooms`);
  3. **counted return.** `counted is True`, `source_stale is False` and `in_boot_window is False`. Otherwise
     `skipped_not_counted_return` with subtype `not_counted` (away under 15 minutes: the GPS flap; or an
     `unknown` / `unavailable -> home` edge whose last real state was not 15 minutes away, which includes "no departure
     seen"), `stale_source` or `boot`;
  4. no intent already open for this person (`intent_duplicate`; the first intent runs on).
- **Intent.** An intent that passes is stored per person (`_arrival_intents`, RAM, owned by the `MusicFollowing` engine,
  cleared at teardown) with `t_a = edge_ts`, the target room (§5.5), and its music and scene outcome slots. The engine
  writes an `intent_opened` episode (`arrival_music`, `outcome: intent_opened`, `opened_at`, `window_s`, `music_on`,
  `scene_on`, `target_room`). A window timer (`async_call_later`, cancelled at teardown) closes the intent at
  `t_a + ARRIVAL_WINDOW_S`.
- **Post-restart.** The residency tracker is RAM; every arrival record within `RESIDENT_RETURN_BOOT_WINDOW_S` (600 s) of
  presence setup carries `in_boot_window = True`, so no intent opens for 10 minutes after a restart or presence reload
  (`skipped_not_counted_return` subtype `boot`, counted in the NM digest). One window per restart.
- **Another tracked person is in room R** is computed as: any other tracked person whose `get_person_location` maps to
  R. That read includes a STALE location kept for `decay_timeout` (300 s), so a resident who left R minutes ago still
  blocks (the conservative direction, accepted by name). It is the one site to swap to `persons_in_room` when
  G6-ONE-BLE-ROOM-READ-1 lands.

### 5.5 Arrival music: start in your room and wait

**Target room.** At intent open, with `auto_music` on: the first room in `rooms_bedroom` (stored order) that has a
primary player, else the first in `rooms_bathroom` that has one. None -> music outcome `skipped_no_player` (terminal).
The same target serves the default mode; follow-me picks its room differently (§5.5.4).

#### 5.5.1 Start (once, at intent open)

Checked in this order; each is a terminal music outcome:

0. toggles re-read now: master, `_coordinator_enabled()`, the fresh profile's `auto_music` (`skipped_toggled_off`);
1. quiet hours (`is_quiet_hours_active`) or house `sleep` / `waking` (`skipped_quiet` / `skipped_sleep`);
2. target room paused (`const.room_automation_paused`) (`skipped_paused`);
3. **occupied (operator rule B).** Any of:
   - another tracked person's layer room is the target room (co-owner included) -> `skipped_occupied` subtype
     `tracked_person`;
   - guests detected: house state `guest`, or the comfort census view's `unidentified_or_guests >= 1` -> `skipped_guests`;
   - **phoneless-guest backstop:** the target room reads occupied and its onset (`occupied_since()`) is at least
     `ARRIVAL_OCCUPIED_BACKSTOP_S` (480 s) before `t_a`, and the arriving person's own layer room is not the target room
     -> `skipped_occupied` subtype `backstop`.
   Your own motion never blocks you: the backstop is skipped when the layer already places you in the target room (the
   slow-GPS case where you walked in first), and no rule compares onset with your entry time. A room occupied for less
   than the backstop with nobody tracked placed in it and no guest detected does start (accepted by rule B: that
   occupant is most likely you, or a phoneless guest the census also missed);
4. one start per person per `ARRIVAL_MIN_GAP_S` (`skipped_gap`);
5. no pick resolves (`skipped_no_media`); target player unavailable (`skipped_no_player`);
6. the native player or its MA entity reads `playing` or is in a playing group (`skipped_playing`);
7. play MA-first, native when no MA entity, with `ura_ctx_kwargs`, at the person's volume; verify the entity played
   reads `playing` within `ARRIVAL_VERIFY_S` -> `started`, stamp `{person, room, native_player, ma_entity,
   media_content_id, started_at}`; else `start_failed` (terminal).

A `started` music slot moves to the wait (§5.5.2). Already in the room at open (the layer places you there) is the same
start followed at once by the hand-off.

#### 5.5.2 Wait (from `started` to window end)

While any wait is open, a `PersonCoordinator.async_add_listener` callback (registered when the first wait or departure
wait opens, removed when the last closes and at teardown; the reserved R10 key) runs one pass per update per waiting
person, in this order:

1. **reversed.** The stamped entity was paused, stopped or set to volume 0 by a non-URA context within the wait ->
   `reversed` (terminal; nothing more is done);
2. **not ours.** The stamped entity no longer plays the stamped `media_content_id` -> `wait_ended_not_ours` (terminal);
3. **arrived.** `get_person_location(name)` maps to the target room -> `arrived` (terminal) and the hand-off (§5.5.3).

At window end, with the music slot still waiting:

1. the same two checks (`reversed`, `wait_ended_not_ours`);
2. **reach check, three reads:** a final `get_person_location`; else `location_moves_since(t_a - update_interval)`
   holding a move of this person into the target room (a pass-through between listener calls); a person seen in the room
   by either is `arrived` (subtype `late_seen`) and handed off. When `location_moves_truncated_since(...)` is True the
   location read decides alone;
3. otherwise **stop**: `media_player.media_stop` on the stamped entity with URA context (`media_pause` when the player
   does not support stop) -> `wait_expired_stopped`. Then for `ARRIVAL_REVERSAL_S` the listener watches: if the layer
   places the person in the target room inside it, record `stopped_then_arrived` (a counted defect, the
   `arrival_stop_premature` trip-wire, §7). Nothing restarts the music.

Nothing else is re-checked during the wait: another person walking into the room while it plays does not stop it
(the "already in that room" rule is a start rule).

#### 5.5.3 Hand-off to music following

At `arrived` the arrival intent's music part ends and step 8 keeps no music state for it, apart from the departure stamp
(§5.7). From then on the music is ordinary playback in the person's room:

- if music following is on for the person (`MusicFollowing._person_enabled(person)`), its existing transfer path moves
  the music when the person changes rooms, exactly as it does for any music the person is playing;
- if it is off, the music stays in the room until someone stops it.

Step 8 adds no code to the transfer path for the hand-off and never stops music after `arrived`. D2 pins the hand-off
with a test that drives the real transfer path (§8).

#### 5.5.4 Option: follow me for the first 15 minutes (off by default)

`CONF_ARRIVAL_MUSIC_FOLLOW_ME` (CM option, rung 2, default False; one house-level field on the existing music form, not
in the People step). When True, the default start in §5.5.1 is replaced:

- the music starts in the FIRST room with a primary player that the person's layer room enters inside the window (any
  room, own or not), with every §5.5.1 gate evaluated for that room;
- for the rest of the window, each later room the person enters that has a primary player receives the music through
  music following's transfer path for that person, whatever their music-following switch (the engine passes an
  arrival-follow flag to the transfer call; no second transfer implementation);
- at `arrived` in an own room the hand-off runs as in §5.5.3; at window end outside an own room the stop rule of §5.5.2
  applies to whatever room the music is in.

Outcomes add `follow_started_in` (room) and `follow_transferred` (count). Marginal-benefit note, stated before build:
this option is the only part of D2 that needs a moving target and a flag into the transfer path. It ships off. If its
build or review cost grows past the default mode's, the orchestrator asks the operator before cutting it (no silent
deferral); it is D2b so the default mode never waits on it.

### 5.6 Welcome scene: the own room only

A per-person override inside the room's own entry scene path (hook built in §10.1). No second scene writer, no manual
hold.

- On the day / evening caller only, `_maybe_activate_slot_scene` asks the engine `arrival_scene_for(room_entry_id)`
  before `slot_scene(...)`: `scene_id = arrival_scene_for(room) or slot_scene(self.config, slot)`. Then the existing
  path: the manual-hold check, the scene-state guard, one URA-context `scene.turn_on`. The sleep caller never asks.
- `arrival_scene_for(room)` returns the owner's scene when all hold, else None; a None return with a reason records the
  intent's terminal scene outcome:
  1. exactly one owner of this room has an open intent with the scene undecided (two -> `scene_skipped_ambiguous`);
  2. toggles re-read: master, `_coordinator_enabled()`, that owner's `auto_scene` and `welcome_scene`
     (`scene_skipped_toggled_off`);
  3. the room is one of the owner's bedrooms (§12 Q1 default: bedrooms only; a bathroom returns None with no outcome);
  4. no other tracked person's layer room is this room (`scene_skipped_occupied`); no guests detected, same read as
     §5.5.1 gate 3 (`scene_skipped_guests`);
  5. not quiet hours, not house `sleep` / `waking` (`scene_skipped_quiet` / `scene_skipped_sleep`);
  6. that owner had no welcome scene within `ARRIVAL_MIN_GAP_S` (`scene_skipped_gap`).
  There is no near rule and no requirement that the owner be placed yet (operator #1): the room's vacant-to-occupied
  edge comes from a body sensor about a minute before BLE places the person (D0 a2, master p50 47 s), so a placement
  test fails most real arrivals. Cost, stated: a co-owner, sibling or untracked person who walks into the owner's empty
  bedroom first, inside the owner's window, before BLE places anyone there, gets the owner's scene. `scene_unconfirmed`
  counts it. A co-owner is the accepted case ("Shares spaces, likely same").
- **Result.** `_maybe_activate_slot_scene` reports `note_arrival_scene_result(room, result)` with one of
  `ARRIVAL_SCENE_RESULT_APPLIED` / `_HOLD` / `_UNAVAILABLE` / `_ERROR`:
  - `applied` -> `scene_applied`; then within `ARRIVAL_SCENE_CONFIRM_S` the layer must place the owner in the room
    (`scene_confirmed`), else `scene_unconfirmed`;
  - `hold` -> `scene_skipped_hold`; the per-light path runs, as today (a hold stays per-light);
  - `unavailable` or `error` -> **review B2:** the entry path retries the room's own slot scene once through the same
    state guard and one `scene.turn_on` (`scene_fallback_slot` when it applied, `scene_fallback_failed` when the slot
    scene is also missing or unavailable, in which case the per-light path runs). A room with a working slot scene never
    drops to per-light lighting because the welcome scene broke.
- If the room's entry rule turns no lights on (bright daytime, no lights), the override is never asked and the scene
  ends at window end as `scene_window_expired`, or `scene_entry_missed` when the layer placed the owner in the room
  inside the window.
- Survival: nothing in URA re-applies a slot scene mid-occupancy and the reconciler acts only on availability edges or a
  quarantine release, so the welcome scene stays until vacancy turns the lights off, or a person changes them. No
  arrival scene state remains after the window.

Music and scene are independent: a playing speaker skips music but not the scene; a scene skip does not stop music.

### 5.7 Departure pause

**Arm.** For a person with a live music stamp, the first of: a named exit at >= 0.75 (step 7 `departure_candidate` or
`attached`, via `get_last_crossing`) or their residency departure record, delivered by `subscribe_person_edges(hass, cb,
persons={person_entity}, kinds={"departure"})` (sync, schedules only). The edge arms a departure wait of length = the
stamped room's own `occupancy_timeout` (room config, read at arm time) + `ARRIVAL_DEPARTURE_VACANCY_WAIT_S`.
`departure_ts` is epoch seconds: the record's `edge_ts`, or the named exit's crossing time as `.timestamp()`. A second
edge while armed is ignored.

**Check.** On every person-coordinator update (the same listener as §5.5.2) and once at the wait's end, in order:
0. **returned:** `get_person_edges_since(departure_ts, persons={person_entity}, kinds={"arrival"})` non-empty (any
   arrival record, counted or not) -> `departure_kept_returned` subtype `edge`; truncated and empty ->
   `departure_kept_returned` subtype `truncated` (fail closed);
1. `ARRIVAL_MUSIC_DEPARTURE_PAUSE`, the master and the person's fresh `auto_music` on, else `departure_kept_toggled_off`;
2. the stamped entity still plays the stamped `media_content_id`, else `departure_kept_not_ours` (this is also the
   outcome when music following has carried the music to another room after the hand-off);
3. the other entity of the pair is not playing something else, else `departure_kept_other_playing`;
4. no tracked person other than the departing one is placed in the room (the departing person's own STALE location is
   excluded), else wait on;
5. the room coordinator reads not occupied, else wait on.
When 0 does not end it, 1-3 hold and 4-5 pass: `media_player.media_pause` on the stamped entity, URA context ->
`departure_paused`. At the wait's end with 4 or 5 failing: `departure_kept_shared` / `departure_kept_occupied`. Jaya's
LD2410 fan phantom can end `departure_kept_occupied` with nobody home (presence state of play §6): the honest outcome.

**Restart.** The stamp is RAM; a restart loses it, counted `departure_stamp_lost_restart` at setup from the last
`started` episode with no pause or stop.

### 5.8 Named arrivals and the count follow-up (P2-D9)

As `PLANNING_crossing_vision.md` §5, at that plan's own review bar, with three rules: (1) the follow-up calls
`notify_arrival_followup(crossing_ref, kind="count", names=..., guests=n - k)`; arrival sends stay <= 3 per crossing and
perimeter is unchanged; (2) a name renders only at the notification class (>= 0.75 or a step-7 confirmation); window NVR
face names count toward `k` but render "not recognised"; (3) the count follow-up sends only while `notification` is in
the active `CROSSING_VISION_CONSUMER_CLASSES` (census CD4 flip). The record is written and displayed before the flip.

### 5.9 Outcome contract and restart

One decision-log line and one episode (`arrival_music` or `welcome_scene`) per outcome; outcomes in the NM digest.

| Path | Outcomes |
|---|---|
| Intent (episode + line) | `intent_opened` (`music_on`, `scene_on`, `target_room`), `intent_lost_restart`, `scene_lost_restart` |
| Intent (counter only) | `skipped_master_off`, `skipped_no_presence`, `skipped_no_rooms`, `skipped_not_counted_return` (subtypes `not_counted` / `stale_source` / `boot`; `boot` in the NM digest), `intent_duplicate` |
| Music start | `started`, `start_failed`, `skipped_toggled_off`, `skipped_quiet`, `skipped_sleep`, `skipped_paused`, `skipped_occupied` (subtypes `tracked_person` / `backstop`), `skipped_guests`, `skipped_gap`, `skipped_no_media`, `skipped_no_player`, `skipped_playing` |
| Music wait | `arrived` (subtype `listener` / `late_seen`), `reversed`, `wait_ended_not_ours`, `wait_expired_stopped`, `stopped_then_arrived`, `wait_lost_restart` |
| Follow-me (option) | `follow_started_in`, `follow_transferred`, `follow_window_expired` (plus the wait outcomes) |
| Scene | `scene_applied`, `scene_confirmed`, `scene_unconfirmed`, `scene_skipped_hold`, `scene_fallback_slot`, `scene_fallback_failed`, `scene_skipped_ambiguous`, `scene_skipped_toggled_off`, `scene_skipped_occupied`, `scene_skipped_guests`, `scene_skipped_quiet`, `scene_skipped_sleep`, `scene_skipped_gap`, `scene_window_expired`, `scene_entry_missed` |
| Departure | `departure_paused`, `departure_kept_returned` (subtype `edge` / `truncated`), `departure_kept_shared`, `departure_kept_occupied`, `departure_kept_not_ours`, `departure_kept_other_playing`, `departure_kept_toggled_off`, `departure_stamp_lost_restart` |

**Restart mid-window.** Intents and waits are RAM. At engine setup, after the episode store is readable, the engine
reads `arrival_music` and `welcome_scene` episodes from the last `ARRIVAL_WINDOW_S` + 1 h. For every `intent_opened`
with no later terminal outcome: music not yet decided -> `intent_lost_restart`; music `started` with no wait outcome ->
`wait_lost_restart` (the music is left playing; nothing stops it after a restart); `scene_on` with no scene outcome ->
`scene_lost_restart`. Each is written once. The action is not resumed.

**Every intent ends counted.** Exits: a start gate; the start; the wait outcomes; the window timer; a toggle turned off
(read at the next decision); teardown or reload (the restart sweep on next setup).

## 6. Falsifiable invariants

The load-bearing invariants for D2 and D3, stated so that one counterexample breaks them:

- **INV-V6-ARRIVAL-START (D2).** For every counted (`counted is True`), non-stale, out-of-boot-window residency arrival
  record of a tracked resident P with `auto_music` on and a target room R, music starts on R's player if and only if
  every §5.5.1 gate passes; in particular it NEVER starts when another tracked person is placed in R, guests are
  detected, R has been occupied for at least `ARRIVAL_OCCUPIED_BACKSTOP_S` before `t_a` while P is not placed in R,
  quiet hours or house `sleep` / `waking` hold, or R's native or MA entity is playing; and it NEVER starts for a record
  with `counted` False (P away under 15 minutes, or an `unknown -> home` with no real 15-minute absence). It starts
  whatever the edge's source tracker (GPS or BLE) and whether or not any F5 was sent.
  Break it with: Oji not_home 4 h, GPS edge, idle Sonos, nobody placed in the master -> `started`. Jaya (BLE-only),
  BLE-led edge after 2 h away -> `started` on `media_player.jayas_room_3`. Oji in the master an hour, GPS
  `home -> not_home -> home` in 40 s -> no intent (`not_counted`). HA restore `unknown -> home` with the last real
  `home` 3 minutes before -> no intent. Ezinne placed in the master -> `skipped_occupied`. An untracked guest in Oji's
  room 30 minutes, census missing them -> `skipped_occupied` subtype `backstop`. Oji already in the master (slow GPS),
  room occupied 20 minutes by his own motion -> `started` (own placement skips the backstop). Census `unidentified 1` at
  `t_a` -> `skipped_guests`. A `ble` F5 30 s after the edge -> no second intent and no second start.
- **INV-V6-ARRIVAL-WAIT (D2).** Every `started` arrival music ends its wait in exactly one of `arrived`, `reversed`,
  `wait_ended_not_ours`, `wait_expired_stopped`, `wait_lost_restart`; and step 8 stops it ONLY at window end, ONLY when
  none of the listener, the final location read and the move log saw P in R inside the window, and ONLY while the
  stamped entity still plays the stamped content. After `arrived`, no step-8 path pauses or stops that music except the
  departure pause.
  Break it with: P walks in at minute 9 -> keeps playing at minute 16. P passes through R between two listener calls
  and leaves -> `arrived` subtype `late_seen`, not stopped. P never comes up -> stopped at minute 15. Someone paused it
  at minute 4 -> `reversed`, no stop call. Someone started a podcast on that speaker at minute 6 -> `wait_ended_not_ours`,
  no stop. P arrives at minute 15:10 -> `stopped_then_arrived` counted.
- **INV-V6-HANDOFF (D2).** After `arrived`, the music follows P to the next room if and only if
  `_person_enabled(P)` is True, through music following's own transfer path; step 8 holds no arrival state for P
  except the departure stamp.
- **INV-V6-SCENE-ROOM (D3).** A welcome scene is applied only by the entry path of one of its owner's own bedrooms, only
  while that owner's intent is open, never when another tracked person is placed in the room or guests are detected,
  and never under quiet hours or house `sleep` / `waking`. An entry issues at most one successful scene activation:
  the welcome scene, or (after the welcome scene reads `unavailable` / `error`) the room's slot scene; a manual hold
  beats both and runs the per-light path.
  Break it with: Oji's window open, Ezinne placed in the master when the radar fires -> slot scene; Oji's scene entity
  deleted -> slot scene applied by the retry (not per-light); a light under a manual hold -> per-light; a bathroom
  entry -> slot scene; Oji and Ezinne both inside their windows -> `scene_skipped_ambiguous`, slot scene.
- **INV-V6-COUNTED.** Every arrival record past the master is counted, and every opened intent ends in exactly one
  terminal music outcome (when `auto_music` is on) and one terminal scene outcome (when `auto_scene` is on), including
  across a restart mid-window and a toggle turned off mid-window; none ends silent.
- **INV-V6-NEVER-INTERRUPT.** No start on a room whose native player or MA entity is playing; no stop or pause of
  playback URA did not start (the content-id match guards the window-end stop and the departure pause).
- **INV-V6-OFF-MEANS-OFF.** With a toggle off, nothing under it acts, whether the HA version hid its fields or kept them,
  and whether it was turned off before the intent opened or inside the window.
- **INV-V6-NO-FACE-ALONE.** Every `started` / `scene_applied` traces to a residency arrival record, which only a raw
  `person.*` edge writes; no face, vision or crossing input opens an intent.
- **INV-V6-DEPARTURE-REACHES.** For a live stamp whose owner departs, with the stamped content still playing, the other
  entity idle, no arrival record of the owner since the departure, and the room going vacant with no other tracked
  person placed in it inside the wait, the outcome is `departure_paused`. **Dual:** no `departure_paused` after an
  arrival record of the owner since the departure (GPS flap `home -> not_home -> home`, then Oji walks downstairs and the
  master goes vacant -> `departure_kept_returned`).
- **INV-V6-NO-RELOAD.** A People save never reloads the CM entry.
- **INV-V6-AWAY.** No step-8 path reads or writes an `infer()` input or HVAC; the census read is the comfort-class view.
- **INV-V6-LAYER.** Step 8 reads F1 only via `subscribe_person_edges`, `get_person_edges_since` and
  `person_edges_truncated_since`; F2 only via `get_house_census(..., cls=CONSUMER_CLASS_COMFORT)`; person rooms only via
  `get_person_location`, `location_moves_since`, `location_moves_truncated_since` and the reserved `async_add_listener`.
  No `SIGNAL_PERSON_ARRIVING` connect, no `subscribe_person_arriving` call, no raw `person.*` listener and no
  `person_coord.data` read remains in either music file; the layer guard test covers both.
- **INV-V6-ONE-AMEND / NAME-BAR.** Arrival follow-ups only through the amend function; no text names below 0.75.

## 7. Producer and consumer checks; sites

**Producers.** The residency tracker writes one arrival record per raw `person.*` `-> home` edge of a resident, in
`_feed_residency`, the first statement of `_handle_geofence_change`; `counted` is the lock regime's own rule. Producer
health (audit, 7 days): 79 arrival edges by source tracker, 62 GPS-led, 16 BLE-led, 1 iCloud3, 19 flaps (all GPS) rejected by `counted`. Its
dependency is HA's `person` composition, which needs each resident's trackers in `person.*` `device_trackers` (Jaya and
Ziri: BLE only). Fire check: residency rows exist since 2026-11-13 20:54 UTC; the arrival path itself has fired zero
times (no-op handler). The person coordinator's room read fires continuously. The comfort census view refreshes on
every census update. **Trip-wires** (HIGH NM unless noted): `arrival_action_zero` (>= 10 opened intents with a target
room in 7 days and 0 `started` + `scene_applied`); `arrival_stop_premature` (>= `ARRIVAL_STOP_PREMATURE_NM` (3)
`stopped_then_arrived` in 7 days: the stop is cutting off real arrivals); `arrival_guest_block_high` (MEDIUM: `skipped_guests`
on more than half of opened intents over 7 days with >= 10 intents: the guest read is blocking residents, D0b's
question asked in code); `arrival_music_failing` (>= 3 `start_failed` in 24 h); `welcome_scene_failing` (>= 3
`scene_unconfirmed` + `scene_fallback_failed` in 24 h); `arrival_entry_missed` (>= `ARRIVAL_ENTRY_MISSED_NM` (3)
`scene_entry_missed` in 7 days). **Forward trace:** `person.*` edge -> residency record -> intent -> target room ->
gates -> play -> verify -> wait -> arrived / stop -> hand-off -> departure -> pause; and intent -> entry path override
-> scene -> confirm. **Consumers of the new store:** the music engine, the entry scene path (through
`arrival_scene_for`), the profile sensor, the People step, and later OC and AI room rules (read-only, through the sensor
or `get_person_profile(person)`; no second store).

**Site enumeration (re-run for rev 3.5):**
1. The F5 read: the raw connect `MusicFollowingCoordinator.async_setup` (`domain_coordinators/music_following.py:296`
   repair base) and `_handle_person_arriving` (`:565`): deleted, no replacement subscription.
2. The arrival-record subscription (`subscribe_person_edges`, kinds arrival) and its scheduled intent work (§5.4).
3. The person-coordinator listener: music wait checks (§5.5.2), follow-me moves (§5.5.4), departure checks (§5.7),
   scene confirm (§5.6). `_on_person_transition` is NOT a site (no arrival code goes there).
4. The window timer per intent and the window-end reach check (§5.5.2).
5. The transfer path call for follow-me only (§5.5.4); the hand-off adds no call.
6. `_maybe_activate_slot_scene` (override read, result note, B2 slot retry), its day / evening caller (reads) and sleep
   caller (must not read).
7. `automation.py` `note_manual_light`: no new caller (guard grep test).
8. Every `media_player.*` / `music_assistant.*` / `scene.turn_on` call in both music files (all with `ura_ctx_kwargs`):
   the start, the window-end stop, the departure pause.
9. The departure subscription and the return-check reads (§5.7); the room `occupancy_timeout` read.
10. The guests read (`get_house_census` comfort view + house state), used by music gate 3 and scene gate 4.
11. The options-save path and the master form (built in §10.1); the follow-me field on the music form (D2b).
12. Every read of `person_profiles`; the amend function.

## 8. Deliverables

**D0 probe.** Done (`AUDIT_identity_actions_d0_2026_11_15.md`). **D0b** (§4) runs before the D2 build: guests-detected
share at counted arrivals, own-room reach within 900 s. Live: n/a.

**D1 profile store, People step, sensor, no-reload, master, portability.** Built (§10.1); ships first with the §10.1 fix
list and the post-install B0 check. Tests (built): `test_person_profile.py` suite incl.
`::test_profile_keyed_by_one_id_rule`, `::test_owners_derived_shared_master`, `::test_people_save_in_reload_suppress_allowlist`,
`::test_people_save_no_reload_real_options_update`, `::test_suggestions_never_stored`, `::test_master_defaults_on_when_unset`,
`::test_master_false_respected`, `::test_cond_helper_falls_back_without_visible`, `::test_cond_helper_passes_visible`,
`::test_people_schema_with_marker_serializes`, `::test_people_form_matches_live_fixture` (skips until B0 records the
fixture; a skip is not a pass), `::test_room_step_one_field_per_player_room`, `::test_toggle_off_ignores_stale_fields`,
`::test_room_name_maps_to_entry_id`, `::test_pick_media_drops_browse_entity_id`,
`::test_stored_pick_keeps_browse_player_for_redisplay`. Added by the fix list: `::test_room_music_step_fields_named_by_room`
(A1), `::test_cleared_pick_clears_when_section_present` (A3, shape per B0), `::test_uri_pick_redisplay_saves_unchanged`
(A5), `::test_deleted_room_default_does_not_block_submit` and `::test_retyped_bathroom_dropped_on_save` (B1),
`::test_profile_sensor_drops_deleted_room` (B3). Live: see §10.1 B0.

**D2 arrival music (default mode).** **D2 B0 first, live, operator present (operator #7):** play a stored MA pick (browsed
through one MA player) on a different MA player, on the native player of a bedroom with a WiiM (`media_player.jayas_room_3`)
and on the master's Sonos; record in the README whether the id plays, the value shape, and whether the URI fallback is
needed; if MA ids do not play across players, enable `PEOPLE_MUSIC_URI_FALLBACK_ENABLED` with the A5 fix and record it.
**D0b** numbers recorded beside it.
Verify (each with its discriminating counter-observation):
- Oji not_home 4 h, GPS-led edge, idle Sonos, nobody placed in the master -> `started` in the master at `t_a`, before he
  reaches the room (an entry-triggered design: nothing plays until he walks in: discriminates).
- Jaya, BLE-only, BLE-led counted edge -> `started` on `media_player.jayas_room_3` (an F5-source design that needs a
  `geofence` label from GPS: no intent for Jaya: discriminates).
- A `ble` F5 30 s after the edge -> one intent, one start (reading F5s: `intent_duplicate` or a second start: discriminates).
- GPS flap 40 s while Oji is in the master -> no intent, `skipped_not_counted_return` subtype `not_counted`, nothing
  plays (no counted gate: `started` on a person who never left: discriminates).
- HA restore `unknown -> home` with no real 15-minute absence -> no intent, subtype `not_counted` ("no departure seen").
- Edge 5 minutes after a restart -> subtype `boot`, in the NM digest.
- Ezinne placed in the master -> `skipped_occupied` `tracked_person`. Census `unidentified 1` -> `skipped_guests`.
  Untracked occupant 30 minutes, census at 0 -> `skipped_occupied` `backstop` (backstop 0: `started`: discriminates).
  Room occupied 3 minutes, nobody placed, census 0 -> `started` (rule B; a time lead of 120 s: `skipped_occupied`:
  discriminates). Oji already in the master on his own motion for 20 minutes -> `started` and `arrived` at once (backstop
  without the own-placement exception: `skipped_occupied` on himself: discriminates).
- Native idle but MA playing -> `skipped_playing`. 23:30 -> `skipped_quiet`.
- Oji reaches the master at minute 9 -> `arrived`, music still playing at minute 16 (window-end stop without the reach
  check: stopped: discriminates). Never reaches it -> `wait_expired_stopped` at minute 15. Passes through between
  listener calls -> `arrived` `late_seen`. Paused by hand at minute 4 -> `reversed`, no stop call. Podcast started at
  minute 6 -> `wait_ended_not_ours`, no stop. Reaches it at 15:10 -> `stopped_then_arrived` and the trip-wire counter.
- After `arrived`, Oji walks to Study A with music following on -> the music transfers through the transfer path; with
  it off -> the music stays in the master and step 8 issues no call.
- Restart mid-wait -> `wait_lost_restart`, music left playing. Restart before the start decision -> `intent_lost_restart`.
- `auto_music` turned off after the intent opened, before start -> `skipped_toggled_off`.
Tests: `test_arrival_music.py::test_counted_edge_starts_in_own_room_before_entry`,
`::test_ble_only_person_edge_starts`, `::test_no_f5_read_ble_f5_no_second_intent`,
`::test_subscribe_person_edges_only_no_raw_connect`, `::test_gps_flap_not_counted_opens_no_intent`,
`::test_uncounted_return_no_departure_seen_opens_no_intent` (safety drill 1),
`::test_recent_departure_flap_opens_no_intent` (safety drill 2), `::test_boot_window_edge_fails_closed_counted_in_digest`,
`::test_stale_source_edge_opens_no_intent`, `::test_duplicate_intent_counted`, `::test_target_room_bedroom_first_then_bathroom`,
`::test_no_player_room_skips`, `::test_tracked_person_in_room_blocks`, `::test_guests_detected_blocks`,
`::test_backstop_blocks_long_occupant`, `::test_short_occupancy_nobody_placed_starts`,
`::test_own_placement_skips_backstop`, `::test_never_interrupts_native_or_ma_playing`, `::test_quiet_and_sleep_skip`,
`::test_paused_room_skips`, `::test_gap_per_person`, `::test_pick_media_precedence`, `::test_slot_from_room_resolve_slot`,
`::test_verify_on_player_state`, `::test_ma_first_native_fallback`, `::test_no_bonus_joins`,
`::test_arrived_within_window_keeps_playing`, `::test_window_end_stops_when_never_reached`,
`::test_window_end_move_log_late_seen_not_stopped`, `::test_window_end_truncated_location_decides`,
`::test_reversed_ends_wait_no_stop`, `::test_not_ours_ends_wait_no_stop`, `::test_stop_only_matching_content`,
`::test_stopped_then_arrived_counted`, `::test_handoff_music_following_transfers_when_enabled`,
`::test_handoff_stays_when_music_following_off`, `::test_no_step8_call_after_arrived`,
`::test_wait_lost_restart_leaves_music`, `::test_intent_lost_restart_counted`, `::test_scene_lost_restart_counted`,
`::test_toggle_off_before_start_skips`, `::test_every_intent_ends_counted`, `::test_zero_fire_tripwire`,
`::test_stop_premature_tripwire`, `::test_guest_block_tripwire`, `::test_listener_removed_when_no_waits_and_at_teardown`,
`::test_callback_sync_schedules_only`. Config extremes: window 0 (no intent opens); window 3600; backstop 0 and 3600;
gap 0; volume 0.05 / 1.0 with scale 1.5; rooms empty; own room with no player; two own bedrooms with players (stored
order wins). Live: the first opted-in counted arrival gives `started` (music audible in the own room) or a named skip in
the decision log, then `arrived` or `wait_expired_stopped`; zero `stopped_then_arrived`; the diagnostics counters show
`skipped_not_counted_return` `not_counted` for any GPS flap that day with no `started` paired with it.

**D2b follow-me option.** `CONF_ARRIVAL_MUSIC_FOLLOW_ME` field (default off) and §5.5.4. Verify: option off -> default
mode exactly (pinned by running the D2 suite with the field absent and False); option on, Oji walks Kitchen (speaker)
-> stairs -> master -> starts in the Kitchen, transfers to the master, `arrived`, hand-off; option on, stays in the
Kitchen 15 minutes -> stopped there; option on, music following off for Oji -> still transfers inside the window, never
after. Tests: `test_arrival_music.py::test_follow_me_off_is_default_mode`, `::test_follow_me_starts_first_speaker_room`,
`::test_follow_me_transfers_inside_window_only`, `::test_follow_me_handoff_in_own_room`,
`::test_follow_me_window_end_stops_where_music_is`, `::test_follow_me_gates_apply_per_room`. Live: n/a (off).

**D3 welcome scene.** Verify: arrival with `auto_scene` and a slot scene for the master -> exactly one `scene.turn_on`,
the welcome scene (without the override: the slot scene: discriminates) -> `scene_applied` then `scene_confirmed`; no
slot scene configured -> the welcome scene still applies; manual hold -> `scene_skipped_hold`, per-light path; welcome
scene entity unavailable -> the slot scene applies (`scene_fallback_slot`; rev 3.4 behaviour: per-light: discriminates);
welcome and slot scenes both unavailable -> `scene_fallback_failed`, per-light path; Ezinne placed in the master ->
`scene_skipped_occupied`, slot scene; guests detected -> `scene_skipped_guests`; Ziri walks into Jaya's empty bedroom
first inside Jaya's window, nobody placed -> Jaya's scene, then `scene_unconfirmed` (the accepted cost); bathroom entry ->
slot scene; sleep caller never reads the override; two owners' windows open -> `scene_skipped_ambiguous`; `auto_scene`
off mid-window -> `scene_skipped_toggled_off`; no engine in `hass.data` -> slot scene, no error. Tests:
`test_welcome_scene.py::test_entry_override_replaces_slot_scene`, `::test_one_scene_call_per_entry`,
`::test_welcome_without_slot_scene`, `::test_manual_hold_blocks_welcome_scene`,
`::test_unavailable_welcome_retries_slot_scene`, `::test_error_welcome_retries_slot_scene`,
`::test_hold_stays_per_light_no_retry`, `::test_both_scenes_unavailable_per_light`, `::test_scene_tracked_person_blocks`,
`::test_scene_guests_block`, `::test_scene_no_near_rule_first_walker_gets_scene`, `::test_scene_unconfirmed_counted`,
`::test_scene_ambiguous_two_owner_intents`, `::test_scene_rooms_default_bedrooms_only`, `::test_scene_shared_gates`,
`::test_scene_independent_of_music_outcome`, `::test_sleep_caller_never_reads_override`,
`::test_scene_toggle_off_mid_window`, `::test_no_engine_falls_back_to_slot_scene`, `::test_no_new_note_manual_light_caller`,
`::test_scene_entry_missed_counted`. Live: the first opted-in arrival gives `scene_applied` + `scene_confirmed` and one
"Room entry [...]: activating ... scene=<welcome>" log line, no second scene line.

**D4 departure pause.** Verify: named exit at 0.9, stamp live, room still occupied at the edge and the person STALE in
it, room vacant 3 min later -> `departure_paused` within one person-coordinator interval of vacancy (a check only at the
edge: `departure_kept_occupied`: discriminates); room occupied to the wait's end -> `departure_kept_occupied`; another
person placed -> `departure_kept_shared`; music following carried the music to Study A after the hand-off ->
`departure_kept_not_ours`; GPS flap arms the wait, Oji walks downstairs -> `departure_kept_returned` (no return check:
`departure_paused` on a person at home: discriminates); edge log truncated and empty -> `departure_kept_returned`
`truncated`; Jaya's named exit 2 min after she leaves her 500 s room, room vacant 11 min after the arm ->
`departure_paused` inside the 800 s wait. Tests: `::test_departure_named_exit_arm_room_timeout_500`,
`::test_flap_departure_then_return_does_not_pause`, `::test_departure_return_check_truncated_fails_closed`,
`::test_departure_wait_is_room_timeout_plus_margin`, `::test_named_exit_arm_return_check_uses_epoch`,
`::test_departure_pauses_when_room_empties_after_exit`, `::test_departing_person_stale_ble_excluded`,
`::test_departure_wait_ends_kept_occupied`, `::test_departure_never_pauses_others`,
`::test_departure_after_handoff_transfer_not_ours`, `::test_departure_on_residency_edge_via_subscribe`,
`::test_departure_toggle_off_during_wait`, `::test_stamp_lost_restart_counted`. Config extremes: margin 0 and 3600; a
room with `occupancy_timeout` 0 and margin 0. Live: the first departure after a start gives `departure_paused` or a kept
reason with the room's occupied state in the decision line.

**D5 arrival record + count follow-up (P2-D9).** Crossing-vision tests plus `::test_count_followup_via_amend_function`,
`::test_r7_and_perimeter_followup_same_crossing` (at most 3 sends per crossing), `::test_low_confidence_names_render_unrecognised`,
`::test_count_followup_dark_until_f_notify`. Builds when step 7's amend function lands. Live: one
`crossing_vision_arrival` row with n, k, `guests_unnamed`; `get_last_arrival_record` returns it.

**D6 episodes.** `arrival_music` and `welcome_scene` move into `MEMORY_WRITER_BACKED_EPISODE_TYPES` in the D2 / D3
commits that add their writers (exempt with reason while the master is off). Outcomes in the NM digest.

**D7 docs, same commit as each ship.** `MUSIC_FOLLOWING.md` arrival, hand-off and scene sections; manual §5.5 comfort
rows; presence state of play §1 (step 8 as a residency-record consumer; the music engine no longer connects
`SIGNAL_PERSON_ARRIVING`; the `occupied_since()` reader); CLAUDE.md 6.0.0 = step 8, quoting "step 8 is fine"; the stale
`music_following.py:567` docstring (review B4, fixed in §10.1).

**Mutation drills (RED then restore), D2-D4:** subscribe to F5 instead of the record (the `ble` duplicate must go RED);
drop the `counted` check; drop the `in_boot_window` check; drop the `source_stale` check; drop the tracked-person check;
drop the guests check; drop the backstop; drop the own-placement exception to the backstop; drop the MA playing check;
stop at window end without the reach check; drop the move-log read at window end; stop without the content-id match; let
the listener stop music after `arrived`; drop the hand-off's `_person_enabled` read (always transfer); start at entry
instead of at `t_a`; read `music_day` without its toggle; issue the slot scene instead of the override when eligible;
retry the slot scene on `hold`; skip the slot retry on `unavailable`; call `scene.turn_on` from the engine; let the
sleep caller read the override; let a bathroom return a scene; drop the departure return check; count the departing
person in the "tracked person here" check; pass the named exit's `datetime` to the edge read; drop `intent_lost_restart`
/ `wait_lost_restart` / `scene_lost_restart` from the sweep; bypass the amend function; render a 0.6 name. Follow-me
(D2b): transfer after the window; skip the gates in the first speaker room.

## 9. Knobs

| Knob | Default | Rung | Why / kill |
|---|---|---|---|
| `CONF_MUSIC_ON_ARRIVAL_START` (REUSED, "Arrival actions") | on (unset live) | 2 | House master for music and scene; off = no intents |
| Profile fields (§5.1) | all off / empty; volume 0.30 | 2 (People) | Per-person opt-in per action |
| `ARRIVAL_WINDOW_S` | 900 (operator: "15 min") | 1 | One window for the music wait, the follow-me window and the scene window. Review-only: it sets when step 8 stops someone's music. 0 = no intent ever opens (the arrival kill switch below the master) |
| `ARRIVAL_OCCUPIED_BACKSTOP_S` (NEW) | 480 (operator: "8 min kept as backstop for phoneless guests") | 1 | A target room occupied at least this long before the arrival, with the arriving person not placed in it, blocks the start. 0 = backstop off (the tracked-person and guest checks stay). Not a kill switch for the occupied rule, which has none |
| `CONF_ARRIVAL_MUSIC_FOLLOW_ME` (NEW) | False | 2 | Operator: "This can be an option". House-level field on the music form; per-deployment behaviour choice, changed rarely. False = default mode |
| `ARRIVAL_SCENE_CONFIRM_S` | 120 | 1 | Wait for the layer to place the owner after a welcome scene; counting only |
| `ARRIVAL_MIN_GAP_S` | 3600 | 1 | No repeat on a door bounce; per person per action |
| `ARRIVAL_VERIFY_S` / `ARRIVAL_REVERSAL_S` | 20 / 120 | 1 | Ground-truth windows; `ARRIVAL_REVERSAL_S` also bounds the `stopped_then_arrived` watch |
| `RESIDENT_RETURN_MIN_AWAY_MIN` (REUSED, `const.py:4109`) | 15 | 1 | Inside `counted`; shared with residency and the lock; not re-tuned here |
| `RESIDENT_RETURN_BOOT_WINDOW_S` (REUSED, `const.py:4110`) | 600 | 1 | Inside `in_boot_window`; the post-restart dead window; shared |
| `ARRIVAL_DEPARTURE_VACANCY_WAIT_S` | 300 | 1 | Margin added to the stamped room's `occupancy_timeout`. 0 = wait exactly the room timeout |
| `ARRIVAL_MUSIC_DEPARTURE_PAUSE` | True | 1 | False = no departure action |
| Trip-wire thresholds | `arrival_action_zero` 10 / 7 d; `ARRIVAL_STOP_PREMATURE_NM` 3 / 7 d (NEW); `arrival_guest_block_high` share 0.5 with >= 10 intents / 7 d (NEW, `ARRIVAL_GUEST_BLOCK_NM_SHARE`); `ARRIVAL_ENTRY_MISSED_NM` 3 / 7 d; failing 3 / 24 h | 1 | 0 = that trip-wire off |

Removed in rev 3.5: `ARRIVAL_OCCUPIED_LEAD_S` (operator rule B), `ARRIVAL_COUNTED_EDGE_LOOKBACK_S` (the trigger is the
record itself; nothing to look back for). Earlier removals: `ARRIVAL_MUSIC_ALLOW_SHARED_ROOM`, `ARRIVAL_SCENE_SETTLE_S`,
`switch.ura_music_arrival_start`.

## 10. Dependencies, seams, sequence

**Before v6.0.0:** step 6 census deconfliction; layer ship 3a (D2 `subscribe_person_edges` / `get_person_edges_since` /
`person_edges_truncated_since`, D4 `location_moves_since` / `location_moves_truncated_since` and the class census read,
D7 guard test; built, phase 2 included); MUSIC-FOLLOWING-TRANSFER-REPAIR-1 (shipped); step 7 for the named-exit departure
arm (`departure_candidate`) and D5's amend function. **BLE-ARRIVAL-PRODUCER-HVAC-GATED-1 is no longer a v6.0.0
dependency:** step 8 reads no F5, and BLE-led arrivals reach it through the composed `person.*` edge, which the HVAC
pre-arrival switch does not gate. The card stays on the board for HVAC's own use; this plan does not decide it.

**Guard entries (ship 3a D7 allowlist), changed in the D2 commit.** The allowlist file is
`quality/tests/person_awareness_layer_allowlist_PROVISIONAL.py` (`ROWS`, whose `max` values sum to
`LAYER_ALLOWLIST_TOTAL`, and `LISTED` with `LISTED_RESERVED`):
- retire the `LISTED` key `('R10', 'domain_coordinators/music_following.py',
  'MusicFollowingCoordinator.async_setup:ura_person_arriving')` (the raw connect is deleted; `ROWS` total unchanged);
- un-reserve the `LISTED` key `('R10', 'music_following.py', '<step 8 §5.4 music listener>:async_add_listener[PC]')`:
  rename it to the real qualified symbol of the registering function and remove it from `LISTED_RESERVED`, same commit;
- the arrival and departure `subscribe_person_edges` callbacks are listed under rule R14 as ship 3a defines it;
- `get_person_edges_since`, `person_edges_truncated_since` and `subscribe_person_edges` are in `READ_LIST["PRESENCE"]`
  (`quality/tests/_layer_guard_engine.py`). The builder confirms `get_house_census` is there (ship 1 read); if not, the
  D2 commit adds it to `READ_LIST["PRESENCE"]` and the contract §4 PRESENCE read list together, as a class read. Rev
  3.4's `get_room_zone` addition is dropped (no near rule).

**Seams.** Music following (arc rule 6): the hand-off reads `_person_enabled` and relies on the existing transfer path
unchanged; follow-me passes one flag into the transfer call (D2b), which is the only change to the music-following
surface and is reviewed under music following's own invariants (bounce safety, Sonos leads in the master, MA first).
Lighting: the welcome scene is a read inside the existing entry scene path, plus the B2 slot retry inside the same
function; no new lighting writer, no manual hold. G6-ONE-BLE-ROOM-READ-1: one call site to swap (§5.4). AI room rules /
OC: they read the profile, never write it. F-NOTIFY: the count follow-up waits for CD4; v6.0.0 does not. Arc map M11
updated at approval.

### 10.1 Ship the People screen first (operator #6)

**What ships.** The built §10.1 set on `feature/step8-identity-actions` (People step, profile store, profile sensor,
master default and relabel, `_cond`, `pick_media` / `play_pick`, `occupied_since()`, the entry-path hook with the engine
stub returning None, D6 episode types), alone, as a PATCH release (version assigned at deploy). Nothing acts: the engine
stub returns None, the F5 handler stays a no-op, and no arrival code exists (review B check 2). Before it ships, the fix
list below lands on the branch, with review A's verdict items re-checked by the same reviewers.

**Fix list (must land before the §10.1 ship):**

| # | Finding | Fix |
|---|---|---|
| A1 | "Music by room" fields are keyed by room config entry_id, so HA shows the raw id as the label | Key each field by a stable slug of the room's own `room_name` (URA's own config) and map it back to entry_id on save; the description lists the rooms in order. Test `::test_room_music_step_fields_named_by_room` |
| A3 | A cleared optional field may be left out of the submission, so `merge_profile_save` keeps the old value and a cleared pick can never clear | Settled at B0 (below): if the frontend omits a cleared field, use `_present` (the section-present set already returned) to treat "section submitted, key missing" as cleared; if it sends null / `{}`, the current code holds and the test pins that shape. Test `::test_cleared_pick_clears_when_section_present` |
| A5 | A pasted-URI pick has no `entity_id`; redisplayed as a suggested value and saved unchanged it fails `MediaSelector.__call__` | Redisplay a URI pick in the URI text field, not the MediaSelector, so an unchanged save passes; latent while `PEOPLE_MUSIC_URI_FALLBACK_ENABLED` is False, fixed now so D2 B0 can turn it on. Test `::test_uri_pick_redisplay_saves_unchanged` |
| B1 | A stored room entry_id that is no longer an option (room deleted, or a bathroom retyped) makes the form refuse its own default, blocking Submit | Filter the room-field defaults to the current options and drop dangling ids on save. Tests `::test_deleted_room_default_does_not_block_submit`, `::test_retyped_bathroom_dropped_on_save` |
| B3 | The profile sensor shows a deleted room as its raw entry_id | Drop unknown ids from the `rooms` attribute (paired with B1). Test `::test_profile_sensor_drops_deleted_room` |
| B4 | `music_following.py:567` docstring says the master is "OFF by default" | Correct it to the `DEFAULT_MUSIC_ON_ARRIVAL_START = True` default |

Recorded, not in the list: A4 / B2 (welcome-scene fallback) is a D3 change (§5.6); A6 (suggestion window counts the
whole house's visits, display only) and A7 (the cached room-name map) are D2 items.

**A2 and the B0 live check, right after install (operator #6).** Review A2 required the D1 B0 spike before ship; the
operator chose to run it immediately after install instead. Right after HA restarts on the release (not while the house
sleeps), the orchestrator, in the live CM options flow on HA 2026.11.1: (i) opens People for one resident, confirms the
fields render, the `visible` conditions hide and show as §5.2 says, and saves the serialized `visible` keys as
`quality/tests/fixtures/people_form_visible_2026_11_1.json` (committed; `::test_people_form_matches_live_fixture` then
runs instead of skipping); (ii) picks music through the MediaSelector, saves, and records the submitted value shape and
whether `entity_id` was required; (iii) clears a pick and saves, and records whether the field was omitted or sent empty
(settles A3); (iv) confirms the save caused no CM reload (log). **Rollback rule:** if the form fails to render, refuses
a valid save, loses a stored profile, or reloads the CM entry, roll back to the prior release the same session and
record why in the README; the plan then goes back to the operator before any further step 8 ship. The MA playback test
on another player is NOT part of this B0; it is D2 B0 with the operator present (§8).

**Base branch.** The step 8 branch already carries develop (music repair shipped; `48fd8deb` merge). Later step 8
branches cut from develop. New step 8 code reads no `person_coord.data`, only the named methods.

**Decided deviations in the §10.1 build (2026-11-15):**

| Piece | Plan text | As built | Reason | Anchor |
|---|---|---|---|---|
| Stored music pick (§5.3) | "URA stores `media_content_id` + `media_content_type` and drops `entity_id`" | The stored pick KEEPS the browse player's `entity_id`; playback strips it (`person_profiles.play_pick`, used by `pick_media`) | HA's `MediaSelector` without `accept` rejects a value with no `entity_id` (`helpers/selector.py` `MediaSelector.__call__`, HA 2026.2.3), so an unchanged re-save would fail. Playback never reads it | `test_person_profile.py::test_pick_media_drops_browse_entity_id`, `::test_stored_pick_keeps_browse_player_for_redisplay` |
| `note_arrival_scene_result` (§5.6) | `note_arrival_scene_result(room, applied: bool)` | `note_arrival_scene_result(room, result: str)`, `result` one of `const.ARRIVAL_SCENE_RESULT_*` (`applied` / `hold` / `unavailable` / `error`) | A bool cannot separate `scene_skipped_hold` from the unavailable case, which D3 now retries (B2) | `test_arrival_scene_entry_hook.py::test_hold_and_unavailable_reasons_differ_same_room` |
| `occupied_since()` | "NEW read-only accessor" | A delegate of the existing `UniversalRoomCoordinator.get_became_occupied_time()` (v3.2.4, same value) | Prior art the scan missed | `test_occupied_since.py` |

**Then:** this rev's plan review (§11) -> D0b -> D2 B0 (operator present) -> D2 + D3 + D4 build -> reviews -> v6.0.0;
D2b builds after D2 on the same branch; D5 when step 7's amend function lands.

## 11. Tier

Tier 2-DB (operator yes). The §10.1 fix list: the same A and B reviewers re-check their findings (Tier 1 scope inside
the cycle). Rev 3.5 itself gets one adversarial plan review plus framing G (goal fidelity) before D2 dispatch: rev 3.5
changes what is delivered (start-at-arrival, hand-off, no near rule), so G checks it against the 2026-11-15 quotes. The
D2-D4 build gets three framing-disjoint code reviews (A gates, start and wait logic, outcome contract, pick precedence;
B integration, restart sweep, listener and timer lifecycle, entry scene path and B2 retry, hand-off through the real
transfer path, departure wait; C per-site source mutation over the §8 drills) plus G. P2-D9 keeps the crossing-vision
plan's own bar. Release v6.0.0 at deploy.

## 12. Remaining operator questions (recommended defaults; built as the defaults until answered)

1. Bathrooms. Default: arrival music targets a bathroom only when the person has no own bedroom with a speaker; the
   welcome scene runs in bedrooms only.
2. Should an arrival into a room that is not yours but empty (the family room) play anything? Default no in the default
   mode (follow-me covers it when turned on).
3. Welcome scene outside an arrival (any entry into your room after 15 min away)? Default no: arrival only.
4. **Departure pause after the hand-off.** The operator asked for no arrival state after the hand-off ("we don't have
   too much state to track") and earlier for a departure pause ("Departure pause is fine"). The pause needs one record
   per person (the stamp: entity and content id) that outlives the hand-off. Default, built until answered: keep the
   stamp, as departure state, until the pause, a kept outcome or a restart; after a music-following transfer the pause
   reads `departure_kept_not_ours` (it pauses only music still playing where step 8 started it). The alternative is to
   drop the stamp at the hand-off, which ends the departure pause for every arrival that reaches its room.
5. **Guests detected.** Default: house state `guest`, or the comfort census view reading at least one unidentified
   person. D0b measures how often that is true at a resident's own counted arrival; if the arriving resident's own body
   often reads unidentified at that moment, the read needs a narrower form (for example unidentified for longer than
   the arrival lead, or zone-level) and goes back to the operator with the number before D2 builds.
6. **Follow-me scope.** Default: one house-level option. A per-person People field is the alternative (it changes the
   shipped People step).

## 13. Non-goals

Per-person temperature (cut; "the exclusion is fine"); guest-gate door identity; predictions writing profile fields
(they suggest only); actions for guests or untracked people; transfers outside follow-me (music following owns them);
any security, lock, HVAC or house-state consumer; Protect names; interior vision (step 9); a trial or shadow stage; a
room-entry "owners" field; re-applying the welcome scene mid-occupancy; building `persons_in_room`
(G6-ONE-BLE-ROOM-READ-1); an independent BLE arrival source (the audit found none: 0 of 31 `ble` F5s without a prior
edge; revisit only if a `ble` F5 ever leads the `person.*` edge by minutes); welcome scenes anywhere the arrival leads
(operator: "Long run. Let's nail the room first"; card WELCOME-SCENE-ARRIVAL-PATH-1 to mint, revival trigger: the
own-room scene validated live, with `scene_confirmed` on most arrivals).

## 14. Plan completion tracking

Built and shipping first (§10.1): the PERSON-PROFILE-PREFERENCES-1 configuration (rooms, owners, music by time and room,
per-action opt-in, welcome scene field), plus the inert pieces D2/D3 use. To build: D0b, D2, D2b, D3, D4, D5, D6
writers, D7. Nothing from the card is parked except welcome scenes beyond the own room (operator's call, §13). The count
follow-up flip is census CD4. DEPARTURE-ACTIONS-1: only the pause.

**Removed in rev 3.5, and why:**

| Removed | Why |
|---|---|
| F5 intake (`subscribe_person_arriving`) and the per-source gates | Audit: one physical arrival = one `person.*` edge; `ble` and `camera_egress` F5s are second views (§5.4) |
| The `ble` / `camera_egress` departure-side bar (`get_residency_snapshot` `left_at` / `arrived_at` rule), its `no_departure_seen` / `recent_departure` subtypes, the 15-minute `ble` / `camera_egress` post-restart dead window | Same; the `counted` flag on the edge carries the 15-minute bar for every arrival |
| BLE-specific tests and drills (patio LOST, S3 dog walk, overrule-only absence, unknown walk, `ble` boot window, same-tick move) | Same. The two safety drills stay as `::test_uncounted_return_no_departure_seen_opens_no_intent` and `::test_recent_departure_flap_opens_no_intent` |
| BLE-ARRIVAL-PRODUCER-HVAC-GATED-1 as a v6.0.0 dependency | No F5 is read (§10) |
| `ARRIVAL_COUNTED_EDGE_LOOKBACK_S`, the geofence lookback read and its truncation outcome `skipped_edges_truncated` | The trigger is the record itself |
| Start-at-room-entry: the move-log cursor, the entry-time reads (`get_person_previous_location_time`, `get_person_previous_seen`), the entry-time clamp, `entry_missed` / `window_expired` / `window_expired_truncated` for music | Operator #1: start at arrival in the own room and wait |
| `ARRIVAL_OCCUPIED_LEAD_S` and the onset-versus-entry rule | Operator #4 (rule B); D0 measured 3-7 minute own-motion leads |
| The §12 Q4 near rule (same house zone, adjacency, approach hall), `scene_skipped_not_near`, the `get_room_zone` read and its guard-list addition, the D0 (a2) near-rule shares as a gate | Operator #1 |
| The "no speakers in Jaya / Ziri bedrooms" note | Operator #8, verified live |
| `intent_duplicate_source` (second source recorded) | Replaced by `intent_duplicate`; there is one source |

## 15. Changes from rev 3.4 (for the equivalence review)

| Area | Rev 3.4 | Rev 3.5 |
|---|---|---|
| Trigger | F5 via `subscribe_person_arriving`; three sources, per-source counted-return rules | One counted residency arrival record via `subscribe_person_edges`; no F5 read |
| Music start | At the first own-room entry inside the window | At the arrival, in the own room, before the person gets there |
| Music end | None after start (departure pause only) | Wait: keep if reached within the window, stop at window end if not; hand-off to music following |
| Occupied rule | Onset earlier than entry minus 120 s, or another tracked person placed | Another tracked person placed, guests detected, or a 480 s backstop with the person not placed |
| Welcome scene | Same-house-zone near rule; unavailable fell to per-light | Own bedroom, no near rule, guests check; unavailable / error retry the slot scene |
| Options | none | Follow-me (off) |
| §10.1 | Built in parallel; B0 spike before ship | Ships first, alone, with the review fix list; B0 right after install, rollback rule |
| v6.0.0 dependencies | Included BLE-ARRIVAL-PRODUCER-HVAC-GATED-1 | Dropped |
| Evidence | D0 to run | D0 run; corrected source framing; D0b added |
