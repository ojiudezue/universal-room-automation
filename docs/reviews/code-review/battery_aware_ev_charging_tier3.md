# Battery-Aware EV Charging (EVSE drain-precedence) — Tier-3 Review Record

**Cycle:** build A → B1 → B2a → B2b-i/ii/iii (merged 57d92fea) + fix-ups B2c-1 (8f2bfc9e), B2c-2 (447daf84), B2c-3 (b48addf0).
**Tier:** 3 (threads the reserve floor through a shared primitive with many emission sites; cost-AND-liveness impacting; Bug Class #53 territory).
**Protocol:** 4 framing-disjoint reviews (A local correctness / B integration-state-machine / C mutation-executed test authority / D adversarial completeness) + D re-pass after each substantive fix-up + orchestrator independent mutation verification.
**Final verdict:** SHIP (D-final, post fix-up 3). `CONF_DP_ENABLE` ships OFF.

## Findings ledger

| ID | Sev | Finding (bug class) | Found by | Fixed in |
|---|---|---|---|---|
| CRIT-1 | CRITICAL | Reversion-oscillation: exit condition "charging stopped" is self-triggered by DP's own pause → pause/revert loop every tick (v5.15.0 flap shape) | B + D independently | 8f2bfc9e (paused-aware exit: revert on car-stopped-while-POWERED) |
| CRIT-2 | CRITICAL | Second plug-in mid-TRANSITIONED never paused — L2 auto-activates, battery drains into car B all window (INV-DP1 breach) | D | 8f2bfc9e (charging-set re-scan while TRANSITIONED) |
| H-1a | HIGH | Blind-hold gate read a nonexistent attribute (invented-attribute getattr — 3rd cycle running) | B | 8f2bfc9e (real signal) |
| H-2a | HIGH | `house_load_kw` stubbed 0.0 — lost in slice hand-off (B2b-ii deferred to B2b-iii; brief dropped it) | B + D | 8f2bfc9e (live wiring) |
| H-3a | HIGH | Kill-switch OFF mid-transition strands the pause (gate stops the cleanup tick) | D | 8f2bfc9e (kill-switch hoist, runs unconditionally first) |
| H-4a | HIGH | No night-window gate — morning plug-in could release reserve through peak | D | 8f2bfc9e |
| H-5a | HIGH | New test wall-clock-coupled | A | 447daf84 (frozen-time refactor) |
| M-1..6 | MED | needed_kwh summed both chargers unconditionally; restored-TRANSITIONED pointless (empty-set reversion); tautological ships-OFF test; TRANSITIONED edge never proved real EVSE ids paused; + cosmetics | A/C/D | 447daf84 |
| D2-H1 | HIGH | `_paused_by_dp` not persisted (siblings all are) + restore-to-HOLD_ONLY ⇒ restart mid-TRANSITIONED orphans a physically-off EVSE, no owner, no reversion (INV-DP2) — pre-existing-pattern gap, diff-blind find | D re-pass; orchestrator-verified vs source | b48addf0 (`evse_dp_paused` KV + owner reclaim + HOLD_ONLY orphan retry driver) |
| D2-H2 | HIGH | Reversion not sticky: membership + "dp" owner dropped BEFORE peer/TOU defer checks → deferred member stranded off with zero owner (docstring claimed v5.15.0 sticky parity; code wasn't) | D re-pass; orchestrator-verified vs source | b48addf0 (defer checks precede mutation; sticky keep; floor collapses only on full drain) |
| D2-M1 | MED | Plugged-idle car (car-side scheduling) contributes 0 to needed_kwh | D re-pass | ACCEPTED GAP (no trustworthy plugged signal across EVSE integrations; must-start-by is the liveness backstop; documented in docstring) |
| D3-L1 | LOW | Indefinite peer-hold keeps `_dp_decision_soc` pinned → floor stays raised (max() contributor, cannot demote; sub-dollar bound) | D final | Accepted (architecturally correct-conservative) |

**Stats:** 2 CRITICAL found/fixed · 7 HIGH found/fixed · 7 MED (6 fixed, 1 accepted-documented) · 1 LOW accepted.

## What survived falsification
- INV-DP1 (both released at floor, incl. late joiners post-fix), INV-DP3 (floor-composition supremacy), INV-DP4 (eval gate order), INV-DP5 (write-verify stamps both legs).
- All 17 builder mutation anchors held under C's re-execution — every defect lived in the wiring seams BETWEEN anchored sites.
- Restore drops the transition rather than resurrecting half-actuated state; 10h-staleness edge resolved by pre-existing `_ev_tou_ensure_on` (energy_pool.py:582), not stranding.
- Retry drivers mutually exclusive on `_dp_on`; reversion idempotent; no double-turn_on race (D-final trace).

## Orchestrator independent verification (mandatory Tier-3)
- Both D re-pass HIGHs re-verified against source BEFORE dispatching the fix (reviewer's tool trail was thin — verification confirmed both real at energy.py:3809-3833 / 1657-1706).
- Real source mutation 1 (sticky → eager discard): 3 specific tests RED. Mutation 2 (drop `evse_dp_paused` save): 2 specific tests RED. Both restored; 312/3 green; tree clean vs b48addf0.

## Bug-class notes for QUALITY_CONTEXT
- Invented-attribute getattr: THIRD cycle running — promote to numbered class.
- Tautological/self-referential test anchor: recurred (ships-OFF default).
- NEW candidate: **slice-seam hand-off drop** — "next slice wires X" markers must be explicitly carried in the next slice's brief (house_load stub).
- NEW candidate: **docstring-claimed-parity-not-implemented** — a docstring citing an established pattern (v5.15.0 sticky) is not evidence the code implements it; reviewers must diff behavior, not prose.

## Naming (operator-ratified 2026-07-17, c27df04c)
Switch friendly name "Battery-Aware EV Charging" (Aware over First — describes the eval, not a fixed priority); sensor "EV Charging Plan"; internals stay `dp_*`. Kill-switch retirement trigger documented in plan.

## Test counts
EVSE filter: 291 (post fix-up 1) → 304 (fix-up 2) → 312 (fix-up 3), 3 skipped. Full suite improved net −8 failures across fix-ups; residual failures = pre-existing unrelated baseline set.
