# Code Review — Whole-House + Room Power Unit Normalization

**Branch:** `feature/whole-house-power-units` (026912b build → 5a20bfe fix-up)
**Protocol:** Operator-elevated Tier 2-DB (STATE_POWER_CURRENT is a shared primitive: RoomPowerProfile, waste-idle, zone power, cost/hour) — 3 framing-disjoint reviews.
**Trigger:** 2026-06-09 SPAN audit: `whole_house_power` = 0.29 W at ~2.7 kW actual (Envoy kW read raw). Bug Class #30 recurrence on the power device class.
**Date:** 2026-06-10

## Findings ledger

| ID | Sev | Finding | Status |
|---|---|---|---|
| B-HIGH | HIGH | `mW`/`MW` differ only by case — lowercase collapse inflated milliwatt sources 10⁹×; energy sibling had latent `mWh`/`MWh` twin | FIXED (5a20bfe) — exact-case M/m matching in both helpers, ambiguous casings refused + debug-logged; 7 tests |
| C1 | HIGH | `WholeHouseCostTodaySensor._sum_energy_sensors` raw-summed the same config key its normalized sibling reads → Wh source = correct energy, 1000× cost | FIXED — normalized via `energy_state_to_kwh`; call-site + no-raw-read test |
| A-M1 | MEDIUM | No isfinite guard — literal "nan"/"inf" states poison sums sticky-forever (both helpers) | FIXED — non-finite → None; tests |
| A-M2 | MEDIUM | Refused uoms dropped silently (behavior change vs pre-fix raw contribution) | FIXED — debug log with entity hint |
| B-M1 | MEDIUM | Persisted RoomPowerProfile baselines from previously-misread kW rooms may fire EnergyAnomaly until EMA converges (~7 samples/cell) | ACCEPTED — Review-D expectation note (no such kW room sensors known live; Envoy was whole-house only) |
| B-M2 | MEDIUM | `any_valid` drift: all-unrecognized-uom whole-house list now → None (was raw garbage number) | ACCEPTED — None is the honest value; Review-D note |
| C2 | MEDIUM | Plumbing test satisfied by bare substring | FIXED — asserts call sites |
| A-L1 | LOW | Helper is now a 3rd normalization semantics vs 5 hand-rolled sites | DEFERRED — consolidation hygiene pass (already noted in _units.py docstring) |
| A-L2 | LOW | Test gaps (negative, NaN, mixed-case, whitespace) | FIXED — 12 tests added |
| A-L3 / C3 / C4 / B-LOW | LOW | Dead defensive wrappers; sum test drives helper not sensor; relaxed import assertion bounded; waste-idle step change is correct behavior | ACCEPTED — documented |

**Cleared by review:** None-propagation to trapezoid/EMA (new loop preserves default-0 semantics); double-normalization (zone/cost read coordinator data, not re-read states); no downstream threshold calibrated against the broken 0.29 W value (load shedding uses the separate, already-normalized Envoy CT path).

## Statistics

| Severity | Found | Fixed | Accepted/Deferred |
|---|---|---|---|
| HIGH | 2 | 2 | 0 |
| MEDIUM | 5 | 3 | 2 (Review-D notes) |
| LOW | 6 | 1 | 5 |

Suite: 5488 passed / 44 failed / 14 errors / 29 skipped — +29 cycle tests across both commits, zero new failures.

## QUALITY_CONTEXT recommendation

Extend Bug Class #30 with the **case-significant SI prefix** trap: `m` (milli) vs
`M` (mega) collide under lowercase collapse for W/Wh; any uom normalizer must
match the M/m prefix exact-case and refuse ambiguous casings.
