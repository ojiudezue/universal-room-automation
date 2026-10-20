# v5.103.77: the billing cycle day setting now works

Card: EC-BILL-UTILITY-DIVERGENCE-FROM-STATS-1 (residual `residual_2026_10_20_cycle_day_dead_knob`). Tier 2, two reviews (A correctness/money math: SHIP; B async/lifecycle: FIX-REQUIRED B1, fixed). Deploy risk: LOW (billing display and bill prediction only).

## Problem

`energy_bill_cycle_day` (Coordinator Manager › Energy) was saved but never passed to the billing engine. `CostTracker` and `PeakAvoidanceTracker` were built without it (`energy.py` ~683/~697), so every install ran on the default 23rd. Found live after v5.103.76: the operator set 24 (PEC bills run 24th → 24th) and `sensor.ura_energy_coordinator_predicted_bill` still showed `cycle_start_date: 2026-09-23`.

## Fix

- Both trackers are built with the configured day, clamped to 1–28 (`clamp_bill_cycle_day`, default 23 when missing or invalid).
- Every other cycle-boundary reader (startup restore, outage days, arbitrage savings, utility divergence, the public cycle-start getter read by `hvac_override.py`, sensors, prediction) already asks the cost tracker, so it follows.
- Saving the key applies in place: added to `OPTIONS_RELOAD_SUPPRESS_KEYS` and `_EC_SETTER_DISPATCH` → `set_bill_cycle_day`. No Coordinator Manager reload.
- A mid-cycle change re-keys both trackers without zeroing, then a tracked one-shot task re-seeds the cycle totals from the DB for the new window plus today's running amounts. A second change cancels a superseded re-seed (review B B1); teardown cancels a running one (B2).
- Peak-avoidance has no daily DB history, so its running cycle total is kept as-is until the next real boundary (display only).

## Tests

- `test_ec_bill_cycle_day_wired.py`: 20 tests against the real package. Builder drills M1–M11 all RED; orchestrator drilled the B1 supersede-cancel and B2 teardown-cancel guards, both RED, tree clean.
- Four test files that keep hand-written setter/suppress stubs updated (count 111).
- Full-suite name-diff vs the v5.103.76 suite: CLEAN, 11 = 11, 0 new / 0 gone (17,774 passed).
- Test-harness fix in the same file: its real-package fixture now restores parent-package attributes exactly; before that, 19 later clock-dependent tests failed in full-suite order (patch("homeassistant.util.dt.now") hit a different module object than the code read).

## Validated 2026-10-20 (restart ~12:00 CDT)

| Criterion | Result | Evidence |
|---|---|---|
| Cycle starts on the 24th | PASS | `sensor.ura_energy_coordinator_predicted_bill` `cycle_start_date: 2026-09-24`, `days_in_cycle: 26` (was 09-23 before) |
| Running total not zeroed | PASS | predicted bill 189.92 (188.57 before the restart) |
| Load | PASS | manifest v5.103.77, 50/50 URA entries loaded, 0 URA ERRORs in the core log |
