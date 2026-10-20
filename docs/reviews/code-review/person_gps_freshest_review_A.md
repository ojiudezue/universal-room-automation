# Review A (local correctness + edge cases): fix/person-gps-freshest-wins @ a33e67c02

Base: `git merge-base develop HEAD` = f86375283; diff three-dot. Files: person_coordinator.py (+59),
test_path_alpha_d2a_matrix_classifier.py (+157), state-of-play doc, plan.
Presence read-first: read the GPS-axis section and the §10 ledger entry this branch adds in
PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md, plus SENSOR_FLEET_CLASSES.md. Not the full 719 lines (stated honestly).

## Truth table: `_read_source_inventory` GPS axis (flag ON)
| GPS trackers (real = home/not_home/zone) | Result | Verified by |
|---|---|---|
| none with source_type=gps | `MISSING` (init, person_coordinator.py:223) | test_gps_no_gps_tracker_reads_missing |
| only unknown/unavailable/""/"None" | `unknown` (:293-294) | test_gps_only_unknown_trackers_read_unknown |
| real + fresher unknown | real reading (unknown sets only `_gps_saw_unknown`, :269-270) | test_gps_unknown_never_beats_a_real_reading x3 |
| two real, distinct stamps | newest `last_updated` (:272-277) | freshest tests, both orders |
| exact tie / both undated | later in list (`>=`, None-vs-None True, :84-91) | equal_timestamps, missing_timestamp |
| dated vs undated | dated wins either order (None ranks oldest) | missing_timestamp |
| non-datetime last_updated | coerced to None (:274-275) | missing_timestamp ("not-a-datetime") |
| naive vs aware mix | TypeError -> True (list order) | code read only; unreachable in HA (all aware) |
| router/BLE tracker newest | ignored for GPS axis | non_gps_source_type test |
| flag OFF | legacy last-wins per tracker (:267-268); post-loop block skipped (:290) | kill_switch test |

Ran the file standalone: 35 passed (.venv-ha).

## Consumer trace: is the GPS axis diagnostic only?
The axis enters `_classify_matrix_row` (:343) which sets status/location/confidence/reason. In BOTH branches that
call it (:726 no-Bermuda-area, :815 no-Bermuda-sensor) the wrapper then overrides `tracking_status` and `location`
from `person_state.state` (:740-797, :834-870). The S1 Bermuda branch (:578) only stamps `tracker_sources`;
location/confidence there come from Bermuda. So location/tracking_status are GPS-axis-independent. HOLDS.

What the axis can change: `tracker_sources`, `tracking_reason`, `confidence` (S2: <0.3 floor only; S3: kept unless
reason==no_signal). Consumers of those:
- `confidence`: get_person_confidence (:1477) -> aggregation.py:5252/5849/6008, sensor.py:2962 (all display attrs,
  confidence_level labels); get_room_occupants 0.3 threshold (:1633) -- only for room locations, which never come
  from the S2/S3 branches (location forced to home/away/unknown) -> not affected; DB person snapshot (:904,
  analytics row only); aggregation.py:2084 diagnostics. No trust decision found.
- `tracking_reason` / `tracker_sources`: sensor.py:3233/3288, aggregation.py:5637-5641/5974-5998 (attrs),
  presence.py:6367/6372 (string token in a diagnostic/explain string). No branching on them.
- presence.py all_tracked_persons_away / binary_sensor.py:1950/1989 / camera_census.py:2682/3073 /
  presence.py:5508 read `location` / `tracking_status` only -> unaffected.
Builder's "diagnostic only" claim: VERIFIED.

## Findings
- LOW (pre-existing, newly reachable in a different mix) person_coordinator.py:780-784 / :862-866: person
  `not_home` with GPS axis `home` (classifier row 10, reason `home_ble_silent`, conf 0.75) is stamped
  location=away with reason `home_ble_silent` because the rewrite only fires on `no_signal`. Incoherent display
  only. Requires HA person not_home while freshest GPS = home, which HA's own freshest-GPS rule makes reachable only
  when a router/BLE tracker overrides HA's person; legacy last-wins reached it more easily. No fix required.
- LOW person_coordinator.py:272-277: after HA restart all trackers get restore-time `last_updated` (near-ties
  broken by microseconds of restore order, not list order) until the next fix. Same as HA's person entity;
  diagnostic only. No fix required.
- INFO test helper (test file :211-221): `report_usage` is patched only around construction, only when the real
  frame module is loaded; it suppresses a DUC-construction usage report, not anything under test. Does not mask
  failures. The async anchor test uses `asyncio.get_event_loop()` (deprecated pattern) but passes on the venv.
- INFO kill switch read as a module global at call time; monkeypatch test exercises it. Rung 1 is appropriate.
- WiFi axis still last-wins (documented non-goal, doc updated).

## Verdict: SHIP
No CRITICAL/HIGH/MEDIUM. Two LOWs are display-only and need no change.
