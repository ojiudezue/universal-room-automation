# v4.5.17 — Bayesian Eval dt_util Import Fix (Phase 2)

**Date:** 2026-05-12 CDT
**Type:** Tier 1 micro-fix — one-line addition driven by Phase 1 log evidence

## Summary

v4.5.16 Phase 1 escalated a silent `_LOGGER.debug` swallow in the Bayesian accuracy eval closure to a WARNING with traceback. The 12:05 CDT bin fired today and produced **exact** evidence of the root cause:

```
WARNING: Bayesian accuracy eval failed: name 'dt_util' is not defined (type=NameError)
File "__init__.py", line 1171, in _bayesian_accuracy_eval
  now = dt_util.now()
NameError: name 'dt_util' is not defined
```

The closure body uses `dt_util.now()` and `dt_util.utcnow()` but never imports `dt_util`. Module-level imports don't include it either. Same pattern works elsewhere in the file at line 2375: `from homeassistant.util import dt as dt_util`.

**This bug has been silent since v4.0.0-B2 was deployed (~6 months ago).** Every Bayesian accuracy eval — every 6 hours, every bin boundary, for ~6 months — has died with `NameError`. The `prediction_results` table has zero rows from this code path. The accuracy sensor has reported `unknown` the entire feature history.

5 new tests. Single staff-engineer review APPROVED, no findings.

## The fix

Single addition at `__init__.py` inside the existing try-block, before the first `dt_util` usage:

```python
async def _bayesian_accuracy_eval(_now):
    """Record prediction accuracy at bin boundaries."""
    try:
        # v4.5.17: dt_util was never imported in this closure's scope,
        # causing every Bayesian eval since the feature was added
        # (v4.0.0-B2) to silently die with NameError. The bare
        # _LOGGER.debug swallow at the bottom of this try block hid
        # the failure for months until v4.5.16 escalated it to
        # WARNING. Phase 1 surfaced the bug; this is Phase 2's
        # one-line fix. Same pattern as __init__.py:2375.
        from homeassistant.util import dt as dt_util
        bp = hass.data.get(DOMAIN, {}).get("bayesian_predictor")
        ...
```

Placement choices:

- **Inside the try-block** (not module-level): consistent with the function-local pattern used at line 2375. A future `homeassistant.util.dt` reorg would still surface via the same v4.5.16 WARNING + traceback path. Defensively correct.
- **Before the first `dt_util.` usage**: obviously required.
- **Idempotent**: Python caches modules in `sys.modules`; the per-fire cost (6×/day) is a dict lookup. Zero perf concern.

## What's NOT changed

- No other code paths touched. v4.5.16's Phase 1 diagnostic logging (warning + exc_info + distinct empty-batch + db-none branches) **remains in place** — these become the long-term safety net that catches the next silent failure shape if it appears.
- `record_prediction()` stub at `bayesian_predictor.py:824` (the SEPARATE per-person `likely_next_room` accuracy pipeline) is still empty — that's a v4.6.x feature cycle.

## Tier 1 Review

Single staff-engineer review, single-line scope. Mental execution: import statement binds `dt_util` in the function's local namespace; subsequent `dt_util.now()` and `dt_util.utcnow()` resolve. NameError gone. No new state. No new failure modes. v4.5.16 diagnostic intact.

**Verdict: APPROVED.** Zero findings.

## Test count

- v4.5.16: 417 tests
- **v4.5.17: 422** (+5 from `test_v4517_bayesian_eval_dt_util.py`)

Tests pin:
1. The import statement is present in the closure
2. Both `dt_util.now()` and `dt_util.utcnow()` references remain
3. The import is INSIDE the try-block (defensive — preserves Phase 1 WARNING for future HA util changes)
4. The closure remains a valid `AsyncFunctionDef` via AST
5. The v4.5.16 Phase 1 WARNING + `exc_info=True` diagnostic stays in place

## Live validation plan

### Immediate (post-restart)

1. No URA ERRORs at startup
2. No immediate Bayesian eval log spam (eval doesn't fire on import; waits for next bin)

### Next bin (17:05 CDT)

The next eval bin is **17:05 CDT** — ~4.5 hours after deploy. After it fires, log evidence should be:

- **Expected (happy path):** `INFO: Bayesian accuracy eval: wrote N prediction rows to DB`
- **Possible secondary failure (room_id mismatch):** `WARNING: produced 0 rows — likely room_id mismatch`
- **Any other WARNING:** Phase 3 micro-cycle scopes the next fix

### Days 1-7

`sensor.ura_coordinator_manager_bayesian_prediction_accuracy` should:
- Transition from `unknown` → numeric state (e.g., `0.832` = 83.2% hit rate)
- `total_predictions_7d` populates 6/day per room → ~50-150 rows/day total
- `brier_score` + `hit_rate_pct` compute as the 7-day window fills

## Filed during this cycle

**BACKLOG: Debug-swallow audit (no slot).** Grep showed ~15 other `_LOGGER.debug` calls inside `except` blocks in `__init__.py`. Most are one-shot migration/prune paths (intentional silence appropriate). But periodic closures with debug-swallow are the known-bad shape — needs an audit. Filed for a future Tier 1 sweep.

## Carry-over evidence (v4.5.16 Part A)

Master Bedroom v4.5.16 Part A test still in flight as of v4.5.17 deploy:
- `became_occupied_time: 11:58 CDT` (~1h 20min ago)
- `failsafe_fired: false`
- mmWave driving — `_last_motion_time` fresh
- Will cross 4-hour mark at ~15:58 CDT. The first natural test of Part A is later this afternoon, with the overnight Ziri Bedroom test being the second.

## Deploy notes

- 1 file touched (`__init__.py`) — single addition
- HACS download required
- HA restart required
- No entity changes, no DB schema, no config keys

## Next

- **v4.5.18:** Widen `scan_data_quality` dedup key (was v4.5.16 in BACKLOG before this renumbering — now next minor)
- **v4.6.0:** Routine Awareness Phase 1
- Eventually: `likely_next_room` accuracy pipeline (v4.6.x feature cycle, the OTHER half of the prediction-scoring gap)
