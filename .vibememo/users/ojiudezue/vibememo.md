# URA — VibeMemo (ojiudezue)

*Last updated: 2026-04-30 | Version 1 | Contributors: ojiudezue*

## DB Write Architecture: Why Single-Threaded and Why That's Right

URA's database layer uses a single-threaded asyncio write worker (v3.22.8) with one persistent SQLite connection. All writes serialize through an asyncio.Queue. Reads use independent transient connections via WAL mode.

This was chosen after v3.18.4's "database is locked" crisis — 25+ rooms writing concurrently caused SQLite lock contention. The single-worker queue mirrors SQLite's fundamental constraint: only one writer at a time. Five hardening releases (v3.22.8 → v3.22.11 → v4.0.17) made it production-solid.
→ [001](entries/001_db_single_writer_architecture.json)

## Startup & Shutdown: Lessons from v4.2.8–v4.2.16

The DB write queue architecture went through a crisis cycle (Apr 2026). An unbounded DELETE in `prune_prediction_results` held the write queue for >120 seconds, causing HA unresponsiveness and hardware reboots. This exposed three compounding issues: unbounded prunes, high-frequency DB reads from sensor polls, and orphaned cleanup methods.

A startup catch-up prune was added (v4.2.8) to clear backlogs, then delayed to 30 min (v4.2.13), then removed entirely (v4.2.14) — it saturated the write queue on every boot regardless of delay, blocking all DB reads for 15+ minutes. Nightly 2:30 AM maintenance is now the sole cleanup mechanism.

The write worker itself was blocking HA startup (v4.2.15) because `async_create_task` tracks tasks for startup completion — a forever-running task never completes. Fixed with `async_create_background_task`. Shutdown was also lossy: all pending writes were failed with RuntimeError on cancel. v4.2.16 added graceful flush with a 5-second time budget — opens a fresh connection, executes remaining writes, then drains failures for anything left.
→ [005](entries/005_db_write_worker_startup_fix.json)

## Energy Measurement: Three Sources, One Truth

URA has three independent energy measurement sources. They don't agree.

1. **Enphase Envoy** — solar gateway with net consumption CT. Sub-second resolution. Primary source for real-time decisions. But cumulative totals drift ~5 kWh/day from the utility meter.
2. **Emporia Vue** — mains panel CTs measuring actual grid import (`mainsfromgrid`) and export (`mainstogrid`). Historically more aligned with utility billing than Envoy.
3. **SmartHub (utility company)** — the meter the electric company bills from. Daily midnight readings. The ground truth for what you actually pay.

The trust hierarchy for cumulative accuracy: SmartHub > Emporia/SPAN > Envoy. Envoy remains primary for real-time because of its resolution, but its cumulative drift means bill predictions based purely on Envoy are off by ~$18/month.

Decision: integrate SmartHub as bill prediction calibration source (B-Lite: divergence reporting first, auto-switching deferred). Populate the empty `grid_import_2` DB column with Emporia mains power for historical cross-validation.
→ [003](entries/003_energy_measurement_trust_hierarchy.json)

## EV Charging: Completing Autonomous Control

EV charge control had two pause reasons: TOU scheduling (pause during peak/mid-peak) and grid import cap (pause when import exceeds threshold). Missing: battery drain protection. The user manually paused charging every evening when the EV drew power from the Enphase battery instead of the grid.

Adding a third pause reason (`_paused_by_battery_drain`) with configurable SOC threshold completes the autonomous control loop. Follows the exact code pattern of the existing grid cap pause.
→ [004](entries/004_ev_battery_drain_autopause.json)

## Open Questions

- After 2-4 weeks of B-Lite divergence data, is automatic prediction source switching (B3) safe for financial predictions?
- Should Envoy be demoted from primary for cumulative tracking entirely, using Emporia mains as the base?
- Non-blocking fire-and-forget writes (Option C from 002) — eliminates timeouts entirely but changes error handling model
- Write batching (Option D from 002) — groups writes into single transactions, reduces count by ~70%
