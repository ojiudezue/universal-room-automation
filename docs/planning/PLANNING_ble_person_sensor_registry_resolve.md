# PLANNING: person Bermuda sensors resolved through the registry (BLE-PERSON-SENSOR-REGISTRY-RESOLVE-1)

Card BLE-PERSON-SENSOR-REGISTRY-RESOLVE-1 (parent REGISTRY-NOT-NAMES-1, cluster C4 of
`AUDIT_registry_not_names_sweep_2026_11_13.md`). Implements `AUDIT_ble_person_sensor_resolution_2026_11_14.md` §4-§5
under the operator rulings recorded on the card 2026-11-14. Rev 1, develop @ c317a6c7. Plan only.

Mandatory reading done, completely: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`,
`docs/architecture/SENSOR_FLEET_CLASSES.md`, the measured audit, `PLANNING_room_occupied_registry_resolve.md`, and the
sweep audit's BLE rows (L2-L4, :103-108, :178). No §10 ledger claim is re-asserted. Identity model: this cycle produces
no F1-F5 fact. It changes how PersonCoordinator finds the inputs of its per-person room and confidence values, which
feed F2 (census BLE leg) as `location` only; every reader stays in its current consumer class.

## 0. Facts that shape the plan (code and live data win)

1. Room location works for all four people today (name strategies happen to hit). The defect is the distance set:
   Ezinne/Ziri/Jaya each match 126 sensors, 12 of them on OTHER people's phones (a scanner named `jaya_3` or
   `...ezinnemakeup` matches the substring). Oji matches 0 and returns the fixed 0.5.
2. Every per-scanner `distance_to_*` sensor is a restored ghost since 2026-10-20 (356/356 `unavailable`,
   `restored: true`). Root cause, context only: Bermuda 0.8.7 `sensor.py:96-108` `create_scanner_entities` returns
   early for ALL devices when any remote scanner has `address_wifi_mac is None`; the 7 wall-panel kiosk_satellite
   proxies added 10-19/10-20 trip it. So confidence is a fixed 0.3 (three people) / 0.5 (Oji) and no decision reads it
   (audit §3.1: the only trust reader is the `< 0.3` filter at `person_coordinator.py:2154-2163`, which both pass).
3. **Same-identifier hazard (new, registry-verified 2026-11-14).** Each person's private_ble device (Oji `f8ff410c`)
   and Bermuda device (Oji `435615c6`) carry the SAME identifier `('private_ble_device', '8ce182a9...')`. HA indexes a
   device by identifier in one slot (`device_registry.py:674-683`; `docs/architecture/DEVICE_TREE.md:108`), so
   `dr.async_get_device(identifiers=...)` returns ONE of the two arbitrarily. Route (b) must NOT use it (D1).
4. Bermuda has no `translation_key`; the only registry fact that types a sensor is its unique_id, which Bermuda builds
   from the device uid (`/config/custom_components/bermuda/sensor.py`): area `<uid>` (:153-158), nearest distance
   `<uid>_range` (:318), per-scanner `<uid>_<mac>_range` (:366), unfiltered `<uid>_<mac>_range_raw` (:409). The
   Bermuda tracker's unique_id is `<uid>` (`device_tracker.py:75-77`). Matching on the registry unique_id of an entity
   on the resolved device is a registry read, not a name guess.
5. Config-first: `CONF_BERMUDA_AREA_SENSORS` (`const.py:4138`) is unset live and has no options-flow field (grep of
   `config_flow.py`: 0 hits); it covers only the area sensor, never distance. No knob fixes this.

## 1. Institutional context verified

Greps on develop @ c317a6c7: `grep -n "device_trackers\|_resolve_bermuda_entity_id\|async_update_entity\|closest_distance"
person_coordinator.py`; `grep -rn "_find_bermuda_sensors\|_find_bermuda_area_sensor\|_calculate_confidence"
custom_components quality/tests`; `grep -rn EVENT_ENTITY_REGISTRY_UPDATED custom_components`; `grep -n "BERMUDA_\|
CONF_BERMUDA" const.py`; `grep -n "unique_id" bermuda/sensor.py bermuda/device_tracker.py`; registry read of
`.storage/core.{device,entity}_registry`.

