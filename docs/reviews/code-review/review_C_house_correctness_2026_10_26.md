# Review C (test authority, real per-site mutation) - house correctness branches, 2026-10-26

Base 95c9e4449. Method: detached worktree per branch, one production-source mutation at a time, branch test files only, bytecode cleared, restored in try/finally, `git status` clean after each branch. Drivers were run serially.

## fix/house-energy-correctness (6597e4cbc) - 21 mutations, 18 RED, 3 GREEN
All RED rows fail a specific test in `test_house_energy_correctness.py` (ec_tou delivery skip, 4 predicted-cost sensors individually, WholeHouseCost reads `ec.cost_today`, similar-days today exclusion, week/month offsets, clamp (upper), min/max plausible, restore+record `pct_error_factor`, `<3 usable`, None filter).
GREEN survivors:
- E7c LOW: lower clamp `-FACTOR_PCT_ERROR_CLAMP` removed - no negative-side clamp test (only upper tested).
- E13 LOW: `usable[-7:]` window removed - no test with >7 usable samples.
- E3b / E9b: equivalent (ec None falls to caught AttributeError -> None; None guard hits TypeError path not reachable by callers). No action.

## fix/house-diagnostics-correctness (58cbfa70c) - 23 mutations, 19 RED, 4 GREEN
RED: expected-on capture/gate/vote, min-samples, sigma term + constant, threshold, ETA entry-keying/elapsed/subtract/filter/time_bin, safety count (missing state, unavailable, numeric loop), diagnostics status, sensor attribute.
GREEN survivors:
- R4 LOW: `day_type` keyed on now instead of entry time - test does not separate weekday/weekend (time_bin is covered).
- R8 LOW: `max(0.0, ...)` clamp on elapsed (future-dated entry) untested.
- R9 LOW: `except Exception` fallback on elapsed untested.
- D7: equivalent (`expected_on_at_drop` init is overwritten at drop before use).

## fix/scanner-areas-own-area (5b8a33bc7) - 10 mutations, 8 RED, 2 GREEN
RED: core filter, initial-flow call + area source, options-save call + area source, options-form default + area source, person_coordinator filter.
GREEN survivors: C1b LOW (`strip_own_area` with empty area_id returns [] instead of list unchanged - untested); P1b equivalent.

### Non-mutation finding (HIGH-ish, regression, no test anchors it)
`config_flow.py:1181` - `@instrument_flow` now sits above the new `strip_own_area()` function (blank line + def inserted between decorator and class). The ConfigFlow class lost its decorator: runtime check shows `UniversalRoomAutomationConfigFlow._cflow_timing_instrumented == False` while `strip_own_area` is "instrumented (0 step handlers)". `CONFIG_FLOW_TIMING` defaults True, so initial config-flow step timing is silently dropped. Fix: move `strip_own_area` above the decorator (or re-attach `@instrument_flow` to the class). Bug class: decorator-binding drift / hollow coverage (#62 adjacent).

## Verdict
Energy and diagnostics: SHIP with LOW test gaps (fold in-cycle per fix-LOWs rule). Scanner: FIX-REQUIRED (decorator misplacement).
