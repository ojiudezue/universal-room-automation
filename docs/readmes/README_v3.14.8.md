# v3.14.8: Excess Solar Overrides TOU Pause

**Date:** 2026-03-13
**Branch:** develop -> main
**Tests:** 18 EVSE tests, 1068 total

## Problem

Excess solar EVSE charging never activated because TOU control paused both EVSEs during peak/mid-peak, and excess solar skipped any EVSE in `_paused_by_us`. Even with battery at 100% and abundant solar, EVs stayed off all day.

## Solution

Excess solar now overrides TOU pause when conditions are met (SOC >= threshold, remaining forecast >= threshold). Priority hierarchy: **excess solar > TOU pause**.

### `domain_coordinators/energy_pool.py`
- **`determine_actions()`**: Skips pausing any EVSE in `_excess_solar_active` — TOU respects the excess solar claim.
- **`determine_excess_solar_actions()`**: When conditions are met and an EVSE is TOU-paused, removes it from `_paused_by_us` and turns it on. Logs "overriding TOU pause" for visibility.

### Flow
1. TOU pauses EVSE during peak/mid-peak
2. Excess solar conditions met (SOC >= 95%, remaining >= 5 kWh) → claims EVSE from TOU, turns it on
3. TOU sees EVSE in `_excess_solar_active` → skips it (no flip-flop)
4. Excess solar conditions stop → turns EVSE off, releases claim → TOU can manage normally

### Also in this release
- **Energy Import Today sensor**: Now shows net grid exchange (import - export), negative = net export. Attributes include full breakdown.
