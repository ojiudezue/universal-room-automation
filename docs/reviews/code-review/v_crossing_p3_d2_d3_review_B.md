# Crossing vision P3-D2 + P3-D3, review B (integration / lifecycle / restart / DB)

Commit 00cd94cef, base 056c69993 (verified parent). Verdict: **SHIP**, with one MEDIUM to fix in the plan or code before the next arc step.

| # | Sev | Site | Finding |
|---|---|---|---|
| B1 | MEDIUM | crossing_vision.py:962-395 (cap and busy gates), const.py `CROSSING_VISION_WATCH_AMBIGUOUS=True` | The plan's claim that ambiguous watching cannot displace resolved crossings is false. Ambiguous requests count in `_pending_primaries()` and `_calls_today`, so they share MAX_CONCURRENT=2 and the daily cap. Repro: the 11-16 burst of 26 ambiguous crossings. Two ambiguous requests on the window route hold both slots for about 25 s wait plus 13 s call each, so an entry or exit crossing in that span is recorded `skipped_busy` and gets the camera term instead of a vision count. Every ambiguous call also spends daily cap. Class: shared-budget displacement. Fix: separate slot and cap budget for ambiguous calls, or correct the plan and accept it. |
| B2 | LOW | crossing_vision.py:1008 | Builder residual confirmed. An ambiguous request waiting on event_clip is overwritten in `_waiting_by_event` by a later entry or exit request on the same event. It then fires only at the 120 s EVENT_END_WAIT_S timer, holding a slot. It is delayed, not lost. It only happens on the fallback route. |
| B3 | LOW | crossing_vision.py:848-866 | A repeat cancelled at unload mid-call increments `_repeats_today` but writes no row. After a restart the repeat budget can read one low, which is harmless. The primary path has the same shape from before this change. |

Cleared:
- Teardown cancels repeat tasks, sets `_slot_event`, and cancels every request's window timer (:657-682). The window route never registers in `_waiting_by_event`.
- Repeat exclusivity holds: the flag is set synchronously after the wait loop. `_yield_to_repeat` is bounded by TIMEOUT_S.
- The cap rehydrate filter holds. `COALESCE(call_kind,'primary')` (database.py:11250) puts old rows on the primary cap, and repeats are rehydrated into their own budget. `_cap_hold` blocks repeats too (:221).
- Reader enumeration for G3: `SIGNAL_EGRESS_RECORD_AMENDED` has 2 readers (sensor.py:5146, :5303). Both act only on role `exit_backfilled`, so `vision_direction` reaches no actor. The new CrossingRecord fields have no reader outside transit_validator.
- DB volume: an amend is RAM plus dispatcher, not a DB write. Rows are one per crossing plus at most 15 repeats a day, so the 26-crossing burst adds about 26 rows.
- No-op path: watch-ambiguous False returns before any counter. Repeat rate 0 or max 0 spawns nothing. Cap 0 is `_enabled` False.

Tests: 350 passed across p3_d2_d3, p3_first, shadow and the layer guard. The daily cap is 93, so the 26-call burst used 28% of it.
