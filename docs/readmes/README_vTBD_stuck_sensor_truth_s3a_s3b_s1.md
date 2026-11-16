# URA vTBD — Stuck-sensor truth S3a, S3b, S1 (DRAFT; version assigned at deploy)

Cards: CHATTER-MODE-SELECT-NOT-WIRED-1 (S3a), MEDIAROOM-FAN-LEFT-ON-STUCK-SENSORS-1 (S3b, S1 prerequisites),
census-reset prerequisites (arc map §4a row 4). Plan: `docs/planning/PLANNING_stuck_sensor_truth.md` rev 2 (d43633b5),
§3 S3a / S3b / S1 only. S2 shipped as P3-D8 (v5.108.27). S4-S6 not in this release.
Branch `feature/stuck-sensor-s1-s3` (from develop c67b8a78).

## What changes

### S3a — the chatter mode select reaches the rooms (Tier 2)
`select.ura_chatter_mode` writes the INTEGRATION entry, but rooms read the CM entry only, so chatter had never acted
(every chatter NM read "WOULD quarantine (shadow)"). Now one resolver, `_nm_cycle_a.chatter_mode_option`: integration
option, else the CM option (pre-D7 migrate target), else `shadow`. Rooms and the select both read it (INV-S3a). The
cache is flushed by the select write, the integration update listener and the CM knob flush. `chatter_mode` joins the
integration reload-suppress allowlist, so flipping the select no longer reloads the parent entry.
**Live effect (operator: act):** the select already reads `act`, so at deploy chattering inputs (Garage A/B ratgdo, the
Master Bathroom InvisOutlet, the media MS600 bit) are excluded from room fusion while they chatter.

### S3b — MS600 motion bit by registry model (Tier 2)
The meross_lan record that owns `..._sensor_presence_motion` has `model` `ms600-un` (model_id None) and resolved
`unknown`. `family_for_model` now splits the first token on whitespace / hyphen / underscore and lists `ms600-un`, so the
bit is `generic_radar` by registry model; the name regex is no longer load-bearing. Golden over every live device pair:
only `ms600-un` changes. Effect: a bit-only tick is radar-sole (recheck window factor 1.5); Guest Bedroom 1 (Fan Mode
Room temperature) becomes eligible for the radar recheck route once unpaused (Q-B); GB2 / Media stay vetoed
`fan_control_off`.

### S1 — P22 off-pulse tolerance (Tier 2-DB)
A MOTION-class room input (ZG-204ZV / PIR family, not a still holder) no longer restarts its 4 h continuous-on run on an
off or dead stretch shorter than 10 s, and the run starts at the rising edge's `last_changed`. Still holders (radar, bed,
camera, BLE, MS600 bit), unknown families and a knob of 0 keep the old rule exactly. Knobs (rung 1):
`STUCK_P22_OFF_GAP_TOLERANCE_S` 10, `STUCK_P22_HOURS` 4.0 (replaces the literal). New pure
`sensor_capability.is_still_holder` / `is_p22_motion_class`.

## Pre-deploy gate NOT yet run (S1)
Plan step 0: a read-only 7-day recorder replay of every motion-class input; GO = zero runs ≥ 4 h S1 would create that
overlap a BLE-confirmed person in the room for > 30 min. Not run by the builder (probe work).

## Acceptance (prospective, live)
| # | Criterion | Signal |
|---|---|---|
| S3a-1 | Next chatter NM reads "quarantined", not "WOULD quarantine (shadow)" | `notification_log` / NM text |
| S3a-2 | The chattering input is listed under client `chatter` | room `automation_health.excluded_sensors` |
| S3a-3 | Flipping `select.ura_chatter_mode` does not reload the parent entry | HA log: "in-place apply, suppressing reload (changed_keys=['chatter_mode'])" |
| S3b-1 | Media radar-sole tick true when only the MS600 bit is on | `binary_sensor.media_room_occupied` radar-sole attribute |
| S1-1 | A motion-class input holding ≥ 4 h with sub-10 s blips stays in `automation_health.stuck_sensors` across the blips | room Automation Health attributes |
| S1-2 | One `continuous` stuck NM per (room, sensor, day), not two | `notification_log` |

## Tests
`quality/tests/test_stuck_sensor_s3a_chatter_mode.py` (12), `test_stuck_sensor_s3b_ms600_family.py` (10),
`test_stuck_sensor_s1_p22_tolerance.py` (34); stubs of `_nm_cycle_a` updated in three chatter test files; integration
allowlist pin and two AST-slice namespaces updated for `chatter_mode`.

## Not done / deferred
- S2 (shipped as P3-D8 in v5.108.27; its same-run check G7 and edge filter are NOT in this release).
- S4, S5, S6 (secondary fan work, out of scope).
- S1 step-0 replay (above).
