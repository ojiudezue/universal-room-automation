# PLANNING: person-awareness read API (one read surface for F1-F5, one id rule)

Cards: PERSON-AWARENESS-READ-API-1 (main), PERSON-ID-NORMALISE-ONE-RULE-1 (merged here), crossing-vision P2-RA (merged
here; the crossing-vision and census plans depend on ship 1). Tier 2 (both ships byte-identical, mutation-anchored).
Clean consolidation 2026-11-13 of crossing-vision rev 7.1 §B11.3 (`plan/crossing-vision` @ 1e76c98a) and
`AUDIT_person_awareness_interface_inventory_2026_11_13.md` §4-§7. Siblings: `PLANNING_census_deconfliction.md` (owner of
the promotion ladder this API reads), `PLANNING_crossing_vision.md`, `PLANNING_person_sighting_layer.md` (F1-F5 home).

## 1. Objective and charter

Charter: `docs/planning/ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md`, "The operator's goals". Goals served:
"assist arrivals accuracy and personalization", and the process goals "clean and streamlined... not Frankenstein" and
"I didn't want artificial seams that will sink us later." This plan expresses the F1-F5 model in code so every consumer
reads each fact one way, by consumer class.

Objective: one public read surface on `PresenceCoordinator` (the inventory's recommended home: it already owns the F1
getters `get_residents_home*` `presence.py:5409-5434`, the F5-adjacent `get_recent_resident_arrival` `:5436`, the F4
store `get_last_person_sighting(s)` `:5907-5917`), public methods on `PersonCensus` and `EgressDirectionTracker` for
what producers now reach as privates, and one person-id rule. Ship 1 is the minimal slice every new consumer is born
on. Ship 2 migrates the existing readers.

## 2. F1-F5: produced and consumed

Produces no fact. Read surface for all five:

| Fact | Owner (code) | Read API |
|---|---|---|
| F1 P home | HA `person.*` + `PersonCoordinator` (`person_state_for_trust`, `person_coordinator.py:144`) | REUSE `get_residents_home*`; EXTEND with an optional person list (ship 2) |
| F2 who is in the house | `PersonCensus` | NEW `get_house_census(view)`; NEW public census methods (ship 2) |
| F3 door crossing + identity attach | `EgressDirectionTracker` (`transit_validator.py:1007`; `_resolve_direction` `:2096`, bus fire `:2191`, `_arrival_departure_notify` `:2603`). Not `TransitValidator` (`:282-1006`): plan §2A and manual §5.5 name it wrongly; fixed in the same commit as this plan | NEW `get_last_crossing(camera=None)` on `EgressDirectionTracker`, wrapped on presence |
| F4 P seen at X at T | sighting producer | REUSE `get_last_person_sighting(s)` (no production callers today) |
| F5 P is arriving | geofence `presence.py:5598`, BLE `person_coordinator.py:1146`, D2 `presence.py:5857` | REUSE `SIGNAL_PERSON_ARRIVING`; EXTEND with one normalised payload type (ship 2) |

Arrival record (F3 attribute, crossing-vision plan): NEW `get_last_arrival_record()`.

## 3. Readers by consumer class

The class decides the view. `view_for_class(cls)` implements the census plan's promotion ladder (§3.2 there):

- returns `awareness` ONLY when `cls` is in `CROSSING_VISION_CONSUMER_CLASSES` (whose legal members raise at import if
  unknown) AND `switch.ura_crossing_vision_census_authority` is ON;
- every other input (any class not promoted, unknown or misspelt strings, switch entity missing) → `trust`. Allow-list,
  never a deny-list.

Consumer-class confidence table (NEW, one object replacing scattered literals): `security` ≥ 0.9 (de-escalate or
annotate only, manual §5.5(a)); `notification` ≥ 0.75 for a name; `display` none; `comfort` and `house_state` use the
trust view and add no identity threshold. Replaces `ARRIVAL_NAME_CONFIDENCE_THRESHOLD` class attribute
(`transit_validator.py:2601`) and the inline 0.9 at `perimeter_alert.py:5019` (const `const.py:2663`) by reference,
values unchanged.