| Piece | Verdict |
|---|---|
| Person tracker list | REUSED: `person.*` attribute `device_trackers`, same read as `person_coordinator.py:303, :439, :714` |
| Person key | REUSED: `person_ids.tracked_person_entity_id` (`person_ids.py:25`); no new title-case round trip |
| Registry unique_id lookup | REUSED pattern: `_resolve_bermuda_entity_id` (`person_coordinator.py:473-480`) |
| Device entity listing | REUSED HA: `er.async_entries_for_device(reg, device_id, include_disabled_entities=False)` (`entity_registry.py:1953`) |
| Override first | REUSED: `CONF_BERMUDA_AREA_SENSORS` Strategy 1 (`:1767-1777`), unchanged |
| Cache invalidation | NOT NEEDED: resolve per tick, no cache (same choice as sibling plan D1 "no cache"); camera_census / coordinator `EVENT_ENTITY_REGISTRY_UPDATED` pattern (`coordinator.py:2716-2728`) available if a cache is ever added |
| Resolver function `_bermuda_device_for_person` | NEW: no person->device helper exists (grep `device_id` in person_coordinator: only proxy-count unique_id lookups). Lives in `person_coordinator.py` beside `_resolve_bermuda_entity_id`; NOT in the sibling's `room_entities.py` (that file resolves URA's own room entities by `{entry_id}_{key}`; a foreign-integration device walk is a different shape) |
| Miss counter | NEW: `PersonTrackingCoordinator._bermuda_resolve_misses: dict[str, int]` keyed `(person, reason)`; no existing person-resolution counter |

Prior plans: sibling `PLANNING_room_occupied_registry_resolve.md` (miss-count + warn-once-on-second-miss rule reused,
not its module); `PLANNING_presence_gps_assistive.md` (registry-by-unique_id for proxy counts). Memory:
`feedback_registry_not_name_guessing`, `feedback_ble_config_is_tuned_check_before_asserting`, `reference_identity_model_f1_f5`.
Code read end to end: `person_coordinator.py:1025-1112, :1753-1930`, `aggregation.py:6110-6310`.

**State of play contradiction (code wins):** §3 cites the area-sensor strategies at `person_coordinator.py:1180-1238`
and the WARN at `:1237`; they are at `:1753-1816` / `:1811`. The builder fixes §3 in the build commit (this planning
commit touches only this file, per the dispatch).

## 2. Falsifiable invariant

**INV-BLE-REG:** for every tracked person P on every tick, (i) every entity in P's resolved distance set and P's
resolved area sensor (when not from the operator override) has registry `device_id` == D(P), where D(P) is the single
Bermuda device reached by route (a) or route (b); (ii) if zero or two-plus candidate devices exist, P resolves to NO
device (area: override or None; distance: empty set -> existing fixed 0.5) and a miss is counted; no entity is ever
selected by a substring of P's name, first name, or slug; (iii) no code path changes an entity's `disabled_by`.

