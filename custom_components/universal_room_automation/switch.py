"""Switch platform for Universal Room Automation."""
#
# Universal Room Automation v3.6.18
# Build: 2026-01-02
# File: switch.py
#

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_DOMAIN_COORDINATORS_ENABLED,
    CONF_ENTRY_TYPE,
    CONF_PRESENCE_ENABLED,
    CONF_SAFETY_ENABLED,
    CONF_SECURITY_ENABLED,
    DOMAIN,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    ENTRY_TYPE_INTEGRATION,
    VERSION,
)
from .coordinator import UniversalRoomCoordinator
from .entity import UniversalRoomEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Universal Room Automation switches."""
    entry_type = entry.data.get(CONF_ENTRY_TYPE)

    # v3.6.0-c2.4: Integration entry — master coordinators toggle
    if entry_type == ENTRY_TYPE_INTEGRATION:
        async_add_entities([DomainCoordinatorsSwitch(hass, entry)])
        return

    # v3.6.0-c2.4: CM entry — per-coordinator toggles
    if entry_type == ENTRY_TYPE_COORDINATOR_MANAGER:
        async_add_entities([
            CoordinatorEnabledSwitch(
                hass, entry,
                coordinator_id="presence",
                conf_key=CONF_PRESENCE_ENABLED,
                name="Presence Coordinator",
                icon="mdi:account-group",
                device_id="presence_coordinator",
                device_name="URA: Presence Coordinator",
                device_model="Presence Coordinator",
            ),
            CoordinatorEnabledSwitch(
                hass, entry,
                coordinator_id="safety",
                conf_key=CONF_SAFETY_ENABLED,
                name="Safety Coordinator",
                icon="mdi:shield-check",
                device_id="safety_coordinator",
                device_name="URA: Safety Coordinator",
                device_model="Safety Coordinator",
            ),
            CoordinatorEnabledSwitch(
                hass, entry,
                coordinator_id="security",
                conf_key=CONF_SECURITY_ENABLED,
                name="Security Coordinator",
                icon="mdi:shield-lock",
                device_id="security_coordinator",
                device_name="URA: Security Coordinator",
                device_model="Security Coordinator",
            ),
        ])
        return

    # Room entry — standard room switches
    if entry.entry_id not in hass.data.get(DOMAIN, {}):
        return
    coordinator: UniversalRoomCoordinator = hass.data[DOMAIN][entry.entry_id]

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


# ============================================================================
# v3.6.0-c2.4: Domain Coordinators Master Toggle
# ============================================================================


class DomainCoordinatorsSwitch(SwitchEntity):
    """Master switch to enable/disable the domain coordinator system.

    Entity: switch.ura_domain_coordinators
    Device: Universal Room Automation (integration device)

    When turned off, the CoordinatorManager is not created on next reload
    and all coordinator sensors show default/unavailable values.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:robot"
    _attr_name = "Domain Coordinators"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_domain_coordinators_enabled"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "integration")},
            name="Universal Room Automation",
            manufacturer="Universal Room Automation",
            model="Whole House",
            sw_version=VERSION,
        )

    @property
    def is_on(self) -> bool:
        """Return True if domain coordinators are enabled."""
        merged = {**self._entry.data, **self._entry.options}
        return merged.get(CONF_DOMAIN_COORDINATORS_ENABLED, False)

    async def async_turn_on(self, **kwargs) -> None:
        """Enable domain coordinators."""
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_DOMAIN_COORDINATORS_ENABLED: True},
        )
        await self.hass.config_entries.async_reload(self._entry.entry_id)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable domain coordinators."""
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_DOMAIN_COORDINATORS_ENABLED: False},
        )
        await self.hass.config_entries.async_reload(self._entry.entry_id)


# ============================================================================
# v3.6.0-c2.4: Per-Coordinator Enable/Disable Toggle
# ============================================================================


class CoordinatorEnabledSwitch(SwitchEntity):
    """Enable/disable an individual domain coordinator.

    Entity: switch.ura_{coordinator_id}_coordinator_enabled
    Device: The coordinator's own device

    Stores the enabled state in the CM entry's options. Takes effect
    on next integration reload.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator_id: str,
        conf_key: str,
        name: str,
        icon: str,
        device_id: str,
        device_name: str,
        device_model: str,
    ) -> None:
        """Initialize."""
        self.hass = hass
        self._entry = entry
        self._coordinator_id = coordinator_id
        self._conf_key = conf_key
        self._attr_unique_id = f"{DOMAIN}_{coordinator_id}_coordinator_enabled"
        self._attr_name = f"Enabled"
        self._attr_icon = icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_name,
            manufacturer="Universal Room Automation",
            model=device_model,
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def is_on(self) -> bool:
        """Return True if this coordinator is enabled."""
        merged = {**self._entry.data, **self._entry.options}
        return merged.get(self._conf_key, True)

    async def async_turn_on(self, **kwargs) -> None:
        """Enable this coordinator."""
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, self._conf_key: True},
        )
        # Reload the integration entry to re-register the coordinator
        for ce in self.hass.config_entries.async_entries(DOMAIN):
            if ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                await self.hass.config_entries.async_reload(ce.entry_id)
                break

    async def async_turn_off(self, **kwargs) -> None:
        """Disable this coordinator."""
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, self._conf_key: False},
        )
        for ce in self.hass.config_entries.async_entries(DOMAIN):
            if ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                await self.hass.config_entries.async_reload(ce.entry_id)
                break


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
