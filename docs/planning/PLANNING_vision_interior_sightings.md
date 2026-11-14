# PLANNING: interior vision sightings (who is where inside, unnamed; where a group went after the door)

Card: VISION-INTERIOR-SIGHTINGS-1 (parent VISION-CROSSING-ANALYSIS-1, batch person-sightings, arc step 9). Tier 3 overall
(D4 touches the census function); per-deliverable tiers in §9. One clean document; nothing here edits another plan (§12).
Linked plans: `PLANNING_crossing_vision.md` (producer of the crossing count; its B-stage camera chains move HERE, its fast
stage P2-D8 is built there), `PLANNING_census_deconfliction.md` (owner of `deconflict_house`, the promotion ladder §3.2),
`PLANNING_person_awareness_read_api.md`, `PLANNING_camera_input_stream_health.md`, `PLANNING_nvr_witness_layer.md`,
`PLANNING_person_sighting_layer.md` (§2A F1-F5, §15.8 head count, D7 path map).

Read completely before writing: charter `ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`, `.claude/skills/ura-arc/SKILL.md`,
`ARC_identity_vision_census_map.md`, `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`, the five linked plans
(sighting plan: §2A, §15.7-§15.9, D7 header), manual §4.5a and §5.5, audits `AUDIT_crossing_vision_p2_d0_2026_11_14.md`,
`AUDIT_vision_d0_frame_sim_2026_11_13.md`, `AUDIT_crossing_vision_d0_2026_11_13.md`,
`AUDIT_ble_person_sensor_resolution_2026_11_14.md`, `AUDIT_registry_not_names_sweep_2026_11_13.md`. HVAC is not touched
(no HVAC reader at any rung in this plan), so the HVAC state of play was not required.

## 1. Charter and why this plan exists

Operator, verbatim. Charter: "Vision is to assist census accuracy. And assist arrivals accuracy and personalization.
Especially when combined with facial recognition from the nvr systems. Frankly our job is to make it faster and faster
until it can eventually be used in security applications too." On this card: "We need this. Sequence is optional as long as
you don't drop it."; "we already know the rooms everyone we know is in via dense ble... Vision confirms known person tracks
and locations and guest locations and egress, ingress. It's complementary... Ble is literal, Vision adds depth. Eventually we
should be able to see and decode emotion."; 2026-11-14: "[Path time-lapse] with interior vision but link the plans... I Want
this tight and not deferred. Make sure its useful. Plans arent just because I said so but because they add value to our
ultimate goal." Hard constraint: "I need away to be fast acting."

Goals referenced below: **G1** census accuracy (guests are the hard part), **G2** arrivals accuracy, **G3** personalization,
**G4** faster, toward security. Every deliverable names its goal and its margin over what BLE + NVR counts already give (§4).

## 2. The product, precisely

Interior cameras sit only in shared spaces. Live `camera_person_entities` (URA entry, read 2026-11-14) resolves to 7 physical
cameras: playroom, master_hallway, staircase, foyer_fisheye, family_room, upstairs_hall, stairs_top (each Frigate + Protect);
the garage hallway Protect camera is in `door_interior_neighbours` only. No bedroom or bathroom has a camera. So "per room"
means these 7 shared spaces; BLE remains the only source for the other ~40 rooms.

1. **Room record (F4-shaped, unnamed).** Per covered room, per census tick: `bodies` (NVR count, physical-camera key),
   `named` (residents BLE places there, plus fresh named faces on that camera; one union, by canonical slug), `unnamed =
   max(0, bodies - |named|)`, `status` in {`confirmed` (bodies == named, at least one), `unnamed_present` (bodies > named:
   a guest or a phoneless resident is HERE), `ble_unconfirmed` (named > bodies: BLE says someone is here, no camera body),
   `empty`, `missing` (camera dead or unhealthy)}, `provenance` (`nvr` / `vision` / `agree`), `as_of`. Display text:
   "2 people in the family room, 1 unnamed". This is the "confirm known-person tracks and locations" and "guest locations"
   product. It names no one new: names come only from the BLE / face union.
