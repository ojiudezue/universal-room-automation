"""Sensor platform for My Integration."""
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MyIntegrationCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up My Integration sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    async_add_entities(
        [
            MyTemperatureSensor(coordinator, entry),
            MyHumiditySensor(coordinator, entry),
        ]
    )


class MyIntegrationSensor(CoordinatorEntity, SensorEntity):
    """Base class for My Integration sensors."""

    def __init__(
        self,
        coordinator: MyIntegrationCoordinator,
        entry: ConfigEntry,
        sensor_type: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{sensor_type}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="My Device",
            manufacturer="My Company",
            model="Model X",
            sw_version="1.0.0",
        )


class MyTemperatureSensor(MyIntegrationSensor):
    """Temperature sensor."""

    def __init__(
        self,
        coordinator: MyIntegrationCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the temperature sensor."""
        super().__init__(coordinator, entry, "temperature")
        self._attr_name = "My Device Temperature"
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data.get("temperature")


class MyHumiditySensor(MyIntegrationSensor):
    """Humidity sensor."""

    def __init__(
        self,
        coordinator: MyIntegrationCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the humidity sensor."""
        super().__init__(coordinator, entry, "humidity")
        self._attr_name = "My Device Humidity"
        self._attr_device_class = SensorDeviceClass.HUMIDITY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = PERCENTAGE

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data.get("humidity")
