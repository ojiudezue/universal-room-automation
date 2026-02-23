"""Switch platform for Universal Room Automation."""
#
# Universal Room Automation v3.3.5.9
# Build: 2026-01-02
# File: switch.py
#

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .coordinator import UniversalRoomCoordinator
from .entity import UniversalRoomEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Universal Room Automation switches."""
    coordinator: UniversalRoomCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    # Core switches (enabled by default)
    entities = [
        AutomationSwitch(coordinator),
        OverrideOccupiedSwitch(coordinator),
        OverrideVacantSwitch(coordinator),
        ClimateAutomationSwitch(coordinator),
        CoverAutomationSwitch(coordinator),
        ManualModeSwitch(coordinator),
    ]
    
    async_add_entities(entities)
    _LOGGER.info(
        "Set up %d switches for room: %s",
        len(entities),
        entry.data.get("room_name")
    )


class AutomationSwitch(UniversalRoomEntity, SwitchEntity, RestoreEntity):
    """Switch to enable/disable room automation."""

    _attr_icon = "mdi:home-automation"

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "automation", "Automation")
        self._attr_is_on = True  # Default to enabled

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_is_on = last_state.state == "on"

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on automation."""
        self._attr_is_on = True
        self.async_write_ha_state()
        _LOGGER.info("Automation enabled for room: %s", self.coordinator.entry.data.get("room_name"))

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off automation."""
        self._attr_is_on = False
        self.async_write_ha_state()
        _LOGGER.info("Automation disabled for room: %s", self.coordinator.entry.data.get("room_name"))


class OverrideOccupiedSwitch(UniversalRoomEntity, SwitchEntity):
    """Switch to override room as occupied."""

    _attr_icon = "mdi:account-check"

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "override_occupied", "Override Occupied")
        self._attr_is_on = False

    async def async_turn_on(self, **kwargs) -> None:
        """Force room to occupied state."""
        self._attr_is_on = True
        self.async_write_ha_state()
        _LOGGER.info("Override occupied enabled for room: %s", self.coordinator.entry.data.get("room_name"))

    async def async_turn_off(self, **kwargs) -> None:
        """Remove occupied override."""
        self._attr_is_on = False
        self.async_write_ha_state()
        _LOGGER.info("Override occupied disabled for room: %s", self.coordinator.entry.data.get("room_name"))


class OverrideVacantSwitch(UniversalRoomEntity, SwitchEntity):
    """Switch to override room as vacant."""

    _attr_icon = "mdi:account-off"

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "override_vacant", "Override Vacant")
        self._attr_is_on = False

    async def async_turn_on(self, **kwargs) -> None:
        """Force room to vacant state."""
        self._attr_is_on = True
        self.async_write_ha_state()
        _LOGGER.info("Override vacant enabled for room: %s", self.coordinator.entry.data.get("room_name"))

    async def async_turn_off(self, **kwargs) -> None:
        """Remove vacant override."""
        self._attr_is_on = False
        self.async_write_ha_state()
        _LOGGER.info("Override vacant disabled for room: %s", self.coordinator.entry.data.get("room_name"))


class ClimateAutomationSwitch(UniversalRoomEntity, SwitchEntity, RestoreEntity):
    """Switch to enable/disable climate-specific automation."""

    _attr_icon = "mdi:thermostat-auto"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "climate_automation", "Climate Automation")
        self._attr_is_on = True  # Default to enabled

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_is_on = last_state.state == "on"

    @property
    def available(self) -> bool:
        """Switch is always available."""
        return True

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on climate automation."""
        self._attr_is_on = True
        self.async_write_ha_state()
        _LOGGER.info("Climate automation enabled for room: %s", self.coordinator.entry.data.get("room_name"))

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off climate automation."""
        self._attr_is_on = False
        self.async_write_ha_state()
        _LOGGER.info("Climate automation disabled for room: %s", self.coordinator.entry.data.get("room_name"))


class CoverAutomationSwitch(UniversalRoomEntity, SwitchEntity, RestoreEntity):
    """Switch to enable/disable cover automation."""

    _attr_icon = "mdi:window-shutter-auto"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "cover_automation", "Cover Automation")
        self._attr_is_on = True  # Default to enabled

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_is_on = last_state.state == "on"

    @property
    def available(self) -> bool:
        """Switch is always available."""
        return True

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on cover automation."""
        self._attr_is_on = True
        self.async_write_ha_state()
        _LOGGER.info("Cover automation enabled for room: %s", self.coordinator.entry.data.get("room_name"))

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off cover automation."""
        self._attr_is_on = False
        self.async_write_ha_state()
        _LOGGER.info("Cover automation disabled for room: %s", self.coordinator.entry.data.get("room_name"))


class ManualModeSwitch(UniversalRoomEntity, SwitchEntity, RestoreEntity):
    """Switch to force manual control mode."""

    _attr_icon = "mdi:hand-back-right"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, "manual_mode", "Manual Mode")
        self._attr_is_on = False  # Default to disabled

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_is_on = last_state.state == "on"

    @property
    def available(self) -> bool:
        """Switch is always available."""
        return True

    async def async_turn_on(self, **kwargs) -> None:
        """Enable manual mode (disables all automation)."""
        self._attr_is_on = True
        self.async_write_ha_state()
        _LOGGER.info("Manual mode enabled for room: %s", self.coordinator.entry.data.get("room_name"))

    async def async_turn_off(self, **kwargs) -> None:
        """Disable manual mode (allows automation)."""
        self._attr_is_on = False
        self.async_write_ha_state()
        _LOGGER.info("Manual mode disabled for room: %s", self.coordinator.entry.data.get("room_name"))
