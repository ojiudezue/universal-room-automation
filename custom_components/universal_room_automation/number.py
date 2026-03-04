"""Number platform for Universal Room Automation."""
#
# Universal Room Automation v3.6.32
# Build: 2026-01-02
# File: number.py
#

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import UnitOfTemperature, UnitOfTime, PERCENTAGE

from .const import (
    DOMAIN,
    COMFORT_TEMP_MIN,
    COMFORT_TEMP_MAX,
    COMFORT_HUMIDITY_MAX,
    DEFAULT_OCCUPANCY_TIMEOUT,
)
from .coordinator import UniversalRoomCoordinator
from .entity import UniversalRoomEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Universal Room Automation number entities."""
    coordinator: UniversalRoomCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    entities = [
        TimeoutOverrideNumber(coordinator),
        ComfortTempMinNumber(coordinator),
        ComfortTempMaxNumber(coordinator),
        ComfortHumidityMaxNumber(coordinator),
    ]
    
    async_add_entities(entities)
    _LOGGER.info(
        "Set up %d number entities for room: %s",
        len(entities),
        entry.data.get("room_name")
    )


class TimeoutOverrideNumber(UniversalRoomEntity, NumberEntity):
    """Number entity for temporary occupancy timeout override."""

    _attr_icon = "mdi:timer-cog"
    _attr_native_min_value = 60
    _attr_native_max_value = 3600
    _attr_native_step = 30
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, "timeout_override", "Timeout Override")
        self._attr_native_value = coordinator.entry.data.get("occupancy_timeout", DEFAULT_OCCUPANCY_TIMEOUT)

    @property
    def native_value(self) -> float:
        """Return current timeout value."""
        return self.coordinator._occupancy_timeout

    @property
    def available(self) -> bool:
        """Number is always available."""
        return True

    async def async_set_native_value(self, value: float) -> None:
        """Set new timeout value."""
        self.coordinator._occupancy_timeout = int(value)
        self.async_write_ha_state()
        _LOGGER.info(
            "Timeout override set to %d seconds for room: %s",
            int(value),
            self.coordinator.entry.data.get("room_name")
        )


class ComfortTempMinNumber(UniversalRoomEntity, NumberEntity):
    """Number entity for minimum comfort temperature."""

    _attr_icon = "mdi:thermometer-low"
    _attr_native_min_value = 60
    _attr_native_max_value = 80
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, "comfort_temp_min", "Comfort Temperature Min")
        self._value = COMFORT_TEMP_MIN

    @property
    def native_value(self) -> float:
        """Return current minimum comfort temperature."""
        return self._value

    @property
    def available(self) -> bool:
        """Number is always available."""
        return True

    async def async_set_native_value(self, value: float) -> None:
        """Set new minimum comfort temperature."""
        self._value = value
        self.async_write_ha_state()
        _LOGGER.info(
            "Comfort temp min set to %.1f°F for room: %s",
            value,
            self.coordinator.entry.data.get("room_name")
        )


class ComfortTempMaxNumber(UniversalRoomEntity, NumberEntity):
    """Number entity for maximum comfort temperature."""

    _attr_icon = "mdi:thermometer-high"
    _attr_native_min_value = 65
    _attr_native_max_value = 85
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, "comfort_temp_max", "Comfort Temperature Max")
        self._value = COMFORT_TEMP_MAX

    @property
    def native_value(self) -> float:
        """Return current maximum comfort temperature."""
        return self._value

    @property
    def available(self) -> bool:
        """Number is always available."""
        return True

    async def async_set_native_value(self, value: float) -> None:
        """Set new maximum comfort temperature."""
        self._value = value
        self.async_write_ha_state()
        _LOGGER.info(
            "Comfort temp max set to %.1f°F for room: %s",
            value,
            self.coordinator.entry.data.get("room_name")
        )


class ComfortHumidityMaxNumber(UniversalRoomEntity, NumberEntity):
    """Number entity for maximum comfort humidity."""

    _attr_icon = "mdi:water-percent"
    _attr_native_min_value = 40
    _attr_native_max_value = 70
    _attr_native_step = 5
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, "comfort_humidity_max", "Comfort Humidity Max")
        self._value = COMFORT_HUMIDITY_MAX

    @property
    def native_value(self) -> float:
        """Return current maximum comfort humidity."""
        return self._value

    @property
    def available(self) -> bool:
        """Number is always available."""
        return True

    async def async_set_native_value(self, value: float) -> None:
        """Set new maximum comfort humidity."""
        self._value = value
        self.async_write_ha_state()
        _LOGGER.info(
            "Comfort humidity max set to %.0f%% for room: %s",
            value,
            self.coordinator.entry.data.get("room_name")
        )
