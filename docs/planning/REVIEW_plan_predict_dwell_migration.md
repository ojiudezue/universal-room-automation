# Plan review: PLANNING_predict_dwell_migration.md (PREDICT-MODEL-DWELL-MIGRATION-1)

Reviewer: ura-planner (Mode 2, single adversarial plan review, Tier 2-DB). Date 2026-10-21.
Presence state-of-play / sensor-fleet docs were not re-read in this pass (the plan reads, but does not classify, presence signals); no §10 ledger claim is re-asserted below.

**Verdict: FIX-PLAN-FIRST** (no CRITICAL; 2 HIGH, both plan-text fixes, about 30 minutes of work). Scope: FOCUSED.

## Verified (greps re-run, claims hold)

- Every `prediction_results` reader filters by `prediction_type`: `sensor.py:15415,15426,15608,15618`, `database.py:7959` (parameterised), `regime_detector.py:391,408`, `optimization.py:3739`. `dwell_share` is invisible to all of them. Holds.
- Prune filter `AND prediction_type = 'bayesian_occupancy'` at `database.py:8003`; literal `{"days": 30}` at `nightly_maintenance.py:39`; 1,000-row batches, 500-batch cap, 0.1 s sleep. `idx_prediction_results_ts` exists (`database.py:1702`), so the 150-batch first prune is indexed. Holds.
- `get_room_occupied_share_by_hour` (`database.py:8129`) returns `(room_id, utc_hour, occupied_sum, n)` and excludes NULLs, so the min-samples gate has its `n`. Holds.
- `training_window` ends at local midnight today (`room_dwell_model.py:270-278`). With freeze-at-start-of-H and nightly/initial refreshes only, I1's `trained_until_utc ≤ start(H)` is satisfiable and the plan's leak repro is real only in an unguarded build. Holds.
- Runner is single, created in the parent entry setup and stopped via `entry.async_on_unload` (`__init__.py:4850-4853`); unsubs are per-attribute (`room_dwell_model.py:296-355`). D3's extra unsub fits. Holds.
- `regime_detector` window is 30 + 7 days (`regime_detector.py:383`), so the 45-day retention keeps it whole. Holds.
- `_score_prediction(person_id, actual_room)` currently has no `from_room` (`transitions.py:478,482`); the plan correctly says it must be threaded from `_log_transition`. Holds.
- Write volume: 24 batched transactions/day at 47 rows each, via the existing `save_prediction_results_batch`. Fine against the 2026-06-09 write-flood lessons (that incident was per-cycle persists plus a boot backlog; this is one hourly `executemany`). No finding.

## HIGH

**H1. The plan says no Optimization threshold is tuned for the old next-room level. That is wrong, and the projected new level sits on the threshold.**
`OPTIMIZER_PREDICTION_ACCURACY_TOP1_FLOOR_PCT = 35.0` (`const.py:4272`) is applied to the next-room top-1 rate at `optimization.py:3914-3926` (7-day window, min 50 samples). P3 projects Oji's raw top-1 at about 34.8%. Before this cycle the finding fires every time. After it, the aggregate (or per-person, depending on how `next_room` is aggregated around `optimization.py:3693-3760`) will sit close to 35% and can flip in and out of the issue list from day to day. §5.4 defers this to "plan review to confirm"; it is now confirmed as a consumer-side behaviour change.
*Fix:* add the Optimization prediction-accuracy finding as a consumer row in §5.4 and §10 (E12). State how the rate is aggregated (read `optimization.py:3693-3760`) and the expected value after D4. Decide whether the floor stays at 35 (record why) or whether it is left alone and the flapping is accepted as display-only. Add a D4 Live criterion: the issue's presence or absence over the first 7 days, matched to the measured top-1.

