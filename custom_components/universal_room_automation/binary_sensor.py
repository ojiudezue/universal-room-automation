"""Binary sensor platform for Universal Room Automation."""
#
# Universal Room Automation v3.3.5.5
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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    ICON_OCCUPIED,
    ICON_VACANT,
    ICON_MOTION,
    ICON_PRESENCE,
    ICON_DARK,
    ICON_ROOM_ALERT,
    STATE_OCCUPIED,
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
)
from .coordinator import UniversalRoomCoordinator
from .entity import UniversalRoomEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Universal Room Automation binary sensors."""
    from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_INTEGRATION, ENTRY_TYPE_ZONE

    # Check if this is an integration entry (aggregation binary sensors)
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
        from .aggregation import async_setup_aggregation_binary_sensors
        await async_setup_aggregation_binary_sensors(hass, entry, async_add_entities)
        return

    # v3.3.5.6: Zone entry - set up zone-specific binary sensors
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE:
        from .aggregation import async_setup_zone_binary_sensors
        await async_setup_zone_binary_sensors(hass, entry, async_add_entities)
        return

    # Room entry - normal binary sensor setup
    coordinator: UniversalRoomCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    # Core binary sensors (enabled by default)
    entities = [
        OccupiedBinarySensor(coordinator),
        MotionDetectedBinarySensor(coordinator),
        PresenceDetectedBinarySensor(coordinator),
        DarkBinarySensor(coordinator),
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
        return {
            ATTR_LAST_MOTION: self.coordinator._last_motion_time.isoformat()
            if self.coordinator._last_motion_time else None,
            ATTR_TIMEOUT: self.coordinator.data.get("timeout_remaining", 0) if self.coordinator.data else 0,
        }


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
