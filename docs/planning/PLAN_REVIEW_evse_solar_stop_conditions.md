# Plan Review — EVSE solar-session stop conditions (Tier 3, 2 framing-disjoint reviews)

Reviewed: 2026-08-26. Plan: `PLANNING_evse_solar_stop_conditions.md`. Both reviews vs `develop`.
**Verdict: FIX-PLAN-FIRST (both).** Build must NOT be dispatched until the plan is reworked and re-reviewed.

## Mechanism ground truth (orchestrator-verified)
Plan §0b:62-64 DISCARDS from `_excess_solar_active` + ADDS to a separate `_solar_follow_suppressed`
set + gates the claim leg on the suppressed set. This is NOT the operator's literal (b) ("keep in
the active set, mark suppressed") — it is a discard-and-move refinement that avoids (b)'s
consumer-incoherence but introduces its own (11+ consumers of the active set change behavior when a
bay is discarded). Plan-review 1 (completeness) read this correctly; plan-review 2 (build-prediction)
misread it as keep-membership. The two reviewers reading the core mechanism oppositely is itself a
build-blocking ambiguity.

## Converged must-fixes (both reviews)
- Timeout backstop reads `stamped_monotonic` the ledger never writes → INV-STOP-3 unreachable / stuck-off. (C4 = B2)
- No power-sensor-health gate → degraded sensor turns off a charging car + 2h suppress. (C7 = B7)
- `SOLAR_MIN_ON_S` (carded rung-1 knob) silently dropped → same-tick claim→stop, J1772 handshake stopped. (C8 = B6)
- SOC hysteresis pair dropped, neither built nor non-goal (number.py ordering unenforced → defensive min()+warning). (C15 = B10)
- No real test deliverable / D7 points at a nonexistent section. (B9; C-implied)
- Byte-identity proof uses hard-coded line ranges that shift on insert + HEAD~1 not merge-base. (C10 = B8)
- disjointness / "unknown" status behavior undefined. (B11; C-adjacent)

## Plan-review 1 (COMPLETENESS) unique — 3 CRIT + structural
- C1 CRIT: plan deviates from operator's chosen mechanism (b) without declaring it. NEEDS OPERATOR RE-CONFIRM.
- C2 CRIT: the card's MANDATED central task — per-consumer enumeration of _excess_solar_active — is ABSENT. 11 read sites unmentioned, several behavior-changing under discard: energy_pool.py:909 (TOU peak-pause skip -> stopped bay becomes TOU-pausable), :2217 (fill-priority), :2553-4 (sensor attrs), :2646-58 + owners:245-51 (classifier_priority=7 -> stopped bay reports bare "off", loses stop reason), energy.py:1656/1941/5402/5415-45, energy_pool.py:3889/4077/4304.
- C3 CRIT: scope fence FALSE — SolarFollowController (energy_pool.py:3717) reads _excess_solar_active at :3889/:4077/:4304; discard triggers amp _restore_pass write to a charger URA turns off same tick. INV-STOP-6 coupling claim false.
- C5 HIGH: "no other module writes this set" refuted — energy.py:1467-8 DB-restore add site.
- C6 HIGH: FOUR returns in determine_excess_solar_actions (:1377/:1533/:1575/:1704) not one -> no stop can fire in a blind window.
- C11 MED: _stop_reason_ledger + _solar_follow_no_draw_since are per-EVSE dicts outside iter_prune_dicts -> leak removed EVSE ids forever (inherited finding 6 handled only for the set).
- C12 MED: _proactive_offpeak_holds not cleared on stop -> stopped bay still reports "off-peak proactive turn-on". Bug#53.
- C13 MED: discard enumeration 3-4 not the 5 the card demanded (missing prune set-pass :790-793).
- C14 MED: AUDIT_excess_solar_and_evse_prior_art.md not cited (has the exact coupling walkthrough + self_modulates dormant flag warning).
- C9 MED: (a)'s named hazard survives under (b) label — no-draw-suppressed bay released by drain can't re-claim until replug/2h.
- C16-C19 LOW: INV-STOP-2/5 not falsifiable; SOLAR_STOP_* vs SOLAR_FOLLOW_* naming; get_status dedup sig; golden regen hard-coded attr list.
- Handled correctly: INV-STOP-2 rescoped; stamped-dict not last_changed; golden-freeze acknowledged (load_shed precedent); cessation ledger; probe-first; classifier_priority=None.

## Plan-review 2 (BUILD-PREDICTION) — see scratch consolidation (B1-B13, 3 CRIT: oscillator-in-text, stamped_monotonic, missing-stamp stuck-off).

## Disposition
Plan needs a substantial rework (~12+ must-fixes). C1 mechanism deviation needs operator re-confirm
BEFORE the rework picks its basis. Build remains gated behind operator go + HVAC-excursion landing.
