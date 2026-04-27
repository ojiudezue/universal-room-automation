"""Number platform for Universal Room Automation."""
#
# Universal Room Automation v4.2.10
# Build: 2026-01-02
# File: number.py
#

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.const import UnitOfTemperature, UnitOfTime, PERCENTAGE

from .const import (
    DOMAIN,
    CONF_ENTRY_TYPE,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    COMFORT_TEMP_MIN,
    COMFORT_TEMP_MAX,
    COMFORT_HUMIDITY_MAX,
    DEFAULT_OCCUPANCY_TIMEOUT,
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
    """Set up Universal Room Automation number entities."""
    # v4.2.2: Coordinator Manager entry gets HVAC number entities
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
        entities = [
            ZoneEntryDwellNumber(hass, entry),
            # v4.2.10: Off-peak drain target numbers
            OffPeakDrainNumber(hass, entry, "excellent", 10, 5, 50),
            OffPeakDrainNumber(hass, entry, "good", 15, 5, 60),
            OffPeakDrainNumber(hass, entry, "moderate", 20, 5, 70),
            OffPeakDrainNumber(hass, entry, "poor", 30, 5, 80),
        ]
        async_add_entities(entities)
        _LOGGER.info("Set up %d CM number entities", len(entities))
        return

    if entry.entry_id not in hass.data.get(DOMAIN, {}):
        return

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


class ZoneEntryDwellNumber(NumberEntity):
    """Configurable zone entry dwell time on HVAC Coordinator device.

    Minutes a zone must be occupied before switching from away to home preset.
    Prevents HVAC flapping when someone briefly transits through a zone.
    Only applies when the house is already occupied.

    Entity: number.ura_hvac_coordinator_zone_entry_dwell
    v4.2.2
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-sand"
    _attr_native_min_value = 0
    _attr_native_max_value = 15
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        from homeassistant.helpers.device_registry import DeviceInfo
        from .domain_coordinators.hvac_const import (
            DEFAULT_ZONE_ENTRY_DWELL_MINUTES,
            CONF_HVAC_ZONE_ENTRY_DWELL,
        )
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_zone_entry_dwell"
        self._attr_name = "Zone Entry Dwell"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        config = {**entry.data, **entry.options}
        self._value = config.get(CONF_HVAC_ZONE_ENTRY_DWELL, DEFAULT_ZONE_ENTRY_DWELL_MINUTES)

    def _get_hvac(self):
        """Get the HVAC coordinator instance."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("hvac")

    @property
    def native_value(self) -> float:
        """Return current dwell value."""
        return self._value

    @property
    def available(self) -> bool:
        """Only available when HVAC coordinator is active."""
        return self._get_hvac() is not None

    async def async_set_native_value(self, value: float) -> None:
        """Set new dwell value — takes effect on next HVAC decision cycle."""
        self._value = int(value)
        hvac = self._get_hvac()
        if hvac is not None:
            hvac._zone_entry_dwell = int(value)
        self.async_write_ha_state()
        _LOGGER.info("Zone entry dwell set to %d minutes", int(value))


class OffPeakDrainNumber(NumberEntity, RestoreEntity):
    """Configurable off-peak battery drain target on Energy Coordinator device.

    SOC% to drain to overnight based on tomorrow's solar forecast quality.
    v4.2.10: Exposes config-flow-only values as runtime-adjustable numbers.
    RestoreEntity persists slider changes across restarts.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:battery-arrow-down-outline"
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry,
        quality: str, default: int, min_val: int, max_val: int,
    ) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self.hass = hass
        self._entry = entry
        self._quality = quality
        self._attr_unique_id = f"{DOMAIN}_energy_offpeak_drain_{quality}"
        self._attr_name = f"Off-Peak Drain {quality.title()}"
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "energy_coordinator")},
            name="URA: Energy Coordinator",
            manufacturer="Universal Room Automation",
            model="Energy Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        # Read initial value from config entry
        from .domain_coordinators.energy_const import (
            CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT,
            CONF_ENERGY_OFFPEAK_DRAIN_GOOD,
            CONF_ENERGY_OFFPEAK_DRAIN_MODERATE,
            CONF_ENERGY_OFFPEAK_DRAIN_POOR,
        )
        conf_map = {
            "excellent": CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT,
            "good": CONF_ENERGY_OFFPEAK_DRAIN_GOOD,
            "moderate": CONF_ENERGY_OFFPEAK_DRAIN_MODERATE,
            "poor": CONF_ENERGY_OFFPEAK_DRAIN_POOR,
        }
        config = {**entry.data, **entry.options}
        self._value = config.get(conf_map.get(quality, ""), default)

    def _get_energy(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        return manager.coordinators.get("energy") if manager else None

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def available(self) -> bool:
        return self._get_energy() is not None

    async def async_added_to_hass(self) -> None:
        """Restore last slider value on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in ("unknown", "unavailable"):
            try:
                restored = int(float(last_state.state))
                self._value = restored
                energy = self._get_energy()
                if energy is not None:
                    energy.set_offpeak_drain(self._quality, restored)
            except (ValueError, TypeError):
                pass

    async def async_set_native_value(self, value: float) -> None:
        self._value = int(value)
        energy = self._get_energy()
        if energy is not None:
            energy.set_offpeak_drain(self._quality, int(value))
        self.async_write_ha_state()
        _LOGGER.info("Off-peak drain %s set to %d%%", self._quality, int(value))
