# Universal Room Automation v3.6.0.9 — Rate-of-Change False Positive Fix

**Release Date:** 2026-03-01
**Previous Release:** v3.6.0.8
**Minimum HA Version:** 2024.1+

---

## Summary

Fixes false rate-of-change overheat alerts caused by two issues: (1) extrapolating short-term sensor noise over tiny time windows, and (2) stale pre-restart readings creating false rate spikes.

---

## Problem

### Root Cause: Minimum Window Too Short

`get_rate()` only required 60 seconds of data before computing a 30-minute extrapolated rate. Normal sensor noise (~0.5°F between readings) over 65 seconds extrapolates to extreme rates:

```
0.5°F / 65s * 1800s = 13.8°F/30min  →  exceeds 10.0 threshold  →  false OVERHEAT alert
```

This is what caused `sensor.invisoutlet_b7d0_temperature` (Study A, 77°F) to show an overheat rate warning of 14.7°F/30min — a tiny real fluctuation over a short window extrapolated into a massive rate.

### Contributing Factor: Post-Restart Stale History

After HA restart, the rate detector could also compare stale pre-restart values against fresh post-restart values, creating additional false spikes.

## Fixes

### 1. Minimum Data Window: 5 Minutes

`RateOfChangeDetector.MIN_WINDOW_SECONDS = 300` (5 minutes). Rate computation now requires at least 5 minutes of data before extrapolating to a 30-minute rate. This prevents short-term noise from being amplified.

With 5 minutes of data, a 0.5°F fluctuation produces:
```
0.5°F / 300s * 1800s = 3.0°F/30min  →  well below 10.0 threshold  →  no alert
```

Only genuine sustained temperature changes (e.g., 3°F over 5 minutes = 18°F/30min) trigger alerts.

### 2. Clear Rate History on Unavailable→Valid Transition

When a sensor transitions from `unavailable`/`unknown` to a valid state, its rate history is cleared to prevent stale pre-restart values from contaminating the rate calculation.

---

## Files Changed

| File | Change |
|------|--------|
| `domain_coordinators/safety.py` | `MIN_WINDOW_SECONDS = 300` in `RateOfChangeDetector`; clear rate history on unavailable→valid transition |
| `const.py` | Version stamp 3.6.0.9 |
| `manifest.json` | Version stamp 3.6.0.9 |

---

## How to Verify

1. After HA restart, no rate-of-change overheat/HVAC-failure alerts should appear within the first 5 minutes
2. `sensor.ura_safety_coordinator_safety_active_hazards` should show 0 (no false positives from sensor noise)
3. Safety status should be "normal"
4. Real sustained temperature changes (>10°F over 5+ minutes) still trigger alerts correctly