2. **Vision adjudication.** When a room record disagrees (BLE vs camera) for long enough, one image call on that camera
   counts the people. The answer is a vision count for that camera, not a name.
3. **Path time-lapse after a door crossing** (moved from crossing vision): for an entry with 2+ people or an unnamed
   person, follow the interior path map's inward edges from the door: "3 came in at garage A; 2 went up the stairs, 1 to the
   family room". It seeds the room records with where the unnamed people went.
4. **Census term.** The interior vision count per camera enters `deconflict_house` as body evidence keyed by physical camera
   (rule 2: max with the NVR count of the same camera, never a sum), awareness view only, by the ladder.

Out: emotion / affect (§10, parked with a trigger, a stated future direction); naming anyone from vision; periodic head
counts (§4, parked); any trust reader.

## 3. F1-F5 and consumer classes

| Fact | Role |
|---|---|
| F1 | consumed: resident locations from `PersonCoordinator` (via the census `_ble_home_by_area`, ACTIVE trackers only) |
| F2 | input only, through `deconflict_house` (D4); the census stays the one writer |
| F3 | consumed: `ura_person_egress_event` + crossing-vision `people_count` / `camera_peak_count` (trigger and `n` for D3) |
| F4 | PRODUCED, unnamed shape (`RoomSighting`, D1; vision and path records, D2/D3). Named F4 sightings are read, not re-made |
| F5 | none. No arrival is derived from an interior record |

| Output | Readers | Class |
|---|---|---|
| Room records, path records | read API getter, the interior awareness sensor, PERSON-PROFILE-PREFERENCES-1 | display (suggestion = display) |
| Interior vision term | `deconflict_house` only | F2 input, awareness view (ladder rung 1 display at ship) |
| Trip-wires | NM via AnomalyDetector / stuck-signal | operator |

No reader in house_state, security, access, comfort (HVAC) or presence inference. Promotion follows census plan §3.2.

## 4. Marginal benefit, per piece (pushback applied before the spec)

What exists today (code wins): the census ALREADY reconciles NVR bodies with BLE per area every tick
(`camera_census.py:5950` `_get_unrecognized_camera_count`, steps at `:6082-6134`: `_last_area_raw_max_pre_cancel`,
`_last_ble_by_area`, `_last_enhanced_area_contributions`) and publishes all three as RECORDED attributes `area_raw_max_pre_cancel`,
`ble_by_area`, `area_contributions` on `sensor.universal_room_automation_persons_in_house` (`sensor.py:3856-3876`; not in the
`_unrecorded_attributes` set at `:3770`). Named interior faces already become F4 sightings (`person_sighting.py:530`).

| Piece | Goal | What it adds over BLE + NVR today | Verdict |
|---|---|---|---|
| D0 probe | all | Measures whether NVR and BLE already agree; without it D2's value is a guess | BUILD first |
| D1 room records, no model | G1, G3, G4 | The reconciliation exists but is a dict keyed by area_id on one sensor, guest-blind direction only; D1 makes it a read-API value per room, adds `ble_unconfirmed` (BLE bleed check) and `missing`, and gives personalization "who is in the family room". Zero model cost, tick-fast | BUILD (largest share of the value, simplest version) |
| D2 vision adjudication | G1, G4 | Only where NVR and BLE disagree: ghost bodies (playroom phantom class), merged groups, a still guest the detector dropped. Value scales with the D0 disagreement rate | BUILD if D0 gate passes, else PARK with trigger |
| Periodic head count every 1800 s (sighting plan §15.8) | G1 | Calls when nothing is in dispute; D2 captures the disputed cases at a fraction of the calls | PARK. Revival: crossing-ledger bar a (drift) fails, needing an independent interior empty check |
| D3 path, no-model leg | G1, G2, G3 | Where a single entrant went: Frigate events on the path map's inward edges already show it; nothing joins them today | BUILD |
| D3 path, vision leg | G1, G2 | Group splits only (2+ entering; NVR counts merge groups). Volume about 30 % of crossings (57 of 189 rows have peak 2+, audit V1), about 4 a day | BUILD if D0 gate passes |
| D4 census term | G1 | Lets interior vision correct the guest count where it beats NVR; required for "per-room count term" but inert until its bar (§3.2 of census plan) | BUILD dark with D2 |
| Emotion | G3 | none measurable now | PARK (§10) |

