# PERSON-AWARENESS-READ-API-1 ship 1: Review C (test authority, per-site source mutation)

Branch `feature/person-awareness-read-api-ship1`, HEAD 6b3b6891, base 376c1272 (merge-base develop, verified).
Method: ONE production-source mutation at a time (write mutant, run, restore in `finally`), pycache purged and
`PYTHONDONTWRITEBYTECODE=1` each run, `git status` clean after. Pass 1 ran `test_person_awareness_read_api.py`
(32 tests). Every GREEN row was re-run against 13 sibling files (473 tests: camera_census, census_ble_over_face,
egress_face_identity_d1, identity_fusion_d2_d3_d4, perimeter_fp_gates/consol1/identity_annotation,
arrival_departure_notify, egress_direction_aware, person_tracking, person_coordinator_setup_wirein,
face_source_registry); all stayed GREEN, so they are genuinely untested.
Note: I did not read the full presence state-of-play doc (mutation pass only; no claim re-asserted).

## Per-site table (67 mutants; 53 RED, 14 GREEN rows below)

| Site | Mutation | Result |
|---|---|---|
| person_ids.py tracked_person_entity_id (lower, space, keep-entity-id) | each removed | RED test_slug_of_display_of_roundtrip |
| person_ids.slug_of (None guard, input strip) | removed | RED roundtrip |
| person_ids.slug_of trailing `.lower()` (line ~60) | removed | **NONE (GREEN, siblings too)** |
| person_ids.slug_of trailing `.strip()` | removed | **NONE (GREEN)** |
| person_ids.display_of (.title, underscore, via slug_of) | each | RED roundtrip |
| camera_census Residual A / B / C | reverted to old expr | RED test_residuals_same_slug_display_and_entity_config[A/B/C-display] |
| perimeter_alert Residual D (`_tracked_person_slugs`) | reverted | RED residuals[D-display] |
| camera_census.canonical_person_slug public wrapper | returns "" | **NONE (GREEN)** |
| person_coordinator re-export of tracked_person_entity_id | local redefinition | RED roundtrip (identity assert) |
| perimeter_alert `_known_identity_for` floor (literal 0.5; wrong class) | each | RED test_class_thresholds_unchanged |
| transit_validator inline notify compare (literal 0.5; display class) | each | RED test_class_thresholds_unchanged |
| transit_validator `ARRIVAL_NAME_CONFIDENCE_THRESHOLD` class attr -> 0.5 | | **NONE (GREEN)**; attr is now read nowhere in production (only a docstring), so equivalent in behavior, but no test pins it |
| const CONSUMER_CLASS_MIN_CONFIDENCE security/notification/display values, MappingProxy | each | RED thresholds_unchanged / table_values |
| const CROSSING_VISION_CONSUMER_CLASSES + security | | RED (import ValueError surfaces as ERROR in every test) |
| const LEGAL set + security | | RED test_consumer_classes_rejects_illegal |
| const `validate_consumer_classes` body (raise removed) | | RED rejects_illegal |
| const module-level `validate_consumer_classes(...)` call deleted | | **NONE (GREEN)** |
| const switch entity name | | RED test_view_for_class_display_follows_class_set |
| presence.view_for_class: promoted-set guard, legal-set guard, switch None, switch != on, switch entity, final return | each | RED (display_follows_class_set / security_always_trust) |
| view_for_class `isinstance(cls, str)` guard | removed | GREEN, but equivalent: `in frozenset` TypeError is swallowed by the except -> trust |
| view_for_class `except` returning trust (flipped to awareness) | | **NONE (GREEN)**: fail-to-trust path never driven |
| presence.get_house_census field copies (identified, unidentified, total, provenance, agreement, as_of), `view="trust"` forced, except->raise | each | RED trust_equals_last_result / missing_census_none |
| get_house_census `view == "awareness"` passthrough (`view=view`, any string echoed) | | **NONE (GREEN)**: awareness view normalization never driven |
| get_house_census census/last/house None guards | each removed | GREEN, equivalent (AttributeError caught -> None) |
| presence.get_last_crossing delegation (camera dropped; tracker-None guard; except->raise) | each | **NONE (GREEN)**: PresenceCoordinator wrapper has no test at all |
| presence.get_last_arrival_record | (constant None) | not mutated; no logic |
| transit_validator.get_last_crossing camera lookup / overall branch | each | RED test_get_last_crossing_matches_bus_event |
| `_record_crossing` call, overall store, per-camera store, `_last_crossing` init | each | RED |
| CrossingRecord fields camera, direction, ts, confidence, source_ref | each | RED |
| CrossingRecord `person_id` (forced None) | | **NONE (GREEN)** |
| CrossingRecord `identity_confidence` (forced None) | | **NONE (GREEN)** |
| CrossingRecord `provenance` conditional | | **NONE (GREEN)** |

## Findings

- MEDIUM (#62 hollow / untested site): CrossingRecord identity fields (`person_id`, `identity_confidence`,
  `provenance`) at transit_validator.py ~2257-2265 are untested. The one crossing test uses a no-identity
  crossing, so the identity half of RA5, the part consumers will read, can be wrong without a failure. Add a
  crossing with an attached identity (person_id, 0.8 conf, provenance) and assert the record equals the bus event.
- MEDIUM: `PresenceCoordinator.get_last_crossing` (presence.py, RA5 public API) has zero tests; camera passthrough,
  tracker-missing None and never-raises are all unpinned. Test through `hass.data[DOMAIN]["egress_tracker"]`.
- LOW: `get_house_census(view="awareness")` (view string normalization, unknown string -> trust) never asserted.
- LOW: module-level `validate_consumer_classes(...)` import-time call is untested (the function body is). Deleting the
  call disables the load-time guard silently; add a test that asserts the call ran, e.g. reload const with a patched
  class set and expect ValueError.
- LOW: `slug_of` trailing `.lower()` matters for an entity-id entry with capitals (`person.Oji_Udezue`, kept as is by
  `tracked_person_entity_id`); no test case has capitals in an entity-id entry. Trailing `.strip()` matters for
  `person. oji`. Add both inputs to the roundtrip test.
- LOW: public `canonical_person_slug` wrapper has no caller and no test.
- LOW: `view_for_class` except path (hass.states raising) not driven.
- INFO: `EgressDirectionTracker.ARRIVAL_NAME_CONFIDENCE_THRESHOLD` is now unread dead attribute (kept for compat);
  threshold test pins behavior via the inline site, so no gap, but decide KEEP+DOCUMENT or delete next ship.

All load-bearing doctrine sites (security floor, notification threshold, table values, class-set legality, promotion
allow-list incl. switch gating, residuals A-D, id rule, crossing store core) are mutation-anchored by a specific named test.

## Verdict: FIX-REQUIRED (test additions only, no production change)

Must-fix: (1) crossing-with-identity test (CrossingRecord identity fields); (2) PresenceCoordinator.get_last_crossing
test. Should-fix LOWs: awareness-view string, validate call at import, capitalized/space entity-id slug cases.
Re-run the 14 GREEN rows after adding tests; each should go RED.
