# v3.6.0.11 — Presence Hardening

**Build:** 2026-03-01

## Summary

Fixes zone room sensor discovery (all zones showed `rooms: {}`) by adding device-area-id fallback and area-registry name matching. Also improves geofence handling, reduces AWAY hysteresis, and adds deferred retry for blocked transitions.

## Problems Fixed

### 1. Room Sensor Discovery Failure (Critical)
All 5 zones showed `rooms: {}` and `room_sensors: false`. Occupancy sensors (Zigbee/MQTT) have `area_id` set on their **device** in the device registry, not on the entity in the entity registry. The discovery code only checked `entity.area_id`, which was always null.

**Fix:** `_discover_room_sensors()` now checks device area_id as fallback when entity area_id is null. Also, `_build_room_area_map()` falls back to matching room names against HA area registry names when `CONF_AREA_ID` is not configured on room entries.

### 2. Geofence Only Triggered From AWAY
Geofence arrival signals were only processed when house state was AWAY. If stuck in another state (e.g., ARRIVING with hysteresis), geofence signals were silently dropped.

**Fix:** Geofence arrival now triggers inference from any state. The inference engine determines the valid transition.

### 3. AWAY Hysteresis Too Long (300s → 30s)
The 300-second AWAY hysteresis prevented quick re-entry even when high-confidence signals (BLE, geofence) confirmed people were home. Entering AWAY already requires `census_count == 0 AND no zone occupied` at confidence 0.9, so the long dwell was redundant.

**Fix:** AWAY hysteresis reduced from 300s to 30s. Entering AWAY is still hard (inference engine gatekeeper), but leaving AWAY is now fast.

### 4. No Retry on Blocked Transitions
When hysteresis blocked a valid transition, the event was lost until the next periodic tick (30s) or sensor event.

**Fix:** `_run_inference()` now schedules a one-shot deferred retry (`async_call_later`) when a transition is blocked by hysteresis, firing just after the dwell period expires.

## Files Changed

| File | Changes |
|------|---------|
| `domain_coordinators/presence.py` | Device area_id fallback in `_discover_room_sensors()`, area registry fallback in `_build_room_area_map()`, geofence from any state, deferred retry on blocked transitions |
| `domain_coordinators/house_state.py` | AWAY hysteresis 300→30, added `remaining_hysteresis()` method |
| `const.py` | Version → 3.6.0.11 |
| `manifest.json` | Version → 3.6.0.11 |

## Verification

1. Zone sensors should show populated `rooms` dict (not `{}`)
2. `room_sensors: true` for zones with rooms containing occupancy sensors
3. Geofence arrival triggers inference from any state (check logs for "geofence_arrive")
4. AWAY → ARRIVING transition within ~30s of first signal
5. BLE-only zones still work as before
6. Deferred retry fires when hysteresis blocks (check logs for "deferred_retry")