## 5. Institutional context verified (REUSE / NEW at file:line, develop 6d8fe70d; live v5.108.21)

| Piece | Verdict | Where |
|---|---|---|
| Per-area NVR bodies, BLE residents, unexplained bodies | REUSE (expose a public getter; no second derivation) | `camera_census.py:5950`, `:6082-6083`, `:6134`; inits `:1406-1413` |
| BLE residents by area (ACTIVE only, STALE / LOST excluded) | REUSE | `camera_census.py:3066` `_ble_home_by_area` |
| Interior camera list | REUSE `CONF_CAMERA_PERSON_ENTITIES` (`const.py:2424`) via `_get_interior_camera_entities` | `camera_census.py:2602` |
| Census result shape | REUSE `CensusZoneResult` unchanged | `camera_census.py:310` |
| Named sighting producer, `PersonSighting` | REUSE (read only; unnamed records are a sibling type, not a new emit on `SIGNAL_PERSON_SIGHTING`) | `person_sighting.py:64`, `:565` |
| Physical camera key | REUSE `canonical_camera_key` | `camera_resolver.py:507` |
| Pick / fusion resolution, face entities per device | REUSE `resolve_pick_to_fusions`, `face_name_entities_for_device` | `camera_resolver.py:916`, `:760` |
| Interior path map (live, valid file, doors garage_a / front with `lag_p90_s`) | REUSE loader + `score_path` event shape; NEW public getter `path_map()` on `EgressDirectionTracker` | `interior_paths.py:39-60`, `:200`; loader `transit_validator.py:2363`, `:2493`, status `:2566`; file `/config/universal_room_automation/interior_paths.json` |
| Crossing-vision call contract, Frigate ring, record writer, gates, cap counter | REUSE `CrossingVisionShadow` patterns (`_on_frigate_event` `:456`, `_record` `:795`, `_spawn` `:374`, teardown `:343`) and `register_frigate_consumer` (`frigate_ingress.py:582`) | `crossing_vision.py` |
| Image call on 1-3 frames | REUSE the image helper P2-D8 adds for the fast stage (`perimeter_enrichment.py`, beside `analyze_crossing_frames` `:360`); if P2-D8 is not merged, D2 waits for it (no second helper) | |
| Provider / model | REUSE `CROSSING_VISION_PROVIDER_ID`, `CROSSING_VISION_MODEL` | `const.py:3554`, `:3549` |
| Stream death = missing | REUSE `camera_input_stream_dead` (room tier, live) and the S2 camera-keyed form when it lands | `coordinator.py:2689` |
| NVR family agreement per camera | REUSE `nvr_witness` `families_live` / `agreement` when W2 lands; until then the census platform split | `PLANNING_nvr_witness_layer.md` §7 |
| Read surface | EXTEND: NEW `get_room_sightings()` and `get_last_path_record()` beside `get_last_person_sighting` (`presence.py:5933`), `get_house_census` (`:5952`), `view_for_class` (`:5984`) | |
| Consumer classes | REUSE `CONSUMER_CLASS_MIN_CONFIDENCE`, `CROSSING_VISION_CONSUMER_CLASSES` | `const.py:6528` |
| Reserved name `CROSSING_VISION_INTERIOR_ENABLED` | REUSED intent, renamed to the `INTERIOR_VISION_*` family (crossing vision §6 row gets a pointer, §12) | |
| `RoomSighting`, `PathRecord`, `interior_vision.py`, `sensor.ura_interior_awareness`, `INTERIOR_VISION_*` knobs | NEW: grep of `const.py`, `config_flow.py`, entity platforms, `domain_coordinators/`, `docs/planning/` for `RoomSighting`, `room_sighting`, `INTERIOR_VISION`, `interior_awareness`, `PathRecord`: 0 hits | |

