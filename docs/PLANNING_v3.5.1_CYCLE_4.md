# PLANNING: v3.5.1 Cycle 4 — Camera-BLE Fusion, Zone Person Aggregation & Perimeter Alerting

**Version:** 1.0
**Date:** 2026-02-23
**Parent:** PLANNING_v3.5.0_CYCLE_3.md (Cycle 3 must ship first)
**Status:** Planning
**Depends on:** v3.5.0 (CameraIntegrationManager, PersonCensus, camera config constants, census_snapshots DB table)

---

## OVERVIEW

Cycle 4 (v3.5.1) builds directly on the census foundation from Cycle 3. Where Cycle 3 established how to *count* people by room using cameras, Cycle 4 establishes *who* those people are by fusing the camera count with BLE IRK identity at the room level. It then propagates that room-level fusion up to zones, adds guest detection, and introduces a lightweight perimeter alerting system as a stepping stone toward the full Security Coordinator in v3.6.0.

**What ships:**

- **Camera-BLE room-level fusion** — Camera person count merged with BLE person identity per room. Camera is added as a weighted signal (weight 0.85) in the room coordinator's `_async_update_data()` alongside motion (0.50), mmWave (0.60), and BLE (0.70). Produces per-room identified person list and guest count.
- **Zone person aggregation** — Zone-level sensors enriched with room-level fusion data. `sensor.{zone}_identified_persons` shows which known persons are in a zone. `sensor.{zone}_person_count` is upgraded from a raw count to a fusion-backed count.
- **Guest detection** — Per-room guest count. A house-level binary sensor fires when camera-visible persons exceed all BLE-tracked persons, indicating an unaccounted-for person is present on-premises.
- **Perimeter intruder alerting** — A new `PerimeterAlertManager` monitors perimeter camera person detection during configurable alert hours and fires a notification when a person is detected with no corresponding BLE egress event. A simple stepping stone; the full Security Coordinator (armed states, sanction logic, pattern learning) ships in v3.6.0.

**What does NOT ship (deferred):**

- Armed state machine (v3.6.0 Security Coordinator)
- Sanctioned vs unsanctioned entry logic (v3.6.0)
- Transit path validation and phone-left-behind detection (v3.5.2 Cycle 6)
- Face recognition entity wiring (v3.5.2 Cycle 6 — action item from Cycle 3 is still open)
- Unidentified face storage and labeling UI (future)
- House state inference / Presence Coordinator (v3.6.0)

---

## IMPLEMENTATION

### Section 1: Room-Level Camera-BLE Fusion

#### 1.1 Modified File: `coordinator.py` — `_async_update_data()`

The room coordinator already polls motion, mmWave, and occupancy sensors every 30 seconds. Camera person detection is added as a fourth weighted signal for rooms that have `CONF_CAMERA_PERSON_ENTITIES` configured.

**Key design rule:** Camera data is purely additive. If no camera entities are configured, the method falls through to existing v3.3.x behavior with no error.

