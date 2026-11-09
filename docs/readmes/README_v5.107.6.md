# v5.107.6 — Entry areas read from the egress tracker

Tier 1 hotfix. Card: LOCK-ENTRY-AREAS-WRONG-OBJECT-1.

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
