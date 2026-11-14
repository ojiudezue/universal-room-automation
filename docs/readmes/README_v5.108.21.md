# v5.108.21: identity arc batch 1

PATCH. Five reviewed branches merged on `release/batch-1` (identity / vision / census arc steps 1, 2, 3, 5 and the W1 pairing fix).

## Pre-merge gate (2026-11-14)
- Full name-diff vs develop c5cd29c0 with `URA_SOURCE_MUTATION=1`: 0 NEW, 0 GONE (one pre-existing failure on both sides: `test_ble_extend_not_create.py::test_MUTATION_m2_seeding_hoisted_above_predicate_makes_order_test_red`).
- D7 hygiene: 84 passed, 3 structural skips.
- Isolated pass NARROWED to the 13 test files the batch added or modified (the full 334-file importer list would take hours): 0 NEW. First gate run found 3 NEW names, fixed test-only in d69200a0 (a re-anchored mutation test; two tests made hermetic against a develop-side module-stub polluter, test_fan_incident_2026_08_01_replay.py).
- Reviews: each branch had three framing-disjoint reviews (A/B/C) plus fix-ups and re-verifies; review docs under docs/reviews/code-review/.

## Live validation
Prospective criteria are in each section below; the post-restart `Validated <date>` table replaces them after the restart. HA restart held while the house is in sleep (operator rule).

## Phone-left-behind camera leg (PHONE-LEFT-BEHIND-CAMERA-LEG-1)


Version: TBD at deploy (patch). Branch `feature/phone-left-behind-camera`. Plan
`docs/planning/PLANNING_phone_left_behind_camera_leg.md` rev 2. Operator ruling A (2026-11-13): the
camera leg is DISPLAY ONLY.

### What changed

- **D1 — phone-left-behind attributes.** `binary_sensor.universal_room_automation_<person>_phone_left_behind`
  now shows the person's newest sighting from the person-sighting store
  (`PresenceCoordinator.get_last_person_sighting`), keyed by `person_coordinator.tracked_person_entity_id`:
  `camera_leg: display_only`, `last_camera_sighting_at` (static between sightings), `last_sighting_source`, `last_sighting_camera`, `last_sighting_room`,
  `last_sighting_census_veto`. The verdict (`on` / `off`) is unchanged: step 4 no longer reads a camera
  store and returns what it returned on every live tick before (the old store never held a name).
  The attribute `phone_left_behind_hours` is removed.
- **D2 — likely-next-room.** `sensor.<person>_likely_next_room` `camera_last_seen` / `camera_last_room` /
  `transit_camera_validated` read the same store (window `NEXT_ROOM_CAMERA_SIGHTING_MAX_AGE_S` = 4 h).
  The window is applied when the attributes are read, not only at the sensor's update (review B2).
  The sensor is disabled by default.
- **D3 — legacy store.** `TransitValidator` stores every camera sighting as `unidentified`; the named
  branch, `get_last_camera_sighting` and `TRANSIT_PHONE_LEFT_BEHIND_HOURS` are deleted. Path validation
  is unchanged for the only history live data produces.

### Knobs

| Knob | Value | Rung | Off |
|---|---|---|---|
| `NEXT_ROOM_CAMERA_SIGHTING_MAX_AGE_S` | 14400 | 1 (const.py) | `<= 0` = never shown |

### Live validation (prospective; replace with a `Validated <date>` table after restart)

| # | Check | Pass looks like | Different failure looks like |
|---|---|---|---|
| L1 | Jaya flag attributes after a family-room face | `last_camera_sighting_at` set, `last_sighting_camera` set, `camera_leg: display_only` on `binary_sensor.universal_room_automation_jaya_phone_left_behind` | null while `sensor.ura_presence_house_state` `face_sighting_last` names Jaya = key or wiring miss |
| L2 | Verdict ignores sightings | at least one `on` row (arrival or restart tick) whose `last_camera_sighting_at` is under 1 h old; if none occurs, in-suite only (`test_fresh_sighting_does_not_change_verdict`) | every `on` row lacks a recent sighting while that person has recent sightings = sightings leaking into the verdict |
| L3 | No recorder churn | between sightings and verdict changes the four flags write no new state rows | a row every 15 min or every ~30 s = a moving attribute is back |
| L4 | Transit path validation unchanged | activity-log `path_method` mix similar to the day before, `path_confirmed` present | `path_confirmed` gone = D3 broke unidentified reads |
| L5 | No URA ERROR at boot or on poll | system_log clean of `binary_sensor` / `transit_validator` / `sensor` errors | |