```python
# In _async_update_data(), after the existing occupancy block:

# === v3.5.1: Camera-BLE Room Fusion ===
camera_entities = self._get_config(CONF_CAMERA_PERSON_ENTITIES, [])
camera_person_count = 0
camera_person_detected = False
camera_source = None  # "frigate", "unifi", or "both"

if camera_entities:
    frigate_count = 0
    unifi_detected = False
    platforms_present = set()

    for entity_id in camera_entities:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown"):
            continue

        # Distinguish platform by entity suffix pattern (from Cycle 3 discovery)
        if "_person_occupancy" in entity_id:
            # Frigate binary — use companion sensor for count
            count_entity = entity_id.replace(
                "_person_occupancy", "_person_count"
            )
            count_state = self.hass.states.get(count_entity)
            if count_state and count_state.state not in ("unavailable", "unknown"):
                try:
                    frigate_count = max(frigate_count, int(float(count_state.state)))
                except (ValueError, TypeError):
                    pass
            platforms_present.add("frigate")
            if state.state == "on":
                camera_person_detected = True

        elif "_person_detected" in entity_id:
            # UniFi Protect binary — only presence, no count
            platforms_present.add("unifi")
            if state.state == "on":
                camera_person_detected = True
                # UniFi gives presence but not count; minimum count is 1
                # frigate_count already covers numeric count when both present

    # Resolve final count:
    # If Frigate count is available, use it (authoritative for numbers)
    # If only UniFi, infer at least 1 when detected
    if "frigate" in platforms_present:
        camera_person_count = frigate_count
    elif "unifi" in platforms_present and camera_person_detected:
        camera_person_count = 1  # Minimum — UniFi can't count

    if len(platforms_present) > 1:
        camera_source = "both"
    elif platforms_present:
        camera_source = next(iter(platforms_present))

# Store camera result in coordinator data for sensors to read
data[STATE_CAMERA_PERSON_COUNT] = camera_person_count
data[STATE_CAMERA_PERSON_DETECTED] = camera_person_detected
data[STATE_CAMERA_SOURCE] = camera_source

# === v3.5.1: Per-Room BLE+Camera Person Fusion ===
# Pull BLE-identified persons who are currently in this room
room_name_key = self.entry.data.get("room_name", "").lower().replace(" ", "_")
person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
ble_persons_in_room: list[str] = []

if person_coordinator:
    for person_id, location_data in person_coordinator.get_all_locations().items():
        if location_data.get("room") == room_name_key:
            ble_persons_in_room.append(person_id)

# Fusion logic:
#   identified_persons = BLE persons confirmed in this room
#   guest_count = max(0, camera_count - len(identified_persons))
#   total_in_room = max(camera_count, len(identified_persons))
identified_persons_in_room = ble_persons_in_room
guest_count_in_room = max(0, camera_person_count - len(identified_persons_in_room))

data[STATE_ROOM_IDENTIFIED_PERSONS] = identified_persons_in_room
data[STATE_ROOM_GUEST_COUNT] = guest_count_in_room
data[STATE_ROOM_TOTAL_PERSONS] = max(camera_person_count, len(identified_persons_in_room))
```

**Weighted confidence adjustment:** The existing occupancy logic uses presence/motion detection. Camera detection (when available) pushes confidence higher. This is implemented without changing the existing confidence machinery — the camera simply supplements the occupancy decision.

Weights for shared-space rooms with cameras configured:
- motion: 0.50
- mmWave: 0.60
- BLE: 0.70
- camera: 0.85

When camera count > 0 and existing sensors are off (timeout has elapsed), camera extends occupancy. When camera count = 0 and all existing sensors are off, the room vacates normally.

```python
# Extend occupancy timeout if camera still sees people
if camera_person_count > 0 and not data[STATE_OCCUPIED]:
    # Camera sees someone — treat as occupied regardless of motion timeout
    data[STATE_OCCUPIED] = True
    data[STATE_TIMEOUT_REMAINING] = self._occupancy_timeout
    # Update motion time to prevent immediate re-expiry
    if not self._last_motion_time:
        self._last_motion_time = now
    _LOGGER.debug(
        "Room %s: Camera overrides vacancy — sees %d person(s)",
        room_name, camera_person_count,
    )
```

#### 1.2 New State Keys: `const.py`

```python
# v3.5.1 Room-level camera-BLE fusion state keys
STATE_CAMERA_PERSON_COUNT: Final = "camera_person_count"
STATE_CAMERA_PERSON_DETECTED: Final = "camera_person_detected"
STATE_CAMERA_SOURCE: Final = "camera_source"           # "frigate", "unifi", "both", None
STATE_ROOM_IDENTIFIED_PERSONS: Final = "room_identified_persons"  # list[str]
STATE_ROOM_GUEST_COUNT: Final = "room_guest_count"
STATE_ROOM_TOTAL_PERSONS: Final = "room_total_persons"

# v3.5.1 Perimeter alerting config
CONF_PERIMETER_ALERT_HOURS_START: Final = "perimeter_alert_hours_start"  # int (hour 0-23)
CONF_PERIMETER_ALERT_HOURS_END: Final = "perimeter_alert_hours_end"      # int (hour 0-23)
CONF_PERIMETER_ALERT_NOTIFY_SERVICE: Final = "perimeter_alert_notify_service"
CONF_PERIMETER_ALERT_NOTIFY_TARGET: Final = "perimeter_alert_notify_target"

DEFAULT_PERIMETER_ALERT_START: Final = 23  # 11 PM
DEFAULT_PERIMETER_ALERT_END: Final = 5     # 5 AM

# v3.5.1 Perimeter alert cooldown (prevents repeated alerts for same event)
PERIMETER_ALERT_COOLDOWN_SECONDS: Final = 300  # 5 minutes per camera

# v3.5.1 Sensor key for zone identified persons
SENSOR_ZONE_IDENTIFIED_PERSONS: Final = "zone_identified_persons"
SENSOR_ZONE_GUEST_COUNT: Final = "zone_guest_count"
```