Break it by: a scanner whose name contains another person's name (`jaya_3`); a person with a `mobile_app`,
`private_ble_device` and `bermuda` tracker in any order (Oji's 4-tracker list); two `bermuda` trackers on one person;
route (b) resolving through `dr.async_get_device` and landing on the private_ble device; the Bermuda entry loading
after tick 1 (must resolve on a later tick, not stay unresolved); a renamed Bermuda entity_id.

## 3. Producer and consumer checks

**Producer (D(P) and the sets).** Route (a): trackers in `device_trackers` whose entity-registry `platform ==
"bermuda"`; exactly one -> its `device_id`. Route (b), only when (a) finds zero: trackers with `platform ==
"private_ble_device"`; exactly one; read its device's `('private_ble_device', X)` identifier; candidates = devices
other than the tracker's own that carry that identifier AND own at least one `bermuda`-platform entity; exactly one ->
D(P). Health (live 2026-11-14): route (a) resolves all four; route (b) also resolves all four (each has one
private_ble tracker, one Bermuda twin); it fires 0 times live and exists for installs whose person lacks the Bermuda
tracker. Area sensor = the `sensor` entity on D(P) with unique_id == the device uid (the bermuda tracker's unique_id,
or X for route (b)). Distance set = enabled `sensor` entities on D(P) whose unique_id ends `_range` or `_range_raw`
and is not `<uid>_range` (that is the nearest-distance sensor, out of scope). This reproduces today's `distance_to_`
filter (filtered + unfiltered) minus foreign phones.

**Fire check.** Today's producer: confidence 0.3 on 100 % of Ezinne/Ziri/Jaya BLE rows, 0.5 on 100 % of Oji's (audit §2,
7 days). Post-change expectation: 0.3 for all four (ghost inputs). Auto-enable has already fired for the three (their
114 are enabled; Oji 13 of 114 enabled, exactly the foreign matches).

**Consumers (re-verified on c317a6c7).** `data[P]["confidence"]`: trust filter `< 0.3` at `:2154-2163` (no change:
0.3 passes); display `aggregation.py`/`sensor.py` `confidence_level` (Oji "medium" -> "low"); DB `log_person_entry`,
`log_person_snapshot` (value change, no shape change). `location` / `bermuda_area`: census BLE leg, perimeter, lock,
room fusion; unchanged values (all four resolve the same area sensor they do today). `closest_distance` (`:1923`):
never populated today or after (ghost inputs and stale-dict store, both out of scope). Forward trace: no action
changes; that is the point (correctness without behaviour change).

**`aggregation._find_bermuda_sensors` triage (`:6170-6196`) -> DELETE.** It scans `sensor.bermuda_<first>_*` excluding
`_distance`: 0 matches for every person since at least v3.6 naming (sweep L2), so it only ever logs the "falling back to
polling" WARNING at each setup. Its consumer is a per-sensor state listener calling `_handle_bermuda_state_change`
(`:6219`), whose job (stamp `_last_bermuda_update`, refresh from the coordinator) is already done by the
`person_coordinator.async_add_listener` subscription at `:6122` plus `_update_from_coordinator` stamping at `:6265`.
MIGRATE would add a NEW live trigger path (listeners on 3-5 live area/nearest sensors per person firing many times a
minute) for no consumer gain. Bucket: DELETE (dead, superseded, footgun WARN). `_handle_bermuda_state_change` goes with it;
the decay timer stays.

## 4. Deliverables

### D1: `_bermuda_device_for_person(person_entity_id) -> (device_id | None, route, uid | None)`
In `person_coordinator.py`. Routes (a)/(b) exactly as §3; never `dr.async_get_device` for route (b); exception in any
registry call -> unresolved. Unresolved reasons: `no_person_state`, `no_bermuda_tracker`, `multiple_bermuda_trackers`,
`private_ble_ambiguous`, `private_ble_no_twin`. Miss: `_bermuda_resolve_misses[(P, reason)] += 1`; one WARN per (P,
reason) on the second consecutive miss (sibling rule, absorbs the boot race R7), one INFO on recovery. No cache.
- **Verify:** Oji fixture resolves `435615c6` via route (a) for all 24 orderings of his 4 trackers.
- **Verify:** with the bermuda tracker removed from `device_trackers`, route (b) resolves `435615c6`, not `f8ff410c`,
  in both registry insertion orders (the index-slot hazard of §0.3); a mutant using `async_get_device` fails one order.
- **Verify:** two bermuda trackers -> None, reason `multiple_bermuda_trackers`, no name fallback.
- **Test:** `test_ble_person_registry_resolve.py::test_route_a_any_tracker_order`, `::test_route_b_same_identifier_twin`,
  `::test_two_bermuda_trackers_unresolved`, `::test_no_bermuda_tracker_unresolved_counted`,
  `::test_late_bermuda_load_resolves_next_tick`, `::test_warn_once_on_second_miss`.

### D2: area sensor via D1 (retire Strategies 2-4, `:1779-1809`)
Order: Strategy 1 override (unchanged) -> registry area sensor on D(P) -> None. The WARN text at `:1811` becomes
"No Bermuda area sensor for %s (route=%s, reason=%s)".
- **Verify:** all four live-shaped persons resolve the same entity_id as today's code (`sensor.iphone_oji_area`,
  `sensor.ezinne_iphone_area`, `sensor.iphone_ziri_area`, `sensor.iphone_jaya_area`).
- **Verify (discriminates):** a fixture whose Bermuda area entity was renamed to `sensor.phone_x_area` still resolves;
  old code returns None for it.
- **Test:** `::test_area_sensor_matches_today_for_four`, `::test_area_sensor_survives_rename`, `::test_override_still_wins`.

### D3: distance set via D1, auto-enable removed (`:1832-1853`)
Distance set per §3. Delete the `async_update_entity(disabled_by=None)` block (audit R1: would enable 101 Oji sensors
and reload the Bermuda entry). Empty set -> the existing `return 0.5`. Scanner-name matching inside the loop
(`:1885-1897`) is unchanged (non-goal).
- **Verify (discriminates):** fixture with Oji's phone holding `distance_to_jaya_3`: Jaya's set excludes it (old code
  includes it). Foreign-sensor count 12 -> 0 for Ezinne/Ziri/Jaya; their sets equal old set minus foreign (114 each).
