# PLANNING: person-awareness layer ship 3 (3a layer plumbing + leak guard, 3b dead-camera rule)

Date 2026-11-14, rev 3.8. Author ura-planner. Cards: PERSON-AWARENESS-READ-API-1 (ship 3a); NVR-WITNESS-CONSOLIDATION-1
field `INSTANCE_2026_11_14_dead_camera_per_entity` (ship 3b). Contract: `docs/planning/CONTRACT_person_awareness_layer.md`
(rev 2, A1-A13, operator answers 4fc1b848). Leak inventory: `docs/planning/AUDIT_person_awareness_layer_leaks_2026_11_14.md`.
Charter: `docs/planning/ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`. Consumers downstream: step 7
`PLANNING_egress_direction_aware_identity.md` rev 3.1, step 8 `PLANNING_identity_actions_v6.md`.

Trees read: `release/batch-2` @ b3cacfcc (written "b2"; every citation is b2 unless marked; it differs from d30c1160
only in `person_coordinator.py` and `aggregation.py`, the BLE registry merge, and those two files are cited at b3cacfcc)
and `feature/census-deconfliction-p2-ledger` @ 92e93c54 ("p2"). p2 is based on develop, not on batch 2. Both are now on
develop (v5.108.23); §6 (ship 3b) cites develop @ 06e88508 directly.

## 0. Where the layer stands

