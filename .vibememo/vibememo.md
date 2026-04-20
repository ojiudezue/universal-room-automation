# Universal Room Automation — VibeMemo

*Last updated: 2026-04-19 | Version 1 | Contributors: ojiudezue*

## How This Started

URA is a Home Assistant custom integration managing 31 rooms across 5 zones with presence detection, HVAC automation, energy management, and Bayesian occupancy prediction. The database layer evolved from direct concurrent SQLite access (frequent "database is locked" errors) to a single-threaded write worker queue (v3.22.8) that eliminated all write contention.

## Key Decisions

**Single-threaded DB write worker (v3.22.8):** SQLite only allows one writer at a time. Instead of multiple connections fighting for the lock, all writes serialize through one asyncio.Queue processed by one persistent connection. Reads use independent transient WAL connections. Adding writers would reintroduce the contention it eliminated.
→ [001](users/ojiudezue/entries/001_db_single_writer_architecture.json)

**Startup warmup accepted (v4.2.6):** After deferring first-cycle writes by 5 minutes with per-room jitter, startup improved from 15 minutes to ~10 minutes. Remaining transient errors at the 5-minute mark are accepted — non-destructive, self-healing, no user impact. Deeper fixes (non-blocking writes, write batching) deferred to backlog.
→ [002](users/ojiudezue/entries/002_startup_warmup_accepted.json)

## Current Architecture

- **Write path:** 44 write methods → `_db()` → asyncio.Queue → single write worker → one persistent SQLite connection
- **Read path:** 43 read methods → `_db_read()` → transient WAL connections
- **Startup:** First-cycle writes deferred 5 min with 0-60s jitter. Census deferred 5 min. Person snapshot deferred 15 min. Energy save hours initialized to current hour. ~10 min warmup before all errors clear.

## Open Questions

- Non-blocking fire-and-forget writes (Option C from 002) — eliminates timeouts entirely but changes error handling model
- Write batching (Option D) — groups writes into single transactions, reduces count by ~70%
- Both deferred to backlog as tech debt