### Not done / deviations from the plan

- **`hours_since_camera_sighting` dropped (plan M2 deviation; review A-M1 / B1).** The plan put it in
  `_unrecorded_attributes` to stop churn. That set only strips the attribute from the recorded blob; HA still
  writes a state row whenever any attribute changes (`homeassistant/core.py` `same_attr` compare). The first
  build stepped it to 15 min, which still wrote up to 96 rows/day/person, and all four sensors are enabled live
  (about 384 rows/day). The fix-up removes the attribute and its quantum constant;
  `last_camera_sighting_at` (static between sightings) carries the same information. Pinned by
  `test_attributes_static_between_polls_no_age`.
- **Accepted A-L1 (verdict identity holds for every reachable input).** Develop's step 4 differed only for a
  camera entity carrying a `person_id` / `face_id` / `label` attribute equal to the person's title-cased
  display name with face recognition on; measured 0 of 102 person entities, so unreachable in this house. A
  future integration that sets such a label would have flipped develop's verdict; this branch never does.
- **Accepted A-L2.** The verdict oracle in `test_phone_left_behind_camera_leg.py` shares that assumption (it
  forces the legacy leg None), so it cannot catch A-L1. Noted in the test docstring.
- **Review B2 fixed.** NextRoom applies the 4 h window at attribute-read time (one dict get), so an aged
  sighting no longer stays shown until the next update.
- D3 drills on deleting the named read / rule 1 are not meaningful (dead branches with no input); INV-3 is
  covered by the hand-derived golden replay instead.
- `test_pathalpha_d2c_d3_observability.py` and `test_v4714_1_forgotten_phone_hotfix.py` fail to collect on
  develop already (import errors unrelated to this change); their source-grep anchors still match the edited
  class.


## Crossing vision Phase 1, shadow (VISION-CROSSING-ANALYSIS-1 phase 1)


Card: VISION-CROSSING-SHADOW-1. Plan: `docs/planning/PLANNING_crossing_vision.md` rev 2 (Phase 1, D1-D3).
Branch: `feature/crossing-vision-shadow`. Tier 2-DB. The orchestrator assigns the version at deploy.

### What it does

For every entry or exit crossing on a door camera, URA asks llmvision (`video_analyzer`, the existing
OpenAI entry, `gpt-4o-mini`) to count the people in the clip of the matching Frigate person event, and
stores the answer next to the camera's own count in one `memory_episodes` row
(`crossing_vision_shadow`). Nothing acts on it. It exists so a weekly scorer can tell whether vision counts
crossings better than Frigate does before anything feeds the census (Phase 2).

### Controls

| Control | Default | Notes |
|---|---|---|
| `switch.ura_crossing_vision_shadow` (Coordinator Manager) | OFF | Turn on after deploy. OFF = no call, no row |
| `number.*_crossing_vision_daily_calls` (Notification Manager device) | 40 | Calls per local day; 0 = off. RAM counter, a restart can allow one more cap that day |
| `LLMVISION_ENRICHMENT_KILL` (const) | False | Code kill for all llmvision use |
| `CROSSING_VISION_*` (const, rung 1) | plan §6 | Model, frames 4, width 768, timeout 90 s, match ±10 s, end wait 120 s, cluster 60 s, concurrency 2 |

### Other changes

- `ura_person_egress_event` carries `peak_person_count` (same value as the DB row; None when ambiguous).
- Diagnostics `crossing_vision_today` and `crossing_vision_last` on Outside: Open Tracks (not recorded).
- Trip-wires: `crossing_vision_zero` (HIGH: 5+ crossings in 24 h with the switch on and no usable count),
  `crossing_vision_errors` (MEDIUM: more than 25 % of 8+ calls failed). The weekly memory-writer check pages
  if no row is written for 7 days, including a switch left off for a week.

