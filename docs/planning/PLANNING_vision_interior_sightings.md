# PLANNING: interior vision sightings (correct and supplement interior person counts; describe what is happening)

Card: VISION-INTERIOR-SIGHTINGS-1 (parent VISION-CROSSING-ANALYSIS-1, batch person-sightings, arc step 9). Tier 3 overall
(D4 touches the census function); per-deliverable tiers in §14. One clean document; nothing here edits another plan (§12).
Linked plans: `PLANNING_crossing_vision.md` (door counts; its B-stage camera chains move HERE; its fast stage P2-D8 and its
grading P2-D10 are built there), `PLANNING_census_deconfliction.md` (owner of `deconflict_house` and the promotion ladder
§3.2), `PLANNING_person_awareness_read_api.md`, `PLANNING_camera_input_stream_health.md`, `PLANNING_nvr_witness_layer.md`,
`PLANNING_person_sighting_layer.md` (§2A F1-F5, §15.8 head count, D7 path map).

Read completely before writing: charter `ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`, `.claude/skills/ura-arc/SKILL.md`,
`ARC_identity_vision_census_map.md`, `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`, the linked plans
(sighting plan: §2A, §15.7-§15.9, D7 header), manual §4.5a and §5.5, audits `AUDIT_crossing_vision_p2_d0_2026_11_14.md`,
`AUDIT_vision_d0_frame_sim_2026_11_13.md`, `AUDIT_crossing_vision_d0_2026_11_13.md`,
`AUDIT_ble_person_sensor_resolution_2026_11_14.md`, `AUDIT_registry_not_names_sweep_2026_11_13.md`. HVAC is not touched (no
HVAC reader at any rung), so the HVAC state of play does not apply.

## 1. Charter and operator direction

Charter, verbatim: "Vision is to assist census accuracy. And assist arrivals accuracy and personalization. Especially when
combined with facial recognition from the nvr systems. Frankly our job is to make it faster and faster until it can
eventually be used in security applications too." Hard constraint: "I need away to be fast acting."
On this card: "We need this. Sequence is optional as long as you don't drop it."; "Ble is literal, Vision adds depth.
Eventually we should be able to see and decode emotion."; "[Path time-lapse] with interior vision but link the plans...
I Want this tight and not deferred. Make sure its useful."
2026-11-14 review of the first draft: "camera body counts: The problem is this is error prone when it depends on nvr
integration sensors. This vision should help. Did you measure the error in the camera body counts?"; "Interior vision is
meant to supplement person counts sensors. And allow us to describe what is happening with people when we need it. It
should add depth (emotion is the deepest). Privacy in the main objection."; "Accept privacy now. If the accuracy holds up,
we should move to local"; "parking needs to ask me".

Goals: **G1** census accuracy (guests are the hard part), **G2** arrivals accuracy, **G3** personalization, **G4** faster,
toward security; **G5** depth (describe what is happening; emotion the deepest, later); **G6** move inference local once
accuracy holds (privacy).

## 2. What we know about count error today (honest)

NVR interior body counts have NEVER been measured against ground truth. The only truth on record is at doors: the operator
hand-labelled 30 door frames, and the Frigate person-tracking proxy agreed on 22 of 30 (73 %): 5 misses (one of them a
2-person frame), 3 false positives (card VISION-CROSSING-ANALYSIS-1, HANDLABEL_2026-11-13). Camera-vs-BLE agreement is not
an error measure: BLE knows only residents, so both can agree while both miss a guest. D0 therefore grades interior frames.

## 3. The product

Interior cameras sit only in shared spaces. Live `camera_person_entities` (URA entry, read 2026-11-14) resolves to 7
physical cameras: playroom, master_hallway, staircase, foyer_fisheye, family_room, upstairs_hall, stairs_top (each Frigate +
Protect); the garage hallway Protect camera is in `door_interior_neighbours` only. No bedroom or bathroom has a camera.

