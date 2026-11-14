# v5.108.21: identity arc batch 1

PATCH. Five reviewed branches merged on `release/batch-1` (identity / vision / census arc steps 1, 2, 3, 5 and the W1 pairing fix).

## Pre-merge gate (2026-11-14)
- Full name-diff vs develop c5cd29c0 with `URA_SOURCE_MUTATION=1`: 0 NEW, 0 GONE (one pre-existing failure on both sides: `test_ble_extend_not_create.py::test_MUTATION_m2_seeding_hoisted_above_predicate_makes_order_test_red`).
- D7 hygiene: 84 passed, 3 structural skips.
- Isolated pass NARROWED to the 13 test files the batch added or modified (the full 334-file importer list would take hours): 0 NEW. First gate run found 3 NEW names, fixed test-only in d69200a0 (a re-anchored mutation test; two tests made hermetic against a develop-side module-stub polluter, test_fan_incident_2026_08_01_replay.py).
- Reviews: each branch had three framing-disjoint reviews (A/B/C) plus fix-ups and re-verifies; review docs under docs/reviews/code-review/.

## Live validation

### Validated 2026-11-14

Restart 12:47 CST (18:47 UTC), house state `guest` at boot. `switch.ura_crossing_vision_shadow` on at 12:48 CST. Read live 12:49 to about 13:07 CST. Signals: HA entity states and attributes, the URA DB (`memory_episodes`, `person_entry_exit_events`, `ura_activity_log`, `census_snapshots`), the recorder `states` table, and the HA system log (all since the 18:47 UTC boot). The `universal_room_automation` logger is at WARNING (`ha_get_logs source=logger`), so INFO lines are not readable live.