### Live acceptance (to run after deploy with the switch on)

- Within 4 daytime hours: at least one row with `outcome = ok`, non-null `people_count` and
  `camera_peak_count` (sentinel-only rows mean the payload is broken).
- Every row's `source_ref` matches an `egress_identity_outcome` row's `source_ref`.
- `crossing_vision_today.calls` is at most today's crossings.
- One new `person_entry_exit_events` row has the same `peak_person_count` as the matching row's
  `camera_peak_count`.
- No `crossing_vision` ERROR in the HA log; no trip-wire page on the first day.

Validation results are written back here after the restart.


## Person-awareness read API, ship 1 (PERSON-AWARENESS-READ-API-1)


Card: PERSON-AWARENESS-READ-API-1 (with PERSON-ID-NORMALISE-ONE-RULE-1). Plan:
`docs/planning/PLANNING_person_awareness_read_api.md` §5 ship 1 (RA1-RA5). Tier 2. Branch
`feature/person-awareness-read-api-ship1`.

### Identity model

Produces no fact. Read surface for F2 (house census, `get_house_census`) and F3 (door crossing,
`get_last_crossing`); `get_last_arrival_record` is the F3-attribute seam for crossing-vision. Consumer class
decides the view (`view_for_class`) and the identity confidence (`CONSUMER_CLASS_MIN_CONFIDENCE`).

### What changed

Behaviour is byte-identical under the live config. No entity, attribute or log line is added or changed.

- **RA1** `PresenceCoordinator.get_house_census(view)` returns a frozen `HouseCensusView` (identified,
  unidentified_or_guests, total, provenance, agreement, as_of) from `census.last_result.house`. Sync, never
  raises; no census or no result gives None. The awareness view returns the trust values with provenance `camera`
  until the census deconfliction plan adds its fields.
- **RA2** `PresenceCoordinator.view_for_class(cls)`: `awareness` only for a class in
  `CROSSING_VISION_CONSUMER_CLASSES` (default `{display}`) that is also legal (`{display, notification}`), with
  `switch.ura_crossing_vision_census_authority` reading `on`. That switch is built by the census plan; until then
  every class reads `trust`. An illegal member raises at import.
- **RA3** `const.CONSUMER_CLASS_MIN_CONFIDENCE` (rung 1, read-only mapping): security 0.9, notification 0.75,
  display 0. Read by `_arrival_departure_notify` (names at ≥ 0.75) and the perimeter D10.5 floor (≥ 0.9).
- **RA4** One id rule in the pure module `person_ids.py`: `tracked_person_entity_id` (moved from
  `person_coordinator`, re-exported there), `slug_of`, `display_of`. Routed: census tracked-slug list, WiFi-guest
  family tracker list, face-name list, perimeter `_tracked_person_slugs`. A display-name `tracked_persons` config
  (`'Oji Udezue'`) now yields `oji_udezue` everywhere (before: `oji udezue`, which emptied sightings, the egress
  BLE leg and perimeter known identities, and counted family phones as WiFi guests). Entity-id config: same slugs
  as before. `PersonCensus.canonical_person_slug` is the public face first-name mapper.
- **RA5** `EgressDirectionTracker.get_last_crossing(camera=None)` returns the last `CrossingRecord` (camera,
  direction, ts, person_id, provenance, confidence, identity_confidence, source_ref), stored right after the
  `ura_person_egress_event` fire with the same values. Wrapped as `PresenceCoordinator.get_last_crossing`.
  `get_last_arrival_record()` returns None until crossing-vision ships its store.

### Knobs

| Knob | Default | Rung | Why |
|---|---|---|---|
| `CONSUMER_CLASS_MIN_CONFIDENCE` | security 0.9, notification 0.75, display 0 | 1 | Doctrine values (manual §5.5); a change needs review |
| `CROSSING_VISION_CONSUMER_CLASSES` / `_LEGAL_` | `{display}` / `{display, notification}` | 1 | Owned by the census plan §3.2 |