## 6. Invariants (falsifiable; reviewer D breaks these)

- **INV-IV-AWAY.** For any room record, vision result, path record, switch or cap value, the AWAY entry time and the number
  and timing of `_run_inference` calls equal develop. Choke points: the census plan's five (§4 there) plus any read of
  `get_room_sightings` / `get_last_path_record` from `presence.py` outside the getters. Test: the census plan's
  `test_away_tick_identical_with_vision_payload` harness, extended with room records showing 3 unnamed and a vision term 5.
- **INV-IV-NO-TRUST.** No module in presence inference, `security*.py`, `security_lock_regime.py`, `perimeter_alert.py`,
  `hvac*.py`, `fan_veto.py`, `arrival_edges.py` reads a room record, path record or interior vision term. Break it by a grep
  hit or by a config under which `view_for_class("security")` yields an interior value.
- **INV-IV-NO-NAME.** `named` comes only from the BLE / face union; no vision or path output sets a slug, `person_id` or
  `identity_provenance`. Break it with a vision `desc` containing a resident's name reaching `named`.
- **INV-IV-DEDUP.** A body seen by a camera's Frigate leg, its Protect leg and a vision call counts once (max per
  `canonical_camera_key`); a resident placed by BLE and recognised by face in the same room counts once; overlapping cameras
  (only {family_room, master_hallway} measured) combine by max. Break it: one body on all three sources → `bodies` 1.
- **INV-IV-MISSING.** A camera whose stream is dead or whose vision call failed is `missing` (case D), never 0 bodies.
- **INV-IV-OFF.** Vision switch off, `LLMVISION_ENRICHMENT_KILL` True or cap 0: zero `llmvision.*` calls and zero Frigate
  media requests from this module. D1 has its own kill (`INTERIOR_ROOM_RECORDS_ENABLED`) and calls no model.
- **INV-IV-SCOPE.** Frames come only from cameras in the resolved interior list or on an inward edge of the crossing's door
  in the path map; never an exterior or unconfigured camera.

## 7. Producer and consumer checks (fire check included)

Producer: `bodies` = the census per-area max post-face (`:6082`), so it inherits face subtraction and the area grouping;
dependency health is measured by D0(b) (are the attributes populated, and how often). `named` from `_ble_home_by_area`:
ACTIVE trackers only (a STALE resident does not confirm a room, deliberate concept split, presence doc gold patterns).
Person BLE confidence is dead at 0.3 / 0.5 for everyone (BLE audit §2) but nothing here reads it: rooms come from
`location`, which works for all four residents (audit §1). Consumers: §3 table only. Forward trace: room records → awareness
sensor, personalization suggestions, D2 trigger, D4 term (awareness). Fire check: D0(b) counts how often each status
occurs per room over 7 days; each new producer ships a zero-fire trip-wire (D5).

## 8. Deliverables

