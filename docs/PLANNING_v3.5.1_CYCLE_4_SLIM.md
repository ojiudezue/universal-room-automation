# PLANNING: v3.5.1 Cycle 4 (Slim) — Camera Occupancy Extension, Zone Aggregation & Perimeter Alerting

**Version:** 1.0
**Date:** 2026-02-24
**Parent:** PLANNING_v3.5.1_CYCLE_4.md (full plan preserved alongside this file)
**Status:** Planning → Build
**Depends on:** v3.4.6 (camera config at integration level, camera_census.py, census_snapshots DB table)

---

## WHY THIS PLAN EXISTS

The full Cycle 4 plan (`PLANNING_v3.5.1_CYCLE_4.md`) includes room-level camera-BLE person fusion in coordinator.py. Analysis showed this is premature:

- **Cameras only cover common areas** — most rooms get zero benefit from fusion code
- **BLE is already solid for known persons** — fusion only helps detect *unknown* persons per-room
- **Guest math is fragile** — `camera_count - ble_count` produces phantom guests due to count noise and BLE transition latency
- **Duplicates camera_census.py** — house-level census already exists; room-level fusion is a second counting system
- **coordinator.py is high-traffic** — adding camera resolution + BLE lookup to every 30s cycle adds load to the most sensitive code path

This slim plan keeps everything **except** per-room camera-BLE identity fusion. The one high-value piece from that section — **camera extends room occupancy** — is retained.

---

## WHAT SHIPS

1. **Camera extends room occupancy** — If a camera still sees people after motion timeout, room stays occupied. ~15 lines in coordinator.py. High value, low risk.
2. **Zone person aggregation** — Zone-level sensors enriched with census data from camera_census.py. `sensor.{zone}_identified_persons` and `sensor.{zone}_guest_count` (disabled by default).
3. **Unexpected person binary sensor** — Upgraded from Cycle 3 stub to real logic using house-level census: `camera_total > ble_active_total`.
4. **Perimeter intruder alerting** — New `PerimeterAlertManager` with configurable alert hours, egress suppression, cooldown. Stepping stone for v3.6.0 Security Coordinator.

## WHAT DOES NOT SHIP (vs full plan)

- Per-room `room_identified_persons`, `room_guest_count`, `room_total_persons` state keys
- Per-room camera-BLE fusion math in coordinator.py `_async_update_data()`
- Per-room camera person count sensor (`sensor.{room}_camera_person_count`)
- Camera as a weighted occupancy signal (0.85 weight) — replaced with simpler "camera extends occupancy" override

If room-level guest detection proves needed after real-world testing, the full plan is preserved and can be implemented then.

---

## IMPLEMENTATION

### Section 1: Camera Extends Room Occupancy (coordinator.py)

Minimal change. After existing occupancy timeout logic in `_async_update_data()`, check if any camera assigned to this room (via area) still detects a person. If so, keep the room occupied.

**How to get cameras for a room:**
- v3.4.6 moved all indoor cameras to integration-level config (`CONF_CAMERA_PERSON_ENTITIES`)
- `camera_census.py` has `CameraIntegrationManager` which resolves cameras and knows their areas
- The coordinator should ask the camera manager (stored in `hass.data[DOMAIN]`) for cameras matching this room's area
- OR: store a room→camera mapping at integration setup time and let coordinators read it

```python
# In _async_update_data(), after existing occupancy timeout block:

# v3.5.1: Camera extends occupancy
# If motion/mmWave have timed out but a camera still sees someone, stay occupied
camera_manager = self.hass.data.get(DOMAIN, {}).get("camera_manager")
if camera_manager and not data.get(STATE_OCCUPIED):
    room_area = self._get_room_area()  # from entity registry or config
    room_cameras = camera_manager.get_cameras_for_area(room_area)
    for cam_entity_id in room_cameras:
        person_sensor = camera_manager.get_person_sensor(cam_entity_id)
        if person_sensor:
            state = self.hass.states.get(person_sensor)
            if state and state.state == "on":
                data[STATE_OCCUPIED] = True
                data[STATE_TIMEOUT_REMAINING] = self._occupancy_timeout
                if not self._last_motion_time:
                    self._last_motion_time = now
                _LOGGER.debug(
                    "Room %s: Camera %s overrides vacancy — person detected",
                    room_name, cam_entity_id,
                )
                break
```

