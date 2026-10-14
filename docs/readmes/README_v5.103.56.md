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

## Validated 2026-10-14 (overnight pass, read-only; HA up since the 01:16-01:20 CDT restart)

| Criterion | Result | Evidence |
|---|---|---|
| HM `loop_stall` samples no longer show `hvac_override.py:_high_draw_time_s_7d` | **PASS** | HA Health Monitor diagnostics `markers.loop_lag.stalls`: 50 samples 06:29-07:05Z; culprits `python_gc` 44, `unknown` (ssl.py) 3, `spook` 2, `wiim` 1. The strings `hvac_override`, `_high_draw` and `universal_room_automation` do not appear anywhere in `markers.loop_lag`. |
| A1 diagnostic attributes still populated | **PASS** | `sensor.ura_hvac_coordinator_82_ac_gate4_blind_fraction_7d_{back_hallway,entertainment_master_suite,upstairs}`: `high_draw_time_s_7d` = 147916 / 369868 / 293994 s, computed 01:21:51 CDT (about 1 min after boot). The hourly refresh had not fired yet at 02:07; it is inside its window. |
| 0 URA errors in system_log after boot | **PASS** | `ha_get_logs source=system level=ERROR` at 02:05 CDT: 19 entries, none from `universal_room_automation`. URA WARNINGs only: boot sensor-unavailable holds, Envoy cross-check divergence right after midnight/boot, duty-cycle notify, coverage re-anchor, and HA deprecation notices (`device_registry.async_get_device` / `.devices` mapping at `__init__.py:5227/5305`, `_devices.py:607`, already carded as URA-DEPRECATED-DEVICE-REGISTRY-CALLS-1). |

Context for "Not changed" above: the house-wide ~2 s pauses ARE garbage collection. HM v2.1 counted 59 gen-2 collections in ~50 min (mean 1,804 ms, max 2,137 ms) and pinned 44 of 50 stalls on them. Recorded in HM `README_v2.1.0` W16 and on card HM-V21-LIVE-VALIDATION-1.
