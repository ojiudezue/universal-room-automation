# Review record — v5.17.1: Arbitrage completed-chunk HOLD precedence (Tier 3)

**Incident:** 2026-07-14 live — after arbitrage charged to 80 (verified write 08:01), SOC reaching target made rung_0 close the gate guarding the HOLD phase; drain fallback released reserve to 30 at 09:31, draining purchased charge into off_peak load 4.5h pre-boundary.
**Invariant (I-AH1):** completed chunk + boundary ahead ⇒ no reachable path emits reserve < peak_buffer_target (floors raise-only).
**Chain:** plan `62517d73` → build `9b8e3c91` (red-first repro) → reviews A/B/C/D → fix part 1 `237f7986` (code) → part 3 `c61f3124` (5 seam anchors, 5 mutations RED) → part 3b `aaab3598` (wall-clock decoupling, 100-year determinism proof) → D re-pass SHIP → orchestrator verification (emission re-grep 18 sites; independent boundary mutation RED; pristine 158/158; full suite 36/14 baseline exact).

## Findings ledger

| ID | Sev | Finding | Outcome |
|---|---|---|---|
| (build) | — | Red-first repro of incident (reserve 30 emitted, phase n/a) | regression test, red-on-62517d73 proven |
| A-HIGH-1 | HIGH | D2 persistence tests order-dependent (import-fail standalone) | resolved at HEAD (self-sufficient bootstrap; standalone fresh-interpreter proof) |
| A-MED-1 | MED | Sub-minute boundary hole (`_bnd_mins > 0` skips final 0-59s) | fixed: `_bnd_dt > now` tz-normalized; anchored (mutation RED) |
| A-LOW-1 | LOW | Reason printed un-floored target | fixed |
| B-MED-1 | MED | Latch persisted only on 15-min cadence (completion→save reboot window) | fixed: eager persist on CHARGE→HOLD edge; anchored |
| C-HIGH-1 | HIGH | Boundary conjunct untested; builder's mutation (b) claim was a FALSE ANCHOR (C re-executed: GREEN) | fixed via A-MED-1 test; anchored |
| C-HIGH-2 | HIGH | D2 save side dead-testable | round-trip test; M12 RED |
| C-HIGH-3 | HIGH | `_floor_reserve` at D1 emission unanchored | partial_hold tests; M6 RED |
| C-MED-1/2/3 | MED | attain precedence / disabled-mid-hold / unparseable-boundary unanchored | anchored in parts 3/3b |
| D-HIGH-1 | HIGH | attain-holding + rung_2 reopened gate → WAIT emitted reserve_soc (80→20 repro) | fixed: dual-owner short-circuit; repro is regression test; D re-pass proves WAIT unreachable |
| D-HIGH-2 | HIGH | LATENT: EVSE-hold append dispatched stale hold SOC under standing hold (80↔45 oscillation) | fixed: append clamps to max(hold, _last_reserve_level_desired); anchored |
| (3b) | HIGH-class | Seam tests wall-clock coupled (passed AM, failed noon on identical bytes) — caught by orchestrator verification | fixed: _FrozenClock; 2000↔2100 determinism proof |
| D-MED-1 | MED | Boot HOLD-CURRENT paths bypass _result → clamp reference None on warm-up ticks (boot-only, D-HIGH-2 class) | **DEFERRED** — tracked follow-up |
| D-MED-2 | MED | Peak-hours saves persist latch w/ tomorrow's boundary; restart ≤15 min after off_peak entry can restore latch into fresh chunk (loses one night's charge; conservative direction) | **DEFERRED** — fix: persist completed:False inside reset_arbitrage_chunk |

## Statistics
CRITICAL 0 · HIGH 6 found / 6 fixed · MED 7 found / 5 fixed + 2 deferred-tracked · LOW 2 fixed.
Framing disjointness: A/B/C/D findings again near-zero overlap; D's re-enumeration produced the exhaustive dual-owner truth table (13/13 executed repros).
Process notes: one false mutation anchor (builder-claimed RED, actually GREEN) caught by C's re-execution; part-2 agent refused to fabricate a mutation table under budget pressure (No-Fabrication rule) and re-scoped correctly; wall-clock-coupled tests caught only by orchestrator's independent restore-to-green check.

## Bug-class recommendations
- New sub-pattern for QUALITY_CONTEXT: **"success-state closes the guard of the branch that owns the success"** (rung_0 satisfied BY the hold it gates) — state-machine cousin of #53.
- **Wall-clock-coupled tests**: tests that pass/fail by time of day; mitigation = frozen-clock wrapper on any decision-path test.

## Deferred ledger (Plan Completion Tracking)
- D-MED-1, D-MED-2 (above) — queue as one Tier-1/2 follow-up cycle.
- QUALITY_CONTEXT.md additions (above) — with the follow-up.