### D0: measure-first probe (read-only; go/no-go per deliverable; ≤ 6 paid calls only with operator OK)
(a) Interior coverage: physical cameras (canonical key), NVR families, HA area, URA room, path-map membership; rooms covered
of 47. (b) From the recorder (7 days) `area_raw_max_pre_cancel` vs `ble_by_area` per area: share of samples equal, camera >
BLE, camera < BLE; duration distribution of disagreement stretches (60 / 120 / 300 s); split resident-only time (no guest
latch, `visitors_present` off) vs guest days. In resident-only time camera > BLE is the false-guest / phoneless proxy.
(c) Frigate vs Protect agreement on the 7 interior cameras (NVR W0 table if run, else recorder edges). (d) Path map: doors,
edges, `lag_p90_s`; group entries per day (crossing rows with peak 2+) and their first inward hop coverage (audit V5: 55-67 %
of entries reach a chain camera). (e) Projected calls a day for D2 at each persistence value and D3. (f) Cost and latency:
reuse D0-V image path (p50 2.07 s, p90 2.70 s, gpt-4o-mini about $0.0095 per 3-frame call; Luna estimate about $0.0003
input); with OK, up to 6 calls on 3 interior cameras to prove the frame source (Frigate `latest.jpg` / snapshot via the HA
proxy) returns usable frames. (g) Operator labels 30 interior frames (people count) drawn from disagreement moments.
- **Gates:** D1 GO unless (b) finds the attributes empty (then the census producer is the finding). D2 GO if disagreement
  stretches ≥ the persistence value occur ≥ 1 a day AND (resident-only camera > BLE ≥ 2 % of area-time OR (g) shows the
  NVR count wrong on ≥ 3 of 30); PARK with trigger if NVR and BLE agree on ≥ 98 % of resident-only area-time and guest
  days show camera > BLE where guests were. D3 vision leg GO if group entries ≥ 1 a day and inward hop coverage ≥ 50 %.
- **Verify:** `docs/planning/AUDIT_vision_interior_d0_<date>.md`, one table per item with numbers. **Live:** none.

### D1: room records, no model (Tier 2-DB: census-adjacent, regression-prone)
NEW `RoomSighting` (frozen) in `interior_vision.py` (HA-free core: `build_room_records(area_bodies, ble_by_area,
named_faces, health, area_to_room, now)`). Census exposes ONE public getter `PersonCensus.area_evidence()` returning the
three dicts it already computes (copies, read after the tick; no arithmetic change). Presence calls the core on each census
update and stores the records in RAM; `get_room_sightings()` returns them. `named_faces` = fresh named interior sightings
from `get_last_person_sighting(s)` within `INTERIOR_ROOM_FACE_FRESH_S`. Health: `camera_input_stream_dead` → `missing`.
Surface: `sensor.ura_interior_awareness` (Census device), state = total `unnamed` across covered rooms, attributes per room
(unrecorded; the census attributes already record the raw inputs, so no new recorder or DB load).
- **Verify (discriminating):** family_room bodies 2, BLE {ezinne}: `unnamed_present`, unnamed 1. Same bodies with BLE
  {ezinne, jaya}: `confirmed`. Bodies 0, BLE {jaya}: `ble_unconfirmed` (a census-only reading would show 0 guests in all
  three, so these separate). Dead stream: `missing`, not `empty`.
- **Tests:** `test_room_records_statuses`, `test_dead_stream_is_missing_not_empty`, `test_named_union_dedups_ble_and_face`,
  `test_stale_resident_does_not_confirm`, `test_census_fields_golden_unchanged` (every existing census field and payload key
  equal to develop with D1 on), `test_no_trust_reader_of_room_records` (grep, INV-IV-NO-TRUST), `test_kill_switch_no_records`.
  Mutation: compute `bodies` from `_last_area_contributions` (post-cancel) instead of pre-cancel → statuses test red.
- **Live:** within an hour, `sensor.ura_interior_awareness` lists the 7 covered rooms; for a room where a resident is BLE-placed
  and on camera, status `confirmed`; census sensors unchanged.

