# Universal Room Automation v3.6.0.1

**Release Date:** 2026-02-28
**Previous Release:** v3.6.0-c2.9.3
**Minimum HA Version:** 2024.1+

---

## Summary

Bug fix release addressing zone presence (root cause found after 4 fix cycles), config flow selector scoping, version header cleanup, and versioning scheme change.

---

## Changes

### 1. Fix Zone Presence "unknown" (Root Cause)

**The bug:** Zone presence sensors were permanently stuck at "unknown" across all 5 zones.

**Root cause:** The config flow stores **config entry IDs** as room references when building zones, but the Presence Coordinator treated them as **room names**. Every zone lookup failed silently because room entry IDs like `"abc123def456"` never matched actual room names like `"Balcony"`.

This affected all three signal tiers:
- Tier 1 (room occupancy sensors): `_discover_room_sensors()` never matched
- Tier 2 (camera sensors): `_discover_zone_cameras()` never matched
- Tier 3 (BLE person location): person location never matched any zone's room list

**Fix:** `_discover_zones()` now resolves entry IDs to room names via `hass.config_entries.async_get_entry(room_ref)` before passing them to `ZonePresenceTracker`. Falls back to treating the value as a literal room name for backward compatibility.

**Why previous fixes didn't work:**
- c2.6 added Zone Manager reading (correct path, but still passed entry IDs)
- c2.9.1 wrapped load_baselines (unrelated crash, masked the real issue)
- c2.9.2 fixed database init (cascading failure, not root cause)

### 2. Manual Switches: Expand Domain Scope

**Before:** Manual switches selector only showed `switch` domain entities.
**After:** Selector now shows `switch`, `light`, and `fan` entities. This allows configuring any device that should turn off when occupancy changes, even if occupancy didn't turn it on.

### 3. Window Sensors: Widen Device Class

**Before:** Window sensor selector accepted `window` and `opening` device classes.
**After:** Now accepts `window`, `door`, `opening`, and `garage_door` device classes. This covers all open/close sensors uniformly.

### 4. Clean Version Headers

**Before:** File headers accumulated version strings: `v3.6.0-c2.9.3-c2.9.2-c2.9.1-c2.10...`
**After:** Headers show only the current version: `v3.6.0.1`

Fixed `stamp_version.py` regex to replace the entire version line instead of just the leading version number.

### 5. New Versioning Scheme

Moved from internal cycle nomenclature (`c2.9.3`) to standard semver-like format:
- `x.y.z.patch` (e.g., `3.6.0.1`)
- Major version bumps for new feature areas (e.g., `3.7.0.0` after coordinators)
- Monotonic patch increments within a release

---

## Files Changed

| File | Change |
|------|--------|
| `domain_coordinators/presence.py` | Resolve entry IDs to room names in `_discover_zones()` |
| `config_flow.py` | Expand manual switches to light/switch/fan; widen window sensors |
| `scripts/stamp_version.py` | Fix header regex to replace full version line |
| `const.py` | Version 3.6.0.1 |
| `README.md` | Version references, release notes link |
| All `.py` files | Clean version headers |

---

## How to Verify

1. After restart, zone presence sensors should show actual states (not "unknown")
2. Presence Coordinator `zones` attribute should be populated (not `{}`)
3. Room config > Devices: manual switches selector shows lights, switches, fans
4. Room config > Sensors: window sensor selector shows door, window, opening, garage_door sensors
5. File headers should show `v3.6.0.1` (clean, no accumulated versions)