| Criterion | Result | Evidence |
|---|---|---|
| **Phone-left-behind L1**: Jaya flag attributes after a family-room face | PENDING | `binary_sensor.universal_room_automation_jaya_phone_left_behind` has `camera_leg: display_only`, `last_camera_sighting_at` null. House-state sensor `sensor.ura_presence_coordinator_presence_house_state`: `face_sightings_today=0`, `face_sighting_last=None` since restart. Proven by a recognised Jaya face on a sighting camera. |
| **L2**: verdict ignores sightings | PENDING | All four flags `off` (ezinne, jaya, oji_udezue, ziri). No sighting since restart, so no `on` row can be checked against a recent sighting. In-suite: `test_fresh_sighting_does_not_change_verdict`. |
| **L3**: no recorder churn from the camera-leg flags | PASS for the four camera flags; churn from other attributes noted | Recorder `states` rows 18:48 to 18:58 UTC. `last_camera_sighting_at`, `last_sighting_source/_camera/_room/_census_veto` stayed null on every row. Row counts: ezinne 13, jaya 8, oji_udezue 4, ziri 4. The extra rows follow `ble_location` and `room_corroboration_*` changing as BLE rooms flap (for example ezinne Breakfast Nook to Patio to Foyer, every 30 to 60 s). Those attributes were already recorded, not added here. Separate triage item, not this cycle. |
| **L4**: transit path validation unchanged | NOT EVALUABLE as written; no regression seen | `ura_activity_log` `path_method` on 2026-11-13 (94 rows) and 2026-11-14 (202 rows): 100% `path_implausible` both days. `path_confirmed` appears on 0 rows on every day from 2026-11-01 to 2026-11-14, so the criterion's key does not exist in this log. The all-`path_implausible` mix is a separate observation (see below). |
| **L5**: no URA ERROR at boot or on poll | PASS | `ha_get_logs source=system level=ERROR`: 13 entries since boot, 0 from URA. 3 tracebacks, all non-URA (assist_satellite setup, esphome manager, elkm1_lib decode). Boot-only WARNINGs dismissed: `Setup of sensor platform universal_room_automation is taking over 10 seconds` (18:47 UTC). |
| **Crossing vision: first shadow row within 4 daytime hours** (`outcome = ok`, `people_count`, `camera_peak_count` non-null) | PENDING | `memory_episodes` `episode_type='crossing_vision_shadow'`: 0 rows. Switch on 12:48 CST; 0 egress rows since restart (newest `person_entry_exit_events` id 9045, 17:39 UTC, pre-restart). Proven by the first door crossing after 12:48 CST. |
| **Crossing vision: `source_ref` matches `egress_identity_outcome`** | PENDING | No shadow rows yet. |
| **Crossing vision: `crossing_vision_today.calls` at most today's crossings** | PENDING | No crossing since switch-on. Daily cap `number.ura_notification_manager_crossing_vision_daily_calls` = 40.0 (config present). Diagnostic not read (Outside: Open Tracks, not recorded). |
| **Crossing vision: one new `person_entry_exit_events` row has the same `peak_person_count` as `camera_peak_count`** | PENDING | Rows since restart: none. Note: `peak_person_count` is already populated (value 2) on rows 9040 to 9045 written before the 18:47 UTC restart, so a populated column is not evidence for this build. |
| **Crossing vision: no `crossing_vision` ERROR, no trip-wire page** | PASS so far | No crossing_vision log line (system or error_log) since boot. No `crossing_vision_zero` / `crossing_vision_errors` page. Re-check after the first daytime crossings. |
| **Read API: no entity or attribute change after restart** | PASS (no new WARN/ERROR); entity values not diffed against a pre-restart read | `sensor.universal_room_automation_identified_persons_in_house` = 2, attributes `person_list` ["ezinne","jaya"]. Boot-only WARNING `Census: all camera platforms unavailable` (2 occurrences, 18:48:09 to 18:48:21 UTC), not recurred. No URA WARN/ERROR from `transit_validator`, `perimeter_alert` or `person_ids` in the system log. |
| **Read API: census identified slugs keep the `oji_udezue` form** | PASS on format; presence delta noted | Pre-restart `census_snapshots` row 842166 (18:46:21 UTC) lists ["ezinne","jaya","oji_udezue"]. Post-restart sensor lists ["ezinne","jaya"] only. Oji's absence is a presence/BLE difference at boot, not a format change. Recheck when BLE settles. |
| **Read API: next garage crossing NM text unchanged** ("<Name> arrived" at >= 0.75, else "Someone") | PENDING | Needs a garage crossing. |
| **Read API: `get_house_census` / `view_for_class` / `get_last_crossing` / `get_last_arrival_record` callers** | PASS | `grep -rn` over `custom_components/` returns definitions and docstrings only: `presence.py:5952, 5984, 6009, 6021`, `transit_validator.py:1044` (plus comment lines). No caller. |
| **S1: Study A and Kitchen `camera_stream_inputs_resolved = 1`, `camera_stream_dead_inputs` empty** | PASS | `sensor.studya_room_device_unavailable_entities`: resolved 1, dead {}. `sensor.kitchen_unavailable_entities`: resolved 1, dead {}, 0 unavailable sensors (12:50 CST). |
| **S1: Upstairs Hallway `camera_stream_inputs_resolved = 1`** | CANNOT READ (operator action) | The Upstairs Hallway unavailable-entities sensor is not in the state machine (disabled by integration, as the README notes). Not enabled, because this validation does not change HA state. Operator: enable the sensor, then read `camera_stream_inputs_resolved` and `camera_stream_dead_inputs`. |
| **S1: no `camera-derived input(s) ... no single camera entity` WARNING for the three rooms** | PASS | No such WARNING in the system log since boot. |
| **S1 organic: a panel outage lists the panel input in `camera_stream_dead_inputs` within about 2.5 min; the room drops occupied** | PENDING | Kitchen panel person input `binary_sensor.kitchen_panel_person_occupancy` was unavailable 18:48:21 to 18:49:04 UTC (43 s, under the 120 s grace). No exclusion and no listing, which is correct, but not a discriminating test. Proven by a panel outage over 120 s. |
| **S1 organic: a 30-min outage pages one HIGH `Camera stream dead: <room>`, then one LOW on recovery** | PENDING | Needs a 30-min camera outage. |
| **W1: a garage_a crossing with `confidence = 0.9` (Frigate and Protect both fired) within a day** | PENDING | No egress since restart. Pre-W1 baseline: 0 of 71 garage_a crossings at 0.9 in 14 days. |
| **W1: `binary_sensor.upstairs_hallway_camera_person_detected` lists two sources, one `correlation_basis: frigate_object_name`** | PASS | Sources: `unifiprotect` `binary_sensor.upstairs_hall_person_detected` (`correlation_basis: frigate_object_name`, state off); `frigate` `binary_sensor.upstairs_hall_person_occupancy_2` (`same_device`, unavailable). `resolved_physical_cameras: 1`, `agreement: unanimous_off`. |
| **W1: other camera pairings unchanged (Living Room, Game Room, Study A fused sources)** | PENDING (no pre-change baseline) | Only one fused sensor in HA carries a `frigate_object_name` source (Upstairs Hallway, above). The other six table rows are not visible as fused sources. `binary_sensor.garage_a_camera_person_detected` has `sources: []`, `resolved_camera_devices: []` (`room_cameras_empty`). Needs a pre-change snapshot to diff. |
| **W1: one INFO `Frigate object-name pairing accepted` per pairing (seven expected)** | CANNOT VERIFY live | The URA logger is at WARNING, so INFO lines are not emitted. Same for the crossing-vision setup pairing lines. In-suite: `test_nvr_witness_w1_resolver.py`. Enable INFO on the logger to check (an operator action). |
| **W1: no WARNING/ERROR from `camera_resolver` or `camera_census` cutover** | PASS | No `camera_resolver` line in the system log. Only the boot-only `camera_census` WARNING above. |
| **Restart: `sensor.kitchen_unavailable_entities` `unavailable` reading after boot** | Observation | `sensor.kitchen_unavailable_entities` lists `binary_sensor.mmwave_lux_temp_humidity_zigbee_kitchen_presence`, temperature, humidity and illuminance as `entity_missing`. Not caused by this release (no registry change in this cycle). Carded for triage. |

