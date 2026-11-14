# Review A: PHONE-LEFT-BEHIND-CAMERA-LEG-1 (local correctness, edge cases, data integrity)

Branch `feature/phone-left-behind-camera` at 5ff9c37e. Diff base: merge-base with develop = 688042b3
(three-dot). Read first: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (complete),
`docs/architecture/SENSOR_FLEET_CLASSES.md`. Focused tests: `test_phone_left_behind_camera_leg.py`,
`test_path_alpha_d9_room_corroboration.py` (25 passed), `test_transit_protect_sourced.py`,
`test_identity_fusion_d2_d3_d4.py`, `test_census_device_switches.py` (74 passed).

## Findings

| # | Sev | Where | Finding | Bug class |
|---|---|---|---|---|
| A-M1 | MEDIUM | `binary_sensor.py:2133`, `:2331-2335`; `const.py:3259` | New recorder churn versus develop. All four sensors are ENABLED live (`binary_sensor.universal_room_automation_{oji_udezue,ezinne,jaya,ziri}_phone_left_behind`). On develop `hours_since_camera_sighting` was always None (the store never held a name), so it never changed a state. Now, once a person has a sighting, the stepped age changes every 900 s on a 30 s-polled entity, so each sensor writes a state row every 15 min (up to 96/day/person, about 384/day for the house) until a restart clears the RAM store. `_unrecorded_attributes` only removes the value from the attribute blob; the row is still written. `last_camera_sighting_at` (static between sightings) already carries the same information. Fix: drop `hours_since_camera_sighting` (or keep the key at None), or justify the 384 rows/day. | Recorder churn (display attribute) |
| A-L1 | LOW | `binary_sensor.py:2221-2229` vs develop step 4 | "Byte-identical for every input" holds for every REACHABLE live input, not for every input. Develop returned False when `TransitValidator._camera_sightings[<display name>]` held a sighting under 1 h old. That required a camera entity with `face_recognition` on and a `person_id`/`face_id`/`label` attribute equal to the title-cased display name (e.g. `Oji Udezue`). The plan measured 0 of 102 person entities with any such attribute, so this is unreachable in this house. A future integration that sets `label` to a display name would have flipped the develop verdict; the branch never does. Accept by name in the README. | #63 (concept equality by measurement, not by construction) |
| A-L2 | LOW | `quality/tests/test_phone_left_behind_camera_leg.py:14`, `:120` | The verdict-identity oracle `_develop_verdict` is rewritten from the plan's description of develop, which already assumes the old leg is always None. It cannot catch A-L1. Acceptable given the 0/102 measurement; note it in the test docstring. | #62-adjacent (oracle shares the hypothesis) |

## Cleared

- **Verdict (INV-1):** step 4 now returns None when `transit_validator` is missing, else True; develop returned None / `sighting is None`, which is always True live (A-L1). Steps 1-3 are untouched. `test_verdict_identity_cross_product` covers the ladder.
- **No trust read (INV-2):** `is_on` never calls `_last_sighting`; only `extra_state_attributes` does (`binary_sensor.py:2262`).
- **Person id resolution:** both sites use `person_coordinator.tracked_person_entity_id` (`person_coordinator.py:130`). Binary sensor passes the raw `CONF_TRACKED_PERSONS` entry (`binary_sensor.py:132`); NextRoom passes `person_id` = the entry after `split('.')[-1]` (`aggregation.py:388`), so `'Oji Udezue'` and `person.oji_udezue` both map to `person.oji_udezue`. No hand-built `person.{...}` in the diff. unique_id unchanged (`binary_sensor.py:2154`).
- **None handling:** `_last_sighting` returns None for no manager / no presence / exception (`binary_sensor.py:2231-2245`); `CoordinatorManager.coordinators` is a dict property (`manager.py:412`). `_sighting_attributes` returns the all-None shape for None or a bad `ts`; age clamped at 0 for a future ts. NextRoom `_recent_person_sighting` has no local guard but its only caller wraps it in try/except (`sensor.py:3559-3565`).
- **Deleted paths:** repo-wide grep for `get_last_camera_sighting`, `TRANSIT_PHONE_LEFT_BEHIND_HOURS`, `PHONE_LEFT_BEHIND_HOURS`, `phone_left_behind_hours` finds only the deletion comment and a negative test assert. `identity_status` / `camera_person_id` have no reader outside `transit_validator.py` (transitions.py reads only `path_method`). Removing face-matched rule 1 in `_correlate_sighting_to_transition` is behaviour-neutral because no stored sighting ever carried a non-`unidentified` `person_id`.
- **Attribute stability:** `person_id`, `ble_location`, `census_persons_in_house`, `room_corroboration_*` unchanged; `hours_since_camera_sighting` kept (new semantics); `phone_left_behind_hours` removed (documented, §3 of the presence doc). NextRoom keys unchanged; `transit_camera_validated` can now read True (display only, no reader).
- **Quantum constant:** rung 1, `<= 0` = unstepped, documented on the constant. Arithmetic floors correctly (`age // q * q`).

## Summary

| Severity | Found | Must fix |
|---|---|---|
| CRITICAL | 0 | 0 |
| HIGH | 0 | 0 |
| MEDIUM | 1 | 1 (A-M1, or explicit operator acceptance) |
| LOW | 2 | 0 (document) |

Bug classes: recorder churn 1, #63 1, #62-adjacent 1.

## Verdict

**FIX-REQUIRED** (small): A-M1, drop or null the age attribute so the enabled sensors write no new rows between sightings, or get the operator to accept about 384 rows/day. A-L1 and A-L2 go in the README as accepted residuals. Everything else: SHIP.
