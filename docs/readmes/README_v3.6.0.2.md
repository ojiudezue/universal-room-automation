# Universal Room Automation v3.6.0.2

**Release Date:** 2026-03-01
**Previous Release:** v3.6.0.1
**Minimum HA Version:** 2024.1+

---

## Summary

Diagnostic release for zone presence debugging. Adds comprehensive logging to zone discovery, bypasses the `_has_sensors` gate for BLE signals, and adds diagnostic attributes to zone presence sensors for real-time troubleshooting.

---

## Changes

### 1. Zone Presence: BLE Bypass for `_has_sensors` Gate

**The problem:** `ZonePresenceTracker._derived_mode` returned "unknown" unless `_has_sensors` was True. BLE person tracking (the most reliable signal) was gated behind sensor discovery, which could fail for various reasons.

**Fix:** BLE (Tier 3) is now checked FIRST and independently of `_has_sensors`:
- BLE occupied → OCCUPIED (always, regardless of sensor discovery)
- Tiers 1 & 2 (room sensors, cameras) still require `_has_sensors`
- If BLE has been seen but no person present → AWAY (not unknown)
- Only returns UNKNOWN if no signals have ever been received

### 2. Zone Presence: Comprehensive Diagnostic Logging

**Added INFO-level logging throughout `_discover_zones()`:**
- Total config entries and their types
- Zone Manager entry ID, data zone count, options zone count
- Raw room references per zone (entry IDs before resolution)
- Each entry ID → room name resolution
- Final tracker creation count and zone names

This will reveal exactly where in the discovery chain the failure occurs.

### 3. Zone Presence: Diagnostic Attributes on Sensor

**When zone presence sensor returns "unknown", the `extra_state_attributes` now explain WHY:**
- `debug_reason: "no_coordinator_manager"` — coordinator system not loaded
- `debug_reason: "no_presence_coordinator"` — presence coordinator missing (lists available coordinators)
- `debug_reason: "no_tracker_for_zone"` — zone name mismatch (lists available zones and requested zone)

When tracker IS found, continues to return full `tracker.to_dict()` diagnostics.

---

## Files Changed

| File | Change |
|------|--------|
| `domain_coordinators/presence.py` | BLE bypass in `_derived_mode`, diagnostic logging in `_discover_zones()` |
| `aggregation.py` | Diagnostic attributes in `ZonePresenceStatusSensor` |
| `const.py` | Version 3.6.0.2 |
| `manifest.json` | Version 3.6.0.2 |
| `README.md` | Version references, release notes link |

---

## How to Verify

1. After restart, check HA logs for "Zone discovery:" INFO messages
2. Check zone presence sensor attributes in Developer Tools > States
3. If still "unknown", the `debug_reason` attribute will identify the failure point
4. If BLE is working, zone should show "occupied" or "away" even without room sensors
