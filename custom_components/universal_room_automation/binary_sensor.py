"""Binary sensor platform for Universal Room Automation."""
#
# Universal Room Automation v3.10.4
# Build: 2026-01-02
# File: binary_sensor.py
# v3.2.6: Renamed "Presence" to "Sensor Presence" for clarity
#

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from .const import (
    DOMAIN,
    VERSION,
    NAME,
    ICON_OCCUPIED,
    ICON_VACANT,
    ICON_MOTION,
    ICON_PRESENCE,
    ICON_DARK,
    ICON_ROOM_ALERT,
    STATE_OCCUPIED,
    STATE_BLE_PERSONS,
    STATE_OCCUPANCY_SOURCE,
    STATE_MOTION_DETECTED,
    STATE_PRESENCE_DETECTED,
    STATE_DARK,
    STATE_TEMPERATURE,
    STATE_HUMIDITY,
    ATTR_LAST_MOTION,
    ATTR_TIMEOUT,
    CONF_DOOR_SENSORS,
    CONF_DOOR_TYPE,
    CONF_WINDOW_SENSORS,
    DOOR_TYPE_EGRESS,
    COMFORT_TEMP_MIN,
    COMFORT_TEMP_MAX,
    COMFORT_HUMIDITY_MIN,
    COMFORT_HUMIDITY_MAX,
    DEFAULT_FAN_TEMP_THRESHOLD,
    DEFAULT_HUMIDITY_THRESHOLD,
    # v3.5.0 Camera Census
    CONF_CAMERA_PERSON_ENTITIES,
    CONF_TRACKED_PERSONS,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ROOM,
    CONF_ENTRY_TYPE,
)
from .aggregation import AggregationEntity
from .coordinator import UniversalRoomCoordinator
from .entity import UniversalRoomEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Universal Room Automation binary sensors."""
    from .const import (
        CONF_ENTRY_TYPE, ENTRY_TYPE_INTEGRATION, ENTRY_TYPE_ZONE,
        ENTRY_TYPE_ZONE_MANAGER, ENTRY_TYPE_COORDINATOR_MANAGER,
    )

    # Check if this is an integration entry (aggregation binary sensors)
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
        from .aggregation import async_setup_aggregation_binary_sensors
        await async_setup_aggregation_binary_sensors(hass, entry, async_add_entities)

        # v3.5.0: Census binary sensors for integration entry
        census_binary: list = [
            URAUnexpectedPersonSensor(hass, entry),
            # v3.5.2: Census mismatch sensor
            CensusMismatchSensor(hass, entry),
        ]

        # v3.5.2: Per-person phone-left-behind sensor (one per tracked person)
        from .const import CONF_TRACKED_PERSONS
        merged_config = {**entry.data, **entry.options}
        tracked_person_entities = merged_config.get(CONF_TRACKED_PERSONS, [])
        for entity_id in tracked_person_entities:
            if entity_id.startswith("person."):
                person_name = entity_id.replace("person.", "").replace("_", " ").title()
            else:
                person_name = entity_id.replace("_", " ").title()
            census_binary.append(PersonPhoneLeftBehindSensor(hass, entry, person_name))

        async_add_entities(census_binary)
        return

    # v3.6.0: Zone Manager entry - set up zone binary sensors under this entry
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER:
        from .aggregation import async_setup_zone_manager_binary_sensors
        await async_setup_zone_manager_binary_sensors(hass, entry, async_add_entities)
        return

    # v3.6.0: Coordinator Manager entry — Presence + Safety binary sensors
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
        coordinator_binary = [
            HouseOccupiedBinarySensor(hass, entry),
            HouseSleepingBinarySensor(hass, entry),
            GuestModeBinarySensor(hass, entry),
            # v3.6.0-c2: Safety Coordinator
            SafetyAlertBinarySensor(hass, entry),
            # v3.6.0.3: Glanceable safety binary sensors
            SafetyWaterLeakBinarySensor(hass, entry),
            SafetyAirQualityBinarySensor(hass, entry),
            # v3.6.0-c3: Security Coordinator
            SecurityAlertBinarySensor(hass, entry),
            # v3.6.29: Notification Manager
            NMActiveAlertBinarySensor(hass, entry),
            # v3.7.3: Energy Coordinator
            EnergyEnvoyAvailableBinarySensor(hass, entry),
            # v3.7.7: L1 Charger status
            EnergyL1ChargerBinarySensor(hass, entry),
        ]
        async_add_entities(coordinator_binary)
        return

    # Legacy zone entry - no longer creates sensors
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE:
        return

    # Room entry - normal binary sensor setup
    coordinator: UniversalRoomCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    # Core binary sensors (enabled by default)
    entities = [
        OccupiedBinarySensor(coordinator),
        MotionDetectedBinarySensor(coordinator),
        PresenceDetectedBinarySensor(coordinator),
        DarkBinarySensor(coordinator),
        # v3.5.0: Per-room camera person detected sensor
        CameraPersonDetectedSensor(coordinator),
    ]

    # Phase 4 diagnostic binary sensors (disabled by default)
    entities.extend([
        HVACCoordinatedBinarySensor(coordinator),
        EnergySavingActiveBinarySensor(coordinator),
        FanShouldRunBinarySensor(coordinator),
        HVACCoolingBinarySensor(coordinator),
        HVACHeatingBinarySensor(coordinator),
        OccupancyAnomalyBinarySensor(coordinator),
        EnergyAnomalyBinarySensor(coordinator),
        RoomAlertBinarySensor(coordinator),
    ])
    
    async_add_entities(entities)
    _LOGGER.info(
        "Set up %d binary sensors for room: %s",
        len(entities),
        entry.data.get("room_name")
    )


class OccupiedBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Binary sensor for room occupancy."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "occupied", "Occupied")

    @property
    def is_on(self) -> bool:
        """Return true if room is occupied."""
        return self.coordinator.data.get(STATE_OCCUPIED, False) if self.coordinator.data else False

    @property
    def icon(self) -> str:
        """Return icon based on state."""
        return ICON_OCCUPIED if self.is_on else ICON_VACANT

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional state attributes."""
        attrs = {
            ATTR_LAST_MOTION: self.coordinator._last_motion_time.isoformat()
            if self.coordinator._last_motion_time else None,
            ATTR_TIMEOUT: self.coordinator.data.get("timeout_remaining", 0) if self.coordinator.data else 0,
        }
        if self.coordinator.data:
            attrs["occupancy_source"] = self.coordinator.data.get(
                STATE_OCCUPANCY_SOURCE, "none"
            )
            attrs["ble_persons"] = self.coordinator.data.get(
                STATE_BLE_PERSONS, []
            )
        return attrs


class MotionDetectedBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Binary sensor for motion detection."""

    _attr_device_class = BinarySensorDeviceClass.MOTION
    _attr_icon = ICON_MOTION

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "motion", "Motion")

    @property
    def is_on(self) -> bool:
        """Return true if motion is detected."""
        return self.coordinator.data.get(STATE_MOTION_DETECTED, False) if self.coordinator.data else False


class PresenceDetectedBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Binary sensor for presence detection (mmWave/PIR/combined)."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_icon = ICON_PRESENCE

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        # v3.2.6: Renamed from "Presence" to "Sensor Presence" for clarity
        # Works with mmWave, PIR, or combined presence sensors
        # unique_id kept as "presence" for backward compatibility
        super().__init__(coordinator, "presence", "Sensor Presence")

    @property
    def is_on(self) -> bool:
        """Return true if presence is detected."""
        return self.coordinator.data.get(STATE_PRESENCE_DETECTED, False) if self.coordinator.data else False


class DarkBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Binary sensor for dark state."""

    _attr_icon = ICON_DARK

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "dark", "Dark")

    @property
    def is_on(self) -> bool:
        """Return true if room is dark."""
        return self.coordinator.data.get(STATE_DARK, False) if self.coordinator.data else False


class HVACCoordinatedBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Binary sensor for HVAC coordination status."""

    _attr_icon = "mdi:hvac"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "hvac_coordinated", "HVAC Coordinated")

    @property
    def available(self) -> bool:
        """Sensor is always available."""
        return True

    @property
    def is_on(self) -> bool:
        """Return true if HVAC is coordinating with room automation."""
        return self.coordinator.data.get("hvac_coordinated", False) if self.coordinator.data else False


class EnergySavingActiveBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Binary sensor for energy saving mode status."""

    _attr_icon = "mdi:leaf"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "energy_saving_active", "Energy Saving Active")

    @property
    def available(self) -> bool:
        """Sensor is always available."""
        return True

    @property
    def is_on(self) -> bool:
        """Return true if energy saving mode is active."""
        # Energy saving when room vacant and devices still consuming power
        occupied = self.coordinator.data.get(STATE_OCCUPIED, False) if self.coordinator.data else False
        power = self.coordinator.data.get("power_current", 0) if self.coordinator.data else 0
        return not occupied and power > 5  # Idle power threshold


class FanShouldRunBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Binary sensor for fan run recommendation."""

    _attr_icon = "mdi:fan"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "fan_should_run", "Fan Should Run")

    @property
    def available(self) -> bool:
        """Available if temperature data exists."""
        return (self.coordinator.data and self.coordinator.data.get(STATE_TEMPERATURE)) is not None

    @property
    def is_on(self) -> bool:
        """Return true if fan should be running based on logic."""
        temp = self.coordinator.data.get(STATE_TEMPERATURE) if self.coordinator.data else None
        occupied = self.coordinator.data.get(STATE_OCCUPIED, False) if self.coordinator.data else False
        if temp is None or not occupied:
            return False
        
        fan_threshold = self.coordinator.entry.data.get("fan_temp_threshold", 80)
        return temp >= fan_threshold


class HVACCoolingBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Binary sensor for HVAC cooling status."""

    _attr_device_class = BinarySensorDeviceClass.COLD
    _attr_icon = "mdi:snowflake"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "hvac_cooling", "HVAC Cooling")

    @property
    def available(self) -> bool:
        """Available if climate entity is configured."""
        climate_entity = self.coordinator.entry.data.get("climate_entity")
        if not climate_entity:
            return False
        state = self.coordinator.hass.states.get(climate_entity)
        return state is not None

    @property
    def is_on(self) -> bool:
        """Return true if HVAC is actively cooling."""
        climate_entity = self.coordinator.entry.data.get("climate_entity")
        if not climate_entity:
            return False
        
        state = self.coordinator.hass.states.get(climate_entity)
        if not state:
            return False
        
        hvac_action = state.attributes.get("hvac_action")
        return hvac_action == "cooling"


class HVACHeatingBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Binary sensor for HVAC heating status."""

    _attr_device_class = BinarySensorDeviceClass.HEAT
    _attr_icon = "mdi:fire"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "hvac_heating", "HVAC Heating")

    @property
    def available(self) -> bool:
        """Available if climate entity is configured."""
        climate_entity = self.coordinator.entry.data.get("climate_entity")
        if not climate_entity:
            return False
        state = self.coordinator.hass.states.get(climate_entity)
        return state is not None

    @property
    def is_on(self) -> bool:
        """Return true if HVAC is actively heating."""
        climate_entity = self.coordinator.entry.data.get("climate_entity")
        if not climate_entity:
            return False
        
        state = self.coordinator.hass.states.get(climate_entity)
        if not state:
            return False
        
        hvac_action = state.attributes.get("hvac_action")
        return hvac_action == "heating"


class OccupancyAnomalyBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Binary sensor for occupancy anomaly detection."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:alert-circle"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "occupancy_anomaly", "Occupancy Anomaly")

    @property
    def available(self) -> bool:
        """Sensor is always available."""
        return True

    @property
    def is_on(self) -> bool:
        """Return true if unusual occupancy pattern detected."""
        # TODO: Implement anomaly detection algorithm
        # For now, return False
        return False


class EnergyAnomalyBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Binary sensor for energy anomaly detection."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:alert-circle"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "energy_anomaly", "Energy Anomaly")

    @property
    def available(self) -> bool:
        """Sensor is always available."""
        return True

    @property
    def is_on(self) -> bool:
        """Return true if unusual energy usage detected."""
        # TODO: Implement anomaly detection algorithm
        # For now, return False
        return False


class RoomAlertBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Binary sensor for room alert/alarm status."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = ICON_ROOM_ALERT

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "room_alert", "Room Alert")

    @property
    def is_on(self) -> bool:
        """Return true if any alerts active."""
        alerts = self._get_active_alerts()
        return len(alerts) > 0

    @property
    def extra_state_attributes(self) -> dict:
        """Return alert details."""
        alerts = self._get_active_alerts()
        return {
            "alert_count": len(alerts),
            "alerts": alerts,
            "temperature_alert": self._check_temperature_alert(),
            "humidity_alert": self._check_humidity_alert(),
            "door_alert": self._check_door_alert(),
            "window_alert": self._check_window_alert(),
        }

    def _get_active_alerts(self) -> list[str]:
        """Get list of active alert descriptions."""
        alerts = []

        # Temperature alerts - use existing thresholds
        temp = self.coordinator.data.get(STATE_TEMPERATURE) if self.coordinator.data else None
        if temp:
            if temp > DEFAULT_FAN_TEMP_THRESHOLD:
                alerts.append(f"Temperature too high: {temp:.1f}°F")
            elif temp < COMFORT_TEMP_MIN:
                alerts.append(f"Temperature too low: {temp:.1f}°F")

        # Humidity alerts - use existing thresholds
        humidity = self.coordinator.data.get(STATE_HUMIDITY) if self.coordinator.data else None
        if humidity:
            if humidity > DEFAULT_HUMIDITY_THRESHOLD:
                alerts.append(f"Humidity too high: {humidity:.0f}%")
            elif humidity < COMFORT_HUMIDITY_MIN:
                alerts.append(f"Humidity too low: {humidity:.0f}%")

        # Door alert (if egress type)
        if self._check_door_alert():
            door_sensor = self.coordinator.entry.data.get(CONF_DOOR_SENSORS)
            if door_sensor:
                door_state = self.hass.states.get(door_sensor)
                if door_state and door_state.state == "on":
                    last_changed = door_state.last_changed
                    duration = int((dt_util.now() - last_changed).total_seconds() / 60)
                    alerts.append(f"Egress door open for {duration} minutes")

        # Window alert
        if self._check_window_alert():
            window_sensor = self.coordinator.entry.data.get(CONF_WINDOW_SENSORS)
            if window_sensor:
                window_state = self.hass.states.get(window_sensor)
                if window_state and window_state.state == "on":
                    last_changed = window_state.last_changed
                    duration = int((dt_util.now() - last_changed).total_seconds() / 60)
                    alerts.append(f"Window open for {duration} minutes")

        return alerts

    def _check_temperature_alert(self) -> bool:
        """Check if temperature is outside safe range."""
        temp = self.coordinator.data.get(STATE_TEMPERATURE) if self.coordinator.data else None
        if temp is None:
            return False
        return temp > DEFAULT_FAN_TEMP_THRESHOLD or temp < COMFORT_TEMP_MIN

    def _check_humidity_alert(self) -> bool:
        """Check if humidity is outside safe range."""
        humidity = self.coordinator.data.get(STATE_HUMIDITY) if self.coordinator.data else None
        if humidity is None:
            return False
        return humidity > DEFAULT_HUMIDITY_THRESHOLD or humidity < COMFORT_HUMIDITY_MIN

    def _check_door_alert(self) -> bool:
        """Check if egress door has been open too long."""
        door_sensor = self.coordinator.entry.data.get(CONF_DOOR_SENSORS)
        door_type = self.coordinator.entry.data.get(CONF_DOOR_TYPE)
        
        if not door_sensor or door_type != DOOR_TYPE_EGRESS:
            return False
        
        door_state = self.hass.states.get(door_sensor)
        if not door_state or door_state.state != "on":
            return False
        
        # Check if open for more than 10 minutes
        last_changed = door_state.last_changed
        duration = (dt_util.now() - last_changed).total_seconds() / 60
        return duration > 10

    def _check_window_alert(self) -> bool:
        """Check if window has been open too long."""
        window_sensor = self.coordinator.entry.data.get(CONF_WINDOW_SENSORS)
        
        if not window_sensor:
            return False
        
        window_state = self.hass.states.get(window_sensor)
        if not window_state or window_state.state != "on":
            return False
        
        # Check if open for more than 30 minutes
        last_changed = window_state.last_changed
        duration = (dt_util.now() - last_changed).total_seconds() / 60
        return duration > 30


# ============================================================================
# v3.5.0: CENSUS BINARY SENSORS
# ============================================================================


class CameraPersonDetectedSensor(UniversalRoomEntity, BinarySensorEntity):
    """Per-room binary sensor: true when any configured camera sees a person.

    Reads CONF_CAMERA_PERSON_ENTITIES from room config and checks if any
    of them are currently in state 'on'. Gracefully returns False if no
    cameras are configured for this room.
    """

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_icon = "mdi:camera-account"

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "camera_person_detected", "Camera Person Detected")

    @property
    def is_on(self) -> bool:
        """Return True if any room camera detects a person."""
        config = {**self.coordinator.entry.data, **self.coordinator.entry.options}
        camera_entities = config.get(CONF_CAMERA_PERSON_ENTITIES, [])
        if not camera_entities:
            return False

        for entity_id in camera_entities:
            state = self.hass.states.get(entity_id)
            if state and state.state == "on":
                return True
        return False

    @property
    def extra_state_attributes(self) -> dict:
        """Return which cameras are active."""
        config = {**self.coordinator.entry.data, **self.coordinator.entry.options}
        camera_entities = config.get(CONF_CAMERA_PERSON_ENTITIES, [])
        active = []
        for entity_id in camera_entities:
            state = self.hass.states.get(entity_id)
            if state and state.state == "on":
                active.append(entity_id)
        return {
            "configured_cameras": camera_entities,
            "active_cameras": active,
            "camera_count": len(camera_entities),
        }


class URAUnexpectedPersonSensor(BinarySensorEntity):
    """Integration-level: True when cameras see more persons than BLE can account for.

    v3.5.1 upgrade: uses house-level PersonCensus camera total vs person_coordinator
    active BLE count.  camera_total > ble_active_total → is_on = True.

    Gracefully returns False if either data source is unavailable.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:account-alert"
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{DOMAIN}_census_unexpected_person_detected"
        self._attr_name = "Unexpected Person Detected"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "integration")},
            name="Universal Room Automation",
            manufacturer="Universal Room Automation",
            model="Whole House",
            sw_version=VERSION,
        )
        self._camera_total: int = 0
        self._ble_total: int = 0

    @property
    def is_on(self) -> bool:
        """Return True when cameras see more persons than BLE can identify."""
        census = self.hass.data.get(DOMAIN, {}).get("census")
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")

        if not census or not person_coordinator:
            return False

        result = census.last_result
        self._camera_total = result.house.total_persons if result else 0

        # Count active BLE persons (known, currently tracked as home)
        ble_active: list[str] = []
        if person_coordinator.data:
            ble_active = [
                pid for pid, info in person_coordinator.data.items()
                if info.get("tracking_status") == "active"
            ]
        self._ble_total = len(ble_active)

        return self._camera_total > self._ble_total

    @property
    def extra_state_attributes(self) -> dict:
        """Return camera total, ble total, and derived guest count."""
        # Trigger a fresh read so attributes are always in sync with is_on
        census = self.hass.data.get(DOMAIN, {}).get("census")
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")

        camera_total = 0
        ble_total = 0

        if census and census.last_result:
            camera_total = census.last_result.house.total_persons

        if person_coordinator and person_coordinator.data:
            ble_total = len([
                pid for pid, info in person_coordinator.data.items()
                if info.get("tracking_status") == "active"
            ])

        return {
            "camera_total": camera_total,
            "ble_total": ble_total,
            "guest_count": max(0, camera_total - ble_total),
        }


