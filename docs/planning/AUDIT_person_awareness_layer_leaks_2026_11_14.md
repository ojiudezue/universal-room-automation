# AUDIT: person-awareness layer leaks (framing D, diff-blind, whole codebase)

Date 2026-11-14. Author ura-planner. Read-only; the only writes are this file and the contract
`docs/planning/CONTRACT_person_awareness_layer.md`. Contract §2-§4 define "goes through the layer".

Code read: `release/batch-2` @ dbff8335 (= develop v5.108.21 + read API ship 2 + stream health S2 + perimeter
batch), plus `feature/census-deconfliction-p2-ledger` @ d52ea568, `feature/crossing-vision-fast-stage` @ a47e4c5b,
`feature/music-following-repair` @ 0ac39b2a (no code commits; worktree clean, so music findings are on batch-2
code). Line numbers are batch-2 unless a branch is named. Method: a read-only scanner
(`.claude/tmp/pa_scan.py`, 20 regex families: raw `person.*` reads, device_tracker, Bermuda, census object,
`person_coordinator` object and `.data`, egress/transit objects, the F3 bus event, the three signals, crossing vision,
stream health, camera person entities, read-API calls, deconflict, sightings, census writes, census entities, id
rules) run over the whole package, then each hit read in context. Pre-existing code is in scope (most leaks below
predate the arc).

Docs read: CLAUDE.md; `ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`; `ARC_identity_vision_census_map.md`;
`PLANNING_person_awareness_read_api.md`; `PLANNING_census_deconfliction.md`; `PLANNING_nvr_witness_layer.md` §1-§6
and headings; `AUDIT_person_awareness_interface_inventory_2026_11_13.md` (whole); grep passes over
`PLANNING_crossing_vision.md`, `PLANNING_camera_input_stream_health.md`, `PLANNING_vision_interior_sightings.md`,
`PLANNING_egress_direction_aware_identity.md`, `PLANNING_identity_actions_v6.md`, `PLANNING_music_following_repair.md`.
**Presence docs:** `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` read completely (§0-§11 + addendum, incl. the §10
corrections ledger; nothing below re-asserts a ledger claim) and `SENSOR_FLEET_CLASSES.md` read completely.
`IDENTITY_FUSION_CAMERAS_MANUAL.md`: §3 and §5.5 read in full, the rest by heading only (stated gap).
`PLANNING_person_sighting_layer.md` §2A was not re-read here; its rules are taken from CLAUDE.md and the census plan.

Code-vs-doc contradiction found (code wins): none new. The inventory's "F4 accessor has zero production callers"
is now stale on batch-2: `get_last_person_sighting` is called at `binary_sensor.py:2246` and `sensor.py:3590`
(PLB camera leg, display), as the presence doc §3 already says.

## 1. Answer first

- **35 sites do not go through the layer** (by class: security/access 11, house_state 6, comfort 4, notification 2,
  display 8, producer-side ingest 4). Plus 24 conforming consumer/producer sites listed for completeness (§3).
- The ingest half is where the layer is weakest: **F1 edges have three ledgers and four raw `person.*` listeners**,
  **F5 has three raw dict sends and a fourth private arrival producer**, and **F2 / F3 have no named read for
  stream health or crossings history**, so consumers keep private caches.
- The read half is mostly in place on batch-2 (F2 display readers migrated to `house_census_view`, F1 HVAC readers
  on `persons_home_for_trust`, F5 readers on `PersonArrivingPayload`), but **every migrated F2 reader passes a
  literal view `"trust"`** instead of a class, so INV-LAYER-CLASS cannot yet be enforced.
