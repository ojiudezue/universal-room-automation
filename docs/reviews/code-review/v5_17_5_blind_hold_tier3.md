# Review record — v5.17.5: blind-hold total contract (Tier-3-grade, 3 framings + D completeness)

**Incidents driving it (both 2026-07-15, both live):** (1) 16:00 — blind-hold froze attain's active grid import into peak (SOC available via cloud fallback the whole time; control is cloud-leg); (2) 18:31 — with desire-stamps frozen stale, the reversion sweep self-healed the operator's manual de-escalation back to reserve 80, forcing a coordinator disable to win.
**Invariants:** I-BH1 (never continue an import into higher rate blind; blind-hold only when NO tier has fresh SOC) · I-BH2 (no FRESH grid-charge entry while degraded; breaker fails closed on unreadable import) · I-D3 (sweep never re-dispatches from stale desire — blind means no decisions AND no re-assertions).
**Series:** 5dd4c578 (gate relax + peak de-escalation) · 0bf0b84d (B-CRIT-1/2: entry guard + breaker fail-closed) · 51fb1884 (D3 sweep freshness + A1 cloud-SOC staleness + A2 full_hold freshness + C-MED-1 ledger leg) · 7af863d4 (D-HIGH-1 guard hoist above grace tick + D-MED-1 no ON-heal while degraded + D-HIGH-2 stub).

## Findings ledger
| ID | Sev | Finding | Outcome |
|---|---|---|---|
| B-CRIT-1 | CRITICAL | relaxed gate let mid_peak attain START a fresh grid import on fallback-only SOC (executed repro) | fixed: degraded entry guard (attain + off_peak arbitrage), mutation-anchored |
| B-CRIT-2 | CRITICAL | breaker guard no-trips blind (docstring assumed removed branch) | fixed: fail-closed, LKG-pattern reuse |
| D3 (live) | HIGH-class | sweep self-heals stale intent while blind (fought operator at 18:31) | fixed: desire freshness gate + post-boot stand-down; orchestrator-executed mutation RED×2 |
| D-HIGH-1 | HIGH | import-guard grace tick returned CHARGE before the new guards (fired exactly when import over cap) | fixed: guards hoisted |
| D-HIGH-2 | HIGH | inclement full_hold precharge can START while degraded | DECISION PENDING (operator: exempt-bounded vs strict); disabled stub + 1-line wire-up committed; today = v5.5.0 status quo; D's repro shape already blocked by A2 freshness |
| D-MED-1 | MED | latched-CHARGING ON-heal could re-start a physically-off import blind | fixed: ON-heal suppressed while degraded; sighted heal anchored unchanged |
| A1 | MED | cloud-fallback SOC tier had no staleness gate | fixed (age gate, stale→None→blind-hold) |
| C-MED-1 | MED | de-escalation ledger leg was a green mutation survivor | test added |
| A2/B-HIGH-1/C-LOW-1 | LOW | full_hold freshness / stale comment / int cast | fixed/fixed/noted |

## Proof state
- 15 executed mutations RED across the series (builder) + 1 independently re-executed by orchestrator (D3 gate — RED×2, byte-identical restore).
- Framing-D's 3 leak repros re-run against HEAD by orchestrator: 3/3 pass (leaks dead).
- Suites: battery 166/166, write-verify 83/83; full-suite failing set = baseline (the +1 deploy-script timeout passes in isolation — load transient).
- Enumeration table (D) covers every CFG-ON emitter, reserve emitter, sweep path, and degraded-proceed path incl. EVSE force-charge, reboot recovery, HOLD-CURRENT.

## Deferred
- D-HIGH-2 wire-up on operator decision (recommendation on record: exempt-bounded — A2-fresh full_hold + fallback-SOC-present required).
- Framing-D notes EVSE overlay may max() the de-escalation reserve back up (CFG off still lands — note only).