---

### Section 2: Zone Person Aggregation

Zone sensors already exist in `aggregation.py` via `async_setup_zone_sensors()`. Cycle 3 added `sensor.{zone}_person_count` as a raw BLE count. Cycle 4 upgrades it and adds two new per-zone sensors.

#### 2.1 New Class: `ZoneIdentifiedPersonsSensor` (in `aggregation.py`)

Aggregates the `STATE_ROOM_IDENTIFIED_PERSONS` lists from all rooms belonging to a zone, deduplicates, and produces a comma-separated state with a `persons` attribute list.

```python
class ZoneIdentifiedPersonsSensor(SensorEntity):
    """Persons identified (by BLE or camera fusion) in a zone."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        zone_name: str,
    ) -> None:
        self._zone_name = zone_name
        self._attr_unique_id = f"{entry.entry_id}_{zone_name}_identified_persons"
        self._attr_name = f"{zone_name} Identified Persons"
        self._attr_icon = "mdi:account-multiple-check"
        # entity_registry_enabled_default: False  (disabled by default — dashboard use)
        self._attr_entity_registry_enabled_default = False
        self._persons: list[str] = []

    @property
    def state(self) -> str:
        """Comma-separated list of identified person IDs."""
        return ", ".join(self._persons) if self._persons else "none"

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "persons": self._persons,
            "count": len(self._persons),
            "zone": self._zone_name,
        }

    async def async_update(self) -> None:
        """Aggregate identified persons from all rooms in this zone."""
        zone_rooms = self._entry.data.get(CONF_ZONE_ROOMS, [])
        seen: set[str] = set()

        for room_entry_id in zone_rooms:
            coordinator = self.hass.data[DOMAIN].get(room_entry_id)
            if coordinator and coordinator.data:
                persons = coordinator.data.get(STATE_ROOM_IDENTIFIED_PERSONS, [])
                seen.update(persons)

        self._persons = sorted(seen)
```

#### 2.2 Upgrade: `ZonePersonCountSensor` (existing, in `aggregation.py`)

The existing zone person count sensor reads raw BLE-tracked counts. In Cycle 4, it should prefer the camera-fusion total (`STATE_ROOM_TOTAL_PERSONS`) when available for any room in the zone, otherwise fall back to BLE count.

```python
# In ZonePersonCountSensor.async_update():
total = 0
for room_entry_id in zone_rooms:
    coordinator = self.hass.data[DOMAIN].get(room_entry_id)
    if coordinator and coordinator.data:
        # v3.5.1: Prefer camera-fusion total, fall back to BLE occupancy
        room_total = coordinator.data.get(STATE_ROOM_TOTAL_PERSONS)
        if room_total is not None:
            total += room_total
        elif coordinator.data.get(STATE_OCCUPIED):
            # No fusion data — count as 1 (a person is here per existing sensors)
            ble_persons = coordinator.data.get(STATE_ROOM_IDENTIFIED_PERSONS, [])
            total += max(1, len(ble_persons))
self._count = total
```

#### 2.3 New Class: `ZoneGuestCountSensor` (in `aggregation.py`)

Disabled by default. Aggregates per-room guest counts across the zone.

```python
class ZoneGuestCountSensor(SensorEntity):
    """Unidentified persons (guests) detected in a zone via camera fusion."""

    def __init__(self, hass, entry, zone_name):
        ...
        self._attr_entity_registry_enabled_default = False
        self._attr_icon = "mdi:account-question"

    @property
    def state(self) -> int:
        return self._guest_count

    async def async_update(self):
        zone_rooms = self._entry.data.get(CONF_ZONE_ROOMS, [])
        total_guests = 0
        for room_entry_id in zone_rooms:
            coordinator = self.hass.data[DOMAIN].get(room_entry_id)
            if coordinator and coordinator.data:
                total_guests += coordinator.data.get(STATE_ROOM_GUEST_COUNT, 0)
        self._guest_count = total_guests
```

#### 2.4 Registration in `async_setup_zone_sensors()`

```python
# Add to entities list in async_setup_zone_sensors():
ZoneIdentifiedPersonsSensor(hass, entry, zone_name),    # disabled by default
ZoneGuestCountSensor(hass, entry, zone_name),           # disabled by default
```