- **Highest live risk:** S1, the Security Coordinator's own geofence listener adds an expected arrival (alarm
  suppression window 10 / 30 min) on any raw `not_home -> home`, bypassing the stale-source rule the lock regime
  applies (`arrival_edges.stale_source_arrival`), so the 78 sub-second iPad-type blips measured 11-05..11-12
  (presence doc §10 #33) would each open a suppression window while armed.

## 2. Leak table (NO rows), ranked by consumer class then live risk

Key: Fact; P = producer side, C = consumer side; class per contract §2.

### 2.1 Security / access (11)

| # | Site | Fact | P/C | Class | What leaks | Fix (route through) | Risk |
|---|---|---|---|---|---|---|---|
| S1 | `domain_coordinators/security.py:2231-2288` `_resubscribe_geofence_persons` / `_handle_person_state_change` | F1 edge → F5 effect | C (acts as a 4th arrival producer) | access (alarm suppression) | own `person.*` listener; `not_home -> home` adds expected arrival 10 min, `not_home -> zone` 30 min; no stale-source or boot test | G1 `subscribe_resident_edges`, apply `arrival_edges.stale_source_arrival` + boot window; card STALE-SOURCE-ARRIVAL-CONSUMERS-1 (extend, do not add a second predicate, arc map M9) | **HIGH** (suppression on a blip while armed) |
| S2 | `domain_coordinators/security_lock_regime.py:633, 777, 1199, 1759, 1942, 2004, 2453, 2609, 2652, 2714` + `_on_person_event` + own `_last_real` | F1 edges | C + 2nd store | access (unlock / lock) | raw edge reader by design, but a second edge ledger (INV-ONE-EDGE-LEDGER) | G1: ResidencyTracker is the one ledger; lock subscribes and keeps only its hold logic. Tier 3; fold into LOCK restart plan (M8). Allowlist until then | HIGH if changed carelessly; current behaviour is correct |
| S3 | `security_lock_regime.py:1855, 1868, 1892` (`record_bermuda_moves(pc.data)`) | F4-BLE | C | access | reads `PersonTrackingCoordinator.data` raw to stamp moves | G6 `location_moves_since(t)` on PersonCoordinator (owner stamps; consumers read) | MED |
| S4 | `security_lock_regime.py:1811` → `arrival_edges.door_entry_areas` (`arrival_edges.py:329`) | F3 config | C | access | reads `EgressDirectionTracker` privates `_egress_entities`, `_interior_neighbours_by_group` | G5 `EgressDirectionTracker.entry_areas()` | MED (the wrong-object bug here already happened once, presence doc §1) |
| S5 | `security.py:283, 346` `context.get("census", {})` | F2 | C | security | no producer anywhere (grep `"census":` → 0 hits): `SanctionChecker` census leg always `{}` | zero-fire finding; when wired, `get_house_census(view_for_class("security"))`; until then KEEP + DOCUMENT dead | LOW (dead) |
| S6 | `perimeter_alert.py:1110` own `ura_person_egress_event` listener → `_note_egress_identity` 600 s cache | F3 | C + private store | security | private crossing history | G2 `get_crossings_since(t, camera)` | MED |
| S7 | `perimeter_alert.py:6226` raw `person.{slug}`; own `_person_arrivals` ledger + listener; `:5958` `pc.data` | F1 edges, F4-BLE | C + 3rd store | security | third edge ledger, raw store | G1 + G6 | MED (de-escalate only) |
| S8 | `perimeter_alert.py:6003` egress tracker privates via `door_entry_areas` | F3 config | C | security | as S4 | G5 | LOW |
| S9 | `perimeter_alert.py:1851-1854, 5907` `census.resolve_face_legs` | F2 evidence | C | security | a consumer deciding on raw face legs (public method, but evidence, not a fact) | read F4 (`get_last_person_sighting`) or F3 identity via G2; keep legs for producers only | MED |
| S10 | `perimeter_alert.py:5339, 5419, 5868-5871` `tracked_person_slugs`, `known_face_guests`, `canonical_person_slug` | id roster | C | security | census as roster owner | `person_ids` + a public roster read on presence | LOW |
| S11 | `perimeter_alert.py:5038` `_apply_single_source_gate`, `_leg_tag` / `base_engine` (`:578-708`) | NVR comparison #3 | C | security | own family classifier, partly by name | NVR witness W2 (`family_of`, `corroborated`) | MED |

### 2.2 House state (6)

| # | Site | Fact | P/C | What leaks | Fix | Risk |
|---|---|---|---|---|---|---|
| H1 | `domain_coordinators/presence.py:3283` boot seed reads `sensor.universal_room_automation_identified_persons_in_house` state into `_census_count` (AWAY input) | F2 | C | a display entity state feeds a trust input | seed from `house_census_view(hass, cls="house_state")` (census object exists before presence finishes setup) or wait for the first signal; golden test `test_boot_seed_ignores_vision_sensors` already planned | MED (boot AWAY) |
| H2 | `presence.py:2443, 4660, 4854, 5306, 6093-6099, 6275, 6457, 7343-7441, 8253-8255, 8928-8932` | F1 level / F4-BLE | C | inference reads `person_coordinator.data` directly (~12 sites, incl. `all_tracked_persons_away`) | G6 frozen `PersonCoordinator.snapshot()` read, one per tick; Tier 3 (house state); allowlist max 12 until then | MED (correct today; drift risk) |
| H3 | `crossing_vision.py:1104-1143` `_held_inputs` (census-p2 branch) | evidence (stream health) | P (F2 term provider) | scans every value in `hass.data[DOMAIN]` for a `camera_input_stream_dead` attribute (duck-typed reach-around). A held dead input missed here lets the empty anchor fire under a sleeping guest | G7: call `camera_stream_health.input_stream_dead` / `entity_stream_view` (exist on batch-2 `:529-658`); rebase census-p2 on batch-2 before merge | MED (awareness only today; trust at rung 4) |
| H4 | `binary_sensor.py:2176-2270` `PersonPhoneLeftBehindSensor` (AWAY input) | F2, F4-BLE | C | `house_census_view(hass, "trust")` literal; `pc.data.get(person)` raw | `house_census_view(hass, cls="house_state")`; G6 | LOW (identical while F-LEAD off) |
| H5 | `camera_census.py:2853-2858, 3239-3249` `_get_ble_persons` | F4-BLE → F2 | P (member reads member store) | `pc.data` raw inside the F2 producer | G6 `persons_located_home()` | LOW |
| H6 | `transit_validator.py:305, 669-911` `_camera_sightings` legacy store; read by `transitions.py:422` path validation | F4 | P (2nd F4 store) | second sighting store (unidentified only since PLB leg) | move path validation to F4 store; then DELETE (dead-and-footgun bucket) | LOW |

### 2.3 Comfort (4)

| # | Site | Fact | What leaks | Fix | Risk |
|---|---|---|---|---|---|
| C1 | `fan_veto.py:380-445` | room camera body evidence (NVR agreement) | reads URA's own `binary_sensor.*_camera_person_detected` STATE and `agreement` / `confidence` attributes for the veto rebuttal; room matched by `room_name` or entry title, slug fallback (name guessing) | room coordinator public getter `camera_person_evidence()` (on, families agreeing) from W5c; registry-only room resolution | MED (fan veto) |
| C2 | `binary_sensor.py:1821-1889` `CameraPersonDetectedSensor` agreement | NVR comparison #4 | counts integrations/sources, not NVR families | W5c `families_on_now` | MED |
| C3 | `fan_veto.py:309-330` | F4-BLE | `get_persons_in_room` (public) then `pc.data[...]["tracking_status"]` raw | G6 `get_persons_in_room(room, active_only=True)` | LOW |
| C4 | `music_following.py:535-538, 597-599, 656-669` | F4-BLE | `person_coord.data` raw | G6 / event payload (music repair D1 already carries `ble_confidence` in `ura_person_location_change`) | LOW |

UNVERIFIED (not counted): `hvac.py:1239` and `presence_fan_recheck.py:672, 1168` fetch the person coordinator
object; the method used after the fetch was not read in this audit.

### 2.4 Notification (2)

| # | Site | What leaks | Fix | Risk |
|---|---|---|---|---|
| N1 | `transit_validator.py` `_arrival_departure_notify` (inside `EgressDirectionTracker`) | notification policy hosted in the F3 producer (reads `CONSUMER_CLASS_MIN_CONFIDENCE` correctly) | D8 moves the one amend/notify function to an NM-side consumer reading `get_last_crossing` + `min_confidence("notification")`; allowlisted exception until then | LOW |
| N2 | `notification_manager.py:4763` raw `person.*` for a display name | `display_of` / friendly-name helper in `person_ids` + presence | LOW |

### 2.5 Display (8)

| # | Site | What leaks | Fix | Risk |
|---|---|---|---|---|
| D1 | `sensor.py:3758-3761, 3809, 3852, 4885, 5616` census sensors read `census.last_result` / object | owner-display exemption (census's own entities): allowlist with counts | — | none |
| D2 | `sensor.py:4567` egress tracker object; `:6658` transit validator object | F3 display through objects | `get_last_crossing` / G2 | LOW |
| D3 | `aggregation.py:6102-6192` `PersonLocationSensor` finds Bermuda sensors by NAME pattern `sensor.bermuda_{first_name}_` | violates "Registry, never name guessing" | reuse PersonCoordinator's registry-resolved area sensor (`_find_bermuda_area_sensor`) via a public getter | LOW (display) |
| D4 | `aggregation.py:2193-2327, 5575-6677` (26 `person_coordinator` fetches, `.data` loops) | raw store | G6 or owner-display allowlist | LOW |
| D5 | `binary_sensor.py:1944-2008` `URAUnexpectedPersonSensor` | `pc.data` + literal `"trust"` | class `display`; G6 | LOW |
| D6 | `binary_sensor.py:2058` `CensusMismatchSensor` reads `sensor.universal_room_automation_persons_in_house` STATE | URA entity state as input | `house_census_view(hass, cls="display")` | LOW |
| D7 | `coordinator.py:1383` room identified persons via person coordinator; `switch.py:963` census object; `binary_sensor.py:3401, 3432, 3501` census privates (allowlisted on batch-2) | objects / privates | allowlist (counted) or G6 | none |
| D8 | `house_status.py:213-244` builds person list from `pc.data` keys | raw store (display, `who()`) | G6 | none |

### 2.6 Producer-side ingest (4)

| # | Site | What leaks | Fix | Risk |
|---|---|---|---|---|
| P1 | `presence.py:5678, 5937`, `person_coordinator.py:1172` | three raw dict sends of `SIGNAL_PERSON_ARRIVING`; no ingest function | G4 `dispatch_person_arriving(hass, PersonArrivingPayload)` | LOW-MED (shape drift; D8 adds a 4th source) |
| P2 | `transit_validator.py:1563-2080` `census.set_egress_identity_last_attach`, `note_*`, `consume_ble_arriving_legs` | F3 provenance and counters stored ON the F2 owner | move attach record + counters to the tracker; census keeps BLE-leg consumption as its own ingest | LOW |
| P3 | `camera_census.py:2395` `_cross_validate_platforms` | NVR comparison #1 (own classifier, `CameraInfo.platform` partly by suffix) | W5b `platform_for` | MED (house count) |
| P4 | `transit_validator.py:2733` `_count_platforms_fired` | NVR comparison #2 (substring test) | W2 `corroborated` | LOW (display confidence) |

## 3. Conforming sites (YES), for completeness

F1: HVAC `hvac.py:3416, 3994`, `hvac_fans`, `hvac_zones.py:2708` (persons_home_for_trust); aggregation zone
fallbacks; `perimeter_alert.py:2162-2232` (`get_residents_home_count`, `get_recent_resident_arrival`);
`sensor.py:5853, 6183-6201`; `house_status.py:220-244` (trust helper). F2: `sensor.py:5237, 5252`,
`aggregation.py:6744, 6773`, `binary_sensor.py:1953, 2001, 2220, 2270` (through `house_census_view`, but literal
view, see INV-LAYER-CLASS); presence `_handle_census_update` via `SIGNAL_CENSUS_UPDATED`; census-p2 deconflict call
site and `census_tick` pull. F3: four entry/exit sensors (`sensor.py:4819, 4950, 5060, 5110`, declared bus);
`person_sighting.py:449`; `crossing_vision.py:58` listener; census register/evict (`transit_validator.py:2321,
2325`). F4: PLB / NextRoom via `get_last_person_sighting`. F5: HVAC `hvac.py:1511`, security `:819`, lock regime,
music (`PersonArrivingPayload`). Evidence: stream health S2 readers (`presence.py:827-4545`, `occupancy_substrate.py:355,
950`, `camera_census.py:2754`, `fan_veto.py:476`).
Excluded (actor identity, not person awareness): `hvac_override.py:895` arrester immunity and
`notification_manager.py:3835` (HA `user_id` → person for "who pressed"); `__init__.py:4563` config validation.

## 4. Top 10 leaks with fixes

1. S1 security geofence expected-arrival → G1 + stale-source rule (HIGH).
2. S2 lock regime second edge ledger → G1, Tier 3 inside the LOCK restart plan (HIGH blast radius).
3. S7 perimeter third ledger + raw person + `pc.data` → G1 + G6.
4. H1 boot seed from a display entity into an AWAY input → `house_census_view(cls="house_state")`.
5. H2 presence inference reads `pc.data` at ~12 sites → G6 snapshot, Tier 3.
6. C1 fan veto reads its own entity state/attributes, room by title → room-coordinator getter from W5c.
7. H3 crossing-vision `_held_inputs` duck-typed hass.data scan → G7 named stream-health read (fix before census-p2 merges).
8. S6 perimeter private crossing cache → G2.
9. S3 / S4 / S8 access reads of `pc.data` and tracker privates → G5 + G6.
10. P1 F5 raw sends → G4 one dispatch function (before D8 adds `camera_egress`).

## 5. The code guard (extends `test_no_private_census_reads_outside_module`, batch-2 `quality/tests/test_person_awareness_read_api_ship2.py:494-602`)

New file `quality/tests/test_person_awareness_layer_guard.py`; the existing census test stays as rule R1's first
member. AST only, no imports of production code beyond source text.

| Rule | Detects | Receiver resolution |
|---|---|---|
| R1 private member read | `obj._x` / `getattr(obj, "_x")` where `_x` is a private of a layer member class (`PersonCensus`, `EgressDirectionTracker`, `TransitValidator`, `PersonTrackingCoordinator`, `PersonSightingProducer`, `CrossingVisionShadow`, `CrossingLedger`, `PresenceCoordinator`), outside the class's own module | names harvested per class like `_census_private_names`; receiver = (a) text regex per class (today's `cens` rule) AND (b) intra-function dataflow: any name assigned from `hass.data[...][K]` / `.get(K)` with K in {`census`, `egress_tracker`, `transit_validator`, `person_coordinator`, `crossing_vision`} is bound to that class (closes the stated "name without cens" hole) |
| R2 store read | `.data` on a person-coordinator receiver; `.last_result` on a census receiver; `_last_sightings`, `_camera_sightings` | as R1 |
| R3 raw entity read | `hass.states.get/async_all` and `async_track_state_change_event` whose argument is a constant or f-string starting `person.`, `device_tracker.`, `sensor.bermuda`, or the domain `"person"`; any read of a URA person-awareness entity id (`*_camera_person_detected`, `*persons_in_house`, `*identified_persons_in_house`, `*guest_count`) | literal / f-string head |
| R4 hass.data scan | a loop over `hass.data[DOMAIN].values()` (or `.items()`) followed by `getattr(<loop var>, <const>)` | loop-target tracking (catches H3) |
| R5 literal view | `house_census_view` / `get_house_census` called with a constant view; any F2 read not wrapped by `view_for_class` | call args |
| R6 F5 send | `async_dispatcher_send(..., SIGNAL_PERSON_ARRIVING, ...)` outside `signals.dispatch_person_arriving` | call args |
| R7 F2 write | Store to a `CensusZoneResult` count field name (harvested from the dataclass) outside `camera_census.py` / `census_deconflict.py` | attribute Store ctx |
| R8 confidence literal | a Compare between `identity_confidence` / `confidence` and the float literals 0.75 or 0.9 outside `const.py` | Compare nodes |
| R9 `person.*` listener | any listener over person entities outside `presence._handle_geofence_change` / `ResidencyTracker` | call args + `async_all("person")` feeding a tracker |

Allowlist: one dict keyed `(rule, file, symbol)` → `{"reason", "card", "max"}`. The test fails when (a) a hit has
no entry, (b) a hit count exceeds `max`, (c) an entry is no longer hit (stale, remove it), or (d) the SUM of `max`
exceeds the pinned `LAYER_ALLOWLIST_TOTAL` (a ratchet constant that may only go down; raising it is a reviewed
contract change). Owner-display exemptions (D1, D7) are rows with reason `owner_display`. Seed rows = the §2 table
(e.g. R9 lock regime: card LOCK-REGIME-BOOT-REALLY-AWAY-1 plan, max 1 listener; R2 presence `.data`: card G6, max
12; R1 sensor census diagnostics: the 39 batch-2 rows).

Anti-hollow: (1) per rule, parametrised positive and negative snippets (the `test_private_census_detector_controls`
pattern, incl. the alias case `t = hass.data[DOMAIN].get("egress_tracker"); t._egress_entities` and the H3 scan
shape); (2) per rule a minimum real-tree hit count (the visitor must find the seeded rows, so a broken visitor fails);
(3) a mutation control: copy one clean module to a temp tree, inject one leak per rule, run the scanner on the copy,
expect exactly that hit; (4) the private-name harvest asserts > N names per class (today's `> 100` check). Stated
limits: dynamic `getattr` with a non-constant name; objects passed as arguments across functions without a
`hass.data` origin; reads in `quality/` and `scripts/` are not scanned.

## 6. Conforming edits each remaining plan needs

- **NVR witness W2-W6:** add a "Layer conformance" table (contract §6). W2 = the evidence service of contract §2.6;
  P3, P4, S11, C2 migrate to it (already its §4.2). W5c must also replace C1: fan_veto reads a room-coordinator
  getter, not the entity state/attributes. W4 Protect clips keep the clip path. Guard rows for the four sites are
  removed as each migrates.
- **Interior vision:** unnamed records via `PersonSightingProducer._emit_unnamed` (plan §108 says "sibling type,
  no second emit"; a sibling store is a second F4 store, contract §2.4); D4 term enters `deconflict_house` as a pulled
  provider at the one census site, keyed by physical camera, health via the named stream-health read.
- **Step 7 (direction-aware egress):** `camera_egress` F5 through G4; candidate provenance on `CrossingRecord`,
  not on the census (P2); INV-CENSUS-HOME unchanged.
- **Step 8 (identity actions v6):** reads `view_for_class("comfort")` (state that it resolves to trust until rung 3
  is legal); departures from G1 edges or `get_crossings_since`, never raw `person.*` (plan line 149 offers the raw
  edge: replace); quiet hours read through NM public method is fine (not a person fact).
- **Music repair:** declare class comfort; consume F4-BLE via `ura_person_location_change` (D1 additive keys are
  conformant); replace C4 reads with G6.
- **Census-p2 (in flight):** G7 before merge (H3).
- **Read API:** a ship 3 card for G1-G6 + the class-taking `house_census_view` + R1-R9 guard.

## 7. Arc-map update (for the orchestrator; this audit does not edit the map)

Add a row "PERSON-AWARENESS-LAYER-CONTRACT-1 (contract + guard)", F = all, reader classes all, seams = every ingest
point in contract §2, order = before steps 6-9 finish build. Add merge M13: read-API ship 3 (G1-G6 + guard) + LOCK
restart plan + STALE-SOURCE-ARRIVAL-CONSUMERS-1 share G1 (one edge ledger, one owner: residency). Add to §4 step
list: "every plan carries the contract §6 conformance table; the merge step runs it". Fix stale fact: the F4
accessor now has two production readers.

## 8. Unknowns

`hvac.py:1239`, `presence_fan_recheck.py:672, 1168` methods after the person-coordinator fetch; `transitions.py:422`
consumer behaviour; live fire counts for S1 (how often security was armed during a blip) were not queried.
