# Person-awareness read API, ship 2 (DRAFT, not deployed)

Card PERSON-AWARENESS-READ-API-1 (PERSON-ID-NORMALISE-ONE-RULE-1 folded in). Plan
`docs/planning/PLANNING_person_awareness_read_api.md` §5 ship 2 (RA6-RA10). Branch
`feature/person-awareness-read-api-ship2`, based on `release/batch-1` (ca133c9d, which carries ship 1).
Tier 2. Invariant INV-RA-BYTE-IDENTICAL: under the live config (display names in `entry.data`, entity
ids in `entry.options`) every migrated reader returns what develop returns.

Identity model: produces no fact. Readers migrated: F1 (zone "any person home", trust class), F2 (house
census counts, display class), F3 producers' census access (egress tracker, perimeter, sighting producer;
security / notification / display classes unchanged), F5 payload reads (security-access, comfort,
personalization).

## What changed

| RA | Change | Sites |
|---|---|---|
| RA6 | Public `PersonCensus` surface, thin delegates to the privates (which stay the implementation and the patch seam): `tracked_person_slugs`, `face_suppressed_now`, `known_face_guests`, `resolve_face_legs`, `resolve_ble_legs`, `consume_ble_arriving_legs`, `egress_identity_enabled`, `egress_identity_failsafe_strict`, `face_producer_live`, `note_egress_identity_outcome`, `register_ble_transition_listeners`, `refresh_ble_crossing_listeners`, readers `frigate_face_named_ring`, `ble_tracker_slug_map`, `egress_identity_last_attach`, `egress_identity_outcomes`, `egress_identity_boost_events`, writers `note_ble_leg_abstained`, `note_face_dropped_producer_down`, `note_face_dropped_stale`, `note_egress_identity_boost`, `set_egress_identity_agreement_class`, `set_egress_identity_last_attach` (`camera_census.py`, after `canonical_person_slug`) | `transit_validator.py` 29 call sites, `perimeter_alert.py` 6, `person_sighting.py` 6, `__init__.py` 2, `sensor.py` 3 (egress-identity attributes) |
| RA7 | One F2 read: `census_view.house_census_view(hass, view)` (pure module; `HouseCensusView` moved there, re-exported by presence, gained `confidence`). `PresenceCoordinator.get_house_census` delegates to it | `UnidentifiedPersonsSensor` value + attributes, `URAUnexpectedPersonSensor` is_on + attributes, `PersonPhoneLeftBehindSensor` census step + attribute, `ZoneGuestCountSensor` value + attributes. Deleted dead code: the `get_room_identified_persons` hook in `coordinator._get_identified_persons_in_room` (PersonCensus never had it) and the presence seed branch reading `hass.data[DOMAIN]["camera_integration_manager"]` (no writer) |
| RA8 | `person_coordinator.persons_home_for_trust` / `first_person_home_for_trust` (one rule, ordered, short-circuit kept); `get_residents_home(zone_persons=...)` answers the per-zone question through it (no phone-left-behind cut: a different question) | `hvac.py` night-trust preset hold + `main_row_home_persons`, `hvac_fans.py` night vacancy hold, `hvac_zones.zone_has_home_person`, `aggregation.py` sleep / non-sleep person fallbacks |
| RA9 | Id copies through `person_ids`: `tracked_person_entity_id`, `slug_of`, `display_of`, and NEW `entity_key_slug` (the frozen `name.lower().replace(' ', '_')` rule for URA-owned unique ids and storage keys; a different concept from `slug_of`, never to be "improved", it would orphan registry entries) | `person_coordinator` overrule match / update loop / `_find_person_entity` (the three Review A copies: a `person.*` entry no longer becomes `person.person.*`), `arrival_edges` (3), `binary_sensor` PLB name + unique id, `sensor` routine-status unique id, `switch` MF follow unique id, `_ble_corroboration` + `presence._phone_left_behind_on` PLB key, `__init__` tracked_persons display conversion, `notification_manager._get_person_name`, `music_following._person_key`, `perimeter_alert` annotation + follow-up names, `transit_validator` arrival title |
| RA10 | `signals.PersonArrivingPayload.from_signal(payload)`: one normalised read of the dict-or-attribute F5 payload, values verbatim. Producers still send dicts | `security._handle_person_arriving_signal`, `security_lock_regime.on_person_arriving` (a third dual read, not in the plan), `music_following._handle_person_arriving` |

