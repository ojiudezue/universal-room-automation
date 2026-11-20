# Plan review: interior vision sightings, completeness framing (Tier 3, review 1 of 2)

Plan: `docs/planning/PLANNING_vision_interior_sightings.md` (VISION-INTERIOR-SIGHTINGS-1, arc step 9), written
2026-11-14 00:45 against develop 98a2a640 / live v5.108.21. Reviewed 2026-11-15 against develop 8d6eaa26 (v5.108.24,
layer ship 3a live) and `feature/layer-ship3b` 5d8b831d (CameraTwinHealth, ships as v5.108.25). Review only; the plan
is not edited.

Read completely first: charter `ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`, `.claude/skills/ura-arc/SKILL.md`,
`ARC_identity_vision_census_map.md`, `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 ledger; nothing below re-asserts
a ledger claim), `SENSOR_FLEET_CLASSES.md`, `IDENTITY_FUSION_CAMERAS_MANUAL.md` §4.5a and §5.5,
`CONTRACT_person_awareness_layer.md`, `PLANNING_person_awareness_layer_ship3.md` §5 D7 and §6.

**Verdict: PLAN-FIX-REQUIRED.** 1 CRITICAL, 5 HIGH, 7 MEDIUM, 3 LOW. The product shape (D0 probe first, unnamed room
records, sampling sized by measured error, describe on demand, path time-lapse, awareness-only census term, local
later) matches the charter. What fails is completeness against the layer contract and the code that landed since
the plan was written: there is no layer conformance table, the F4 producer contradicts the contract, D4 does not fit
`deconflict_house` as built, camera liveness reads a getter that answers None for one of the seven cameras, and the
BLE `named` source returns counts, not slugs.

## 1. Surface re-enumeration

| Surface | Plan claims | Verified | Gap |
|---|---|---|---|
| Census per-area bodies / BLE | REUSE via NEW `PersonCensus.area_evidence()` copying `camera_census.py:5950, 6082-6134` | stores are `_last_area_contributions` (`camera_census.py:1410`, written `:2172`), `_last_area_raw_max_pre_cancel` / `_last_ble_by_area` (`:1428-1429`, written `:6367-6368`); 0 hits for `area_evidence` | cites drifted; BLE side is counts only (H4) |
| BLE residents by area | REUSE `_ble_home_by_area` `:3066` | now `camera_census.py:3236`, returns `dict[str, int]` | cannot give slugs (H4) |
| Interior camera list | REUSE `_get_interior_camera_entities` `:2602` | now `camera_census.py:2706`; ship 3b renames it public `interior_camera_entities()` (on the guard READ_LIST, 3b `_layer_guard_engine.py:126`); returns person `binary_sensor` ids, not `camera.*` | frame source not derived (H5) |
| Census function | `deconflict_house` term per camera | `census_deconflict.py:90-131`: scalar `guest_vis` + `extra_guest_terms` mapping, guest terms maxed, ONE `vision_leads` flag; call site `camera_census.py:6929` | D4 shape mismatch (H1) |
| Named sightings | REUSE read; unnamed = sibling type, no emit on `SIGNAL_PERSON_SIGHTING` | `person_sighting.py:569`; contract §2.4 and §7 require `_emit_unnamed` on the same producer | C1 |
| Physical camera key | `canonical_camera_key` `camera_resolver.py:507` | exists; ship 3b adds a second grouping (`CameraTwinHealth` twin groups, W1 `_frigate_object_name_sibling` `camera_resolver.py:1672`, registry evidence) | two keys, no stated equivalence (M4) |
| Stream death | `camera_input_stream_dead` `coordinator.py:2689` | now `:2772`; a ROOM getter, answers only for that room's inputs; house fold `camera_stream_health.entity_stream_view` `:633`; 3b `physical_camera_dead` (`camera_twin_health.py:1165`) | H3 |
| Path map | NEW `EgressDirectionTracker.path_map()` | `path_map_status` exists (`transit_validator.py:2836`) and is in `LAYER_NON_PERSON_PUBLIC` (`_layer_guard_engine.py:207`) | guard (H2) |
| Crossing reads (D5) | `ura_person_egress_event` + crossing-vision `people_count` / `camera_peak_count` | pull reads `get_crossings_since` (`presence.py:6112`), `get_last_arrival_record`; crossing-vision row store has one owner (contract G8) | read path unnamed (H2, M6) |
| Image helper | REUSE "the helper P2-D8 adds" beside `analyze_crossing_frames` (`perimeter_enrichment.py:360`) | P2-D8 is on `feature/crossing-vision-fast-stage`, not develop; `analyze_crossing_frames` already wraps llmvision `video_analyzer` (`:346-353`) | clip path unstated (H5) |
| Grading | P2-D10 Companion branch, `GRADE_URA_` prefix | P2-D10 unbuilt; the fallback "labelling page used for the 30 door frames" is not a code surface | MEDIUM risk on D0 timing, noted |
| AWAY harness | `test_away_tick_identical_with_vision_payload` | 0 hits in `quality/`; exists only as text in `PLANNING_census_deconfliction.md:202`; the shipped golden is `test_census_trust_golden.py` | M1 |
| Memory rows | `log_memory_episode(..., dedup_source_ref=False)`, `MEMORY_WRITER_BACKED_EPISODE_TYPES` | `database.py:10686` (params `dedup_source_ref`, `window_dedup`), const exists | OK |
| Kill | `LLMVISION_ENRICHMENT_KILL` | exists (`const.py`, read by `crossing_vision.py`, `perimeter_enrichment.py`) | OK |
| NM | trip-wires, D3 reply, grading | handler for the D3 inbound request not named | M6 |
| Diagnostics | sensor attributes | ship 3a has the config-entry diagnostics download (`get_layer_diagnostics`) | M7 |

Should cover and does not: the layer contract §6 conformance table (C1); ship 3b (device liveness, house tracker for
cameras no room watches, `interior_camera_entities`, `zone_camera_entities`); the seam with NVR-WITNESS-CONSOLIDATION-1
W2 (arc map step 9a, `ARC_identity_vision_census_map.md:155`); the clip-frame path (charter 2026-11-14, contract §6
item 8); the G6 one BLE-in-room read; the guard allowlist/READ_LIST delta.

Parked-plan triggers the plan would touch: DEAD-CAMERA-TWIN-COVERAGE-1 (revival "when W2 builds the one-physical-camera
model", `kanban.data.yaml:35058+`) if D1/D4 adopt a per-camera key; sighting plan §15.8 periodic head count (plan §10
asks, correct); `FACE_ARRIVAL_INTERIOR_ENABLED` (False; plan does not touch arrivals, correct). Reserved
`CROSSING_VISION_INTERIOR_ENABLED`: 0 code hits, so "renamed" is a doc-only rename (fine).

## 2. Layer contract check (guard rules, `_layer_guard_engine.py`)

`interior_vision.py` is not in `MEMBER_MODULES` (`_layer_guard_engine.py:54-57`). Each planned read, where it would
live, and the guard result:

| Planned read / write | If in `interior_vision.py` (non-member) | If in `presence.py` (member) |
|---|---|---|
| `census.area_evidence()` (new CENSUS public) | R2 hit (not on READ_LIST CENSUS, `:117-121`) | allowed, but the new public method must be added to contract §2.6 |
| `tracker.path_map()` (new EGRESS public) | R2 hit (READ_LIST EGRESS `:113-116`) | allowed |
| listen to `ura_person_egress_event` (D5 trigger) | R10 hit: not a listed listener (contract §4.2) and a new consumer may add zero rows | R10 hit too (presence is not a listed listener for this channel) |
| crossing-vision `people_count` (D5 `n`) | R2/R7 against the G8 row store unless read through `get_last_arrival_record()` / `get_crossing()` | same |
| `get_room_sightings` / `get_room_description` / `get_last_path_record` read by `sensor.py` | R2 hit until added to READ_LIST PRESENCE (`:101-110`) | n/a |
| unnamed record store, vision-count store, path-record store | new stores; R7 needs an owner row; contract §1 rule "no new store" unless owner is a member | owner = sighting producer per contract §2.4 |
| `get_last_person_sighting(s)`, `get_crossings_since`, `interior_camera_entities` (3b) | allowed (on READ_LIST) | allowed |
| D4 term pulled at `_compute_awareness` | conformant if pulled like `_ledger_tick` (`camera_census.py:6880-6897`) | n/a |

## 3. Findings

### CRITICAL

**C1. No layer conformance table, and the F4 producer contradicts the contract.** Contract §6
(`CONTRACT_person_awareness_layer.md:367-385`): "Every plan in the arc carries a 'Layer conformance' table ... a plan
that cannot fill a row is sent back." The plan has none (grep for "conformance" / "ingest": 0 hits). Contract §2.4
(`:141`) and §7 (`:394`): "interior vision adds `_emit_unnamed` ON THE SAME PRODUCER, not a sibling store." Plan §6
row "Named sightings" (`PLANNING_vision_interior_sightings.md:108`) says the opposite: "unnamed records are a sibling
type, no second emit on `SIGNAL_PERSON_SIGHTING`", and D1 (`:171-174`) builds records in presence RAM. Either the plan
conforms (unnamed record via `PersonSightingProducer._emit_unnamed`, store owned by the producer, `SIGNAL_PERSON_SIGHTING`
listeners still none) or it names the contract change and its owner (§6 item 7). Fix: add the §6 table (facts, ingest
function, read method + class, separation, delivery, guard delta, seam, clip path) and resolve the producer question.

### HIGH

**H1. D4 does not fit `deconflict_house` as built.** `deconflict_house(trust, *, guest_vis, vision_leads, flag_min,
extra_guest_terms=None)` (`census_deconflict.py:90-131`) takes house-level guest scalars combined by max; it has no
camera key (contract §2.2 `:102-105` says so) and one `vision_leads` flag fed from
`CROSSING_VISION_AWARENESS_VISION_LEADS` (`camera_census.py:6932`). Plan D4 (`:217-219`) specifies a term "per camera,
keyed by `canonical_camera_key`, max with the NVR count of the same camera", plus its own `INTERIOR_VISION_TERM_LEADS`.
The per-camera NVR max is ingest half (1) (`_cross_validate_platforms`, contract §2.2), not `deconflict_house`; a
second LEADS flag cannot be expressed without changing the function. Fix: D4 = a pulled `extra_guest_terms["interior"]`
house scalar (interior unnamed bodies after R, overlap pairs by max), REUSE `extra_guest_terms`; state whether interior
gets its own leads flag (a signature change, Tier 3, named) or shares the existing one.

**H2. Guard / read-surface delta missing.** Table §2 above: at least four planned reads are guard hits (R2
`area_evidence` / `path_map` from a non-member, R10 egress listener, R2 new getters from `sensor.py`) and three new
stores need owner rows. Plan §12 edits the read-API plan but not the contract §4.1/§4.2, the guard READ_LIST, or
`LAYER_ALLOWLIST_TOTAL`. Fix: name the module that hosts each runtime piece (member or not); D5 pulls
`get_crossings_since` / `get_crossing` on a tick or listens to `SIGNAL_EGRESS_RECORD_AMENDED` (people_count arrives as a
G3 attribute) instead of a raw bus listener; list every READ_LIST addition.

**H3. Camera liveness reads a room getter that answers None for the foyer camera.** Plan §6 (`:115`) reuses
`camera_input_stream_dead` (`coordinator.py:2772`), which answers only for that room's own inputs. Ship 3b §6.3 found
the foyer group (Frigate `camera.foyer_fisheye`, Protect `binary_sensor.foyer_fisheye_person_detected`) is watched by
no room (set U). Repro: foyer camera device offline → room getter None → D1 treats it as no opinion → record
`empty` / NVR 0, not `missing`. That breaks INV-IV-MISSING and the operator's "a dead camera is faulty equipment".
Also the Protect person sensors resolved `multi_camera` before 3b (ledger #41), so 6 of 7 interior Protect legs had no
liveness at all. Fix: read `camera_stream_health.entity_stream_view` (house fold, 3b house tracker for U) for
per-reader holds and `physical_camera_dead` for "every NVR lost it"; REUSE `PersonCensus.interior_camera_entities()`
(3b) for the list. Minimal dependency: ship 3b merged, not W2 (§4 below).

**H4. The BLE `named` source returns counts.** D1 `named` = "BLE residents placed there plus fresh named faces; one
union by canonical slug" (`:49-50`), sourced from `_ble_home_by_area` (`:105`), which returns `dict[str, int]`
(`camera_census.py:3236`). No slug, so the union, INV-IV-DEDUP ("BLE + face for one resident in one room counts once")
and `test_named_union_dedups_ble_and_face` cannot be built from it. Contract §2.4a names the ONE BLE-in-room read
`persons_in_room(room)` with the phone-left-behind filter (operator Q1 yes, `:421-423`). Fix: REUSE `persons_in_room` /
`get_person_location`, keyed by room; state the ACTIVE-only (`_ble_home_by_area`) vs STALE concept split if the plan
keeps the census count for `bodies` reconciliation (Bug Class #63, state of play gold patterns "STALE concept split").

**H5. Frame source per physical camera unspecified; clip path absent.** Interior list entries are person
`binary_sensor`s; frames need a `camera.*`. Protect devices carry 2-4 enabled camera entities (high, medium, low,
package; 3b §6.0). Which entity is snapshotted, chosen by what registry rule, and whether Frigate or Protect is the
frame source per camera is not stated (CLAUDE.md "Registry, never name guessing" applies; 3b's
`own_camera_entity_for_device` picks the first sorted entity, which can be a low or package channel). Separately, the
charter (2026-11-14: "Make sure no plan precludes that") and contract §6 item 8 require each vision deliverable to keep
a short-clip frame path; the plan never mentions clips (grep "clip" / "video": 0 hits), although
`analyze_crossing_frames` already wraps `video_analyzer` (`perimeter_enrichment.py:346-360`). Fix: a frame-source
section: registry rule per physical camera, still-frame default, and the clip route (Frigate event clip through the
existing adapter) for D3 and D5 at minimum.

### MEDIUM

**M1. INV-IV-AWAY anchor test does not exist; record build placement unspecified.**
`test_away_tick_identical_with_vision_payload` has 0 hits under `quality/`; the shipped golden is
`test_census_trust_golden.py` with `fixtures/away_latency_golden_develop.json` (state of play line 14). D1 builds records
"on each census update" (`:173`): the census handler is a `_run_inference` trigger (contract INV-AWAY-LATENCY,
`census_update`). The plan must say the build runs after the inference schedule and never awaits on that path, and pin
the real golden test. "The census plan's five (§4 there)" choke points should be listed in this plan.

**M2. Dead input semantics are mixed.** INV-IV-MISSING (`:145`): dead stream = `missing` at once. The census, which
supplies `bodies`, holds a dead camera's frozen reading up to `CAMERA_INPUT_STREAM_DEAD_CENSUS_HOLD_MAX_S` (900 s) and
then marks it missing (state of play S2 entry). So D1 can show `missing` while `bodies` carries a frozen count. State
which wins on the record (recommended: view `held` or `released` → status `missing`, `bodies` withheld), and that the D4
term never reads a held camera as 0.

**M3. Fact base stale.** Written on develop 98a2a640 / v5.108.21. Since then 3a is live (v5.108.24) and 3b is built.
Cites drifted: `_get_interior_camera_entities` `:2602` → `:2706` (public in 3b), `_ble_home_by_area` `:3066` → `:3236`,
`camera_input_stream_dead` `:2689` → `:2772`, `_emit` `:565` → `:569`, census area code `:5950/:6082` → around
`:2172`/`:6367`. Charter rule 8 (verify facts before dispatch).

**M4. Camera model seam with W2 not stated.** Arc map step 9a (`ARC_identity_vision_census_map.md:155`): W2 before step
9, "extend, never a second camera-liveness model". The plan keys identity by `canonical_camera_key` (fusion source set
min device id) and liveness by room getters; 3b groups by W1 twin pairs. The plan must state that, for the 7 interior
cameras, the canonical key and the 3b twin group name the same devices (or which is authoritative), and record that it
does not need W2 except for NVR-agreement provenance (plan §13 row "NVR W2 interior agreement").

**M5. Numbers without knobs.** Gate and bar numbers are inline: D0-P1 97 %, D0-P2 1/day and 50 %, D0-P3 12/20; D4 bar
100 rows / 7 days / 10 non-resident / 90 % / 2 % / 80 %; D6 2 points / 1 point / 14 days; D3 `describe_person` has no
cooldown of its own; `interior_frames_left` has no off value. Scorer thresholds should be named module constants (rung
1). `INTERIOR_VISION_GRADE_DAILY_N` and the two caps are rung 3 but the Number entities are not named. Switch label
"Interior vision (shadow)": operator "Name of switch. not good yet" and the no-shadow-mode rule (memory
`feedback_no_shadow_mode_day1_correct`) make the label a goal-fidelity question for review G.

**M6. Two consumer surfaces unnamed.** D3 "one inbound command routed to the same handler family" (`:207`): which NM
inbound path (Companion action `_handle_companion_action`, `notification_manager.py:1330`, or BlueBubbles) and which
class constant (`notification`, `min_confidence("notification")`). D5 `n` from crossing vision: through which read
(`get_last_arrival_record` vs a G3 attribute on the record), given G8 single ownership of the row store.

**M7. Diagnostics on entity attributes.** D7 puts `calls_today`, `cost_today_est`, `latency_p90_s`, per-camera
`exact_rate` / `weight` on `sensor.ura_interior_awareness`. State `_unrecorded_attributes` for each, or use the ship 3a
diagnostics download (`get_layer_diagnostics`) for counters.

### LOW

**L1.** INV-IV-NO-TRUST lists modules by name; it is falsifiable only through `test_no_trust_reader_of_room_records`.
Name that test's mechanism (AST import / call scan) and include `coordinator.py` (room occupancy), `aggregation.py`,
`presence_fan_recheck.py`, `music_following.py`, `automation.py`.

**L2.** INV-IV-NO-STORE covers this module's files; grading frames "held for the labelling run" have no location,
owner or deletion check.

**L3.** §12 state-of-play correction (stale "NOT deployed" markers for read API ship 1, S1, sightings, crossing-vision
shadow) is still true today (state of play lines 7, 13, 105, 107); keep it.

## 4. Camera model: minimal dependency

- D0, D2, D3, D5: need a per-physical-camera frame source and liveness. Ship 3b supplies liveness
  (`entity_stream_view`, `physical_camera_dead`, house tracker for the foyer) and the interior list
  (`interior_camera_entities`). They need 3b merged, not W2.
- D1: `bodies` from the census are already twin-deduped in `_cross_validate_platforms`; needs 3b for liveness, not W2.
- D4: as a house `extra_guest_terms` scalar (H1), no camera key reaches `deconflict_house`; W2 not needed. If the plan
  keeps a per-camera term, it depends on W5b moving `_cross_validate_platforms` to `nvr_witness` and must wait.
- W2 is needed only for NVR-family agreement as `bodies` provenance. State this, and tell the operator that step 9 can
  start on 3b, ahead of 9a, unless the plan keeps per-camera terms.

## 5. Charter constraints

| Constraint | Result |
|---|---|
| Short-clip path stays possible | FAIL (not stated), H5 |
| Privacy: accept now, local later | PASS (§7 flags, D0(f) folder check, D6); L2 residual |
| Supplements counts, adds depth (description, emotion later) | PASS in shape (D2, D3, §10 emotion with trigger) |
| AWAY stays fast | PARTIAL: invariant stated, anchor test missing and build placement unspecified (M1) |
| Dead camera = faulty equipment | FAIL for the foyer (H3), mixed semantics (M2) |

## 6. Plan-quality checks

- Invariants: INV-IV-AWAY, -DEDUP, -MISSING, -OFF, -SCOPE, -NO-STORE are falsifiable as written; INV-IV-DEDUP is not
  buildable from the named BLE source (H4); INV-IV-NO-TRUST is a list, not a mechanism (L1).
- Knobs: most runtime numbers have names and rungs; gate and bar numbers do not (M5).
- Acceptance: D1 and D2 have discriminating verifies; D3, D5, D6 Live criteria are thin but present; D0 has none
  (read-only, fine).
- Non-goals: there is no explicit non-goals section. §3 "Never: a name from vision; any trust reader" and §10 cover
  part of it; add a list (no identity from vision, no trust reader, no F2-T change, no new camera-liveness model, no
  bedroom or bathroom frames, no emotion fields).

## 7. What must change before a build can start

1. Add the layer conformance table and resolve the F4 producer (C1).
2. Re-spec D4 on `extra_guest_terms` and decide the leads flag (H1).
3. Name the host module of each runtime piece and list every READ_LIST, listener and allowlist change; D5 by pull or
   `SIGNAL_EGRESS_RECORD_AMENDED` (H2).
4. Rebase liveness and the camera list on ship 3b (`entity_stream_view`, `physical_camera_dead`,
   `interior_camera_entities`) and state the W2 dependency as provenance only (H3, M4).
5. Source `named` from `persons_in_room` with slugs (H4).
6. Add a frame-source section with the registry rule and the clip route (H5).
7. Re-verify cites, name the real AWAY golden test and the record build placement, fix dead-input semantics, give the
   gate numbers named constants, name the D3 and D5 read surfaces, add non-goals (M1-M7).

Estimate: one planner revision of half a day; D0 can start now (read-only, does not depend on these fixes).

## Summary

| Severity | Found |
|---|---|
| CRITICAL | 1 |
| HIGH | 5 |
| MEDIUM | 7 |
| LOW | 3 |

Bug classes touched: computed-but-not-consumed / one missed site (#53, guard surfaces), stale data source (#7, room
getter for an unwatched camera), concept split unnamed (#63, BLE count vs slugs; ACTIVE vs STALE), registry not names
(frame channel choice).
