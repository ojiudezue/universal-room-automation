"""Base entity for Universal Room Automation."""
#
# Universal Room Automation vv5.78.0
# Build: 2026-01-02
# File: entity.py
#

import logging

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL, VERSION
from .coordinator import UniversalRoomCoordinator

_LOGGER = logging.getLogger(__name__)


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

    # D3-AREA-INHERIT (2026-08-12): after the first entity registers, the
    # shared room device exists in the device registry. Stamp its area_id
    # from the room's CONF_AREA_ID via the supported (non-deprecated)
    # dr.async_update_device(device_id, area_id=...) call.
    #
    # HA source refs (verified 2026-08-12):
    #   - DeviceInfo.suggested_area (and DeviceEntry.suggested_area) are
    #     deprecated with breaks_in_ha_version="2026.9" — see
    #     homeassistant/helpers/device_registry.py:446-452 and:348-349,
    #     :1342-1357 (passing suggested_area to async_update_device logs a
    #     ReportBehavior break warning for 2026.9.0). We do NOT use it.
    #   - async_update_device(device_id, area_id=...) is the durable write
    #     (device_registry.py:1317-1346, area_id is a supported kwarg,
    #     no deprecation).
    #
    # Only-when-unset guard preserves ALL operator manual choices:
    #   - Existing device with area_id set by operator: skipped.
    #   - Existing entity with per-entity area_id set by operator in
    #     entity_registry: entity_registry.area_id wins over device.area_id
    #     for entity resolution, so a device write here cannot override it.
    #
    # Kill switch: leave CONF_AREA_ID unset (or empty) on the room config
    # and this whole method is a no-op.
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        try:
            configured_area = self.coordinator._get_room_area()
        except Exception:  # noqa: BLE001 — never break entity add
            configured_area = None
        if not configured_area:
            return
        from homeassistant.helpers import device_registry as dr  # noqa: PLC0415
        dev_reg = dr.async_get(self.hass)
        entry_id = self.coordinator.entry.entry_id
        device = dev_reg.async_get_device(identifiers={(DOMAIN, entry_id)})
        if device is None:
            # Device not yet present (shouldn't happen: async_added_to_hass
            # runs after platform-managed device registration). Silent
            # skip — next sibling's add will retry.
            return
        if device.area_id is not None:
            return  # Operator-set or previously-inherited; do not clobber.
        try:
            dev_reg.async_update_device(device.id, area_id=configured_area)
            _LOGGER.info(
                "URA room device %s inherited area_id=%s from CONF_AREA_ID",
                entry_id, configured_area,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "URA room device %s: async_update_device(area_id=%s) failed: %s",
                entry_id, configured_area, exc,
            )
