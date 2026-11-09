# v5.107.6 — Entry areas read from the egress tracker

Tier 1 hotfix. Card: LOCK-ENTRY-AREAS-WRONG-OBJECT-1.

## Release contents (combined release)

v5.107.1 to v5.107.5 were built and reviewed as separate cycles but never released on their own. They ship in this
release, with one HA restart at the end of the perimeter-identity arc. Each has its own README:

| Version | Card | README |
|---|---|---|
| v5.107.1 | FACE-SOURCE-REGISTRY-DISCOVERY-1: face sensors found via the HA registry; 17 skipped `_2` cameras fixed | README_v5.107.1.md |
| v5.107.2 | PERIMETER-FRIGATE-SNAPSHOT-CAPTURE-NEVER-1: Frigate event snapshot fetched over the internal URL | README_v5.107.2.md |
| v5.107.3 | (no card, operator) daily HA external-URL self-check with a Repairs issue | README_v5.107.3.md |
| v5.107.4 | LOCK-REGIME-FACE-ARRIVAL-CORROBORATION-1: face-based lock releases need a same-person arrival edge | README_v5.107.4.md |
| v5.107.5 | PERIMETER-IDENTITY-FOLLOWUP-1: one quiet "that was &lt;name&gt;" follow-up on door alerts | README_v5.107.5.md |
| v5.107.6 | LOCK-ENTRY-AREAS-WRONG-OBJECT-1: this README | — |

Pre-deploy gate (2026-11-09): full-suite name-diff of develop `d0a2d87a` against v5.107.0 `b9c1b3d0` showed 0 NEW and
0 GONE failures. The isolated gate over 346 files also showed 0 NEW. The D7 anchors all passed.

## The bug

Two consumers added in the v5.107.x arc looked up `hass.data[DOMAIN]["transit_validator"]` to get door
groups and interior neighbours. That object is the `TransitValidator`, which has none of those attributes.
They live on `EgressDirectionTracker` (`transit_validator.py:943` `_egress_entities`, `:953`
`_interior_neighbours_by_group`, `:1178` `_door_group_for_stem`), stored at
`hass.data[DOMAIN]["egress_tracker"]` (`__init__.py:3461`).

- `security_lock_regime.py` `_entry_areas` → `arrival_edges.door_entry_areas`: always returned an empty set,
  so a Bermuda/BLE move never corroborated a `camera_face` arrival. The lockout/away-lock release then needed
  the live `person.*` not_home→home edge. Fail-safe (no wrong unlock), but the BLE half of the face+BLE rule
  was dead.
- `perimeter_alert.py` `_near_areas`: `tv._door_group_for_stem` raised AttributeError, which was swallowed,
  so only the camera's own area counted. Configured door-interior neighbours never corroborated.

The unit tests passed a `SimpleNamespace` stand-in carrying the tracker's attributes under the wrong key, which hid it.

## Fix

Both consumers now read `"egress_tracker"`. `door_entry_areas`' parameter is renamed `egress_tracker`.
Neither needs anything from the TransitValidator.

Other `"transit_validator"` readers were checked and are correct: `sensor.py:3555`, `binary_sensor.py:2191`/`2204`
(`get_last_camera_sighting`, `transit_validator.py:653`) and `sensor.py:6446` (`build_diagnostic_attrs`, `:238`)
all call TransitValidator methods.

## Tests

The tests now use a real `EgressDirectionTracker` at `"egress_tracker"` and a real `TransitValidator` at
`"transit_validator"`, so a consumer reading the wrong key gets an object without the surface.
New: `test_entry_areas_read_from_egress_tracker`, `test_neighbour_area_bermuda_move_releases_via_tracker`;
`test_egress_gate_near_area_includes_configured_neighbours` now also asserts `_near_areas` directly.

Mutation drill (key reverted to `"transit_validator"`): lock regime → 15 RED; perimeter → 1 RED.

## Live validation (prospective)

- With `CONF_DOOR_INTERIOR_NEIGHBOURS` configured, a garage face arrival plus a Bermuda move into the
  garage or a neighbour area releases the lockouts and logs no fail-safe hold.
- A doorbell D10.5 decision with a BLE move into a configured neighbour area records `demoted = True`.

## Behaviour change to expect

This fix makes the face + Bluetooth entry check work for the first time. After deploy, a garage or door face
arrival plus a Bermuda move into the door's area (or a configured neighbour area) can release the lockout /
away-lock. Before, only the `person.*` not_home→home edge could. Tier-1 review: SHIP
(`docs/reviews/code-review/v5.107.6_entry_areas_egress_tracker.md`).
