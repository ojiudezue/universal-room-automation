# v4.5.16 — Failsafe Occupancy-Freshness Gate + Bayesian Eval Diagnostic

**Date:** 2026-05-12 CDT
**Type:** Tier 1 combined cycle (two unrelated fixes shipping together)
**Predecessor:** v4.5.15 (live-validated)

## Summary

Two surgical fixes, single deploy. **Part A** ships the headline bug fix (failsafe firing nightly for every occupied bedroom). **Part B** ships a Phase 1 diagnostic for the Bayesian prediction-accuracy pipeline (0 rows in 7d). Files touched are unrelated (`coordinator.py` vs `__init__.py`), code paths are independent — zero coupling between the two.

16 new tests. Tier 1 staff-engineer review APPROVED-WITH-FIXES (4 LOW findings → 2 cheap fixes applied pre-deploy, 2 deferred to Phase 2 BACKLOG).

## Part A: Failsafe occupancy-freshness gate

### The bug

URA's RESILIENCE-001 failsafe (`coordinator.py:1402`) was anchored to `_became_occupied_time` and ignored signal freshness. A bedroom continuously occupied for 4 hours (person sleeping, mmWave correctly detecting them via `sensor_presence`) hit the duration ceiling and got force-marked vacant for 30-60 seconds.

