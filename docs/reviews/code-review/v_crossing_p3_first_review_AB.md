# Crossing vision Phase 3 first set (P3-D1, P3-D5, P3-D8): review A + B

Branch `feature/crossing-p3-first` at 48d4bc94, diff `340bfe7f...48d4bc94`. Read only.
Cycle tests + layer guard (`test_crossing_vision_p3_first.py`, `test_person_awareness_layer_guard.py`): 150 passed.
The state-of-play doc, the sensor fleet doc and QUALITY_CONTEXT were not re-read end to end in this pass. P3-D8 claims were checked against code.

Verdict: **SHIP**. No CRITICAL, HIGH or MEDIUM findings. Three LOWs.

## A. Local correctness

| # | Sev | Site | Finding |
|---|---|---|---|
| A1 | LOW | crossing_vision.py:921 | The call-time gate in `_run` reads `_calls_today`, not `_calls_counted()`. I confirm the builder's claim that it can't be reached. While the hold is on, the schedule gate (:745) skips every crossing. No request can exist before setup turns the hold on. A midnight `_roll_day` clears the hold and the counter together. Optional fix for defence in depth: use `_calls_counted()` here too. |
| A2 | LOW | crossing_vision.py:933 vs :1131 | Rehydration can count fewer calls than were made. Three cases: (1) `_calls_today` goes up before the call, but no row is written if `analyze_crossing_frames` raises (the `except` at :976 writes no row); (2) a call still in flight at restart has no row yet; (3) a row still waiting in the spawned write task at shutdown is lost. The shortfall is at most the concurrency limit plus rows not yet flushed, which is a few cents. Bug class #53. Acceptable. |
| A3 | LOW | database.py:2015 | The only index on `memory_episodes` is `(node_id, episode_type, started_at)`, and the new count filters on `episode_type` + `ended_at`. The count therefore scans the whole table once per setup. If that scan ever takes longer than 30 s, twice in a row, the result is a full day with no calls plus a LOW page. That is bounded and fails safe. Measure the scan time on the live DB once. If it is slow, add an `(episode_type, ended_at)` index. |

Checks that held:
- **P3-D1.** At :966 the error text is threaded only on the `else` (error) branch. At :1101, `_record` adds the `error` key only when `outcome == OUTCOME_ERROR`, truncated to `ERROR_TEXT_MAX_CHARS`. A `None` stays `None`. No other row gains the key.
- **DAO SQL.** `json_extract(attrs_json,'$.outcome')` matches the writer's attrs key (`"outcome"` at :1079). The writer stores `ended_at = dt_util.utcnow().isoformat()` (:1135), giving `...T06:00:00.123456+00:00` (or with no fraction when microseconds are 0). Each bound is `as_utc(start_of_local_day).isoformat()`, giving `...T06:00:00+00:00`. In ASCII `+` (0x2B) sorts before `.` (0x2E), so the lexical `>=` and `<` comparisons match the time order at the second boundary on both ends. A row exactly at midnight falls in the new day. Building the bounds with `start_of_local_day(day+1)` handles DST.
- **Read path only.** The DAO uses `_db_read()` and never touches the write queue.
- **Success vs error.** `(count, True)` vs `(0, False)`. An empty outcome list returns `(0, True)`. No database returns `(0, False)` (:998).
- **`CALL_OUTCOMES` matches the call path.** Rows after a made call: ok, blank, unparseable and refused (via `parse_vision_response`), timeout, and error (:957-972). Rows from the gate or pre-call steps (no_frigate_event, clustered, skipped_cap, skipped_busy, no_clip_url) are excluded, which is correct. When `reply is None` the code decrements the counter and writes no row, which is consistent.
- **Hold and rehydrate.** Setup sets the hold before the task starts. Each try is bounded by `wait_for(30 s)`, with one retry after 60 s. A `CancelledError` is re-raised. Two failures set the state to failed, increment the failure counter and send a LOW `fire_stuck_signal`. `_roll_day` clears the hold at midnight. A result for an old day is discarded by the `self._day == day` check after a second `_roll_day`, and `max()` stops it lowering a live count.
- **P3-D8 rule.** All three conditions are checked (:1306): the state is `on`, the stream view is `None`, and `input_room_stuck_excluded` is True. The client set `{p22_continuous, chatter, stuck_dutycycle}` matches the real promoters at coordinator.py:3095, :3781 and :3849. It never includes `CAMERA_STREAM_EXCLUSION_CLIENT` (:2627). The kill switch is in const. Last-good is kept because `classify_held` still sees the reading and only the result sets are subtracted. If the getter raises, the input still holds. Removing the ignored inputs from `dead_held` has no effect, because an ignored input is live (view is None), so it can never be in `dead_held`.
- **The builder's three deviations.**
  - Bound rendering (aware isoformat vs the writer): verified above.
  - The unreachable call-time gate: see A1.
  - DB not ready: crossing vision is set up after `hass.data[DOMAIN]["database"]` in the same entry (__init__.py:2734, then :3601). If the DB failed to initialise, both tries fail at once, giving a LOW page and no calls that day. That fails safe.

## B. Integration and lifecycle

| # | Sev | Site | Finding |
|---|---|---|---|
| none | | | |

Checks that held:
- **Ordering.** The bus listener is subscribed (:450) before the hold and the task. A crossing that arrives before rehydration finishes is recorded as `skipped_cap`, as intended. The task is created with `async_create_background_task`, added to `_tasks`, and discarded when done.
- **Teardown.** Teardown cancels the rehydration task explicitly (:477). `_rehydrate_cap` also checks `_torn_down` before and after each await, so a late result never touches a torn-down instance. The existing bounded gather covers `_tasks`.
- **Reload and restart.** A new instance runs a new rehydration. The hold cannot outlast the day: `_roll_day` runs on every crossing (:668), in `_run` (:914) and in diagnostics (:1690). Before any calls-counted read, the hold is either cleared or still for the same day. With the DB down all day, the result is no calls until midnight plus one LOW page per restart. That is bounded, not stuck forever. A restart after midnight starts a new hold, which is correct.
- **The `_ask` sweep.** `input_room_stuck_excluded` uses the same `_ask` pattern as the existing `input_room_quarantined`. The layer-guard test passes, so the delta-0 claim holds. Cost: it runs only for Tier-1 inputs that read `on` with no stream view, once per anchor sample (60 s). Each call asks every room coordinator (about 40) for one `clients_for` dict lookup. That is cheap.
- **P3-D8 against house state.** The ledger reaches consumers only through `census_tick` → `PersonCensus._ledger_tick` → `deconflict_house` → the awareness fields (camera_census.py:6890-6955). Those fields are read by `census_view` for `view == "awareness"` and by the display sensors (sensor.py:4247-4273). `CROSSING_VISION_AWARENESS_VISION_LEADS = False` (const.py:6744), and `deconflict_house` keeps the trust view unchanged (census_deconflict.py:25). No house-state, AWAY or F-LEAD path reads the awareness fields. An earlier anchor reset can only change the display-only awareness view. The anchor-zero page now names the ignored inputs.
- **Recorder.** `crossing_vision_cap_rehydrate` was added to the unrecorded-attribute set of `ExteriorOpenTracksDiagnosticSensor` (sensor.py:4590).

## Bug class tally
#53 computed-but-not-consumed: 1 (A2, LOW). Index or performance: 1 (A3, LOW). Defence in depth: 1 (A1, LOW).
