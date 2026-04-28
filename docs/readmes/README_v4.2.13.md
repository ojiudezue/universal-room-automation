# v4.2.13 — Startup Catch-Up Delay + Bayesian Init Hardening

**Date:** 2026-04-28

## Summary

Fixes Bayesian predictor initialization failure caused by DB read contention from startup catch-up prune. Delays catch-up prune from 5 min to 30 min post-boot. Registers Bayesian predictor before DB load so button/sensors are available even on DB failure.

## Problem

1. **Bayesian predictor init failure:** The startup catch-up prune (v4.2.8) fired at 5 min, saturating the DB write queue. Bayesian `initialize()` does DB reads (`load_bayesian_beliefs`, `scan_data_quality`) which block on WAL checkpoint under write congestion. If `initialize()` throws, the predictor never registers → button unavailable, accuracy unknown.

2. **Fragile init-or-nothing pattern:** If `bayesian_predictor.initialize(database)` failed for any reason, all wiring (transition listener, periodic save, accuracy eval, guest listener) was skipped. The predictor wasn't registered, so all downstream sensors returned None/unknown permanently until next restart.

## Changes

### 1. Startup catch-up delay: 5 min → 30 min
- `async_call_later(hass, 300, ...)` → `async_call_later(hass, 1800, ...)`
- Both primary and deferred DB init paths
- Gives all coordinators, Bayesian predictor, and zone sensors time to complete DB reads before prune writes begin
- Nightly 2:30 AM maintenance remains the primary cleanup mechanism

### 2. Bayesian init hardening
- Register `hass.data[DOMAIN]["bayesian_predictor"] = bayesian_predictor` BEFORE `initialize()`
- Inner `try/except` catches DB load failures with warning log
- On failure: predictor starts with empty beliefs, learns from live transitions
- All downstream wiring (transition listener, periodic save, accuracy eval, guest listener) still executes
- Button becomes available, accuracy sensor starts recording at next bin boundary

## Verified Safe

All Bayesian methods handle empty beliefs gracefully:
- `predict_room()` → None for missing cells
- `save_beliefs()` → returns early if no rows or no DB
- `clear_and_reinitialize()` → returns early if no DB
- `get_accuracy_stats()` → returns `{brier_score: None, ...}` if no DB

## Review: Tier 1 (hotfix, 1 file)
- 0 CRITICAL, 0 HIGH, 1 MEDIUM (pre-existing async_call_later pattern), 6 LOW
- Full report: `docs/reviews/code-review/v4.2.13_startup_delay_bayesian_init.md`

## Files Modified (1)
- `__init__.py` — catch-up delay 300→1800, Bayesian init register-before-load