**Dismissed boot-only transients** (all within 18:47 to 18:50 UTC unless noted): `coordinator` "All N sensors unavailable, holding occupancy state for 60s" (26 entries across several rooms, last 18:49:28 UTC; no later occurrence); `HVAC boot-settle: released via TIMEOUT after 60s` (18:48:46 UTC; one occurrence); `camera_census` "all camera platforms unavailable" (18:48:09 to 18:48:21 UTC); `weather_manager` divergence 5.0 F (18:48:16 UTC); `Waiting for integrations to complete setup: idasen_desk` (bootstrap, not URA); `Setup of sensor platform universal_room_automation is taking over 10 seconds` (18:47 UTC).

**Non-boot URA WARNINGs (not in any criterion, carded for triage):**
- `Room Living Room: Sensor binary_sensor.screek_human_sensor_l13_2412s_presence duty-cycle stuck`, NOTIFY-ONLY (not excluded). Logged twice: 18:48:55 and 18:53:13 UTC.
- `Reset-day accrual on import capped: raw=48.218 cap=6.142` (`energy_billing_counters.py:192`, 18:52:44 UTC). A restart-time billing accrual cap, not a presence item.
- `External URL https://madronehaos.phalanxmadrone.com is not reachable (TimeoutError); notification image links will be broken` (18:49:34 UTC). Outside this release.
- `SOC stream tier trust -> trusted` (18:53:04 UTC). Informational, not an error.
- Deprecation WARNINGs from URA code, HA 2027.8 / 2027.9 deadlines: `__init__.py:5212` (`device_registry.devices.values()`), `__init__.py:5290` (`async_get_device`), `_devices.py:627`. Not failures now; carded for HA-deprecation cleanup.

**Log totals since boot:** ERROR 13 (0 URA). URA-logger WARNINGs are the entries listed above; their counts are the system-log `count` fields.

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

### Live validation: Validated 2026-11-14

Results for L1 to L5 are in the consolidated table under `## Live validation` at the top of this file.

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

### Live acceptance: Validated 2026-11-14 (PENDING, see the top table)

Five criteria are PENDING: no crossing has happened since the switch went on at 12:48 CST. The first
daytime door crossing proves them. Results are in the consolidated table under `## Live validation`.


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

### Live validation: Validated 2026-11-14

Results are in the consolidated table under `## Live validation`. Three PASS, one PENDING (garage NM text).

<!-- prospective criteria (superseded by the table above) -->
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

### Acceptance: Validated 2026-11-14

Results are in the consolidated table under `## Live validation`. Study A and Kitchen pass; Upstairs Hallway
cannot be read (its sensor is disabled and this validation does not change HA state); the two organic
outage criteria are PENDING. In-suite only: the byte-identical cases and the grace / NM boundaries are proven in
`quality/tests/test_camera_stream_health.py`.


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

### Live validation: Validated 2026-11-14

Results are in the consolidated table under `## Live validation`. Still PENDING: the garage_a 0.9 row (no egress since restart), the other-camera pairing diff (no pre-change baseline), and the INFO lines (logger at WARNING). The Upstairs Hallway two-source check PASSES.

<!-- prospective criteria (superseded by the table above) -->
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