1. **Room record (F4-shaped, unnamed).** Per covered room: `bodies` (best count: NVR, or a fresh vision count, per physical
   camera), `named` (BLE residents placed there plus fresh named faces; one union by canonical slug), `unnamed = max(0,
   bodies - |named|)`, `status` in {`confirmed`, `unnamed_present`, `ble_unconfirmed`, `empty`, `missing`}, `provenance`
   (`nvr` / `vision` / `agree`), `as_of`. Display: "2 people in the family room, 1 unnamed".
2. **Vision supplements the count sensors.** A sampling and correction budget over the shared spaces, sized by each
   camera's measured error, not only fired on disagreement.
3. **Describe what is happening, on demand.** Activity and context for a room or a person ("two people at the kitchen
   table, one on the sofa watching TV"), structured, for personalization and when the operator asks.
4. **Path time-lapse after a door crossing** (moved from crossing vision): where a group went inside.
5. **Census term.** Interior vision counts enter `deconflict_house` as body evidence per physical camera, awareness only.
Deepest direction, stated and not built now: emotion (§10). Never: a name from vision; any trust reader.

## 4. F1-F5 and consumer classes

| Fact | Role |
|---|---|
| F1 | consumed: resident rooms from `PersonCoordinator` via the census `_ble_home_by_area` (ACTIVE trackers only) |
| F2 | input only, through `deconflict_house` (D4); the census stays the one writer |
| F3 | consumed: `ura_person_egress_event` + crossing-vision `people_count` / `camera_peak_count` (D5 trigger and `n`) |
| F4 | PRODUCED, unnamed: `RoomSighting` (D1), vision counts (D2), descriptions (D3), path records (D5). Named F4 read, not re-made |
| F5 | none |

| Output | Readers | Class |
|---|---|---|
| Room records, path records, descriptions | read API getters, `sensor.ura_interior_awareness`, PERSON-PROFILE-PREFERENCES-1 | display (suggestion = display) |
| Description on operator request | NM reply to the operator | notification (no naming beyond the F3 / BLE union at ≥ 0.75) |
| Interior vision term | `deconflict_house` only | F2 input, awareness view (rung 1 display at ship) |
| Trip-wires, grading requests | NM | operator |

No reader in house_state, security, access, comfort (HVAC, fans) or presence inference. Promotion only by census plan §3.2.

## 5. Value per deliverable (margin over BLE + NVR today)

Code today: the census already reconciles NVR bodies with BLE per area every tick (`camera_census.py:5950`,
`:6082-6134`) and records the inputs as attributes `area_raw_max_pre_cancel`, `ble_by_area`, `area_contributions` on
`sensor.universal_room_automation_persons_in_house` (`sensor.py:3856-3876`; not in `_unrecorded_attributes` `:3770`). It
trusts the NVR count as truth; nothing checks it.

| Deliverable | Goal | Margin | Gate that may PROPOSE parking (operator decides) |
|---|---|---|---|
| D0 error probe | all | First measurement of interior count error; sizes D2 | none |
| D1 room records | G1, G3 | Per-room who/unnamed/unconfirmed as a read-API value; adds `ble_unconfirmed`, `missing` | none |
| D2 sampling + correction | G1, G4 | Corrects NVR misses, false positives and merged groups where D0 shows them; supplements counts generally | D0-P1 |
| D3 describe on demand | G3, G5 | Depth NVR and BLE cannot give at all | D0-P3 |
| D4 census term | G1 | Lets corrected interior counts move the awareness guest count, inert until its bar | none (flip is an operator checkpoint) |
| D5 path time-lapse | G1, G2, G3 | Where a single entrant (no model) or a group (vision) went | D0-P2 |
| D6 local inference | G6 | Privacy: frames stay in the house | none (switch is an operator checkpoint) |
| D7 diagnostics | all | Zero-fire, error, latency, grading | none |

**No deliverable parks itself.** A gate marked D0-Pn that fails produces an operator question with the numbers and a
recommended answer; the orchestrator asks (charter rule 4). Same for the periodic head count (§10).

## 6. Institutional context verified (REUSE / NEW at file:line, develop 98a2a640; live v5.108.21)

| Piece | Verdict | Where |
|---|---|---|
| Per-area NVR bodies, BLE residents, unexplained bodies | REUSE through ONE new public getter `PersonCensus.area_evidence()` (copies; no arithmetic change) | `camera_census.py:5950`, `:6082-6083`, `:6134`; inits `:1406-1413` |
| BLE residents by area | REUSE `_ble_home_by_area` | `camera_census.py:3066` |
| Interior camera list | REUSE `CONF_CAMERA_PERSON_ENTITIES` (`const.py:2424`), `_get_interior_camera_entities` | `camera_census.py:2602` |
| Census result | REUSE `CensusZoneResult` unchanged | `camera_census.py:310` |
| Named sightings | REUSE (read); unnamed records are a sibling type, no second emit on `SIGNAL_PERSON_SIGHTING` | `person_sighting.py:64`, `:565` |
| Physical camera key, pick / fusion, face entities | REUSE `canonical_camera_key`, `resolve_pick_to_fusions`, `face_name_entities_for_device` (registry, never names) | `camera_resolver.py:507`, `:916`, `:760` |
| Interior path map (live file, garage_a / front, `lag_p90_s`) | REUSE validator + event shape; NEW public getter `path_map()` on `EgressDirectionTracker` | `interior_paths.py:39-60`, `:200`; `transit_validator.py:2363`, `:2493`, `:2566` |
| Vision shadow patterns (ring, gates at call time, record, teardown) | REUSE from `CrossingVisionShadow` (`:456`, `:795`, `:374`, `:343`), `register_frigate_consumer` (`frigate_ingress.py:582`) | `crossing_vision.py` |
| Image call on 1-3 frames | REUSE the image helper P2-D8 adds beside `analyze_crossing_frames` (`perimeter_enrichment.py:360`); no second helper | |
| Provider / model | REUSE `CROSSING_VISION_PROVIDER_ID` (Luna entry), `CROSSING_VISION_MODEL` | `const.py:3554`, `:3549` |
| Grading | REUSE crossing-vision P2-D10 Companion branch, prefix `GRADE_URA_` (one handler in `_handle_companion_action`, `notification_manager.py:1330`), and the one weekly labelling run (arc map M10) | |
| Stream death = missing | REUSE `camera_input_stream_dead` (live), S2 camera-keyed form later | `coordinator.py:2689` |
| NVR family agreement | REUSE `nvr_witness` `families_live` / `agreement` when W2 lands | `PLANNING_nvr_witness_layer.md` §7 |
| Read surface | EXTEND: NEW `get_room_sightings()`, `get_room_description(room)`, `get_last_path_record()` beside `presence.py:5933`, `:5952`, `:5984` | |
| Consumer classes | REUSE `CONSUMER_CLASS_MIN_CONFIDENCE`, `CROSSING_VISION_CONSUMER_CLASSES` | `const.py:6528` |
| Reserved `CROSSING_VISION_INTERIOR_ENABLED` | REUSED intent, renamed `INTERIOR_VISION_*` (pointer in crossing vision §6, §12) | |
| `RoomSighting`, `interior_vision.py`, `sensor.ura_interior_awareness`, `INTERIOR_VISION_*` | NEW: grep of `const.py`, `config_flow.py`, entity platforms, `domain_coordinators/`, `docs/planning/` for those names: 0 hits | |

## 7. Privacy (operator: accepted now; move local when accuracy holds)

- Inference uses the Luna provider entry (cloud). Frames only from the 7 shared-space cameras (INV-IV-SCOPE).
- Every call sets `store_in_timeline` False, `use_memory` False, `expose_images` False. Measured at doors: with
  `expose_images` True llmvision writes one key frame per call to `/media/llmvision/snapshots/<uid>-<n>.jpg` and its
  retention of that folder is not known (`AUDIT_crossing_vision_d0_2026_11_13.md`). Whether `expose_images` False writes
  nothing is NOT verified: D0(f) lists the folder before and after its calls and the plan ships only if 0 new files appear;
  if a file appears, D2 deletes it after the call and counts it (`interior_frames_deleted`).
- No frame is kept by URA. Grading frames for D0 / D7 are held for the labelling run only and deleted after the grade.
- D6 moves inference to a local model on homelab hardware (not the Mac Ollama) when the bar in D6 is met.

## 8. Invariants (falsifiable; reviewer D breaks these)

- **INV-IV-AWAY.** For any room record, vision count, description, path record, switch or cap value, AWAY entry time and
  the number and timing of `_run_inference` calls equal develop. Choke points: the census plan's five (§4 there) plus any
  read of the new getters from `presence.py` outside the getters. Test: the census plan's
  `test_away_tick_identical_with_vision_payload` harness with 3 unnamed and a vision term 5.
- **INV-IV-NO-TRUST.** No module in presence inference, `security*.py`, `security_lock_regime.py`, `perimeter_alert.py`,
  `hvac*.py`, `fan_veto.py`, `arrival_edges.py` reads a room record, description, path record or interior term.
- **INV-IV-NO-NAME.** `named` comes only from the BLE / face union; no vision output sets a slug, `person_id` or
  `identity_provenance`. Break it with a description naming a resident reaching `named`.
- **INV-IV-DEDUP.** A body seen by a camera's Frigate leg, its Protect leg and a vision call counts once (max per
  `canonical_camera_key`); BLE + face for one resident in one room counts once; {family_room, master_hallway} combine by max.
