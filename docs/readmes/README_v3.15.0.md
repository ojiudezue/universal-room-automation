# v3.15.0: EC Restart Resilience + Envoy Offline Defense

**Date:** 2026-03-13
**Branch:** develop -> main
**Tests:** 24 new resilience tests, 1092 total

## Problem

Energy Coordinator lost critical state on HA restart:
- **Daily billing accumulators** (import_kwh, export_kwh, cost) reset to zero mid-day
- **Consumption history baselines** (per-DOW deques for prediction) started empty, forcing 45 kWh fallback
- **Load shedding level** dropped to 0, releasing all shed protections
- **Battery full time** showed "unknown" until Envoy reconnected (could take 15+ minutes)
- **Midnight lifetime snapshots** — if Envoy was offline at restart, consumption tracking lost the day's baseline

## Solution

Three new DB tables + restore/save methods provide full state persistence across HA restarts.

### Phase 1: Restart Resilience

#### `database.py` — 3 new tables
- **`energy_midnight_snapshot`**: Singleton row storing midnight lifetime sensor values + daily billing accumulators. Persisted at midnight, every 15 minutes, and at shutdown.
- **`energy_state`**: Generic key-value store for persistent state (load shedding level, future use).
- **`envoy_cache`**: Singleton row caching last-known Envoy sensor values (SOC, power, lifetime values). Updated every 15 minutes when Envoy is online. Staleness-checked on restore (skipped if > 4 hours old).
- **`get_consumption_history()`**: New query returning recent energy_daily rows for DOW baseline restore.

#### `energy_forecast.py` — `restore_consumption_history()`
- Restores per-DOW consumption deques from energy_daily on startup
- Processes oldest-first to keep most recent values when deque maxlen exceeded

#### `energy_billing.py` — `restore_daily()`
- Restores today's billing accumulators (import/export kWh, cost) from midnight snapshot
- Date-checked: only restores if snapshot date matches today

#### `energy.py` — Startup restore sequence
Added to `async_setup()` after existing restores:
1. `_restore_consumption_history()` — per-DOW baselines from energy_daily
2. `_restore_midnight_snapshot()` — lifetime snapshots + billing accumulators
3. `_restore_envoy_cache()` — battery_full_time hold cache
4. `_restore_load_shedding_level()` — with 3-cycle grace period to prevent immediate de-escalation

#### `energy.py` — Save points
- **Midnight**: `_save_midnight_snapshot()` fires immediately when `_maybe_reset_daily` detects date change
- **Every 15 min**: Envoy cache + midnight snapshot saved inside `_periodic_db_writes()` (serialized with other DB writes)
- **Shutdown**: All three saved in `async_teardown()`

### Phase 2: Envoy Offline Defense

- **Envoy cache**: Last-known SOC, power, and lifetime values cached to DB each cycle when Envoy is online
- **Staleness guard**: Cache older than 4 hours is ignored on restore (prevents misleading data after extended downtime)
- **Battery full time**: `already_full` state restored from cache when SOC >= 99

### Load Shedding Grace Period

After restoring a non-zero load shedding level, a 3-cycle grace period suppresses de-escalation while the sustained readings buffer refills. Without this, the empty buffer would immediately trigger de-escalation, defeating the persistence.

## Files Changed

| File | Changes |
|------|---------|
| `database.py` | 3 new tables + 7 CRUD methods |
| `energy.py` | 8 new restore/save methods, wired into setup/cycle/teardown |
| `energy_forecast.py` | `restore_consumption_history()` |
| `energy_billing.py` | `restore_daily()` |
| `test_energy_restart_resilience.py` | 24 new tests |