Guard: `test_no_private_census_reads_outside_module` is AST-based (PersonCensus private names come
from the class AST; receivers matched `(^|[._])cens`; getattr/hasattr/setattr with constant names
included), with an exact allowlist + counts that fails on stale entries, and anti-hollow controls.

## Byte-identity evidence

- The reader goldens in `quality/tests/test_person_awareness_read_api_ship2.py` (RA7 sensors, RA9
  display/name/key sites, RA10 handlers, `zone_has_home_person`, `arrival_edges`) were run unchanged on
  the base tree ca133c9d and PASS there (35/35 of the tests that only call pre-existing APIs). The 27
  that fail on base call new APIs, or pin the two intended `person.*`-entry fixes (overrule match,
  `_find_person_entity`), or a fake census hook that never existed.
- Targeted name-diff, 216 test files (every file touching a changed module), candidate vs base: no new
  failure, none fixed.
- Behaviour that differs, all OFF the live config: a `person.*` entry in the person coordinator's
  display-name list now matches (was `person.person.*`); exotic whitespace / `person.`-in-the-middle
  inputs to the display rules; a malformed census house object (missing fields) now reads "no census"
  in the RA7 readers instead of raising.

## Mutation drills (one site at a time, restored, `git status` clean after each)

All per-site drills below went RED on a named test (full list in the builder report): RA9 18/18,
RA10 9/9, RA8 8/8, RA7 13/13, RA6 call sites 46/46 (including each occurrence of the 5 abstain
counters, 3 consumes, 2 boosts, 4 last-attach writes, 2 tracked reads), RA6 wrapper bodies 23/23, guard
detector 1/1. Sites first found GREEN (pre-existing untested paths) got new tests before re-drilling:
`__init__` display conversion, agreement-class stamps, attach-provenance forwarding, setup listener
wiring, census sensor egress attributes, the BLE precedence branches' side effects, perimeter known
face guests.

## Not done (accounted)

- `_CensusBaseSensor` rich display sensors (`sensor.py` ~3756-4330: persons / identified / property /
  confidence / validation age) still read `census.last_result` (a public property) for ~25 fields the
  7-field view does not carry. Widening the view into a FullCensusResult clone is out of scope.
- ~39 display-only getattr reads of census diagnostics in the census sensor and 2 in
  `CameraInputDegradedBinarySensor` are allowlisted (display class, no producer).
- `f"person.{slug}"` compositions from an already canonical slug (camera_census, perimeter, sighting,
  transit) left as is: composition, not normalisation.
- Registry-not-names audit C4 person cluster in files touched: `person_coordinator` Bermuda name guesses
  (`:1764`, `:1782-1812`, `:1835`) and `aggregation.py:6179` are registry migrations (audit §8 item 2),
  not id copies; not done. `.title()` entity-name/location copies in `sensor.py` / `aggregation.py`
  (not in either audit list) left. Room/zone slug copies (C5) out of scope.
- `presence._run_inference` phone-left-behind closure left untouched (INV-MACHINE,
  `test_run_inference_source_unchanged`).
- HVAC `_handle_person_arriving` keeps its dict read (dict producers only).

## Live validation (prospective)

- Census sensors (`sensor.universal_room_automation_unidentified_persons`, zone guest counts,
  unexpected-person / phone-left-behind binary sensors) read the same values the day after deploy.
- NM arrival text names the same people; HVAC night-trust holds and the fan night hold fire as before
  (activity log `home_persons` unchanged in shape).
- No new WARNING/ERROR lines from `camera_census`, `transit_validator`, `perimeter_alert`,
  `person_sighting`.