# ============================================================================
# v3.5.2: CENSUS MISMATCH SENSOR
# ============================================================================


class CensusMismatchSensor(BinarySensorEntity):
    """On when camera count and BLE count diverge for an extended period.

    Enabled by default. Useful for automations that respond to unknown persons.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = True

    MISMATCH_THRESHOLD = 2
    MISMATCH_DURATION_MINUTES = 10

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{DOMAIN}_census_mismatch"
        self._attr_name = "Census Mismatch"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "integration")},
            name="Universal Room Automation",
            manufacturer="Universal Room Automation",
            model="Whole House",
            sw_version=VERSION,
        )
        self._mismatch_since = None
        self._camera_count: int = 0
        self._ble_count: int = 0

    @property
    def is_on(self) -> bool | None:
        """Return True when camera count and BLE count diverge for 10+ minutes."""
        census_state = self.hass.states.get(
            "sensor.universal_room_automation_persons_in_house"
        )
        confidence_state = self.hass.states.get(
            "sensor.universal_room_automation_census_confidence"
        )

        if not census_state or not confidence_state:
            return None
        if confidence_state.state == "none":
            return False

        try:
            self._camera_count = int(float(census_state.state))
        except (ValueError, TypeError):
            return None

        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        if not person_coordinator:
            return None

        self._ble_count = sum(
            1 for p in person_coordinator.data.values()
            if p.get("location") not in (None, "unknown", "away")
        )

        difference = abs(self._camera_count - self._ble_count)
        now = dt_util.now()

        if difference >= self.MISMATCH_THRESHOLD:
            if self._mismatch_since is None:
                self._mismatch_since = now
            elapsed = (now - self._mismatch_since).total_seconds() / 60
            return elapsed >= self.MISMATCH_DURATION_MINUTES
        else:
            self._mismatch_since = None
            return False

    @property
    def extra_state_attributes(self) -> dict:
        """Return mismatch details."""
        return {
            "camera_count": self._camera_count,
            "ble_count": self._ble_count,
            "mismatch_since": self._mismatch_since.isoformat() if self._mismatch_since else None,
            "threshold": self.MISMATCH_THRESHOLD,
            "duration_minutes": self.MISMATCH_DURATION_MINUTES,
        }


# ============================================================================
# v3.5.2: PHONE LEFT BEHIND SENSOR (per person, diagnostic)
# ============================================================================


class PersonPhoneLeftBehindSensor(BinarySensorEntity):
    """Diagnostic: BLE says person is home but camera hasn't seen them recently.

    Fires when:
      - BLE places person in a room (not away/unknown)
      - No camera has seen this person in PHONE_LEFT_BEHIND_HOURS (1h)
      - Camera census is NOT currently seeing unidentified persons
        (if census sees people, the phone holder is likely present)
      - Outside sleep hours (10 PM – 7 AM)

    Disabled by default — enable manually if the signal is reliable in your home.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_has_entity_name = True

    PHONE_LEFT_BEHIND_HOURS: float = 1.0
    SLEEP_START_HOUR: int = 22
    SLEEP_END_HOUR: int = 7

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, person_id: str) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        self._person_id = person_id
        self._attr_unique_id = f"{DOMAIN}_person_{person_id.lower().replace(' ', '_')}_phone_left_behind"
        self._attr_name = f"{person_id} Phone Left Behind"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "integration")},
            name="Universal Room Automation",
            manufacturer="Universal Room Automation",
            model="Whole House",
            sw_version=VERSION,
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if phone-left-behind conditions are met."""
        # 1. Check sleep hours — suppress during sleep
        now = dt_util.now()
        hour = now.hour
        if hour >= self.SLEEP_START_HOUR or hour < self.SLEEP_END_HOUR:
            return False

        # 2. Check BLE location
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        if not person_coordinator:
            return None
        person_data = person_coordinator.data.get(self._person_id, {})
        ble_location = person_data.get("location")
        if not ble_location or ble_location in ("unknown", "away"):
            return False

        # 3. If camera census currently sees people, suppress —
        #    the phone holder is likely present (census is evidence of presence)
        census = self.hass.data.get(DOMAIN, {}).get("census")
        if census and census.last_result:
            house = census.last_result.house
            if house.total_persons > 0:
                return False

        # 4. Check camera sighting age — 1 hour threshold
        transit_validator = self.hass.data.get(DOMAIN, {}).get("transit_validator")
        if not transit_validator:
            return None
        sighting = transit_validator.get_last_camera_sighting(
            self._person_id,
            max_age_hours=self.PHONE_LEFT_BEHIND_HOURS,
        )
        return sighting is None

    @property
    def extra_state_attributes(self) -> dict:
        """Return diagnostic details."""
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        transit_validator = self.hass.data.get(DOMAIN, {}).get("transit_validator")

        ble_location = None
        hours_since_sighting = None
        census_persons = None

        if person_coordinator:
            person_data = person_coordinator.data.get(self._person_id, {})
            ble_location = person_data.get("location")

        if transit_validator:
            sighting = transit_validator.get_last_camera_sighting(
                self._person_id, max_age_hours=24.0
            )
            if sighting:
                ts = sighting.get("timestamp")
                if ts:
                    if isinstance(ts, str):
                        from homeassistant.util import dt as dt_util2
                        ts = dt_util2.parse_datetime(ts)
                    if ts:
                        delta = dt_util.now() - ts
                        hours_since_sighting = round(delta.total_seconds() / 3600, 2)

        census = self.hass.data.get(DOMAIN, {}).get("census")
        if census and census.last_result:
            census_persons = census.last_result.house.total_persons

        return {
            "person_id": self._person_id,
            "ble_location": ble_location,
            "hours_since_camera_sighting": hours_since_sighting,
            "phone_left_behind_hours": self.PHONE_LEFT_BEHIND_HOURS,
            "census_persons_in_house": census_persons,
        }


# ============================================================================
# v3.6.0-c1: Presence Coordinator Binary Sensors
# ============================================================================


class HouseOccupiedBinarySensor(BinarySensorEntity):
    """True when any person is detected in the house.

    Entity: binary_sensor.ura_house_occupied
    Device: URA: Presence Coordinator
    """

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_has_entity_name = True
    _attr_icon = "mdi:home-account"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import DOMAIN, VERSION
        self._attr_unique_id = f"{DOMAIN}_house_occupied"
        self._attr_name = "House Occupied"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def is_on(self) -> bool:
        """Return True if house is occupied."""
        from .const import DOMAIN
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return False
        from .domain_coordinators.house_state import HouseState
        return manager.house_state not in (
            HouseState.AWAY, HouseState.VACATION
        )


class HouseSleepingBinarySensor(BinarySensorEntity):
    """True when house is in SLEEP state.

    Entity: binary_sensor.ura_house_sleeping
    Device: URA: Presence Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:sleep"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import DOMAIN, VERSION
        self._attr_unique_id = f"{DOMAIN}_house_sleeping"
        self._attr_name = "House Sleeping"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def is_on(self) -> bool:
        """Return True if house is sleeping."""
        from .const import DOMAIN
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return False
        from .domain_coordinators.house_state import HouseState
        return manager.house_state == HouseState.SLEEP


