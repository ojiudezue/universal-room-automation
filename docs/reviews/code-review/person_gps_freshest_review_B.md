# Review B: person GPS freshest-wins (cross-coordinator ripple, lifecycle/restart, test authority)

Branch `fix/person-gps-freshest-wins` @ a33e67c02. Base verified: `git merge-base` = f86375283 (develop). Three-dot diff: `person_coordinator.py` (+59/-6), the presence state-of-play doc, the plan, and `test_path_alpha_d2a_matrix_classifier.py`.
Read first, completely: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `SENSOR_FLEET_CLASSES.md`. No corrections-ledger claim is re-asserted here. The new §10 #23 entry matches the code (see below).

## Ripple: can the GPS axis change a decision path?

The axis is produced by `_read_source_inventory` (`person_coordinator.py:209-295`). It is consumed only by `_classify_matrix_row` (`:364`) at three sites: S1 (`:578`), Bermuda-no-room (`:726`) and no-Bermuda (`:815`).

| Output field | Set from the GPS axis? | Decision consumers | Verdict |
|---|---|---|---|
| `location` | No. Overwritten from `person.<x>.state` at `:740/:768/:781` and `:835/:853/:864`. S1 uses the resolved room. | presence α/β denominator, census `camera_census.py:3080`, room occupants `:1630` | unchanged |
| `tracking_status` | No. Overwritten at the same lines. | `presence.py:6298` (`_tracking_active`), `:6352`, `binary_sensor.py:1953/1992` | unchanged |
| `_person_was_away` / `_lost_away_since` / `_person_lost_since` | No. Keyed on `_ps_state` only. | BLE pre-arrival, path-β grace | unchanged |
| `tracking_reason` | Yes, when the person state is home or away (the home branch keeps the anomalous reasons). | `presence.py:6360-6372` writes it into exclusion-reason strings only. No `==` test on its value anywhere outside `person_coordinator.py` (grep). | display/diagnostic |
| `confidence` | Yes, e.g. 0.75 vs 0.92 in the test case. | `get_person_confidence` → `sensor.py:2962`, `aggregation.py:5252/5849/6008` (attributes); `get_persons_in_room` `:1630` skips non-room locations, so the GPS rows never reach it. `BLE_SILENT_ONLY_AWAY_CONFIDENCE` has no reader outside its emission. | display only |
| `tracker_sources` | Yes | `aggregation.py:5640/5985` attributes | display only |

HVAC and house_state do not read person-coordinator confidence, reason or sources (grep of `domain_coordinators/`). The camera census reads only `bluetooth_le` device_trackers (`camera_census.py:4215-4285`), never the GPS axis. **No decision path changes.** That matches the plan and §10 #23.

## Lifecycle / restart

- **LOW B-L1 (accepted, no fix): boot ordering.** After an HA restart, each tracker's `last_updated` is its re-add time, not its last real fix. Until a tracker reports again, "freshest" means "added last", and a stale iPad `not_home` can win over the phone. HA's own `person` entity has the same behaviour. The effect lasts until the next GPS update and is display-only (table above).
- No new state, listener, task or timer. The function is pure per call and no cache was added (`test_source_inventory_read_per_tick_not_cached` still green). Kill switch off is byte-identical to legacy: the `:268` branch assigns as before and the `:290` block is skipped.
- `_gps_newer_or_equal` returns True on a naive/aware `TypeError` (`:89-92`), which falls back to list order. Fail-safe.
- STALE overlay (`:686`) inherits the previous tick's `tracker_sources`. Unchanged and correct.

## Test authority (real source mutation, targeted file only, `PYTHONDONTWRITEBYTECODE=1`, pycache cleared, tree restored, `git status` clean)

Baseline: 35 passed.

| Mutation (production source) | Result | Named tests RED |
|---|---|---|
| `_gps_newer_or_equal` always returns True (legacy for real readings) | 4 failed | `test_gps_freshest_phone_beats_stale_ipad_listed_last`, `_is_not_any_home_wins`, `_missing_timestamp_ranks_oldest`, `_freshest_wins_through_async_update_data` |
| An unknown reading overwrites the best value | 3 failed | `test_gps_unknown_never_beats_a_real_reading[unknown/unavailable/""]` |
| Final `sources["gps"] = _gps_best_value` dropped | 11 failed | all new GPS tests + `test_source_inventory_read_per_tick_not_cached` |

The tests drive the real `_read_source_inventory` and, through `test_gps_freshest_wins_through_async_update_data`, the real `_async_update_data` no-Bermuda branch. Their oracles are hand-derived, so none of them is hollow. No GREEN rows.
- **LOW B-L2:** the new tests use naive `datetime`s, while production stamps are tz-aware. The comparison is the same either way. The aware-vs-naive `TypeError` fallback has no test. Optional.

## Verdict: **SHIP**

Must-fix: none. B-L1 is accepted by name and B-L2 is optional.
