# URA v3.6.28 — Transfers Today Sensor Count Fix

**Date:** 2026-03-03
**Scope:** sensor.py

## Summary

Fixes the Transfers Today sensor to only count actual music-involved transfer attempts, not pre-music-check rejections like `low_confidence`.

## Problem

`MusicFollowingTransfersTodaySensor.native_value` summed all `_transfer_stats` values, including `low_confidence`, `cooldown_blocked`, and `ping_pong_suppressed` — stats recorded before any music-playing check occurs. This caused the sensor to show 151 "transfers" when no music was playing; all were person movements rejected at the BLE distance check.

## Fix

`native_value` now only sums stats that indicate actual music-involved transfer attempts: `success`, `failed`, `unverified`, `active_playback_blocked`. Pre-music-check stats remain visible in the sensor attributes for diagnostic purposes.

## Files Changed

- `custom_components/universal_room_automation/sensor.py` — `MusicFollowingTransfersTodaySensor.native_value` filtering

## Tests

645/645 passed.
