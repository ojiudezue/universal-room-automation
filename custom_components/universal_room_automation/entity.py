"""Base entity for Universal Room Automation."""
#
# Universal Room Automation vv4.2.0
# Build: 2026-01-02
# File: entity.py
#

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL, VERSION
from .coordinator import UniversalRoomCoordinator


class UniversalRoomEntity(CoordinatorEntity[UniversalRoomCoordinator]):
    """Base entity for Universal Room Automation."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UniversalRoomCoordinator,
        entity_type: str,
        name: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        
        room_name = coordinator.entry.data.get("room_name", "Unknown Room")
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{entity_type}"
        self._attr_name = name
        
        # Device info - all entities belong to the room device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=room_name,
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=VERSION,
        )
