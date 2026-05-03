# v4.2.19 — EVSE Power Sensor Fallback + Health Alert

**Date:** 2026-05-02

## Summary

When the Emporia EVSE power sensor is unavailable, EV control was completely blind — all charging detection returned `power: 0, charging: false`. Now falls back to the switch status attribute ("Charging") with estimated power (7.6 kW). Alerts via NM after 15 minutes of unavailability.

## Problem

`sensor.garage_a_power_minute_average` went unavailable. URA's `_get_evse_state` returned `charging: false` because `power = 0`. This disabled ALL EV control paths:
- Battery drain couldn't detect the EV draining the battery
- Grid cap couldn't detect high grid import from EV
- TOU still paused/resumed by switch state (not affected), but the "charging" field was wrong

## Changes

### 1. Switch status fallback (energy_pool.py)
- When power sensor is unavailable AND `switch.garage_a` is ON AND switch status attribute is "Charging" → set `charging: true` with estimated power of 7,600W
- New `power_source` field in EVSE state: `"sensor"` (normal), `"switch_status"` (fallback), `"unavailable"` (both down)
- `power_source` visible in EV charging status sensor attributes per EVSE

### 2. Power sensor health check (energy_pool.py)
- `check_power_sensor_health()` tracks consecutive unavailable readings per EVSE
- After 3 misses (~15 min) → returns alert for NM
- Clears on recovery, dedup prevents repeat alerts
- Responsive but non-numeric sensor states (e.g., "idle") don't trigger false alerts

### 3. NM alert (energy.py)
- HIGH severity alert: "EVSE Power Sensor Unavailable: garage_a"
- Fires once per unavailability event (deduped)

### 4. Estimated power constant (energy_const.py)
- `EVSE_ESTIMATED_POWER_W = 7600` — L2 charger estimated draw for grid cap / energy accounting when sensor is down

## Review: Tier 1 (hotfix, 3 files)
- 0 CRITICAL, 0 HIGH
- 2 MEDIUM fixed: non-numeric sensor false alerts, zero power in fallback mode
- 2 LOW accepted: single alert per event, conservative status matching

## Files Modified (3)
- `energy_pool.py` — Fallback detection, health check, power_source field
- `energy.py` — Wire health check into decision cycle, NM alert
- `energy_const.py` — EVSE_ESTIMATED_POWER_W constant