- **INV-IV-MISSING.** Dead stream or failed call = `missing` (case D), never 0.
- **INV-IV-OFF.** Switch off, `LLMVISION_ENRICHMENT_KILL` True or cap 0: zero inference calls and zero frame fetches from
  this module (D1 calls no model and has its own kill).
- **INV-IV-SCOPE.** Frames come only from the resolved interior list or an inward path-map edge of the crossing's door.
- **INV-IV-NO-STORE.** After any call, no new file from this module remains under `/media/llmvision/snapshots` or URA paths.

## 9. Deliverables

### D0: interior count error probe (read-only plus a graded sample)
(a) Coverage: physical cameras (canonical key), NVR families, area, URA room, path-map membership. (b) Graded sample: ≥ 30
frames per camera (≥ 210), drawn from the recorder timeline and fetched through the HA Frigate / Protect proxies, stratified
by moment: NVR and BLE agree, disagree, BLE empty (no resident placed), NVR count 0, and night / day; graded in the weekly
labelling run (P2-D10 grading path, `GRADE_URA_` prefix; until P2-D10 is live, the labelling page used for the 30 door
frames). Truth = operator people count. Report per camera: miss rate (truth ≥ 1, NVR 0), false-positive rate (truth 0, NVR ≥
1), multi-person undercount rate (truth ≥ 2, NVR < truth), exact rate, Wilson 95 % intervals. (c) Same frames through Luna
(≤ 1 call per frame, cost about $0.0003 input each, gpt-4o-mini fallback about $0.0095): per-camera vision error with
intervals. (d) Secondary table: recorded-attribute agreement (`area_raw_max_pre_cancel` vs `ble_by_area`), shares and
disagreement durations. (e) Path map doors and edges; group entries per day (57 of 189 crossing rows had peak 2+) and
inward-hop coverage (55-67 % of entries reach a chain camera). (f) Privacy check of §7 (folder before / after) and latency
p50 / p90 of interior calls. (g) Description pilot: 20 frames, operator rates "useful / wrong / empty".
- **Gates (each failure = an operator question, never an automatic park):** D0-P1 D2 proposed parked if NVR exact ≥ 97 % on
  every camera AND vision is not better on any camera. D0-P2 D5 vision leg proposed parked if group entries < 1 a day or
  hop coverage < 50 %. D0-P3 D3 proposed parked if fewer than 12 of 20 descriptions rated useful.
