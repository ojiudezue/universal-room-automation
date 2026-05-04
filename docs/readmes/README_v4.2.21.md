# v4.2.21 — Smart Plug Hardening: Mid-Peak TOU + Battery Drain Protection

**Date:** 2026-05-03

## Summary

SmartPlugController (L1 charger outlets) upgraded with mid-peak TOU pause and battery drain protection. Load shedding resume paths now respect battery drain for both EVSE and smart plugs (pre-existing bug fixed).

## Problem

SmartPlugController only paused during `peak` TOU. Mid-peak ($0.09/kWh) was treated as off-peak — L1 chargers ran during expensive periods. No battery drain awareness — plugs drained the battery the same as the L2 EVSE but without protection.

## Changes

### D1: Mid-peak TOU pause (energy_pool.py)
- `tou_period == "peak"` → `tou_period in ("peak", "mid_peak")`
- Aligns with EVChargerController which already pauses on both

### D2: Battery drain protection (energy_pool.py)
- New `_paused_by_battery_drain` tracking set
- `determine_battery_drain_actions(battery_power_w, battery_soc, soc_threshold)` — pauses ON plugs when battery discharging + SOC < threshold
- Resume on battery recovery or SOC +5% hysteresis
- Cross-pause guards: TOU resume checks battery drain, battery drain resume checks TOU
- No manual override cooldown (L1 plugs aren't user-interactive)
- Not persisted to DB (stateless dumb switches, recoverable in one decision cycle)
- Shares `_ev_battery_drain_soc` threshold with EVSE (same config)

### D3: Decision cycle integration (energy.py)
- `_smart_plugs.determine_battery_drain_actions()` called after `determine_actions()`
- Passes same battery state as EVSE battery drain

### Load shedding fix (energy.py) — pre-existing bug
- Load shedding resume (lines 2198-2204 EVSE, 2219-2225 smart plugs) directly manipulated `_paused_by_us` and issued `switch.turn_on` without checking `_paused_by_battery_drain`
- Fixed: both paths now check battery drain before resuming

## Review: Tier 1 (1 review)

| Severity | Found | Fixed |
|----------|-------|-------|
| HIGH | 1 | Load shedding resume bypasses battery drain guard (both EVSE + plugs) |
| MEDIUM | 1 | Timing gap when battery drain starts during TOU pause — accepted (narrow window, recovers next cycle) |
| LOW | 3 | Shared threshold, no DB persistence, no cooldown — all by design |

Full report: `docs/reviews/code-review/v4.2.21_smart_plug_hardening.md`

## Files Modified (2)
- `energy_pool.py` — SmartPlugController: mid_peak, battery drain method, cross-pause guards, status
- `energy.py` — Wire smart plug battery drain + fix load shedding resume guards for both EVSE and plugs
