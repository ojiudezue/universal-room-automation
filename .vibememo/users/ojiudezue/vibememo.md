# URA — VibeMemo (ojiudezue)

*Last updated: 2026-04-19 | Version 1 | Contributors: ojiudezue*

## DB Write Architecture: Why Single-Threaded and Why That's Right

URA's database layer uses a single-threaded asyncio write worker (v3.22.8) with one persistent SQLite connection. All writes serialize through an asyncio.Queue. Reads use independent transient connections via WAL mode.

This was chosen after v3.18.4's "database is locked" crisis — 25+ rooms writing concurrently caused SQLite lock contention. The single-worker queue mirrors SQLite's fundamental constraint: only one writer at a time. Five hardening releases (v3.22.8 → v3.22.11 → v4.0.17) made it production-solid.
→ [001](users/ojiudezue/entries/001_db_single_writer_architecture.json)

## Startup Warmup: 10 Minutes, Accepted

After v4.2.6 added startup deferral (all first-cycle DB writes delayed 5 min with per-room jitter), the system improved from "15-minute startup with stage 2 timeouts" to "~10-minute warmup with transient log errors." The remaining errors occur when deferred writes converge at the 5-minute mark — 31 rooms × 3 writes hitting a 60-second window plus census + midnight snapshot catch-up.

The errors are transient, non-destructive, and self-healing. No data is lost (writes queue and complete). No user-facing impact after 10 minutes. Deeper fixes (non-blocking writes, write batching) are deferred to backlog as tech debt — they require architectural changes to the write queue with real risk for diminishing returns.
→ [002](users/ojiudezue/entries/002_startup_warmup_accepted.json)

## Open Questions

- If room count grows past 40, will the 10-minute warmup become unacceptable?
- Should the 35s write timeout be adaptive (longer during startup)?