- **Verify:** `docs/planning/AUDIT_vision_interior_d0_<date>.md`, one table per item with intervals. **Live:** none.

### D1: room records, no model (Tier 2-DB)
`interior_vision.py` HA-free core `build_room_records(area_bodies, ble_by_area, named_faces, vision_counts, health,
area_to_room, now)`; census getter `area_evidence()`; presence builds records on each census update into RAM;
`get_room_sightings()`. `bodies` per camera = a vision count fresher than `INTERIOR_VISION_TERM_MAX_AGE_S` (from D2) else
the NVR count. `sensor.ura_interior_awareness` (Census device): state = total unnamed in covered rooms, per-room attributes
unrecorded (raw inputs are already recorded by the census sensor).
- **Verify (discriminating):** family_room bodies 2, BLE {ezinne} → `unnamed_present` 1; BLE {ezinne, jaya} → `confirmed`;
  bodies 0, BLE {jaya} → `ble_unconfirmed` (the census guest count reads 0 in all three); dead stream → `missing`.
- **Tests:** `test_room_records_statuses`, `test_dead_stream_is_missing_not_empty`, `test_named_union_dedups_ble_and_face`,
  `test_stale_resident_does_not_confirm`, `test_census_fields_golden_unchanged`, `test_no_trust_reader_of_room_records`,
  `test_kill_switch_no_records`. Mutation: read post-cancel `_last_area_contributions` for `bodies` → statuses test red.
