# v5.103.83: the room occupancy-anomaly sensor works, on a dwell model

Card: BAYES-OCCUPANCY-ANOMALY-NEVER-EVALUATES-1. Plan: `docs/planning/PLANNING_occupancy_anomaly_dwell_model.md`. Tier 2-DB (new DAO, changed `anomaly_log` row type/payload). Deploy risk: LOW (a disabled-by-default diagnostic sensor; read-only model; no actuation, no notification).

## Problem

- `binary_sensor.<room>_occupancy_anomaly` never evaluated: its logic lived in `async_update`, which HA never calls on a coordinator entity (no polling). The 9 operator-enabled entities sat frozen.
- Its model was wrong for the question: an arrival-count Bayesian score, so a room people stay in for hours (Study A) scored 0.004 and would have read as "unusual".

## Fix

- **Dwell model** (`room_dwell_model.py`, new): share of time each room is occupied by local hour x weekday/weekend, from the 5-minute `environmental_data.occupied` samples URA already keeps (365 days). One bounded `GROUP BY` read 120 s after setup and nightly at 03:40; nothing written; a failed refresh keeps the previous model. Today is excluded from training. DST handled per UTC hour bucket.
- **Sensor** evaluates on every room-coordinator update. On only when: occupied, the cell's usual share is below 2%, the cell's samples span at least 4 distinct days (and at least 24 samples, a floor), occupied at least 30 min (`OCC_ANOMALY_DEBOUNCE_S` = 1800; the plan's 900 failed G1), house not GUEST, model refreshed. Off on the first tick any of those fails.
- **Attributes explain the state**: `expected_share`, `threshold`, `cell_samples`, `cell_days`, `cell`, `usual_hours`, `occupied_since`, `occupied_for_min`, `debounce_remaining_s`, `occupancy_source`, `radar_sole`, `ble_persons`, `usual_people` (BLE visits, labelled), `learning_status`, `model_status`, `model_refreshed_at`, `suppressed_reason`, `last_anomaly_at`. `occupied_for_min` and `debounce_remaining_s` are unrecorded.
- **No notification on any path** (operator ruling). The rising edge sends `SIGNAL_OCCUPANCY_ANOMALY` (zero consumers) and writes one `anomaly_log` row, type `occupancy.dwell_anomaly`, coordinator `occupancy`, severity INFO. Both are skipped inside the 5-min startup grace, inside the 30-min per-room cooldown, and in presence observation mode (`switch.ura_presence_observation_mode`; the old check read a room-coordinator attribute that does not exist).
- Knobs: `const.OCC_ANOMALY_*` (rung 1). Kill switch `OCC_ANOMALY_DWELL_ENABLED`. Learning gate `OCC_ANOMALY_MIN_CELL_DAYS` = 4 plus floor `OCC_ANOMALY_MIN_CELL_SAMPLES` = 24. A sample-count gate of 200 was replaced at fix-up because a 56-day weekend cell holds at most 192 samples (16 days), so weekends could never learn.
- **The four room "today" sensors now refresh** (Occupancy Pct Today, Time Occupied Today, Time Uncomfortable Today, Avg Time To Comfort). Same defect as the anomaly sensor: logic in `async_update`, never called. Now each coordinator update starts at most one DB refresh per sensor per `TODAY_SENSOR_REFRESH_S` (300 s), never two in flight, in a task cancelled on removal. Values are quantized (minutes to `TODAY_SENSOR_MINUTES_QUANTUM` = 5, percent to `TODAY_SENSOR_PCT_QUANTUM` = 1) to keep recorder churn low (v5.103.78 pattern). They are still disabled by default.
- Side fixes: `get_occupancy_time_today` (wrong key: room name vs entry_id; counted an event type the writer never emits; always 0), `get_occupancy_percentage` (local cutoff vs UTC timestamps; summed time-since-last-motion as episode length), and `get_uncomfortable_minutes_today` (same name key at the same call sites; UTC midnight). All now use entry_id, a local-midnight/naive-UTC window, and entry/exit pairing.
- **Missing exit rows no longer become phantom occupancy (review A).** The room coordinator now always writes the `occupancy_events` exit row on the occupied->vacant edge (`duration` NULL when the fan-demote or failsafe path already cleared the motion stamp; the fan-recheck release, which clears occupancy outside the tick, writes its own exit row once through the same writer; live 7 days had 50 entry->entry pairs against 1586 entry->exit). The readers bound the prior-event look-back and cap any one episode at `OCC_EPISODE_MAX_S` = 12 h; an entry while an episode is open closes it at that entry or the cap, whichever is sooner. The only other reader of `duration` (the room data export) already writes NULL as empty. Occupancy Pct Today divides by time since `start_of_local_day` (DST-correct).
- **Model build off the event loop (review B).** The parse of ~60k hour rows and the visits runs in `hass.async_add_executor_job`; the swap happens on the loop, and a stop during the read or build discards the result. One retry `OCC_ANOMALY_RETRY_DELAY_S` = 600 s after a failed or no-database first build. `OCC_ANOMALY_USUAL_PEOPLE_MAX_VISITS` raised 50000 -> 200000 (live: ~66k closed visits in 56 days were being truncated).

## Tests

- `test_room_dwell_model.py` (22), `test_occupancy_anomaly_dwell.py` (26), `test_occupancy_db_side_fixes.py` (32). DB tests run the real `UniversalRoomDatabase.initialize()`. 74 single-site mutation drills, all RED (review fix-up added 18: exit-row producer and edge guard, episode cap, entry-closes-episode, latest prior event, window-start inclusive, event-type filter, in-window evidence, open-at-start, multi-day window, naive-UTC window, share lower bound, stop during read/build, executor build, retry scheduled / only on failure / cancelled on stop, comfort quantization; then the fan-recheck release exit row, its real-edge guard, and a mixed-timezone visit row skipped instead of failing the build).
- Review-fix notes: the tz-aware normalisation in the visits parser was dropped (G16; `person_visits` times are naive local by construction). The prior-event look-back bound is belt-and-braces under the 12 h cap (a dangling entry older than the cap contributes nothing either way); it keeps the query small. The exit-row writer was extracted to `UniversalRoomCoordinator._async_log_occupancy_edge` so it can be tested against the real DB; its call inside `_async_update_data` is not behaviourally anchored (no full room-tick harness exists).
- `test_nm_notify_signature_sites.py`: the deleted NM site's anchors removed. `test_v461_canary_migrations.py`: the Bayesian source-grep tests retired (behavioural row-shape test replaces them).

## Post-deploy check (operator 2026-10-21: the D0 replay runs after deploy)

`ssh ha "python3 - --days 7" < scripts/probes/occupancy_dwell_backtest.py` reports G1-G4. HA's recorder keeps 7 days (`purge_keep_days: 7`), so the replay of `binary_sensor.<room>_occupied` covers 7 days. The training data (`environmental_data`) goes back to 2025-11-19, so the 56-day window is full.

Build-time run (2026-10-21, 7 days, **shipped setting 0.02 / 1800 s / 48-cell**, day gate 4 / floor 24):

| Gate | Result | Detail |
|---|---|---|
| G1 rate | PASS | house median 0 fires/day (5 in 7 days: 0, 0, 1, 2, 0, 0, 2); max 2 in one room |
| G2 quality | PASS (heuristic) | 0 of 5 fires overlap a resident BLE visit (Guest Bedroom 2 Bathroom x2, Stair Closet, Game Room, Exercise Room); needs a human read |
| G3 Study A | PASS | 0 daytime fires; weekday 09-17 share 0.56 |
| G4 learning | PASS | 47/47 rooms have every cell learned (weekend cells now included) |

At the plan's 900 s the same replay gave a house median of 5 fires/day and 11 in one room (G1 fail), which is why 1800 ships. Exercise Room fires (the most frequent room at 900 s, one at 1800 s) are probably the fault of its radar (card EXERCISE-ROOM-ZK-NEVER-ON-1), not real visits.

## Live acceptance (prospective)

| Criterion | How to check |
|---|---|
| Model refreshed | Any enabled `binary_sensor.<room>_occupancy_anomaly`: `model_status: ok`, `model_refreshed_at` within ~2 min of restart and again after 03:40 |
| State not frozen | `binary_sensor.study_a_occupancy_anomaly` attribute `occupied` matches `binary_sensor.study_a_occupied` at read time |
| Usual room stays off | Study A occupied on a weekday daytime: `expected_share` > 0.02, state `off` |
| Explains off | Every enabled room in `off` shows `learning_status` / `suppressed_reason` consistent with its state; weekend cells show `learning_status: ok` and `cell_days` >= 4 |
| Today sensors refresh | An enabled `sensor.<room>_time_occupied_today` changes during the day in steps of 5 min, and its `last_updated` moves at most every ~5 min |
| Row shape | After the first `on`: one `anomaly_log` row `metric_name='occupancy.dwell_anomaly'` with non-NULL `expected_share` in `context_json` |
| Exit rows | `occupancy_events` for any room: no `entry` followed by `entry` created after deploy (fan-demote / failsafe exits now have a row with NULL duration) |
| No notification | `notification_log` has no row from `bayesian_predictor` / `occupancy` after deploy |
| Logs | No `Room dwell model refresh failed` WARNING; no ERROR from `binary_sensor` |

## Validated 2026-10-21 (restart ~18:23 CDT)

| Criterion | Result | Evidence |
|---|---|---|
| Load | PASS | 0 URA ERROR/Traceback lines after boot; 0 `write worker is closed` over the restart |
| Model builds after start | PASS | `binary_sensor.studya_room_device_occupancy_anomaly`: `model_status ok`, `model_refreshed_at 23:27:58Z` (≈2 min after start), `model_window_days 56` |
| Sensor evaluates with attributes | PASS | Study A, weekday 18:00 cell: `expected_share 0.3026`, `cell_days 40`, `cell_samples 466`, `learning_status ok`, `usual_people` Oji; Kitchen: `expected_share 0.1848`, usual people Jaya 0.56 / Oji 0.32 / Ezinne 0.10; both `off` (rooms vacant) |
| Measures dwell, not arrivals | PASS | Study A weekday share 0.30 at 18:00 (old Bayesian model gave ~0.01) |
| Exit rows on vacancy | PASS (rate) | occupancy_events today (UTC): 240 entry / 228 exit, normal daily rate; no burst after the restart |
| NULL-duration exit on fan/failsafe vacate | PASS (2026-10-28) | occupancy_events since 10-21: 1,880 exit rows, 33 with NULL duration (latest 2026-10-28T01:43:47) |
| Replay G1-G4 after a week live | PASS (2026-10-28) | Probe `--days 7` (10-21..10-27, 47 rooms, writer healthy, null_share 0): at the shipped setting (48-day model, 0.02, 1800 s) the replay gives 0 fires (G1 true); G2 vacuous (no fires); G3 Study A weekday 09-17 share 0.533, 0 daytime fires; G4 47/47 rooms fully learned, weekend cells max 16 days |
| Live fires (one week) | 0 fires | `anomaly_log` `occupancy.dwell_anomaly`: 0 rows ever. Recorder: 9 enabled `binary_sensor.*_occupancy_anomaly`, 0 `on` states since 10-21. Matches the replay. Sensor is evaluating, not stuck: `binary_sensor.studya_room_device_occupancy_anomaly` `model_status ok`, refreshed 10-28 03:40 CDT, `expected_share 0.594`. No fires = nothing for the operator to judge; it also means the row-shape criterion is still unexercised live |

Note: at 1800 s the sensor is very quiet. The replay fired 7 times in the week at 900 s with threshold 0.02 (max 2 per room, G1 still true), so 900 s is the knob to turn if the operator wants some signal.
