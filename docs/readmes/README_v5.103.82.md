# v5.103.82: the room occupancy-anomaly sensor works, on a dwell model

Card: BAYES-OCCUPANCY-ANOMALY-NEVER-EVALUATES-1. Plan: `docs/planning/PLANNING_occupancy_anomaly_dwell_model.md`. Tier 2-DB (new DAO, changed `anomaly_log` row type/payload). Deploy risk: LOW (a disabled-by-default diagnostic sensor; read-only model; no actuation, no notification).

## Problem

- `binary_sensor.<room>_occupancy_anomaly` never evaluated: its logic lived in `async_update`, which HA never calls on a coordinator entity (no polling). The 9 operator-enabled entities sat frozen.
- Its model was wrong for the question: an arrival-count Bayesian score, so a room people stay in for hours (Study A) scored 0.004 and would have read as "unusual".

## Fix

- **Dwell model** (`room_dwell_model.py`, new): share of time each room is occupied by local hour x weekday/weekend, from the 5-minute `environmental_data.occupied` samples URA already keeps (365 days). One bounded `GROUP BY` read 120 s after setup and nightly at 03:40; nothing written; a failed refresh keeps the previous model. Today is excluded from training. DST handled per UTC hour bucket.
- **Sensor** evaluates on every room-coordinator update. On only when: occupied, the cell's usual share is below 2%, the cell has at least 200 samples, occupied at least 15 min, house not GUEST, model refreshed. Off on the first tick any of those fails.
- **Attributes explain the state**: `expected_share`, `threshold`, `cell_samples`, `cell`, `usual_hours`, `occupied_since`, `occupied_for_min`, `debounce_remaining_s`, `occupancy_source`, `radar_sole`, `ble_persons`, `usual_people` (BLE visits, labelled), `learning_status`, `model_status`, `model_refreshed_at`, `suppressed_reason`, `last_anomaly_at`. `occupied_for_min` and `debounce_remaining_s` are unrecorded.
- **No notification on any path** (operator ruling). The rising edge sends `SIGNAL_OCCUPANCY_ANOMALY` (zero consumers) and writes one `anomaly_log` row, type `occupancy.dwell_anomaly`, coordinator `occupancy`, severity INFO. Both are skipped inside the 5-min startup grace, inside the 30-min per-room cooldown, and in presence observation mode (`switch.ura_presence_observation_mode`; the old check read a room-coordinator attribute that does not exist).
- Knobs: `const.OCC_ANOMALY_*` (rung 1). Kill switch `OCC_ANOMALY_DWELL_ENABLED`.
- Side fixes: `get_occupancy_time_today` (wrong key: room name vs entry_id; counted an event type the writer never emits; always 0), `get_occupancy_percentage` (local cutoff vs UTC timestamps; summed time-since-last-motion as episode length), and `get_uncomfortable_minutes_today` (same name key at the same call sites; UTC midnight). All now use entry_id, a local-midnight/naive-UTC window, and entry/exit pairing.

## Tests

- `test_room_dwell_model.py` (17), `test_occupancy_anomaly_dwell.py` (22), `test_occupancy_db_side_fixes.py` (9). DB tests run the real `UniversalRoomDatabase.initialize()`. 45 single-site mutation drills, all RED.
- `test_nm_notify_signature_sites.py`: the deleted NM site's anchors removed. `test_v461_canary_migrations.py`: the Bayesian source-grep tests retired (behavioural row-shape test replaces them).

## Post-deploy check (operator 2026-10-21: the D0 replay runs after deploy)

`ssh ha "python3 - --days 7" < scripts/probes/occupancy_dwell_backtest.py` reports G1-G4. The recorder keeps about 7 days of `binary_sensor.<room>_occupied`, so use `--days 7`. A build-time run (2026-10-21, 7 days, shipped setting 0.02 / 900 s / 48-cell): house median 2 fires/day, max 5 in one room (G1 fails at the plan's 1.0/day); G3 pass (0 Study A daytime fires; Study A weekday 09-17 share 0.56, a dwell signal); G4 fails by construction: a 56-day weekend cell holds at most 192 samples, below the 200 minimum, so weekends never fire. Tune the knobs from the full replay.

## Live acceptance (prospective)

| Criterion | How to check |
|---|---|
| Model refreshed | Any enabled `binary_sensor.<room>_occupancy_anomaly`: `model_status: ok`, `model_refreshed_at` within ~2 min of restart and again after 03:40 |
| State not frozen | `binary_sensor.study_a_occupancy_anomaly` attribute `occupied` matches `binary_sensor.study_a_occupied` at read time |
| Usual room stays off | Study A occupied on a weekday daytime: `expected_share` > 0.02, state `off` |
| Explains off | Every enabled room in `off` shows `learning_status` / `suppressed_reason` consistent with its state (weekends: `learning`) |
| Row shape | After the first `on`: one `anomaly_log` row `metric_name='occupancy.dwell_anomaly'` with non-NULL `expected_share` in `context_json` |
| No notification | `notification_log` has no row from `bayesian_predictor` / `occupancy` after deploy |
| Logs | No `Room dwell model refresh failed` WARNING; no ERROR from `binary_sensor` |
