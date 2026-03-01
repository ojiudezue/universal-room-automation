# Universal Room Automation v3.6.0.6 — Safety Cycle Completion

**Release Date:** 2026-03-01
**Previous Release:** v3.6.0.5
**Minimum HA Version:** 2024.1+

---

## Summary

Completes the Safety Coordinator glanceability cycle (C2.5). Adds affected rooms entity with zone grouping, filters internal/diagnostic temperature sensors from monitoring, fixes private attribute access and missing push notification on flooding escalation.

---

## Changes

### 1. New Entity: Safety Affected Rooms

| Entity | Type | State | Purpose |
|--------|------|-------|---------|
| `sensor.ura_safety_affected_rooms` | sensor | Comma-separated room names or "clear" | Which rooms have active hazards? |

**Attributes:**
- `affected_rooms`: list of room names with active hazards
- `affected_by_zone`: `{"Zone Name": ["Room A", "Room B"]}` — rooms grouped by zone
- `room_count`: number of affected rooms
- `zone_count`: number of affected zones
- `worst_room`: room with highest severity hazard

Zone mapping reads `CONF_ZONE` from each URA room config entry to group affected rooms by zone.

### 2. Filter Internal/Diagnostic Temperature Sensors

**Problem:** Monitoring devices (Shelly switches, Apollo Air, mmwave sensors) have internal chip/board temperature sensors that measure circuit temperature, not room temperature. These were classified as environmental temperature sensors, causing false overheat/freeze hazards (e.g., Apollo ESP Temperature at 133°F).

**Fix:** Dual filter in `_classify_entity()`:
1. **entity_category check** — skip entities marked as `diagnostic` in the HA entity registry
2. **Name pattern check** — skip temperature sensors matching known internal patterns: `esp_temperature`, `internal_temperature`, `chip_temperature`, `mcu_temperature`, `board_temperature`, `cpu_temperature`, `pcb_temperature`, `device_temperature`

### 3. Fix Private Attribute Access

`SafetyAlertBinarySensor.extra_state_attributes` accessed `safety._active_hazards` (private) instead of `safety.active_hazards` (public property).

### 4. Fix Missing Push Notification on Flooding Escalation

`_async_periodic_check()` added flooding hazards directly to `_active_hazards` without calling `_notify_entity_update()`. Safety entities would not update via push when flooding was detected — only on next poll cycle.

---

## Files Changed

| File | Change |
|------|--------|
| `domain_coordinators/safety.py` | `get_affected_rooms()` getter; diagnostic/internal sensor filter in `_classify_entity()`; `_notify_entity_update()` on flooding |
| `sensor.py` | `SafetyAffectedRoomsSensor` class; registered in coordinator_manager setup |
| `binary_sensor.py` | Fix `_active_hazards` → `active_hazards` |

---

## How to Verify

1. `sensor.ura_safety_coordinator_safety_affected_rooms` shows "clear" when no hazards
2. When hazards active, shows comma-separated room names
3. Attributes include `affected_by_zone` grouping
4. Internal temp sensors (ESP Temperature, etc.) no longer monitored — check `sensors_monitored` count
5. Flooding escalation triggers immediate entity update (not delayed to next poll)

---

## Safety Coordinator Entity Summary (C2.5 Complete)

| Entity | Type | Category | Purpose |
|--------|------|----------|---------|
| `safety_status` | sensor | Prominent | Overall status + scope + hazard detail |
| `safety_active_hazards` | sensor | Prominent | Count of active hazards |
| `safety_affected_rooms` | sensor | Prominent | Which rooms, grouped by zone |
| `safety_alert` | binary_sensor | Prominent | Any hazard active? |
| `safety_water_leak` | binary_sensor | Prominent | Any water problem? |
| `safety_air_quality` | binary_sensor | Prominent | Any air problem? |
| `safety_diagnostics` | sensor | Diagnostic | Health status |
| `safety_anomaly` | sensor | Diagnostic | Statistical deviation |
| `safety_compliance` | sensor | Diagnostic | Compliance score |
