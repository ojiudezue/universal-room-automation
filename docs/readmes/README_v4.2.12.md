# v4.2.12 — Review Fixes + RSS Delta Sensor + Retrospective + Bug Classes

**Date:** 2026-04-28

## Summary

Fixes 9 review findings from v4.2.11: zone sensor exception handlers destroying preserved state, memory sensor property side-effects, Bayesian accuracy exception handler not updating cache timer. Changes memory delta sensor to RSS-based (MB). Adds DB query performance retrospective and 3 new bug classes to QUALITY_CONTEXT.

## Changes

### Review fixes (sensor.py, aggregation.py)
1. Zone `ZoneLastOccupantSensor` exception handler: no longer resets `_last_occupant = "Unknown"` on transient DB errors — preserves existing values
2. Zone `ZoneLastOccupantTimeSensor` exception handler: same preservation fix
3. Both zone sensors: `_last_query_time` updated on exception to prevent retry spam
4. Bayesian accuracy sensor: exception handler now updates `_last_query_time` to prevent 30s retry loop
5. `URAMemoryUsageSensor`: computation moved from `native_value`/`extra_state_attributes` properties to `async_update()` — properties now return cached values (HA reads properties multiple times per state write)
6. `URAMemoryDeltaSensor`: rewritten as RSS-based (MB) using `resource.getrusage` — computation in `async_update()`, property is side-effect free
7. Zone sensors: all instance attrs declared in `__init__` — removed `hasattr()` checks
8. `BayesianPredictionAccuracySensor`: switched to `_cm_device_info()` helper (consistency)

### New documentation
- `docs/reviews/retro_db_query_performance.md` — full retrospective on DB write queue crisis
- `docs/QUALITY_CONTEXT.md` — 3 new bug classes:
  - #25: Unbounded DB DELETE in Write Queue
  - #26: High-Frequency DB Read from Sensor Platform
  - #27: Orphaned Cleanup Method

## Review: Combined with v4.2.11 (Tier 2, 2x adversarial)
- Full report: inline in session context (session ran out before persisting to file)

## Files Modified (3 + docs)
- `sensor.py` — 8 review fixes
- `aggregation.py` — zone sensor exception handlers + init declarations
- `docs/QUALITY_CONTEXT.md` — 3 new bug classes
- `docs/reviews/retro_db_query_performance.md` — retrospective
