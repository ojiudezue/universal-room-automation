"""Select platform for Universal Room Automation."""
#
# Universal Room Automation v3.4.4
# Build: 2026-01-02
# File: select.py
#

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import UniversalRoomCoordinator
from .entity import UniversalRoomEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Universal Room Automation select entities."""
    coordinator: UniversalRoomCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    entities = [
        AutomationModeSelect(coordinator),
    ]
    
    async_add_entities(entities)
    _LOGGER.info(
        "Set up %d select entities for room: %s",
        len(entities),
        entry.data.get("room_name")
    )


class AutomationModeSelect(UniversalRoomEntity, SelectEntity):
    """Select entity for automation mode."""

    _attr_icon = "mdi:tune"
    _attr_options = ["auto", "manual", "learning", "eco", "comfort"]

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator, "automation_mode", "Automation Mode")
        self._attr_current_option = "auto"

    @property
    def current_option(self) -> str:
        """Return current automation mode."""
        return self._attr_current_option

    async def async_select_option(self, option: str) -> None:
        """Set new automation mode."""
        self._attr_current_option = option
        self.async_write_ha_state()
        _LOGGER.info(
            "Automation mode set to '%s' for room: %s",
            option,
            self.coordinator.entry.data.get("room_name")
        )
        
        # TODO: Implement mode-specific behavior
        # auto: Normal automation
        # manual: Disable all automation
        # learning: Collect data, minimal intervention
        # eco: Prioritize energy savings
        # comfort: Prioritize comfort over efficiency