---

### Section 3: Guest Detection (House-Level)

#### 3.1 New Binary Sensor: `UnexpectedPersonBinarySensor` (in `aggregation.py`)

This sensor extends the existing `binary_sensor.ura_unexpected_person_detected` from Cycle 3. In Cycle 3 it was a stub. In Cycle 4 it becomes real.

**Logic:**
1. Sum all `STATE_ROOM_TOTAL_PERSONS` across all room coordinators for the house total seen by cameras.
2. Sum all BLE-tracked persons currently home (from `person_coordinator`).
3. If `camera_total > ble_total` and all BLE persons are accounted for (tracked as active, not stale), then an unidentified person is present.

```python
class UnexpectedPersonBinarySensor(BinarySensorEntity):
    """On when camera sees more persons than BLE can account for."""

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
            "ble_persons": self._ble_persons,
            "last_evaluated": self._last_evaluated,
        }

    async def async_update(self) -> None:
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        if not person_coordinator:
            self._unexpected = False
            return

        # Count BLE-tracked persons who are home (active tracking status)
        ble_persons = [
            pid for pid, loc in person_coordinator.get_all_locations().items()
            if loc.get("tracking_status") == TRACKING_STATUS_ACTIVE
        ]
        self._ble_total = len(ble_persons)
        self._ble_persons = ble_persons

        # Sum camera-fusion room totals
        camera_total = 0
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            coordinator = self.hass.data[DOMAIN].get(entry.entry_id)
            if coordinator and coordinator.data:
                room_total = coordinator.data.get(STATE_ROOM_TOTAL_PERSONS, 0)
                camera_total = max(camera_total, camera_total + (room_total or 0))
                # Note: rooms may overlap in zone membership but physical cameras
                # only cover distinct spaces. Sum is safe for distinct rooms.
        self._camera_total = camera_total
        self._unexpected = camera_total > self._ble_total and self._ble_total >= 0
        self._last_evaluated = dt_util.now().isoformat()
```

**Note on "unexpected person" vs "guest":** This sensor does not distinguish between an expected guest (someone who was invited) and an intruder. That distinction requires Security Coordinator armed-state logic (v3.6.0). In v3.5.1, any camera-visible person who is not BLE-tracked as active triggers the sensor. Users can build their own automations on top of this.

---

### Section 4: Perimeter Intruder Alerting

This is a new, self-contained manager. It intentionally does NOT implement armed states, sanction logic, or pattern learning — those belong in v3.6.0. It implements one simple rule:

> During configurable alert hours, if a perimeter camera detects a person AND no BLE person egress event has occurred at an egress camera in the last 5 minutes, fire a notification.

#### 4.1 New File: `perimeter_alert.py`

New module, approximately 150-200 lines.

