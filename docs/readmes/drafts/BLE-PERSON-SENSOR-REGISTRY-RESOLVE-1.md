# BLE-PERSON-SENSOR-REGISTRY-RESOLVE-1 — README draft

Plan: `docs/planning/PLANNING_ble_person_sensor_registry_resolve.md` (rev 2). Audit:
`docs/planning/AUDIT_ble_person_sensor_resolution_2026_11_14.md`. Tier 2. Operator approval 2026-11-14.

## What was wrong

PersonCoordinator found each person's Bermuda sensors by entity_id substrings:

- **Distance set (confidence input):** any Bermuda `distance_to_*` sensor whose entity_id contained the person's
  slug. A scanner named after a person (`jaya_3`, `...ezinnemakeup`) matched too, so Ezinne, Ziri and Jaya each
  picked up 12 sensors on OTHER people's phones. Oji matched none and sat at the fixed 0.5.
- **Auto-enable:** every matched disabled distance sensor was enabled in the entity registry, which also schedules a
  Bermuda config-entry reload. It is how the 13 foreign sensors on Oji's phone became enabled.
- **Area sensor:** three name strategies (private_ble object_id, two patterns, registry substring). They happened to
  hit for all four people.
- **`aggregation.PersonLocationSensor._find_bermuda_sensors`:** scanned `sensor.bermuda_<first>_*`, matched 0 for
  everyone since v3.6 naming and only logged "No Bermuda sensors found, falling back to polling" at each setup.

## What changed

`person_coordinator.py`:

1. `_bermuda_device_for_person(person_entity_id)` resolves the person's Bermuda DEVICE through the registries only.
   Route (a): the one `device_tracker` in the person's `device_trackers` whose registry platform is `bermuda`.
   Route (b), only when (a) finds none: the one `private_ble_device` tracker, its device's
   `('private_ble_device', X)` identifier, then the one OTHER device carrying X that owns a `bermuda` entity, found
   by a full scan of the device registry (the identifier index holds one device per identifier, and the
   private_ble device and the Bermuda device share X). Zero or two-plus candidates resolve to nothing. No cache: it
   runs per tick, so a late Bermuda load resolves on the next tick.
2. `_bermuda_person_sensors(device_id, uid)` types the sensors on that device by registry unique_id (Bermuda builds
   them from the device uid): area = `<uid>`; distance = ONE enabled sensor per scanner, the filtered
   `<uid>_<mac>_range`, falling back to `<uid>_<mac>_range_raw` only when the filtered one is absent or disabled;
   the nearest-distance `<uid>_range` is excluded. (Fix-up A-L1: the build counted both, so one close scanner read
   as two and gave 0.9 instead of 0.7. Inert today, every per-scanner input is a ghost.)
3. `_find_bermuda_area_sensor`: config override (unchanged) -> registry area sensor -> None. Strategies 2-4 deleted.
4. `_calculate_confidence`: distance set from the person's own device. The auto-enable block is deleted; no code path
   writes `disabled_by`. Scanner-name matching inside the confidence loop is unchanged (non-goal).
5. One resolve per person per tick (fix-up A-L3): `_async_update_data` calls `_bermuda_device_for_person` once and
   passes the result to `_find_bermuda_area_sensor` and `_calculate_confidence` (optional `resolved` argument; a
   direct call without it resolves itself). Nothing is cached across ticks, so runtime registry changes still take
   effect on the next tick.
6. Fire check: `_bermuda_resolve_hits` / `_bermuda_resolve_misses[(person, reason)]`, `get_bermuda_resolve_stats()`,
   surfaced as the unrecorded attribute `bermuda_resolve` on `sensor.*person_tracking_status` (Person Tracking
   Status diagnostic). Miss reasons: `no_person_state`, `no_bermuda_tracker`, `multiple_bermuda_trackers`,
   `tracker_no_device`, `private_ble_ambiguous`, `private_ble_no_twin`, `registry_error`, `no_area_sensor`. One
   WARN `No Bermuda area sensor for <person> (route=..., reason=...)` per (person, reason) on the second consecutive
   miss; one INFO when a warned person resolves again.

`aggregation.py`: `_find_bermuda_sensors` and `_handle_bermuda_state_change` deleted (supersession bucket DELETE).
PersonLocationSensor keeps the person_coordinator listener and the decay timer.

## Expected effect

- Oji's confidence 0.5 -> 0.3 (display "medium" -> "low"); Ezinne, Ziri, Jaya stay 0.3. All per-scanner distance
  sensors have been restored ghosts since 2026-10-20 (Bermuda upstream issue), so 0.3 is the "no numeric reading"
  value.
- Ezinne, Ziri and Jaya each lose the 12 foreign sensors. Oji gains his 13 enabled own-device sensors.
- Area sensors unchanged for all four (`sensor.iphone_oji_area`, `sensor.ezinne_iphone_area`,
  `sensor.iphone_ziri_area`, `sensor.iphone_jaya_area`).
- No decision changes: the only trust reader of person confidence is the `< 0.3` filter, which 0.3 passes. The music
  8 ft gate was dropped on 2026-11-14, so the plan's music-plan seam is moot.

## Known residuals (display only, left as is)

- **A-L2:** the warn-once streak resets when the miss reason changes, so a person alternating between two miss
  reasons every tick never WARNs. The `bermuda_resolve` counters still show every miss.
- **B-8:** a person removed or renamed in `tracked_persons` keeps their `bermuda_resolve` counters until the person
  coordinator is rebuilt (reload or restart). Bounded by the names ever configured.
- **A-L4 (carded, not fixed):** the confidence loop still takes the scanner name from the entity_id
  (`split("distance_to_")`, `person_coordinator.py` `_calculate_confidence`) and matches it to `_get_area_scanners`
  names by substring. A registry fix by the unique_id MAC is not a 30-line change: in the live device registry each
  scanner MAC is a connection on 2-3 devices (the integration device plus Bermuda's scanner device), and 184 MACs map
  to devices in different areas or with no area, so a MAC-to-area rule needs a design decision. Card: a
  REGISTRY-NOT-NAMES-1 child.

## Tests

`quality/tests/test_ble_person_registry_resolve.py` (27 tests after the fix-up, real `hass` + real entity/device registries, Oji's
live 4-tracker shape and the shared-identifier twin). 30 single-site source mutations, each RED on a named test,
including the three wire-in calls (area finder, confidence, tick) and the fire-check wiring. Fix-up: six more
drills, each RED (scanner dedup, filtered-over-raw preference, the two tick call sites passing the result, the two
helpers consuming it). Single-argument `_find_bermuda_area_sensor` stubs in `test_census_ble_over_face.py`,
`test_house_state_sleep_mask_ble_memory.py` and `test_person_gps_assistive.py` now take the extra argument.

## Live validation (prospective; replace with a `Validated <date>` table)

- `bermuda_resolve` on Person Tracking Status: each home resident `last_route: a`, `resolved` rising,
  `unresolved: 0`.
- `person_presence_snapshots` / `person_visits` after restart: Ezinne / Jaya / Ziri confidence 0.3; Oji 0.3 if home
  (he is abroad until ~11-16: likely not observable).
- HA log after boot: zero `No Bermuda area sensor` WARNs, zero `Auto-enabled Bermuda distance sensor` INFOs, zero
  `No Bermuda sensors found` WARNs, no Bermuda config-entry reload in the boot window.
- Entity registry: count of enabled `bermuda` entities identical before and after restart.
- `sensor.<person>_location` for the home residents matches their `sensor.*_area`.