### Tests

`quality/tests/test_person_awareness_read_api.py` (real HA core, real URA modules): `test_slug_of_display_of_roundtrip`,
`test_residuals_same_slug_display_and_entity_config` (A-D x display / live-entity config),
`test_class_thresholds_unchanged`, `test_consumer_class_table_values`, `test_consumer_classes_rejects_illegal`,
`test_view_for_class_security_always_trust` (4 class sets x 4 switch values x 9 classes),
`test_view_for_class_display_follows_class_set`, `test_get_house_census_trust_equals_last_result`,
`test_get_house_census_missing_census_none`, `test_get_last_crossing_matches_bus_event`.

### Live validation (prospective)

- **Live:** no entity or log change after restart: `sensor.universal_room_automation_persons_in_house` /
  identified sensors read the same as before; no new WARN/ERROR from `camera_census`, `transit_validator`,
  `perimeter_alert`, `person_ids`.
- **Live:** census `identified_persons` and sighting slugs use the same strings as the day before
  (`oji_udezue`-form; check a `person_sighting` / census attribute).
- **Live:** the next garage crossing's NM text is unchanged in form ("<Name> arrived" at ≥ 0.75, else "Someone").
- **Live:** `grep -rn "get_house_census\|view_for_class\|get_last_crossing\|get_last_arrival_record"
  custom_components/` shows definitions only (callers arrive with the census / crossing-vision plans).


## Camera input stream health S1 (PANEL-KS-HEALTH-AS-INPUT-1)


Cards: PANEL-KS-HEALTH-AS-INPUT-1 (S1). S2 (zone tier, fan recheck, census) is CAMERA-STREAM-DEAD-ZONE-AND-CENSUS-1 and
is NOT in this ship. Plan: `docs/planning/PLANNING_camera_input_stream_health.md`. Tier 2-DB (room occupancy ripples into
lights, fans, HVAC).

### What changed

- A room input (motion / presence / occupancy list) whose own camera entity has read `unavailable` for 120 s no longer
  counts in that room's occupancy. "Own camera" means the input's device carries exactly one enabled `camera.*` entity.
  Devices with no camera, a disabled camera, or two or more cameras (NVR devices) are left alone.
- The rule keys on the camera entity's availability only. It does not look at camera names, the kiosk app or the NVR brand.
  The 120 s must be continuous: if the camera reads `unknown` / nothing for longer than 120 s between two `unavailable`
  readings, the clock restarts. A camera reading `unavailable` with `restored: True` (its integration has not loaded it,
  e.g. Frigate in setup retry) is "no opinion": it excludes nothing and pages nothing.
- The room's camera override (a camera in the room's area whose person sensor reads `on` keeps the room occupied after
  the sensors time out) now skips a person sensor whose own camera is dead, so it can no longer hold the room that way
  (review B-M1). Only the dead-stream exclusion applies here; stuck / chattering exclusions do not, as before (review
  D-M1). An override person sensor that is not a room input is watched and excluded the same way,
  but it is not paged and not shown on the sensor.
- If the exclusion lasts 30 min, one HIGH notification says which input stopped counting and which camera is down, once
  per room input per day. A LOW "counts again" notification follows when the camera returns.
- `sensor.<room>_unavailable_entities` gains two display attributes (not recorded): `camera_stream_dead_inputs` and
  `camera_stream_inputs_resolved`.
- New public getter `camera_input_stream_dead(input_eid)` on the room coordinator (for S2 and a later NVR-witness layer).

### Knobs (all rung 1, `const.py`)

| Knob | Default | Effect |
|---|---|---|
| `CAMERA_INPUT_STREAM_HEALTH_ENABLED` | True | False = no exclusion, no notification (pre-S1 behaviour) |
| `CAMERA_INPUT_STREAM_DEAD_GRACE_S` | 120 | seconds of `unavailable` before inputs stop counting |
| `CAMERA_INPUT_STREAM_DEAD_NM_AFTER_S` | 1800 | seconds of exclusion before the HIGH page; 0 = no page |

### Not in this ship

