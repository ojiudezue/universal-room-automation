# v4.2.18 — Fix EV Battery Drain Resume Flapping

**Date:** 2026-05-01

## Summary

Removes off-peak TOU as a resume condition from EV battery drain protection. The off-peak condition caused a 5-minute flapping loop: resume (off-peak) → battery starts draining → re-pause (SOC low) → resume (still off-peak) → repeat.

## Problem

In `determine_battery_drain_actions`, the resume conditions were:
1. Battery stops discharging
2. SOC recovers above threshold + 5%
3. **Off-peak TOU period** ← this caused flapping

During off-peak night with Enphase in `self_consumption` mode, the battery always discharges to supply house load. Condition 3 fires immediately because it's already off-peak, turning the charger on. The charger draws power, battery discharges further, SOC drops below threshold, pause fires. Next cycle: still off-peak → resume → discharge → pause. Every 5 minutes.

## Fix

Removed `off_peak` resume condition. Resume now only fires on:
1. **Battery stops discharging** — happens when battery hits reserve/drain target and Enphase holds. Grid takes over. EV charges from grid at lowest rate.
2. **SOC recovers above threshold + 5%** — happens when morning solar recharges battery.

Also cleaned up: removed dead `tou_period` parameter, updated docstring and comments.

## Safety Verification

**Can the EV get stuck paused forever?** No — three exit paths:
- Battery hits drain target → reserve holds → battery_power ~0W → resume
- Solar recharges battery above threshold + hysteresis → resume
- User manually turns on charger → override detection → 1h cooldown

**Can the EV resume into expensive rates?** No — the `_paused_by_us` guard (line 495) prevents resume when TOU has the charger paused for peak/mid-peak.

## Review: Tier 1 (hotfix, 1 file)
- 0 CRITICAL, 0 HIGH, 0 MEDIUM, 3 LOW (all fixed: stale docstring, stale comment, dead parameter)

## Files Modified (2)
- `energy_pool.py` — Remove off-peak resume, clean up docstring/comments/parameter
- `energy.py` — Remove tou_period argument from caller