- **Live:** within an hour the sensor lists the 7 rooms; a BLE-placed resident on camera reads `confirmed`; census sensors
  unchanged.

### D2: sampling and correction budget (Tier 2-DB; after D0 and P2-D8's image helper)
Per camera a sampling weight from D0: `w = clamp(err_rate, INTERIOR_VISION_MIN_WEIGHT, 1)`, err_rate = 1 − exact (refreshed
from graded D7 rows). Inputs that schedule a call on a camera, in priority order: (1) a room record in `unnamed_present` or
`ble_unconfirmed` for `INTERIOR_VISION_DISAGREE_PERSIST_S`; (2) an NVR count change on a camera with `w` ≥
`INTERIOR_VISION_CHANGE_WEIGHT_MIN`; (3) a background sample while the room's NVR count is ≥ 1 or BLE places someone there,
at most once per `INTERIOR_VISION_SAMPLE_INTERVAL_S / w`. Per-camera cooldown, daily call cap and daily cost cap (the cost is
estimated per call from frames × `INTERIOR_VISION_EST_COST_PER_FRAME`, since llmvision returns no usage); skips counted.
Call: 1-3 frames, prompt forbids naming, schema `{people, desc}`, §7 privacy flags. Row: one `log_memory_episode(
episode_type="interior_vision", node_id=f"ivision:{camera_key}:{ts}", source_ref=camera_key, dedup_source_ref=False)` with
room, NVR count, named count, vision people, trigger, outcome, latency, model, `pipeline_version`; type joins
`MEMORY_WRITER_BACKED_EPISODE_TYPES`. Up to `INTERIOR_VISION_GRADE_DAILY_N` rows a day go to grading (disagreements first).
Output feeds D1 `bodies` and D4 only (awareness).
- **Verify (discriminating):** ghost (NVR 1, truth 0, vision 0) → record `empty`, provenance `vision`, census trust count
  unchanged; merged group (NVR 1, vision 3) → unnamed 3 on the record only; a camera with D0 exact 99 % gets about a tenth of
  the background samples of one at 80 %.
