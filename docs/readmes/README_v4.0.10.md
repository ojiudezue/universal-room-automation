# v4.0.10 — DB Query Caching + Poll Stagger

## Problem
Room automations taking 5-39 seconds to respond. Diagnostic instrumentation (v4.0.8-v4.0.9) identified two root causes:

1. **Phase 2+3 DB queries** (energy period scans, prediction queries) running on EVERY 30-second refresh across 31 rooms — 155 DB queries per poll cycle. Individual queries took 3-15 seconds due to SQLite contention.

2. **Thundering herd** — all 31 rooms' poll timers started at the same HA restart time, firing simultaneously every 30 seconds. Each room's `_async_update_data` held the HA 2025.11+ async_refresh lock while waiting for DB queries, blocking event-driven occupancy callbacks for 20-39 seconds.

## Fixes

### 1. Phase 2+3 DB Query Cache (5-minute TTL)
Cached results of 5 DB queries that were running every 30s but return data that changes hourly/daily:
- `get_energy_for_period()` ×2 (weekly + monthly, 14,400 rows each)
- `get_next_occupancy_prediction()` (7-day patterns)
- `get_occupancy_percentage()` (7-day aggregate)
- `get_peak_occupancy_hour()` (7-day aggregate)

Uses the same timestamp-guard pattern as existing `_last_env_log` throttle. Cache timestamp set AFTER cache populated (review fix — prevents 5-min stale window on DB failure). `STATE_NEXT_OCCUPANCY_IN` countdown recomputed each cycle from cached prediction time.

**Impact:** ~90% reduction in DB queries (from 155/cycle to ~5/cycle on cache miss every 5 min).

### 2. Poll Timer Jitter
Added `random.uniform(0, 5)` seconds to each room's `update_interval` (30-35s). Prevents all 31 rooms from polling simultaneously after HA restart. Small range (0-5s) limits occupancy timeout overshoot to max +5s.

### 3. Diagnostic Cleanup
Removed all v4.0.6-v4.0.9 diagnostic WARNING logs. Restored RESILIENCE-002 motion log to INFO level.

### 4. Trailing Refresh Cleanup (review fix)
Added `_trailing_refresh_unsub` cleanup to `__init__.py` unload path — was missing from the v4.0.7 rate limiter addition.

## Expected Performance
- **Before:** 5-39 seconds sensor → light (measured)
- **After:** ~700ms-1s (estimated: callback 10ms + refresh 150ms + debounce 400ms + refresh 150ms)
- **Improvement:** 7-50x faster

## What Is NOT Affected
- Activity Log, Bayesian, HVAC — zero real-time dependency on cached data
- Occupancy detection — still event-driven via Tier 1 listeners
- Energy cost per hour — uses real-time power, not cached
- First refresh after restart — queries DB fresh (cache empty)

## Review Summary
- Tier 2 feature review (two reviews)
- Review 1: 1 HIGH (cache timestamp ordering — fixed), 1 MEDIUM (stale precool times — mitigated by TTL)
- Review 2: 1 HIGH (trailing_refresh_unsub cleanup — fixed), 1 MEDIUM (first-cycle herd — acceptable, WAL handles)
- All findings addressed

## Files Changed
- `coordinator.py` — cache, jitter, diagnostic cleanup
- `__init__.py` — trailing refresh unsub cleanup on unload
