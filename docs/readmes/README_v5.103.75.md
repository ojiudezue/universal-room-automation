# v5.103.75 (DRAFT): house-state sensor attribute churn left out of the recorder

> Draft. The version number may change at deploy time. Card: HOUSE-STATE-SENSOR-ATTR-CHURN-1. Tier 1.

## Summary
`sensor.ura_presence_coordinator_presence_house_state` wrote about 2,870 recorder rows a day.
Measured 2026-10-19, 2,869 of them carried a distinct attribute blob (average 3.3 KB, about
9.5 MB/day of attribute JSON) for 13 state changes. The main cause is `dwell_seconds`, which
changes on every 30 s poll. HA dedupes attribute blobs by content, so leaving the churny keys
out of the recorder lets rows share blobs again.

## What changed
- `sensor.py` `PresenceHouseStateSensor._unrecorded_attributes` now also lists `dwell_seconds`,
  `zones`, `signal_consensus`, `signal_consensus_band` and `signal_consensus_inputs`. It already
  listed `stale_counted_home` and `nobody_home_zone_input`.
- Live `state.attributes` are unchanged. Dashboards, the PWA and in-process readers see every key.
- Low-churn diagnostics are still recorded: `state`, `previous_state`, `state_since`,
  `veto_path`, `last_veto_decision`, `last_away_*`, `away_entries_today`, `guest_reason`,
  `census_count` and `boot_settle_*`.

## Consumer check (recorder-history readers)
| Key | 24 h changes | History reader found | Decision |
|---|---|---|---|
| `dwell_seconds` | 2,869 | None. `routine_forecaster.py:343` computes its own local `dwell_seconds` from state timestamps and does not read the attribute | Unrecord. It can be derived from `state_since` |
| `zones` | 678 | None. Frontend bundles and tests read live state only | Unrecord |
| `signal_consensus_inputs` | 666 | `PLANNING_fan_noise_mitigation_layer2_actuation.md:44` lists "recorder attribute history" as a diagnostic recipe | Unrecord. The same dict stays recorded on `sensor.ura_signal_consensus_confidence` (`sensor.py` `SignalConsensusConfidenceSensor`) |
| `signal_consensus` | 67 | None | Unrecord. It is the native state of `sensor.ura_signal_consensus_confidence` |
| `signal_consensus_band` | 64 | None | Unrecord. It is recorded as `consensus_band` on the same sensor |
| `fan_interference_active` | 184 | n/a | Not a top-level key. It lives inside `signal_consensus_inputs` |

The `veto_path` and `last_veto_decision` history readers (`PLANNING_v4.7.15.1...md:458`, README_v5.103.54) are unaffected because both keys stay recorded.
Existing idiom followed: `_unrecorded_attributes` on `SafetyStatusSensor`, `SecurityComplianceSensor` and others in `sensor.py`.

## Tests
- New `quality/tests/test_house_state_attr_unrecorded.py`. It asserts on HA's combined
  `Entity.__combined_unrecorded_attributes`, which is the set the recorder actually receives.
  Churny keys must be in it and kept diagnostics must not be.
- `test_house_state_sleep_mask_ble_memory.py::test_unrecorded_attributes_set` exact pin updated.
- Mutation drill: removing `dwell_seconds` made the test go RED, and so did adding `veto_path`.
  The file was restored afterwards.

## Live acceptance (prospective, one-shot recorder query 24 h after deploy)
- Distinct `attributes_id` per day for the sensor drops from about 2,869 to **< 400**.
- Row count per day is unchanged (about 2,870).
- State history is intact: the 13 or so daily state changes are still present.
- **Discriminator:** if the row count drops sharply while blobs stay high, something else
  changed (polling or write path), not this fix. If blobs stay at about 2,869, the exclusion
  did not take effect (wrong class, or a stale install).