```python
"""Perimeter intruder alerting for URA v3.5.1.

Simple rule-based alerting: person on perimeter camera during alert hours
with no matching egress entry = notification.

This is a stepping stone for the full Security Coordinator (v3.6.0),
which will add armed states, sanction logic, and pattern learning.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_PERIMETER_CAMERAS,
    CONF_EGRESS_CAMERAS,
    CONF_PERIMETER_ALERT_HOURS_START,
    CONF_PERIMETER_ALERT_HOURS_END,
    CONF_PERIMETER_ALERT_NOTIFY_SERVICE,
    CONF_PERIMETER_ALERT_NOTIFY_TARGET,
    DEFAULT_PERIMETER_ALERT_START,
    DEFAULT_PERIMETER_ALERT_END,
    PERIMETER_ALERT_COOLDOWN_SECONDS,
    ENTRY_TYPE_INTEGRATION,
    CONF_ENTRY_TYPE,
)

_LOGGER = logging.getLogger(__name__)


class PerimeterAlertManager:
    """Monitor perimeter cameras during alert hours and fire notifications.

    Lifecycle:
        - Instantiated in __init__.py after integration entry loads
        - Calls async_setup() once; self-manages state listeners
        - Cleaned up via async_teardown() in unload
    """

    def __init__(self, hass: HomeAssistant, integration_entry) -> None:
        self.hass = hass
        self._entry = integration_entry
        self._unsub_listeners: list = []
        # Per-camera last-alerted timestamps for cooldown
        self._last_alert: dict[str, datetime] = {}
        # Egress crossing buffer: records when a BLE person last crossed an egress point
        self._last_egress_crossing: datetime | None = None

    def _get_config(self, key: str, default: Any = None) -> Any:
        """Read from integration entry options with data fallback."""
        return self._entry.options.get(
            key, self._entry.data.get(key, default)
        )

    async def async_setup(self) -> None:
        """Register state listeners for perimeter and egress cameras."""
        perimeter_cameras = self._get_config(CONF_PERIMETER_CAMERAS, [])
        egress_cameras = self._get_config(CONF_EGRESS_CAMERAS, [])

        if not perimeter_cameras:
            _LOGGER.debug(
                "PerimeterAlertManager: No perimeter cameras configured, "
                "alerting disabled."
            )
            return

        @callback
        def _on_perimeter_state_change(event) -> None:
            """Handle perimeter camera entity state changes."""
            new_state = event.data.get("new_state")
            if not new_state or new_state.state not in ("on", "detected"):
                return
            entity_id = event.data.get("entity_id", "")
            self.hass.async_create_task(
                self._handle_perimeter_detection(entity_id)
            )

        @callback
        def _on_egress_state_change(event) -> None:
            """Record egress crossing time."""
            new_state = event.data.get("new_state")
            if new_state and new_state.state in ("on", "detected"):
                self._last_egress_crossing = dt_util.now()

        if perimeter_cameras:
            self._unsub_listeners.append(
                async_track_state_change_event(
                    self.hass, perimeter_cameras, _on_perimeter_state_change
                )
            )

        if egress_cameras:
            self._unsub_listeners.append(
                async_track_state_change_event(
                    self.hass, egress_cameras, _on_egress_state_change
                )
            )

        _LOGGER.info(
            "PerimeterAlertManager: Monitoring %d perimeter cameras, "
            "%d egress cameras.",
            len(perimeter_cameras),
            len(egress_cameras),
        )

    async def _handle_perimeter_detection(self, camera_entity_id: str) -> None:
        """Evaluate a perimeter camera detection and alert if warranted."""
        now = dt_util.now()

        # 1. Check alert hours
        alert_start = self._get_config(
            CONF_PERIMETER_ALERT_HOURS_START, DEFAULT_PERIMETER_ALERT_START
        )
        alert_end = self._get_config(
            CONF_PERIMETER_ALERT_HOURS_END, DEFAULT_PERIMETER_ALERT_END
        )
        if not self._is_in_alert_hours(now.hour, alert_start, alert_end):
            return

        # 2. Check cooldown for this camera
        last = self._last_alert.get(camera_entity_id)
        if last and (now - last).total_seconds() < PERIMETER_ALERT_COOLDOWN_SECONDS:
            _LOGGER.debug(
                "PerimeterAlertManager: Skipping alert for %s — cooldown active",
                camera_entity_id,
            )
            return

        # 3. Check for recent egress crossing (someone went OUT through a door recently)
        #    If someone just exited via a known egress point, the perimeter detection
        #    is likely that same person, not an intruder.
        if self._last_egress_crossing:
            seconds_since_egress = (now - self._last_egress_crossing).total_seconds()
            if seconds_since_egress < 120:  # 2 minutes — just walked outside
                _LOGGER.debug(
                    "PerimeterAlertManager: Egress crossing %ds ago — "
                    "perimeter detection likely same person, skipping alert.",
                    seconds_since_egress,
                )
                return

        # 4. Fire alert
        self._last_alert[camera_entity_id] = now
        await self._send_alert(camera_entity_id, now)

    async def _send_alert(self, camera_entity_id: str, when: datetime) -> None:
        """Send notification via configured notification service."""
        notify_service = self._get_config(CONF_PERIMETER_ALERT_NOTIFY_SERVICE)
        notify_target = self._get_config(CONF_PERIMETER_ALERT_NOTIFY_TARGET)

        if not notify_service:
            _LOGGER.warning(
                "PerimeterAlertManager: Person detected on %s during alert hours "
                "but no notification service is configured.",
                camera_entity_id,
            )
            return

        # Friendly camera name (strip domain prefix and suffixes)
        friendly = camera_entity_id.split(".")[-1].replace("_person_occupancy", "").replace(
            "_person_detected", ""
        ).replace("_", " ").title()

        message = (
            f"Person detected on perimeter camera: {friendly}. "
            f"Time: {when.strftime('%I:%M %p')}. "
            "No door entry detected. Verify via camera."
        )

        service_parts = notify_service.split(".")
        if len(service_parts) != 2:
            _LOGGER.error(
                "PerimeterAlertManager: Invalid notify service '%s'", notify_service
            )
            return

        service_data: dict = {"message": message}
        if notify_target:
            service_data["target"] = notify_target

        try:
            await self.hass.services.async_call(
                service_parts[0],
                service_parts[1],
                service_data,
                blocking=False,
            )
            _LOGGER.warning(
                "PerimeterAlertManager: ALERT — %s at %s",
                friendly,
                when.isoformat(),
            )
        except Exception as exc:
            _LOGGER.error(
                "PerimeterAlertManager: Failed to send alert: %s", exc
            )

    @staticmethod
    def _is_in_alert_hours(current_hour: int, start: int, end: int) -> bool:
        """Return True if current_hour falls within alert window.

        Handles overnight wrap (e.g., start=23, end=5 means 11pm to 5am).
        """
        if start > end:
            # Overnight: alert from start to midnight, then midnight to end
            return current_hour >= start or current_hour < end
        else:
            return start <= current_hour < end

    async def async_teardown(self) -> None:
        """Unsubscribe all listeners on integration unload."""
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()
```

