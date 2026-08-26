# Code Review — HVAC Excursion-Restore Unified (Tier 3, 4 framing-disjoint)

Branch: feature/hvac-excursion-restore @ da3ec8237. Baseline: pre-review-hvac-excursion-restore.
Reviewers: A (local-correctness), B (async/lifecycle/race), C (test-authority via mutation), D (adversarial completeness).
**Verdict: FIX-REQUIRED (all four).** Not shipped.

## Convergence — the load-bearing defects
| Defect | A | B | C | D | Sev |
|---|---|---|---|---|---|
| S14 orphans _off_phase_ceiling_tokens after lease-expiry sweep -> per-tick ungoverned rewrite / D3-ON flap | A-HIGH-2 | B2 | C-5 | D-CRIT-2 | **CRIT** (3-way) |
| D4 one-shot anti-flap guard is dead code (add cleared same block) | A-CRIT-1 | B5 | C-5 | D-CRIT-3 | **CRIT** (3-way) |
| D2 AST governance gate is HOLLOW — governs 1/11 writers; whitelist module-agnostic; invalidates D3-ON interlock | — | — | C-1 | D-CRIT-1 | **CRIT** |
| Discharge uses async_create_task, NO await before begin_excursion (mechanism of orphan) | — | B1 | — | — | HIGH |
| S14 hand-rolls release, bypasses auto_release_on_incomplete CM (restore_ok None vs False; exception leak) | A-HIGH-3 | — | — | — | HIGH |
| S9 async_startup_ramp_audit = LIVE ungoverned writer every boot; D3 stomps after 5s arrester TTL | — | — | — | D-HIGH-1 | HIGH |
| S10/DPM ungoverned; Auto-Adjust ON + D3 ON = per-tick fight | — | — | — | D-HIGH-2 | HIGH |
| Cross-kind collision: NUDGE borrow live -> S14 emits ungoverned; kill-switch OFF + D3 ON = guaranteed flap | — | — | — | D-HIGH-3 | HIGH |
| Sweep re-entrancy: slow (>60s Carrier) emit -> sweep N+1 double wire preset write | — | B3 | — | — | HIGH |
| D3 recovery consumer + kill-switch UNTESTED both positions (Bug#53) | — | — | C-3 | (noted) | HIGH |
| OVERRIDE_NORMAL_DELTA borrowed bare -> misclassifies operator nudge under coast -> silent disarm no restore | A-MED-4 | — | — | — | HIGH |
| wrote_setpoint_high not persisted in to_row(); None after generic rehydrate; hollow test anchor | A-MED-5 | — | C-6 | — | MED |
| Untracked background tasks (2 async_create_task not stored/cancelled) | — | B4 | — | (noted) | MED |
| D1 sweep wire-in untested (deleting async_track_time_interval reg -> GREEN) | — | — | C-8 | — | MED |
| 8 named D3/D4 acceptance tests ABSENT; follow-on cards never filed; superseded test not inverted | — | — | C-3/5 | D | MED |
| HIGH-1 pre_preset skip tests non-discriminating (shared observation both mechanisms) | — | — | C-4 | — | MED |

## Cleared (converged)
- D3 OFF-path byte-identity HOLDS (B, D-Inv3, C-4a/4b): short-circuit at hvac.py:2118, nothing hoisted, no mutation/emit.
- D3 switch RestoreEntity: no unavailable->OFF poisoning, defaults OFF (B).
- Sweep timer teardown (unsub in _unsub_listeners) HOLDS (B); _returned double-return guard HOLDS (A,B,D).
- has_live_row kind-agnostic + stranded bound + release-predicate consistency HOLD and are TESTED (A truth-table, C RED-on-neuter).
- D1 stale-boot BANKING release TESTED (C: RED on neuter) — genuinely fixes measured "2 open/0 ended banking".
- OVERRIDE_NORMAL_DELTA substitution rationale ACCEPTED in kind (plan's SETPOINT_ECHO_TOLERANCE doesn't exist) — but needs its own named const (A-MED-4).

## Layer risk assessment (for descope decision)
- D1 (auto-release sweep + stale-boot BANKING): helper layer well-tested, real measured driver, SEPARABLE. Needs: sweep re-entrancy guard (B3), untracked-task fix (B4), wire-in test (C-8). If D4/S14 parked, the orphan interaction (D-CRIT-2) disappears — sweep then only closes banking tokens.
- D4 (S14 off-phase ceiling): where ALL 3 CRITICALs + most HIGHs concentrate. Orphan, dead one-shot, cross-kind collision, async discharge, CM bypass, zero end-to-end tests. Needs real rework.
- D2+D3 (AST gate + recovery + interlock): gate hollow, consumer untested, D3-ON ungoverned-writer hazards (S9/S10). D3 ships OFF so not live, but the gate/interlock design must be fixed before D3 can ever flip ON.

## Baseline note (C)
Branch in-slice: 336 passed / 0 failed. Builder's "9 pre-existing offphase ImportError failures" DO NOT reproduce — do not carry forward. Full suite 61 failed all pre-existing/out-of-cycle.
