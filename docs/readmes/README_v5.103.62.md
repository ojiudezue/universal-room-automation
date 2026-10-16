# URA v5.103.62: Custom Preset Ranges waits for a preset change to settle; failures no longer creep to the latch

Card: HVAC-S10-STALE-RANGE-AFTER-PRESET-CHANGE-1. Plan: `docs/planning/PLANNING_hvac_s10_stale_range.md` Rev 3 (plan reviews: Rev 1 FIX-REQUIRED, Rev 2 FIX-REQUIRED, Rev 3 orchestrator-verified; `docs/reviews/code-review/plan_hvac_s10_review.md`). Tier 2-DB (operator-elevated): reviews A (correctness), B (lifecycle / zone 1-2 rollout), C (per-site mutation), each FIX-REQUIRED and fixed; record `docs/reviews/code-review/v5.103.62_hvac_s10.md`. Deploy risk: **LOW-MEDIUM** (HVAC Custom Preset Ranges only; only zone_3 is in rollout).

## Why
- The card's premise (one redundant write per preset change) was refuted: an existing 120 s same-tick gate already prevents it.
- The real problem (measured 2026-10-15): on 10-14 a zone_3 S10 write 299 s after a preset change was rejected locally while the thermostat still reported the previous preset's setpoints for 422 s. That was 1 of 544 zone_3 preset changes since 10-01. Rejections count toward the 3-strike apply latch and were never reset (zone_3 away = 1/3). A first visit inside such a window could also save the wrong "original" range — reachable once zones 1 and 2 roll out (operator: "we need to add those zones soon").

## What changed
- **Settle gate:** `ZoneState` records the last observed preset change (any writer: S1, arrester, AC reset, a person, the Bryant schedule). For `S10_POST_PRESET_CHANGE_SETTLE_S` = 600 s after one, S10 skips apply, restore and original-snapshot capture (skip step `post_preset_change_settle`, ahead of `s1_same_tick`). Effective delay after a change is ~15-20 min. The first readable observation after boot seeds without stamping; `""` / `unknown` are ignored; Carrier `hold_activity = None` (no hold) is a readable value; ecobee/Generic (no attribute) are unaffected.
- **Failure reset:** a confirmed success (already-correct, or matching view at the write limit) resets the apply-failure count and is saved. A plain APPLIED does not (ruling A4).
- **Held trip-wire:** a zone held continuously for `S10_SETTLE_HELD_WARN_S` = 4 h (zone 1's feed split can do this) sends one HIGH notification per zone per local day (reaches the companion app) and shows `s10_settle_held_s` in the Active Preset Overrides diagnostics. Zones removed from rollout that still hold saved originals are covered too.
- Known residual: the stamps are RAM-only, so a restart within ~10 min of a preset change can let the first pass after boot read stale setpoints.
- State-of-play doc corrected in the same cycle (C37 Custom Preset Ranges live on zone_3; C38; §9.9 renumber; ship versions for stale "not deployed" labels).

## Tests
- `quality/tests/test_s10_post_preset_change_settle.py`: 34 tests; `test_hvac_cpr_batch_c.py` 155 still pass.
- Mutation: build drills 5/5 red; review C 35 drills, the 12 initially green all made red in the fix-up; orchestrator drill (neuter the settle return) reddened 8 tests.

## Pre-deploy gate
- Full-suite name-diff, develop e1827366c vs the same + feature/hvac-s10-settle (79a6cc499): **CLEAN**, 0 NEW, 0 GONE; 119 failed / 14941 passed vs 119 / 14907. py_compile clean.

## Live acceptance
- **Live:** `sensor.ura_hvac_coordinator_active_preset_overrides` `preset_range_by_zone.zone_3` home/away/sleep stay `skipped_already_correct` with correct ranges (home 70-77, away 62-80, sleep 70-77); originals unchanged (home 70/78, away 66/80).
- **Live:** after a zone_3 preset change, no S10 write within 600 s of it (activity log / `climate_write` rows); `s10_settle_held_s` is None for zone_3 once settled.
- **Live:** 0 URA ERRORs after restart.