#### 4.2 New Sensor: `PerimeterAlertStatusSensor` (in `sensor.py` or `aggregation.py`)

A diagnostic sensor at integration level showing last alert time and status. Disabled by default.

```python
class PerimeterAlertStatusSensor(SensorEntity):
    """Last perimeter alert: timestamp and camera. Diagnostic."""

    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:shield-alert"

    @property
    def state(self) -> str:
        """'none' or ISO timestamp of last alert."""
        manager = self.hass.data[DOMAIN].get("perimeter_alert_manager")
        if not manager or not manager._last_alert:
            return "none"
        last_time = max(manager._last_alert.values())
        return last_time.isoformat()

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data[DOMAIN].get("perimeter_alert_manager")
        if not manager:
            return {}
        return {
            "alerts_by_camera": {
                cam: t.isoformat() for cam, t in manager._last_alert.items()
            },
            "cameras_monitored": len(
                self.hass.data[DOMAIN]
                .get("integration_entry", self._entry)
                .options.get(CONF_PERIMETER_CAMERAS, [])
            ),
        }
```

---

### Section 5: Integration Init Changes (`__init__.py`)

The `PerimeterAlertManager` must be started after the integration entry loads. This follows the same pattern as `camera_manager` and `census` from Cycle 3.

```python
# In async_setup_entry(), after Cycle 3 camera/census init:

# v3.5.1: Perimeter alerting
from .perimeter_alert import PerimeterAlertManager

if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
    perimeter_manager = PerimeterAlertManager(hass, entry)
    await perimeter_manager.async_setup()
    hass.data[DOMAIN]["perimeter_alert_manager"] = perimeter_manager

# In async_unload_entry():
perimeter_manager = hass.data[DOMAIN].get("perimeter_alert_manager")
if perimeter_manager:
    await perimeter_manager.async_teardown()
```

---

### Section 6: Config Flow Changes (`config_flow.py`)

Cycle 3 already added `CONF_PERIMETER_CAMERAS` and `CONF_EGRESS_CAMERAS` to the integration-level options. Cycle 4 adds alert-hours and notification config to the same step.

```python
# Add to integration options step schema (alongside existing perimeter camera selector):

vol.Optional(
    CONF_PERIMETER_ALERT_HOURS_START,
    default=DEFAULT_PERIMETER_ALERT_START,
): selector.NumberSelector(
    selector.NumberSelectorConfig(min=0, max=23, mode="box")
),
vol.Optional(
    CONF_PERIMETER_ALERT_HOURS_END,
    default=DEFAULT_PERIMETER_ALERT_END,
): selector.NumberSelector(
    selector.NumberSelectorConfig(min=0, max=23, mode="box")
),
vol.Optional(CONF_PERIMETER_ALERT_NOTIFY_SERVICE): selector.TextSelector(),
vol.Optional(CONF_PERIMETER_ALERT_NOTIFY_TARGET): selector.TextSelector(),
```

**UI guidance strings (strings.json):**
- Alert hours start: "Perimeter alert hours — start (0–23)"
- Alert hours end: "Perimeter alert hours — end (0–23; wraps overnight)"
- Notify service: "Notification service (e.g. notify.mobile_app_john)"
- Notify target: "Notification target (optional, leave blank for service default)"

