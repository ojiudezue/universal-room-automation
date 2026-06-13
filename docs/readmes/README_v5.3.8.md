# URA v5.3.8 — Peak-Buffer Attainability + Reboot Decision-Pickup

Strategy cycle motivated by the 2026-06-12 incident: good-solar day, EV off-peak charging consumed all production, battery entered mid_peak at 10% vs the 80% buffer target; the forecast-class-only arbitrage gate (`_gate_is_open`, poor/very_poor days only) never consulted the buffer. Operator-ratified principle: **"no solar reaching the battery → need for arbitrage."**

Tier 2-DB at maximum ceremony: build + 2 full framing-disjoint review passes (6 reviewers) + focused pass-3 + 4 fix-up passes + 7-mutation test-authority regime. Ledger: `docs/reviews/code-review/ec_hc_reboot_decision_pickup.md`. Plan: `docs/planning/PLANNING_ec_hc_reboot_decision_pickup.md`.

## What ships

### D1 — Attainability branch (`attain` arbitrage phase)
- Tri-state machine `inactive → charging → holding`, routed before the entry predicate, chunk-lock, and drain fallback in BOTH the off_peak and mid_peak branches.
- **Entry** (evaluated only when inactive): SOC < peak_buffer_target AND charge window open AND solar-informed projection misses target — projection = SOC + K=3-smoothed observed net rate + time-sliced Solcast forecast (today entity, tomorrow entity for midnight-crossing winter windows; local-time daylight bounds; stale forecast → 0, fail-toward-charging). 30-min entry floor.
- **Charging**: command-once + verify-only; operator/cloud drift = observed ON→OFF transition only (actuation lag is never drift); grid-import guard with chunk-lock honored.
- **Holding** (SOC ≥ target): reserve pinned at target every tick until the boundary — persists through the 15-min handoff lead (generalized to any boundary whose period rate ≥ current).
- **Reboot recovery from hardware state**: charge_from_grid ON at boot → adopt in-flight charge (or HOLD); unavailable → defer without consuming the once-latch; out-of-window → orderly release. No RAM-latch trust.

### D1b — Mid-peak continuation (state-matrix invariant change, operator-mandated)
"Arbitrage IS arbitrage": if off_peak couldn't build the buffer, attain continues/enters during mid_peak targeting the PEAK boundary — gated on live TOU rate spread (mid_peak < peak), summer-only, SOC below target, peak-ahead. Charging during peak remains structurally impossible.

### D2 — Reboot decision-pickup
20-row inventory of time-anchored EC/HC decisions (ledger). Fixed: HVAC pre-cool day-flag pickup, cover hysteresis re-seed (with operator-close protection + band alignment). Deferred: dwell-timer persistence, EVSE force-charge KV, TOU cross-day rows (hygiene bucket).

### Riders
- Load shedding now uses battery-excluded import (attain's grid draw can't shed the pool/EVs).
- Savings accounting: solar-driven SOC rise excluded from attain savings; displaced-rate from the live TOU engine.

## Measured constants (2026-06-12 manual arbitrage, baked into design)
Reserve-bump solar-charge onset ~22 min; charge_from_grid cloud enable ~35 min; full rate ~16 kW (8 Encharges). Manual SOC result that day: 10%→45%.

## Live Validation (Review D) — prospective criteria
- [ ] Clean restart; zero new URA ERRORs; 40/40 entries; EC producing within 5 min.
- [ ] `arbitrage_phase` exposes `attain`/HOLD reasons in plain English on the battery-strategy sensor.
- [ ] **Tomorrow's charge window (~08:00)**: if SOC < 80% and solar-informed projection misses → attain enters (phase=`attain`, reason names the cause); charge_from_grid commanded ONCE; no oscillation (no repeated cloud writes within the chunk).
- [ ] SOC reaches target → HOLD: reserve stays pinned through 13:45–14:00 (no drain release inside the lead window).
- [ ] If buffer still short at 14:00 with positive rate spread → mid_peak continuation engages targeting peak; turn-off lands by peak−15 min.
- [ ] No load-shedding escalation attributable to battery charge draw.
- [ ] Good-solar-and-actually-delivering morning: attain does NOT enter (solar term nonzero — verifies the as_local fix live).

*Replaced with observed results post-restart per the README write-back rule.*