Callers in ship 1 (all born on the API): the two awareness entities, `crossing_vision_last`, the arrival count
follow-up, the PERSON-PROFILE-PREFERENCES-1 read seam (`get_house_census(view_for_class("display"))`,
`get_last_arrival_record()`). The presence inference path never calls it.

## 4. Invariants

- **INV-RA-BYTE-IDENTICAL.** Every migrated reader produces the same outputs as develop for the same inputs (ship 2:
  per-site golden); ship 1 changes no existing reader.
- **INV-RA-TRUST-DEFAULT.** `view_for_class` returns `trust` for every class not in the active promoted set, under every
  class-set and switch value. Test `test_view_for_class_security_always_trust` parametrised over class sets, switch
  values and `house_state`, `security`, `hvac`, `comfort`, `""`, `"Display"`, `"suggestion"`.
- **INV-RA-NO-INFERENCE-READ.** `aware_` and `vision` appear in `presence.py` only inside `get_house_census` /
  `view_for_class`. Mutation drill: in `_handle_census_update`, assign `get_house_census("awareness").total` to the value
  it takes from `interior_count` → `test_away_tick_identical_with_vision_payload` (census plan) red. Calling and
  discarding is not a drill.
- **INV-ID-ONE-RULE.** Every name → entity-id / slug / display conversion goes through the one module; for display-name
  config (`entry.data`) and entity-id config (`entry.options`) the census, sighting, egress BLE leg and perimeter return
  the same slug. Falsified today by Residuals A-D under a display-name config (§5 ship 1).

## 5. Deliverables

### Ship 1 (Tier 2; lands before the census plan's CD1)

**RA1. `get_house_census(view: Literal["trust", "awareness"]) -> HouseCensusView | None`** on `PresenceCoordinator`.
Frozen dataclass: `identified`, `unidentified_or_guests`, `total`, `provenance`, `agreement`, `as_of`. Reads
`census.last_result.house` (never `_census_count`), sync, never raises; missing census → None. Trust view = existing
fields; awareness view = the census plan's `aware_*` fields (until they exist, awareness returns the trust values with
`provenance = camera`).
- **Tests:** `test_get_house_census_trust_equals_last_result`, `test_get_house_census_missing_census_none`.

**RA2. `view_for_class(cls) -> str`** per §3. **Tests:** `test_view_for_class_security_always_trust`,
`test_view_for_class_display_follows_class_set`.

**RA3. Consumer-class confidence table** (`CONSUMER_CLASS_MIN_CONFIDENCE`, rung 1, const) + the two call sites
referencing it. **Test:** `test_class_thresholds_unchanged` (0.75 and 0.9 equal develop at both sites). Mutation: drop
the table reference at `_arrival_departure_notify` and hard-code 0.6 → red.

**RA4. One id rule.** REUSE `tracked_person_entity_id` (`person_coordinator.py:130`); NEW beside it `slug_of(entity_or_name)`
and `display_of(slug)`. Route the four residual readers through it: Residual A `camera_census._get_tracked_person_slugs`
(`camera_census.py:3900-3912`, no space → `_`), B wifi-guest tracked list (`:6159-6176`, raw entry used as an entity id),
C face-name tracked list (`:6311-6320`), D `perimeter_alert.py:5117-5121`. Residual A also feeds `person_sighting._emit`
(`:596`) and `transit_validator.py:1771, 1905`, so a display-name config would zero sightings and the egress BLE leg.
`_canonical_person_slug` (`camera_census.py:3915`) stays the face first-name mapper and becomes public.
- **Tests:** `test_residuals_same_slug_display_and_entity_config` (parametrised A-D over `entry.data` display names vs
  `entry.options` entity ids), `test_slug_of_display_of_roundtrip`. Mutation: revert Residual A → red.