---

## ENTITIES

### New Sensors

| Entity ID | Type | Default | State | Key Attributes |
|---|---|---|---|---|
| `sensor.{room}_camera_person_count` | sensor | enabled | int (camera count) | source (frigate/unifi/both), identified_persons, guest_count |
| `sensor.{zone}_identified_persons` | sensor | **disabled** | "John, Jane" or "none" | persons (list), count |
| `sensor.{zone}_guest_count` | sensor | **disabled** | int | zone, rooms_with_guests |
| `sensor.ura_perimeter_alert_status` | sensor | **disabled** | ISO timestamp or "none" | alerts_by_camera, cameras_monitored |

### Modified Sensors

| Entity ID | What Changes |
|---|---|
| `sensor.{zone}_person_count` | Now uses camera-fusion `STATE_ROOM_TOTAL_PERSONS` when available; falls back to BLE count |
| `binary_sensor.ura_unexpected_person_detected` | Now real logic (was stub in Cycle 3): fires when camera_total > ble_active_total |

### Modified Coordinator Data Keys

Added to `coordinator.py` data dict per room (visible to all room-level sensors):

| Key | Type | Description |
|---|---|---|
| `camera_person_count` | int | Raw camera count for this room (0 if no cameras) |
| `camera_person_detected` | bool | True if any camera sees a person |
| `camera_source` | str\|None | "frigate", "unifi", "both", or None |
| `room_identified_persons` | list[str] | BLE-confirmed person IDs in this room |
| `room_guest_count` | int | camera_person_count minus identified count |
| `room_total_persons` | int | max(camera_count, len(identified)) |

### Entity Counts Summary

| Category | Enabled | Disabled | Total New |
|---|---|---|---|
| Per-room camera count sensor (rooms with cameras only) | varies | — | varies |
| Zone identified persons | — | 1 per zone | ~3 |
| Zone guest count | — | 1 per zone | ~3 |
| Perimeter alert status | — | 1 | 1 |
| Unexpected person binary (upgraded from stub) | 1 | — | 0 new |

---

## FILES TO CREATE/MODIFY

| File | Action | What Changes | Lines Est. |
|---|---|---|---|
| `perimeter_alert.py` | **Create** | New PerimeterAlertManager class | ~200 |
| `coordinator.py` | **Modify** | Add camera-BLE fusion block to `_async_update_data()`, camera extends occupancy | ~60 |
| `const.py` | **Modify** | Add 8 new state keys and 6 new config/default constants | ~25 |
| `aggregation.py` | **Modify** | Add ZoneIdentifiedPersonsSensor, ZoneGuestCountSensor; upgrade ZonePersonCountSensor and UnexpectedPersonBinarySensor; register new sensors | ~150 |
| `sensor.py` | **Modify** | Add PerimeterAlertStatusSensor; add camera_person_count room-level sensor | ~80 |
| `__init__.py` | **Modify** | Init PerimeterAlertManager after integration entry load; teardown on unload | ~20 |
| `config_flow.py` | **Modify** | Add alert-hours and notify config fields to integration options step | ~30 |
| `strings.json` | **Modify** | Add UI strings for new config fields | ~15 |

**Total estimated new/changed lines: ~580**

No new database tables. Cycle 3's `census_snapshots` table is sufficient for the data this cycle produces. Perimeter alert history is not persisted — it lives in `PerimeterAlertManager._last_alert` in memory, which is acceptable for this stepping-stone feature.

---

## GRACEFUL DEGRADATION

Every feature in this cycle degrades cleanly when its dependencies are absent:

| Scenario | Behavior |
|---|---|
| No cameras configured | coordinator fusion block exits early; `camera_person_count=0`, `room_guest_count=0`; zone sensors fall back to BLE count; `unexpected_person_detected` stays off |
| No BLE persons tracked | `room_identified_persons=[]`; guest count = camera count; `unexpected_person` fires if cameras see anyone |
| No perimeter cameras configured | `PerimeterAlertManager.async_setup()` logs and returns immediately; no listeners registered |
| No perimeter notify service | Manager logs a warning on detection but does not error; alert is recorded in `_last_alert` dict for the diagnostic sensor |
| Camera entity unavailable | Skipped in the per-entity loop; treated as no-data for that platform |
| `person_coordinator` absent | Room fusion skips BLE lookup; treats everyone as unidentified |

