# URA v5.5.3 — Arbitrage/attain partial_hold reserve-floor completeness (Tier 3)

Closes the v5.5.0 follow-up: an inclement `partial_hold` raises the effective reserve floor (default 50%), but the off_peak **arbitrage** and **attain** paths emitted `reserve_level` without consulting it — so during a partial_hold with the arbitrage gate open + an overnight watch, the battery could drain/hold below the storm floor. v5.5.0 clamped only the off_peak drain-target fallback; arbitrage/attain short-circuited past it.

**First cycle reviewed under the new Tier 3 protocol** (four framing-disjoint reviews; CLAUDE.md). The 4th adversarial-completeness pass earned the tier on day one.

## What ships
A new `_floor_reserve(existing, effective_reserve, hold_depth)` helper (`energy_battery.py:1457`) clamps every reserve emission to `max(existing, effective_reserve)` **only under an active partial_hold** — byte-identical otherwise. `determine_mode` threads `effective_reserve` + `decision.hold_depth` into `_get_arbitrage_decision` and `_run_attain_branch` (which forwards to its sub-decisions).

**Sites floored (7 total):** arbitrage HOLD/CHARGE/WAIT, attain CHARGE/HOLD, reboot-recovery release, **and the summer mid_peak peak-ahead hold** (the 7th, found by the Tier-3 completeness reviewer — a latent v5.5.0 gap). Of these, only the `reserve_soc`/`int(soc)` sites change under a partial_hold; the `peak_buffer_target` (80%) sites are no-ops under the 50% floor but are threaded defensively. Charge is never suppressed (the CHARGE→HOLD transition reads `peak_buffer_target`, not the clamped reserve).

**Net invariant (now holds):** under an inclement `partial_hold`, the battery cannot hold/drain below the effective reserve floor in **any** off_peak or mid_peak path.

## Review (Tier 3 — four framing-disjoint)
- **A (clamp arithmetic):** SHIP — `_floor_reserve` correct, all sites route through it, byte-identical when not partial_hold.
- **B (state machine / charge-not-suppressed / C2-CRIT-1):** SHIP — clamp only raises; phase transitions read the target, not the reserve.
- **C (test authority):** APPROVE — **real per-site source mutation** (bypass one clamp at a time) confirmed every site is individually test-covered.
- **D (adversarial completeness):** found **D-HIGH-1** — the 7th unclamped site (mid_peak summer hold, latent v5.5.0 gap), with a legal-config repro (`target=30, floor=60, soc=45 → reserve 45`). Fixed + mutation-tested. Orchestrator independently re-enumerated all 16 emission lines + re-ran the mutation (`2 failed` on bypass).

Ledger: `docs/reviews/code-review/v5.5.3_arbwait_summary.md` (+ reviews A/B/C/D).

## Live Validation — PROSPECTIVE
| # | Criterion | How to verify |
|---|---|---|
| L1 | Deploy healthy | v5.5.3 HACS-installed, config loaded, zero new URA ERRORs |
| L2 | Byte-identical no-alert behavior | With no active inclement alert (allow_discharge), off_peak/mid_peak battery behavior is unchanged from v5.5.2 — normal drain/arbitrage, no spurious reserve elevation. `inclement_reserve_floor == reserve_soc`. |
| L3 | Floor honored under partial_hold | (In-suite authoritative — requires an uncorroborated watch + arbitrage gate open, rare live.) Mutation-anchored across all 7 sites. If a partial_hold ever fires off_peak/mid_peak, recorder shows reserve ≥ floor. |
| L4 | No regression | 24h `battery_mode` history: no unexpected `backup`, no skipped peak discharge on clear days. |
