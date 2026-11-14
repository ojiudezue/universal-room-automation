# BLE-PERSON-SENSOR-REGISTRY-RESOLVE-1 — Review A (local correctness + edge cases)

Branch `fix/ble-person-registry-resolve` @ 8cbbb764. Base: `git merge-base HEAD develop` = 1674ef0d (verified); three-dot diff.
Read first, completely: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md`.
No §10 ledger claim re-asserted. Plan: `PLANNING_ble_person_sensor_registry_resolve.md` rev 2 (INV-BLE-REG).

Ground truth used: live `.storage/core.{device,entity}_registry` and `.storage/person` on the Samba mount (read-only).

## Live registry facts (verified, not from the plan)

| Person | device_trackers (platform) | Route | Bermuda device | area sensor (uid == stem) | distance set enabled / total | raw enabled |
|---|---|---|---|---|---|---|
| oji_udezue | mobile_app, bermuda, private_ble_device, mobile_app | a | 435615c6 | `sensor.iphone_oji_area` | 13 / 114 | 6 |
| ezinne | private_ble_device, bermuda, mobile_app | a | 97398998 | `sensor.ezinne_iphone_area` | 114 / 114 | 57 |
| ziri | bermuda only | a | ff7cce21 | `sensor.iphone_ziri_area` | 114 / 114 | 57 |
| jaya | private_ble_device, bermuda | a | 89b8e4c4 | `sensor.iphone_jaya_area` | 114 / 114 | 57 |

Each Bermuda device carries only `('private_ble_device', X)` and its sensors' unique_id stem is X, so route (b)'s `uid = X`
is the correct stem (`person_coordinator.py` `_bermuda_device_for_person`, the `next(i[1] ...)` line). Two registry
entries carry unique_id == X (the tracker and the area sensor); the `e.domain != "sensor"` filter separates them.

## Truth table — `_bermuda_device_for_person` (person_coordinator.py:1764-1838)

| Registry shape | Result | Correct? |
|---|---|---|
| no `person.*` state | (None, `no_person_state`) | yes |
| 0 trackers / only mobile_app | (None, `no_bermuda_tracker`) | yes |
| 1 bermuda tracker (any list order) | (device, `a`, tracker uid) | yes (test_route_a_any_tracker_order) |
| 2 bermuda trackers | (None, `multiple_bermuda_trackers`), no fallthrough to (b) | yes, per INV (ii) |
| bermuda tracker, `device_id` None | (None, `tracker_no_device`), no fallthrough to (b) | yes, (b) only when (a) finds NONE |
| tracker listed but missing from registry | dropped (entries filter), so it acts as absent | yes |
| 0 bermuda, 1 private_ble with Bermuda twin | (twin, `b`, X) by full scan, own device excluded | yes, both insertion orders tested |
| 0 bermuda, 2 private_ble | (None, `private_ble_ambiguous`) | yes |
| private_ble, twin has no bermuda entity / no X identifier | (None, `private_ble_no_twin`) | yes |
| two twins with bermuda entities | (None, `private_ble_ambiguous`) | yes |
| registry raises | (None, `registry_error`) | yes |
| disabled bermuda tracker | still resolves (device membership only) | acceptable, no enable |

`_bermuda_person_sensors` (:1898-1924): `include_disabled_entities=False`, platform `bermuda`, domain `sensor`; area
`u == uid`; distance `startswith(uid_)` and ends `_range` / `_range_raw` and `!= uid_range`. Live sibling unique_ids
(`_area_last_seen`, `_area_switch_reason`, `_floor`, `_ref_power`, `_rssi`, `_scanner`) are correctly excluded. Disabled
or missing area sensor → `no_area_sensor` miss (:1957-1962). No `disabled_by` write anywhere in the diff (INV iii holds).

## Findings

| # | SEV | Where | Finding | Class |
|---|---|---|---|---|
| A-L1 | LOW (latent, pre-existing parity) | `person_coordinator.py:1915-1921` + loop at `:2020-2057` | The distance set holds BOTH `<uid>_<mac>_range` and `<uid>_<mac>_range_raw` for each scanner (live: `sensor.iphone_oji_distance_to_X` and `sensor.iphone_oji_unfiltered_distance_to_X`). The confidence loop counts each as a scanner, so ONE close scanner gives `close_scanners == 2` → 0.9 instead of 0.7, and one very-close scanner counts twice. The old `"distance_to_" in eid` filter matched both too, so this is parity, and inert today (all 356 per-scanner sensors are restored ghosts). It becomes live the day Bermuda recreates per-scanner entities. Plan §3 calls the raw inclusion "reproduces today's filter"; recommend carding it alongside the music-plan seam, not fixing here. | #63-adjacent (two quantities counted as one concept) |
| A-L2 | LOW | `_note_bermuda_resolve` `:1857-1866` | The streak resets whenever the reason changes, so a person alternating between two miss reasons every tick (e.g. `no_area_sensor` / `registry_error`) never WARNs; only the counters show it. Unlikely shape; the `bermuda_resolve` attribute still records it. | warn-once logic gap |
| A-L3 | LOW | `:1951` and `:1992` | The resolver runs twice per person per tick (area lookup, then confidence); route (b) does a full `dev_reg.devices` scan each time. Live uses route (a) for all four (O(trackers)), so cost is nil today. Note only. | perf |
| A-L4 | LOW (out of scope, pre-existing) | `:2032-2040` | Scanner identity is still taken from the entity_id (`split("distance_to_")`) and matched to `_get_area_scanners` names by substring. A renamed Bermuda distance entity silently stops matching. Plan and state-of-play §3 both declare this unchanged; the registry-not-names rule makes it a candidate card (the mac is already in the unique_id). | registry-not-names residual |

No CRITICAL / HIGH / MEDIUM.

## Cleared (holds because)

- **None handling in `_calculate_confidence`**: `device_id` None → empty set → 0.5 (:1996-2001); `uid` None → `[]` (:1905); state None / unknown / unavailable skipped (:2022); non-numeric caught (:2059); registry raise caught by the outer `except` → 0.5 (:2082).
- **Expected live effect**: Ezinne / Ziri / Jaya 126 → 114 (own device only; 12 foreign gone); Oji 0 → 13 enabled sensors, all `unavailable`, so `detected_by_any` stays False and he returns 0.3 when `_get_area_scanners(bermuda_area)` is non-empty, else still 0.5 (:2007-2009). The plan's live criterion already hedges on that. Area sensors are identical for all four. The `< 0.3` filter passes 0.3. Exactly what the code does.
- **Name inference in the diff**: none. `tracked_person_entity_id` is the one id rule (`person_ids.py`); `normalized_name` is only the override config key. Old Strategies 2-4 and the `distance_to_` / person-substring match are deleted.
- **Deleted aggregation path**: `_find_bermuda_sensors`, `_handle_bermuda_state_change` and the `async_track_state_change_event` import are gone with no remaining reference in `custom_components/` or tests (grep). `_unsub_state_listeners` still holds the coordinator listener and is cleared in teardown (`aggregation.py:6126`, `:6148-6150`). `_last_bermuda_update` is still stamped in `_update_from_coordinator` (`:6199-6200`). The decay timer is kept. Nothing dangles.
- **Unrecorded attribute**: `_unrecorded_attributes = {"bermuda_resolve"}` (`aggregation.py:2280`). The sensor already changes attributes every tick (`last_update`, `last_update_ago`), so the counters add no new state-row churn.
- **WARN-once / INFO-on-recovery**: WARN on the 2nd consecutive same-reason miss, once per (person, reason); a hit clears the streak and that person's warned keys and logs INFO only if one was warned (:1840-1866). Late Bermuda load resolves on the next tick (no cache).

## Tests run (targeted only)

`test_ble_person_registry_resolve.py`, `test_music_following.py`, `test_house_state_sleep_mask_ble_memory.py`,
`test_path_alpha_d2a_matrix_classifier.py`, `test_person_gps_assistive.py`, `test_census_ble_over_face.py`,
`test_v455_person_coord_none_data.py`: **253 passed**. `test_pathalpha_d2c_d3_observability.py` fails at collection when
run in this subset (`ModuleNotFoundError: ...database`, a module the diff does not touch; a sys.modules stub-order
artifact). Left to the validator's full-suite name-diff.

## Doc nit

Plan §3 says route (b) "also resolves all four"; Ziri has no private_ble tracker, so route (b) could not resolve him.
Irrelevant to behaviour (route (a) wins for all four).

## Verdict: **SHIP**

No must-fix items. Recommended cards: A-L1 (range + range_raw double count, before any confidence reader above 0.3
ships), A-L4 (scanner identity from the unique_id mac instead of the entity_id).