The v3.3.x baseline (motion + mmWave only, no cameras, no BLE) is fully preserved in all cases.

---

## VERIFICATION

### Camera-BLE Fusion

1. Configure a room with both a Frigate occupancy sensor and a UniFi person detected sensor.
2. Trigger a camera detection. Verify `coordinator.data["camera_person_count"]` > 0.
3. Ensure the room stays occupied past its normal timeout while camera still sees people.
4. With BLE tracking active for one person, verify `room_identified_persons` contains that person's ID when they are in the room.
5. With camera seeing 3 and BLE tracking 1, verify `room_guest_count` = 2.
6. Clear camera detections. Verify `camera_person_count` returns to 0.

### Zone Aggregation

7. Place one known person (BLE-tracked) in one room of a zone, with a guest in another room of the same zone.
8. Verify `sensor.{zone}_person_count` reflects the fusion total.
9. Enable `sensor.{zone}_identified_persons` in HA and verify it shows the known person's ID only.
10. Enable `sensor.{zone}_guest_count` and verify it shows 1.

### Guest Detection

11. With all BLE persons away (or stale), trigger a camera detection.
12. Verify `binary_sensor.ura_unexpected_person_detected` turns on.
13. Bring a BLE person back to active tracking. With camera seeing 1 person, verify sensor turns off.
14. With camera seeing 2, BLE showing 1 active, verify sensor stays on (guest present).

### Perimeter Alerting

15. Configure one perimeter camera and a notification service. Set alert hours to include the current time.
16. Trigger the perimeter camera entity to "on". Verify notification is sent.
17. Trigger again within 5 minutes. Verify no second notification (cooldown).
18. Trigger an egress camera event, then trigger the perimeter camera within 2 minutes. Verify no alert (egress suppression).
19. Set alert hours to exclude the current time. Trigger the perimeter camera. Verify no alert.
20. Remove notify service from config. Trigger perimeter camera. Verify warning log, no crash.

### Graceful Degradation

21. Remove all `CONF_CAMERA_PERSON_ENTITIES` from a room. Verify room coordinator still produces `STATE_OCCUPIED` correctly via motion/mmWave.
22. Unload and reload the integration with no perimeter cameras configured. Verify no errors in logs.

---

## DEPLOY

```bash
./scripts/deploy.sh "3.5.1" "Camera-BLE fusion, zone person aggregation, perimeter alerting" "- Room-level fusion: camera person count + BLE identity per room
- Camera extends occupancy when motion timeout expires but camera still sees people
- Zone identified persons sensor: who is in each zone by name
- Zone guest count sensor: unidentified camera-visible persons per zone
- Zone person count upgraded to use camera-fusion totals when available
- Unexpected person binary sensor: real logic (camera total > BLE active total)
- PerimeterAlertManager: configurable alert hours, egress suppression, 5-min cooldown
- Perimeter alert status diagnostic sensor
- Alert hours + notification config in integration options flow
- All features degrade cleanly without cameras or BLE"
```

---

## STEPPING STONE NOTES FOR v3.6.0

This cycle is deliberately scoped to avoid over-engineering. The following were consciously deferred and should be picked up by the Security Coordinator in v3.6.0:

- **Armed states** — `PerimeterAlertManager` always uses alert-hours as its only gating. The Security Coordinator will replace this with proper `ArmedState` enum logic as designed in `SECURITY_COORDINATOR.md`.
- **Sanction checking** — Currently there is no way to say "the person on the perimeter camera is an expected guest." The Security Coordinator's `SanctionChecker` handles this.
- **Pattern learning** — No unusual-time detection. The Security Coordinator's `SecurityPatternLearner` handles this.
- **Perimeter alert logging to DB** — Alerts fire and are logged via `_LOGGER.warning` only. The Security Coordinator will persist alert events.
- **Camera recording trigger** — Noted in `SECURITY_COORDINATOR.md` as a desired response action. Not implemented here.
- **House state integration** — `PerimeterAlertManager` does not read house state. The Security Coordinator will map `HouseState → ArmedState` and use that to gate all alerts.

The `PerimeterAlertManager` is designed to be replaced entirely by the Security Coordinator. Its interface (`async_setup`, `async_teardown`, config keys) is chosen not to conflict with v3.6.0's coordinator framework.
