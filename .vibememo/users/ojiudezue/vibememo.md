# URA — VibeMemo (ojiudezue)

*Last updated: 2026-05-07 | Version 1 | Contributors: ojiudezue*

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

## Battery Strategy v4.5.0: Phased State Machine + EC Nexus Framing

Through May 2026 the battery strategy hit structural failure. The five-knob system (`reserve_soc`, four `drain_target_*` sliders, `arbitrage_trigger`, `arbitrage_target`) had three coupled problems: arbitrage_trigger=20 sat below drain_target_poor=30 so arbitrage was unreachable from above (rarely fired); when it did fire, charged energy drained back to drain_target during morning off-peak before peak hits at 16:00, wasting the buffer; and "drain less when forecast is bad" structurally conflicts with "charge more when forecast is bad" — the same threshold can't serve both jobs.

A multi-turn design conversation on 2026-05-06/07 produced a phased state machine: **WAIT → CHARGE → HOLD → DISCHARGE**. WAIT means "do nothing, battery operates normally"; CHARGE fires `arbitrage_charge_lead_time_min` (default 360 = 6h) before the next high-rate transition with a fresh forecast re-check that aborts cleanly if class improved; HOLD locks reserve_level at peak_buffer_target until the high-rate window starts; DISCHARGE preserves existing logic. Drain targets stay as the fallback when arbitrage is OFF — byte-for-byte v4.3.4 behavior preserved on every "arbitrage disabled" row of the State Matrix. The matrix in `PLANNING_v4.5.0_battery_strategy_redesign.md` is the implementation spec.

Two key user corrections shaped the design: (1) "Only 1 use Ura for now. So we don't need backward compatibility" → drop ALL mode-toggle / calibration-phase / migration-cycle scaffolding; just ship the new behavior. (2) "Earlier start is better if same day" → lead_time defaults to 360 min not 120, biasing the CHARGE phase to fire after morning intraday solar telemetry confirms forecast.

The cycle introduces the **"EC cost-minimization nexus"** framing — Energy Coordinator is the central decision-maker for every controllable load (battery, EV, eventually appliances), and the umbrella objective is total energy cost minimization. v4.5.0's D4 mutual-exclusion (`_paused_by_arbitrage` set on `EVChargerController`) is the precedent v4.7.x B5 (Appliance Scheduler) will copy onto each appliance controller. Saw-tooth charge rate cap was originally D4; it would flap on Enphase's binary `charge_from_grid` switch and doesn't address breaker safety. Replaced with arbitrage/EV mutual-exclusion that establishes the load-coordination pattern.

Seven advanced topics deferred to v4.6.x (Bayesian peak_buffer_target, charge-rate control via barneyonline HACS, solar-aware partial top-up, intraday-confirmed dynamic lead time, season-variable buffer, per-window economic gate, cycle-wear amortization). Each captured with "why deferred" + "what it would unlock" so v4.6.x has a prioritized backlog when v4.5.0 calibration completes.
→ [006](entries/006_v450_battery_strategy_redesign_pivot.json)

## Transition Doc Skill — Hazard Maps for the Next Session

The v4.5.0 conversation produced ~9 mistake-and-correction pivots. The final plan reflected only the destination; the rejected paths were lost. Recognized this as a recurring pattern — planning conversations regularly produce significant pivots that the artifact alone doesn't preserve, and the next session opening that artifact cold has no protection against re-deriving the same seductive false starts.

Built `.claude/skills/transition-doc/` (with both `SKILL.md` and a publishable `README.md`) — a user-invocable slash command that generates a structured "transition notes" doc capturing mistakes-in-order with user quotes, confirmed-good decisions, hot-zone implementation risks, and a what-good/bad-looks-like checklist for the next session. Output lives next to the plan it accompanies (e.g., `PLANNING_v4.5.0_TRANSITION_NOTES.md`). The first such doc was hand-written for v4.5.0 as the proof-of-pattern; future cycles use `/transition-doc`.

Establishes a three-layer model for cross-session knowledge: durable memory (cross-cutting principles), VibeMemo (load-bearing decisions with structured rationale), transition docs (per-cycle session narrative). Different shapes for different jobs.
→ [007](entries/007_transition_doc_skill_pattern.json)

## Open Questions

- After 2-4 weeks of B-Lite divergence data, is automatic prediction source switching (B3) safe for financial predictions?
- Should Envoy be demoted from primary for cumulative tracking entirely, using Emporia mains as the base?
- Non-blocking fire-and-forget writes (Option C from 002) — eliminates timeouts entirely but changes error handling model
- Write batching (Option D from 002) — groups writes into single transactions, reduces count by ~70%
- v4.5.0 calibration: does `arbitrage_charge_lead_time_min=360` produce the right safety margin? Adjust in v4.5.1 based on observed charge durations + HOLD efficacy.
- Does barneyonline charge-rate-control HACS work on user's Enphase firmware? If yes, v4.6.x rewrites D4 to allow concurrent battery + EV charging.
- After 3-4 transition docs, is the pattern producing artifacts future sessions actually consume? If not, replace with embedded rationale or more aggressive vibememo entries.
