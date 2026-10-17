# v5.103.68: EC storm Stage A — one raise-only storm floor + blind decisions (EC-INCLEMENT-HARDENING-1, Stage A)

**Tier 3.** Four framing-disjoint reviews plus an operator checkpoint (approved 2026-10-16):
- **A (local correctness):** SHIP with 4 LOWs. LOW-3 (rate-rank guard) was fixed. LOW-4 was refuted: both reads merge `{**data, **options}`, now pinned by a test.
- **B (integration / state machine):** SHIP with 2 LOWs. LOW-2 was adjudicated as not a regression.
- **C (mutation):** FIX, for 3 test gaps (C-1..C-3) plus C-4 (LOW). All closed with drilled tests.
- **D (adversarial completeness):**
  - First pass FIX for D-HIGH-1: `_get_attainability_hold_current_decision` bypassed the floor, so an EVSE overlay could emit 40 under floor 50. Fixed.
  - Re-pass SHIP with D-MED-1: an unreadable reserve on the hold-current path could lower an in-flight reserve to F. Fixed in 88dd37aa0.

Plan: `docs/planning/PLANNING_ec_storm_and_blind_decisions.md` Rev 3.4, Stage A. Reviews are in `docs/reviews/code-review/` (`ec_stage_a_review_*`).

## Problem
- Inclement holds expressed the reserve floor through several ad-hoc sites. One missed site (Bug Class #53) could let arbitrage, the EVSE overlay or a redispatch drop the reserve below the storm floor.
- When the Envoy went blind, the inclement decision stopped reasoning.

## Solution
- **One floor, raise-only (INV-1).** `determine_mode` resets `_tick_reserve_floor` at the start of each tick and registers it after both `_inclement_decision` calls (sighted and blind).
  - `_reserve_action(level)` is the only writer of `_last_reserve_level_desired`. It folds `max(level, floor)`, clamps, stamps, then applies stand-down and the ≥2 deadband.
  - The EVSE overlay and `force_redispatch` compose from that stamp, so they inherit the floor.
  - The two non-`_result` returns (blind dict, hold-current dict) route through it too.
- **Blind decisions.** With the Envoy blind, URA keeps holding or releasing per the plan's rules. The full-hold floor is the new `InclementBlindFullHoldFloorNumber` (default 60), read from options with no setter. `BLIND_RESPECT_MANUAL_LOWER=False`.
- **TOU rank helpers** in `energy_tou.py`: `rate_rank`, `is_top_rate`, `is_bottom_rate` and `period_rank`, with guards for unknown periods and non-numeric rates. Off-peak clamps are re-keyed on the registered floor.
- **No floor = no change (INV-2).** A golden of 210 no-floor cases, captured on a pre-Stage-A commit, is byte-identical.

## Known limits
- No grid buying: Stage A only stops discharge below the floor. Pre-charge, matching and the forecast check are Stages B+C, built together.
- `BLIND_RESPECT_MANUAL_LOWER` has two must-fix defects (plan §7) and must not be enabled before they are fixed.
- The hold-current return does not refresh `_desired_stamped_at`; this predates Stage A. The re-pass confirmed it can only suppress a write, never lower one.
- With SOC unknown on a sighted tick, a full hold uses the slider value (60) instead of 100 (plan §6).

## Tests
- New: `test_ec_stage_a_noop_golden.py` (210 cases), `test_ec_stage_a_tou_rank.py`, `test_ec_stage_a_floor_and_blind.py`, `test_ec_stage_a_blind_floor_slider.py`. 292 pass.
- Mutation-drilled on 13 load-bearing sites, each with a named test going RED. The orchestrator independently neutered the floor fold: 8 tests failed, and all passed again on restore.
- Full suite: 119 failed / 15460 passed / 3 errors, with 0 new failures by name-diff against the v5.103.66 baseline.

## Live validation (prospective)
- **Live:** with no inclement alert, `ura_activity_log` `reserve_write` rows have `inclement_floor=null`, and reserve values and reasons match the pre-restart pattern.
- **Live:** `number.*inclement_blind_full_hold_floor*` exists with value 60.
- **Live:** 0 URA ERRORs mentioning `_reserve_action`, `tick_reserve_floor` or `rate_rank` after restart.
- **Live (event-gated, not watched):** the first inclement hold writes `reserve_write` rows with a non-null `inclement_floor`, a non-null `floor_ok`, and `value >= inclement_floor`.
