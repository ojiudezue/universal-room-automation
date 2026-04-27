# v4.2.8 — DB Prune Batching + Nightly Maintenance + Census Write Throttle

**Date:** 2026-04-27

## Summary

Fixes DB write queue saturation caused by unbounded `prune_prediction_results` DELETE holding the write queue for >120 seconds. All 8 prune/cleanup methods batched with LIMIT 1000. Prediction prune moved from every-30-min to nightly 2:30 AM. 5 orphaned cleanup methods now scheduled nightly. Census DB writes throttled 4x. Startup catch-up prune clears accumulated backlog.

## Problem

`prune_prediction_results()` ran every 30 minutes via Bayesian periodic save. After weeks of predictions (~43K+ rows), the unbounded DELETE held the write queue's single connection for >120s. Queue peaked at 94 items, all timed out at 35s. Census writes every 30s compounded the problem.

## Changes

### Batched prune (database.py)
- All 8 prune/cleanup methods: `DELETE ... LIMIT 1000` in loop with `asyncio.sleep(0.1)` between batches
- Max 500 batches cap prevents infinite loops
- Each batch acquires/releases write queue independently

### Nightly maintenance (__init__.py)
- 2:30 AM: predictions (30d), census (90d), energy_history (180d), external_conditions (90d), notifications (30d), inbound (30d), person_data (90d)
- Registered on both primary and deferred DB init paths
- Startup catch-up at 5 min after boot (one-time)
- `unsub_startup_catchup` stored for clean unload

### Census write throttle (camera_census.py)
- DB write every 4th cycle (~120s) via counter
- Census compute stays at 30s for real-time sensors

### Other
- Census event debounce: 5s → 30s
- Census cleanup timezone: `datetime.now()` → `dt_util.utcnow()`
- Inter-method `asyncio.sleep(1.0)` yield in maintenance loops

## Review: 2x adversarial, 0 CRITICAL, 2 HIGH fixed, 4 MEDIUM
Full report: `docs/reviews/code-review/v4.2.8_db_prune_batching.md` (if exists) or inline in session context.

## Files Modified (4)
- `database.py` — 8 batched prune/cleanup methods
- `__init__.py` — Nightly maintenance + startup catch-up + Bayesian prune removal
- `camera_census.py` — Write-skip counter
- `const.py` — Census event debounce 5s → 30s
