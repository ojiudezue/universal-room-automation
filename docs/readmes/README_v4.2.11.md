# v4.2.11 — Cache Slow DB Read Sensors + Rework Memory Sensor

**Date:** 2026-04-27

## Summary

Caches zone occupant sensors (5 min) and Bayesian accuracy sensor (30 min) that were doing DB reads every 30 seconds. Reworks memory sensor from shallow `sys.getsizeof` to counts-based measurement of known-growable structures.

## Problem

Zone last occupant sensors and Bayesian accuracy sensor had no caching — HA polls `async_update()` every 30 seconds by default. Each query opened a transient DB read connection. Under write queue congestion, reads block on WAL checkpoint. 202 occurrences of >10s sensor updates observed in logs.

## Changes

### Sensor DB read caching
- `ZoneLastOccupantSensor.async_update()`: 5-minute cache via `time.monotonic()`
- `ZoneLastOccupantTimeSensor.async_update()`: 5-minute cache
- `BayesianPredictionAccuracySensor.async_update()`: 30-minute cache

### Memory sensor rework
- `URAMemoryUsageSensor`: Changed from `sys.getsizeof` (shallow, misleading) to `_count_items()` counting known-growable structures (dedup cache, belief cells, DB queue, hass_data keys)
- Unit changed from KB to items
- Added process RSS in attributes for correlation
- `URAMemoryDeltaSensor`: Tracks item count delta between measurements

## Review: Part of v4.2.12 combined review cycle
- Zone sensor exception handlers reset state to "Unknown" on error — caught and fixed in v4.2.12
- Memory sensor property side-effects (native_value mutated state) — caught and fixed in v4.2.12

## Files Modified (2)
- `sensor.py` — Bayesian accuracy cache, memory sensor rework
- `aggregation.py` — Zone sensor caching
