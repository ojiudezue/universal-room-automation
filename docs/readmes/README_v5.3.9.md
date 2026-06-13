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

## Live Validation (Review D) — prospective criteria
- [ ] Clean restart; zero URA ERRORs; 40/40 entries; EC producing.
- [ ] **Excellent-solar day, gate open via d2=poor but solar delivering:** rung-0 suppresses arbitrage — EVs NOT paused while net is exporting; battery still reaches target on solar; `charge_from_grid` never commanded. (This is today's exact incident shape — the defining test.)
- [ ] Rung-1: a tick where EVs eating solar make rung-0 miss but EV-paused attains → EVs pause (`redirect`), no grid; resume when rung-0 recovers; no on/off churn.
- [ ] Breaker ordering: on any grid-charge tick, EV `turn_off` is dispatched before `charge_from_grid`; no EV `turn_on` while grid charging.
- [ ] `paused_by_arbitrage_reasons` attr shows redirect vs breaker correctly.

*Replaced with observed results post-restart per the README write-back rule.*