- **Tests:** `test_disagreement_needs_persistence`, `test_sampling_weight_scales_rate`, `test_cost_cap_and_call_cap_skip`,
  `test_switch_off_no_call`, `test_blank_frames_not_zero`, `test_no_name_reaches_named`, `test_privacy_flags_set`,
  `test_teardown_cancels`, `test_scope_interior_cameras_only`. Mutation: drop the call-time switch re-read; drop the weight.
- **Live:** ≥ 1 `interior_vision` row per triggered input type within a day; calls ≤ cap; 0 new files under the snapshot folder.

### D3: describe what is happening, on demand (Tier 2-DB; with D2)
`get_room_description(room)` / `describe_person(slug)` (person → the room BLE places them in, or the last named sighting
camera). One call on the room's camera, schema `{people, activities: [{what, where_in_room}], context, confidence}`, no
names, no affect fields. Triggers: an operator NM request (one inbound command routed to the same handler family, reply to
the operator only) and a personalization read (rate-limited per room by `INTERIOR_DESCRIBE_ROOM_COOLDOWN_S`). Counts against
the D2 caps. Rows `interior_description`. A description is never stored as a frame.
- **Verify:** an operator request "family room" returns one structured description within p90 latency + 5 s; a room
  without a camera returns "no camera" without a call.
- **Tests:** `test_describe_schema_no_names`, `test_describe_room_without_camera_no_call`, `test_describe_rate_limited`,
  `test_describe_counts_against_cap`, `test_describe_never_feeds_census`.
- **Live:** one operator-requested description delivered; one `interior_description` row.

### D4: interior term in `deconflict_house` (Tier 3; after census CD1 and D2)
Term per camera: the fresh vision count, keyed by `canonical_camera_key`; max with the NVR count of the same camera (rule 2),
residents once through R (rule 4), guest side by max (rule 3), stale / failed = missing (rule 5). Moves the awareness view
only while `INTERIOR_VISION_TERM_LEADS` is True (default False). Bar for the flip (operator Tier-3 checkpoint): ≥ 100 graded
interior rows over ≥ 7 days incl. ≥ 10 with a non-resident, vision exact ≥ 90 % per camera, false guest in resident-only
time ≤ 2 %, vision right on ≥ 80 % of graded NVR disagreements.
- **Tests:** `test_interior_term_max_with_nvr_same_camera`, `test_interior_term_missing_when_stale`,
  `test_awareness_unchanged_until_leads`, `test_trust_view_byte_identical_interior_on`, INV-IV-AWAY. Mutation: sum NVR and
  vision on one camera; let the term reach `unidentified_count`.
- **Live:** awareness equals trust while LEADS is False; the scorer reports the bar numbers.

### D5: path time-lapse after a crossing (Tier 2-DB; no-model leg after D1, vision leg with D2)
Trigger: an entry `ura_person_egress_event` on a door with a path map. No-model leg: inward-edge cameras with a person event
inside `E` + the edge's `lag_p90_s` (fallback `INTERIOR_PATH_DEFAULT_WINDOW_S`) → `PathRecord` (crossing_key, door, n,
hops: camera, room, first seen, count). Vision leg: when n ≥ `INTERIOR_PATH_VISION_MIN_N` or `guests_unnamed` ≥ 1, one call
per hop camera (≤ 3 per crossing). Hops seed the hop room's record for `INTERIOR_PATH_SEED_TTL_S`. Coverage ceiling 55-67 %
of entries is stated, not tuned. Rows `interior_path`.
- **Tests:** `test_path_window_from_map_lag`, `test_single_entrant_no_call`, `test_group_entry_calls_hops_capped`,
  `test_no_map_no_record`, `test_path_seeds_room_record_ttl`. Mutation: count approach edges as inward.
- **Live:** ≥ 1 `interior_path` row after a multi-person entry.