class GuestModeBinarySensor(BinarySensorEntity):
    """True when house is in GUEST mode.

    Entity: binary_sensor.ura_guest_mode
    Device: URA: Presence Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:account-group"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import DOMAIN, VERSION
        self._attr_unique_id = f"{DOMAIN}_guest_mode"
        self._attr_name = "Guest Mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def is_on(self) -> bool:
        """Return True if in guest mode."""
        from .const import DOMAIN
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return False
        from .domain_coordinators.house_state import HouseState
        return manager.house_state == HouseState.GUEST


# ============================================================================
# v3.6.0-c2: Safety Coordinator Binary Sensors
# ============================================================================


class SafetyAlertBinarySensor(BinarySensorEntity):
    """True when any safety hazard is active.

    Entity: binary_sensor.ura_safety_alert
    Device: URA: Safety Coordinator
    """

    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-alert"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import DOMAIN, VERSION
        self._attr_unique_id = f"{DOMAIN}_safety_coordinator_safety_alert"
        self._attr_name = "Safety Alert"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "safety_coordinator")},
            name="URA: Safety Coordinator",
            manufacturer="Universal Room Automation",
            model="Safety Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def is_on(self) -> bool:
        """Return True if any safety hazard is active."""
        from .const import DOMAIN
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return False
        safety = manager.coordinators.get("safety")
        if safety is None:
            return False
        return len(safety.active_hazards) > 0

    @property
    def extra_state_attributes(self) -> dict:
        """Return hazard details."""
        from .const import DOMAIN
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {"hazard_type": None, "location": None, "severity": None}
        safety = manager.coordinators.get("safety")
        if safety is None or not safety.active_hazards:
            return {"hazard_type": None, "location": None, "severity": None}

        # Return the worst active hazard
        worst = max(
            safety.active_hazards.values(),
            key=lambda h: h.severity,
        )
        attrs = {
            "hazard_type": worst.type.value,
            "location": worst.location,
            "severity": worst.severity.name.lower(),
            "active_count": len(safety.active_hazards),
        }
        # v3.6.0.3: All active hazards, not just worst
        attrs["all_hazards"] = [
            {"hazard_type": h.type.value, "location": h.location,
             "severity": h.severity.name.lower()}
            for h in safety.active_hazards.values()
        ]
        return attrs

    async def async_added_to_hass(self) -> None:
        """Subscribe to safety entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SAFETY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SAFETY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle safety entity update signal."""
        self.async_write_ha_state()


class SafetyWaterLeakBinarySensor(AggregationEntity, BinarySensorEntity):
    """Water leak/flooding indicator.

    v3.6.0.3: Glanceable binary sensor — any water problem?
    Entity: binary_sensor.ura_safety_water_leak
    """

    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_has_entity_name = True
    _attr_icon = "mdi:water-alert"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_safety_water_leak"
        self._attr_name = "Safety Water Leak"
        from homeassistant.helpers.device_registry import DeviceInfo
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "safety_coordinator")},
        )

    @property
    def is_on(self) -> bool:
        """Return True if any water leak or flooding hazard active."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return False
        safety = manager.coordinators.get("safety")
        if safety is None:
            return False
        status = safety.get_water_leak_status()
        return status.get("active", False)

    @property
    def extra_state_attributes(self) -> dict:
        """Return water leak details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        safety = manager.coordinators.get("safety")
        if safety is None:
            return {}
        status = safety.get_water_leak_status()
        if not status.get("active"):
            return {}
        return {
            "locations": status.get("locations", []),
            "sensor_ids": status.get("sensor_ids", []),
            "sensor_count": status.get("sensor_count", 0),
            "flooding_escalated": status.get("flooding_escalated", False),
            "first_detected": status.get("first_detected"),
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to safety entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SAFETY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SAFETY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle safety entity update signal."""
        self.async_write_ha_state()


