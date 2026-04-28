# Retrospective: DB Query Performance Crisis (v4.0.17–v4.2.11)

**Date:** 2026-04-28
**Duration of impact:** ~2 weeks (Apr 12–27)
**Severity:** HIGH — caused HA unresponsiveness, hardware reboots, app disconnections

---

## Timeline

| Date | Event |
|------|-------|
| Apr 12 | v4.0.15 introduced async_call_later coroutine bug → event loop congestion |
| Apr 12 | Congestion exposed latent DB init race (31 write workers) → HA crash, hardware reboot |
| Apr 13 | v4.0.17 fixed DB init race (asyncio.Lock). Startup DB write burst still caused 4 timeouts. |
| Apr 13-26 | Recurring "DB write worker did not process request within 35s" errors. Queue peaks 82-94 items. |
| Apr 27 | Diagnosed: `prune_prediction_results` (unbounded DELETE every 30 min) held write queue >120s |
| Apr 27 | v4.2.8 batched all prune operations + nightly maintenance. First run cleared backlog but caused 12 min congestion. |
| Apr 27 | v4.2.9 added time budget + rotation. Also fixed timezone-naive sensor crashes. |
| Apr 27 | v4.2.10 added EC toggles + memory sensor. Memory sensor revealed shallow measurement was useless. |
| Apr 27 | Discovered zone/Bayesian sensors doing DB reads every 30s → 202 occurrences of >10s updates |
| Apr 28 | v4.2.11 cached zone sensors (5 min) + Bayesian accuracy (30 min). HA became responsive. |

---

## Root Causes (3 compounding issues)

### 1. Unbounded prune DELETE in write queue
`prune_prediction_results()` ran every 30 minutes with no LIMIT clause. After weeks of predictions (~43K rows), the DELETE held the single write worker for >120 seconds. All other writes (31 rooms × energy/environmental snapshots) queued behind it.

**Why it wasn't caught:** The prune was added in the Bayesian B1 cycle (v4.0.0) when the table was small. No performance testing with realistic data volumes. No batching pattern existed yet.

### 2. High-frequency DB reads from sensor platform
Zone last occupant sensors and Bayesian accuracy sensor used `async_update()` with no caching — HA calls this every 30 seconds by default. Each opened a transient `_db_read()` connection and queried potentially large tables (`person_visits`, `prediction_results`). These reads competed with writes for SQLite WAL checkpoint access.

**Why it wasn't caught:** Read queries were assumed fast because they use `_db_read()` (independent connections, WAL mode). But under write queue congestion, even read connections block during WAL checkpoint. The combination of high read frequency + congested writes created a feedback loop.

### 3. Never-called cleanup methods
5 cleanup methods existed in `database.py` but were never scheduled: `cleanup_census`, `cleanup_energy_history`, `cleanup_external_conditions`, `prune_notification_log`, `cleanup_person_data`. These tables grew unbounded, making the first nightly prune after v4.2.8 process months of data.

**Why it wasn't caught:** The methods were implemented during feature cycles (v3.5.0–v3.9.7) with the intent to "wire up later." No follow-up task was created. The DEVELOPMENT_CHECKLIST.md doesn't include "verify cleanup methods are scheduled."

---

## What We Should Have Done Differently

### At implementation time
1. **Every DB write method should have a corresponding cleanup method AND a scheduled call.** Add to DEVELOPMENT_CHECKLIST: "If you add a DB INSERT, verify there's a DELETE/prune method AND it's scheduled."
2. **Every `async_update()` that does a DB query should have a cache with TTL.** The v4.0.10 query caching for room coordinator reads set this pattern — but zone/aggregation sensors didn't follow it.
3. **LIMIT clause on every DELETE operation by default.** Unbounded DELETEs are never safe in a single-writer queue.
4. **Performance test DB operations with realistic row counts** before shipping. Even a simple `INSERT 50000 rows; time DELETE` would have caught the prune issue.

### At review time
5. **Review checklist should include: "Does any async_update() hit the database? If yes, what's the cache TTL?"** This would have caught the zone sensor issue during the Bayesian B2 review.
6. **Review checklist should include: "Is there a LIMIT on every DELETE statement?"** This would have caught the prune issue.

### At monitoring time
7. **The DB write queue peak metric should trigger an alert.** We had `_db_stats["queue_peak"]` logging at >10 items but no persistent sensor until v4.2.10. If we'd had the memory/DB diagnostic sensor earlier, we'd have seen queue_peak climbing days before it crashed.

---

## New Bug Classes for QUALITY_CONTEXT.md

### Bug Class #24: Unbounded DB DELETE in Write Queue
**Pattern:** A DELETE operation without LIMIT runs inside the serialized `_db()` write queue. Table grows over time; DELETE takes progressively longer, eventually blocking all writes.
**Prevention:** Always use `DELETE ... WHERE rowid IN (SELECT rowid ... LIMIT N)` with batching loop. Never run unbounded DELETEs through the write queue.

### Bug Class #25: High-Frequency DB Read from Sensor Platform
**Pattern:** A sensor's `async_update()` queries the database every 30s (HA default). Under write congestion, reads block on WAL checkpoint. 202+ occurrences of >10s updates saturate the event loop.
**Prevention:** Cache DB query results with a TTL appropriate for the data's change frequency. Zone occupancy → 5 min. Prediction accuracy → 30 min. Energy data → 5 min (already cached via v4.0.10).

### Bug Class #26: Orphaned Cleanup Method
**Pattern:** A DB cleanup/prune method exists but is never called from any scheduler. The table grows unbounded until disk/memory pressure causes issues.
**Prevention:** Every `INSERT` table must have a matching cleanup in the nightly maintenance list. Add to DEVELOPMENT_CHECKLIST.

---

## Changes Made

| Version | Fix |
|---------|-----|
| v4.0.16 | async_call_later coroutine → plain callback |
| v4.0.17 | DB init race → asyncio.Lock double-checked locking |
| v4.2.6 | Startup DB op deferral (5 min grace period) |
| v4.2.8 | Batched all 8 prune methods (LIMIT 1000, max 500 batches) |
| v4.2.8 | Nightly maintenance at 2:30 AM for all 7 cleanup ops |
| v4.2.8 | Census write throttle (every 4th cycle) |
| v4.2.9 | Time budget (5 min) + rotating start index on nightly |
| v4.2.9 | Timezone-naive datetime fixes |
| v4.2.11 | Zone sensor DB read cache (5 min) |
| v4.2.11 | Bayesian accuracy DB read cache (30 min) |
| v4.2.11 | Memory sensor reworked to counts-based |

---

## Checklist Additions

Add to `quality/DEVELOPMENT_CHECKLIST.md`:

- [ ] Every DB INSERT table has a cleanup/prune method
- [ ] Every cleanup method is scheduled (nightly maintenance or startup)
- [ ] Every DELETE uses LIMIT with batching loop
- [ ] Every sensor `async_update()` that queries DB has cache TTL
- [ ] DB write queue peak monitored via diagnostic sensor
- [ ] New tables estimated for row growth rate × retention period
