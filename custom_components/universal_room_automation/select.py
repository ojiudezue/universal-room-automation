"""Select platform for Universal Room Automation."""
#
# Universal Room Automation v3.6.26
# File: select.py
# v3.6.0-c1: Added house state override and zone presence mode selects
#

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ENTRY_TYPE,
    DOMAIN,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ZONE,
    ENTRY_TYPE_ZONE_MANAGER,
    HOUSE_STATE_OVERRIDE_OPTIONS,
    VERSION,
    ZONE_PRESENCE_OVERRIDE_OPTIONS,
)
from .coordinator import UniversalRoomCoordinator
from .entity import UniversalRoomEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Universal Room Automation select entities."""
    entry_type = entry.data.get(CONF_ENTRY_TYPE)

    # v3.6.0-c1: Integration entry — house state override on URA device
    if entry_type == ENTRY_TYPE_INTEGRATION:
        entities = [
            IntegrationHouseStateOverrideSelect(hass, entry),
        ]
        async_add_entities(entities)
        return

    # v3.6.0-c1: Coordinator Manager entry — house state override on CM + Presence devices
    if entry_type == ENTRY_TYPE_COORDINATOR_MANAGER:
        entities = [
            CMHouseStateOverrideSelect(hass, entry),
            PresenceHouseStateOverrideSelect(hass, entry),
        ]
        async_add_entities(entities)
        return

    # v3.6.0-c1: Zone Manager entry — create zone presence mode selects for all zones
    if entry_type == ENTRY_TYPE_ZONE_MANAGER:
        merged = {**entry.data, **entry.options}
        zones_data = merged.get("zones", {})
        entities = []
        for zone_name in zones_data:
            # v3.6.0-c2.1: Use raw zone name to match aggregation.py's
            # ZoneSensorBase identifiers — f"zone_{zone}" with zone as-is.
            # Previously used zone_slug (lowercased+underscored) which
            # created mismatched device identifiers and "Unnamed device" spam.
            zone_identifier = f"zone_{zone_name}"
            entities.append(
                ZonePresenceModeSelect(hass, zone_name, zone_identifier)
            )
        if entities:
            async_add_entities(entities)
            _LOGGER.info(
                "Set up %d zone presence mode selects", len(entities)
            )
        return

    # Legacy zone entry — no selects (migrated to Zone Manager)
    if entry_type == ENTRY_TYPE_ZONE:
        return

    # Room entry — automation mode select
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


# ============================================================================
# Room-level select
# ============================================================================


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


# ============================================================================
# v3.6.0-c1: House State Override Selects
# ============================================================================


class _HouseStateOverrideSelectBase(SelectEntity):
    """Base class for house state override select entities.

    Both the integration device and CM device get one of these.
    They share the same backing state (the HouseStateMachine override).

    v3.6.0-c2.4: available=False when coordinator_manager is not running,
    which grays out the dropdown in the HA UI.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-switch-outline"
    _attr_options = HOUSE_STATE_OVERRIDE_OPTIONS

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry

    @property
    def available(self) -> bool:
        """Return False when coordinator_manager is not running."""
        return self.hass.data.get(DOMAIN, {}).get("coordinator_manager") is not None

    @property
    def current_option(self) -> str:
        """Return current override (or 'auto' if no override)."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "auto"
        presence = manager.coordinators.get("presence")
        if presence is not None:
            return presence.get_house_state_override()
        # Fallback: check state machine directly
        if manager.house_state_machine.is_overridden:
            return str(manager.house_state_machine.state)
        return "auto"

    async def async_select_option(self, option: str) -> None:
        """Set house state override."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            _LOGGER.warning("Cannot set house state: coordinator manager not initialized")
            return

        presence = manager.coordinators.get("presence")
        if presence is not None:
            presence.set_house_state_override(option)
        else:
            # Direct state machine control if Presence not registered
            from .domain_coordinators.house_state import HouseState
            if option == "auto":
                manager.house_state_machine.clear_override()
            else:
                try:
                    manager.house_state_machine.set_override(HouseState(option))
                except ValueError:
                    _LOGGER.warning("Invalid house state: %s", option)
                    return

        self.async_write_ha_state()
        _LOGGER.info("House state override set to: %s", option)


class IntegrationHouseStateOverrideSelect(_HouseStateOverrideSelectBase):
    """House state override on the URA integration device.

    Entity: select.ura_house_state_override
    Device: Universal Room Automation (integration device)
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_house_state_override"
        self._attr_name = "House State Override"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "integration")},
            name="Universal Room Automation",
            manufacturer="Universal Room Automation",
            model="Whole House",
            sw_version=VERSION,
        )


class CMHouseStateOverrideSelect(_HouseStateOverrideSelectBase):
    """House state override on the Coordinator Manager device.

    Entity: select.ura_cm_house_state_override
    Device: URA: Coordinator Manager
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_cm_house_state_override"
        self._attr_name = "House State Override"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )


class PresenceHouseStateOverrideSelect(_HouseStateOverrideSelectBase):
    """House state override on the Presence Coordinator device.

    Entity: select.ura_presence_house_state_override
    Device: URA: Presence Coordinator
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_presence_house_state_override"
        self._attr_name = "House State Override"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )


# ============================================================================
# v3.6.0-c1: Zone Presence Mode Select (future — added per zone device)
# ============================================================================

class ZonePresenceModeSelect(SelectEntity):
    """Zone presence mode override on a zone device.

    Entity: select.ura_{zone_name}_presence_mode
    Device: URA: Zone {zone_name}
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:map-marker-radius"
    _attr_options = ZONE_PRESENCE_OVERRIDE_OPTIONS

    def __init__(
        self,
        hass: HomeAssistant,
        zone_name: str,
        zone_identifier: str,
    ) -> None:
        """Initialize."""
        self.hass = hass
        self._zone_name = zone_name
        zone_slug = zone_name.lower().replace(" ", "_")
        self._attr_unique_id = f"{DOMAIN}_{zone_slug}_presence_mode"
        self._attr_name = f"{zone_name} Presence Mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, zone_identifier)},
        )

    @property
    def current_option(self) -> str:
        """Return current zone presence mode."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "auto"
        presence = manager.coordinators.get("presence")
        if presence is None:
            return "auto"
        tracker = presence.zone_trackers.get(self._zone_name)
        if tracker is None:
            return "auto"
        if tracker.is_overridden:
            return tracker._override or "auto"
        return "auto"

    async def async_select_option(self, option: str) -> None:
        """Set zone presence mode override."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return
        presence = manager.coordinators.get("presence")
        if presence is None:
            return
        tracker = presence.zone_trackers.get(self._zone_name)
        if tracker is None:
            _LOGGER.warning("No zone tracker for: %s", self._zone_name)
            return

        tracker.set_override(option)
        self.async_write_ha_state()
        _LOGGER.info(
            "Zone %s presence mode set to: %s",
            self._zone_name, option,
        )