### D2: vision adjudication (Tier 2-DB; after D1 live, D0 gate, and P2-D8's image helper)
`InteriorVision` in `interior_vision.py`, built beside `CrossingVisionShadow`, `hass.data[DOMAIN]["interior_vision"]`, same
teardown shape. Trigger: a room record in `unnamed_present` or `ble_unconfirmed` continuously for
`INTERIOR_VISION_DISAGREE_PERSIST_S`, per-camera cooldown `INTERIOR_VISION_CAMERA_COOLDOWN_S`. Call: 1-3 frames from that
camera (Frigate snapshot / latest frame through the HA proxy; Protect thumbnail when no Frigate leg), the shared provider,
prompt forbids naming, schema `{people, desc}`. Gates re-read at call time (switch, kill, cap, concurrency). Outcome rows:
one `log_memory_episode(episode_type="interior_vision", node_id=f"ivision:{camera_key}:{ts}", source_ref=camera_key,
dedup_source_ref=False)`, attrs: room, bodies, named count, vision people, status before, outcome, latency, model,
`pipeline_version`. The type joins `MEMORY_WRITER_BACKED_EPISODE_TYPES`. The vision count updates that room's record
(`provenance = vision` / `agree`) until the next NVR change.
- **Verify (discriminating):** a ghost (bodies 1, BLE 0, vision 0) → record `empty`, provenance `vision`, and the census trust
  count unchanged; a merged group (bodies 1, vision 3) → unnamed 3 on the record only.
- **Tests:** `test_trigger_needs_persistence`, `test_cooldown_per_camera`, `test_switch_off_no_call`, `test_cap_skip_counted`,
  `test_blank_frames_not_zero` (all frames empty → `blank`, record unchanged), `test_no_name_reaches_named`,
  `test_teardown_cancels`, `test_scope_interior_cameras_only`. Mutation: drop the call-time switch re-read; drop persistence.
- **Live:** ≥ 1 `interior_vision` row with non-null `people` within a day of the switch on; calls ≤ cap.

### D3: path time-lapse after a crossing (Tier 2-DB; no-model leg after D1, vision leg with D2)
Trigger: `ura_person_egress_event` entry on a door with a path map. No-model leg: for `E` + the edge's `lag_p90_s` (fallback
`INTERIOR_PATH_DEFAULT_WINDOW_S`), record which inward-edge cameras saw a person event (Frigate ring, REUSED); output a
`PathRecord` (crossing_key, door, n entered, hops: camera, room, first seen, count). Vision leg: when n ≥
`INTERIOR_PATH_VISION_MIN_N` or the arrival record has `guests_unnamed ≥ 1`, one call per hop camera (cap 3 per crossing)
counting people at the hop. Path hops update the hop room's record for `INTERIOR_PATH_SEED_TTL_S` (where the unnamed went).
Rows: `interior_path` episodes, same writer rules as D2. Chain coverage ceiling 55-67 % of entries is stated, not tuned.
- **Verify:** a 3-person garage A entry with staircase then stairs_top events → path record with both hops; a 1-person entry
  makes no call. An entry on a door with no map → no record (not an empty one).
- **Tests:** `test_path_window_from_map_lag`, `test_single_entrant_no_call`, `test_group_entry_calls_hops_capped`,
  `test_no_map_no_record`, `test_path_seeds_room_record_ttl`. Mutation: ignore the map edge kind (count approach edges).
- **Live:** ≥ 1 `interior_path` row after a multi-person entry; `get_last_path_record()` returns it.

### D4: interior vision term in `deconflict_house` (Tier 3; after census CD1 and D2)
Term per camera: `vision_people` from D2 / D3 within `INTERIOR_VISION_TERM_MAX_AGE_S`, keyed by `canonical_camera_key`;
combined with the NVR body count of the same camera by max (rule 2), residents subtracted once through R (rule 4), guest
side by max with the ledger and camera terms (rule 3), stale / failed = missing (rule 5). Moves only the awareness view and
only while `INTERIOR_VISION_TERM_LEADS` is True (default False, so `aware_guests` is unchanged at ship). Its bar (before the
const flip, operator Tier-3 checkpoint): ≥ 60 graded interior calls over ≥ 7 days, exact count ≥ 90 %, false guest in
resident-only time ≤ 2 %, vision wins ≥ 80 % of its disagreements with NVR on graded cases.
- **Tests:** `test_interior_term_max_with_nvr_same_camera`, `test_interior_term_missing_when_stale`,
  `test_awareness_unchanged_until_leads`, `test_trust_view_byte_identical_interior_on` (census plan golden harness),
  INV-IV-AWAY test above. Mutation: sum NVR and vision on one camera → max test red; let the term reach `unidentified_count`
  → trust golden red.
