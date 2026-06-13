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

## Live Validation — Validated 2026-06-12/13

Deployed 2026-06-12 19:46 CDT (restart landed post-peak). Validated against the restarted instance:

| Criterion | Result | Evidence |
|---|---|---|
| Clean restart, zero URA ERRORs, 40/40 entries, EC producing | PASS | 40/40 loaded post-restart; battery-strategy sensor producing within one cycle; zero URA ERROR lines (only non-URA proxy/frontend noise) across the boot + overnight window |
| `attain` attrs render on battery-strategy sensor | PASS | `attain_state`, `attain_projected_soc_at_boundary`, `attain_solar_term_pct` present; 19:56 CDT showed `attain_state: inactive` (peak discharge from the 43% manual buffer — correct) |
| Hardware-derived reboot recovery (cfg OFF → clean defer) | PASS | charge_from_grid was OFF at boot → no spurious commands; no restore-poisoning recurrence |
| Attain ENTRY (the defining scenario) | **NOT YET EXERCISED** | 2026-06-13 ~08:00 window: today `target_day=excellent` but `d2_class=poor` → the *regular* arbitrage gate opened via the multi-day-horizon branch, so arbitrage CHARGE pre-filled to 80% and attain correctly stayed `inactive` (arbitrage takes precedence when gate open). Attain's scenario (gate CLOSED + solar underperforms) needs a day where neither today nor d2 is poor/very_poor — pending real conditions. The mechanism is mutation-anchored in-suite (7 mutations; deleting the solar term or zeroing HOLD reserve fails named tests). |
| HOLD reserve pin / mid_peak continuation / load-shed exclusion | IN-SUITE | Could not be live-exercised this window (attain never entered); covered by mutation-anchored tests. |
| Good-delivering morning: attain does NOT enter (as_local fix) | PARTIAL | Attain stayed inactive on an excellent-solar morning as expected — but via the arbitrage-gate-precedence path, not the solar-term path, so the as_local fix specifically remains in-suite-only. |

**Note for next session:** the 2026-06-13 morning surfaced a related finding (task #16) — on an excellent-solar day arbitrage intervened (and paused EVs) even though solar would fill the battery free; the inverse of attain. Tracked separately.

*This README is the durable validation ledger per the write-back rule; attain-entry remains pending real conditions — re-validate when a gate-closed-and-solar-underperforms day occurs.*