class SafetyAirQualityBinarySensor(AggregationEntity, BinarySensorEntity):
    """Air quality problem indicator.

    v3.6.0.3: Glanceable binary sensor — any air quality problem?
    Entity: binary_sensor.ura_safety_air_quality
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_has_entity_name = True
    _attr_icon = "mdi:air-filter"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_safety_air_quality"
        self._attr_name = "Safety Air Quality"
        from homeassistant.helpers.device_registry import DeviceInfo
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "safety_coordinator")},
        )

    @property
    def is_on(self) -> bool:
        """Return True if any air quality hazard active."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return False
        safety = manager.coordinators.get("safety")
        if safety is None:
            return False
        status = safety.get_air_quality_status()
        return status.get("active", False)

    @property
    def extra_state_attributes(self) -> dict:
        """Return air quality hazard details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        safety = manager.coordinators.get("safety")
        if safety is None:
            return {}
        status = safety.get_air_quality_status()
        if not status.get("active"):
            return {}
        return {
            "hazard_types": status.get("hazard_types", []),
            "locations": status.get("locations", []),
            "sensor_ids": status.get("sensor_ids", []),
            "worst_severity": status.get("worst_severity"),
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to safety entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SAFETY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SAFETY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle safety entity update signal."""
        self.async_write_ha_state()