**H2. The I4 from-room gate can silently drop most scored rows, and D0 cannot measure that.**
The gate compares `cache.current_room` (taken from `person_coordinator.data[p]["location"]`, the BLE location, `sensor.py:3460-3463`) with `transition.from_room` (the `TransitionDetector`'s own room). The plan assumes the two agree in name and timing. The D0 item-4 backtest computes the gate on `room_transitions` alone, where the prediction's room is by construction the transition's `from_room`, so it measures 100% agreement whatever happens live. Live sources of mismatch: BLE location updating before or after the transition row is written; the sensor refreshing between the location change and the transition log; naming differences (display name versus slug). If the mismatch rate is high, the accuracy sensors look better because the sample shrinks to the easy cases. The test then fails the plan's own "honest scoring" intent, and the D4 Live check (Jaya ≥ 40%) would pass for the wrong reason.
*Fix:* (a) make `next_room_skipped_room_mismatch` observable and not DEBUG-only (an attribute on the existing accuracy sensor, or a counter included in the Live query). (b) Add a D4 Live criterion: skipped / (skipped + scored) ≤ a stated bound (suggested 30%), with the bound named as a knob. (c) Add a discriminating check: if the skip ratio is above the bound, the top-1 gain is not accepted as evidence. (d) Either drop D0 item 4's claim that it measures the drop, or reword it to "upper bound on agreement".

## MEDIUM

**M1. The persistence alignment at runtime does not match the probe.** At runtime `last_hour_fraction` is H−1's fraction, available from minute 2 of H, and the sensor computes `+1h` at an arbitrary `now` within H. At 10:50 the `+1h` cell is 11:00 and the persistence input is 09:00–10:00, so the effective lag is about two hours. P1's "+1 h, last full hour's fraction" alignment is not stated. If the probe predicted hour H+1 from hour H, the shipped forecast is staler than what was measured, and the −40% gain is overstated. *Fix:* D0 states the alignment exactly as the runtime will have it (the forecast hour is the cell of `now + horizon`, persistence is the last completed hour at `now`, with `now` sampled uniformly within the hour) and the weight sweep is re-run on that alignment.

**M2. The `prediction_timestamp` string format is unspecified, and prune and readers compare strings.** The prune cutoff is `utcnow().isoformat()` (`+00:00` suffix); the dwell DAO uses naive-UTC strings (`database.py:8137-8140`). "Start of H, UTC ISO" is ambiguous. A naive string sorts and compares differently from an aware string at the same instant only in the suffix, but mixed formats in one column make the D3 Live `>= <restart hour>` query and future OC reads error-prone. *Fix:* pin the format to the one the `bayesian_occupancy` writer uses (`__init__.py:3203-3318`; read and cite it) and add it to the `test_row_shape` assertion.

**M3. DST and freeze keying.** `frozen[H]` is described by "local hour H". At fall-back the local 01:00 occurs twice. *Fix:* key `frozen` and `prediction_timestamp` by the UTC hour start. Look up the cell from the local time of that UTC start. Add `test_fall_back_hour_two_rows_distinct_utc` and `test_spring_forward_no_gap_error`.

**M4. The I2 restart test describes something that cannot happen.** After a real restart `frozen` is empty, so "two ticks in the same hour (restart re-registers)" never reaches the dedupe. The reachable double-write cases are (a) the time-change callback firing twice in one minute (clock adjustment) and (b) two runners existing during a reload overlap. *Fix:* reword the D3 I2 test as "the same tick callback invoked twice for the same H" and add a guard that records the last scored UTC hour. Test that `async_stop` cancels the tick before a new runner registers.

**M5. Blend behaviour after a restart is unspecified.** `last_hour_fraction` is in memory, so after a restart the blend reverts to the cell share alone until minute 2 of the second hour, and `forecast_+1h` jumps when it returns. *Fix:* state it in D2 (attribute `last_hour_fraction: null` → blend weight effectively 0), and add a test.

**M6. The forecast sensor's update cadence is unspecified.** The existing sensors poll on their own schedule. If they update less often than hourly, `forecast_now` and the D2 Live equality with the anomaly sensor's `expected_share` can disagree across an hour boundary. *Fix:* state the cadence (cite `sensor.py`'s `should_poll`/scan interval for these classes), and make the Live check "within the same cell".

## LOW

- **L1.** `confidence = n` (a count) in a column the other types fill with 0–1 probabilities. Every reader filters by type, so nothing breaks today, but OC slice-1 readers will be surprised. Either store `n` in the JSON-free `confidence` with a docstring note at the DAO, or put `cell_days` there. Record the choice in §5.3.
- **L2.** The D0 weight sweep picks w on the same 14 test days it reports (selection on test). With 5 candidates the optimism is small, but report the chosen-w error on a held-out week, or say it is in-sample.
- **L3.** §6 `DWELL_SHARE_TICK_MINUTE` "validated at import" means an assert in `const.py`. Say whether a bad value raises at import (breaks setup) or clamps. Prefer clamp plus a warning.
- **L4.** D5 Live "no write-queue backlog warning" should name the log string to grep (the `_write_queue` saturation message), so it is checkable.
- **L5.** The pattern sensor's `top_cells` attribute: five cells, each with a share, is fine. Confirm it stays under the recorder attribute-size limit (it does at five; state the bound as a constant, not an inline literal, per the knob ladder).

## Knob ladder

Every behavioural number in §6 has a name and a rung. Missing: the top-cells count (L5) and the H2 skip-ratio bound. The prune retention move from literal to constant is correct.

## Institutional context

Complete for code and plans. The prior-art scan is real (re-run greps match). One gap: §1.1 does not list the Optimization accuracy constants (`const.py:4272-4285`) as a consumer surface. That gap is H1.

## Non-goals

These are explicit and adequate. After the H1 fix, add one: "No change to the `OPTIMIZER_PREDICTION_ACCURACY_*` thresholds", unless the fix chooses to change one.

## Required before build

H1 and H2 plan edits; M1 (re-run the D0 sweep on the runtime alignment); M2–M5 one-line spec additions. LOWs at the planner's discretion.