- **Live:** sightings and census identified set unchanged after deploy (same slugs as the day before).

**RA5. `get_last_crossing(camera=None)`** on `EgressDirectionTracker` (camera, direction, ts, person_id, provenance,
confidence, `source_ref`), wrapped on presence; and `get_last_arrival_record()` reading the crossing-vision arrival
record store (returns None until that ships).
- **Test:** `test_get_last_crossing_matches_bus_event`.

**Live (ship 1):** no entity or log change; `grep` shows the new symbols called only from the listed callers.

### Ship 2 (Tier 2; parallel any time after ship 1)

**RA6. Public `PersonCensus` methods** replacing ~20 private methods called 40+ times from `transit_validator.py`,
`person_sighting.py`, `perimeter_alert.py`, `__init__.py`, `sensor.py` (inventory §4): `tracked_person_slugs()`,
`canonical_person_slug()`, `face_suppressed_now()`, `known_face_guests()`, `resolve_face_legs()`, plus thin public
wrappers for the egress-identity counters. Callers migrated; privates stay as implementations.
**RA7. F2 readers** (`sensor.py:3715, 5179`, `binary_sensor.py:1937, 1981, 2186`, `aggregation.py:6740, 6773`) read
`get_house_census("trust")`; delete the dead `get_room_identified_persons` hook (`coordinator.py:1365`) and the dead
seed branch reading `hass.data[DOMAIN]["camera_integration_manager"]` (`presence.py:3222`; the sensor fallback works).
**RA8. F1 per-zone helper:** extend `get_residents_home` with an optional person list; replace the six zone loops
(`hvac.py:3415, 3993`, `hvac_fans.py:1529`, `hvac_zones.py:2726`, `aggregation.py:4759, 4896`). HVAC files: the builder
reads `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` completely first.
**RA9. Id copies:** the 14+ inline name → slug copies and 5 `.title()` inverses (inventory §5.2) route through RA4.
**RA10. F5 payload:** one normalised payload type; `security.py:2395-2410` and `music_following.py:560-568` drop the
dict-or-attribute dual read.
- **Tests:** per migrated site a golden (INV-RA-BYTE-IDENTICAL) and a mutation anchor; `test_no_private_census_reads_outside_module`
  (grep test).
- **Live:** census sensors, NM arrival text, HVAC night-trust holds unchanged on the first day.

Not consolidated, by design (concept splits, Bug Class #63): levels (`get_residents_home`) vs raw edges (residency,
lock regime and identity vetoes read raw state on purpose); seen (F4) vs counted (F2) as separate methods.

## 6. Knobs

| Knob | Default | Rung | Why |
|---|---|---|---|
| `CONSUMER_CLASS_MIN_CONFIDENCE` | security 0.9, notification 0.75, display 0 | 1 | Doctrine values; changing them requires review |
| (reads) `CROSSING_VISION_CONSUMER_CLASSES`, `switch.ura_crossing_vision_census_authority` | census plan | 1 / 3 | Owned by the census plan |

No other numbers.

## 7. Dependencies and sequence

Ship 1 first in the arc after the built ships (perimeter Part A, phone-left-behind camera leg, crossing-vision Phase 1);
before the census plan CD1. Ship 2 in parallel any time after ship 1. One adversarial plan review (Tier 2) plus a
goal-fidelity framing; two code reviews per ship; ship 2 HVAC sites get a framing that reads the HVAC state of play.

## 8. Non-goals

Any behaviour change; new facts; merging levels with edges or F4 with F2; the resident-edge ledgers in the lock regime,
residency and perimeter (inventory finding 7, separate card if wanted); `CameraResolver` construction dedup (four
constructions, separate card if wanted); the security `context["census"]` producer (untraced in the inventory).