**New methods needed on CameraIntegrationManager** (camera_census.py):
- `get_cameras_for_area(area_id: str) -> list[str]` — returns camera entity_ids assigned to a given area
- `get_person_sensor(camera_entity_id: str) -> str | None` — returns the resolved person detection binary_sensor for a camera (this may already exist via resolve_camera_entity)

**New const.py additions for this section:** None beyond what Cycle 3 already added. The occupancy extension reuses existing `STATE_OCCUPIED` and `STATE_TIMEOUT_REMAINING`.

---

### Section 2: Zone Person Aggregation (aggregation.py)

Zone sensors read from `camera_census.py`'s `PersonCensus` (house-level data) rather than aggregating per-room fusion data.

#### 2.1 New: `ZoneIdentifiedPersonsSensor`

Aggregates BLE-identified persons across rooms in a zone (from person_coordinator). Disabled by default.

```python
class ZoneIdentifiedPersonsSensor(SensorEntity):
    """Persons identified by BLE in a zone."""

    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:account-multiple-check"

    @property
    def state(self) -> str:
        return ", ".join(self._persons) if self._persons else "none"

    @property
    def extra_state_attributes(self) -> dict:
        return {"persons": self._persons, "count": len(self._persons), "zone": self._zone_name}

    async def async_update(self) -> None:
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        if not person_coordinator:
            self._persons = []
            return
        zone_rooms = self._get_zone_rooms()
        seen: set[str] = set()
        for person_id, loc in person_coordinator.get_all_locations().items():
            if loc.get("room") in zone_rooms:
                seen.add(person_id)
        self._persons = sorted(seen)
```

#### 2.2 New: `ZoneGuestCountSensor`

Uses house-level census to estimate guests in a zone. Camera census total minus BLE-tracked total = guest estimate. Disabled by default.

```python
class ZoneGuestCountSensor(SensorEntity):
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:account-question"

    @property
    def state(self) -> int:
        return self._guest_count

    async def async_update(self) -> None:
        census = self.hass.data[DOMAIN].get("person_census")
        if not census:
            self._guest_count = 0
            return
        result = census.get_latest_result()
        if result:
            self._guest_count = max(0, result.house_total - result.house_identified)
        else:
            self._guest_count = 0
```

#### 2.3 Upgrade: Existing zone person count sensor

Prefer census house total when available, fall back to existing BLE/occupancy count.

#### 2.4 Registration

Add both new sensors in `async_setup_zone_sensors()`.

---

### Section 3: Unexpected Person Binary Sensor (aggregation.py or binary_sensor.py)

Upgrade from Cycle 3 stub. Uses house-level data only — no per-room fusion needed.

```python
class UnexpectedPersonBinarySensor(BinarySensorEntity):
    """On when cameras see more persons than BLE can account for."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:account-alert"

    @property
    def is_on(self) -> bool:
        return self._unexpected

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "camera_total": self._camera_total,
            "ble_total": self._ble_total,
            "guest_count": max(0, self._camera_total - self._ble_total),
        }

    async def async_update(self) -> None:
        # Get house-level census total (from camera_census.py)
        census = self.hass.data[DOMAIN].get("person_census")
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")

        if not census or not person_coordinator:
            self._unexpected = False
            return

        result = census.get_latest_result()
        self._camera_total = result.house_total if result else 0

        # Count active BLE persons
        ble_active = [
            pid for pid, loc in person_coordinator.get_all_locations().items()
            if loc.get("tracking_status") == "active"
        ]
        self._ble_total = len(ble_active)
        self._unexpected = self._camera_total > self._ble_total
```

---

### Section 4: Perimeter Intruder Alerting

**Identical to full plan.** This section has no dependency on room-level fusion.

Create `perimeter_alert.py` with `PerimeterAlertManager`:
- Monitors perimeter camera state changes during configurable alert hours (default 11PM–5AM)
- Fires notification when person detected with no recent egress crossing (2-min window)
- 5-minute cooldown per camera to prevent alert storms
- Egress camera state changes recorded to suppress false positives

Add `PerimeterAlertStatusSensor` (disabled by default) — diagnostic showing last alert time.

Wire in `__init__.py`: create after integration entry loads, teardown on unload.

Config flow: add alert hours (start/end), notification service, notification target to integration options.

Strings.json: add user-friendly labels for all new config fields.

See full plan Sections 4.1–4.2 and Section 6 for complete implementation reference.

---

### Section 5: Config & Strings

**New const.py additions:**