| Contract piece | Status | Where (file:line) |
|---|---|---|
| F2 read by class: `view_for_class`, `get_house_census`, `CONSUMER_CLASS_MIN_CONFIDENCE` | LIVE in v5.108.21 | `presence.py:6006-6041`, `const.py:6547-6580` |
| F3 read: `get_last_crossing` (tracker + presence delegate) | LIVE in v5.108.21 | `transit_validator.py:1040-1054`, `presence.py:6043-6053` |
| One person-id rule `person_ids.tracked_person_entity_id` / `slug_of` / `display_of` | LIVE in v5.108.21 | `person_ids.py` |
| F1 residency ledger `ResidencyTracker` + `get_recent_resident_arrival` / `get_residency_snapshot` | LIVE in v5.108.21 | `domain_coordinators/residency.py:62-215`, `presence.py:5516-5543` |
| S1 room stream health (`camera_input_stream_dead`) | LIVE in v5.108.21 | `coordinator.py:2772` |
| `census_view.house_census_view` (pure F2 read) | LIVE in v5.108.22 | `census_view.py:52` |
| `PersonArrivingPayload.from_signal` | LIVE in v5.108.22 | `domain_coordinators/signals.py:28-69` |
| Public census evidence reads `tracked_person_slugs`, `egress_identity_enabled` | LIVE in v5.108.22 | `camera_census.py:4061`, `:4085` |
| Private-census-read guard (41 allowlist rows) | LIVE in v5.108.22 | `quality/tests/test_person_awareness_read_api_ship2.py:494-602` |
| S2 house stream-health getters and views (`input_stream_view`, `entity_stream_view`, `camera_stream_dead`, 900 s holds) | LIVE in v5.108.22 | `domain_coordinators/camera_stream_health.py:508-668` |
| BLE-PERSON-SENSOR-REGISTRY-RESOLVE-1 (registry-resolved Bermuda sensor per person; deletes `aggregation._find_bermuda_sensors`; adds `get_bermuda_resolve_stats`) | LIVE in v5.108.22 (merged into `release/batch-2` at 9114d2a0) | `person_coordinator.py:1918` (`get_bermuda_resolve_stats`); no listener, dispatcher or bus call added. Seam: §11 |
| F2 deconfliction `deconflict_house`, crossing ledger, `tier1_entity_ids` | LIVE in v5.108.23 (census-p2) | p2 `census_deconflict.py:90-131`, p2 `crossing_ledger.py`, p2 `occupancy_substrate.py:860-864` |
| F1 edge push channel `SIGNAL_RESIDENCY_EVENT` | LIVE in v5.108.23 (census-p2) | p2 `signals.py:200`, send p2 `presence.py:5331`, raw listener p2 `crossing_vision.py:417-421` |
| G8 crossing-vision row store owner | LIVE in v5.108.23 (census-p2) | `crossing_vision.py` |
| G7 ledger stream-health swap (per-input `entity_stream_view` replacing the duck-typed scan) | LIVE in v5.108.23 (built in census-p2's rebase) | `crossing_vision.py:1168` (develop) |
| G4 `dispatch_person_arriving` + `PersonArrivingPayload.to_signal()` (A7) | BUILT BY SHIP 3a | §5 D1 |
| F5 read `subscribe_person_arriving` | BUILT BY SHIP 3a | §5 D1 |
| Typed F4 camera ingest (face latch register / read) | BUILT BY SHIP 3a | §5 D1 |
| G1 `subscribe_person_edges` + A1 `get_person_edges_since` (A1b `counted`) | BUILT BY SHIP 3a | §5 D2 |
| G2 crossing ring + `get_crossings_since`, A3 `get_crossing`, A9 `door_camera_device_ids` | BUILT BY SHIP 3a | §5 D3 |
| G3 `attach_crossing_attribute` + `amend_crossing` + `SIGNAL_EGRESS_RECORD_AMENDED` (A4, A5), exit-backfill migration | BUILT BY SHIP 3a | §5 D3 |
| G5 door roster (`door_entry_entities`, `door_neighbours_for_stem`) | BUILT BY SHIP 3a | §5 D3 |
| G6 pull `location_moves_since` (A2) | BUILT BY SHIP 3a | §5 D4 |
| G9 `set_pre_arrival_enabled`; `min_confidence`; class-taking census view; `ZonePresenceTracker.note_face` | BUILT BY SHIP 3a | §5 D4 |
| Layer diagnostics | BUILT BY SHIP 3a | §5 D5 |
| Leak guard R1-R14 with counted allowlist and ratchet | BUILT BY SHIP 3a | §5 D7 |
| Dead-camera rule, option A at device level: device liveness, `page_camera_key`, `CameraTwinHealth` (NVR-only device twin map), house tracker for unwatched census / zone cameras, `physical_camera_dead`, page split; device-level readers (decided Q12) | BUILT BY SHIP 3b | §6 D6 |
| Dual-lens doorbell package channel counted as a device member | SPLIT TO CARD DUAL-LENS-PACKAGE-CHANNEL-MEMBERSHIP-1 | §6.0 |
| Census face reads (`last_recognized_face`) without stream health | SPLIT TO CARD CENSUS-FACE-READS-STREAM-HEALTH-1 | `camera_census.py:3903-3945` |
| Per-reader twin coverage (option B) | SPLIT TO CARD DEAD-CAMERA-TWIN-COVERAGE-1 (parked) | §14 Q11 |
| G6 rest (one BLE-in-room meaning, phone-left-behind filter on room occupancy, ~10 reader migrations) | SPLIT TO CARD G6-ONE-BLE-ROOM-READ-1 | contract §2.4a |
| BLE F5 producer gated by the HVAC pre-arrival switch | SPLIT TO CARD BLE-ARRIVAL-PRODUCER-HVAC-GATED-1 | `hvac.py:1241`, `person_coordinator.py:1170` |
| Nine inline `person.<slug>` id builders + `house_status` private id read | SPLIT TO CARD PERSON-ID-INLINE-SWEEP-1 | §9 |
| Census boot seed from a display entity | SPLIT TO CARD PRESENCE-BOOT-SEED-FROM-VIEW-1 | `presence.py:3280-3290` |
| G1 approach kind and non-resident edges | OUT OF SCOPE, owner STALE-SOURCE-ARRIVAL-CONSUMERS-1 | contract §5 G1 |
| `camera_egress` F5 sender, ArrivalNotifier, provenance constants, perimeter cache retirement (A6, A10-A13) | OUT OF SCOPE, owner EGRESS-DIRECTION-AWARE-IDENTITY-1 (step 7) | step 7 §14 |
| NVR witness W2: egress-camera health, non-W1 NVR pairs, pool-overhead's four integrations | OUT OF SCOPE, owner NVR-WITNESS-CONSOLIDATION-1 | `PLANNING_nvr_witness_layer.md` |
| Security census input (S5) | OUT OF SCOPE, owner operator decision (contract Q2, 4fc1b848: unwired, revival trigger recorded) | `security.py:283, 346` |
| Interior-vision unnamed sightings | OUT OF SCOPE, owner VISION-INTERIOR-SIGHTINGS-1 | `PLANNING_vision_interior_sightings.md` |

Open leaks after 3a and 3b, each with its card: §9 (34 leak groups; how they map onto guard rows is in §9; first-run rulings in §17).

## 1. Goals, decisions and the two ships

Charter goals this plan serves (operator, verbatim): "a consolidated boundary crossing and person awareness function
etc. That all consumers can [read] and producers can feed?"; "Unified functions or layers are powerful only if we get it
right and make sure there are no leaks"; "I assume if even one nvr has the cam it doesn't count as dead"; "A dead camera
is not a presence or absence of signal. Its faulty equipment"; "I need away to be fast acting" (hard constraint); "I
didn't want artificial seams that will sink us later". Operator on this plan, 2026-11-14: "Do it"; "Yes"; "Pull in the
dead camera fix"; "Most important thing to get right"; "Dig in and get this moving and get it right. All context needed
and reverifying producers and consumers"; "Make sure it's not a Frankenstein given drift ... Consistent from top to
bottom across what has been shipped and what remains."

Dead-camera rule, approved by the operator 2026-11-14 ("Smart. Do it"):
1. A stale NVR reading never counts. Delivered as: every dead input is held and then released by the S1 / S2 rules,
   now for the 10 person sensors on multi-camera devices that reach readers (9 Protect, 1 Reolink; device level, decided
   Q12) and for the census person-count / occupancy and zone camera entities no room watches. Not delivered: the
   census face reads (CENSUS-FACE-READS-STREAM-HEALTH-1). A twin input carrying the evidence instead (coverage) is
   parked as DEAD-CAMERA-TWIN-COVERAGE-1 (decided Q11).
2. A camera (a registry device) is dead only when every paired NVR device has lost it. Only that raises the HIGH
   camera-down and hold-released pages; one NVR down with the other covering gets the MEDIUM notice (§6.6, decided Q7).
   Charter drift #15 stays open for holds and the anchor, linked to DEAD-CAMERA-TWIN-COVERAGE-1.

**One plan, two ships: built in parallel, shipped in sequence (decided Q9).**
- **Ship 3a, layer plumbing (D0-D5, D7).** A provable no-op plus the leak guard. Tier 2-DB (operator-elevated).
- **Ship 3b, dead-camera rule (D6).** A deliberate behaviour change threaded through a shared primitive with ten
  readers. Tier 3.
- Batch 2 and census-p2 (with G7) are both live in v5.108.23, so every 3a deliverable and all of 3b can build now; the
  Q2 fallback was not needed.
- 3a ships first. 3b then rebases onto 3a, re-runs its tests and drills, and only then takes its Tier 3 reviews and the
  operator checkpoint. The 3b builder gets 3a's guard rules (§5 D7) up front so it adds no allowlist rows.
- Rule 2 holds for W1-paired cameras only. Non-W1 NVR pairs, including pool-overhead's four integrations, keep today's
  per-entity behaviour until NVR witness W2 (decided Q6).

Splitting keeps 3a's no-op proof clean; building in parallel means 3b is not delayed by 3a's reviews.

## 2. Institutional context verified

Read completely: CLAUDE.md; the charter; `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (b2 copy, incl. §10 #33, #34, #38,
#39; nothing re-asserted); `SENSOR_FLEET_CLASSES.md`; `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (b2 copy, incl. §10; relevant:
the 2026-11-14 header on the D6 stale-occupancy failsafe's Source 3, §3.2 "Readers that BYPASS the gate", §4.2b);
the contract; the audit; step 7 §6.3-§6.4, §8, §9 D0b, §14; step 8 §5.4. Skill `ura-arc` loaded. Identity manual §1,
§4.5 for W1 and the face latch.

### 2.1 REUSE / NEW per piece ("0" = `git grep` 0 hits in `custom_components` and `quality` on b2 and p2)

| Piece | Verdict | Evidence |
|---|---|---|
| `PersonArrivingPayload` | REUSED + EXTEND | `signals.py:28-69` |
| `dispatch_person_arriving`, `subscribe_person_arriving` | NEW (0) | raw sends `presence.py:5676-5680`, `:5935-5944`, `person_coordinator.py:1189-1193` |
| `register_face_latch_callback`, `face_latch_callbacks` | NEW (0), over the existing list | `person_sighting.py:148`, `:198`; `camera_census.py:5876` |
| Residency ledger + channel | REUSED | `residency.py:62-161`; p2 `presence.py:5291-5334` |
| `subscribe_person_edges`, `get_person_edges_since` | NEW (0) | |
| Ring, `get_crossings_since`, `get_crossing`, `door_camera_device_ids`, `door_entry_entities`, `door_neighbours_for_stem` | NEW (0) | owner `_door_group_for_stem` `transit_validator.py:1269`, `door_camera_stems` `:1295` |
| `attach_crossing_attribute`, `amend_crossing`, `_send_record_amended`, `SIGNAL_EGRESS_RECORD_AMENDED` | NEW (0) | |
| `location_moves_since`, `PersonMove` | NEW (0) | move site `person_coordinator.py:1093-1125` |
| `set_pre_arrival_enabled` | NEW (0) | private `person_coordinator.py:256` |
| `ZonePresenceTracker.note_face` | NEW (0) | private writes `person_sighting.py:666-667` |
| `min_confidence`, `census_view.view_for_class` | NEW (0) | table `const.py:6564`; rule today in `presence.py:6018-6041` |
| `get_person_previous_seen`, `async_add_listener` (contract read list) | REUSED | `person_coordinator.py:2235`; HA `DataUpdateCoordinator` |
| Person-id derivation at the BLE producer | REUSED | `_find_person_entity` `person_coordinator.py:1781-1795` (`tracked_person_entity_id`, then raw `person.<name>` fallback `:1792`, None if no state) |
| Exit-backfill channel | REUSED, DELETED by D3 | `SIGNAL_EGRESS_EXIT_BACKFILLED` `signals.py:83`; send `camera_census.py:5258-5271`; readers `sensor.py:4963-4971`, `:5117-5125` |
| Stream health (3b surface) | REUSED | `domain_coordinators/camera_stream_health.py`: `CameraInputStreamHealth` `:72`; S1 state rules `:224-260`; dead loop `:262-272`; S1 page decision `:293-310`; second decision `:332-364`, `is_unavailable_held` `:462-480`; S2 pages `:372-402`; camera getters `:423-460`; house getters `:508-668`; room wiring `coordinator.py:2621`, `:2641-2650`, `:2657-2691`, `:2728-2810`, `:2836-2860` |
| Ledger held path (3b surface) | REUSED | p2 `crossing_ledger.classify_held` `:107-139`; p2 `crossing_vision._held_inputs` `:1104-1180` |
| W1 pairing | REUSED | `CameraResolver._frigate_object_name_sibling` `camera_resolver.py:1672-1707`; switch `RESOLVER_FRIGATE_OBJECT_NAME_EVIDENCE` `:147`; only caller `resolve_capabilities` `:1129` |
| Device liveness helpers (`camera_device_for_entity`, `device_camera_members`), twin map, house tracker, `physical_camera_dead`, `CameraTwinHealth` | NEW (0) | W1 above; `own_camera_entity_for_input` `:818-879`; the house tracker reuses `CameraInputStreamHealth.evaluate` (`camera_stream_health.py:182-330`) |
| `own_camera_entity_for_device` | NEW, extracted | from `camera_resolver.py:818-879` |
| Knobs in §8 not marked existing | NEW (0) | `EGRESS_CROSSING_RING_*`, `PERSON_LOCATION_MOVES_*`, `CAMERA_STREAM_DEAD_TWIN_RULE`, `CAMERA_STREAM_UNWATCHED_STAMPS_ENABLED`, `CAMERA_STREAM_TWIN_COVERING_NOTICE_ENABLED`, `CAMERA_TWIN_MAP_REBUILD_DEBOUNCE_S`, `CAMERA_TWIN_HEALTH_TICK_S`, `CAMERA_STREAM_DEVICE_LEVEL_INPUTS`, `CAMERA_TWIN_BOOT_SETTLE_S`, `LAYER_ALLOWLIST_TOTAL` |
| Config-entry diagnostics download `diagnostics.py` | NEW (0 files) | D5's on-demand counters |
| `camera_stream_health.room_stream_input_entities(hass, entry)`, `PersonCensus.interior_camera_entities()`, `PresenceCoordinator.zone_camera_entities()` | NEW (0); a helper over the room config entry and the camera manager's area lookup, and public wrappers over existing lists | 3b's watched / unwatched sets (§6.3); today private: `PersonCensus._get_interior_camera_entities` `camera_census.py:2706` (develop), presence zone camera discovery `presence.py:5152-5216`, `hvac_zones.py:540-568` |
| `page_camera_key`, `fire_stuck_signal_ex` (`SENT` / `ALREADY_SENT` / `NOT_SENT`) | NEW (0) | one page key for rooms and the owner; send result that tells "already sent, not recovered" from "failed" (`_stuck_signal_nm.py:189-205` returns one bool today) |
| Guard | REUSED + EXTEND | `test_person_awareness_read_api_ship2.py:569`, controls `:598` |

No CONF_*, entity, config-flow field or DB column is added.

### 2.2 Prior art

Plans: contract §2-§6; audit §2, §5; step 7 §6.4 (ring and amend semantics, adopted verbatim); `PLANNING_census_deconfliction.md`
(G7, G8, residency channel); `PLANNING_nvr_witness_layer.md` §5 (W1); `PLANNING_camera_input_stream_health.md` (S1 measured
shape: Frigate `camera.<panel>` unavailable while its person sensor stayed `on` 14 h; INV-STREAM-ONE-GETTER);
`PLANNING_person_awareness_read_api.md` (ships 1-2); `PLANNING_vision_interior_sightings.md` (reads named sightings, no
second emit). Memory: `reference_identity_model_f1_f5`, `feedback_registry_not_name_guessing`,
`feedback_dead_sensor_is_faulty_equipment`, `feedback_suppression_needs_discharge`, `feedback_fire_check_and_forward_trace`,
`feedback_hollow_test_anchors`, `feedback_wire_in_anchor_mandatory`.

### 2.3 Config-first

No setting does any of this. The only dead-camera knob is `CAMERA_INPUT_STREAM_HEALTH_ENABLED` (all or nothing).

## 3. Producers and consumers per fact (re-verified on b2 and p2)

Class: access, security, house_state, comfort, notification, display. "Listed" = an allowed listener for the guard
(§5 D7 R10). "Row" = an allowlist row with its card (§9).

### F1 — P is home (level) and P's home/away edges

| Role | Site | Class / guard status |
|---|---|---|
| Level producer | `PersonTrackingCoordinator._async_update_data` (`.data`, `_gps_home_overruled`) | owner |
| Level push channel | `PersonTrackingCoordinator.async_add_listener` (HA coordinator update): `aggregation.py:2194, 5582, 5722, 6123, 6416, 6505, 6560` (display), `sensor.py:2974, 3072` (display), `security_lock_regime.py:1874` via `getattr` (access); step 8's music-following listener (comfort) reserved | listed: the nine display sites and step 8's reserved listener; row: lock (S3) |
| Edge producer | `presence._handle_geofence_change` `:5629` → `_feed_residency` (p2 `:5291`) → `ResidencyTracker.on_event`; push p2 `presence.py:5331` `SIGNAL_RESIDENCY_EVENT`, synchronous, before `handle_geofence_event` schedules inference | owner; edge ts float `_residency_clock()` |
| Direct AWAY triggers | `presence.py:9888, 9892` | house_state; never behind G1 |
| Edge listener | p2 `crossing_vision.py:417-421` (`@callback _on_residency_event` p2 `:1208`) | F2-A; moves onto G1 in D2 |
| Edge pull | `get_recent_resident_arrival` `presence.py:5516` (exterior severity, security), `get_residency_snapshot` `:5543` (display) | listed |
| Presence privates read by display | `sensor.py:6198` `_residency_residents`, `:6202` `_phone_left_behind_on` | row (owner_display) |
| Level trust reads | `persons_home_for_trust` (`hvac.py:3416, 3994`, `hvac_zones.py:2708`) | comfort / house_state; conforming |
| Raw person listeners | lock `_on_person_event` (access, S2), perimeter `perimeter_alert.py:1118` list + `:6226` + `_person_arrivals` (security, S7), security `_handle_person_state_change` and its added-domain person listener `security.py:2212` (access, S1) | rows |

### F2 — who is in the house now

| Role | Site | Class / guard status |
|---|---|---|
| Producer pair | `PersonCensus._apply_enhanced_house_census` + `_cross_validate_platforms` `camera_census.py:2395`; p2 `deconflict_house` | owner |
| Push | `SIGNAL_CENSUS_UPDATED` send `camera_census.py:1893`; listeners `presence.py:3219` (house_state), `binary_sensor.py:3389` (display), `sensor.py:3746` (display) | listed |
| Pull by literal view | `sensor.py:5239, 5254` (`UnidentifiedPersonsSensor`, display), `aggregation.py:6744, 6773` (`ZoneGuestCountSensor`, display), `binary_sensor.py:1953, 2001` (`URAUnexpectedPersonSensor`, display) | rows (§14 Q3) |
| Pull by class | `binary_sensor.py:2220, 2270` (`PersonPhoneLeftBehindSensor`, house_state) → `cls="house_state"` in D4; p2 `sensor.py:4224` (`_CensusAwarenessSensor`, `view_for_class("display")`) | conforming after D4 |
| Boot seed from a display entity | `presence.py:3280-3290` reads `sensor.<domain>_identified_persons_in_house` into `_census_count` | row (PRESENCE-BOOT-SEED-FROM-VIEW-1) |
| Stream-health term | census `_stream_view_set` `camera_census.py:2740-2758` (`entity_stream_view(..., census=True)`), called from the enhanced branch `:2043`, the single-source branch `:2227` and the Frigate-only `_get_unrecognized_camera_count` `:6225` (the source of `unidentified_count`) | 3b reader (§6) |

### F3 — door crossing and identity attach

| Role | Site | Class / guard status |
|---|---|---|
| Producer | `EgressDirectionTracker._resolve_direction`: bus fire `transit_validator.py:2214`, then `_record_crossing` `:2246-2263` in a `try` (failure logged at debug) | owner. Order kept: bus first, store second; D5 counts store failures; a bus listener must not expect the ring record yet |
| DB create | `transit_validator.py:2347` `log_entry_exit_event` | owner |
| BLE exit producer outside the tracker | `camera_census.py:5414` `async_track_state_change_event` on resident `bluetooth_le` trackers → `_on_crossing_tracker_state_change` (`:4904`) → `_backfill_exit_identity` (`:5087`) | row (EGRESS-DIRECTION-AWARE-IDENTITY-1) |
| DB amend after creation | `camera_census.py:5236` `backfill_entry_exit_person_id` | row (same card); its display signal moves onto G3 in D3 |
| Bus channel `ura_person_egress_event` | listeners `sensor.py:4819, 4950, 5060, 5110` (display), `person_sighting.py:151` and `crossing_vision.py:328` (p2 `:379`) through module-local constants `EGRESS_EVENT` (`person_sighting.py:56`, `crossing_vision.py:58`, p2 `:64`), `perimeter_alert.py:1110` (security, own 600 s cache) | listed; row: perimeter (S6, step 7 A12) |
| Amend channel `SIGNAL_EGRESS_RECORD_AMENDED` (new) | listeners: the two exit-backfill readers now; step 7 adds the four egress display sensors and the sighting producer (A5) | listed, A5 listeners pre-listed |
| Exit-backfill signal (retired in D3) | send `camera_census.py:5258-5271`; readers `sensor.py:4963-4971`, `:5117-5125` | D3 |
| Pull | `get_last_crossing` `presence.py:6043` (display) | listed |
| Door roster privates | `arrival_edges.py:335-336` (lock entry areas, access), `perimeter_alert.py:6005-6006` (security) | D3 removes |

### F4 — P seen at X at T

| Role | Site | Class / guard status |
|---|---|---|
| Camera ingest | face bridge → `hass.data[DOMAIN]["face_latch_callbacks"]` read `camera_census.py:5876` → `PersonSightingProducer._on_bridge` (registered `person_sighting.py:148`, removed `:198`) → `_emit` `:565` | owner; typed in D1 |
| Camera push | `SIGNAL_PERSON_SIGHTING` send `person_sighting.py:649`; zero listeners on b2 and p2 | listed: none (§14 Q5) |
| Sighting writes into the zone tracker | `person_sighting.py:666-667` `tracker._last_face_recognized` / `_last_face_time` | D4 replaces with `note_face` |
| Camera pull | `get_last_person_sighting` `presence.py:5987`: `binary_sensor.py:2246`, `sensor.py:3590` (display) | listed |
| BLE producer | `person_coordinator.py:1093-1125`, bus `ura_person_location_change` `:1110-1113` | owner |
| BLE bus listener | `transitions.py:93` (learning, display) | listed |
| BLE re-publish | `TransitionDetector.async_add_listener` `transitions.py:153`: root `music_following.py:211` (comfort), `__init__.py:3255` (Bayesian, display) | listed |
| BLE raw readers | room occupancy `coordinator.py:1385, 3315, 4440, 5003`; `binary_sensor.py:2204, 2293` `_is_room_occupied`; fan `fan_veto.py:309-330`; recheck `presence_fan_recheck.py:1375`; music root `music_following.py:538, 599, 659`; lock `security_lock_regime.py:1855-1892`; presence inference (~12 sites) | rows (G6-ONE-BLE-ROOM-READ-1; presence inference H2) |
| Previous-seen read (step 8) | `get_person_previous_seen` `person_coordinator.py:2235` | listed (contract read list, §12) |

### F5 — P is arriving

| Role | Site | Class / guard status |
|---|---|---|
| Producers | geofence `presence.py:5676-5680`; camera_face `:5935-5944` (`FACE_ARRIVAL_INTERIOR_ENABLED` False, ~0 live); BLE `person_coordinator.py:1189-1193` (`_find_person_entity`) | D1 moves all three onto G4 |
| Producer gate | HVAC pre-arrival switch `switch.py:4565-4571` → `hvac.pre_arrival_enabled` setter → `hvac.py:1241` writes `pc._pre_arrival_enabled` → gate `person_coordinator.py:1170` | 3a: setter swap, behaviour unchanged; scope fix BLE-ARRIVAL-PRODUCER-HVAC-GATED-1 |
| Listeners | `hvac.py:1511` (comfort), `domain_coordinators/music_following.py:282` (comfort), `security.py:819` (access) → `security.py:2393` → `security_lock_regime.py:1247` `on_person_arriving` (corroboration via `arrival_source_needs_corroboration`); the connect inside `subscribe_person_arriving` | listed |
| Planned | `camera_egress` sender (step 7 D8; the source is already in `CAMERA_DERIVED_ARRIVAL_SOURCES`, `const.py` p2 `:3486`, with no sender and not offered by HVAC), HVAC consumer (step 7 D5 / step 8), step 8 consumer through `subscribe_person_arriving` | reserved R13 feeder (step 7 D8) |
| Fire rate (contract §0a, 14 days) | geofence 152, BLE 68, camera_face 0 | D0 (b) re-measures and checks how many BLE arrivals duplicate a geofence arrival |

### Evidence service — camera stream health (the 3b surface)

| Role | Site | Today | Ship 3b |
|---|---|---|---|
| Room dead decision | `camera_stream_health.py:262-272` | per input, own camera entity (a sensor on a multi-camera device resolves to none: `multi_camera`) | per camera DEVICE (decided Q12); identical for an unchanged one-camera device (§6.2) |
| Second decision (held from t0) | `_classify_unavailable_inputs` `:332-364`, `is_unavailable_held` `:462-480`, view `:619-625` | per input | same code, device liveness; reused by the house tracker (§6.3) |
| S1 page | decided `:293-310` (skipped after the camera's S2 page, `:301-304`), sent `coordinator.py:2657-2671` | per input, HIGH, per-day latch | in-map groups and unwatched devices paged by the owner, same suppression and per-day latch (§6.6) |
| S2 hold page | `_evaluate_hold_pages` `:372-402`, sent `coordinator.py:2683-2691` | per camera entity, HIGH | in-map groups: HIGH only when every device is lost; else one MEDIUM (§6.6) |
| Flip set → substrate | `coordinator.py:2641-2650` → `_notify_substrate_stream_flips` `:2809` | dead / expired / newly-plain | same code, device-level sets (§6.2) |
| Camera getters | `camera_is_dead` `:423-432`, `camera_hold_expired` `:447-460`, `camera_stream_dead` `:544-563` | per entity | room getters answer per device for any member of that device (never a twin); house getters fall back to the house tracker only for entities in U ∪ sticky (§6.3) |
| Hybrid getters | `entity_stream_dead` `:566-586`, `entity_stream_view` `:633-658` | input route, else camera route | unchanged outside U and for one-camera devices |
| Readers | substrate `occupancy_substrate.py:346-369` and `_is_live_end` `:947-950` (`input_room_quarantined`); night limb `presence.py:4366-4374` + `_input_stream_released` `:9955-9962`; zone camera tier `presence.py:818-840, 975-984` + `_camera_entity_stream_view` `:9965-9972`; census `camera_census.py:2740-2758` (from `:2043`, `:2227`, `:6225`); ledger p2 `crossing_vision.py:1104-1171` / `crossing_ledger.classify_held` `:107-139`; Source 3 `presence.py:2467` (HVAC D6 stale-occupancy failsafe confirmation, `check_zone_occupancy_confidence` `:2375`); presence fan gate `presence.py:4326`, D4d `zone_hold_all_away` diagnosis label `:4546` (display, develop); `fan_veto.py:263` (motion leg) and `:462-476`; room camera-override consumer `coordinator.py:2742-2764`; house camera route `camera_stream_health.py:581`, `:653` (`own_camera_entity_for_input`); display snapshot `coordinator.py:2834`, `sensor.py:2125-2126` | | per-reader effects in §6.2 (measured) and §6.3 (unwatched); develop line numbers in §6 |

## 4. Falsifiable invariants

- **INV-3A-NOOP.** Ship 3a changes no dispatcher send (signal, payload equality, order, count), bus fire, DB row, actuator
  call, `_run_inference` call (trigger, count, order), entity state, or entity attribute, with two named exceptions: a new
  on-demand config-entry diagnostics download (D5; writes nothing), and the exit-backfill notice, which travels on
  `SIGNAL_EGRESS_RECORD_AMENDED` with a superset payload instead of `SIGNAL_EGRESS_EXIT_BACKFILLED` while its two readers
  produce identical states (D3). Falsified by any other golden difference.
- **INV-ONE-INGEST-AND-LISTENER.** After 3a, outside its owner nothing sends a person-awareness channel (§5 D7 R6),
  listens to one except its listed listeners (R10, incl. the two `async_add_listener` channels and module-local event
  constants), feeds an ingest function except its pinned feeders (R13), writes a `CrossingRecord` after creation, writes
  `_pre_arrival_enabled` on a person coordinator, reads the tracker's door privates, or touches the face-latch key; and
  the guard fails on any new instance not in the allowlist. Falsified by a guard-green tree containing one.
- **INV-AWAY-LATENCY (hard).** No await and no new hop is added before `_run_inference` on the geofence path. G1
  subscribers run synchronously inside `_feed_residency`, before `handle_geofence_event` schedules inference; each is
  sync, does no I/O and no loop over states, and a raising subscriber does not stop the inference task being created.
  Falsified by the golden inference replay count changing, or by
  `::test_g1_subscriber_raise_does_not_block_inference` failing.
- **INV-DEAD-INPUT (3b).** A camera is a registry device: live if any enabled camera entity on it reads live; dead on a
  tick only if no member is live, at least one reads `unavailable` (not restored) on that tick, and its dead-since stamp
  has passed the grace (§6.1 reader rule). Every dead input is held by the S1 / S2 rules (excluded at the room, held to
  its cap, then released; held from t0 when it went `unavailable` with its device). While held it neither creates nor
  ends occupancy (the zone keeps its prior level, the census its last available reading, which is frozen by
  definition); past its cap it is released (off / missing, never zero) and never counts its own frozen reading again. Outside the unwatched set U, for a device whose member set is one camera entity and unchanged, every
  room and house getter answers exactly as today, `unknown` and restored ticks included. For an entity outside U ∪
  sticky (§6.3), the house getters answer exactly as the rooms do. The reader rule ignores `unknown` / restored, the
  page loss rule counts them: a deliberate split. Readers always get their own device's answer, keyed by its own
  canonical camera, never a twin's. Named changes: the 10 multi-camera person sensors in the room camera override, 6 of
  them in the zone camera tier, the 7 Protect census entries (§6.2 table), a device whose enabled camera set changes (it
  is re-read and re-ruled), and the entities in U. Falsified by an unchanged one-camera-device answer differing
  outside U, an entity outside U ∪ sticky answered by the house tracker, a dead input's frozen reading counted PAST
  its cap, or a hold without a cap.
- **INV-DEAD-CAMERA (3b).** A group is a camera device plus its NVR-only W1 twin devices. `physical_camera_dead` is True
  only when every member device is LOST (not-live for the grace; a never-live member only after the boot settle). The
  owner pages only groups with a member some URA reader uses (Wr ∪ U); the 9 reader-less admitted pairs never page from
  3b. For such an in-map group, a HIGH is sent only while `physical_camera_dead` is True and the LATEST member's loss
  stamp + the cap has passed, at most one HIGH per group episode (S2; S1 only when both caps are 0); a send counts as
  sent when it was sent, or was already sent and not recovered (any date) under the same pure `page_camera_key` or an adopted member room S1 key; the key is frozen for the
  episode; the episode ends when the gate has been False for one grace, and whoever owns the outage then sends its
  LOW. A one-camera device watched by a room pages as today; the 3 unpaired multi-camera devices a room watches page
  per device (named new pages); a no-twin device in U pages like a room would (named new, none live). Falsified by a
  HIGH while any member is not lost, a HIGH earlier than the latest member's loss + cap, no HIGH in an episode where
  every member is lost past it (all members restored included), a page for a reader-less group, two HIGHs for one
  episode (across midnight, a handoff or the owner-absent window), a spurious LOW on a dissolve, a later same-day
  episode left silent by an uncleared latch, or a pairing not produced by W1's registry evidence with every camera
  entity of both devices on NVR platforms.
- **INV-ANCHOR (3b, decided Q8).** The ledger anchor code is unchanged from G7 (`crossing_vision.py:1168`): each Tier-1
  input's `entity_stream_view`, HELD or RELEASED blocks. No live Tier-1 input sits on a multi-camera device or in U, so
  no anchor answer changes; a future one would only block more. Falsified by the anchor firing over a dead, held or
  released Tier-1 input, or by any anchor decision on an unchanged one-camera-device input differing from G7.

## 5. Ship 3a deliverables (Tier 2-DB)

### D0: probe (read-only, `ssh ha "python3 -"`), before D2 and D6 build

(a1) Max residency records (`memory_episodes` `person_arrival`/`person_departure`) in any 1800 s window over 7 days.
(a2) Max `person_visits` room changes in any 1800 s window over 7 days (sliding window, so the process-local clock of
`person_visits`, presence §10 #32, does not matter). (b) F5 by source over 14 days; how many BLE arrivals have a
geofence arrival for the same person within 300 s. (c) Exit backfills from `_ble_exit_backfilled_count` on the census
diagnostics sensor (recorder). (d) and (e) are not 3b gates: (d) only decides DEAD-CAMERA-TWIN-COVERAGE-1's revival, and
(e) is answered in §13. (d) per W1-paired camera, 7 days: windows where one entity
read `unavailable` ≥ 120 s, with the dead input's state (frozen on / frozen off / unavailable), the twin camera's state,
and whether a readable same-class twin input sat in each reader set (Tier-1 map, zone camera list, census sets);
(e) what the twin map returns for pool-overhead and for the three ESPHome kiosk panels; (f) enabled camera entities per
device and the paths by which multi-camera sensors reach readers (done, §13; sizes §6.2). (d) is the probe that decides
DEAD-CAMERA-TWIN-COVERAGE-1's revival (§14 Q11).
- **Verify:** numbers in §13 before D2 / D6 build. If (a1) × 2 exceeds 32, D2 raises `RESIDENCY_RECENT_EVENTS` in the
  same build, and names that change as an INV-3A-NOOP exception (it changes `recent_arrival` / `last_of` answers only
  when more than 32 records fall inside their window); (a2) × 4 sizes `PERSON_LOCATION_MOVES_MAX` when larger than 256.
- **Test:** none. **Live:** none.

### D1: F5 ingest and read; typed F4 camera ingest

- `PersonArrivingPayload` gains `ts: Any = None` and `to_signal()`: keys `person_entity`, `source`; plus `sighting` and
  `zone` iff `sighting is not None`; plus `ts` iff not None. A plain dict literal (never `dataclasses.asdict`).
- `signals.dispatch_person_arriving(hass, payload)`: raises `ValueError` if `payload.source` is None or empty, then
  `async_dispatcher_send(hass, SIGNAL_PERSON_ARRIVING, payload.to_signal())`. The three sites call it; each keeps its
  observation-mode suppression; camera_face keeps `zone=sighting.house_zones[0] if sighting.house_zones else ""`; BLE
  keeps `_find_person_entity`.
- `signals.subscribe_person_arriving(hass, cb) -> unsub`: a `@callback` connect that calls `cb(PersonArrivingPayload)`;
  sync callbacks only. No user in 3a (step 8 is its first); the three existing listeners stay as listed.
- Face latch: `signals.register_face_latch_callback(hass, cb) -> unsub` and `signals.face_latch_callbacks(hass) ->
  tuple` over the SAME `hass.data[DOMAIN]["face_latch_callbacks"]` list (setup order unchanged). The reader returns a
  snapshot, exactly as `camera_census.py:5875-5877` does today with `list(...)`.
- **Verify:** the three dicts equal today's (geofence and BLE two keys; camera_face four keys, `sighting` the same
  object); the latch callbacks are called in the same order.
- **Discriminates:** a `to_signal` that always emits four keys passes reader tests but fails geofence dict equality.
- **Test:** `test_person_awareness_layer_ship3a.py::test_dispatch_person_arriving_payload_equal[geofence|ble|camera_face]`,
  `::test_to_signal_omits_unset`, `::test_to_signal_sighting_identity`, `::test_dispatch_rejects_missing_source`,
  `::test_observation_mode_still_suppresses[geofence|ble|camera_face]`, `::test_subscribe_person_arriving_payload`,
  `::test_face_latch_register_order_and_unsub`.
- **Migrated tests (assertions kept):** `test_person_sighting*.py` latch fixtures use the register function.
- **Live:** the next real geofence or BLE arrival writes the HVAC `pre_arrival` activity row with that source
  (domain evidence, primary); the diagnostics download shows `f5_sent` for that source ≥ 1.

### D2: F1 edges (G1, A1, A1b); crossing vision becomes the first G1 subscriber

- `residency.subscribe_person_edges(hass, cb, *, persons=None, kinds=frozenset({"arrival","departure"})) -> unsub`
  (module function, so subscribers need no presence object at setup) plus a presence delegate. The connected target is a
  `@callback` closure that filters and calls `cb(record)` inline (HA runs a non-callback target in the executor,
  `helpers/dispatcher.py:162-179, 245-251`). A coroutine function or an unknown kind raises `ValueError` at subscribe.
  Budget (INV-AWAY-LATENCY): callbacks are sync, O(1), and schedule any real work (crossing vision's callback already
  only schedules, p2 `crossing_vision.py:1209-1246`); guard R14.
- `persons` holds person entity ids (`ResidencyEvent.person`, e.g. `person.oji_udezue`).
- `PresenceCoordinator.get_person_edges_since(t: float, *, persons=None, kinds=...) -> tuple[ResidencyEvent, ...]`: a
  plain tuple, records with `edge_ts >= t`, oldest first, from `ResidencyTracker.recent`. `t` is epoch seconds (float),
  the unit of `edge_ts` (`_residency_clock`, p2 `presence.py:1868`). The shape is what step 7 A1 reads.
  `person_edges_truncated_since(t: float) -> bool` is True when the deque is full and its oldest `edge_ts > t`, OR when
  `t` is older than the tracker's creation (the deque is RAM, so after a restart or reload a "not full" answer does not
  mean complete); each True answer is counted in the `edges_truncated` diagnostics counter.
- Crossing vision's raw connect (p2 `crossing_vision.py:417-421`) becomes `subscribe_person_edges(self.hass,
  self._on_residency_event)`, all kinds, so every record is still delivered at the same time and in the same order.
- **Test:** `::test_person_edges_delivered_synchronously`, `::test_person_edges_callback_counted_flags`,
  `::test_person_edges_since_per_person_inclusive`, `::test_person_edges_since_plain_tuple`,
  `::test_person_edges_truncated_since`,
  `::test_subscribe_rejects_coroutine_and_unknown_kind`, `::test_geofence_triggers_unchanged`,
  `::test_g1_subscriber_raise_does_not_block_inference`, `::test_crossing_vision_residency_delivery_equal`.
- **Live:** on the next resident departure the crossing-vision ledger still writes its departure-reconcile row (domain
  evidence, primary); the diagnostics download shows `g1_subscribers` = 1.

### D3: F3 ring, reads, amend primitive, door roster (G2, G3, G5, A3, A4, A5, A9)

- Ring exactly as step 7 §6.4: `_crossing_ring[camera]` deques pruned by count and age on append and read; appended by
  `_record_crossing` after its two assignments; bus-then-store order and the `try` kept; a store failure is counted
  (`crossing_store_failed` diagnostics counter).
- Tracker reads, each with a presence delegate that never raises: `get_crossings_since(t: datetime, camera=None) ->
  tuple[CrossingRecord, ...]` (`t` a `datetime`, the type of `CrossingRecord.ts`; `ts >= t`, oldest first, merged
  across cameras when None; step 7's signature),
  `get_crossing(source_ref)`, `door_camera_device_ids()` (entity-registry `device_id` of each egress entity),
  `door_entry_entities()` (egress entities, then every configured neighbour, today's order),
  `door_neighbours_for_stem(stem)`.
- G5 exposes entities, not areas, because the lock and perimeter resolve areas with different functions; an area-level
  API would change one of them.
- `arrival_edges.door_entry_areas(tracker, area_of)` keeps its signature and reads `tracker.door_entry_entities()`; the
  lock still passes `hass.data[DOMAIN]["egress_tracker"]` (a member public read, row max 1), so the access path gains no
  presence dependency. Perimeter `_near_areas` calls `tracker.door_neighbours_for_stem(cam_key)`.
- `CrossingRecord` additive defaulted fields, no writer in 3a: `identity_role=None`, `nameable` (empty
  `MappingProxyType`), `pair_state=None`, `pair_partner=None`, `identity_synthetic_corroborated=False`.
- G3 `EgressDirectionTracker.attach_crossing_attribute(source_ref, changes, provenance, *, camera, role, row_id=None,
  payload_extra=None) -> bool`, semantics verbatim step 7 §6.4; keys `camera`, `direction`, `ts`, `source_ref`,
  `confidence` raise `ValueError`, and so does any key outside the writable set (the five additive fields plus
  `person_id`, `provenance`, `identity_confidence`); with `source_ref` None it amends nothing and returns False;
  `crossing_record_aged_out` counted only when a `source_ref` is given and not found. Every call, found or not, sends once through `transit_validator._send_record_amended(hass, payload)`, payload `{role, source_ref,
  row_id, person_id, egress_camera, **payload_extra}`.
- `transit_validator.amend_crossing(hass, source_ref, changes, provenance, *, camera, role, row_id=None,
  payload_extra=None)`: tracker in `hass.data[DOMAIN]` → its G3; no tracker → `_send_record_amended` only. No presence
  needed.
- Exit backfill: `camera_census._backfill_exit_identity` replaces its send with exactly `amend_crossing(self.hass, None,
  {}, provenance=None, camera=None, role="exit_backfilled", row_id=row_id, payload_extra={"person_id": slug})`, inside the
  existing `try`. The payload is built base keys first, then `**payload_extra`, so `person_id = slug` wins. Ring
  untouched. Readers (`sensor.py:4963`, `:5117`) connect to `SIGNAL_EGRESS_RECORD_AMENDED` and act on `role ==
  "exit_backfilled"`. `SIGNAL_EGRESS_EXIT_BACKFILLED` deleted.
- **Discriminates:** an amend that always rewrites `_last_crossing_by_camera` passes "found" but fails the clobber test;
  a backfill resolved to a ring record changes `get_last_crossing` and fails `::test_exit_backfill_ring_untouched`.
- **Test:** `::test_ring_prunes_by_count_and_age`, `::test_get_crossings_since_order`,
  `::test_ring_amend_does_not_clobber_newer`, `::test_g3_forbidden_keys`, `::test_g3_fires_once_found_or_not`,
  `::test_exit_backfill_display_equal[tracker|no_tracker|no_presence]`, `::test_exit_backfill_ring_untouched`,
  `::test_door_camera_device_ids_registry_only`, `::test_door_entry_areas_unchanged[lock|perimeter|no_presence]`,
  `::test_presence_f3_delegates_never_raise`, `::test_crossing_store_failure_counted`.
- **Migrated tests (assertions kept):** `test_egress_display_reread_and_tz.py` sends through `amend_crossing`.
- **Live:** Persons Exited Today still renames a backfilled exit on the next BLE departure with a null-person exit row
  (domain evidence, primary); the diagnostics download shows `g3_calls.exit_backfilled` ≥ 1.

### D4: owner setters, class reads, move log

- `PersonTrackingCoordinator.set_pre_arrival_enabled(value)`; `hvac.py:1241` calls it. Behaviour unchanged (a reloaded
  person coordinator still starts True whatever the HVAC switch reads; recorded on BLE-ARRIVAL-PRODUCER-HVAC-GATED-1).
- `ZonePresenceTracker.note_face(slug, when)`; `person_sighting.py:666-667` calls it (same two assignments).
- Move log at the one move site, same condition as the bus fire: `PersonMove(person_entity, from_room, to_room, ts:
  datetime, method="bermuda")`, a frozen NamedTuple, `person_entity = self._find_person_entity(person_name)` (the
  derivation the BLE F5 send uses; None → not logged, counted `move_unresolved_person`).
  `location_moves_since(t: datetime) -> tuple[PersonMove, ...]`: a plain tuple, `ts >= t`, oldest first, the shape
  step 7 A2 and step 8 §5.4 read; `t` and `ts` are the `datetime` the move site uses (`dt_util.now()`).
  `location_moves_truncated_since(t: datetime) -> bool` is True when the log is full and its oldest `ts > t`, OR when
  `t` is older than the log's creation (RAM; restart or reload) (counted in the `moves_truncated` diagnostics counter). Bounded by `PERSON_LOCATION_MOVES_MAX` / `_MAX_AGE_S`; presence delegates for both.
- `PresenceCoordinator.min_confidence(cls)` → table value or None.
- Census view (on the post-census-p2 tree): `house_census_view(hass, view="trust", *, cls=None)`. With `cls`, the view is
  `census_view.view_for_class(hass, cls)` (presence's method delegates to it: one rule) and `view` is ignored; with
  neither, `trust`. presence `get_house_census` delegates to it. `PersonPhoneLeftBehindSensor` (`binary_sensor.py:2220,
  2270`) passes `cls="house_state"` (always trust). Display callers keep `view="trust"` positionally (decided Q3).
- **Test:** `::test_hvac_toggle_reaches_person_coordinator` (asserts the person coordinator's flag, keyed on that
  receiver), `::test_note_face_equal`, `::test_location_moves_since_plain_tuple_inclusive`, `::test_location_moves_truncated_since`,
  `::test_location_moves_mirror_bus_event`, `::test_min_confidence_table`, `::test_census_view_positional_and_cls_equal`,
  `::test_census_view_cls_house_state_is_trust`.
- **Live:** after turning the HVAC pre-arrival switch off then on, the next BLE arrival writes an HVAC `pre_arrival`
  row with source `ble` (domain evidence: the person coordinator received the value); the diagnostics download shows
  `f5_sent.ble` ≥ 1.

### D5: diagnostics on demand (no new producer, no entity attribute)

`PresenceCoordinator.get_layer_diagnostics() -> dict` returns the counters: `f5_sent` by source, `g3_calls` by role,
`crossing_record_aged_out`, `crossing_store_failed`, ring sizes, move-log size, `move_unresolved_person`,
`g1_subscribers`, `edges_truncated`, `moves_truncated`. No entity attribute carries them: the candidate host
(`PresenceDiagnosticSensor`, `sensor.py:6559`) has `should_poll` False and is written once after boot, and making it
write on layer events would change how often its recorded attributes reach the recorder. The counters are read on demand
through a new config-entry diagnostics download (`diagnostics.py`, `async_get_config_entry_diagnostics`, coordinator-manager
entry, key `person_awareness_layer`); URA has no diagnostics module today (verified, 0 files). It writes nothing and
records nothing. 3a adds no producer, so no zero-fire trip-wire is due.
- The download returns ONLY the layer counters: no config-entry `data` or `options`, no entity states and no person
  coordinator `.data`. Config entries can hold credentials and API keys, so nothing from them reaches the file. Any
  later key added to this module goes through `async_redact_data` with an explicit redact list. Room and zone entries
  return an empty dict.
- **Test:** `::test_layer_diagnostics_counts` (one F5 send per source, one G3 call, one G1 subscriber move the counters),
  `::test_diagnostics_download_contains_layer`, `::test_diagnostics_download_has_no_config_entry_data` (a config entry
  whose data and options carry a fake token: the download contains neither the key nor the value).

### D7: the leak guard (R1-R14)

`quality/tests/test_person_awareness_layer_guard.py`, AST only: it parses source text and the string constants of
`const.py` and `signals.py`; it imports no production module. The existing census test
(`test_no_private_census_reads_outside_module`) becomes R1's first member and its 41 rows move into the allowlist.
"Member" = a person-awareness layer member class or module: PersonCensus, EgressDirectionTracker, TransitValidator,
PersonTrackingCoordinator, PersonSightingProducer, CrossingVisionShadow, CrossingLedger, PresenceCoordinator,
ResidencyTracker, ZonePresenceTracker (absent classes tolerated; harvest floor per present class), and their modules.

- **R1 private member access.** A Load, Store or Del of `_x`, or `getattr` / `hasattr` / `setattr` / `delattr` with a
  constant `"_x"`, where `_x` is in the harvested private set of a member class, outside that class's module; also
  `vars(x)[...]` and `x.__dict__` in a non-member module. Receiver-agnostic: the attribute name decides. A name that is
  also private on a non-member class is a `name_collision` hit; it is a leak row when the receiver resolves to a member
  (e.g. `binary_sensor.py:2204, 2293` `person_coordinator._is_room_occupied`, `hvac.py:1241` `pc._pre_arrival_enabled`)
  and a `name_collision` row otherwise (e.g. `hvac.py` `_ready_event`). Not hits: a read on a bare `self`; a read
  whose receiver resolves (by R10's value binding) to a non-member object, e.g. `camera_manager =
  hass.data[DOMAIN]["camera_manager"]` and its `_get_integration_camera_list` / `_get_interior_camera_entities`; and
  the house-state lifecycle flag `_boot_settle_done`, which is not an F1-F5 fact (excluded from the harvest by name,
  listed in `LAYER_NON_PERSON_PRIVATES`).
- **R2 store and member-method reads.** `.last_result`, `_last_sightings`, `_camera_sightings` on any receiver in a
  non-member module; `.data` / `getattr(x, "data")` only on a receiver bound (R10's value binding) to the person
  coordinator, in any module other than `person_coordinator.py`; `self.coordinator.data` in a `CoordinatorEntity` built
  with the person coordinator; and any call of a person-awareness PUBLIC method of a member that is not on the contract
  §4 read list (method names harvested per member class, minus the read list, minus `LAYER_NON_PERSON_PUBLIC`; e.g.
  `get_persons_in_room` from `sensor.py`). `LAYER_NON_PERSON_PUBLIC` holds member methods that answer no F1-F5 fact:
  `tracker_for_room`, `get_fan_last_transition`, `is_room_mmwave_fan_demoted`, `set_fan_interference_hold_s`,
  `set_house_state_override`, `get_house_state_override`, `get_house_occupancy` (house state, `presence.py:5544`),
  `get_next_state_prediction`, `is_room_direct_ble` and `get_ble_tier` (room scanner config), `path_map_status`,
  `get_stuck_cameras` (stream watchdog). Lifecycle calls are not hits: callees named `async_setup*`, `async_init`,
  `async_teardown`, `async_shutdown`, `async_unload*`, `rebind`, and the `__init__.py` setup / teardown wiring calls
  `register_ble_transition_listeners`, `async_register_frigate_face_listener`, `async_load_fleet_memory`,
  `async_cancel_pending_backfill_tasks`, `async_teardown_ble_transition_listeners`,
  `async_teardown_frigate_face_listener`.
- **R3 raw person-entity read.** `hass.states.get` / `async_all` / `async_entity_ids`,
  `async_track_state_change_event`, `async_track_state_change_filtered`, `Template(...)` /
  `async_track_template_result`, where the entity id or domain is tainted: a constant or f-string starting `person.`,
  `device_tracker.` or `sensor.bermuda`; domain `"person"`; any value from `tracked_person_entity_id(...)`;
  `async_get_entity_id(..., DOMAIN, uid)` with a person-awareness `uid` suffix (`_phone_left_behind`,
  `_camera_person_detected`, `persons_in_house`, ...); an `async_all()` result filtered by `.startswith("person." /
  "device_tracker." / "sensor.bermuda")`; a `CONF_*` person-list read; a string containing `states.person` or
  `is_state('person.`. Taint follows assignments, comprehensions and function returns inside one module. Not hits:
  (i) a person-domain read whose result is used only for `.entity_id` membership (a set of ids, never `.state` or an
  attribute value), e.g. the config-flow person picker and setup validation of configured person lists; (ii) actor
  identity, a person read filtered on `attributes["user_id"]` to name who pressed something; (iii) `sensor.bermuda_global_*`
  fleet-health entities (the `sensor.bermuda` taint covers per-person Bermuda sensors only); (iv) in a member module,
  raw `person.*` / `device_tracker.*` / Bermuda reads, which are layer-internal producer reads (contract §2.1, §2.7); in
  member modules R3 covers only URA person-awareness entity states.
- **R4 hass.data scan.** Any `.values()` / `.items()` iteration (loop, comprehension, `filter`, `map`) whose element
  reaches `getattr` / `hasattr` / `isinstance` / an attribute call with a member or stream-health name, whatever the dict's
  origin (`hass.data[DOMAIN]`, `_domain_data()`, a parameter). Owner row: `camera_stream_health._room_coordinators`.
- **R5 class literal.** `house_census_view(..., cls=)` / `get_house_census` / `view_for_class` / `min_confidence` called
  with anything but a string literal in `CONSUMER_CLASSES` (rejects Names, `functools.partial`, f-strings); a file whose
  literal class differs from the pinned per-file class map; any positional `view` literal, `"trust"` included (the six
  display callers are rows, §9 #6). The class set is read from the `CONSUMER_CLASS_*` constants in `const.py`. Owner
  delegates are not hits: `PresenceCoordinator.get_house_census` (passes its caller's view through) and
  `census_view.py` itself.
- **Residency channel value.** census-p2 is on develop, so R6 / R10 read `SIGNAL_RESIDENCY_EVENT` from the tree; the
  builder's temporary shim that read it from census-p2's text is removed.
- **R6 push-channel send.** `async_dispatcher_send` / `dispatcher_send` / `hass.bus.async_fire` / `hass.bus.fire` whose
  signal or event VALUE (resolved through `const` / `signals` constants, module-local constants and `import ... as`
  aliases) is one of: `SIGNAL_PERSON_ARRIVING` (owner `dispatch_person_arriving`), `SIGNAL_RESIDENCY_EVENT`
  (`_feed_residency`), `SIGNAL_CENSUS_UPDATED` (`camera_census`), `ura_person_egress_event` (`_resolve_direction`),
  `SIGNAL_EGRESS_RECORD_AMENDED` (`_send_record_amended`), `SIGNAL_PERSON_SIGHTING` (`PersonSightingProducer._emit`),
  `ura_person_location_change` (`PersonTrackingCoordinator`), outside its owner.
- **R7 store write.** Outside the owner: an Attribute or Subscript Store, `setattr`, `dataclasses.replace`,
  `__dict__.update`, or a constructor call of the record type (`CensusZoneResult`, `CensusResult`, `CrossingRecord`,
  `PersonSighting`) for `CensusZoneResult` count fields, `census.last_result`, `PersonTrackingCoordinator.data` (incl.
  `pc.data[p]["location"] = ...`), `_gps_home_overruled`, `_last_sightings`, the crossing ring, the crossing-vision row
  store and the residency ledger. G3 is the only `CrossingRecord` writer after creation.
- **R8 confidence threshold.** A comparison with a side naming `confidence` whose other side is not
  `CONSUMER_CLASS_MIN_CONFIDENCE[...]` / `min_confidence(...)`; in `const.py`, a confidence constant equal to a class
  threshold (0.75, 0.9) not allowlisted with its intent (seed: `BLE_TRANSITION_CONFIDENCE`, `CONFIDENCE_HIGH`,
  `FACE_MATCH_CORRELATED_BOOST`).
- **R9 person listener.** A listener over person entities outside `presence._handle_geofence_change` / `ResidencyTracker`:
  R3-tainted entity lists passed to a tracker wherever built; `EVENT_STATE_CHANGED` bus listeners whose callback reads
  `entity_id.startswith("person.")`; `async_track_state_added_domain(hass, "person", ...)`; a polling ledger (a dict keyed
  by person entity id, filled from states and compared on a timer) in a non-member module. The `sensor.bermuda_global_*`
  fleet entities are not person entities (as R3 (iii)).
- **R10 listener.** `async_dispatcher_connect`, `dispatcher_connect`, `bus.async_listen`, `bus.async_listen_once` on a
  channel VALUE (resolved as R6), plus `async_add_listener` on a receiver bound to `PersonTrackingCoordinator` or
  `TransitionDetector`. Receivers are resolved by value inside a function, not by name: any local or `self.<attr>`
  assigned from a person-coordinator source (`hass.data[DOMAIN]["person_coordinator"]`, `.get(..., "person_coordinator")`
  on that dict, `getattr(..., "person_coordinator")`, `manager.person_coordinator`) is bound, and so are the attribute
  forms `self.person_coordinator` and `self.transition_detector`; `getattr(<bound>, "async_add_listener")` counts. One
  hop (stated limit). Allowed only from the listed listeners in §3, pinned by `(file, qualified function, channel)`,
  never by line. `SIGNAL_RESIDENCY_EVENT` only inside `subscribe_person_edges`; `SIGNAL_PERSON_ARRIVING` from hvac,
  `domain_coordinators/music_following.py`, security and inside `subscribe_person_arriving`; `SIGNAL_PERSON_SIGHTING`
  none; `SIGNAL_EGRESS_RECORD_AMENDED` the two exit readers plus step 7's A5 listeners (pre-listed). Reserved listener
  (step 8 §5.4): music following's `async_add_listener` on the person coordinator.
- **R11 latch key.** Any non-docstring AST `Constant` equal to `"face_latch_callbacks"` outside `signals.py`, so a
  module-level alias (`KEY = "face_latch_callbacks"`) is also a hit.
- **R12 inline person id.** Outside `person_ids.py`: an f-string, `+` concatenation, `.format`, `%` formatting or
  `str.join` whose constant part starts `person.` (for `join`, a sequence whose first constant element is `"person"`
  joined by `"."`). Nine rows: `camera_census.py:4760, 4817, 5898, 6630`, `perimeter_alert.py:1118, 6226`,
  `person_coordinator.py:1792`, `person_sighting.py:605`, `transit_validator.py:2020` (PERSON-ID-INLINE-SWEEP-1); the
  `%` and `join` forms have 0 hits today.
- **R13 ingest feeders.** Every call of `dispatch_person_arriving`, `attach_crossing_attribute`, `amend_crossing`,
  `set_pre_arrival_enabled`, `register_face_latch_callback` and `note_face` is an allowlist row keyed
  `(R13, file, Class.method:callee)` with a `max`: `PresenceCoordinator._handle_geofence_change` and
  `PresenceCoordinator._derive_face_arrival` (dispatch, max 1 each), `PersonTrackingCoordinator._async_update_data`
  (dispatch, max 1), `EgressDirectionTracker.attach_crossing_attribute` callers in `transit_validator.py` (G3 internal,
  pinned by function at build), `PersonCensus._backfill_exit_identity` (amend, max 1), `HVACCoordinator.pre_arrival_enabled`
  setter (max 1), `PersonSightingProducer.async_setup` (register, max 1), the sighting writer of `note_face` (pinned by
  function at build). Reserved rows, pinned to the file with max 1 until the owning plan names the function: step 7 D8's
  `camera_egress` dispatch in `transit_validator.py`, the fast stage's G3 calls in `crossing_vision.py`.
- **R14 G1 callback budget.** A function passed to `subscribe_person_edges` in the same module contains no `await`, no
  `for` over `hass.states`, and no call to `hass.services.*`, `async_add_executor_job`, a `database.` method or the
  recorder. A callback defined in another module is not checked (stated limit).
- **Allowlist.** `(rule, file, symbol) -> {reason, card, max, reserved}`. `symbol` = the qualified name of the enclosing
  function, i.e. the chain of enclosing classes and `def`s joined by `.` (Python's `__qualname__` without `<locals>`),
  `<module>` at top level, a lambda attributed to its enclosing `def`; then `:` and the accessed name, channel or callee,
  e.g. `<module>:SIGNAL_PERSON_ARRIVING` or `Outer.method._inner:_is_room_occupied` for a hit inside a nested `def _inner`. The test fails
  on: an unlisted hit; a count over max; a stale row (a non-reserved row with 0 hits); or a row-max sum not EQUAL to
  `LAYER_ALLOWLIST_TOTAL`. Closing a leak therefore lowers the total in the same change; raising it is a contract change.
  Rows with `reserved: True` are exempt from the stale check, count in the total, and are reviewed when their owning plan
  ships or is parked (then they become ordinary rows or are removed). Reserved now: A12 perimeter
  `_note_egress_identity` cache read on the master-off path (max 1; a different row from today's full cache, §9 #10),
  A13 `transit_validator.freshest_gps_fix` R3 read (max 1), and the R10 / R13 reservations above.
- **Sizing (approximate AST dry run, 2026-11-14, of R1, R2, R11, R12 on b2 and p2; other rules from §3 and the audit's
  §2 table).** R1: 109 rows / 127 hits on b2, plus 2 `__init__.py` BLE-listener private reads p2 adds, plus 17 rows / 23
  hits of collision names resolved per receiver at build; most R1 rows are display reads of presence and census privates
  through `getattr` in `sensor.py` and `binary_sensor.py`. R2 by the dry-run regex (`person_coordinator.data` / `pc.data`):
  about 43 hits in 7 files (aggregation 14, sensor 9, binary_sensor 7, presence 5, camera_census 4, root
  music_following 3, house_status 1); other R2 receivers are counted at first run (§9). R11: 3 hits, 0 after D1. R12: 9.
  3a removes: 3 R6 sends (P1), 1 R1 write (P5), 4 R1 door reads (S4, S8), 1 R10 raw residency connect, 2 R1 sighting
  writes, 3 R11 hits. The build's first real run on the post-census-p2 tree produces the committed per-rule table and
  the pinned total. Any row this sizing and §9 do not explain stops the build and goes to the orchestrator; it is never
  pasted in.
- **Anti-hollow:** per rule, positive and negative snippets: helper-passed object, `vars()`, coordinator-manager reach,
  `_domain_data()` scan, Name view, `functools.partial`, aliased signal, module-local event constant, `bus.async_fire`,
  `setattr` / `dataclasses.replace`, `0.750`, template read, registry-resolved PLB id, polling ledger, raw connect,
  `async_add_listener` via `getattr`, via a `.get("person_coordinator")` local alias, and via `self.transition_detector`,
  latch key and its module-level alias, `+` / `%` / `join`-built person id, slow G1 callback, a nested-function hit keyed
  by its full qualified name, and a ratchet case (remove one hit, keep the total: red). Plus a per-rule minimum of
  real-tree hits, an injected-leak control on a copied clean module, and stated limits (dynamic `getattr(x, name_var)`,
  cross-module dataflow past one hop, `quality/` and `scripts/` not scanned).
- **Test:** the file, plus `::test_guard_red_on_reverted_site[p1_geofence|p1_camera|p1_ble|p5|s4|s8|exit_backfill|raw_residency_connect|latch_key|sighting_private_write|census_view_kwonly|missing_source]`.

## 6. Ship 3b deliverable (Tier 3): D6, the dead-camera rule (option A, decided Q11; device level, decided Q12)

3b cites are develop @ 06e88508 (v5.108.23 live: S1, S2, census-p2 with G7). Live registry figures are from plan
review A's probe (`.claude/tmp/rev35_probe.py`, recorded in §13 as D0 (f)).

### 6.0 What 3b delivers, and what it does not

- **Rule 2 (pages).** A physical camera is a registry DEVICE. It is reported dead only when every paired NVR device has
  lost it (§6.5, §6.6). Scope (default, the orchestrator is telling the operator): the owner pages only groups with a
  member device that some URA reader uses (a room input, a camera-override extra, a zone camera tier entry or a census
  entry: Wr ∪ U, §6.3). Not paged by 3b, owned by PERIMETER-RING-CAMERAS-STREAM-WATCH-1 and NVR witness W2: the 9
  admitted pairs no URA reader uses, back_yard, front_door_aerial, front_side_ptz, g5_bullet, hot_tub,
  madrone_g6_entry, pool_equipment, rear_ptz, utilities_ptz. New pages 3b does add: room S2 pages per device for the 3
  unpaired multi-camera devices a room watches (Garage Doorbell Lite, Camera_Protect_GarageHallway, Reolink TrackMix),
  and the MEDIUM twin-covering notice. Garage Doorbell Lite (room S2) and garage_a / garage_b (owner group pages) page
  because a room reads them: this is room-input health, not door-camera health, which stays with
  PERIMETER-RING-CAMERAS-STREAM-WATCH-1 (put to the operator at the checkpoint).
- **Rule 1 (holds).** Every dead input is held and then released by the existing S1 / S2 rules. 3b extends who gets them:
  - the 10 person sensors on multi-camera devices that reach readers today (9 Protect, 1 Reolink TrackMix), which
    resolve to no camera now (§6.2, decided Q12);
  - the census and zone camera entities no room watches (live: the foyer group, §6.3).
  The 10 multi-camera sensors reach the room camera override (all 10), the zone camera tier (6 of them, §6.2) and the
  census (7 Protect entries).
  No reader substitutes a twin's reading; per-reader coverage is parked as DEAD-CAMERA-TWIN-COVERAGE-1 (§14 Q11).
- **Not delivered (each carded or decided).**
  - Census face reads (`camera_census.py:3903-3945`, `last_recognized_face`, no stream-health term):
    CENSUS-FACE-READS-STREAM-HEALTH-1.
  - Non-W1 NVR pairs, including pool-overhead: per entity (decided Q6).
  - Dual-lens doorbells: the registry carries no field that marks a package channel (live
    `camera.madrone_g6_entry_package_camera`: `translation_key` None, `unique_id` `<mac>_3`; reading the `_3` suffix
    would be an undocumented string rule). So the package channel stays a device member, and a live package channel can
    mask a dead main lens. Carded as DUAL-LENS-PACKAGE-CHANNEL-MEMBERSHIP-1. Live effect today: none, because the one
    dual-lens device (Madrone G6 Entry) is read by no URA reader.
  - Charter drift #15 stays open for holds and the anchor, linked to DEAD-CAMERA-TWIN-COVERAGE-1; 3b closes it for pages.
- **Why device level (measured).** Frigate devices carry 1 enabled camera entity each (29 of 29). Protect devices carry
  1 (5 adopted third-party cameras), 2 (17), 3 (2) or 4 (1). Reolink TrackMix carries 2; Amcrest and Dahua 3 each;
  each ESPHome panel 2. The one-camera rule (`camera_resolver.py:866-879`) therefore answers `multi_camera` for every
  multi-channel device, so S1 / S2 watch none of their sensors today.

### 6.1 Device liveness (the one rule)

`camera_stream_health` gains pure helpers, used by the room trackers, the house tracker and the owner:
- `camera_device_for_entity(registry, entity_id) -> device_id | None`: the entity's registry `device_id`, if that device
  has at least one ENABLED `camera.*` entity. Never inferred from an entity-id string.
- `device_camera_members(registry, device_id) -> tuple[str, ...]`: the device's enabled `camera.*` entities, sorted. Read
  at resolution and re-read on every entity-registry invalidation (`coordinator.py:2836-2862`), so enabling or disabling
  a channel rebuilds the device's member set.
- `own_camera_entity_for_device(registry, device_id) -> str`: the device's own canonical member (first sorted enabled
  camera entity), extracted from `own_camera_entity_for_input`. The READER key: room dead-input maps, camera getters,
  exclusion reasons and diagnostics name the input's own camera, never a twin's.
- `twin_pair_for_device(registry, device_id) -> frozenset[device_id]`: a pure registry function, the same pairing rule
  the map build calls (W1 sibling, `_frigate_object_name_sibling`, plus the NVR-platform check, honouring
  `CAMERA_STREAM_DEAD_TWIN_RULE`). Computable with the owner absent.
- `page_camera_key(registry, device_id) -> str`: the PAGE key only, used at the five send and recover sites and nowhere
  else: the Frigate device's camera for a device that `twin_pair_for_device` pairs, else
  `own_camera_entity_for_device`. Pure, so rooms and the owner always agree, owner present or not. The owner's debounced
  map and the pure key can differ for one debounce window after a registry change, or after a failed rebuild that kept
  the old map; the owner keys its own pages with the pure function too, so the map is never a page-key source.
- **Episode-frozen key.** An outage episode records its page key when it starts and keeps it to the end. If a pair
  dissolves mid-episode (a rename or a platform change), the owner sends the LOW for the frozen group key and closes
  the episode; each former member then starts a fresh room episode under its own key. So a dissolve can give HIGH,
  LOW, HIGH in one outage (rare, named), never a spurious LOW while the old key is still latched.
- Per member reading: LIVE = a real state other than `unavailable` / `unknown`; DEAD-READ = `unavailable` without
  `restored: True`; NO-OPINION = `unknown`, restored `unavailable`, or no state.
- **Reader rule (holds).** A device's dead-since stamp starts on the first tick where no member is LIVE and at least one
  member is DEAD-READ; any LIVE member clears it; a stretch where every member is NO-OPINION keeps the stamp, and if it
  lasts longer than the grace, the next DEAD-READ restarts it (today's continuity rule, `camera_stream_health.py:245-256`).
  The device is dead ON A TICK only if, on that tick, no member is LIVE, at least one member is DEAD-READ, and the stamp is
  ≥ `CAMERA_INPUT_STREAM_DEAD_GRACE_S` (today's `:266` rule: an `unknown` or restored tick is never a dead tick). For a
  device whose member set is one camera and unchanged, this is exactly today's per-camera rule.
- **Loss rule (pages only).** A device's not-live-since stamp starts on the first tick where no member is LIVE
  (DEAD-READ and NO-OPINION alike); any LIVE member clears it. The device is LOST when that stamp is ≥ the grace, with one
  boot rule: a member that has been NO-OPINION since the owner's setup counts toward loss only after
  `CAMERA_TWIN_BOOT_SETTLE_S` (600 s) from setup.
- **Deliberate split (Bug Class #63).** The reader rule ignores NO-OPINION (a Frigate in setup retry never holds its
  inputs, as today: unknown is not dead); the loss rule counts it (so every NVR stuck in setup retry still pages). Do not
  align them. Pinned by `::test_reader_and_loss_rules_differ_on_restored`.

### 6.2 Room trackers and readers at device level (decided Q12, conditional on symmetry)

With `CAMERA_STREAM_DEVICE_LEVEL_INPUTS` True:
- `CameraInputStreamHealth._ensure_resolution` (`camera_stream_health.py:128-157`) resolves each watched input (configured
  inputs and camera-override extras) to its camera DEVICE; `evaluate` (`:182-330`) stamps per device with the reader rule;
  `dead[eid] = (own_camera_entity_for_device(device), since)`: the input's OWN camera, never the page key. The exclusion
  reason (`coordinator.py:2624-2627`) therefore names the input's own camera.
- The second decision (`_classify_unavailable_inputs` `:332-364`, today `camera_state.get(cam) != _UNAVAILABLE` at
  `:350`) uses one device value: the input is held from t0 only while its device is DEAD-READ this tick (no member LIVE,
  at least one member `unavailable` and not restored). A mixed set such as {restored, unavailable} or
  {unknown, unavailable} is DEAD-READ; {live, unavailable} is not. Liveness is looked up by the same device key it was
  stamped with.
- Room getters keep their signatures; `camera_is_dead(camera_eid)` / `camera_hold_expired` resolve their argument to its
  device and compare devices, so they answer for any member of THAT device and never for a twin.
- The house camera route (`entity_stream_dead` `:566-586` and `entity_stream_view` `:633-658`, which call
  `own_camera_entity_for_input` at `:581` and `:653`) resolves a non-input entity to its camera DEVICE and asks the rooms
  with `own_camera_entity_for_device(device)`, so it gets that device's own answer. No reader ever takes a twin's answer
  (option A).
- `page_camera_key` is used only where a page is sent or recovered (§6.6).

Measured effect (D0 (f)): no configured room input (72) sits on a multi-camera device. The multi-camera sensors reach
readers through three paths:

| Reader | Multi-camera sensors live | Today | 3b |
|---|---|---|---|
| Room camera override (`coordinator.py:2742-2764`, `_camera_override_live_person_sensors`, area match via `camera_census.py:1259`) | 10: Protect `camera_protect_garagehallway`, `doorbell_lite`, `family_room`, `garage_a`, `garage_b`, `master_hallway`, `playroom`, `stairs_top`, `upstairs_hall` `_person_detected`; Reolink `ptzcamreolinktmixpstudybporch_person` | a frozen `on` holds the room vacancy override | dropped from the override once its device is dead past the grace |
| Zone camera tier (`presence.py:809-845`, `:981` → `_camera_entity_stream_view` `:9970-9974`) | 6: Protect `family_room`, `master_hallway`, `playroom`, `stairs_top`, `upstairs_hall` `_person_detected`, and Reolink `ptzcamreolinktmixpstudybporch_person`. Not read: `camera_protect_garagehallway` (Garage Hallway opts out with `CONF_DISABLE_CAMERA_PRESENCE`), `doorbell_lite`, `garage_a`, `garage_b` (Garage A and B are in no zone); discovery `presence.py:5152-5216` | counted live; the zone empties after `_CAMERA_OCCUPANCY_TIMEOUT_SECONDS` when the sensor goes `unavailable` | held from t0 (updates ignored, `_camera_stream_ignored`), released (off) after 900 s |
| Census enhanced and single-source branches (`camera_census.py:2776`, `:2783` → `_stream_view_set` `:2785-2795`) | 6 watched Protect census entries; the foyer Protect entry through U (§6.3) | counted live, or missing when `unavailable` | held, then released; held from t0 when it goes `unavailable` with its device |
| Census `_get_unrecognized_camera_count` | Frigate-only | unchanged | unchanged |
| Room pages | the unpaired multi-camera devices: Garage Doorbell Lite, Camera_Protect_GarageHallway, Reolink TrackMix | none | NEW room S2 HIGH at the cap, per device, S1 key `(room, input)` as today; paired devices with a reader page through the owner (§6.6) |
| Substrate, night limb (`presence.py:4373`), presence fan gate (`:4326`), D4d `zone_hold_all_away` diagnosis label (`:4546`, display), ledger anchor, fan veto motion leg | none (Tier-1 = configured inputs) | — | no live change (latent: a future configured input on a multi-camera device would get the same rules) |
| HVAC D6 Source 3 | no multi-camera `zone_cameras` entry | — | unchanged |
| Display snapshot (`coordinator.py:2834`, `sensor.py:2125-2126`) | override extras are not configured inputs (`camera_stream_health.py:487-495`) | — | unchanged |

**Cost, stated for the operator.** A Protect or Reolink device that drops off the network while its person sensor sees a
body is now held in the census for up to the 900 s census cap (and held from t0). Today the reading is missing at once.
So AWAY through path α can be delayed by up to 15 min in that case, exactly as a Frigate camera already does today. In
the zone camera tier the same device's sensor now keeps its zone occupied for up to 900 s after the device drops,
where today the zone empties after the camera timeout.

**Symmetry check.** Grace, both caps, held-from-t0, release, pages, recovery and the reader list are the same constants
and code for Frigate and the multi-camera NVRs. Two differences remain, both named: liveness is "any enabled channel
live" for a multi-camera device and "the one stream live" for Frigate (identical meaning for a single-lens camera,
whose channels are encodes of one sensor on one link; the dual-lens doorbell residual is carded, §6.0), and
`_get_unrecognized_camera_count` reads Frigate only (pre-existing, unchanged).

`CAMERA_STREAM_DEVICE_LEVEL_INPUTS` False (the fallback if the operator withdraws Q12): room trackers and the house
camera route stay per entity exactly as today; the house tracker also resolves per entity; device liveness is used only
by the owner for pages and `physical_camera_dead`.

### 6.3 House tracker for cameras no room watches

- **Gate.** The owner computes no watched or unwatched set, and the house getters never consult it, until the camera
  manager (`hass.data[DOMAIN]["camera_manager"]`, created at `__init__.py:2938-2948`) is present and has discovered.
- **Watched set Wr.** The camera devices of every room's configured inputs plus its area's camera-override person
  sensors, computed by one helper, `camera_stream_health.room_stream_input_entities(hass, entry)`, over the room config
  entry and the camera manager's area lookup (`get_person_sensor_for_area`). The room tracker builds its watched list
  with the same helper. A reloading room keeps its config entry and the camera manager is not room-owned, so a room
  reload or first tick never moves a camera out of Wr. A runtime None answer is never used to classify.
- **Unwatched set U.** The person-count / occupancy entities read by the census interior readers (new public
  `PersonCensus.interior_camera_entities()`, the resolved list `camera_census.py:2706`, not the stored `camera.*` config
  ids) and by the zone camera tier and Source 3 (new public `PresenceCoordinator.zone_camera_entities()`), minus every
  entity whose camera device is in Wr. Recomputed on each owner tick by set comparison. An entity that leaves U stays
  in the house tracker's inputs for one grace (sticky), so a census reload or a registry rebuild that briefly empties the
  list never prunes a live stamp.
- **House tracker.** One `CameraInputStreamHealth` instance (room name `"<house>"`), called with `evaluate(now,
  inputs=U ∪ sticky, ...)` on each owner tick: the same stamp code, the same D-M1 held-from-t0 classifier, the same device
  rule. Reading `hass.states` each tick seeds a camera that is already dead; `evaluate`'s prune (`:224-230`) runs only
  after the sticky grace. The owner discards `evaluate`'s `to_page`, `hold_pages` and `hold_recoveries`; it pages only
  through §6.6.
- **Answers.** The house getters (`:529-668`) fold the room answers first, exactly as today. Only for an entity (or its
  device) in U ∪ sticky, and only when the fold is None, do they ask the house tracker.
- **Live effect.** U = the foyer group: Frigate `camera.foyer_fisheye`'s person sensor and Protect
  `binary_sensor.foyer_fisheye_person_detected` (census interior), plus `binary_sensor.foyer_fisheye_person_occupancy`
  (Entertainment `zone_cameras`, Source 3). No other census or zone camera is unwatched.
- **Residual.** A camera that moves from U into Wr (a room starts watching it) starts a fresh room stamp, so its grace and
  cap restart: a hold can extend by up to grace + cap, like the restart and reload residuals. The same holds for an
  entity that leaves U for longer than the sticky grace and comes back (fresh stamp).
- Kill switch `CAMERA_STREAM_UNWATCHED_STAMPS_ENABLED`.

### 6.4 `CameraTwinHealth`: owner, twin map, lifecycle

- One instance, created in `__init__.py` integration setup on the coordinator-manager entry, at
  `hass.data[DOMAIN]["camera_twin_health"]`. Its house tracker is a private attribute named so that no `hass.data` scan
  matches it (not `_camera_stream_health`, not `camera_input_stream_dead`); a guard test asserts the owner is never in
  `camera_stream_health._room_coordinators(hass)`.
- **Twin map, devices.** For each Frigate device with a W1 sibling (`_frigate_object_name_sibling`,
  `camera_resolver.py:1672-1707`), pair the Frigate device with the sibling device, both directions, only when every
  enabled camera entity on the Frigate device has registry `platform` `frigate` and every enabled camera entity on the
  sibling has `platform` in {`unifiprotect`, `reolink`, `amcrest`, `dahua`}, and each side has at least one enabled camera
  entity (so "every" is never vacuous). Live: 20 W1 pairs, 17 Frigate ↔ Protect
  admitted, 3 Frigate ↔ ESPHome panel rejected.
- **Rebuild.** A fresh `CameraResolver` per build. Triggers: `device_registry_updated` `create` / `remove`; an `update` on
  a device that has or had a camera entity; `entity_registry_updated` for the `camera` domain or for an entity on a mapped
  or candidate device. Filters evaluated at rebuild time; debounced by `CAMERA_TWIN_MAP_REBUILD_DEBOUNCE_S`; a sync
  `@callback`, no await. A build that raises keeps the previous map; the first build that raises leaves an empty map and
  is logged. A failed rebuild keeps the old map until the next trigger and sets `map_stale_since` (diagnostics, §6.9).
- **`map_ready`.** Set after the first attempted build, whether it succeeds or not. The owner exposes
  `is_map_candidate(device)` (has a W1 sibling) from the same build. While the owner is present and not ready, rooms
  defer pages for every in-scope device, bounded by `CAMERA_TWIN_BOOT_SETTLE_S`; past the bound they page as today. A
  deferred page sets no latch (`_hold_paged`, `_paged_episode`, `_paged_day`), so the page is sent once the deferral
  ends (latch-after-send, §6.6).
- **Teardown.** Pop `hass.data[DOMAIN]["camera_twin_health"]`; set `_torn_down` (checked first in the debounce callback
  and the tick); unsubscribe both registry listeners and the tick interval; cancel the pending debounce handle; clear the
  house tracker's state getter.

### 6.5 `physical_camera_dead` and the group gate

- Group = a camera device plus its twin devices (one member for a device with no twin).
- `physical_camera_dead(hass, entity_or_device) -> bool | None`: resolves to the device, then the group; True iff EVERY
  member device is LOST (§6.1 loss rule). Evaluated once per group.
- Readers: the pages and the diagnostics only. No hold, view or anchor reads it.

### 6.6 Pages

Today (`camera_stream_health.py:289-322`): S2 `camera_stream_hold_released` (HIGH, per camera, at min(positive caps) =
900 s) is evaluated first; S1 `camera_stream_dead` (HIGH, per input, at `CAMERA_INPUT_STREAM_DEAD_NM_AFTER_S` = 1800 s,
once per (room, input) per local day) is skipped for a camera that already sent S2 in the outage. One HIGH per outage.

- **Scope.** The owner pages only groups with a member device in Wr ∪ U (§6.0). A group with no reader sends nothing.
- **No twin, watched by a room:** the room tracker pages as today. A one-camera device is unchanged; the 3 unpaired
  multi-camera devices now page per device (named new pages, §6.2). Room S1 key `(room, input)` as today.
- **No twin, in U:** the owner pages it as a one-member group, same kinds, times, S2-suppresses-S1 rule and per-day S1
  latch as a room. A named new page; none live (the only U devices are an in-map pair).
- **In the twin map, with a reader:** room trackers send neither pages nor recoveries for the device; the owner pages
  the group. "In the map" on the room side is the owner's map (`is_map_candidate` / group membership), never the pure
  `twin_pair_for_device`, so an empty or failed map makes rooms page (no silent outage). When the map and the pure
  function disagree (a failed rebuild kept the old map), the group key is the Frigate member's `page_camera_key`.
  - **Group clock.** The group became fully lost at the LATEST member's not-live-since (its loss stamp, §6.1). HIGH S2
    on the first owner tick where `physical_camera_dead` is True and that latest not-live-since + min(positive caps) ≤
    now. So a short blip of the live twin while the other NVR has been dead for an hour sends no HIGH until the blip has
    itself lasted the cap. Both members restored since setup still page (both stamp at setup, after the boot settle).
  - **S1.** The owner sends S1 only when both caps are 0, at the latest not-live-since + `CAMERA_INPUT_STREAM_DEAD_NM_AFTER_S`,
    once per group per local day. With any positive cap the owner never sends S1, so `NM_AFTER` below the cap cannot
    produce two HIGHs. (Room trackers keep today's order unchanged.)
  - **Episodes.** A group episode starts when `physical_camera_dead` turns True and ends when it has stayed False for one
    grace. HIGH latches and the page key belong to the episode (frozen, §6.1). A member that stays dead never blocks the
    next episode.
  - **MEDIUM** `camera_stream_nvr_down_twin_covering`: once per member device episode, when that member's LOSS stamp
    (not-live-since, so a member stuck in setup retry counts after the boot settle) + min(positive caps) ≤ now while
    `physical_camera_dead` is False. The member episode ends when the member is live for one grace. Off with
    `CAMERA_STREAM_TWIN_COVERING_NOTICE_ENABLED` False. A twin flapping faster than the grace gives at most one MEDIUM /
    LOW pair per grace (accepted, notification log only, decided Q7).
  - **Owner texts.** HIGH S2: "Every NVR has lost <camera> for <minutes>; its URA inputs are released." MEDIUM: "<NVR> has
    lost <camera>; <other NVR> still sees it." LOW at an episode end: "<camera> is visible again on <NVR(s) now live>",
    adding "<NVR> still down" when a member is still lost. LOW on a dissolve: "<camera> is now watched per NVR; pages
    follow per device".
- **Send result.** A new `fire_stuck_signal_ex(...) -> SENT | ALREADY_SENT | NOT_SENT` in `_stuck_signal_nm.py`
  (`fire_stuck_signal` keeps its bool for existing callers). ALREADY_SENT is returned whenever `(kind, key)` is in
  `_STUCK_SIGNAL_NOTIFIED` (`_stuck_signal_nm.py:53`, `:238`), i.e. sent and not yet recovered, whatever the date; the
  `_LATCHES[key] == today` test alone is not enough (a room page at 23:59 and an owner tick at 00:01 would both send).
  The owner and the room trackers treat SENT and ALREADY_SENT as sent and NOT_SENT (NM missing, kill switch off,
  exception) as not sent (retry next tick). The recovery duty clears `_STUCK_SIGNAL_NOTIFIED`, so a later outage pages.
- **Latch after send (room trackers).** Today `evaluate` sets the S1 latches at decision time
  (`_paged_episode.add` / `_paged_day[eid] = today`, `camera_stream_health.py:308-309`) and the S2 latch inside
  `_evaluate_hold_pages` (`_hold_paged.add(cam)`, `:397`), before the coordinator sends (`coordinator.py:2654-2725`).
  3b moves all three writes out of `evaluate`: `evaluate` returns candidates only, and the coordinator calls a new
  `mark_paged(kind, eid_or_cam, today)` on the tracker after the sender returns SENT or ALREADY_SENT. A deferred page
  (owner not map-ready) or a NOT_SENT result sets nothing, so the candidate comes back next tick. The S1 duplicate
  checks (`:298-306`) and the S2 skip (`:388`) read the same three sets, so the decision logic is otherwise unchanged.
- **Keys.** Every page uses the pure `page_camera_key`: S2 key `(page_camera_key,)`; owner S1 key
  `("<group>", page_camera_key)`; room S1 key `(room, input)`. Because owner S1 and room S1 keys differ, the owner on
  start or takeover adopts any member device's room S1 key `(room, input)` found in `_STUCK_SIGNAL_NOTIFIED` as this
  episode's HIGH (no second HIGH), and recovers it at episode end.
- **Recovery duty.** Whoever owns the outage at its end sends the LOW, whoever sent the HIGH. The owner calls
  `fire_stuck_signal_recovered` at episode end for the group's S2 key and for any room S1 key `(room, input)` of a member
  device that a room sent during the owner-absent window (a no-op when nothing was latched). A device that leaves the map
  mid-episode: the dissolve rule in §6.1 applies (owner LOW, fresh room episodes).
- **Handoff.**
  - Owner absent (boot before CM setup, CM reload): room trackers page every watched device, in-map ones included, with
    the same pure key the owner will use; this window can page a HIGH while a twin is live (accepted, bounded by the
    reload).
  - Owner appears mid-outage: it evaluates the episode from the stamps; a room-sent S2 of the same key reads
    ALREADY_SENT (unrecovered, any date) and a room-sent S1 is adopted (Keys), so no second HIGH, before or after
    midnight.
  - Entry reload keeps the module-level `_LATCHES`; an HA restart clears them, so a group still dead after a restart can
    page once more.

### 6.7 Kill-switch matrix

| `CAMERA_INPUT_STREAM_HEALTH_ENABLED` | `CAMERA_STREAM_DEAD_TWIN_RULE` | `CAMERA_STREAM_UNWATCHED_STAMPS_ENABLED` | Result |
|---|---|---|---|
| False | any | any | no exclusion, no hold, no page; room getters False, house fallback None (as today) |
| True | False | False | today, plus device-level inputs (and their room pages) if `CAMERA_STREAM_DEVICE_LEVEL_INPUTS`; no owner pages, no house tracker |
| True | False | True | house tracker for U; the owner pages U one-member groups; no twin map; rooms page every watched device |
| True | True | False | twin map and group pages; no house tracker; U answers None |
| True | True | True | full 3b |

- `CAMERA_STREAM_DEVICE_LEVEL_INPUTS` False: per entity as today in every row; the owner still uses device liveness.
- Caps both 0: S2 never fires; S1 does; no hold expires, so no MEDIUM. Override extras never page S1 (`:298-299`), so the
  3 unpaired multi-camera devices (reached only as extras) do not page at caps 0, as Frigate extras today.
- `CAMERA_INPUT_STREAM_DEAD_NM_AFTER_S` 0: no S1.
- `CAMERA_STREAM_TWIN_COVERING_NOTICE_ENABLED` False: no MEDIUM.

### 6.8 Inputs, readers and the ledger

Every dead input is held by the S1 / S2 rules; the second decision keeps every hold capped; no reader substitutes a
twin's reading. The ledger anchor code is unchanged from G7 (`crossing_vision.py:1168` on develop); no Tier-1 input sits
on a multi-camera device or in U live, so its answers do not change.

### 6.9 Diagnostics

Pairs (admitted / rejected), Wr and U sizes, sticky entries, house-tracker stamps, group and member episodes, latches,
send results and page counts, `map_stale_since`, in the D5 config-entry diagnostics download under `camera_twin_health`. No entity
attribute.

### 6.10 Tests, drills and build notes

Fixtures use real registry shapes: Frigate devices with one camera entity; Protect devices with 2, 3 and 4 enabled
channels; a Reolink device with 2; ESPHome kiosk devices with ONE and with TWO camera entities (the live shape; for the platform check).

**Tests** (`test_camera_twin_health.py`):
- device liveness: `::test_device_live_if_any_channel_live`, `::test_device_dead_needs_every_channel[two|four]`,
  `::test_one_camera_device_rule_unchanged` (golden incl. an `unknown` tick and a restored tick past the grace),
  `::test_member_set_change_rebuilds_device_rule`, `::test_loss_counts_restored_after_boot_settle`,
  `::test_reader_and_loss_rules_differ_on_restored`;
- device-level readers: `::test_protect_override_sensor_dropped_when_device_dead` (2-channel device),
  `::test_protect_zone_camera_tier_held_then_released`, `::test_protect_census_entry_held_from_t0`,
  `::test_watched_device_non_input_entity_answers`, `::test_device_level_off_is_today`;
- house tracker: `::test_watched_camera_getters_unchanged[camera_stream_dead|camera_stream_hold_expired|entity_stream_dead|entity_stream_view|input_stream_view]`,
  `::test_room_reload_window_answers_today`, `::test_no_house_answers_before_camera_manager`,
  `::test_unwatched_census_camera_held_then_released`, `::test_unwatched_unavailable_with_camera_held_from_t0`,
  `::test_unwatched_dead_before_owner_setup_is_stamped`, `::test_unknown_blip_does_not_restart_stamp`,
  `::test_unwatched_set_flicker_keeps_stamp`, `::test_camera_leaving_unwatched_set_pruned_after_grace`,
  `::test_unwatched_source3_foyer_skips_dead_camera`, `::test_unwatched_set_from_public_reads`,
  `::test_house_tracker_pages_discarded`, `::test_owner_not_in_room_coordinators`;
- twin map: `::test_twin_map_multi_channel_protect`, `::test_twin_map_rejects_non_nvr_sibling`,
  `::test_twin_pairing_registry_only`, `::test_twin_map_fresh_resolver_per_build`, `::test_twin_map_built_once_per_invalidation`,
  `::test_twin_map_boot_storm_bounded`, `::test_twin_map_rebuilt_on_device_rename`, `::test_twin_map_rebuilt_on_new_device`,
  `::test_failed_rebuild_keeps_old_map`, `::test_failed_first_build_rooms_page`, `::test_rooms_defer_until_map_ready_bounded`;
- gate and pages: `::test_physical_dead_requires_every_device[twin_live|twin_lost|twin_restored_after_settle|twin_unknown|twin_missing]`,
  `::test_twin_blip_under_grace_no_high`, `::test_staggered_deaths_clock`, `::test_one_high_per_outage[caps_900|caps_0]`,
  `::test_s1_page_silent_while_twin_live` (room path), `::test_owner_s1_silent_while_twin_live[caps_0|caps_900]`,
  `::test_s2_page_silent_while_twin_live`, `::test_s1_page_fires_when_both_lost`,
  `::test_both_nvrs_setup_retry_pages_after_settle`, `::test_twin_dies_after_medium_pages_high[watched|unwatched]`,
  `::test_permanently_dead_twin_does_not_mask_next_outage`, `::test_medium_once_per_member_episode`,
  `::test_low_on_episode_end`, `::test_latch_not_set_when_send_fails`, `::test_suppressed_by_shared_key_not_resent_after_midnight`,
  `::test_room_paged_then_owner_takeover_next_outage_pages`, `::test_device_leaves_map_room_sends_low`,
  `::test_room_then_owner_same_device_one_dispatch` (owner ABSENT at the room's page, present at takeover; the room
  watches the Protect member),
  `::test_pair_dissolves_mid_outage_no_spurious_low`, `::test_twin_blip_after_long_outage_no_early_high` (group clock on
  the latest member), `::test_owner_s1_never_with_positive_cap`, `::test_reader_less_group_never_pages`,
  `::test_medium_for_member_in_setup_retry`, `::test_owner_page_texts`,
  `::test_camera_getter_never_answers_for_twin`, `::test_classifier_mixed_members[restored_unavailable|unknown_unavailable|live_unavailable]`,
  `::test_twin_map_rebuilt_on_camera_enable_disable`, `::test_unwatched_no_twin_pages_like_room`,
  `::test_owner_after_midnight_reload_no_second_high` (CM reload 23:58, room S2 at 23:59, owner back 00:01),
  `::test_owner_adopts_room_s1_key_caps_0`, `::test_not_sent_retries_next_tick[s1|s2]`,
  `::test_deferred_page_not_marked_hold_paged[s2|s1_caps_0]`, `::test_member_set_change_rebuilds_device_rule[enable_while_dead]`,
  `::test_twin_map_requires_a_camera_each_side`, `::test_failed_rebuild_sets_map_stale_since`, `::test_dissolve_low_text`,
  `::test_owner_reload_mid_outage_no_false_high`, `::test_no_twin_pages_as_today`;
- switches and lifecycle: `::test_kill_switch_matrix[...]` (every §6.7 row and bullet), `::test_unload_mid_debounce_no_rebuild`;
- readers: `::test_dead_inputs_held_as_today[substrate|census|ledger]`.

**Mutation drills** (framing C; each edits one existing or 3b-built site; restore and `git status` clean):
- M1 house fallback consulted outside U (fixture: the room fold returns None and a stale house stamp sits on an entity just past its sticky grace) → `::test_watched_camera_getters_unchanged[camera_stream_dead]`;
- M2 remove the house fallback → `::test_unwatched_census_camera_held_then_released`;
- M3 drop the D-M1 classifier from the house path → `::test_unwatched_unavailable_with_camera_held_from_t0`;
- M4 count a `restored: True` twin as live → `::test_physical_dead_requires_every_device[twin_restored_after_settle]`;
- M5 drop the NVR-platform check (one-camera AND 2-camera ESPHome fixtures, so the rejection comes from the platform) → `::test_twin_map_rejects_non_nvr_sibling`;
- M6 drop the device-registry listener (rename only, through the listener) → `::test_twin_map_rebuilt_on_device_rename`;
- M7 filter at event time → `::test_twin_map_rebuilt_on_new_device`;
- M8 owner S1 gate removed → `::test_owner_s1_silent_while_twin_live[caps_0]`;
- M9 owner S2 gate removed → `::test_s2_page_silent_while_twin_live`;
- M10 HIGH latch set on the MEDIUM send → `::test_twin_dies_after_medium_pages_high[unwatched]`;
- M11 room trackers keep paging in-map devices (fixture group in the map AND with a reader; counts dispatches on two consecutive days) → `::test_s1_page_silent_while_twin_live`;
- M12 remove the debounce (several events inside one window, no clock advance between them) → `::test_twin_map_boot_storm_bounded`;
- M13 remove the MEDIUM latch → `::test_medium_once_per_member_episode`;
- M14 skip one-member groups → `::test_unwatched_no_twin_pages_like_room`;
- M15 latch from the bool (failed and latched cases, across midnight) → `::test_suppressed_by_shared_key_not_resent_after_midnight` and `::test_latch_not_set_when_send_fails`;
- M16 end episodes only when every member is live → `::test_permanently_dead_twin_does_not_mask_next_outage`;
- M17 drop the LOW on episode end → `::test_low_on_episode_end`;
- M18 drop the twin grace in the loss rule → `::test_twin_blip_under_grace_no_high`;
- M19 per-entity resolution kept with device-level on (2-channel override fixture) → `::test_protect_override_sensor_dropped_when_device_dead`;
- M20 house tracker without the tick-time state read → `::test_unwatched_dead_before_owner_setup_is_stamped`;
- M21 room-side `_classify_unavailable_inputs` looks liveness up per entity under device level → `::test_protect_census_entry_held_from_t0`;
- M22 page clock on the reader stamp → `::test_both_nvrs_setup_retry_pages_after_settle`;
- M23 drop the DEAD-READ-this-tick term → `::test_one_camera_device_rule_unchanged`;
- M24 drop the boot settle (the test asserts NOT lost at 599 s and lost at 601 s + grace) → `::test_loss_counts_restored_after_boot_settle`;
- M25 unbounded `map_ready` deferral → `::test_failed_first_build_rooms_page`;
- M26 a failed rebuild clears the map → `::test_failed_rebuild_keeps_old_map`;
- M27 pair with the one-camera rule → `::test_twin_map_multi_channel_protect`;
- M28 reuse the resolver across builds (a registry rename lands between the two builds) → `::test_twin_map_fresh_resolver_per_build`;
- M29 no sticky grace on U → `::test_unwatched_set_flicker_keeps_stamp`;
- M30 compute U before the camera manager exists → `::test_no_house_answers_before_camera_manager`;
- M31 room key from its own member, not `page_camera_key` (fixture: the room watches the PROTECT member) → `::test_room_then_owner_same_device_one_dispatch`;
- M32 owner skips the LOW for a page it did not send → `::test_room_paged_then_owner_takeover_next_outage_pages`;
- M33 house camera route stays per entity (fixture: a non-input entity on an IN-MAP multi-camera device) → `::test_watched_device_non_input_entity_answers`;
- M34 each new kill switch ignored in turn → `::test_kill_switch_matrix[...]`: `CAMERA_STREAM_DEAD_TWIN_RULE` ignored → row 3 (owner pages in-map groups), `CAMERA_STREAM_UNWATCHED_STAMPS_ENABLED` ignored → row 4 (U answers), `CAMERA_STREAM_DEVICE_LEVEL_INPUTS` ignored → the device-level-off bullet, `CAMERA_STREAM_TWIN_COVERING_NOTICE_ENABLED` ignored → its bullet;
- M35 `page_camera_key` reads the owner's map instead of `twin_pair_for_device` (room watches the PROTECT member; the map is stale) → `::test_room_then_owner_same_device_one_dispatch`;
- M36 no episode-frozen key on dissolve → `::test_pair_dissolves_mid_outage_no_spurious_low`;
- M37 group clock from the earliest member → `::test_twin_blip_after_long_outage_no_early_high`;
- M38 `dead[eid]` carries the page key → `::test_camera_getter_never_answers_for_twin`;
- M39 the house tracker forwards its pages → `::test_house_tracker_pages_discarded`;
- M40 drop the `_torn_down` check in the debounce callback → `::test_unload_mid_debounce_no_rebuild`;
- M41 room-side recovery after a device leaves the map skipped → `::test_device_leaves_map_room_sends_low`;
- M42 entity-registry camera enable / disable not a rebuild trigger → `::test_twin_map_rebuilt_on_camera_enable_disable`;
- M43 reader scope dropped (owner pages every admitted pair) → `::test_reader_less_group_never_pages`;
- M44 MEDIUM on the reader stamp → `::test_medium_for_member_in_setup_retry`;
- M45 room latch set in `evaluate` at decision time (today's shape) → `::test_deferred_page_not_marked_hold_paged[s2|s1_caps_0]`;
- M46 latch on NOT_SENT → `::test_not_sent_retries_next_tick[s1|s2]`;
- M47 `_ex` from `_LATCHES == today` only → `::test_owner_after_midnight_reload_no_second_high`;
- M48 owner does not adopt member room S1 keys → `::test_owner_adopts_room_s1_key_caps_0`;
- M49 device stamps keyed by the canonical camera → `::test_member_set_change_rebuilds_device_rule[enable_while_dead]`;
- M50 room-side "in map" from the pure function → `::test_failed_first_build_rooms_page`.

**Build notes (most likely builder errors, ranked by the final plan review).**
1. Latching in `evaluate` and gating only the send: latches are set by `mark_paged` after SENT / ALREADY_SENT (§6.6; M45,
   M46).
2. Room-side "in map" from the pure function: use the owner's map; an empty or failed map makes rooms page (M50).
3. Device stamps, prunes and liveness keyed by the canonical camera: key them by `device_id`; only `dead[eid]` carries
   `own_camera_entity_for_device` (M49).
4. `fire_stuck_signal_ex` from `_LATCHES` only: ALREADY_SENT is "in `_STUCK_SIGNAL_NOTIFIED`", any date; the owner adopts
   member room S1 keys (M47, M48).
5. Computing `page_camera_key` from the owner's map, or in `evaluate`, or writing it into `dead[eid]`: pure, send-site
   only (M35, M38).
6. Pruning house stamps on U churn: the sticky grace runs before `evaluate`'s prune.
7. Naming the house tracker attribute so a `hass.data` scan finds the owner: the guard test catches it.
8. Mixing device and entity keys between `evaluate` and `_classify_unavailable_inputs`: M21.
9. Running the page clock off the reader stamp: M22.
10. A one-camera fixture for a Protect test (the §10 #41 trap): every Protect fixture has 2+ channels; ESPHome has a
    2-camera case too.
11. Hollow-drill fixtures: M31 / M35 have the room watch the Protect member; M1 uses a None room fold; M11 a mapped group
    with a reader.
12. The twin filter needs at least one enabled camera on each side; a failed rebuild sets `map_stale_since`; the
    dissolve LOW has its own text.

**Live:**
- During the next Frigate-only outage on a W1-paired camera with a reader (Playroom, Master Hallway, Upstairs Hall,
  Stairs top or Family Room): no HIGH; one MEDIUM `camera_stream_nvr_down_twin_covering` at the cap; the D5 diagnostics
  download shows the group, both devices' loss stamps and the MEDIUM latch.
- When `camera.foyer_fisheye` goes `unavailable`: the diagnostics download shows the foyer entries in U with a house
  stamp past the grace, and the zone status attribute for the Entertainment zone shows D6 Source 3 no longer counting
  `binary_sensor.foyer_fisheye_person_occupancy`.
- The next disconnect of a zone-tier Protect device (one of the five above) while its zone is occupied: the zone tracker
  lists the sensor in `_camera_stream_ignored` (diagnostics download) and the zone stays occupied past
  `_CAMERA_OCCUPANCY_TIMEOUT_SECONDS`, up to 900 s, then releases. Without 3b the zone empties at the camera timeout, so
  this discriminates.

## 7. Emission and decision sites, and forward trace

### 7.1 Sites (reviewers and the orchestrator re-grep these before each ship)

F5 sends `presence.py:5678, 5937`, `person_coordinator.py:1191`. Residency send `presence.py:5331`, listener
`crossing_vision.py:419` (census-p2 lines; both now on develop). Exit backfill `camera_census.py:5265-5270`, `sensor.py:4968, 5122`. Latch `person_sighting.py:148,
198`, `camera_census.py:5876`. Sighting private writes `person_sighting.py:666-667`. `_pre_arrival_enabled` `hvac.py:1241`.
Door privates `arrival_edges.py:335-336`, `perimeter_alert.py:6005-6006`. Census view §3 F2. `_record_crossing`
`transit_validator.py:1040`, call `:2246`. Move site `person_coordinator.py:1095-1113`. Listener channels §3 F1/F4.
Stream health §3 evidence table, plus the flip set `coordinator.py:2641-2650`, page senders `coordinator.py:2657-2671,
2683-2691` (develop: S1 `:2654-2681`, S2 `:2690-2725`), the room camera-override consumer `coordinator.py:2742-2764`, the house camera route
`camera_stream_health.py:581`, `:653`, and `_stuck_signal_nm.py:189-205` (send result) / `:292-302` (recovery).

### 7.2 Forward trace (each seam to the actions it can reach)

| Seam / reader | Reaches access? | Reaches house_state? | Direction vs today |
|---|---|---|---|
| G4 F5 send (3a) | yes, lock and security, unchanged listeners | no (HVAC pre-arrival is comfort) | same |
| G1 edges (3a) | no | no (ledger is F2-A display; presence's own AWAY triggers stay direct) | same |
| G2 / G3 / A3 / A9 / G5 (3a) | lock entry areas via G5, same set | no | same |
| Move log, `min_confidence`, census view by class (3a) | no | PLB sensor (AWAY input) through `cls="house_state"`, same trust view | same |
| 3b pages (`physical_camera_dead`) | no | no (notifications) | for groups with a reader: no HIGH while a twin is live (fewer), a MEDIUM instead; new room S2 pages for the 3 unpaired multi-camera devices; the 9 reader-less pairs page nothing |
| 3b device-level readers (decided Q12): 10 override sensors, 6 of them zone-tier, 7 census entries | no | yes: room camera override, zone camera tier and census feed room occupancy, nobody-home, SLEEP and paths α / β | a dead device's frozen reading is dropped from the override and held to 900 s in the zone tier and census, then released; AWAY via path α can wait up to 15 min while a held body counts |
| 3b house tracker, foyer census and Entertainment zone camera | no | yes (census) and HVAC D6 via Source 3 | held then released instead of counted live; D6 stops resetting on a dead foyer camera |
| 3b, one-camera devices outside U | no | no change | same |

## 8. Knobs

| Name | Rung | Value | Why / kill |
|---|---|---|---|
| `EGRESS_CROSSING_RING_PER_CAMERA` | 1 | 32 | step 7 §6.4 (peak 9 per 30 min); ≥ 1 |
| `EGRESS_CROSSING_RING_MAX_AGE_S` | 1 | 1800 | ≥ 900 + 120 + caller delay; a test asserts it |
| `PERSON_LOCATION_MOVES_MAX` | 1 | 256, or D0 (a2) × 4 if larger | house-wide |
| `PERSON_LOCATION_MOVES_MAX_AGE_S` | 1 | 1800 | matches the ring |
| `RESIDENCY_RECENT_EVENTS` (existing, `const.py:4075`) | 1 | 32 unless D0 (a1) × 2 exceeds it | now a window for A1; truncation flagged |
| `CAMERA_STREAM_DEAD_TWIN_RULE` | 1 | True | operator rule 2; False = no twin map, no owner group pages; rooms page every watched device (with device-level inputs on, that includes the 3 unpaired devices' new S2 pages) |
| `CAMERA_STREAM_UNWATCHED_STAMPS_ENABLED` | 1 | True | operator rule 1 for unwatched cameras; False = they answer None as today |
| `CAMERA_STREAM_TWIN_COVERING_NOTICE_ENABLED` | 1 | True | the MEDIUM notice (decided Q7); False = no notice |
| `CAMERA_TWIN_HEALTH_TICK_S` | 1 | 30 | the owner's tick (house tracker, U recompute, pages), one room poll |
| `CAMERA_STREAM_DEVICE_LEVEL_INPUTS` | 1 | True (decided Q12) | room trackers and the house camera route resolve to devices; False = per entity as today, device level for pages only |
| `CAMERA_TWIN_BOOT_SETTLE_S` | 1 | 600 | a member never live since setup counts toward loss only after this; pages both-NVRs-in-setup-retry |
| `CAMERA_TWIN_MAP_REBUILD_DEBOUNCE_S` | 1 | 10 | bounds the boot registry-event storm to one build |
| `LAYER_ALLOWLIST_TOTAL` | test const | first real run, post-census-p2 | must EQUAL the row-max sum; closing a leak lowers it in the same change; raising it is a contract change |

## 9. Leaks still open after 3a and 3b (each with its card; §14 Q10)

Columns: the guard rule that pins the group, and its rows (or hits) from the §5 D7 dry run; "first run" = the count is
fixed by the build's first real run; "unguarded (card only)" = a real leak no rule can see (logic inside an owner
module, a policy, or a public read the rules do not cover), tracked by its card alone.

| # | Fact | Leak group | Rule(s) | Rows / max | Card |
|---|---|---|---|---|---|
| 1 | F1 | Security geofence own `person.*` listeners (S1; `security.py:2212` + resubscribe) | R9 | 2 | STALE-SOURCE-ARRIVAL-CONSUMERS-1 |
| 2 | F1 | Lock regime second edge ledger + raw listener (S2) | R9 | 1 | LOCK-REGIME-BOOT-REALLY-AWAY-1 (LOCK restart plan) |
| 3 | F1 / F4 | Perimeter third ledger, raw `person.*` read, `pc.data` (S7) | R9, R3, R2 | 1 + 1 + first run | STALE-SOURCE-ARRIVAL-CONSUMERS-1 |
| 4 | F1 | `sensor.py:6198, 6202` presence privates (display) | R1 | 2 | PERSON-AWARENESS-READ-API-1 (owner_display) |
| 5 | F2 | Boot seed from a display entity (H1) | R3 | 1 | PRESENCE-BOOT-SEED-FROM-VIEW-1 |
| 6 | F2 | Six display census callers on a literal view | R5 | 6 | crossing-vision Phase 2 promotion (`PLANNING_crossing_vision.md`) |
| 7 | F2 | Census privates read by census display sensors | R1 | 41 | PERSON-AWARENESS-READ-API-1 (owner_display) |
| 8 | F2 | `_cross_validate_platforms` own platform classifier (P3) | unguarded (card only) | 0 | NVR-WITNESS-CONSOLIDATION-1 (W5b) |
| 9 | F2 | Security census input unwired (S5) | unguarded (card only) | 0 | operator decision, contract Q2 |
| 10 | F3 | Perimeter's full 600 s egress cache and its bus listener (S6), today | R10 | 1 | EGRESS-DIRECTION-AWARE-IDENTITY-1 |
| 11 | F3 | Egress provenance stored on the census (P2) | unguarded (card only) | 0 | EGRESS-DIRECTION-AWARE-IDENTITY-1 |
| 12 | F3 | Arrival/departure notify inside the producer (N1) | unguarded (card only) | 0 | EGRESS-DIRECTION-AWARE-IDENTITY-1 (A10) |
| 13 | F3 | Census BLE exit producer outside the tracker (`camera_census.py:5414`) | R9 | 1 | EGRESS-DIRECTION-AWARE-IDENTITY-1 |
| 14 | F3 | Census DB amend `camera_census.py:5236` | unguarded (card only) | 0 | EGRESS-DIRECTION-AWARE-IDENTITY-1 |
| 15 | F3 | Step 7 reserved rows: A12 perimeter cache read on the master-off path; A13 `freshest_gps_fix` | R1 / R10, R3 | 1 + 1 (reserved) | EGRESS-DIRECTION-AWARE-IDENTITY-1 (A12, A13) |
| 16 | F3 | Lock passes the egress tracker object to `door_entry_areas` | unguarded (card only) | 0 | PERSON-AWARENESS-READ-API-1 |
| 17 | F3 | Transit `_count_platforms_fired` substring classifier (P4) | unguarded (card only) | 0 | NVR-WITNESS-CONSOLIDATION-1 (W2) |
| 18 | F3 | Perimeter `_apply_single_source_gate` family classifier (S11) | unguarded (card only) | 0 | NVR-WITNESS-CONSOLIDATION-1 (W2) |
| 19 | F3 | Perimeter census legs / roster reads (S9, S10) | R2 (member public outside §4) | first run | EGRESS-DIRECTION-AWARE-IDENTITY-1 |
| 20 | F4 | Room occupancy raw BLE-in-room (C6, C7, C8; `coordinator.py:1385` via `getattr` is unguarded) | R2 (member public outside §4) | 3 (+1 unguarded) | G6-ONE-BLE-ROOM-READ-1 |
| 21 | F4 | `binary_sensor.py:2204, 2293` `_is_room_occupied`; PLB `pc.data` (H4) | R1 (collision name, person receiver), R2 | 2 hits + 1 | G6-ONE-BLE-ROOM-READ-1 |
| 22 | F4 | Fan veto `pc.data`, fan recheck `_area_id_to_room` + slug fallback (C3, C5) | R2, R1 | first run + 1 | G6-ONE-BLE-ROOM-READ-1 |
| 23 | F4 | Music `person_coord.data` (C4, root `music_following.py`) | R2 | 3 | G6-ONE-BLE-ROOM-READ-1 |
| 24 | F4 | Lock `record_bermuda_moves(pc.data)` + update listener (S3) | R2, R10 | first run + 1 | G6-ONE-BLE-ROOM-READ-1 |
| 25 | F4 | Presence inference `pc.data` + PLB twin (H2) | R2 | 5 | G6-ONE-BLE-ROOM-READ-1 (H2 part needs its own Tier-3 review) |
| 26 | F4 | Display `pc.data` loops and raw BLE-in-room display reads (aggregation, sensor, house_status, `binary_sensor.py`; D4, D5, D8; `get_persons_in_room` `sensor.py:3004, 3023, 3099`, `get_room_occupants` `binary_sensor.py:555`) | R2 | 30 `.data` hits (aggregation 14, sensor 9, binary_sensor 6, house_status 1) + 4 member-public calls | G6-ONE-BLE-ROOM-READ-1 |
| 27 | F4 | Census `_get_ble_persons` `pc.data` (H5) | R2 | 4 | G6-ONE-BLE-ROOM-READ-1 |
| 28 | F4 | TransitValidator legacy camera store (H6) | R2 | first run | PERSON-AWARENESS-READ-API-1 |
| 29 | F4 | Fan veto reads URA camera entity state (C1) and room fusion integration count (C2) | R3 (C1); C2 unguarded | first run | NVR-WITNESS-CONSOLIDATION-1 (W5c) |
| 30 | F5 | HVAC switch gates the BLE arrival producer (policy; no code hit after D4) | unguarded (card only) | 0 | BLE-ARRIVAL-PRODUCER-HVAC-GATED-1 |
| 31 | ids | Nine inline `person.<slug>` builders, `house_status.py:237` `_find_person_entity`, and the notification manager's raw `person.*` display-name read (`notification_manager.py:4763`) | R12, R1, R3 | 9 + 1 + 1 | PERSON-ID-INLINE-SWEEP-1 |
| 33 | F1-F4 | Member-to-member private reads: census `presence._zone_trackers` (`camera_census.py:2508`), presence `person_coordinator._lost_away_since` (`presence.py:8087`), person coordinator `presence._ble_leads_enabled` (`person_coordinator.py:524`), sighting producer `_face_arrival_cooldown` / `_face_recognition_enabled` / `_zone_trackers` (`person_sighting.py:612, 532, 664`) | R1 | 6 | PERSON-AWARENESS-READ-API-1 |
| 34 | F4 | Display entities write the person coordinator's previous location on restore: `seed_previous_location` (`aggregation.py:6404`), `seed_previous_location_time` (`aggregation.py:6488`) | R2 | 2 | PERSON-AWARENESS-READ-API-1 |
| 32 | F1-F4 | Presence-coordinator, census and zone-tracker privates read for display or by other coordinators (fan state, consensus, guest stay, wake / arriving counters, face fields; `sensor.py`, `binary_sensor.py`, `coordinator.py`, `hvac.py`, `__init__.py`, `coordinator_diagnostics.py`, `manager.py`, `presence_fan_recheck.py`), plus non-person `name_collision` rows and two census setup-wiring reads in `__init__.py` | R1 | about 62 rows + about 15 collision rows | PERSON-AWARENESS-READ-API-1 (owner_display / name_collision) |

Counts from the guard's first real run (builder, `feature/layer-ship3a` 888a58d7) after the §17 rulings: 285 rows /
max-sum 317 found; 33 rows (max-sum 37) were false positives and are removed by the rule fixes in §5 D7; 14 rows (max-sum
14) are public reads moved to the contract read list (§12). Applying the §17 exclusions exactly as written also drops 5
rows §17 had left standing: `_boot_settle_done` in #32 (`coordinator.py` ×2, `presence_fan_recheck.py`, `sensor.py`
`PresenceHouseStateSensor`) and the census's own `get_stuck_cameras` display read in #7. That leaves 233 rows, max-sum
261, before the six R2 lifecycle-wiring rows are removed (§5 D7 R2); pinned at build: `LAYER_ALLOWLIST_TOTAL` =
<final max-sum>, reported by the builder. Plus 28 listed listeners (R10 list, not rows). 13 first-run rows were real leaks and are placed
above: #33 (6), #34 (2), #26 (+4), #31 (+1). The dry-run estimates the earlier sizing used (about 107 R1 rows, about 43
R2 `.data` hits, 9 R12) are superseded by these counts. Unguarded groups: #8, #9, #11, #12, #14, #16, #17, #18, #30
(9 groups), plus single unguarded sites inside #20 and #29.

Closed by BLE-PERSON-SENSOR-REGISTRY-RESOLVE-1 (in batch 2): the Bermuda-sensor-by-name read in aggregation (audit D3).
Cleanup is sized and sequenced in `docs/planning/PLANNING_person_awareness_leak_cleanup.md` (decided Q10). Order to
close (recommended): 30 (before v6.0.0, operator pick A), 20-27 (G6-ONE-BLE-ROOM-READ-1, parallel with step 7),
10-15 and 19 (step 7), 1-3 (STALE-SOURCE / LOCK), 31, 5, 8 and 17-18 and 29 (W2/W5), 4, 6, 7, 16, 28, 32 (display,
last), 33 and 34 (with READ-API follow-ups). Row 9 stays open by operator decision until its revival trigger.

## 10. Non-goals

No consumer migrations beyond crossing vision onto G1. No approach kind or non-resident edges. No G6 rest. No change to
the HVAC switch's scope. No `_arrival_departure_notify` move, no provenance constants, no `camera_egress` sender. No
non-W1 NVR pairing, no egress-camera health. No security census wiring. No AWAY trigger change. No reordering of bus and
store in `_resolve_direction`. For an unchanged one-camera device outside U, no change to the answers of
`entity_stream_dead`, `entity_stream_view`, `camera_stream_dead`, `camera_is_dead`, `camera_hold_expired`,
`input_stream_view`, `input_stream_dead` or `input_room_quarantined`. No per-reader twin coverage
(DEAD-CAMERA-TWIN-COVERAGE-1, parked). No stream health for census face reads (CENSUS-FACE-READS-STREAM-HEALTH-1). No
package-channel exclusion (DUAL-LENS-PACKAGE-CHANNEL-MEMBERSHIP-1). No second F1 store: approach kind and non-resident
edges (STALE-SOURCE) go in a separate deque, so `recent_arrival` stays byte-identical.

## 11. Sequencing, seams and review

Order: **batch 2 and census-p2 with G7 (both live in v5.108.23) → 3a and 3b build in parallel → ship 3a → rebase,
review and ship 3b → step 7.** G6-ONE-BLE-ROOM-READ-1 dispatches
when 3a merges and runs in parallel with step 7 (decided Q1).
- D4's census-view part is written against develop, where census-p2's rebase reconciled `census_view.py` with its
  `get_house_census`.
- Q2's fallback (3a carrying `SIGNAL_RESIDENCY_EVENT`) was not needed: census-p2 landed first.
- 3b changes no ledger code; its INV-ANCHOR proof runs against the post-G7 tree, so G7 is its precondition.
- The orchestrator re-greps the §7.1 sites before each ship, and re-runs one mutation per 3a ingest site (D1 send, D3
  G3 send, D4 setter) before 3a ships.
- BLE-PERSON-SENSOR-REGISTRY-RESOLVE-1 seam (merged in batch 2 at 9114d2a0): it rewrote the Bermuda resolver, added the
  public `get_bermuda_resolve_stats` (`person_coordinator.py:1918`) and deleted `aggregation._find_bermuda_sensors`. This
  plan cites both files after the merge. The move site and `_find_person_entity` are unchanged in behaviour. D7 lists
  `get_bermuda_resolve_stats` on the contract read list if a non-owner reads it.

| Seam | Other plan | Resolution |
|---|---|---|
| F1 channel + G1 | census-p2, LOCK restart, STALE-SOURCE | channel owner `_feed_residency`; G1 the only connect |
| Ring, G2, G3, A3, A9, G4, G6 pull, record fields | step 7 D0b / D1 | built here at step 7's signatures; step 7 D0b becomes "verify present" |
| G3 attribute roles | crossing-vision fast stage | uses G3 after rebasing on census-p2 |
| Stream health | census-p2 G7, NVR witness W2, DEAD-CAMERA-TWIN-COVERAGE-1 | 3b adds device liveness, `CameraTwinHealth`, the house tracker and `physical_camera_dead`; G7 stays a pure swap; coverage stays parked |
| `subscribe_person_arriving`, `location_moves_since`, music `async_add_listener` | step 8 | step 8's F5 read, moves pull and reserved listener |
| `camera_egress` F5 feeder | step 7 D8 | reserved R13 feeder in `transit_validator.py` |

Review:
- **3a, Tier 2-DB:** plan re-review (completeness + framing G); build reviews A (byte identity, per-site), B (async,
  lifecycle, `@callback` delivery, setup order, AWAY latency), C (per-site mutation on every D1-D4 site and every
  reverted-site guard case).
- **3b, Tier 3:** a Tier 3 plan re-review of §6 first (completeness + framing G + adversarial build prediction). Build
  reviews in four framings: A (one-camera-device answers byte-identical, device liveness truth table, page timing and
  episodes), B (registry listeners, debounce, teardown, owner tick, latch-on-send, handoff, HVAC D6 Source 3 for U),
  C (drills M1-M50), D (diff-blind re-enumeration of every `camera_stream_health` caller, pre-existing ones included,
  with legal repros against a registry that has multi-channel Protect devices). The orchestrator re-greps every caller
  and re-runs M1, M9, M15, M16, M19, M22, M31, M35, M37, M45 and M47 before ship. Operator checkpoint before deploy.

## 12. Doc write-backs (same commit as each build)

Read shapes and time types, written the same way in every plan that consumes them:

| Read | Returns | `t` |
|---|---|---|
| `get_person_edges_since(t, *, persons, kinds)` | plain tuple of `ResidencyEvent`, `edge_ts >= t`, oldest first; truncation via `person_edges_truncated_since(t)` | float epoch seconds |
| `location_moves_since(t)` | plain tuple of frozen `PersonMove(person_entity, from_room, to_room, ts, method)`, `ts >= t`, oldest first; truncation via `location_moves_truncated_since(t)` | `datetime` |
| `get_crossings_since(t, camera=None)` | plain tuple of `CrossingRecord`, `ts >= t`, oldest first; no truncation read: it covers at most `EGRESS_CROSSING_RING_MAX_AGE_S` (1800 s), 32 records per camera, and only since the tracker's creation (RAM) | `datetime` |

- Contract (3a): §4.2 channel table with owners and listed listeners (incl. `SIGNAL_RESIDENCY_EVENT`, the two
  `async_add_listener` channels, module-local `EGRESS_EVENT`); §4.1 read list adds `async_add_listener`,
  `get_person_previous_seen`, the three reads above with their shapes and units, the two truncation methods,
  the public reads ruled legitimate at the guard's first run (§17): person coordinator `get_person_confidence`,
  `get_persons_in_zone`, `get_tracked_person_count`, `get_person_previous_location`,
  `get_person_previous_location_time`, `get_diagnostic_data` (display class), presence
  `should_veto_due_to_reliable_signals` (comfort / house_state, zone fallback) and `check_zone_occupancy_confidence`
  (comfort, HVAC D6 confirmation),
  `subscribe_person_arriving`; G5 = `door_entry_entities` / `door_neighbours_for_stem`; G3 sender `_send_record_amended`
  and `amend_crossing`; F4 camera ingest = the typed latch; G1 callback budget; §2.6 evidence-service row for the twin
  rule (3b).
- Step 7 (3a): A1 and A2 return shapes and units as above (on truncation, fall back to the live state read); `>=`
  includes the cursor record, so dedupe it; A9 "next to G5 `entry_areas`" → `door_entry_entities`; D0b → verify
  present. Exact conversions at step 7's call sites (`t_E` and `crossing_ts` are `CrossingRecord.ts`, a `datetime`;
  perimeter `edge` is a `datetime`, `perimeter_alert.py:5846`):
  - §5 K5 partner edges (step 7 l.349): `get_person_edges_since(t_E.timestamp() - 120, persons={partner},
    kinds={"arrival"})`;
  - §5 K5 partner moves (l.350): `location_moves_since(t_E - timedelta(seconds=120))`;
  - own-confirming-edge moves (l.365, l.379): `location_moves_since(crossing_ts)`, then keep `move.ts > crossing_ts`;
    compare `move.person_entity` with `tracked_person_entity_id(slug)` (the BLE producer derives it with
    `_find_person_entity`, whose first candidate is that same rule);
  - perimeter (l.490): `get_crossings_since(edge - timedelta(seconds=PERIMETER_EGRESS_IDENTITY_MATCH_S +
    EGRESS_ENTRY_WINDOW_SECONDS))`.
- Step 8 (3a): §5.4 moves shape and unit as above (on truncation, re-read `get_person_location`); its music-following
  `async_add_listener` is a reserved R10 listener; its F5 read is `subscribe_person_arriving`.
- HVAC state-of-play (3a): header line for the D4 setter (`hvac.py:1241` now calls
  `PersonTrackingCoordinator.set_pre_arrival_enabled`; byte-identical, no HVAC decision changed). (3b): header line
  "holds a dead camera's level for up to 4 h" → 900 s; Source 3 now also skips a dead camera no room watches (house
  stamp), so the D6 failsafe can release it as it already does for watched cameras.
- Presence state-of-play (3a: residency row, diagnostics download; 3b: stream-health entry, §10 if anything is refuted).
- Contract (3b): read list adds `PersonCensus.interior_camera_entities()` and `PresenceCoordinator.zone_camera_entities()`;
  §2.6 names `camera_stream_health.room_stream_input_entities` (room config entry plus the camera manager's area
  lookup) as the one room-input list, and `page_camera_key` as the one stuck-signal page key.
- Presence state-of-play on develop: §10 #41 (done on develop, 109cd0df): the S2 entry's claim that the
  "Protect device drops off Wi-Fi" case is pinned does not hold live, because every Protect person sensor resolves
  `multi_camera` (2-4 enabled camera channels per device), so `is_unavailable_held` answers None for it; the test
  fixture used a one-camera Protect device. 3b (decided Q12) closes it for every path that reads a Protect sensor live
  (room camera override, zone camera tier, census; §6.2).
- Contract INV-MISSING-NOT-ZERO (3b): device liveness, the house tracker for unwatched cameras and the MEDIUM
  twin-covering notice.
- Identity manual §1 (3b: W1 consumer). Arc map M13/M14 (orchestrator).

## 13. D0 report

(a)-(e): filled before D2 / D6 build. (d) also decides DEAD-CAMERA-TWIN-COVERAGE-1.

**(f) Enabled camera entities per device, and where multi-camera sensors reach readers** (plan review A's probe
`.claude/tmp/rev35_probe.py`, read-only over `core.device_registry`, `core.entity_registry`, `core.config_entries`,
2026-11-14; re-run by the planner the same day with the same result):
- Cameras per device: frigate 29 devices, 1 each; unifiprotect 25: 1 (5), 2 (17), 3 (2), 4 (1, Madrone G6 Entry incl.
  `camera.madrone_g6_entry_package_camera`, `unique_id` `<mac>_3`, no `translation_key`); reolink 2: 1 and 2 (TrackMix);
  amcrest 1: 3; dahua 1: 3; ESPHome panels 7, 2 each.
- W1 pairs: 20; admitted 17 (Frigate ↔ Protect); rejected 3 (Frigate ↔ ESPHome kitchen, study_a, up_hallway panels).
  (e): pool-overhead is not W1-paired (decided Q6).
- Admitted pairs a URA reader uses: 8 (family_room, garage_a, garage_b, master_hallway, playroom, stairs_top,
  upstairs_hall, foyer_fisheye); reader-less: 9 (back_yard, front_door_aerial, front_side_ptz, g5_bullet, hot_tub,
  madrone_g6_entry, pool_equipment, rear_ptz, utilities_ptz).
- Room inputs on a multi-camera device: 0 of 72. Room inputs on camera devices: 3, all one-camera Frigate panel sensors.
- Room camera-override candidates on multi-camera devices: 9 Protect `*_person_detected` (camera_protect_garagehallway,
  doorbell_lite, family_room, garage_a, garage_b, master_hallway, playroom, stairs_top, upstairs_hall) and 1 Reolink
  (`ptzcamreolinktmixpstudybporch_person`). The zone camera tier reads 6 of them (plan review A rev 3.6): Garage Hallway
  opts out (`CONF_DISABLE_CAMERA_PRESENCE`) and Garage A / B sit in no zone.
- Census `camera_person_entities`: 12 entries; 7 Protect, 6 on room-watched devices, 1 (`foyer_fisheye`) unwatched;
  Frigate `camera.foyer_fisheye` also unwatched.
- Protect devices whose person sensor reaches no override and no zone tier: 10 (back_yard, foyer_fisheye, front_door_aerial,
  front_side_ptz, g5_bullet, hot_tub, madrone_g6_entry, pool_equipment, rear_ptz, utilities_ptz); of these only
  foyer_fisheye is read at all (census, through U).

## 14. Decisions and open questions

Decided by the operator, 2026-11-14 ("Defaults are good by me"):
- **Q1.** G6 rest goes to G6-ONE-BLE-ROOM-READ-1, dispatched when ship 3a merges, in parallel with step 7.
- **Q2.** If census-p2 slips, ship 3a carries `SIGNAL_RESIDENCY_EVENT`.
- **Q3.** Display census callers stay on the trust view.
- **Q4.** BLE-ARRIVAL-PRODUCER-HVAC-GATED-1, operator pick A, lands before v6.0.0 (so step 8 arrival music keeps BLE
  arrivals whatever the HVAC switch reads). Ship 3a keeps today's behaviour.
- **Q5.** Keep `SIGNAL_PERSON_SIGHTING`, no listeners allowed.
- **Q6.** Pool-overhead's four integrations are deferred to NVR witness W2.
- **Q7.** One NVR down with the other covering: one MEDIUM "one NVR down, the other covering" notice when the hold would
  have ended; HIGH only when every NVR has lost the camera.
- **Q8.** A dead Tier-1 input with no readable twin input in the Tier-1 map keeps blocking the anchor. With option A
  (Q11) no twin input covers anything, so every dead Tier-1 input blocks, held or released, exactly as in census-p2's G7.
- **Q9 (structure).** Operator: "3a and 3b are fine. Ok doing them in parallel and then shipping sequence can be
  serial?" Two ships, built in parallel, shipped 3a then 3b (§1).
- **Q10 (remaining leaks), decided 2026-11-14.** Operator: "Leak groups accepted but I'm going to need a size on
  cleaning that up. And a plan." The 34 groups are accepted (233 allowlist rows, max-sum 261, before the six R2 lifecycle rows are removed; pinned at
  build: `LAYER_ALLOWLIST_TOTAL` = <final max-sum>; plus 28 listed listeners;
  nine groups unguarded and tracked by card only). The sized cleanup plan is
  `docs/planning/PLANNING_person_awareness_leak_cleanup.md` (§9).
- **Q11 (3b scope), decided 2026-11-14.** Operator: "Dead camera - option A. Card B and why we would uncork it later.
  Link it." 3b ships option A (§6). Option B, per-reader twin coverage, is parked as DEAD-CAMERA-TWIN-COVERAGE-1 on
  develop's board. Revival trigger: D0 (d) shows a twin input in the same reader set for at least one paired camera AND
  one-NVR outages cause at least 30 held-input minutes a week that change a decision or a display; or the operator asks.
- **Q12 (device-level stream health for multi-camera NVR devices), decided 2026-11-14.** Operator: "This symmetrical
  with frigate right? If so, yes"; confirmed yes on the corrected framing (kanban d0a25cbc). Facts: no room input (0 of
  72) sits on a multi-camera device; the multi-camera sensors reach readers through the room camera override (9 Protect,
  1 Reolink TrackMix), the zone camera tier (6 of the 10; Garage Hallway opts out, Garage A / B are in no zone; the
  orchestrator re-puts this corrected count) and the census (7 Protect entries, 6 watched, foyer unwatched). Effects:
  §6.2 table. Cost: a Protect or Reolink device that drops off while seeing a body holds the census up to 15 min, as
  Frigate does today, which can delay AWAY. Symmetry: same grace, caps, held-from-t0, release, pages and readers; the
  only differences are "any channel live" liveness (identical for single-lens cameras; the dual-lens package channel is
  carded) and the pre-existing Frigate-only unrecognized count. `CAMERA_STREAM_DEVICE_LEVEL_INPUTS` = True; False is the
  fallback if the operator withdraws.

Open: none.

## 15. Plan completion tracking (filled at ship)

| Item | Status | If deferred: why, where |
|---|---|---|
| D0-D5, D7 (3a) | | |
| D6 option A (3b) | | |
| Per-reader twin coverage (option B) | parked (decided Q11) | DEAD-CAMERA-TWIN-COVERAGE-1, revival trigger in §14 Q11 |
| G6 rest | split | G6-ONE-BLE-ROOM-READ-1 |
| G1 approach / all persons | out of scope | STALE-SOURCE-ARRIVAL-CONSUMERS-1 |
| Pool-overhead twin | out of scope | NVR-WITNESS-CONSOLIDATION-1 (W2) |
| Leak cleanup | planned separately (decided Q10) | `PLANNING_person_awareness_leak_cleanup.md` |
| Census face reads stream health | out of scope | CENSUS-FACE-READS-STREAM-HEALTH-1 |
| Dual-lens package channel membership | out of scope (no registry rule) | DUAL-LENS-PACKAGE-CHANNEL-MEMBERSHIP-1 |

## 16. Change history

The "Changes from rev X" tables (rev 2 → rev 3.8) were meant to move to
`docs/planning/archive/PLANNING_person_awareness_layer_ship3_history.md`, but that file was never written. This plan
also lived only in `.claude/tmp` until 2026-11-14, when it was committed during the ship 3b close; the v5.108.24 README
and the state-of-play doc already cited this path. The per-rev history survives only in the plan-review docs
(`docs/reviews/code-review/v_layer_ship3*`) and the session transcript.

## 17. Guard rulings (appendix, part of the 3a spec)

Source: `quality/tests/person_awareness_layer_allowlist_PROVISIONAL.py` on `feature/layer-ship3a` (888a58d7), the 60
rows marked `explained: False` (the builder's summary counted 59; the R5 row makes 60). Lines are in that worktree.
Apply mechanically: (a) rows disappear once the named rule fix is in the engine; (b) rows disappear once the method is on
the contract read list; (c) rows stay, with `group` set to the §9 number and `explained: True`.

| # | Rule | Site (feature/layer-ship3a 888a58d7) | Allowlist symbol | Ruling | Where |
|---|---|---|---|---|---|
| 1 | R1 | `actuator_reconciler.py:424` | `ActuatorReconciler._boot_settle_done:_boot_settle_done` | a | R1 `LAYER_NON_PERSON_PRIVATES` (`_boot_settle_done`) |
| 2 | R1 | `automation.py:856` | `RoomAutomation._away_boot_settle_done:_boot_settle_done` | a | same |
| 3 | R1 | `automation.py:4514` | `RoomAutomation._failsafe_boot_settle_done:_boot_settle_done` | a | same |
| 4 | R1 | `camera_census.py:3104` | `PersonCensus._d1_boot_settle_done:_boot_settle_done` | a | same |
| 5 | R1 | `fan_veto.py:218` | `_boot_settle_done:_boot_settle_done` | a | same |
| 6 | R1 | `person_coordinator.py:1531` | `PersonTrackingCoordinator._boot_settle_done:_boot_settle_done` | a | same |
| 7 | R1 | `transit_validator.py:1353` | `EgressDirectionTracker.async_init:_get_integration_camera_list` | a | R1 receiver resolves to `camera_manager` (non-member) |
| 8 | R1 | `transit_validator.py:1356` | `EgressDirectionTracker.async_init:_get_interior_camera_entities` | a | same |
| 9 | R1 | `transit_validator.py:569` | `TransitValidator._build_and_subscribe:_get_integration_camera_list` | a | same |
| 10 | R1 | `transit_validator.py:567` | `TransitValidator._build_and_subscribe:_get_interior_camera_entities` | a | same |
| 11 | R1 | `transit_validator.py:739` | `TransitValidator._get_shared_space_cameras:_get_interior_camera_entities` | a | same |
| 12 | R1 | `camera_census.py:2508` | `PersonCensus._any_zone_occupied_snapshot:_zone_trackers` | c | §9 #33 |
| 13 | R1 | `domain_coordinators/presence.py:8087` | `PresenceCoordinator._run_inference:_lost_away_since` | c | §9 #33 |
| 14 | R1 | `person_coordinator.py:524` | `PersonTrackingCoordinator._ble_leads_enabled:_ble_leads_enabled` | c | §9 #33 |
| 15 | R1 | `person_sighting.py:612` | `PersonSightingProducer._emit:_face_arrival_cooldown` | c | §9 #33 |
| 16 | R1 | `person_sighting.py:532` | `PersonSightingProducer._face_recognition_on:_face_recognition_enabled` | c | §9 #33 |
| 17 | R1 | `person_sighting.py:664` | `PersonSightingProducer._update_tracker_fields:_zone_trackers` | c | §9 #33 |
| 18 | R2 | `__init__.py:8383` | `_apply_in_place:set_fan_interference_hold_s` | a | R2 `LAYER_NON_PERSON_PUBLIC` (fan) |
| 19 | R2 | `__init__.py:6251` | `_async_register_presence_services.handle_clear_override:set_house_state_override` | a | R2 `LAYER_NON_PERSON_PUBLIC` (house-state override) |
| 20 | R2 | `__init__.py:6232` | `_async_register_presence_services.handle_set_house_state:set_house_state_override` | a | same |
| 21 | R2 | `select.py:272` | `_HouseStateOverrideSelectBase.async_select_option:set_house_state_override` | a | same |
| 22 | R2 | `select.py:257` | `_HouseStateOverrideSelectBase.current_option:get_house_state_override` | a | same |
| 23 | R2 | `binary_sensor.py:581` | `OccupiedBinarySensor.extra_state_attributes:tracker_for_room` | a | R2 `LAYER_NON_PERSON_PUBLIC` (zone tracker handle) |
| 24 | R2 | `coordinator.py:4028, 4815` | `UniversalRoomCoordinator._async_update_data:tracker_for_room` | a | same (max 3) |
| 25 | R2 | `coordinator.py:3333` | `UniversalRoomCoordinator._evaluate_mmwave_demoted_latch:tracker_for_room` | a | same |
| 26 | R2 | `coordinator.py:4143` | `UniversalRoomCoordinator._async_update_data:get_fan_last_transition` | a | R2 `LAYER_NON_PERSON_PUBLIC` (fan) |
| 27 | R2 | `coordinator.py:4720` | `UniversalRoomCoordinator._async_update_data:is_room_mmwave_fan_demoted` | a | same |
| 28 | R2 | `coordinator.py:4447` | `UniversalRoomCoordinator._async_update_data:is_room_direct_ble` | a | R2 `LAYER_NON_PERSON_PUBLIC` (room scanner config) |
| 29 | R2 | `domain_coordinators/presence_fan_recheck.py:687` | `FanRecheckManager._evaluate_eligibility:get_ble_tier` | a | same |
| 30 | R2 | `sensor.py:4569` | `ExteriorOpenTracksDiagnosticSensor.extra_state_attributes:path_map_status` | a | R2 `LAYER_NON_PERSON_PUBLIC` (path map config) |
| 31 | R2 | `sensor.py:5861` | `PresenceHouseStateSensor.extra_state_attributes:get_house_occupancy` | a | R2 `LAYER_NON_PERSON_PUBLIC` (house state, `presence.py:5544`) |
| 32 | R2 | `sensor.py:6904` | `PresenceNextStateSensor._get_prediction:get_next_state_prediction` | a | R2 `LAYER_NON_PERSON_PUBLIC` (house-state prediction) |
| 33 | R2 | `sensor.py:5624` | `URAStuckSignalWatchdogSensor._collect:get_stuck_cameras` | a | R2 `LAYER_NON_PERSON_PUBLIC` (stream watchdog) |
| 34 | R2 | `aggregation.py:2219` | `OccupantCountSensor.native_value:get_tracked_person_count` | b | display |
| 35 | R2 | `aggregation.py:6183` | `PersonLocationSensor._update_from_coordinator:get_person_confidence` | b | display |
| 36 | R2 | `aggregation.py:6342` | `PersonLocationSensor.extra_state_attributes:get_person_confidence` | b | display |
| 37 | R2 | `aggregation.py:5656` | `ZoneCurrentOccupantsSensor.extra_state_attributes:get_person_confidence` | b | display |
| 38 | R2 | `sensor.py:3028` | `CurrentOccupantsSensor.extra_state_attributes:get_person_confidence` | b | display |
| 39 | R2 | `aggregation.py:6439` | `PersonPreviousLocationSensor.native_value:get_person_previous_location` | b | display |
| 40 | R2 | `aggregation.py:6529` | `PersonPreviousSeenSensor.native_value:get_person_previous_location_time` | b | display |
| 41 | R2 | `aggregation.py:2321` | `PersonTrackingDiagnosticSensor.extra_state_attributes:get_diagnostic_data` | b | display |
| 42 | R2 | `aggregation.py:4931` | `ZoneAnyoneBinarySensor._nonsleep_person_fallback_occupied:should_veto_due_to_reliable_signals` | b | comfort / house_state |
| 43 | R2 | `aggregation.py:4784` | `ZoneAnyoneBinarySensor._sleep_person_fallback_occupied:should_veto_due_to_reliable_signals` | b | comfort / house_state |
| 44 | R2 | `aggregation.py:5647` | `ZoneCurrentOccupantsSensor.extra_state_attributes:get_persons_in_zone` | b | display |
| 45 | R2 | `aggregation.py:5618` | `ZoneCurrentOccupantsSensor.native_value:get_persons_in_zone` | b | display |
| 46 | R2 | `aggregation.py:5757` | `ZoneOccupantCountSensor.native_value:get_persons_in_zone` | b | display |
| 47 | R2 | `domain_coordinators/hvac.py:3098` | `HVACCoordinator._apply_house_state_presets:check_zone_occupancy_confidence` | b | comfort (HVAC D6 confirmation) |
| 48 | R2 | `aggregation.py:6404` | `PersonPreviousLocationSensor.async_added_to_hass:seed_previous_location` | c | §9 #34 |
| 49 | R2 | `aggregation.py:6488` | `PersonPreviousSeenSensor.async_added_to_hass:seed_previous_location_time` | c | §9 #34 |
| 50 | R2 | `binary_sensor.py:555` | `OccupiedBinarySensor.extra_state_attributes:get_room_occupants` | c | §9 #26 |
| 51 | R2 | `sensor.py:3004` | `CurrentOccupantsSensor.native_value:get_persons_in_room` | c | §9 #26 |
| 52 | R2 | `sensor.py:3023` | `CurrentOccupantsSensor.extra_state_attributes:get_persons_in_room` | c | §9 #26 |
| 53 | R2 | `sensor.py:3099` | `OccupantCountSensor.native_value:get_persons_in_room` | c | §9 #26 |
| 54 | R3 | `__init__.py:4563` | `async_setup_entry:async_all` | a | R3 (i) id-membership only (setup validation) |
| 55 | R3 | `config_flow.py:1548` | `UniversalRoomAutomationConfigFlow._all_person_entities:async_entity_ids` | a | R3 (i) id-membership only (config-flow person picker) |
| 56 | R3 | `domain_coordinators/hvac_override.py:895` | `OverrideArrester._resolve_context_user_to_person:async_all` | a | R3 (ii) actor identity (`user_id`) |
| 57 | R3 | `domain_coordinators/notification_manager.py:3835` | `NotificationManager._person_for_companion_event:async_all` | a | R3 (ii) actor identity (`user_id`) |
| 58 | R3 | `domain_coordinators/notification_manager.py:4763` | `NotificationManager._get_person_name:states.get` | c | §9 #31 (raw `person.*` for a display name; `display_of`) |
| 59 | R5 | `domain_coordinators/presence.py:6026` | `PresenceCoordinator.get_house_census:house_census_view(view:view_not_trust)` | a | R5 owner delegate |
| 60 | R9 | `__init__.py:3111` | `async_setup_entry:async_track_state_change_event (`sensor.bermuda_global_total_device_count`)` | a | R9 / R3 (iii) fleet-health entity |

Totals: (a) 33 rows, (b) 14 rows, (c) 13 rows. Applying the exclusions exactly also drops 5 further rows (4
`_boot_settle_done`, 1 `get_stuck_cameras`, accepted) and six `__init__.py` R2 lifecycle-wiring rows (orchestrator
ruling): 233 rows, max-sum 261, before the six; final total pinned at build. Judgement call for the operator, with default: the two
restore-time writes in §9 #34 (`seed_previous_location*`) are ruled real leaks (a display entity writing the owner's
store) rather than an owner-display exemption; default: keep them as leaks under PERSON-AWARENESS-READ-API-1 and move the
restore into the person coordinator later.
