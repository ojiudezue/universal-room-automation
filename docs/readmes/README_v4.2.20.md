# v4.2.20 — EVSE Power Sensor Unavailability Timestamps

**Date:** 2026-05-03

## Summary

Adds `power_sensor_unavail_since` timestamp to EVSE status when the power sensor is unavailable. Visible in the EV charging status sensor attributes per EVSE. NM alert message now includes when unavailability started. Timestamp clears on recovery.

## Changes (energy_pool.py)

- `_power_sensor_unavail_since` dict tracks ISO timestamp when each EVSE's power sensor first went unavailable
- `check_power_sensor_health()` sets timestamp on first unavailable reading, includes it in alert message, clears on recovery with log
- `get_status()` surfaces `power_sensor_unavail_since` in per-EVSE attributes when set

## Review: Tier 1 (additive, 1 file, timestamps only)
No logic changes — purely observability improvement. No review findings.

## Files Modified (1)
- `energy_pool.py` — unavail_since tracking, alert message, status attributes
