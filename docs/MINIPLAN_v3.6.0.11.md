# MINIPLAN v3.6.0.11 — Presence Hardening

**Date:** 2026-03-01
**Status:** Planning

## Problem Statement

All 5 zones show `rooms: {}` and `room_sensors: false`. The house state machine works only via BLE (Tier 3). Room occupancy sensors (Tier 1) are never discovered, making zone presence unreliable and dependent on a single signal source.

Additionally, the geofence→state transition path is too narrow (only triggers from AWAY), and AWAY hysteresis blocks quick re-entry even when high-confidence signals (BLE, geofence) confirm people are home.

## Root Cause Analysis

### Issue 1: Room Sensor Discovery Failure (Critical)

**Discovery chain:**
```
_build_room_area_map()      →  room_name → area_id  (from CONF_AREA_ID in room config entries)
_discover_room_sensors()    →  find binary_sensors where entity.area_id == area_id
```

**Why it fails:**
- Zigbee sensors (MQTT) have `area_id` set on the **device**, not on the **entity**
- Entity registry: `binary_sensor.occupancy_..._downguestroom_presence` → `area_id: null`
- Device registry: device `0ef7bb1400deca9f93d057d6dceaeaa8` → `area_id: "bedroom"` (= Guest Bedroom 1)
- Code only checks `entity.area_id` (line 760), never falls through to device area_id
- This affects ALL Zigbee/MQTT occupancy sensors across all rooms

**Secondary issue:** `_build_room_area_map()` depends on `CONF_AREA_ID` being set in room config entries. If any rooms lack this, the map is incomplete and name-based fallback is used — which also fails because entity names (`downguestroom`) don't match room names (`Guest Bedroom 1` → `guest_bedroom_1`).

### Issue 2: Geofence Only Triggers From AWAY

**Code (presence.py:1372-1377):**
```python
if zone == "home":
    if manager and manager.house_state_machine.state == HouseState.AWAY:
        self.hass.async_create_task(self._run_inference("geofence_arrive"))
```

Geofence arrival only triggers inference when state is AWAY. If state is stuck in ARRIVING (hysteresis blocking), geofence signals are silently dropped. Departure always triggers (line 1380).

### Issue 3: AWAY Hysteresis Blocks Re-Entry

`DEFAULT_HYSTERESIS[AWAY] = 300` seconds. When the system enters AWAY, it cannot transition out for 5 minutes. This means:
- Person walks in the door (geofence "home")
- BLE detects them in a zone
- Inference wants AWAY → ARRIVING, but hysteresis says "stay AWAY for 5 min"
- All signals are silently discarded

The user wants: **hard to enter AWAY** (high confidence required) but **easy to leave AWAY** (any arrival signal should work quickly).

### Issue 4: No Retry on Blocked Transitions

When hysteresis blocks a valid transition, the event is lost. The next inference only runs on the next periodic tick (every 30s) or the next sensor event. There's no mechanism to retry sooner.

## Solution

### Fix 1: Device Area ID Fallback in Room Sensor Discovery

In `_discover_room_sensors()`, when `entity.area_id` is null, look up the entity's device and use `device.area_id`:

```python
# Get effective area_id (entity → device fallback)
entity_area = entity.area_id
if not entity_area and entity.device_id:
    dev_entry = dev_reg.async_get(entity.device_id)
    if dev_entry:
        entity_area = dev_entry.area_id
```

This requires importing and using the device_registry alongside entity_registry.

### Fix 2: Area Registry Fallback in Room Area Map

In `_build_room_area_map()`, when a room config entry lacks `CONF_AREA_ID`, try to match the room name to an HA area name via the area registry:

```python
if not area_id:
    # Fallback: find HA area matching room name
    for area in area_reg.async_list_areas():
        if area.name.lower() == room_name.lower():
            area_id = area.area_id
            break
```

This handles rooms where the user never explicitly set CONF_AREA_ID but the HA area name matches the room name.

### Fix 3: Geofence Triggers From Any State

Remove the `state == HouseState.AWAY` guard. Geofence arrival should trigger inference from any state — the inference engine and state machine will determine the valid transition:

```python
if zone == "home":
    self.hass.async_create_task(self._run_inference("geofence_arrive"))
    _LOGGER.info("Geofence: %s arrived home", person_id)
```

### Fix 4: Asymmetric AWAY Hysteresis + Deferred Retry

**A. Reduce AWAY hysteresis to 30 seconds** (from 300s). The "hard to enter AWAY" is handled by the inference engine requiring `census_count == 0 AND not any_zone_occupied` at confidence 0.9 — that's already stringent. The 300s dwell was redundant and harmful.

**B. Add deferred retry in `_run_inference()`:** When `can_transition()` returns false (hysteresis), schedule a retry after the remaining dwell time:

```python
if not accepted:
    remaining = machine.remaining_hysteresis()
    if remaining > 0:
        self._schedule_retry(remaining + 1)
```

This ensures blocked transitions are not silently lost.

## Files Changed

| File | Changes |
|------|---------|
| `domain_coordinators/presence.py` | Fix 1: device_registry fallback in _discover_room_sensors. Fix 2: area_registry fallback in _build_room_area_map. Fix 3: remove AWAY guard on geofence. Fix 4b: deferred retry on blocked transitions |
| `domain_coordinators/house_state.py` | Fix 4a: AWAY hysteresis 300→30. Add remaining_hysteresis() method |
| `const.py` | Version → 3.6.0.11 |
| `manifest.json` | Version → 3.6.0.11 |

## Constants

```
DEFAULT_HYSTERESIS[AWAY] = 30    # Was 300. Easy to leave AWAY.
# Entering AWAY still requires census_count==0 AND no zone occupied (inference engine)
```

## Critical Review

**Q: Could reducing AWAY hysteresis cause oscillation?**
A: No. Entering AWAY requires BOTH census_count==0 AND not any_zone_occupied at confidence 0.9. The inference engine is the gatekeeper, not hysteresis. A person walking in triggers geofence → BLE → zone occupied, so the AWAY condition can't be met while someone is home.

**Q: Could geofence from any state cause unexpected transitions?**
A: No. The inference engine decides the target state. Geofence just triggers re-evaluation. If the person is already home, inference returns None (no change). The state machine enforces valid transitions.

**Q: What if _build_room_area_map matches the wrong area?**
A: Case-insensitive exact match on area.name vs room_name. Not substring. "Kitchen" won't match "Kitchen Hallway". False matches are extremely unlikely.

**Q: Device area_id fallback — could it match unrelated devices?**
A: No. We still require the entity to be a binary_sensor with an occupancy keyword in entity_id AND the device area must match the room's area. Three conditions must all be true.

**Q: What about rooms with no HA area at all?**
A: Name-based fallback (existing) still runs. If that also fails, the room simply has no sensor discovery — same as today, no regression.

## Verification

1. After restart, check zone sensors: `rooms` should be populated (not `{}`)
2. `room_sensors: true` for zones that have rooms with occupancy sensors
3. Geofence arrival from any state triggers inference (check logs)
4. AWAY → ARRIVING transition should happen within ~30s of first signal
5. BLE-only zones still work as before (no regression)
6. Absolute safety alerts unaffected (separate coordinator)
