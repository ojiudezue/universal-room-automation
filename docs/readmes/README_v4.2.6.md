# v4.2.6 — Defer First-Cycle DB Operations at Startup

**Date:** April 19, 2026
**Scope:** Startup DB write contention elimination
**Tests:** 1478 passing (no regressions)

## Problem

On HA startup, 31 room coordinators all trigger their first refresh simultaneously.
Each first refresh fires 3 DB writes (environmental log, energy snapshot, room
state save) and 5 DB reads (weekly energy, monthly energy, next prediction,
occupancy %, peak hour). Total: 31 × 8 = 248 DB operations in ~3 seconds.

The DB write worker is single-threaded (by design — see Architecture section below).
Under event loop contention from 31 coordinators initializing, the worker can't
process the queue fast enough. Writes that wait >35 seconds get timeout errors:
`DB write worker did not process request within 35s`.

This causes cascading issues: HA's stage 2 setup times out waiting for the write
worker task, startup takes 15+ minutes, and the system is unresponsive.

## Solution

Initialize 4 throttle timestamps to `now()` instead of `None` in coordinator
`__init__`. The throttle checks (`if self._last_X is None or elapsed >= 300`)
see the timestamp as recent and skip the first-cycle operation. Real operations
begin at the 5-minute mark when the system is stable.

### What's Deferred

| Field | Was | Now | Effect |
|-------|-----|-----|--------|
| `_last_env_log` | `None` | `now()` | Environmental log deferred 5 min |
| `_last_energy_log` | `None` | `now()` | Energy snapshot deferred 5 min |
| `_last_room_state_save` | `None` | `now()` | Room state save deferred 5 min (redundant — just restored from DB) |
| `_last_prediction_query` | `None` | `now()` | 5 prediction reads deferred 5 min |

### Startup Impact

**Before:** 31 rooms × (3 writes + 5 reads) = 248 DB operations in ~3 seconds
**After:** 0 DB operations on first cycle. First operations at 5-minute mark.

### What's NOT Deferred

- **Occupancy event logging** (`log_occupancy_event`) — still fires immediately if
  someone is detected on startup. This is event-driven, not throttled.
- **Room state restore** (`get_room_state`) — still reads on setup (before first
  refresh). This is a read in `__init__.py`, not in the coordinator's `_async_update_data`.
- **Energy coordinator DB restores** — consumption history, power profiles, accuracy
  data, circuit state. These are reads during `async_setup()`, not first-refresh writes.

### Data Loss Assessment

~5 minutes of environmental and energy snapshot data per room after each restart.
At 30-second intervals, that's ~10 data points per room. For a system that runs
continuously, this is a trivial gap. The prediction queries are reads that populate
sensor attributes — sensors will show `unknown` or cached values for the first
5 minutes, then populate normally.

## Why Single-Threaded Write Worker Is Correct

The write worker architecture (introduced v3.22.8) uses one persistent SQLite
connection processing writes sequentially from an asyncio.Queue. This was chosen
after v3.18.4's "database is locked" crisis where 25+ rooms writing concurrently
caused SQLite lock contention.

**SQLite only allows one writer at a time.** Adding write workers would reintroduce
the exact contention v3.22.8 eliminated. The single-worker queue mirrors SQLite's
fundamental constraint — serialize writes in application code rather than fighting
the database's lock.

The startup contention is a **demand problem**, not an architecture problem. The
worker processes writes fast (sub-millisecond each). The 35s timeout fires because
the event loop is saturated with 31 coordinator initializations, preventing the
worker from getting scheduled. Reducing demand (this fix) is the correct approach.

See `.vibememo/users/ojiudezue/entries/001_db_single_writer_architecture.json`
for the full decision trail.

## Architecture History

| Version | Change |
|---------|--------|
| v3.18.4 | Added `_db()` context manager with timeout + busy_timeout to all 69 connections |
| v3.13.1 | Serialized 4 concurrent `async_create_task` DB writes into sequential `_periodic_db_writes()` |
| v3.22.8 | Single-worker asyncio.Queue eliminates all write contention |
| v3.22.9 | Crash recovery + fail-fast if worker not running |
| v3.22.10 | Idempotent start + race-safe DB init |
| v3.22.11 | Timeout guards + init order + race safety |
| v4.0.10 | Jitter on poll intervals (0-5s) to spread subsequent refreshes |
| v4.0.17 | DB write worker race fix + review hardening |
| **v4.2.6** | **Defer first-cycle writes/reads to eliminate startup thundering herd** |

## Files Changed
- `coordinator.py` — 4 timestamp initializations changed from `None` to `now()`