- S2: the zone tracker, fan recheck and census still count a frozen dead-camera `on` (they never honoured room
  exclusions). Until S2 ships, the Upstairs Hallway zone can still be held by the frozen panel input until the 4 h
  stuck-sensor rule.
- Kiosk app health (`foreground_app`) and kiosk restarts (homelab watchdog), per plan §8 non-goals.

### Acceptance (prospective; replace with a `Validated <date>` table after restart)

- **Live:** `sensor.study_a_unavailable_entities`, `sensor.kitchen_unavailable_entities` and
  `sensor.upstairs_hallway_unavailable_entities` each show `camera_stream_inputs_resolved = 1` and an empty
  `camera_stream_dead_inputs` while the panels stream. The sensor is disabled by default
  (`_attr_entity_registry_enabled_default = False`); on Upstairs Hallway it is `disabled_by: integration` today, so
  enable it before reading (review B-L4).
- **Live:** no `camera-derived input(s) ... have no single camera entity` WARNING in the log for those three rooms after
  restart (a WARNING there means the panel's device did not resolve to one camera).
- **Organic:** the next panel outage lists the panel person input under `camera_stream_dead_inputs` within about 2.5 min
  (120 s grace + one 30 s room poll), and the room is not held occupied by it. Discriminator: under the fix the room's
  `binary_sensor.<room>_occupied` drops one room-timeout after the input is listed; under the old behaviour it stays `on`
  until the 4 h stuck-sensor rule.
- **Organic:** if that outage lasts 30 min, exactly one HIGH `Camera stream dead: <room>` notification, and one LOW
  recovered notification when the camera returns.
- **In-suite only:** the byte-identical cases (unresolved camera, kill switch off) and the grace / NM boundaries are
  proven in `quality/tests/test_camera_stream_health.py`; they cannot be forced live without breaking a camera.


## NVR witness W1: registry-only Frigate/Protect pairing (NVR-WITNESS-CONSOLIDATION-1 W1)


Card NVR-WITNESS-CONSOLIDATION-1. Plan `docs/planning/PLANNING_nvr_witness_layer.md` §5, §8 W1. Tier 2-DB.
Branch `feature/nvr-witness-w1-pairing`. Version to be assigned at deploy.

### What changed

`CameraResolver.resolve_capabilities` gains one acceptance path. For each Frigate input device it reads the Frigate
object name from the device's Frigate identifier (`(frigate, "<instance>:<object>")`, via the existing
`_frigate_object_name_for_device`) and compares it with HA's `slugify` of each camera device's registry name
(`name_by_user`, else `name`). No entity_id is parsed for this. The sibling is accepted only when all four hold:

1. the input device is Frigate and its object name equals the candidate's slugified registry name;
2. exactly one non-Frigate device that owns an enabled `camera.*` entity carries that slug;
3. no other Frigate device has that object name;
4. the candidate device has no Frigate identifier of its own.

Accepted sources carry `correlation_basis = "frigate_object_name"` (visible on the room fused sensor's per-source
attributes). Knob `camera_resolver.RESOLVER_FRIGATE_OBJECT_NAME_EVIDENCE` (rung 1, default True; False = the develop
resolver, byte-identical, tested over all 105 live cameras).

Residual, accepted in the plan: one Protect camera and one Frigate camera with the same name, and no other camera of
that name, pair even if they are two physical cameras. The registry cannot tell that apart from a true pair
(`test_resolver_residual_one_name_one_camera_each_side_pairs`).

### Effect on this house (measured against the live registry, 2026-11-13)

The plan expected one change (garage_a). The live registry gives seven: every Frigate camera whose HA camera entity
did not share a stem with its Protect sibling. The operator accepted all seven pairings on 2026-11-14.

