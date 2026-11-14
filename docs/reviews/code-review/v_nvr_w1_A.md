# Review A (local correctness + registry rule): NVR witness W1

Branch `feature/nvr-witness-w1-pairing` @ d450c382. Base = `git merge-base develop HEAD` = 4b825c50 (verified; develop's
`camera_resolver.py` is unchanged since 4b825c50). Plan `PLANNING_nvr_witness_layer.md` §5 / W1. Not HVAC or presence-sensor
work; identity manual §3-§4 consulted for the resolver ladder. Identity model: W1 changes the F3 producer input (door
crossing person-sensor subscription for garage_a) and the F4 sighting physical key; no consumer policy changes.

**Verdict: SHIP.** No CRITICAL/HIGH/MEDIUM.

## Checks

| Check | Result | Evidence |
|---|---|---|
| Four conditions implemented as planned | holds | `camera_resolver.py:1566-1601`: (1) Frigate input via `_infer_integration` + object name from identifier (`_frigate_object_name_for_device`); (2) `len(candidates) != 1` over the non-Frigate camera-device slug index; (3) `_frigate_stem_to_device_ids[obj] - {input}` empty; (4) candidate has no Frigate identifier |
| No false pair on HA `X` / `X_2` | holds, except the plan's accepted residual | (3) refuses two Frigate devices of one object name; (2) refuses two non-Frigate devices; residual (one non-Frigate + one Frigate, distinct cameras, same name) is tested as accepted (`test_resolver_residual_one_name_one_camera_each_side_pairs`) |
| Registry-only evidence | holds | object name from device `identifiers`; candidate from `name_by_user or name` through `homeassistant.util.slugify` (`:56-70`); no entity_id parsing in the new path. Index membership uses `_camera_entity_by_device`, which is keyed by entity domain from the registry, not the id string |
| slugify edge cases | holds | "Stairs - top" → `stairs_top` (live Protect device, fixture row matches live). Frigate object with `-` or uppercase would not equal the slug → no pair (fail closed, never a false pair). Unicode: slugify transliterates; Frigate names are ASCII; worst case is a miss |
| Disabled entities | holds | index built only from enabled `camera.*` (`:671` A-MED-1 gate precedes `:687`); `test_resolver_object_name_ignores_device_with_only_disabled_camera` |
| Disabled devices | holds (indirect) | `device.disabled_by` is not read, but HA sets `disabled_by=device` on the device's entities, so the entity gate excludes it. Condition (3) counts Frigate devices regardless of enabled state, which only makes it more conservative |
| Knob off byte-identical | holds | `:1047` guard; `test_resolver_knob_off_byte_identical_all_callers` passes, and I re-ran develop's own `camera_resolver.py` (main checkout) over the fixture: snapshot == golden, 105 cameras |
| Fixture honesty | holds | Re-derived from live `.storage`: all 138 live `camera.*` entities with a device are present with identical platform/device_id/disabled_by; device rows for Garage A, Upstairs Hall, Rear PTZ, Stairs - top (Protect) and their Frigate twins match name/name_by_user/identifiers; no duplicate Frigate object names live |
| Targeted tests | 19 passed | `quality/tests/test_nvr_witness_w1_resolver.py` |

## Camera-key changes (upstairs_hall_2 b75c→b063, stairs_top_2 ebc6→74f1, rear_ptz_2 c887→c62c)

`canonical_camera_key` (`camera_resolver.py:491`) consumers: `person_sighting.py:334` (`_views`, `_face_to_physical`),
`:505` (`_egress_keys`), debounce `("sighting", slug, physical_camera)` (`:611`); `transit_validator.py:2410` (path-map
validation context). All are in-memory and rebuilt at setup. Persisted surfaces checked: `interior_paths.json` names
entity_ids, not device ids; `.storage/universal_room_automation.perimeter_agreement` is keyed by perimeter stems
(`front_side_ptz`, `rear_ptz`, ...) from `_camera_key_for_sensor`, not the resolver key; grep of all URA `.storage`
files and the two JSON config files for the six full device ids finds none; `database.py` has no physical-camera
column. Effect of the change: at the deploy restart the Frigate and Protect legs of each camera now share one key
(min device id over both), which is the intended dedup; there is no stale key to migrate. Room fused sensor
`physical_camera_id` (`binary_sensor.py:1847`) is `sorted(input ids)[0]` and is unchanged (asserted in the golden test).

## Findings

| # | SEV | Where | Finding | Class |
|---|---|---|---|---|
| A1 | LOW | `PLANNING_nvr_witness_layer.md` §5 last para | Plan says W1 changes perimeter Part A input for garage_a; measured not true (perimeter legs already reached Protect via the `_N` stem bridge in `resolve_detection_legs`; `test_perimeter_resolve_legs_unchanged`). README states the correction; the plan text should be amended so W0/W2 baselines are not read against a predicted shift that will not happen. Code wins. | doc drift |
| A2 | LOW | plan §5 vs README | Plan predicted one changed camera; registry gives seven (operator accepted all seven 2026-11-14). Same amendment. | doc drift |
| A3 | LOW (info) | `camera_resolver.py:56-70` | Pairing fails closed when the Frigate object name is not already a slug (hyphen/uppercase). No false pair; would only matter on another install. Worth a sentence in the manual. | portability note |

No must-fix items.
