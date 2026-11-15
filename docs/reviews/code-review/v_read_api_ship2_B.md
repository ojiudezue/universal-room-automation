# Review B: person-awareness read API ship 2 (RA6-RA10)

Branch `feature/person-awareness-read-api-ship2` @ 1d49aef9. Base `release/batch-1` ca133c9d, verified as the merge-base (`git merge-base HEAD ca133c9d` = ca133c9d), so the three-dot diff is complete.
Framing B: cross-coordinator ripple, forward trace to actions, lifecycle, import cycles.
Read completely first: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`, `HVAC_ARCHITECTURE_STATE_OF_PLAY.md`. No corrections-ledger claim is re-asserted here.

## Verdict: SHIP

No CRITICAL, HIGH or MEDIUM findings. Under the live config, every migrated consumer produces the same value on the same path. Four LOWs are listed below; none of them is reachable under the live config.

## Forward trace (live config)

| Consumer (action) | Change | Equivalence evidence |
|---|---|---|
| RA8 HVAC D7 night-trust preset hold (`hvac.py:3412`), `main_row_home_persons` (display, `:3989`), fan night vacancy hold (`hvac_fans.py:1526`), `zone_has_home_person` (`hvac_zones.py:2723`, no production caller), the two `ZoneAnyoneBinarySensor` vetoes (`aggregation.py:4756`, `:4890`) | Loops replaced by `persons_home_for_trust` / `first_person_home_for_trust` (`person_coordinator.py:165-189`) | Same predicate (`person_state_for_trust(...) == "home"`), same order. `next()` over a generator keeps the short-circuit. `persons or []` covers the old `(zone.zone_persons or [])`. The fan hold logs the same first person and returns the same tuple. The only difference is on the exception path: the night-trust list is now `[]` instead of a partial list. `person_state_for_trust` does not raise ("any error -> raw"), so this is not reachable. |
| RA7 census readers: `UnidentifiedPersonsSensor`, `ZoneGuestCountSensor`, `URAUnexpectedPersonSensor`, phone-left-behind step 3 (TRUST: feeds the AWAY-veto denominator through `presence._phone_left_behind_on`) | `house_census_view(hass, "trust")` (`census_view.py:64`) | It reads the same fields. `CensusZoneResult` (`camera_census.py:310-338`) has every field the view reads (`identified_count` / `unidentified_count` / `total_persons` / `source_agreement` / `timestamp` / `confidence`), and they are ints/strs, so the view is None only when `census` / `last_result` / `house` is missing, the same cases where the old code returned 0/None/False. |
| RA10 SC `_handle_person_arriving` (`security.py:2399`), lock regime `on_person_arriving` (`security_lock_regime.py:1248`), music following (`music_following.py:557`) | `PersonArrivingPayload.from_signal` (`signals.py:27-67`) | Field by field: dict `person_entity` defaults to `""`, `source` / `sighting` to None, `zone` to `""`. An attribute object without `person_entity` returns None, which is the same early return as before. The lock regime keeps `str(... or "")`. `sighting` is read only in the face branch, as before. No field was renamed or dropped, so no unlock or block path changes. The camera_face corroboration (`arrival_source_needs_corroboration`) receives the same `source`. |
| NM arrival/departure fallback name (`notification_manager.py:4763`), perimeter "Identified:" text (`perimeter_alert.py:1780`, `:5563`), egress notify name (`transit_validator.py:2671`) | `display_of` | Old `x.replace("person.","").replace("_"," ").title()` and new `slug_of` → `.title()` agree on every input without surrounding whitespace: `title()` lowercases the non-initial letters anyway. `guest:abc` gives `Guest:Abc` both ways. |
| Person-coordinator tracked names (`__init__.py:3142`) → `entry.data` rewrite → `PersonTrackingCoordinator.tracked_persons` (`person_coordinator.py:204`) | `display_of` | Same output, so `async_update_entry` writes identical data (no entry-update churn). The phone-left-behind unique_id `entity_key_slug(display_of(eid))` is unchanged. |
| Person-coordinator `person.*` builds (`:842`, `:1016`, `:1766`) | `tracked_person_entity_id` | Same id for display names. `tracked_persons` is always display names: `__init__` rewrites `entry.data` before constructing the coordinator. The new keep-`person.*` branch is therefore not reachable live (see LOW-3). |
| Music `_person_key` (`music_following.py:58`), arrival-edge slugs (`arrival_edges.py:66`, `:202`, `:240`) | `slug_of` / `entity_key_slug` | Same keys for `person.<slug>` and display names. `entity_key_slug` is the exact old expression. |
| Own unique ids (phone-left-behind, routine status, MF follow switch, `_ble_corroboration`, `presence._phone_left_behind_on`) | `entity_key_slug` | The exact old expression, so no registry orphan. |
| RA6 identity producers (egress tracker `transit_validator.py:1559-2316`, sighting producer, perimeter, setup) | Public delegates (`camera_census.py:3925-4028`) | Each delegate forwards to the private method or runs the identical counter or attribute write. `canonical_person_slug` already existed. The getattr defaults are kept (`None` / `{}`). |

**House state / AWAY / HVAC actuation / locks / security / NM text:** no change under the live config.

## Dead hooks deleted

- `get_room_identified_persons`: `PersonCensus` has no such method (repo grep: only the new comment at `coordinator.py:1371`). The branch always fell through to the person coordinator, so the delete is safe.
- `hass.data[DOMAIN]["camera_integration_manager"]`: no writer anywhere. The string appears only in the new comment at `presence.py:3225`, and `CameraIntegrationManager` is stored inside `PersonCensus`, never under that key. The seed therefore always used the sensor fallback (`if self._census_count == 0`), and it still does. The delete is safe.

## Lifecycle / event loop / imports

- No new listener, timer or task. `register_ble_transition_listeners` / `refresh_ble_crossing_listeners` are pass-throughs. The unsub and teardown paths are unchanged.
- All new reads are sync and in-memory, with no I/O on the loop.
- `census_view.py` and `person_ids.py` import only the stdlib (`logging`, `dataclasses`, `typing`), so they cannot form a cycle. The import sites are: presence at mid-module (`..census_view`); `transit_validator` and `arrival_edges` at top level (`.person_ids`); the lock regime in-function (`from .signals`, resolved inside `domain_coordinators`, correct). `signals.py` already imported `dataclass` (`:5`).
- Targeted run: `test_person_awareness_read_api_ship2.py`, `test_person_gps_assistive_hvac.py`, `test_lock_face_arrival_corroboration.py`, `test_face_arrival_rule.py`: 140 passed.

## AST guard allowlist

`_ALLOWED_DISPLAY_READS` (`test_person_awareness_read_api_ship2.py:498-525`) is an exact map of (file, name) to count, and the guard checks it both ways. A count above the allowance fails. A stale entry also fails (`:584`). The list therefore cannot grow silently, and it must shrink as entries are migrated. Every entry is a display-only diagnostics read in `sensor.py`, plus two `binary_sensor.py` reads behind a display mirror. The detector has positive and negative controls (`:588-602`). The allowlist is honest.

## Findings

| SEV | Site | Finding / scenario | Bug class |
|---|---|---|---|
| LOW-1 | `census_view.py:82-91` | The view needs all seven fields readable and int-convertible, where readers such as the phone-left-behind step 3 needed only one. A partial or odd `house` object (only test doubles today) now yields None, which reads as no census. On the phone-left-behind path that can make the sensor turn on where the old code suppressed it. Production `CensusZoneResult` always has the fields, so this is not reachable. Informational. | Coincidental equality (#63, latent) |
| LOW-2 | `test_..._ship2.py:542-566` | The guard sees only receivers whose source text contains `cens`. Verified: all 19 current assignments from `hass.data[...]["census"]` outside `camera_census.py` use `census` / `cens` / `_cens` / `census_ref` / `_cens_for_teardown`. The limit is stated in the docstring. A future `pc = ...["census"]` would bypass it. | Hollow-anchor risk (#62, bounded) |
| LOW-3 | `person_coordinator.py:842`, `:1016`, `:1766` | `tracked_person_entity_id` now keeps a `person.*` entry, where the old code built `person.person.*`. This changes behaviour only if `PersonTrackingCoordinator.tracked_persons` held entity ids. `__init__.py:3150-3162` rewrites `entry.data` to display names before construction, so it is not reachable live. If it were reached, it would be a fix (lookups that never resolved would start resolving). | none (intended) |
| LOW-4 | `person_ids.py:51`, through `display_of` at `__init__.py:3149` | `slug_of` strips surrounding whitespace, and the old inline title-case did not. A `tracked_persons` entry such as `" Oji"` would now map to a different display name: one `entry.data` rewrite, plus a new phone-left-behind unique_id (orphaning the old one). This is not reachable from the entity selector or the stored display names. | none |

## Invariant checklist

- Byte-identical consumers under the live config: PASS.
- No change to house state, AWAY, HVAC actuation, lock behaviour, security or NM text: PASS.
- No live reader of the deleted hooks: PASS.
- No import cycle, nothing that blocks the event loop: PASS.
- Allowlist honest and shrink-only: PASS.

Must-fix list: none.
