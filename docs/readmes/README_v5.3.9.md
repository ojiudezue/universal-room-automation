# URA v5.3.9 — Arbitrage Solar-Attainability Three-Rung Ladder + Breaker-Safety Chokepoint

Operator-found 2026-06-13 (excellent-solar morning): arbitrage CHARGE fired and paused both EVs even though solar (17 kW, net exporting, grid $0) would fill the battery to target for free — the inverse of the v5.3.8 attainability gap. Cycle adds a least-cost intervention ladder AND closes a breaker-safety hole (incl. one latent since v5.3.8).

Tier 2-DB at full ceremony: build + 2 fix-ups + validator + 3 framing-disjoint reviews + focused breaker pass + final confirm (0/0/0/0). Ledger: `docs/reviews/code-review/arbitrage_solar_attainability_ladder.md`. Plan: `docs/planning/PLANNING_arbitrage_solar_attainability_ladder.md`.

## What ships

### Three-rung arbitrage ladder (D1) — least-cost intervention first
Reuses the v5.3.8 attain projection (`_expected_solar_surplus_pct`, K-tick rate window). At each arbitrage-eligible tick, `_classify_attain_rung` runs a **two-pass** projection:
- **Rung 0 — do nothing:** if today's projected SOC at the high-rate boundary reaches `peak_buffer_target` with CURRENT loads (incl. EVs), the arbitrage gate is **suppressed** — no grid, EVs keep charging on solar.
- **Rung 1 — redirect (the operator's "suppress EVs first"):** if rung-0 misses, re-project with the EV load removed. If *that* attains, **pause EVs only** (label `redirect`), command NO grid. EXIT is **counterfactual** (project as if EVs were resumed) so pausing them can't spuriously self-satisfy rung-0 — a stable latch, not an oscillator (the v5.3.8 self-referential-rate lesson, applied preemptively; mutation-guarded by a 5-tick oscillation test).
- **Rung 2 — grid:** only if even EV-paused solar misses → command `charge_from_grid` (label `breaker`).
No-solar / no-EV short-circuits skip rung-1. v5.3.8 attain remains the realized-divergence safety net on the post-gate fallback.

### Bidirectional breaker-safety chokepoint (D2)
A 20 kW grid charge + a charging EV + base ≈ 134 A → main-breaker trip. Enforced as a single dispatch-site chokepoint keyed on `decision["charge_from_grid"]` (phase-label-independent, so it covers arbitrage CHARGE, v5.3.8 attain — **a latent hole closed** — and rung-2 uniformly):
- No `charge_from_grid=True` dispatches until EVs are commanded paused (breaker) earlier in the same tick.
- No EV commanded ON (ensure-on, TOU/arbitrage resume) while grid charge is commanded/ON — guard reads the **decision flag OR** the live switch (covers the 35-min actuation lag), fails CLOSED on `unavailable` with a last-known-good latch.
- Reboot mid-charge: live-switch read re-establishes the breaker pause; ensure-on stays suppressed.

### Parsimony / observability
No new CONF, no new entity. Surfaces via existing `arbitrage_phase`/`reason` + a new `paused_by_arbitrage_reasons` attr on the existing EV diag sensor.

## Accepted-as-designed
Rung-1 defers EV charging without a deadline guard (operator ruling 2026-06-13): the battery-buffer > deferred-EV-charge assumption is accepted (overnight off-peak slack; cars TOU-paused through mid_peak anyway). Revisit only if a real tight-same-day-deadline case bites.

## Live Validation — Validated 2026-06-13 (restart 12:24 CDT, mid-charge)

Deployed into the live incident shape (excellent solar, net exporting, EVs paused under the OLD code). Restart landed during an active arbitrage charge — a live test of the reboot-mid-charge breaker recovery.

| Criterion | Result | Evidence |
|---|---|---|
| Clean restart, zero URA ERRORs, 40/40 entries, EC producing | PASS | 40/40 loaded; EC produced within 2 cycles (first cycle Envoy-holding per v5.3.7 decoupling); zero URA ERROR lines |
| Reboot mid-charge breaker recovery | PASS | `charge_from_grid` was ON at restart; post-boot EC re-engaged arbitrage with EVs re-paused (`evse_paused_by_arbitrage: [garage_a, garage_b]`, `current_holds_active: [arbitrage_compound_load]`) — no EV left on under the charge |
| `attain_state` / projection attrs render | PASS | `attain_state: inactive`, projection attrs present (null while the post-restart K-tick window seeds — cold-boot defer to rung-2, by design) |
| **Rung-0/rung-1 suppression (the headline)** | **NOT YET EXERCISED** | Two reasons: (1) K-tick rate window still seeding post-restart → cold-boot defers to rung-2; (2) solar collapsed 18→4.6 kW (clouds) within minutes of the restart, removing the "solar attains" condition. The morning's excellent-exporting window (where the fix *would* suppress) occurred pre-restart under the old code — which is exactly where the EVs were observed needlessly paused while exporting (the incident this fixes). Headline behavior is mutation-anchored in-suite (oscillation + ordering + capacity mutations); awaits a clean post-warmup excellent-solar window. |
| Breaker ordering / resume guard / fail-closed | IN-SUITE | Coordinator-tick integration test + ordering mutations (turn-off-before-grid on arbitrage AND attain ticks); could not be live-exercised without a real grid-charge tick on warm state. |
| `paused_by_arbitrage_reasons` attr | PASS (shape) | Attribute present on the EV diag sensor; showed breaker-label pause under the post-boot arbitrage charge. |

**Note:** observed that under a sudden solar collapse during commanded arbitrage CHARGE, the Enphase side let the battery discharge to serve house load (net≈0, no grid import) rather than pulling grid — an Enphase self-consumption behavior, not a URA defect; flagged for the EVSE-coordination follow-up.

**Re-validation attempts (recurring daily check armed):**
- **2026-06-14 10:00 CDT — blocked:** Envoy integration in `setup_retry` (~9h, no telemetry) → EC holding, no attainability decision possible; also moderate solar + gate closed (today + d2 moderate). `attain_state: inactive` / `evse_paused: []` reflect the Envoy-down hold, NOT a deliberate suppression. Two clean side-PASSes that day: v5.3.7 Envoy decoupling held (URA fully up despite Envoy `setup_retry`, zero URA errors), and NO breaker-invariant assertion in logs.

*Headline ladder suppression remains live-unexercised (same caveat class as v5.3.8 attain entry) — re-validate on a clean post-warmup good/excellent-solar day with the arbitrage gate open AND the Envoy reporting. Recurring 10:07 CDT check self-records the PASS when conditions align.*
