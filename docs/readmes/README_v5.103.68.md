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

## Validated 2026-10-21

| Criterion | Result | Evidence |
|---|---|---|
| With no inclement alert, `reserve_write` rows have `inclement_floor=null`; values and reasons match the pre-restart pattern | PASS | `ura_activity_log` `reserve_write`: 145 rows 2026-10-16 to 10-21 (1/20/0/39/80/5 per day on 10-16, 17, 18, 19, 20, 21), `json_extract(details_json,'$.inclement_floor')` is NULL for 145 of 145, `tick_floor` NULL for all. Reasons are the normal strategy text, for example id 317936 (2026-10-21 23:25:49Z) "Mid-peak (shoulder) - discharging ... (degraded telemetry: lkg)", id 317274 "Off-peak hold - SOC 8.0% <= target 10%". |
| `number.*inclement_blind_full_hold_floor*` exists with value 60 | PASS | `number.ura_energy_coordinator_inclement_blind_full_hold_floor` = 60 (last_updated 2026-10-21 18:25:37); entity registry `disabled_by: None` |
| 0 URA ERRORs mentioning `_reserve_action`, `tick_reserve_floor`, `rate_rank` | NOT-YET-EVALUABLE | log-read gap. Proxy: `reserve_write` rows keep landing after the restart (latest 2026-10-21T23:25:49Z), so `_reserve_action` is executing; this does not prove the absence of ERRORs. |
| Event-gated: first inclement hold writes `reserve_write` with non-null `inclement_floor`, non-null `floor_ok`, `value >= inclement_floor` | NOT-YET-EVALUABLE (event-gated) | 0 rows with a non-null `inclement_floor` since the ship. Discriminator for later: `select ... from ura_activity_log where action='reserve_write' and json_extract(details_json,'$.inclement_floor') is not null` and check `value >= inclement_floor` and `floor_ok` not null. Per the Soak Exit rule this should carry a revival trigger (first inclement hold), not ride organic. |

---

_Log-scan criteria are NOT-YET-EVALUABLE (no log access from the probe); source: docs/planning/AUDIT_readme_straggler_validation_2026_10_21.md._
