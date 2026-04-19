# Universal Room Automation — VibeMemo

*Last updated: 2026-04-19 | Version 1 | Contributors: ojiudezue*

## How This Started

URA is a Home Assistant custom integration managing 31 rooms across 5 zones with presence detection, HVAC automation, energy management, and Bayesian occupancy prediction. The database layer evolved from direct concurrent SQLite access (frequent "database is locked" errors) to a single-threaded write worker queue (v3.22.8) that eliminated all write contention.

## Key Decisions

**Single-threaded DB write worker (v3.22.8):** SQLite only allows one writer at a time. Instead of multiple connections fighting for the lock, all writes serialize through one asyncio.Queue processed by one persistent connection. Reads use independent transient WAL connections. This survived 5 hardening releases and is the correct architecture for SQLite.
→ [001](users/ojiudezue/entries/001_db_single_writer_architecture.json)

## Current Architecture

- **Write path:** All 44 write methods → `_db()` context manager → asyncio.Queue → single write worker → one persistent SQLite connection → per-write commit
- **Read path:** All 43 read methods → `_db_read()` → transient connection → WAL concurrent reads
- **Startup:** 31 rooms × (3 writes + 5 reads) = 248 DB operations in ~3 seconds. Write queue can't keep up under event loop contention → 35s timeouts. Fix: reduce startup demand, not add parallelism.

## Open Questions

- Optimal startup write deferral strategy — defer env/energy logs only, or also room state saves?
- Whether staggered first_refresh (Priority 2) is needed in addition to write deferral (Priority 1)
