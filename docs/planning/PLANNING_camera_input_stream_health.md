# PLANNING: camera input stream health (a dead camera's inputs stop holding rooms, zones and the census)

Cards: PANEL-KS-HEALTH-AS-INPUT-1 (implemented by S1, KS-agnostic), CAMERA-STREAM-DEAD-ZONE-AND-CENSUS-1 (S2), the URA
side of F2-PANEL-FFMPEG-CRASHLOOP-1. Tier 2-DB (standing regression-prone policy: room occupancy ripples into lights,
fans, HVAC). Clean consolidation 2026-11-13 of `PLANNING_perimeter_gate_evidence_and_input_health.md` Part B §7
(`plan/perimeter-batch` @ 514d4e06); that doc keeps Part A only. Siblings: `PLANNING_census_deconfliction.md` (reads
the S1 getter: a dead source is a missing term).

Read first for the build: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md` and, because room
occupancy feeds HVAC, `HVAC_ARCHITECTURE_STATE_OF_PLAY.md`, all completely.

## 1. Objective and charter

Charter: `docs/planning/ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`. Goals served: census accuracy ("Vision
is to assist census accuracy"), "Agnostic fixes" (drift row 10: the panel watchdog had been keyed on Frigate / one
camera), and the settings goal "help with accuracy (first)".

Objective: when a camera's stream is dead, inputs derived from that camera stop counting as evidence: first at room
tier (S1), then at zone tier, fan recheck and the census (S2), all through ONE health getter. Measured harm to fix: a
FROZEN `on` holding a room (and its zone) for hours, not an `off` being believed.

## 2. F1-F5: produced and consumed

Produces input health, not an identity fact. Consumed by F2: a camera-derived census input whose stream is dead is a
missing term (case D) in `deconflict_house`, never a zero. No F1, F3, F4 or F5 role.

## 3. Readers by consumer class

| Reader | Class | Ship |
|---|---|---|
| Room fusion legs via `_fusion_filter_active` (`coordinator.py:3620-3662`), D2 witness (`:2292`), `:5766` → room `STATE_OCCUPIED` → lights, fans, covers, HVAC `hvac_occupied`, NM panel targeting | house_state (room tier) | S1 |
| Zone substrate / tracker (`occupancy_substrate.py`, presence zone tier, `_zone_night_raw`) | house_state (zone tier) | S2 |
| Fan pause-recheck (`presence_fan_recheck.py`), `fan_veto.py` | comfort | S2 |
| Census interior camera counts (`camera_census.py`) | F2 input | S2, through the census plan's dedup rule 5 |
| `sensor.<room>_unavailable_entities` attributes | display | S1 |
| `optimization.py` (analysis) | display | unchanged |

Today zone, fan and census readers do not honour room exclusions (contract STEP-EXCLUDE-4), so S1 alone leaves a frozen
panel `on` holding the zone and counting a census body until the stuck rule fires.

## 4. Invariants

- **INV-STREAM (S1).** While a configured room input's own camera entity (same device, exactly one camera entity on that
  device) has read `unavailable` continuously for at least `CAMERA_INPUT_STREAM_DEAD_GRACE_S`, that input's vote
  contributes 0 to room-tier fusion, so it can neither create nor hold room occupancy. When the camera entity cannot be
  resolved, or the kill switch is False, room fusion is byte-identical to develop. Falsified by a room held occupied by
  a camera-derived input whose camera entity has been `unavailable` longer than the grace plus one tick.
- **INV-STREAM-ONE-GETTER (S2).** Zone tier, fan recheck and census read the dead-stream state only through the S1
  getter; no second derivation. Grep test.
- **INV-STREAM-ZONE (S2).** Same statement as INV-STREAM for zone occupancy and the census camera term (missing, not 0).

## 5. Deliverables

### Measurement (done 2026-11-13, recorder read-only)

URA consumes three panel inputs, Frigate person sensors filed as `presence_sensors` (still-person class):
`binary_sensor.study_a_panel_person_occupancy` (Study A), `binary_sensor.kitchen_panel_person_occupancy` (Kitchen),
`binary_sensor.up_hallway_panel_person_occupancy` (Upstairs Hallway). No KS-device entity is in any URA room list.

| Signal | Up Hallway outage 11-11 22:52 → 11-13 13:53 | Study A outage 11-13 13:14 → 13:53 | Healthy |
|---|---|---|---|
| `camera.<panel>` (Frigate, same device as the person sensor) | `unavailable` 22:53 → 13:53 | `unavailable` 13:14 → 13:53 | `streaming`; blips < 1 min at F2/HA restarts (11-12 13:16-13:17) |
| `binary_sensor.<panel>_person_occupancy` | stuck `on` 22:52 → 11-12 12:56 (14 h), then `off` | `off` | normal |
| `binary_sensor.upstairs_hallway_occupied` | held `on` 22:52 → 02:52 (4 h, released by the stuck-sensor rule) | n/a | n/a |
| `sensor.<panel>_foreground_app` (KS, esphome) | bridge app / `unavailable` | `android` → bridge app | kiosk; but Study A read `unavailable` 11-11 19:24 → 11-12 13:49 while its camera streamed |
| `switch.<panel>_rtsp_streaming` | `on` | `on` | not a health signal |

Findings: the Frigate camera entity's availability matches both outages exactly and needs no new entity;
`foreground_app` would give an 18 h false "unhealthy"; the harm is a frozen `on`; Frigate `sensor.<panel>_camera_fps`
exists but is disabled by the integration (no enable needed).

Config-first: removing the three panel sensors from the rooms' `presence_sensors` would stop the harm but loses their
value when healthy. Code needed for degrade-on-dead.

### S1: room-tier exclusion of dead-stream inputs (Tier 2-DB)

Design (marginal-benefit pushback applied; the operator framed it as "Kiosk Satellite health"; the KS-agnostic rule
covers both outages and any Frigate camera). In the room coordinator tick, after `reset_tick` (`coordinator.py:3373`) and
before the fusion legs:
- for each entity in the room's motion / presence / occupancy lists: resolve device → camera entity via REUSED
  `CameraResolver.resolve_entity_to_device_id` (`camera_resolver.py:776`) + `camera_entity_for_device` (`:756`; index
  `:656`, disabled skipped `:647`); devices with zero or ≥ 2 camera entities → unresolved, fail open (Protect NVR devices
  host several cameras). Cache per room, cleared on `entity_registry_updated`.
- `self._camera_unavail_since[camera_eid]`: set on first observed `unavailable`, cleared on any other state; `None` state
  (not loaded) and `unknown` = no opinion.
- if `CAMERA_INPUT_STREAM_HEALTH_ENABLED` and `now − since ≥ CAMERA_INPUT_STREAM_DEAD_GRACE_S`:
  `self._exclusion_set.promote("camera_stream_dead", input_eid, f"{camera_eid} unavailable since {since}")` (REUSED
  `SensorExclusionSet`, `domain_coordinators/sensor_exclusion.py`, contract STEP-EXCLUDE-1..4, `coordinator.py:713`).
- NM: once a promotion has lasted `CAMERA_INPUT_STREAM_DEAD_NM_AFTER_S`, `fire_stuck_signal(kind="camera_stream_dead",
  key=(room, input_eid), severity="HIGH", exclusion_engaged=True)` (`_stuck_signal_nm.py:165`); on release
  `fire_stuck_signal_recovered` (`:276`). A page at 30 min means the homelab watchdog did not fix it.
- Surface: `sensor.<room>_unavailable_entities` (`sensor.py:1810-1880`) gains `camera_stream_dead_inputs`
  ({input: camera, since}) and `camera_stream_inputs_resolved` (count). Unrecorded.
- NEW public getter `camera_input_stream_dead(input_eid) -> bool | None` (None = unresolved) for S2.
- Silence check (a zero-fire page is wrong: healthy = zero): a room listing a camera-derived input with
  `camera_stream_inputs_resolved = 0` logs one WARNING per boot. Fire check: would have fired twice in the 7-day window,
  engaged ~39 h and ~37 min.

Acceptance:
- **Verify:** replay of the Up Hallway shape (person `on`, camera `unavailable` from t0) → room vacates at the first tick
  after t0 + 120 s (+ the room's timeout), not at 4 h; provenance `camera_stream_dead`.
- **Verify:** camera `unavailable` 60 s then `streaming` → no exclusion.
- **Verify:** unresolved camera (no device / two cameras / disabled) → fusion byte-identical (golden on existing fusion
  fixtures). Kill switch False → byte-identical.
- **Verify (discriminating):** person `on` with camera `streaming` → occupied as today.
- **Verify:** NM once at 30 min HIGH and once recovered; not again the same day.
- **Tests:** `test_camera_stream_health.py::test_dead_stream_excludes_input_after_grace`, `::test_restart_blip_not_excluded`,
  `::test_unresolved_camera_byte_identical`, `::test_multi_camera_device_unresolved`, `::test_live_stream_input_counts`,
  `::test_nm_after_threshold_and_recovery`, `::test_kill_switch_off_byte_identical`, `::test_unknown_state_no_opinion`.
  Mutation anchors: remove the promote call; invert the grace compare; drop the multi-camera guard.
- **Live:** `sensor.study_a_unavailable_entities`, `sensor.kitchen_unavailable_entities`,
  `sensor.upstairs_hallway_unavailable_entities` each show `camera_stream_inputs_resolved = 1` and an empty
  `camera_stream_dead_inputs` while the panels stream. Organic: the next KS outage lists the input within ~2 min and the
  room is not held.

### S2: zone tier, fan recheck and census honour the getter (Tier 2-DB)

Enumerate every zone / fan / census reader of camera-derived inputs (§3 list is the hypothesis; the plan review re-greps).
Each reads `camera_input_stream_dead` and treats a dead input as no vote (zone, fan) or a missing term (census, through
the census plan's `deconflict_house` rule 5; the census trust view keeps its current arithmetic unless its own promotion
says otherwise, so S2 changes only which camera inputs the census treats as present).
- **Tests:** `test_zone_not_held_by_dead_stream_input`, `test_fan_recheck_ignores_dead_stream_input`,
  `test_census_dead_stream_is_missing_not_zero`, `test_stream_dead_single_getter` (grep). Mutation: bypass the getter at
  the zone site → the zone test red.
- **Live:** on the next outage the zone of the panel room is not held by the panel input; census `aware_agreement` shows
  `single_source` for that camera, not a 0 count.

## 6. Knobs

| Knob | Rung | Default | Kill |
|---|---|---|---|
| `CAMERA_INPUT_STREAM_HEALTH_ENABLED` | 1 | True | False = develop |
| `CAMERA_INPUT_STREAM_DEAD_GRACE_S` | 1 | 120 | larger = slower; restart blips measured < 60 s |
| `CAMERA_INPUT_STREAM_DEAD_NM_AFTER_S` | 1 | 1800 | 0 = no NM (exclusion still applies) |

## 7. Dependencies and sequence

S1 after perimeter Part A ships (independent code). S2 after S1, and before the census plan's F-LEAD. Reviews per ship:
A correctness (grace timing, resolution cache, state vocabulary); B cross-coordinator effects (HVAC `hvac_occupied`, zone
roll-up, fan recheck with a vacated room) + restart; C per-site mutation; plus a goal-fidelity framing per the charter.

## 8. Non-goals

KS restart / watchdog (homelab owns it, F2-PANEL-FFMPEG-CRASHLOOP-1); the KS `foreground_app` leg (parked; revival
trigger: a KS-device entity such as `binary_sensor.<panel>_motion` is added to a URA room list, OR an outage where the
Frigate camera entity stays `streaming` while inputs freeze; design note: unhealthy only on a real non-KS value,
`unavailable` / `unknown` = no opinion); "hold on dead sensor" (operator default: exclude only; Upstairs Hallway is a
transit space, Study A and Kitchen have radars; a hold-on-missing rule is the phantom-hold shape); enabling Frigate fps
entities; NM wall-panel channel delivery health.
