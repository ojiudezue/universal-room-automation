# URA v3.6.26 — Music Following Anomaly Detector Fix

**Date:** 2026-03-03
**Type:** Bug Fix — Diagnostics Integration
**Scope:** domain_coordinators/music_following.py

## Summary

Fixes the Music Following Coordinator's anomaly detection and diagnostics framework integration. The v3.6.25 coordinator declared anomaly hooks but never instantiated the `AnomalyDetector` or wired it to transfer outcomes.

## Issues Fixed

### 1. AnomalyDetector Never Created
The coordinator checked `if self.anomaly_detector is not None` but never instantiated one. Safety, security, and presence coordinators all self-create their detector in `async_setup()`. Now creates `AnomalyDetector(hass, "music_following", MUSIC_FOLLOWING_METRICS)` and loads baselines from the database.

### 2. Non-Existent `register_metric()` API
The code called `self.anomaly_detector.register_metric()` which doesn't exist on `AnomalyDetector`. The class takes metric names in its constructor. Fixed by defining `MUSIC_FOLLOWING_METRICS = ["transfer_success_rate", "cooldown_frequency"]` and passing to the constructor.

### 3. No Observations Recorded
Even with a detector, nothing fed data to it. The standalone `MusicFollowing` class has `add_diagnostic_listener()` that fires on every `_record_stat()` call. Now registers `_on_transfer_outcome()` as a listener that computes rates from running stats and calls `record_observation()`.

### 4. Wrong Method Name in Teardown
`async_teardown()` called `async_save_baselines()` (doesn't exist) instead of `save_baselines()`.

## Impact

- CoordinatorManager `get_system_anomaly_status()` now reports music_following as `"learning"` → `"active"` instead of `"not_configured"`
- Transfer success rate and cooldown frequency now tracked with z-score anomaly detection
- Baselines persist to database across restarts

## Tests
645 tests pass (no new tests — existing coordinator tests cover the fix)
