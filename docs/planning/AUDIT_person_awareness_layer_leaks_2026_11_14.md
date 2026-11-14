# AUDIT: person-awareness layer leaks (framing D, diff-blind, whole codebase)

Date 2026-11-14, rev 2. Author ura-planner. Read-only; the only writes are this file and the contract
`docs/planning/CONTRACT_person_awareness_layer.md`. Contract §2-§4 define "goes through the layer". Rev 2 applies plan
review `docs/reviews/plan-review/PLANREVIEW_person_awareness_layer_contract.md` (findings D1-D12, guard breaks §2,
goal-fidelity §3) and the 2026-11-14 rulings (contract §9). Rev 1 is in git history.

Code read: `release/batch-2` @ dbff8335 (= develop v5.108.21 + read API ship 2 + stream health S2 + perimeter
batch), plus `feature/census-deconfliction-p2-ledger` @ 92e93c54, `feature/crossing-vision-fast-stage` @ a47e4c5b,
`feature/music-following-repair` @ 0ac39b2a (no code commits; music findings are on batch-2 code). Line numbers are
batch-2 unless a branch is named. Method: a read-only scanner (`.claude/tmp/pa_scan.py`, 20 regex families) over the
whole package, each hit read in context, then the review's missed sites re-verified by `git grep` / `git show`.
Pre-existing code is in scope (most leaks below predate the arc).