### D6: local inference (Tier 2-DB; operator checkpoint to switch)
A provider choice `INTERIOR_VISION_BACKEND` (`luna` / `local`) where `local` is an llmvision provider entry (or an
OpenAI-compatible endpoint) served by a vision model on homelab hardware, never the Mac Ollama. Equivalence test: the same
graded set (D0(b) plus D7 grades, ≥ 200 frames) through both; switch is proposed when local exact count is within 2 points
of Luna per camera, false-positive rate not higher by more than 1 point, multi-person undercount not higher, and p90
latency ≤ `INTERIOR_VISION_LOCAL_LATENCY_P90_S`. Trigger to run the test: D4 bar met, or Luna exact ≥ 90 % held 14 days.
The switch itself is an operator checkpoint; after it, a rolling 14-day check pages if local falls below the bar.
- **Tests:** `test_backend_switch_routes_calls`, `test_equivalence_report_per_camera`. **Live:** equivalence audit file.

### D7: diagnostics, grading and trip-wires (with each producer)
`interior_room_records_zero` (HIGH: interior NVR bodies > 0 on ≥ `INTERIOR_ZERO_MIN_TICKS` ticks in 24 h and 0 records);
`interior_vision_errors` (MEDIUM, error rate > `INTERIOR_VISION_ERROR_RATE_MAX`); `interior_frames_left` (HIGH, any file
INV-IV-NO-STORE finds); attributes `calls_today`, `cost_today_est`, `latency_p90_s`, per-camera `exact_rate` and `weight`.
Grading through P2-D10 (`GRADE_URA_` prefix, one handler). Weekly scorer extended in the crossing-vision scorer script.

## 10. Directions not built now (each an operator decision with a revival trigger, carded per §12)

- **Emotion / affect, the deepest layer.** Revival: counts (D4 bar) and descriptions (≥ 80 % rated useful over 30 days) have
  earned trust, a named consumer exists (personalization), and the operator rules on affect inference for household members;
  D6 local inference strongly preferred first.
- **Periodic fixed-interval head count** (sighting plan §15.8): D2's background sampling covers it; revival if the crossing
  ledger's bar a fails twice. Asked, not assumed.
- **Security use** (G4): census ladder rung 5, plus D2 p90 latency ≤ 15 s.

## 11. Knobs

| Knob | Default | Rung | Why / kill |
|---|---|---|---|
| `INTERIOR_ROOM_RECORDS_ENABLED` | True | 1 | D1 master; False = no records |
| `switch.ura_interior_vision` ("Interior vision (shadow)"), config-flow entry | off at ship | 3 | D2 / D3 / D5 vision master |
| `INTERIOR_VISION_DAILY_CALLS` | 60 (D0 sizes) | 3 (Number) | 0 = no calls; separate from the door cap |
| `INTERIOR_VISION_DAILY_COST_USD` | 0.50 | 3 (Number) | Estimated spend cap; 0 = no calls |
| `INTERIOR_VISION_EST_COST_PER_FRAME` | 0.0001 (Luna estimate) | 1 | Cost estimate, no usage from llmvision |
| `INTERIOR_VISION_SAMPLE_INTERVAL_S` | 3600 | 1 | Background rate at weight 1 |
| `INTERIOR_VISION_MIN_WEIGHT` | 0.1 | 1 | Floor so a good camera is still checked |
| `INTERIOR_VISION_CHANGE_WEIGHT_MIN` | 0.1 | 1 | Count-change trigger only on error-prone cameras |
| `INTERIOR_VISION_DISAGREE_PERSIST_S` | 120 | 1 | Ignores walk-through blips |
| `INTERIOR_VISION_CAMERA_COOLDOWN_S` | 600 | 1 | Calls per camera bound |
| `INTERIOR_VISION_MAX_FRAMES` | 3 | 1 | D0b: ≥ 3 frames for a count |
| `INTERIOR_VISION_TERM_MAX_AGE_S` | 600 | 1 | Older = missing |
| `INTERIOR_VISION_TERM_LEADS` | False | 1 | D4 flip; reviewed const edit |
| `INTERIOR_VISION_GRADE_DAILY_N` | 5 | 3 | 0 = no grading |
| `INTERIOR_DESCRIBE_ROOM_COOLDOWN_S` | 300 | 1 | Personalization reads |
| `INTERIOR_ROOM_FACE_FRESH_S` | 300 | 1 | Named-face freshness |
| `INTERIOR_PATH_DEFAULT_WINDOW_S` / `_VISION_MIN_N` / `_SEED_TTL_S` | 90 / 2 / 600 | 1 | Path leg; MIN_N 99 = vision leg off |
| `INTERIOR_VISION_BACKEND` | `luna` | 2 (options) | `local` after the D6 checkpoint |
| `INTERIOR_VISION_LOCAL_LATENCY_P90_S` | 10 | 1 | Local acceptance |
| `INTERIOR_ZERO_MIN_TICKS` / `INTERIOR_VISION_ERROR_RATE_MAX` | 20 / 0.25 | 1 | Trip-wires; 0 / > 1 = off |