**Live evidence (Ziri Bedroom, 2026-05-11 CDT):**
- 21:19 CDT — kid in bed → `_became_occupied_time = 21:19`
- 22:55 CDT — motion last fired (PIR doesn't trigger on micro-movements during sleep)
- 21:19 → 01:19 CDT — `sensor_presence` (mmWave) continuously ON throughout
- **01:19:42 CDT — failsafe fired** at the 4-hour mark, marked vacant
- 01:20 CDT — next cycle re-occupied (sensor_presence still on)

Net: 34-second false-vacant transition per bedroom per night. Any automation gated on vacancy fires once nightly then reverts. Sleep protection toggle (`CONF_SLEEP_PROTECTION_ENABLED`) does NOT gate the failsafe — it only throttles motion-driven automation.

### The fix

`_last_motion_time` is misleadingly named — it's actually the **universal Tier 1 freshness timestamp** at `coordinator.py:1353` where `any_sensor_active` includes motion + mmWave + occupancy sensors. So when mmWave fires every cycle, `_last_motion_time` stays fresh.

The failsafe now consults this timestamp before firing:

```python
if duration > failsafe_seconds:
    signal_stale = True
    signal_age = None
    if self._last_motion_time:
        signal_age = (now - self._last_motion_time).total_seconds()
        # Clock-skew defense: negative age (future timestamp) → treat as stale
        if 0 <= signal_age < 2 * self._occupancy_timeout:
            signal_stale = False
    if signal_stale:
        # fire failsafe (stuck sensor / forgotten light)
        ...
    else:
        # debug log + skip (legitimate continuous occupancy)
        ...
```

**Stale threshold = `2 * self._occupancy_timeout`:**
- Bedroom (timeout 900s): 30-min stale threshold — covers sleep without firing
- Closet (timeout 120s): 4-min threshold — natural idle pauses OK, stuck sensor caught
- Bathroom (timeout 300s): 10-min threshold — shower duration OK, fan-driven stuck caught

### What's deliberately NOT changed

Initial sketch proposed cleaning up the camera + BLE override branches (`coordinator.py:1442, 1490`) to always-set `_last_motion_time = now` instead of only-when-None. **Risk audit rejected this** — three downstream consequences:

1. **Breaks Sparse BLE Tier 2 hardening** (`coordinator.py:1517`). The Tier 2 gate requires motion corroboration; BLE override setting `_last_motion_time` itself self-confirms.
2. **`STATE_TIME_SINCE_MOTION` sensor lies** (`coordinator.py:1391-1392`). Reports 0 seconds since motion when only camera/BLE fired.
3. **Hidden behavioral drift** across all `_last_motion_time` readers expecting "PIR/mmWave last fired."

Camera-only / BLE-only rooms remain on the old failsafe shape. Trade-off: rare config, and the wrong-failsafe re-occupies in <1 min on the next cycle. CUT entirely (was tentatively filed as v4.5.19; no longer in BACKLOG).

## Part B: Bayesian prediction-scoring diagnostic (Phase 1)

### The bug

`sensor.ura_coordinator_manager_bayesian_prediction_accuracy` reports `total_predictions_7d: 0` despite `_bayesian_accuracy_eval` being registered to fire at hours 00/06/09/12/17/21:05 local. Root cause hidden by a silent `_LOGGER.debug` swallow at `__init__.py:1214-1217`.

### The Phase 1 fix

Swap `debug` → `warning + exc_info=True` (traceback at WARNING level), plus add distinct log lines for the success path, empty-batch case, and DB-handle-None case:

```python
if batch_rows:
    if database is not None:
        await database.save_prediction_results_batch(batch_rows)
        _LOGGER.info("Bayesian accuracy eval: wrote %d prediction rows to DB", len(batch_rows))
    else:
        _LOGGER.warning("...db handle is None — rows DROPPED")
else:
    _LOGGER.warning("...produced 0 rows — likely room_id mismatch or no predictions")
except Exception as exc:
    _LOGGER.warning("Bayesian accuracy eval failed: %s (type=%s)", exc, type(exc).__name__, exc_info=True)
```

After one decision bin (~6 hours) of logs, we'll know which failure mode is firing. **Phase 2 cycle ships later today** with the actual fix.

## Tier 1 Review

Single staff-engineer review. Mental execution covered 6 failsafe scenarios + concurrency + recovery path. 0 CRITICAL/HIGH/MEDIUM. 4 LOW (2 fixed pre-deploy, 2 filed to BACKLOG for Phase 2).

| Severity | Found | Fixed pre-deploy | Deferred |
|---|---|---|---|
| CRITICAL | 0 | — | — |
| HIGH | 0 | — | — |
| MEDIUM | 2 | 2 | 0 |
| LOW | 2 | 0 | 2 |

**Fixed pre-deploy:**
- Clock-skew clamp on `signal_age` — negative timestamp falls through to fire (recoverable) instead of permanent silence
- `exc_info=True` on the exception warning — traceback for free at the same noise level

**Deferred to Phase 2 BACKLOG:**
- Demote empty-batch + success Bayesian logs from WARNING/INFO once Phase 1 confirms failure mode
- Min/max floor on stale-threshold for pathological `_occupancy_timeout` values
- Parallel clock-skew clamp at `coordinator.py:1517` (Sparse BLE Tier 2)

## Test count

- v4.5.15: 401 tests
- **v4.5.16: 417** (+16 from `test_v4516_failsafe_freshness.py`)

Breakdown:
- 8 decision-helper tests for the failsafe gate (under duration / over duration + fresh / over + stale / no timestamp / boundary at duration / boundary at stale threshold / closet fresh / closet stale)
- 4 AST + source-grep regression guards (`_last_motion_time` referenced, `2 * self._occupancy_timeout` threshold, 'signal stale' log phrase, camera/BLE branches untouched)
- 4 source-grep tests for Part B (no debug swallow, success log includes row count, empty-batch logged distinctly, exception logs include type)

## Live validation plan (post-restart)

### Part A — failsafe gate

1. **No immediate regressions.** No rooms transition vacant on restart from this change.
2. **Wait for the natural overnight test.** With 4 family bedrooms occupied 4+ hours, the old code fired failsafe nightly. v4.5.16 should fire ZERO bedroom failsafes if mmWave is detecting people. Check overnight logs (~12 hrs after deploy): `ha_get_logs source=system search="failsafe" hours_back=24` should show only stuck-sensor or genuinely-vacant patterns, not occupied bedrooms.
3. **Debug log spam check.** With debug logging off (HA default), no noise. If debug enabled, will see ~120 "skipping failsafe" entries per bedroom per night — expected.

### Part B — Bayesian eval diagnostic

1. **Wait 6 hours (one decision bin).** Next eval fires at the upcoming 00/06/09/12/17/21:05 boundary in local time.
2. **Capture the log.** `ha_get_logs source=system search="Bayesian accuracy eval"` after the next bin boundary. Expected outcomes:
   - `"wrote N prediction rows to DB"` → eval works, Bayesian DataQuality query has a mismatch (Phase 2 fixes the query)
   - `"produced 0 rows"` → eval fires but no rooms produce predictions (Phase 2 likely a room_id mismatch in `predict_room_occupancy`)
   - `"failed: <error>"` with traceback → exception in the predictor; Phase 2 fixes the specific exception
   - No log at all → eval never fires; need to check `async_track_time_change` wiring
3. **Phase 2 ships later today** based on which log fires.

### Carry-over fixes

- v4.5.13: kwh_rate sensors live, anomaly gate working
- v4.5.13.1: 3 canonical AC zones (kwh_rate_back_hallway → "Entertainment + Master Suite" merged)
- v4.5.13.1.1: per-zone kWh threshold sliders at 0.8
- v4.5.14: anomaly sensors show `metrics_active_ratio` and `metrics_silent`
- v4.5.15: closet/bathroom failsafe at 60 min (and now respects signal freshness too)

### Envoy race watch

6th restart this session. Running tally: 1/5 fired. Statistical update only.

## Deploy notes

- 2 files touched: `coordinator.py`, `__init__.py`
- HACS download required after deploy.sh
- HA restart required
- No entity changes, no orphans, no DB schema, no config keys

## Documents

- BACKLOG: 4 Phase-2 carry-overs filed; v4.5.13.2 envoy race still parked; v4.5.19 (camera-only failsafe) cut entirely
- Predecessors: README_v4.5.{12..15}.md

## Next

- **v4.5.17 (later today):** Bayesian prediction-scoring Phase 2 fix based on Phase 1 log evidence
- **v4.5.18:** Widen scan-data-quality dedup key (originally v4.5.16 in BACKLOG, renumbered)
- **v4.6.0:** Routine Awareness Phase 1
