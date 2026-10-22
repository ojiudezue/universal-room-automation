# Review A — data integrity + DB architecture (PREDICT-MODEL-DWELL-MIGRATION-1)

Branch `feature/predict-dwell-migration` @ e86707305, base develop ca81bc8fc (three-dot, merge-base verified).
Read: PRESENCE state-of-play diff lines, plan §6/§8/§13, QUALITY_CONTEXT classes. No pytest run (framing C owns it).

## Findings

| SEV | Site | Finding | Bug class |
|---|---|---|---|
| LOW | `database.py:8158-8167` via `room_dwell_model.py:470` | Hourly D3 tick reads `environmental_data` with `WHERE timestamp >= ? AND timestamp < ?` only. The only index is `(room_id, timestamp)` (`database.py:862`), so each hourly read likely does a full table scan (docstring cites ~1.5 s for the nightly 56-day read). It runs on the read connection (WAL, off the event loop, not the write queue), so no writer starvation; cost is 24 scans/day instead of 1. Accept, or add `idx_environmental_data_ts` later if live timing shows > ~1 s. | Perf (not a listed class) |
| LOW (doc) | `database.py:7994-7998` | Prune docstring says "every writer stores isoformat() UTC". True for all three writers (`__init__.py:3233`, cache `sensor.py:3547` -> `transitions.py:573`, `room_dwell_model.py:487`). Pre-existing readers (`sensor.py` accuracy, `optimization.py:3723`) still build space-separated cutoffs; plan already records this as pre-existing. No change needed. | — |

No CRITICAL / HIGH / MEDIUM.

## Cleared (holds because)

- **Existing types unchanged:** `save_prediction_result` (`database.py:7452`), `save_next_room_prediction_result` (`:7495`) and the bayesian batch (`__init__.py:3235-3271`) are untouched; the only DAO change is a docstring on `save_prediction_results_batch`. next_room row shape unchanged (`transitions.py:561-575`); D4 only reduces volume via the from-room gate, and the cache sets `current_room=None` for Bayesian/away paths (`sensor.py:3368`, `:3549`), so those keep old scoring.
- **dwell_share shape:** 7-tuple matches the batch DAO column order (`room_dwell_model.py:486-490`); stamp `prev.isoformat()` of an aware UTC hour = `YYYY-MM-DDTHH:00:00+00:00`, same family as the other writers and the prune cutoff; `person_id` NULL; `confidence` = cell count, documented at `database.py:7924-7927`.
- **Readers isolated:** every reader filters `prediction_type` — `get_prediction_results` default `bayesian_occupancy` (`database.py:7966`), sensor accuracy `next_room` (`sensor.py:15590`, `:15838`), regime detector (`regime_detector.py:391-412`), optimizer (`optimization.py:3741`). dwell_share rows cannot leak into existing analytics. `get_bayesian_accuracy` return dict is additive only (`bayesian_predictor.py:957-965`); sensor.py diff removes no keys.
- **Write volume / queue:** one `executemany` + commit per hour through `_db()` (47 rows); I2 guard `_last_scored_utc_hour` set before the first await (`room_dwell_model.py:461-462`); frozen entry popped before the await. Batched, never per-row.
- **D5 prune:** filter removed (`database.py:8011-8017`); still 1,000-row rowid batches, one write-queue item per batch, `asyncio.sleep(0.1)` between (other writers interleave), subquery uses `idx_prediction_results_ts` (`database.py:1702`). ~150k rows = ~150 batches, under the 500-batch cap. Runs from the nightly op chain, not on the event loop thread. Not the 2026-06-09 shape (that was unbounded per-cycle writes at boot). Retention 45 d >= regime detector's 37-day window (`const.py:2225-2227`).
- **Prune lexical compare:** cutoff `...T...+00:00`; any legacy space-separated row only differs on the cutoff date and only by keeping it one extra night. Safe.

## Verdict: **SHIP**

Must-fix: none. Optional: record live hourly-tick read duration in the README validation table.