```python
# Perimeter alerting config
CONF_PERIMETER_ALERT_HOURS_START: Final = "perimeter_alert_hours_start"
CONF_PERIMETER_ALERT_HOURS_END: Final = "perimeter_alert_hours_end"
CONF_PERIMETER_ALERT_NOTIFY_SERVICE: Final = "perimeter_alert_notify_service"
CONF_PERIMETER_ALERT_NOTIFY_TARGET: Final = "perimeter_alert_notify_target"

DEFAULT_PERIMETER_ALERT_START: Final = 23  # 11 PM
DEFAULT_PERIMETER_ALERT_END: Final = 5     # 5 AM
PERIMETER_ALERT_COOLDOWN_SECONDS: Final = 300  # 5 min

# Zone sensor keys
SENSOR_ZONE_IDENTIFIED_PERSONS: Final = "zone_identified_persons"
SENSOR_ZONE_GUEST_COUNT: Final = "zone_guest_count"
```

**strings.json additions (under options.step.camera_census or new perimeter_alerting step):**
- Alert hours start: "Alert monitoring starts at this hour (0–23). Default: 11 PM."
- Alert hours end: "Alert monitoring ends at this hour (0–23). Wraps overnight. Default: 5 AM."
- Notify service: "Notification service to call when a person is detected on your perimeter (e.g., notify.mobile_app_john)."
- Notify target: "Notification target (optional — leave blank to use the service default)."

---

## FILES TO CREATE/MODIFY

| File | Action | What Changes | Lines Est. |
|------|--------|-------------|-----------|
| `perimeter_alert.py` | **Create** | PerimeterAlertManager class | ~200 |
| `coordinator.py` | **Modify** | Camera-extends-occupancy block (~15 lines) | ~20 |
| `camera_census.py` | **Modify** | Add `get_cameras_for_area()`, `get_person_sensor()` helper methods | ~30 |
| `const.py` | **Modify** | Perimeter alert constants, zone sensor keys | ~15 |
| `aggregation.py` | **Modify** | ZoneIdentifiedPersonsSensor, ZoneGuestCountSensor, upgrade UnexpectedPersonBinarySensor | ~120 |
| `sensor.py` | **Modify** | PerimeterAlertStatusSensor | ~40 |
| `__init__.py` | **Modify** | Wire PerimeterAlertManager setup/teardown | ~15 |
| `config_flow.py` | **Modify** | Alert hours + notify config fields | ~30 |
| `strings.json` | **Modify** | New UI strings | ~15 |
| `translations/en.json` | **Sync** | Copy of strings.json | — |

**Total estimated new/changed lines: ~485** (vs ~580 in full plan)

---

## GRACEFUL DEGRADATION

Same as full plan — every feature degrades cleanly:

| Scenario | Behavior |
|---|---|
| No cameras configured | Occupancy extension skips; zone sensors use BLE only; unexpected person stays off |
| No BLE persons tracked | Zone identified = empty; guest count = camera total; unexpected person fires if cameras see anyone |
| No perimeter cameras | PerimeterAlertManager.async_setup() returns immediately |
| No notify service configured | Manager logs warning, no crash |
| Camera entity unavailable | Skipped in occupancy check |
| person_coordinator absent | Zone/guest sensors return empty/zero |

---

## VERIFICATION

1. Configure a room with cameras (area-assigned). Let motion timeout. Camera still sees person → room stays occupied.
2. Clear camera detection → room vacates normally.
3. Enable zone identified persons sensor → shows BLE-tracked persons in that zone's rooms.
4. Enable zone guest count → shows house-level camera minus BLE delta.
5. Trigger unexpected person: all BLE away, camera sees someone → binary sensor on.
6. Configure perimeter camera + notify service + alert hours including now. Trigger detection → notification sent.
7. Trigger again within 5 min → no notification (cooldown).
8. Trigger egress camera, then perimeter within 2 min → no alert (egress suppression).
9. Set alert hours to exclude current time → no alert.
10. Remove all cameras → integration works exactly as v3.3.x baseline.

---

## WHAT THE FULL PLAN ADDS (deferred)

If room-level guest detection proves needed after real-world testing:
- Per-room `room_identified_persons`, `room_guest_count`, `room_total_persons`
- Camera as weighted signal (0.85) in coordinator occupancy calculation
- Per-room camera person count sensor
- Full fusion math in coordinator.py _async_update_data()

See `PLANNING_v3.5.1_CYCLE_4.md` for the complete design.
