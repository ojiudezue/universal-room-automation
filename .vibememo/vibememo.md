# Universal Room Automation — VibeMemo

*Last updated: 2026-04-30 | Version 1 | Contributors: ojiudezue*

## How This Started

URA is a Home Assistant custom integration managing 31 rooms across 5 zones with 7 domain coordinators (Presence, Energy, HVAC, Safety, Security, Music Following, Notifications). It automates room behavior based on occupancy detection, Bayesian prediction, energy optimization, and cross-coordinator signals.

## Key Decisions

**Single-threaded DB write worker (v3.22.8):** SQLite only allows one writer at a time. Instead of multiple connections fighting for the lock, all writes serialize through one asyncio.Queue processed by one persistent connection. Reads use independent transient WAL connections. This eliminated all write contention from the v3.18.4 "database is locked" crisis.
→ [001](users/ojiudezue/entries/001_db_single_writer_architecture.json)

**Write worker as background task with graceful shutdown (v4.2.15-16):** The write worker runs forever — using `async_create_task` made HA wait indefinitely for startup completion. Changed to `async_create_background_task`. On shutdown/reload, pending writes are now flushed (5s budget, fresh connection) instead of failed with RuntimeError. Data integrity preserved across restarts.
→ [005](users/ojiudezue/entries/005_db_write_worker_startup_fix.json)

**Startup catch-up prune removed (v4.2.14):** Added in v4.2.8 to clear orphaned table backlogs, delayed to 30 min in v4.2.13, removed in v4.2.14. Regardless of delay, it saturated the write queue for 15+ minutes on every boot, blocking all DB reads. Nightly 2:30 AM maintenance is the sole cleanup mechanism. The one-time backlog it was designed to clear is gone.

**Energy measurement trust hierarchy (v4.2.16+):** Three independent measurement sources — Envoy (solar gateway), Emporia Vue (mains CTs), SmartHub (utility meter) — don't agree. Envoy drifts ~5 kWh/day from utility billing. Trust hierarchy for cumulative accuracy: SmartHub > Emporia/SPAN > Envoy. Envoy remains primary for real-time (sub-second resolution). SmartHub will calibrate bill predictions. Emporia mains will populate the empty `grid_import_2` column in energy_history for historical cross-validation. Shipping divergence reporting first (B-Lite), deferring auto source switching (B3) until 2-4 weeks of data validates the pattern.
→ [003](users/ojiudezue/entries/003_energy_measurement_trust_hierarchy.json)

## Current Architecture

- **Write path:** 44 write methods → `_db()` → asyncio.Queue → single background write worker → one persistent SQLite connection. Graceful 5s flush on cancel.
- **Read path:** 43 read methods → `_db_read()` → transient WAL connections. Zone sensors cached 5 min, Bayesian accuracy cached 30 min.
- **Startup:** First-cycle writes deferred 5 min with 0-60s jitter. No catch-up prune. Bayesian predictor registered before DB load (survives init failure). Write worker is a background task (doesn't block startup). ~5 min warmup.
- **Energy:** Envoy primary for real-time, CostTracker uses Emporia mains for billing. Utility meter integration planned (B-Lite).
- **EV control:** TOU pause + grid cap pause. Battery drain auto-pause planned (Cycle A).
- **DB:** 810 MB, WAL mode, 30s busy_timeout. Nightly 2:30 AM prune (7 tables, rotating start, 5-min budget). SQLite-over-SMB reads blocked by persistent write worker — known limitation, not a code bug.

## Open Questions

- After B-Lite divergence data, is automatic prediction source switching safe for financial predictions?
- Should Envoy be demoted from primary for cumulative tracking?
- Non-blocking fire-and-forget writes — eliminates timeouts but changes error model
- Write batching — groups writes into single transactions, reduces count by ~70%
- If room count grows past 40, will warmup become unacceptable?
