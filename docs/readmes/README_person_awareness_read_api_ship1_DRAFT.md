# Person-awareness read API, ship 1 (DRAFT, version assigned at deploy)

Card: PERSON-AWARENESS-READ-API-1 (with PERSON-ID-NORMALISE-ONE-RULE-1). Plan:
`docs/planning/PLANNING_person_awareness_read_api.md` §5 ship 1 (RA1-RA5). Tier 2. Branch
`feature/person-awareness-read-api-ship1`.

## Identity model

Produces no fact. Read surface for F2 (house census, `get_house_census`) and F3 (door crossing,
`get_last_crossing`); `get_last_arrival_record` is the F3-attribute seam for crossing-vision. Consumer class
decides the view (`view_for_class`) and the identity confidence (`CONSUMER_CLASS_MIN_CONFIDENCE`).

## What changed

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

## Knobs

| Knob | Default | Rung | Why |
|---|---|---|---|
| `CONSUMER_CLASS_MIN_CONFIDENCE` | security 0.9, notification 0.75, display 0 | 1 | Doctrine values (manual §5.5); a change needs review |
| `CROSSING_VISION_CONSUMER_CLASSES` / `_LEGAL_` | `{display}` / `{display, notification}` | 1 | Owned by the census plan §3.2 |

## Tests

`quality/tests/test_person_awareness_read_api.py` (real HA core, real URA modules): `test_slug_of_display_of_roundtrip`,
`test_residuals_same_slug_display_and_entity_config` (A-D x display / live-entity config),
`test_class_thresholds_unchanged`, `test_consumer_class_table_values`, `test_consumer_classes_rejects_illegal`,
`test_view_for_class_security_always_trust` (4 class sets x 4 switch values x 9 classes),
`test_view_for_class_display_follows_class_set`, `test_get_house_census_trust_equals_last_result`,
`test_get_house_census_missing_census_none`, `test_get_last_crossing_matches_bus_event`.

## Live validation (prospective)

- **Live:** no entity or log change after restart: `sensor.universal_room_automation_persons_in_house` /
  identified sensors read the same as before; no new WARN/ERROR from `camera_census`, `transit_validator`,
  `perimeter_alert`, `person_ids`.
- **Live:** census `identified_persons` and sighting slugs use the same strings as the day before
  (`oji_udezue`-form; check a `person_sighting` / census attribute).
- **Live:** the next garage crossing's NM text is unchanged in form ("<Name> arrived" at ≥ 0.75, else "Someone").
- **Live:** `grep -rn "get_house_census\|view_for_class\|get_last_crossing\|get_last_arrival_record"
  custom_components/` shows definitions only (callers arrive with the census / crossing-vision plans).
