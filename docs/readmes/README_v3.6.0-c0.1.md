# Universal Room Automation v3.6.0-c0.1 — Camera Census Hotfix

**Release Date:** 2026-02-26
**Internal Reference:** Hotfix (Camera Census + Dashboard)
**Previous Release:** v3.6.0-c0
**Minimum HA Version:** 2024.1+
**Depends on:** v3.6.0-c0

---

## Summary

v3.6.0-c0.1 is a hotfix for two bugs that prevented the camera census system from functioning. Despite cameras being configured in integration settings, all census sensors showed 0/none/unknown because (1) configured cameras were never passed to the discovery function, and (2) the census update loop was never started. Also fixes a stale entity reference in the URA Diagnostics dashboard.

### What's Fixed

- **Camera discovery now uses configured cameras** — `async_discover()` was called without parameters, causing it to fall back to full-scan mode that only finds Frigate/UniFi cameras. Now reads `CONF_CAMERA_PERSON_ENTITIES`, `CONF_EGRESS_CAMERAS`, and `CONF_PERIMETER_CAMERAS` from integration options and passes them to discovery. Madrone and other non-Frigate/UniFi cameras will now be discovered.
- **Census updates now run periodically** — `async_update_census()` was defined but never called anywhere. Added `async_track_time_interval()` with `SCAN_INTERVAL_CENSUS` (30 seconds) to trigger census calculations. Census sensors will now update with actual person counts.
- **Census timer cleanup on unload** — The periodic timer is properly cancelled when the integration entry is unloaded.
- **Dashboard entity fix** — URA Diagnostics dashboard referenced the old `sensor.universal_room_automation_identified_people_count` (renamed in Cycle 5). Updated to `sensor.universal_room_automation_occupant_count`. Applied live via MCP.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `__init__.py` | Modified | Pass configured cameras to `async_discover()`, add periodic census timer, cleanup on unload |

### Dashboard Change (applied live via HA MCP, not in codebase)

| Dashboard | Change |
|-----------|--------|
| `ura-diagnostics` | Badge + House Status tile: `identified_people_count` → `occupant_count` |

---

## How to Deploy

```bash
./scripts/deploy.sh "3.6.0-c0.1" "Hotfix: camera census discovery and periodic updates" \
  "- Fix camera discovery to use configured cameras instead of empty full-scan
- Add periodic census update timer (every 30s)
- Clean up census timer on integration unload
- Fix stale entity reference in URA Diagnostics dashboard"
```

---

## How to Verify It Works

### 1. Census sensors update after restart

1. Restart Home Assistant after updating
2. Check logs for: `Camera census: discovered X cameras` (should be > 0)
3. Within 30 seconds, check census sensors:
   - `sensor.universal_room_automation_persons_in_house` — should reflect actual camera detections
   - `sensor.universal_room_automation_census_confidence` — should show a value (not "none")
   - `sensor.universal_room_automation_census_validation_age` — should show seconds (not "unknown")

### 2. Dashboard badge works

1. Open the URA Diagnostics dashboard
2. The "People Home (BLE)" badge and tile should show a number (not "Entity not found")

### 3. Census updates periodically

1. Walk in front of a configured camera
2. Within 30 seconds, the person count sensors should update
3. Check logs for periodic `Census complete` entries

---

## Root Cause Analysis

**Camera Discovery Bug:** In `__init__.py`, the camera manager's `async_discover()` was called with no arguments. The method signature accepts `room_cameras`, `egress_cameras`, and `perimeter_cameras` parameters, but when none are provided, it defaults to scanning all binary sensors for Frigate/UniFi naming patterns. The user's Madrone G6 cameras don't match those patterns, so zero cameras were discovered.

**Census Timer Bug:** The `PersonCensus.async_update_census()` method performs the actual person counting, but nothing ever called it. The `SCAN_INTERVAL_CENSUS` constant (30 seconds) was defined in `const.py` but never wired up to `async_track_time_interval()`. The census object was created and stored in `hass.data`, and sensors read from `census.last_result`, but since the method was never called, `last_result` remained `None`.

---

## Version Mapping

| External Version | Cycle | Feature |
|-----------------|-------|---------|
| 3.6.0-c0 | C0 | Domain coordinator base infrastructure |
| **3.6.0-c0.1** | **Hotfix** | **Camera census discovery + periodic updates (this release)** |
