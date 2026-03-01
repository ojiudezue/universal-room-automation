# Universal Room Automation v3.6.0.9 — Rate-of-Change Restart Fix

**Release Date:** 2026-03-01
**Previous Release:** v3.6.0.8
**Minimum HA Version:** 2024.1+

---

## Summary

Fixes false rate-of-change overheat/HVAC-failure alerts after HA restarts. When sensors transition from unavailable→valid, the rate detector now clears its history for that sensor to prevent false spikes.

---

## Problem

After HA restart, sensors go unavailable briefly then come back online. The rate-of-change detector had stale pre-restart readings in its history. When the sensor reported its first valid reading post-restart, the detector computed a rate against the last pre-restart value:

1. Pre-restart: sensor at 66°F → recorded in history
2. HA restarts → sensor goes `unavailable` (state change skipped)
3. Post-restart: sensor at 76°F → recorded in history
4. Rate detector: 66→76 = +10°F in short window → **false `temperature_rise_extreme` overheat alert**

This is what caused `sensor.invisoutlet_b7d0_temperature` (Study A) to show an overheat rate-of-change warning with value 10.4°F/30min — the sensor was 76.82°F (perfectly normal) but the rate spike from unavailable→valid transition exceeded the 10°F/30min threshold.

## Fix

In `_async_sensor_state_changed()`: when the old state was `unavailable` or `unknown` and the new state is valid, clear the sensor's rate-of-change history via `self._rate_detector.clear(entity_id)`. The first post-restart reading starts fresh with no history, so no rate can be computed until a second reading arrives.

---

## Files Changed

| File | Change |
|------|--------|
| `domain_coordinators/safety.py` | Clear rate history on unavailable→valid transition in `_async_sensor_state_changed()` |
| `const.py` | Version stamp 3.6.0.9 |
| `manifest.json` | Version stamp 3.6.0.9 |

---

## How to Verify

1. After HA restart, no rate-of-change overheat/HVAC-failure alerts should appear
2. `sensor.ura_safety_coordinator_safety_active_hazards` should show 0 (no false positives)
3. Safety status should be "normal"
4. Real rate-of-change alerts (sensor genuinely changing rapidly while online) still fire correctly