## 12. Edits other plans need (not made here)

- `PLANNING_crossing_vision.md` §8: B-stage chains and interior head counts → this plan D5 / §10; §6 reserved row → pointer;
  P2-D8 image helper reused by D2 / D3; P2-D10 grading gains the interior key prefix and frame strata.
- `PLANNING_census_deconfliction.md` §3.3: interior term = D4 with its bar; §3.6: per-room awareness = D1 sensor.
- `PLANNING_person_sighting_layer.md` §15.8 → D2 background sampling; §15.9.4 window knobs → path map `lag_p90_s`.
- `PLANNING_person_awareness_read_api.md`: add the three getters to the ship-1 callers.
- `PLANNING_camera_input_stream_health.md` S2 and `PLANNING_nvr_witness_layer.md` W5b: list D1 / D4 as readers.
- `ARC_identity_vision_census_map.md`: card row → this doc; path chains merged here; D6 local inference added to the arc.
- `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (code contradicts doc): read-API ship 1, stream health S1, person sightings and
  crossing vision shadow are marked "NOT deployed" but are in tag v5.108.21 (`git grep`), live.
- `IDENTITY_FUSION_CAMERAS_MANUAL.md` §4.5a: unnamed room records beside named sightings (on D1 ship).
- Board: card the §10 directions (emotion, periodic head count) as operator-decided items with triggers; link P2-D8 / P2-D10.

## 13. Revise when we learn

| Measurement | Changes |
|---|---|
| D0(b) per-camera NVR error | D2 weights, call cap, whether D0-P1 is asked |
| D0(c) vision error vs NVR | D2 value case; D4 bar realism |
| D0(f) snapshot folder check | §7 delete step needed or not |
| D0(g) description ratings | D3 schema, D0-P3 question |
| P2-D8 shadow (F on real snapshots) | D2 frame source |
| P2-D7 group walks | D5 vision threshold |
| D7 graded rows over time | weights refresh, D4 flip, D6 trigger |
| NVR W2 interior agreement | `bodies` provenance |
| Local model equivalence | D6 switch |

## 14. Tier, reviews, sequence

Plan: Tier 3, two plan reviews (completeness; adversarial build-prediction) plus framing G (goal fidelity). D1, D2, D3, D5,
D6: Tier 2-DB (correctness; async / lifecycle / write path; test authority by per-site mutation) plus framing G. D4: Tier 3
(A / B / C mutation / D completeness on INV-IV-AWAY and INV-IV-DEDUP incl. pre-existing census readers; orchestrator re-grep
and mutation; operator checkpoint). Sequence: D0 now (grading in the next weekly run); D1 and D5 no-model leg next; D2, D3
and D5 vision leg after D0 and the P2-D8 helper; D4 after census CD1; D6 when its trigger fires. Each ship updates the
presence state of play in the same commit.

## 15. Plan completion tracking

Filled at each ship: delivered, operator decisions on any D0-Pn question, deferrals with card and reason, and a supersession
check of the census per-area attributes once D1 reads them through `area_evidence()`.