- **Live:** awareness fields equal trust while LEADS is False; scorer shows interior bar numbers.

### D5: diagnostics, metrics, trip-wires (with each producer)
`interior_room_records_zero` (HIGH: census interior bodies > 0 on ≥ `INTERIOR_ZERO_MIN_TICKS` ticks in 24 h and 0 records);
`interior_vision_errors` (MEDIUM, error rate > `INTERIOR_VISION_ERROR_RATE_MAX`); attributes `calls_today`, `latency_p90_s`,
`disagreements_today`, `resolved_by_vision_today`. Grading reuses crossing vision P2-D10's Companion grading branch (one
`GRADE_URA_` handler, a second key prefix), feeding D4's bar. Weekly scorer extension in the crossing-vision scorer script.
- **Tests:** `test_zero_fire_pages_once`, `test_error_rate_pages`, `test_grade_action_writes_interior_episode`.

## 9. Knobs

| Knob | Default | Rung | Why / kill |
|---|---|---|---|
| `INTERIOR_ROOM_RECORDS_ENABLED` | True | 1 | D1 master; False = no records, no sensor value |
| `switch.ura_interior_vision` (label "Interior vision (shadow)"), config-flow entry | off at ship | 3 | D2 / D3 vision master; off = INV-IV-OFF |
| `INTERIOR_VISION_DAILY_CALLS` | 30 (D0(e) may change) | 3 (Number) | 0 = no calls; separate from the door cap so doors never starve |
| `INTERIOR_VISION_DISAGREE_PERSIST_S` | 120 (D0(b)) | 1 | Ignores transit blips; 0 = immediate |
| `INTERIOR_VISION_CAMERA_COOLDOWN_S` | 900 | 1 | Bounds calls per stuck disagreement |
| `INTERIOR_VISION_MAX_FRAMES` | 3 | 1 | D0b: ≥ 3 frames needed for a count |
| `INTERIOR_VISION_TERM_MAX_AGE_S` | 600 | 1 | Older vision = missing term |
| `INTERIOR_VISION_TERM_LEADS` | False | 1 | D4 value flip; reviewed const edit only |
| `INTERIOR_ROOM_FACE_FRESH_S` | 300 | 1 | Named-face freshness for `named` |
| `INTERIOR_PATH_DEFAULT_WINDOW_S` | 90 | 1 | Used only for an edge with no `lag_p90_s` (audit 15.9.4: 94 % of first hops at 90 s) |
| `INTERIOR_PATH_VISION_MIN_N` | 2 | 1 | Group threshold; 99 = vision leg off |
| `INTERIOR_PATH_SEED_TTL_S` | 600 | 1 | How long a path hop seeds a room record |
| `INTERIOR_ZERO_MIN_TICKS` / `INTERIOR_VISION_ERROR_RATE_MAX` | 20 / 0.25 | 1 | Trip-wires; 0 / > 1 = off |
| `INTERIOR_VISION_KEEP_FRAMES` | False | 1 | Interior frames not kept locally unless the operator says so (§11 Q1) |

## 10. Non-goals and parked

Non-goals: any name from vision; vision direction; any AWAY, house-state, lock, alarm, perimeter, HVAC or fan reader;
cameras in private rooms; rooms without cameras (BLE stays the source); exterior property counts; a second emit on
`SIGNAL_PERSON_SIGHTING`; changing the census trust view; a new DB table (memory episodes only, bounded by the cap).
Parked (each needs a card with this trigger, §12):
- **Emotion / affect** (future direction, stated): revival when D2 exact count ≥ 90 % has held 30 days, a named consumer
  exists (personalization), and the operator rules on privacy for affect inference on household members.
- **Periodic interior head count** (§15.8): revival when crossing-ledger bar a fails twice.
- **Security use of room records** (G4): census ladder rung 5 trigger, plus D2 p90 latency ≤ 15 s.