# ============================================================================
# v3.6.0-c3: Security Coordinator binary sensors
# ============================================================================


class SecurityAlertBinarySensor(BinarySensorEntity):
    """True when a security alert is active.

    Entity: binary_sensor.ura_security_alert
    Device: URA: Security Coordinator
    """

    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-alert"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import DOMAIN, VERSION
        self._attr_unique_id = f"{DOMAIN}_security_coordinator_security_alert"
        self._attr_name = "Security Alert"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "security_coordinator")},
            name="URA: Security Coordinator",
            manufacturer="Universal Room Automation",
            model="Security Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def is_on(self) -> bool:
        """Return True if a security alert is active."""
        from .const import DOMAIN
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return False
        security = manager.coordinators.get("security")
        if security is None:
            return False
        return security.active_alert

    @property
    def extra_state_attributes(self) -> dict:
        """Return alert details."""
        from .const import DOMAIN
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {"alert_type": None, "armed_state": None}
        security = manager.coordinators.get("security")
        if security is None or not security.active_alert:
            return {"alert_type": None, "armed_state": None}
        details = security.alert_details
        return {
            "alert_type": details.get("type"),
            "armed_state": security.armed_state.value,
            "entity_id": details.get("entity_id"),
            "timestamp": details.get("timestamp"),
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to security entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SECURITY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle security entity update signal."""
        self.async_write_ha_state()


# ============================================================================
# v3.6.29: Notification Manager Binary Sensor
# ============================================================================


class NMActiveAlertBinarySensor(BinarySensorEntity):
    """True when an unacknowledged CRITICAL/HIGH alert exists.

    Entity: binary_sensor.ura_notification_active_alert
    Device: URA: Notification Manager
    """

    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_has_entity_name = True
    _attr_icon = "mdi:bell-alert"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import DOMAIN, VERSION
        self._attr_unique_id = f"{DOMAIN}_notification_active_alert"
        self._attr_name = "Notification Active Alert"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "notification_manager")},
            name="URA: Notification Manager",
            manufacturer="Universal Room Automation",
            model="Notification Manager",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def is_on(self) -> bool:
        """Return True if an active alert exists."""
        from .const import DOMAIN
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return False
        return nm.active_alert

    @property
    def extra_state_attributes(self) -> dict:
        """Return alert state details."""
        from .const import DOMAIN
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return {"alert_state": "not_initialized"}
        return {"alert_state": nm.alert_state}

    async def async_added_to_hass(self) -> None:
        """Subscribe to NM alert state changes."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NM_ALERT_STATE_CHANGED
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_NM_ALERT_STATE_CHANGED, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle NM alert state change signal."""
        self.async_write_ha_state()


# ============================================================================
# v3.7.3: Energy Coordinator binary sensors
# ============================================================================


class EnergyEnvoyAvailableBinarySensor(AggregationEntity, BinarySensorEntity):
    """True when the Envoy is responding (SOC + storage mode readable).

    When off, the Energy Coordinator holds current state and issues no commands.
    Entity: binary_sensor.ura_energy_coordinator_envoy_available
    Device: URA: Energy Coordinator
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_icon = "mdi:solar-panel"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_envoy_available"
        self._attr_name = "Energy Envoy Available"
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "energy_coordinator")},
            name="URA: Energy Coordinator",
            manufacturer="Universal Room Automation",
            model="Energy Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if Envoy is available."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.battery_strategy.envoy_available

    @property
    def extra_state_attributes(self) -> dict:
        """Return Envoy availability details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        summary = energy.get_energy_summary()
        return {
            "unavailable_count": summary.get("envoy_unavailable_count", 0),
            "last_available": summary.get("envoy_last_available"),
        }


class EnergyL1ChargerBinarySensor(AggregationEntity, BinarySensorEntity):
    """L1 charger status — on when any Moes plug socket is on.

    Entity: binary_sensor.ura_energy_l1_charger_garage_a
    Device: URA: Energy Coordinator
    """

    _attr_device_class = BinarySensorDeviceClass.PLUG
    _attr_has_entity_name = True
    _attr_icon = "mdi:ev-plug-type1"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_l1_charger_garage_a"
        self._attr_name = "L1 Charger Garage A"
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "energy_coordinator")},
            name="URA: Energy Coordinator",
            manufacturer="Universal Room Automation",
            model="Energy Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if any L1 charger socket is on (charging)."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.l1_charger_active