| Frigate camera | Gains Protect source | Fusion key | Live consumer reached |
|---|---|---|---|
| `camera.garage_a_2` | `binary_sensor.garage_a_person_detected` | unchanged (`7c45...`) | transit egress subscription (via census `get_transit_egress_entities`) |
| `camera.upstairs_hall_2` | `binary_sensor.upstairs_hall_person_detected` | `b75c...` → `b063...` | Upstairs Hallway room fused sensor (→ fan veto); person sightings `Upstairs` pick |
| `camera.stairs_top_2` | `binary_sensor.stairs_top_person_detected` | `ebc6...` → `74f1...` | person sightings `Upstairs` pick (`binary_sensor.stairs_top_person_occupancy`) |
| `camera.foyer_fisheye` | `binary_sensor.foyer_fisheye_person_detected` | unchanged | person sightings `Entertainment` pick; its detection legs gain the Protect leg (not a perimeter camera) |
| `camera.rear_ptz_2` | `binary_sensor.rear_ptz_person_detected` | `c887...` → `c62c...` | none live (perimeter configures the Protect entity, which already paired) |
| `camera.utilities_ptz_2` | `binary_sensor.utilities_ptz_person_detected` | unchanged | none live (same) |
| `camera.garage_b_2` | `binary_sensor.garage_b_person_detected` | unchanged | perimeter leg set unchanged (see below) |

**Expected rates (review B-M1).** garage_a gains a third egress trigger (the Protect person sensor). Expect about
12 new directed crossings a week from Protect-only detections, and about 2 a week where Frigate and Protect fire in
opposite directions, giving one extra crossing row and one extra arrived/left notification. This split already happens
on the two-leg doors (28 such pairs in 14 days), so it is not new behaviour, only a new door. The proper fix is the
shared corroboration in W2, not a W1 change.

**Fan-veto consumer (review B-L3).** The Upstairs Hallway room fused sensor gains a second source. A second source
can make the room read split, and the fan-veto rebuttal is denied in AWAY / VACATION. Inert today: there is no fan in
Upstairs Hallway.

Unchanged, by test: census `get_transit_interior_entities` (the camera-person list already names the Protect cameras;
the merge dedups), transit `_path_map_context` door and exterior keys, every other camera's fusion, picks and legs.

**Perimeter Part A legs do NOT change.** The plan (§5, plan review 1 M1) says W1 changes shipped perimeter Part A input for garage_a.
Measured: it does not. Perimeter takes its legs from `resolve_detection_legs`, which on develop already reaches
garage_a's Protect leg through its own `_N`-stripped stem bridge (`camera_resolver.py` `resolve_detection_legs`,
`candidate_stems` loop). The leg sets of every live perimeter camera and of `camera.garage_a_2` are identical with the
knob on and off (`test_perimeter_resolve_legs_unchanged`). So W1 does not change perimeter `families_live` or
AgreementTracker samples on this house. (That stem bridge is itself a name guess; it belongs to REGISTRY-NOT-NAMES-1.)

### Tests

`quality/tests/test_nvr_witness_w1_resolver.py` (21), helper `quality/tests/_nvr_w1_registry.py`, fixtures
`quality/tests/fixtures/nvr_w1_live_registry_shape.json` (live registry extract) and
`nvr_w1_resolver_golden_develop.json` (develop 4b825c50 resolver output over that fixture). Every condition, the
knob, the call site, the slug function, the `name_by_user` precedence and the camera-device gate are mutation-anchored.
Fix-up: the once-per-pairing INFO log (B-L1) and slugify-import fail-closed (C-1) each have a RED-on-mutation test.

### Live validation (prospective)

- **Live:** within a day, a `person_entry_exit_events` row with `egress_camera = binary_sensor.garage_a_person_detected`,
  or a garage_a crossing with `confidence = 0.9` (Frigate and Protect both fired). Before W1 garage_a scored 0.9 on
  0 of 71 crossings in 14 days. A subscription fault would pass the resolver tests and show no such row, so this
  discriminates.
- **Live:** `binary_sensor.upstairs_hallway_camera_person_detected` (room fused sensor) lists two sources, one with
  `correlation_basis: frigate_object_name`.
- **Live:** no other camera's pairing changes beyond the table above: the fused sensor attributes of Living Room,
  Game Room and Study A list the same sources as before.
- **Live:** one INFO line `Frigate object-name pairing accepted` per accepted pairing after restart (seven expected).
- **Live:** no WARNING / ERROR from `camera_resolver` or `camera_census` cutover after restart.