- **Verify:** Oji's set = his 13 enabled own-device sensors (old 0); with all inputs `unavailable` he returns 0.3
  (old 0.5). No `disabled_by` write in any test (spy on `async_update_entity`: 0 calls).
- **Test:** `::test_no_foreign_phone_sensors`, `::test_oji_resolves_own_device`, `::test_never_enables_disabled`,
  `::test_nearest_range_sensor_excluded`.

### D4: delete `aggregation._find_bermuda_sensors` + `_handle_bermuda_state_change`
- **Verify:** PersonLocationSensor still updates on a coordinator refresh and still decays (existing tests green);
  no "No Bermuda sensors found" WARNING at setup.
- **Test:** existing PersonLocationSensor tests; `::test_location_sensor_no_bermuda_scan_warning`.

### Live (one post-restart read, feeds the README table)
- `person_presence_snapshots` / `person_visits` rows after restart: Ezinne/Jaya/Ziri confidence 0.3 (unchanged); Oji
  0.3 if he is home (0.5 before; he is abroad until ~11-16, so expect no new Oji BLE rows and mark "not observable").
- HA log after boot: zero `No Bermuda area sensor` WARNs; zero `Auto-enabled Bermuda distance sensor` INFOs; no
  Bermuda config-entry reload in the boot window.
- Entity registry: count of enabled `bermuda` entities identical before and after (no enables).
- `sensor.<person>_location` states for the three home residents match their `sensor.*_area` resolution.

## 5. Test plan
Real `hass` fixture (pytest-homeassistant-custom-component), real `er`/`dr`: a MockConfigEntry for `bermuda` and one
for `private_ble_device`, devices and entities created with `dr.async_get_or_create` / `er.async_get_or_create` in the
live shape (Oji: two `mobile_app` trackers, one `private_ble_device` tracker on device A, one `bermuda` tracker on
device B; A and B both carrying `('private_ble_device', X)`; B holding area `<uid>`, `<uid>_range`, per-scanner
`<uid>_<mac>_range` / `_range_raw`, 101 of them disabled). No `SimpleNamespace` registries (audit R8). The two existing
tests that stub `_find_bermuda_area_sensor` (`test_census_ble_over_face.py:354`,
`test_house_state_sleep_mask_ble_memory.py:1184`) keep their stubs. Mutation drills (review C): restore the substring
test at `:1847` -> `test_no_foreign_phone_sensors` red; restore auto-enable -> `test_never_enables_disabled` red; swap
route (b) to `async_get_device` -> `test_route_b_same_identifier_twin` red.

## 6. Knobs
None. No behavioural number is added; the miss-warn rule (second consecutive miss) is a protocol constant matching the
sibling. Kill switch not provided: the old path is a name guess the operator ruled out, and no decision reads the output.

## 7. Non-goals
- Re-basing confidence / `closest_distance` on `sensor.<dev>_distance`, and the stale-dict `closest_distance` store
  (`:1922-1923`): they turn on the 8 ft music gate for the first time (audit §3.5); card BERMUDA-DISTANCE-SENSORS-DEAD-1,
  operator yes/no.
- Repairing Bermuda's per-scanner entities (upstream / wall-panel proxy MACs).
- The scanner-name substring match inside the confidence loop (`:1885-1897`) and `_get_area_scanners`: all inputs are
  ghosts, so no observable; it moves with the re-base card.
- Auto-enabling Oji's 101 disabled sensors, or any operator-action button to do it.
- An options-flow field for `CONF_BERMUDA_AREA_SENSORS`.
- An NM trip-wire: every consumer of the resolved values is display or a threshold both values pass; the WARN and
  counter are enough. Revisit if a trust reader of confidence appears.

## 8. Tier
**Tier 2** (person_coordinator + aggregation, registry semantics, removal of a live registry writer). Two reviews,
framings A = correctness + registry shapes + route (b) hazard; B = lifecycle (boot order, late Bermuda load, per-tick
cost, listener removal in D4). Plus one adversarial plan review before build. Not 2-DB: no schema, DAO, payload shape
or house-state change; DB values shift only for Oji (0.5 -> 0.3), display-only. Escalate to 2-DB if the build finds any
reader that thresholds confidence at 0.5.
