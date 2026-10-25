# Review C (test authority, per-site source mutation) - CENSUS-BLE-OVER-FACE-1

Branch fix/census-ble-over-face @ ec9adbfa2 (base df3bb8412). Suite: test_census_ble_over_face.py + test_face_cross_check_behavioral.py + test_census_v2.py, baseline 117 passed. One mutation at a time, pycache cleared, PYTHONDONTWRITEBYTECODE=1, tree restored and verified clean after.

| # | Site (camera_census.py unless noted) | Mutation | Result | Killing test |
|---|---|---|---|---|
| M1 | raw guard `raw_value == "not_home"` | never true | RED | test_census_face_dropped_raw_not_home_unchanged |
| M2 | raw read of person.state | always None | RED | same |
| M3 | flag branch | `elif False` | RED | test_census_face_dropped_when_ble_overruled |
| M3b | flag branch | `elif True` (ignores flag) | RED | test_census_face_kept_when_flag_false |
| M4 | helper call person_state_for_trust | replaced by raw | RED | test_census_face_dropped_when_ble_overruled |
| M5 | exception fallback | fail-closed not_home | RED | test_census_face_fail_open_helper_raises |
| M6 | trust compare | never drops | RED | test_census_face_dropped_when_ble_overruled |
| M6b | trust compare | always drops | RED | test_census_face_kept_when_ble_leads_off |
| M7 | drop_source = "ble_overrule" | removed | RED | test_census_face_dropped_when_ble_overruled |
| M8 | counter increment | +0 | RED | same |
| M8b | counter bumped on raw drops too | | RED | test_census_face_dropped_raw_not_home_unchanged |
| M9 | **per-tick reset in run loop (~:1718)** | removed | **GREEN** | none |
| M10 | drop `continue` | never taken | RED | test_census_face_dropped_when_ble_overruled |
| M11 | **sensor.py attr `face_dropped_ble_overrule_count`** | removed | **GREEN** | none |
| M12 | sensor.py `_unrecorded_attributes` | emptied | RED | test_counter_kept_out_of_recorder |
| M13 | const.py default | True -> False | RED | test_census_face_dropped_when_ble_overruled |
| M14 | `__init__` counter init | removed | GREEN (benign) | redundant: increment uses getattr default, reset assigns each tick, sensor uses getattr |

## Findings

- **MEDIUM (Bug class #53 / #62 hollow coverage) M9: per-tick reset untested.** Without the reset the "PER-TICK" counter silently becomes a lifetime accumulator; the code comment and the const/sensor semantics promise per-tick. Need a test that runs two ticks (drop on tick 1, none on tick 2) and asserts the counter is 0 after tick 2, plus a drill that detaches the reset line.
- **MEDIUM M11: sensor attribute line untested.** Nothing asserts `face_dropped_ble_overrule_count` appears in URAPersonsInHouseSensor.extra_state_attributes (test_counter_kept_out_of_recorder only checks the `_unrecorded_attributes` set). Deleting the producer line leaves the suite green and the operator display would silently vanish. Need an attribute-value test driven through the sensor with census counter = N.
- **INFO M14:** `__init__` init is redundant (getattr fallbacks); not load-bearing. No action.
- Coordinator.py comment is non-load-bearing (not mutated).

Verdict: **FIX-REQUIRED** (two MEDIUM untested sites, both display-only counter; behavioral guard paths M1-M8b, M10, M13 are all anchored RED).