Docs read: CLAUDE.md; `ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`; `ARC_identity_vision_census_map.md`;
`PLANNING_person_awareness_read_api.md`; `PLANNING_census_deconfliction.md`; `PLANNING_nvr_witness_layer.md` §1-§6;
`AUDIT_person_awareness_interface_inventory_2026_11_13.md`; grep passes over the crossing vision, stream health,
interior vision, egress direction, identity actions v6 and music repair plans. **Presence docs:**
`PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `SENSOR_FLEET_CLASSES.md` read completely for rev 2 (incl. the §10
corrections ledger; nothing below re-asserts a ledger claim). `IDENTITY_FUSION_CAMERAS_MANUAL.md` §3-§5.5 read in
full.

Code-vs-doc contradictions (code wins): (1) the inventory's "F4 accessor has zero production callers" is stale:
`get_last_person_sighting` is called at `binary_sensor.py:2246` and `sensor.py:3590` (display). (2)
`camera_census.py:2728` docstring says the census hold cap is 600 s; the constant is 900 s (`const.py:6035`). Doc
fix belongs to the stream-health S2 branch owner (one-line docstring).

## 1. Answer first

- **42 sites do not go through the layer** (security/access 11, house_state 6, comfort 9, notification 2, display 8,
  producer-side ingest 6). Rev 1 counted 35; rev 2 adds the review's D1, D3, D4, D5, D9, D10 and the private
  `_is_room_occupied` read found while verifying D2.
- **The largest F4-BLE reader was missing from rev 1:** room occupancy (`coordinator.py:3315, 4440, 5003`) runs on
  every tick of ~40 rooms and reads raw `get_persons_in_room`, while fan recheck and the zone tier read a
  phone-left-behind-filtered view. Contract §2.4a names one meaning.
- The ingest half is still the weakest: F1 edges have three ledgers and four raw `person.*` listeners, F5 has three
  raw dict sends and an HVAC write of the BLE pre-arrival enable flag, and F2's dedup lives in two places (union +
  `_cross_validate_platforms`, then `deconflict_house`), now named as one ingest pair.
- **Highest live risk:** S1, the Security Coordinator's own geofence listener (only while armed) adds an expected
  arrival on any raw `not_home -> home` (10 min) or `not_home -> zone` (30 min), for every `person.*` including
  guests, with no stale-source or boot test, so each of the 78 sub-second iPad blips measured 11-05..11-12 (presence
  doc §10 #33) could open a suppression window while armed.

## 2. Leak table (NO rows), ranked by consumer class then live risk

Key: Fact; P = producer side, C = consumer side; class per contract §2.

### 2.1 Security / access (11)

| # | Site | Fact | P/C | Class | What leaks | Fix (route through) | Risk |
|---|---|---|---|---|---|---|---|
| S1 | `domain_coordinators/security.py:2231-2288` `_resubscribe_geofence_persons` (`async_all("person")`, every person) / `_handle_person_state_change` (armed only) | F1 edge → F5 effect | C (a 4th arrival producer) | access (alarm suppression) | own `person.*` listener; `not_home -> home` 10 min, `not_home -> named zone` 30 min; guests included; no stale-source or boot test; a geofence arrival can also arrive via `SIGNAL_PERSON_ARRIVING` (`:819`), so one arrival adds twice (harmless refresh, LOW) | G1 `subscribe_person_edges(persons=all, kinds={arrival, approach})`, stale-source edge HELD then confirmed (lock-regime semantics), boot window applied; keep the 10/30-min windows and guest scope (operator ruling: no delivery change); dedupe by person with the `:819` path. Card STALE-SOURCE-ARRIVAL-CONSUMERS-1 (extend, no second predicate, arc map M9) | **HIGH** |
| S2 | `security_lock_regime.py:633, 777, 1199, 1759, 1942, 2004, 2453, 2609, 2652, 2714` + `_on_person_event` + own `_last_real` | F1 edges | C + 2nd store | access | second edge ledger | G1; lock keeps only its hold logic. Tier 3; inside LOCK restart plan (M8). Allowlist until then | HIGH if changed carelessly; correct today |
| S3 | `security_lock_regime.py:1855, 1868, 1892` (`record_bermuda_moves(pc.data)`) | F4-BLE | C | access | raw store | G6 `location_moves_since(t)` | MED |
| S4 | `security_lock_regime.py:1811` → `arrival_edges.door_entry_areas` (`arrival_edges.py:329`) | F3 config | C | access | tracker privates `_egress_entities`, `_interior_neighbours_by_group` | G5 `entry_areas()` | MED (wrong-object bug happened once, presence doc §1) |
| S5 | `security.py:283, 346` `context.get("census", {})` | F2 | C | **access** | no producer anywhere (`manager.py:1022-1033` `_build_context` has no `census`): the unknown-person ALERT_HIGH (`:369-371`, fires even disarmed), census-intent lock-all-doors (`:1104-1115`) and persons-home SANCTIONED leg have never fired | **KEEP + DOCUMENT, do not wire.** Wiring would activate a dormant lock-all-doors path fed by the census; operator decision (contract §9 Q2), own Tier-3 card if wanted | dormant |
| S6 | `perimeter_alert.py:1110` own `ura_person_egress_event` listener → `_note_egress_identity` 600 s cache | F3 | C + private store | security | private crossing history | G2 | MED |
| S7 | `perimeter_alert.py:6226` raw `person.{slug}`; own `_person_arrivals` ledger + listener; `:5958` `pc.data` | F1 edges, F4-BLE | C + 3rd store | security | third ledger, raw store | G1 + G6 | MED |
| S8 | `perimeter_alert.py:6003` tracker privates via `door_entry_areas` | F3 config | C | security | as S4 | G5 | LOW |
| S9 | `perimeter_alert.py:1851-1854, 5907` `census.resolve_face_legs` | F2 evidence | C | security | consumer deciding on raw legs | F4 / F3 via G2; legs for producers only | MED |
| S10 | `perimeter_alert.py:5339, 5419, 5868-5871` `tracked_person_slugs`, `known_face_guests`, `canonical_person_slug` | id roster | C | security | census as roster owner | `person_ids` + a public roster read on presence | LOW |
| S11 | `perimeter_alert.py:5038` `_apply_single_source_gate`, `_leg_tag` / `base_engine` (`:578-708`) | NVR comparison #3 | C | security | own family classifier, partly by name | NVR witness W2 | MED |

### 2.2 House state (6)

| # | Site | Fact | P/C | What leaks | Fix | Risk |
|---|---|---|---|---|---|---|
| H1 | `presence.py:3283` boot seed reads `sensor.universal_room_automation_identified_persons_in_house` state into `_census_count` (AWAY input) | F2 | C | display entity state feeds a trust input | seed from `house_census_view(hass, cls="house_state")` or wait for the first signal; golden test `test_boot_seed_ignores_vision_sensors` | MED (boot AWAY) |
| H2 | `presence.py:2443, 4660, 4854, 5306, 6093-6099, 6275, 6457, 7343-7441, 8253-8255, 8928-8932`; also `async_all()` + `.startswith("person.")` at `:5315-5317` | F1 level / F4-BLE | C | inference reads `person_coordinator.data` (~12 sites) and raw person states | G6 frozen `snapshot()` once per tick; Tier 3 (house state); allowlist max 12 until then. The inference phone filter twin (`:7355`) is migrated here, with its parity test | MED |
| H3 | `crossing_vision.py:1141-1145` `_held_inputs` (census-p2 @ 92e93c54) | evidence (stream health) | P (F2 term provider) | iterates `self._domain_data().values()` for any object with `camera_input_stream_dead` (duck-typed reach-around through a helper; R4 rev 1 could not see it) | G7: per input `input_stream_view` / `entity_stream_view`; any non-None view (HELD or RELEASED) holds the anchor; RELEASED is never off for the anchor (orchestrator ruling: a dead Tier-1 input blocks the anchor while dead). Rebase census-p2 on batch-2 first (S2 getters absent there) | MED (awareness today; trust at rung 4) |
| H4 | `binary_sensor.py:2176-2270` `PersonPhoneLeftBehindSensor` (AWAY input) | F2, F4-BLE | C | `house_census_view(hass, "trust")` literal; `pc.data.get(person)` raw; **`person_coordinator._is_room_occupied(...)` private read** (`:2203`, D9 carve-out) | `house_census_view(hass, cls="house_state")`; G6; a public `room_occupied(room)` on PersonCoordinator | LOW |
| H5 | `camera_census.py:2853-2858, 3239-3249` `_get_ble_persons` | F4-BLE → F2 | P | `pc.data` raw inside the F2 producer | G6 `persons_located_home()` | LOW |
| H6 | `transit_validator.py:305, 669-911` `_camera_sightings` legacy store; read by `transitions.py:422` | F4 | P (2nd F4 store) | second sighting store (unidentified only) | move path validation to F4; then DELETE | LOW |

### 2.3 Comfort (9)

| # | Site | Fact | What leaks | Fix | Risk |
|---|---|---|---|---|---|
| C1 | `fan_veto.py:380-445` | room camera body evidence | reads URA's own `binary_sensor.*_camera_person_detected` STATE and `agreement` / `confidence` attributes; room matched by name or title, slug fallback (name guessing) | room-coordinator public getter `camera_person_evidence()` from W5c; registry-only room resolution | MED |
| C2 | `binary_sensor.py:1821-1889` `CameraPersonDetectedSensor` agreement | NVR comparison #4 | counts integrations, not NVR families | W5c `families_on_now` | MED |
| C3 | `fan_veto.py:309-330` | F4-BLE | `get_persons_in_room` then `pc.data[...]["tracking_status"]` raw | G6 `persons_in_room(room, active_only=True)` | LOW |
| C4 | `music_following.py:535-538, 597-599, 656-669` | F4-BLE | `person_coord.data` raw | G6 / event payload | LOW |
| C5 | `presence_fan_recheck.py:1375` `getattr(person_coord, "_area_id_to_room", None)`; `:1384-1386` slug fallback `str(area).lower().replace(" ", "_")`; reached from `:672` (eligibility) and `:1168` (mid-flight cancel) via `_l1_persons` | F4-BLE config | producer private read in a callee (object passed in) + name guessing | G6 `room_for_area(area_id)` + `persons_in_room_or_scanner_areas(room)` (scanner-area union kept: presence doc §6 item 3) | MED (cancels a recheck mid-flight) |
| C6 | `coordinator.py:4436-4441` BLE extends room occupancy (`get_persons_in_room`, raw) | F4-BLE | highest-volume F4-BLE reader (~40 rooms, every tick); a member public method read outside §4, and a second BLE-in-room meaning (no phone filter) | G6 one read; phone filter behind operator Q1 + probe (contract §2.4a) | **HIGH** (volume + concept split) |
| C7 | `coordinator.py:3310-3318` radar-latch clear reason `ble_person` | F4-BLE | as C6 | as C6 | MED |
| C8 | `coordinator.py:4998-5003` `STATE_BLE_PERSONS` fill (read by `binary_sensor.py:505, 3638`) | F4-BLE | as C6 | as C6 | LOW |
| C9 | `_ble_corroboration.py:34-66` `phone_trustworthy` (registry-resolved PLB state read) + presence twins `presence.py:4830, 7355` and `_phone_left_behind_on` | F4-BLE filter | a URA person-awareness entity state as a decision input outside the layer, three copies | one predicate owned by the layer (contract §2.6 "Phone left behind"); `_ble_corroboration` re-exports; zone-tier twin `:4830` routes to it; inference twin `:7355` stays allowlisted until H2 | MED |

### 2.4 Notification (2)

| # | Site | What leaks | Fix | Risk |
|---|---|---|---|---|
| N1 | `transit_validator.py` `_arrival_departure_notify` (inside `EgressDirectionTracker`) | notification policy hosted in the F3 producer (reads `CONSUMER_CLASS_MIN_CONFIDENCE` correctly) | D8 moves it to an NM-side consumer reading `get_last_crossing` + `min_confidence("notification")`; allowlisted until then | LOW |
| N2 | `notification_manager.py:4763` raw `person.*` for a display name | `display_of` / friendly-name helper in `person_ids` + presence | LOW |

### 2.5 Display (8)

| # | Site | What leaks | Fix | Risk |
|---|---|---|---|---|
| D1 | `sensor.py:3758-3761, 3809, 3852, 4885, 5616` census sensors read `census.last_result` / object | owner-display exemption (allowlist with counts) | — | none |
| D2 | `sensor.py:4567` egress tracker object; `:6658` transit validator object | F3 display through objects | `get_last_crossing` / G2 | LOW |
| D3 | `aggregation.py:6102-6192` `PersonLocationSensor` finds Bermuda sensors by NAME `sensor.bermuda_{first_name}_` | Registry-not-names violation | reuse PersonCoordinator's registry-resolved area sensor via a public getter | LOW |
| D4 | `aggregation.py:2193-2327, 5575-6677` (26 `person_coordinator` fetches, `.data` loops) | raw store | G6 or owner-display allowlist | LOW |
| D5 | `binary_sensor.py:1944-2008` `URAUnexpectedPersonSensor` | `pc.data` + literal `"trust"` | class `display`; G6 | LOW |
| D6 | `binary_sensor.py:2058` `CensusMismatchSensor` reads `sensor.universal_room_automation_persons_in_house` STATE | URA entity state as input | `house_census_view(hass, cls="display")` | LOW |
| D7 | `coordinator.py:1383-1385` room identified persons via `get_persons_in_room`; `switch.py:963` census object; `binary_sensor.py:3401, 3432, 3501` census privates (allowlisted on batch-2) | objects / privates | G6 (`:1385`); allowlist (counted) | none |
| D8 | `house_status.py:213-244` person list from `pc.data` keys | raw store | G6 | none |

### 2.6 Producer-side ingest (6)

| # | Site | What leaks | Fix | Risk |
|---|---|---|---|---|
| P1 | `presence.py:5678, 5937`, `person_coordinator.py:1172` | three raw dict sends of `SIGNAL_PERSON_ARRIVING` | G4 | LOW-MED (D8 adds a 4th source) |
| P2 | `transit_validator.py:1563-2080` `census.set_egress_identity_last_attach`, `note_*`, `consume_ble_arriving_legs` | F3 provenance and counters stored ON the F2 owner | move attach record + counters to the tracker; census keeps BLE-leg consumption | LOW |
| P3 | `camera_census.py:2395` `_cross_validate_platforms` | **F2 ingest** (body dedup, contract §2.2 (1)); NVR comparison #1 with its own classifier, `CameraInfo.platform` partly by suffix | W5b `platform_for`, only with a byte-identical house-count test | MED (house count) |
| P4 | `transit_validator.py:2733` `_count_platforms_fired` | NVR comparison #2 (substring test) | W2 `corroborated` | LOW |
| P5 | `domain_coordinators/hvac.py:1236-1241` `pc._pre_arrival_enabled = value` | non-owner WRITE of a PersonCoordinator private that gates the BLE F5 producer: toggling HVAC pre-arrival silently turns BLE pre-arrival on/off | G9 public `set_pre_arrival_enabled(value)` on the owner (behaviour unchanged; whether HVAC should own that toggle at all is out of scope) | MED |
| P6 | inline `f"person.{slug.lower()}"`: `camera_census.py:4760, 4817, 6630`; `person_sighting.py:605`; `transit_validator.py:2020`; `person_coordinator.py:1773`; `perimeter_alert.py:1118` | Registry-not-names (contract §2.6); five are inside identity vetoes, so a friendly-name person whose entity id is not the lower-cased slug reads `None` and the veto fails open | `person_ids.tracked_person_entity_id` | LOW |

## 3. Conforming sites (YES), for completeness

F1: HVAC `hvac.py:3416, 3994`, `hvac_fans`, `hvac_zones.py:2708` (persons_home_for_trust); aggregation zone
fallbacks; `perimeter_alert.py:2162-2232` (`get_residents_home_count`, `get_recent_resident_arrival`);
`sensor.py:5853, 6183-6201`; `house_status.py:220-244` (trust helper); presence's direct geofence triggers
(`presence.py:9888, 9892`, the AWAY fast path, contract INV-AWAY-LATENCY). F2: `sensor.py:5237, 5252`,
`aggregation.py:6744, 6773`, `binary_sensor.py:1953, 2001, 2220, 2270` (through `house_census_view`, but literal
view); presence `_handle_census_update` via `SIGNAL_CENSUS_UPDATED`; census-p2 deconflict call site and `census_tick`
pull. F3: four entry/exit sensors (`sensor.py:4819, 4950, 5060, 5110`, declared bus); `person_sighting.py:449`;
`crossing_vision.py:58` listener; census register/evict (`transit_validator.py:2321, 2325`). F4: PLB / NextRoom via
`get_last_person_sighting`. F5: HVAC `hvac.py:1511`, security `:819`, lock regime, music (`PersonArrivingPayload`).
Evidence: stream health S2 readers (`presence.py:827-4545`, `occupancy_substrate.py:311, 355, 358, 950`,
`camera_census.py:2728-2754`, `fan_veto.py:476`); they apply the 900 s release + HIGH page, which IS the operator
ruling (contract INV-MISSING-NOT-ZERO), so they conform.
Excluded (actor identity, not person awareness): `hvac_override.py:895` arrester immunity and
`notification_manager.py:3835` (HA `user_id` → person for "who pressed"); `__init__.py:4563` config validation.

## 4. Top 10 leaks with fixes

1. S1 security geofence expected-arrival → G1 (all persons, approach kind) + held stale-source rule (HIGH).
2. C6-C8 room occupancy reads raw BLE-in-room on every room tick → G6 one read (operator Q1 for the filter).
3. S2 lock regime second edge ledger → G1, Tier 3 inside the LOCK restart plan.
4. S7 perimeter third ledger + raw person + `pc.data` → G1 + G6.
5. H1 boot seed from a display entity into an AWAY input → `house_census_view(cls="house_state")`.
6. H2 presence inference reads `pc.data` at ~12 sites → G6 snapshot, Tier 3.
7. H3 crossing-vision `_held_inputs` duck-typed scan → G7 (view; RELEASED holds the anchor) before census-p2 merges.
8. C1 / C5 fan veto own-entity state and fan recheck private + slug fallback → W5c getter, G6 `room_for_area`.
9. P5 HVAC writes `pc._pre_arrival_enabled` → G9 public setter.
10. P1 F5 raw sends → G4 (before D8 adds `camera_egress`).

## 5. The code guard (extends `test_no_private_census_reads_outside_module`, batch-2 `quality/tests/test_person_awareness_read_api_ship2.py:494-602`)

New file `quality/tests/test_person_awareness_layer_guard.py`; the existing census test stays as rule R1's first
member. AST only, no imports of production code beyond source text and the string constants of `const.py` /
`signals.py` (parsed, not imported). Rev 2 closes every bypass from review §2.

| Rule | Detects | Receiver / resolution (rev 2) |
|---|---|---|
| R1 private member access | Load, Store or Del of `_x`, or `getattr` / `setattr` / `hasattr` / `delattr` with constant `"_x"`, where `_x` is in the harvested private set of a layer member class (`PersonCensus`, `EgressDirectionTracker`, `TransitValidator`, `PersonTrackingCoordinator`, `PersonSightingProducer`, `CrossingVisionShadow`, `CrossingLedger`, `PresenceCoordinator`, `ResidencyTracker`), outside that class's module. Also `vars(x)[...]` / `x.__dict__` on any receiver in a non-member module | **Receiver-agnostic**: the attribute name alone decides (catches helper-passed objects such as `_l1_persons`, renamed locals, coordinator-manager reach `coordinators["presence"]._residency`, `_domain_data()` indirection). Names that collide with a non-member class's own private go to the allowlist with reason `name_collision` |
| R2 store / member-method read | `.data` / `.last_result` / `_last_sightings` / `_camera_sightings` on any receiver in a non-member module; `getattr(x, "data")`; `self.coordinator.data` in any `CoordinatorEntity` constructed with a member (bound by scanning `CoordinatorEntity.__init__(coordinator=...)` call sites); AND any call of a member PUBLIC method that is not on the contract §4 list (e.g. `get_persons_in_room` from `coordinator.py`) | method names harvested per member class minus the §4 allowlist |
| R3 raw entity read | `hass.states.get/async_all/async_entity_ids`, `async_track_state_change_event`, `async_track_state_change_filtered`, `Template(...)` / `async_track_template_result` where the entity id or domain is tainted: a constant or f-string starting `person.`, `device_tracker.`, `sensor.bermuda`, domain `"person"`; any value from `tracked_person_entity_id(...)`; `async_get_entity_id(..., DOMAIN, uid)` where `uid` ends with a person-awareness suffix (`_phone_left_behind`, `_camera_person_detected`, `persons_in_house`, ...); `async_all()` results filtered by `.startswith("person."/"device_tracker."/"sensor.bermuda")`; a `CONF_*` person-list read from config; string constants containing `states.person` or `is_state('person.` | intra-module dataflow taint (assignments, comprehensions, function returns within the module) |
| R4 hass.data scan | any `.values()` / `.items()` iteration (loop, comprehension, `filter`, `map`) whose element reaches `getattr` / `hasattr` / `isinstance` / an attribute call with a member-ish or stream-health name, regardless of where the dict came from (`hass.data[DOMAIN]`, `_domain_data()`, a parameter) | element tracking; owner row for `camera_stream_health._room_coordinators` |
| R5 class literal | `house_census_view` / `get_house_census` / `view_for_class` / `min_confidence` called with anything but a str literal in `CONSUMER_CLASSES` (rejects Names such as `VIEW_TRUST`, `functools.partial`, f-strings); a file whose literal class differs from the pinned per-file class map (the conformance table) | call args + pinned map |
| R6 push channel send | `async_dispatcher_send` / `dispatcher_send` / `hass.helpers.dispatcher` / `hass.bus.async_fire` / `hass.bus.fire` whose signal or event VALUE (resolved from the parsed constants, through aliases and `import ... as`) is one of the five channels (contract §4.2), outside that channel's owner | value resolution, not name match |
| R7 store write | per store: Attribute or Subscript Store, `setattr`, `dataclasses.replace`, `__dict__.update`, and constructor calls of the store's record type (`CensusZoneResult`, `CensusResult`, `CrossingRecord`, `PersonSighting`), outside the owner, for `CensusZoneResult` count fields, `census.last_result`, `PersonTrackingCoordinator.data` (incl. `pc.data[p]["location"] = ...`), `_gps_home_overruled`, `_last_sightings`, the crossing-vision row store, the residency ledger | Store ctx + call names |
| R8 confidence threshold | any Compare with a side naming `confidence` (attribute or Name) whose other side is not `CONSUMER_CLASS_MIN_CONFIDENCE[...]` / `min_confidence(...)`; in `const.py`, any confidence constant equal to a class threshold (0.75, 0.9) not allowlisted with intent (seed: `BLE_TRANSITION_CONFIDENCE`, `CONFIDENCE_HIGH`, `FACE_MATCH_CORRELATED_BOOST`) | Compare nodes; const scan |
| R9 person listener | listeners over person entities outside `presence._handle_geofence_change` / `ResidencyTracker`: R3-tainted entity-list arguments wherever the list was built; `EVENT_STATE_CHANGED` bus listeners whose callback reads `entity_id.startswith("person.")`; `async_track_state_added_domain(hass, "person", ...)`; a polling ledger (a member-outside module holding a dict keyed by person entity id, filled from states, compared on a timer) | taint + callback body scan |

Allowlist: one dict keyed `(rule, file, symbol)` → `{"reason", "card", "max"}`. The test fails when (a) a hit has no
entry, (b) a hit count exceeds `max`, (c) an entry is no longer hit (stale, remove it), or (d) the SUM of `max`
exceeds the pinned `LAYER_ALLOWLIST_TOTAL` (a ratchet that may only go down; raising it is a reviewed contract
change). Owner-display exemptions are rows with reason `owner_display`. Seed rows = the §2 table (e.g. R9 lock regime
max 1 listener, card LOCK-REGIME-BOOT-REALLY-AWAY-1; R2 presence `.data` max 12, card G6; R1 sensor census
diagnostics: the 39 batch-2 rows; R1 presence inference phone twin `:7355`, card H2; R2 `coordinator.py`
`get_persons_in_room` max 4, card G6).

Anti-hollow: (1) per rule, parametrised positive and negative snippets, including one positive snippet for every
bypass in review §2 (helper-passed object, `vars()`, private Store, coordinator-manager reach, `_domain_data()` scan,
`getattr`-comprehension scan, Name view, `partial`, aliased signal, `bus.async_fire`, `setattr` / `replace` /
Subscript Store, `0.750` / module-local threshold, template read, registry-resolved PLB id, polling ledger); (2) per
rule a minimum real-tree hit count (the visitor must find the seeded rows); (3) a mutation control: copy one clean
module to a temp tree, inject one leak per rule, run the scanner on the copy, expect exactly that hit; (4) the
private-name harvest asserts > N names per class (today's `> 100` check). Stated limits that stay stated: AST
scanning cannot prove absence for dynamic names (`getattr(x, name_var)`), cross-module dataflow beyond one
function-return hop is not tracked, reads in `quality/` and `scripts/` are not scanned.

## 6. Conforming edits each remaining plan needs

- **NVR witness W2-W6:** add a "Layer conformance" table (contract §6). W2 = the evidence service of contract §2.6
  and answers for every egress/perimeter camera (cameras outside rooms have no stream-health answer today). P3, P4,
  S11, C2 migrate to it; P3 is F2 ingest and moves only with a byte-identical house-count test. W5c replaces C1. W4
  Protect clips keep the clip path.
- **Interior vision:** unnamed records via `PersonSightingProducer._emit_unnamed` (a sibling store is a second F4
  store); its term enters `deconflict_house` as a pulled provider, keyed by physical camera, health via the named
  stream-health read.
- **Step 7 (direction-aware egress):** `camera_egress` F5 through G4; candidate provenance on `CrossingRecord`, not on
  the census (P2); INV-CENSUS-HOME unchanged.
- **Step 8 (identity actions v6):** reads `view_for_class("comfort")` (state that it resolves to trust until rung 3
  is legal); departures from G1 or `get_crossings_since`, never raw `person.*`.
- **Music repair:** class comfort; F4-BLE via `ura_person_location_change`; C4 reads → G6.
- **Census-p2 (in flight):** rebase on batch-2; G7 (H3) before merge; owns G8 (crossing-vision row store +
  `_ledger_terms`).
- **Crossing-vision fast stage (in flight):** rebase on census-p2 after it merges; provisional rows only, no
  `apply_term`, `people_count` None on blank; G8 merge-gate test (terms only from stage-B rows).
- **Read API ship 3:** G1-G6 + G9, the class-taking `house_census_view`, the R1-R9 guard; the room-occupancy phone
  filter behind operator Q1 and its recorder probe.
- **Security (S1):** STALE-SOURCE-ARRIVAL-CONSUMERS-1 moves S1 onto G1 with delivery unchanged (windows, guests).
  S5 is not wired (operator decision).

## 7. Arc-map update (for the orchestrator; this audit does not edit the map)

Add a row "PERSON-AWARENESS-LAYER-CONTRACT-1 (contract + guard)", F = all, reader classes all, seams = every ingest
point in contract §2, order = before steps 6-9 finish build. Add merge M13: read-API ship 3 (G1-G6, G9 + guard) +
LOCK restart plan + STALE-SOURCE-ARRIVAL-CONSUMERS-1 share G1 (one edge ledger, one owner: residency). Add merge
M14: census-p2 + crossing-vision fast stage share the crossing-vision row store (G8, owner census-p2, merge order
census-p2 first). Add to the step list: "every plan carries the contract §6 conformance table; the merge step runs
it". Fix stale fact: the F4 accessor has two production readers.

## 8. Unknowns

- `transitions.py:422` consumer behaviour (H6 path validation) not read.
- Live fire count for S1 (how often security was armed during a blip) not queried.
- The §2.4a room-occupancy probe (ticks BLE-held by a phone-left-behind person) not yet run; it gates operator Q1.
- Whether HVAC should own the BLE pre-arrival toggle at all (P5) is a design question outside this audit.
