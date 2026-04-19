# URA — VibeMemo (ojiudezue)

*Last updated: 2026-04-19 | Version 1 | Contributors: ojiudezue*

## DB Write Architecture: Why Single-Threaded and Why That's Right

URA's database layer uses a single-threaded asyncio write worker (v3.22.8) with one persistent SQLite connection. All writes serialize through an asyncio.Queue. Reads use independent transient connections via WAL mode.

This was chosen after v3.18.4's "database is locked" crisis — 25+ rooms writing concurrently caused SQLite lock contention. The single-worker queue mirrors SQLite's fundamental constraint: only one writer at a time. Rather than fighting the database's lock with busy_timeout and retries, we serialize in application code. Five hardening releases (v3.22.8 → v3.22.11 → v4.0.17) made it production-solid.

The architecture is correct. The startup contention problem (31 rooms × 3 writes = 93 writes in 3 seconds causing 35s timeouts) is a demand problem, not an architecture problem. Adding write workers would reintroduce the exact contention v3.22.8 eliminated. The fix is reducing startup demand: defer non-critical first-cycle writes so the first 5 minutes after restart don't flood the queue.
→ [001](users/ojiudezue/entries/001_db_single_writer_architecture.json)

## Open Questions

- Will Priority 1 (defer first-cycle env/energy writes) alone eliminate startup timeouts, or do we also need Priority 2 (stagger first_refresh)?
- Should room state saves also be deferred on first cycle, or are they needed for occupancy restore accuracy?
