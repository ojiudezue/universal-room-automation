# URA v5.103.56 — HVAC high-draw diagnostic moved off the event loop

Card: HVAC-A1-HIGHDRAW-PER-TICK-SCAN-1. Investigation: docs/planning/INVESTIGATION_hvac_override_loop_stall.md. Tier 1 with Tier-2 protocol (2 reviews, fix-ups drilled). Full suite name-diff vs 7ef7551e0: CLEAN (0 new, 0 gone).

## Why
HA Health Monitor flagged a ~2 s event-loop stall 5–6 s after 11 of 12 HVAC decision ticks, inside `OverrideArrester._refresh_a1_cache` → `_high_draw_time_s_7d`. Every 5-minute tick it re-walked 7 days of recorder history per zone (~4.7k states each) on the event loop, purely for a diagnostic figure.

## What changed
- The 7-day high-draw figure is computed by a sync worker (`_compute_high_draw_time_s_7d`) in the executor, not on the loop.
- Result cached per zone and refreshed at most hourly (`HVAC_A1_HIGH_DRAW_REFRESH_S = 3600`, hvac_const — module constant: a diagnostic cadence, not policy).
- No decision logic reads this figure; HVAC behaviour is unchanged.

## Not changed
- The house-wide ~2 s pauses every ~80 s at unrelated sites are not URA; GC hypothesis pending HA Health Monitor v2.1 GC timing.

## Live acceptance
- **Live:** HM `loop_stall` samples no longer show `hvac_override.py:_high_draw_time_s_7d` after restart.
- **Live:** A1 diagnostic attributes still populated (figure present, refreshed within an hour).
- **Live:** 0 URA errors in system_log after boot.
