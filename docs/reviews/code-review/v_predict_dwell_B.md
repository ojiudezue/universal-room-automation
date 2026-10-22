# Review B: PREDICT-MODEL-DWELL-MIGRATION-1 (migration correctness, consumers and signal chain, lifecycle)

Branch `feature/predict-dwell-migration` @ `e86707305`. Diff base: local develop `ca81bc8fc`, three-dot.
Read first, completely: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`, and the plan. No ledger claim is re-asserted. No presence-doc contradiction found: §1 and §9 match the code.

## Consumer enumeration (re-grepped, not taken from the plan)

| Re-sourced value | Consumers found | Same type/shape? |
|---|---|---|
| `*_bayesian_occupancy_forecast` state/attrs | No code reader. Not on any dashboard or the PWA (grep of `dashboard-v3/src` and the ura_v8 backups). | State is still a float %, but its meaning changes (intended). Attrs: `forecast_now/+1h/+4h` and `room` kept, others added. |
| `*_bayesian_occupancy_pattern` | No code reader. Not on any dashboard. | State is still a str (`"weekday 14:00"` instead of a time bin), intended. |
| `*_likely_next_room` state | ura_v8 markdown (state only); `dashboard-v3 Presence.tsx:76` (state). | str, unchanged. Attr `current_room` is now the real room on the PatternLearner path (was `""`). Nothing reads it. |
| `next_room_predictions` cache | Read only by `transitions._score_prediction`. | Adds the `current_room` key. |
| `get_accuracy_stats` | `sensor.py:15467`, `optimization.py:3890`. | Keys added only. The empty-row returns lack the new keys; every reader uses `.get`. |
| `prediction_results` readers | `sensor.py:15589/15600/15837/15847`, `regime_detector.py:391/408`, `optimization.py:3740`, `database.py:7964`. | All filter by `prediction_type`, so `dwell_share` is invisible to all of them. |
| Energy forecast (switch off or on) | `energy_forecast.py` is not in the diff and does not read either sensor or `get_accuracy_stats`. | I3 holds. |
| Regime detector D7 | Unchanged and already inert (pre-existing JSON compare). Retention 45 ≥ its 37-day read. | n/a |

## Findings

| # | SEV | file:line | Finding / scenario | Class |
|---|---|---|---|---|
| B-L1 | LOW | `room_dwell_model.py:464-496` | `_last_hour_fraction` is replaced only when a scoring pass runs. If `frozen_prev` is None (the previous freeze yielded nothing, or was skipped because `trained > hour`, which happens on a half-hour-offset TZ at the local-midnight tick) or `database` is None, the old dict stays. D2 then blends a fraction 2+ hours old while labelling it `last_hour_fraction`. Display only. Fix: clear it (or stamp it with `_last_scored_utc_hour` and ignore it when older than H−1) on every tick that does not score. | Stale data source (#7) |
| B-L2 | LOW | `transitions.py:466-478` → `:503-507` | The scorer reads the cache after `await database.log_transition(...)`. If a 30 s poll of `PersonLikelyNextRoomSensor` lands during that write, the cache is rewritten with `current_room = to_room`, and a transition that should be scored is counted as `skipped_room_mismatch`. It never writes a wrong row, but it inflates `skip_ratio`, which is a gating Live criterion (H2), and more so under write-queue backlog. Fix: capture the cache entry in `_on_location_change` before the first await and pass it through. | Capture-before-await |
| B-L3 | LOW | `optimization.py:3941-3946` | The skill rule (`skill_pct <= 0`) is a fixed threshold with no hysteresis. After deploy the pooled 7-day skill crosses 0 once, going up, as old Bayesian rows age out. Per-row noise near the crossing can toggle the finding over a few evaluations. It is advisory only, and the drift per hour (~20 rows) outweighs per-row noise, so the flicker is expected to be short. Accepted under the plan's Q5 choice. | No-flap |
| B-L4 | LOW | `sensor.py:3549`, `transitions.py:575` | With the kill switch `NEXT_ROOM_CURRENT_ROOM_PRIMARY=False`, the cache dict gains `"current_room": None` and the `scored` counter still increments. Behaviour is identical: None takes the legacy branch and every row is byte-identical. The cache dict itself is not, but its only reader is the scorer. Cosmetic. | — |
| B-L5 | LOW | `room_dwell_model.py:442,497` | `_stopped` is checked only at tick entry, so a tick in flight during `async_stop` (reload/unload) still runs `save_prediction_results_batch`. This cannot duplicate rows: the new runner starts with an empty `_frozen`, so it never scores that hour. If the DB is already closed, the write's own except catches it. Harmless; optionally re-check `_stopped` before the write. | Lifecycle |
| B-I1 | INFO | `pattern_learning.py:304-321`, `sensor.py:3386` | `predict_next_room` used to run only as a rare fallback. It now runs on every poll for every person, so the hourly `analyze_patterns` (30 days of transitions, a Python loop on the event loop) actually runs: about 4 per hour, ~15k rows for Oji. That is milliseconds. Note only. | — |

## Cleared (holds because …)

- **D2 kill switch is byte-identical.** The new code is a prefix block under `if FORECAST_DWELL_SOURCE_ENABLED`, and the old code below it is untouched (`sensor.py:15123-15190`, `15309-15400`).
- **D4 precedence.** `away_typical` still wins for a geofence-away person: the primary path excludes `away`, so `_cached_prediction` is None at `:3435`. The Bayesian path is skipped only when the primary path produced a prediction (`:3403-3406`).
- **I4 compare is exact.** The cache's `current_room` is person_coordinator `location`. The transition's `from_room` is the `previous_location` of `ura_person_location_change` = `old_location` from the same `data[...]["location"]` (`person_coordinator.py:534-548`). They are the same strings, so no normaliser is needed.
- **D3 same-hour guard.** `_last_scored_utc_hour` is set and `frozen_prev` is popped before the first await (`room_dwell_model.py:461-465`). A concurrent second invocation finds nothing to score, and its freeze is idempotent (`hour in self._frozen`). Clock-back double fire: covered.
- **Restart and reload.** `async_setup_room_dwell_model` stops any existing runner before creating one (`:605-610`), `entry.async_on_unload(async_stop)` is at `__init__.py:4853`, and the tick unsub is cancelled in `async_stop` (`:527-535`). No double registration: `async_start` runs once per runner, and the tick is registered only inside it, after the `OCC_ANOMALY_DWELL_ENABLED` gate. After a restart, `_frozen` is empty, so no row can come from a post-restart model (I1).
- **I1 out-of-sample.** `trained_until_utc` is the start of the refresh's local day in UTC, and the freeze requires `trained <= hour`. A refresh during H cannot alter a frozen value.
- **DST.** Hour keys are UTC, so fall-back gives two keys and spring-forward has no gap. `forecast()` does the arithmetic in UTC and converts back to local (`:269-271`).
- **Event loop vs executor.** The tick does an O(rooms) dict walk on the loop, a DB read via `_db_read`, and one `executemany` via `_db()`. The model build stays in the executor.
- **Write volume.** One batch per tick; the format is aware ISO, matching the prune cutoff. The prune without the type filter uses `idx_prediction_results_ts` (`database.py:1702`); the first night is about 150 batches.
- **`dwell_share` is hidden from every existing reader** (every query filters by type).

## Verdict: **SHIP**

There are no CRITICAL, HIGH or MEDIUM findings. B-L1 and B-L2 are recommended in-cycle LOW fixes (each 5 to 15 LoC). B-L2 matters most, because it biases the H2 skip-ratio Live gate.