## 11. Tradeoffs and questions for the operator (rule 3)

1. Interior frames go to the OpenAI provider (shared spaces only, people inside the home). Default: send, never keep frames
   locally (`INTERIOR_VISION_KEEP_FRAMES` False). Alternative: local-only model, not available today.
2. D2 gate: if D0 shows NVR and BLE already agree, D2 parks and the product is D1 + D3 no-model. That changes what is
   delivered (less vision); the orchestrator asks before parking.

## 12. Edits other plans need (not made here)

- `PLANNING_crossing_vision.md` §8: "B-stage chains across cameras and interior head counts" → this plan D3 / §10; §6 row
  `CROSSING_VISION_INTERIOR_ENABLED` → pointer to `INTERIOR_VISION_*` here; P2-D8 section: its image helper is reused by D2.
- `PLANNING_census_deconfliction.md` §3.3 future terms: interior term = this plan D4, with its bar; §3.6: per-room awareness
  is `sensor.ura_interior_awareness` (D1).
- `PLANNING_person_sighting_layer.md` §15.8 head count → parked here; §15.9.4 per-door window knobs → path map `lag_p90_s`.
- `PLANNING_person_awareness_read_api.md`: add `get_room_sightings`, `get_last_path_record` to ship-1 callers list.
- `PLANNING_camera_input_stream_health.md` S2 and `PLANNING_nvr_witness_layer.md` W5b: list D1 / D4 as readers.
- `ARC_identity_vision_census_map.md`: row for this card (status planned → this doc), merge note: path chains merged here.
- `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (code contradicts doc): the header blocks for read-API ship 1, stream health S1,
  person sightings and crossing vision shadow say "NOT deployed", but all four are in tag v5.108.21 (`git grep`), live.
- `IDENTITY_FUSION_CAMERAS_MANUAL.md` §4.5a: unnamed room records are a sibling of named sightings (on D1 ship).
- Board: mint VISION-INTERIOR-AFFECT-PARKED-1 and INTERIOR-HEADCOUNT-PARKED-1 with the §10 triggers; link this card to
  VISION-CROSSING-ANALYSIS-1 P2-D8.

## 13. Revise when we learn

| Measurement (source) | Changes |
|---|---|
| D0(b) agreement ≥ 98 % resident-only | D2 parks (ask operator), D4 waits |
| D0(b) disagreement stretch durations | `INTERIOR_VISION_DISAGREE_PERSIST_S`, cap |
| P2-D8 shadow: F count on real snapshots vs B | D2 frame source (snapshot vs latest frame vs thumbnail) |
| Crossing-vision group sample (P2-D7) undercount | D3 vision leg threshold; whether door `n` can seed D3 |
| D2 rows: blank rate on interior frames | `INTERIOR_VISION_MAX_FRAMES`, frame source |
| NVR W2 interior agreement | `bodies` provenance; whether a Protect-only camera may trigger D2 |
| Crossing ledger bar a | revives periodic head count |
| D5 latency p90 | G4 progress; security rung trigger |

## 14. Tier, reviews, sequence

Plan: Tier 3, two plan reviews (completeness; adversarial build-prediction) plus framing G (goal fidelity). Builds: D1, D2,
D3 Tier 2-DB (three framings: correctness, async / lifecycle / write path, test authority by per-site mutation) plus
framing G; D4 Tier 3 (four code reviews A / B / C mutation / D completeness on INV-IV-AWAY and INV-IV-DEDUP including
pre-existing census readers, orchestrator re-grep and mutation, operator checkpoint). Sequence: D0 now; D1 next (no
dependency beyond live code); D3 no-model leg with D1; D2 and D3 vision leg after the D0 gate and P2-D8 merge; D4 after
census CD1. Each ship updates the presence state of play in the same commit.

## 15. Plan completion tracking

Filled at each ship: delivered, deferred (reason, card), and a supersession check of the census per-area attributes once
D1 reads them through `area_evidence()` (KEEP + DOCUMENT expected).
