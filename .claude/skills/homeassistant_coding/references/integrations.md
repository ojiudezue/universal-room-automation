# HomeAssistant Custom Integrations Reference

## Integration Structure

Custom integrations are located in `custom_components/<domain>/`.

**Minimum Required Files:**
```
custom_components/
└── my_integration/
    ├── __init__.py         # Required - Integration setup
    ├── manifest.json       # Required - Integration metadata
    ├── sensor.py          # Optional - Sensor platform
    ├── switch.py          # Optional - Switch platform
    ├── light.py           # Optional - Light platform
    ├── config_flow.py     # Optional - Configuration UI
    ├── const.py           # Optional - Constants
    └── strings.json       # Optional - Translations
```

## manifest.json

**Required Structure:**
```json
{
  "domain": "my_integration",
  "name": "My Integration",
  "documentation": "https://github.com/username/my_integration",
  "codeowners": ["@username"],
  "requirements": ["pyserial==3.5", "requests>=2.25.0"],
  "version": "1.0.0",
  "iot_class": "local_polling"
}
```

**IoT Classes:**
- `local_polling` - Polls local device
- `local_push` - Receives updates from local device
- `cloud_polling` - Polls cloud service
- `cloud_push` - Receives updates from cloud
- `calculated` - Calculated values

**Optional Fields:**
```json
{
  "dependencies": ["http"],
  "after_dependencies": ["mqtt"],
  "config_flow": true,
  "dhcp": [{"hostname": "mydevice", "macaddress": "AA:BB:CC:*"}],
  "zeroconf": ["_mydevice._tcp.local."],
  "homekit": {"models": ["MyDevice"]},
  "ssdp": [{"manufacturer": "MyCompany"}]
}
```

## __init__.py (Integration Setup)

### Basic Setup (YAML Configuration):
```python
"""The My Integration integration."""
import logging
import voluptuous as vol

from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)

DOMAIN = "my_integration"

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_HOST): cv.string,
                vol.Optional(CONF_PORT, default=8080): cv.port,
                vol.Optional(CONF_USERNAME): cv.string,
                vol.Optional(CONF_PASSWORD): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the My Integration component."""
    hass.data[DOMAIN] = {}

    if DOMAIN not in config:
        return True

    conf = config[DOMAIN]
    host = conf[CONF_HOST]
    port = conf[CONF_PORT]

    # Initialize your API/device connection here
    # Store in hass.data[DOMAIN]

    # Load platforms
    await hass.helpers.discovery.async_load_platform("sensor", DOMAIN, {}, config)
    await hass.helpers.discovery.async_load_platform("switch", DOMAIN, {}, config)

    return True
```

### Modern Setup (Config Flow):
```python
"""The My Integration integration."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up My Integration from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Store data for platforms to access
    hass.data[DOMAIN][entry.entry_id] = {
        "host": entry.data["host"],
        "port": entry.data["port"],
    }

    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
```

## config_flow.py (UI Configuration)

**Basic Config Flow:**
```python
"""Config flow for My Integration."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN

class MyIntegrationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for My Integration."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Validate connection
            try:
                # Test connection here
                await self._test_connection(
                    user_input[CONF_HOST],
                    user_input[CONF_PORT]
                )
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                # Create entry
                return self.async_create_entry(
                    title=user_input[CONF_HOST],
                    data=user_input
                )

        # Show form
        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=8080): cv.port,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors
        )

    async def _test_connection(self, host, port):
        """Test if we can connect."""
        # Add your connection test logic
        pass
```

**With Discovery (SSDP/Zeroconf):**
```python
async def async_step_ssdp(self, discovery_info):
    """Handle SSDP discovery."""
    await self.async_set_unique_id(discovery_info["serial"])
    self._abort_if_unique_id_configured()

    self.context["title_placeholders"] = {
        "name": discovery_info.get("name", "Unknown")
    }

    return await self.async_step_confirm()

async def async_step_confirm(self, user_input=None):
    """Confirm discovered device."""
    if user_input is not None:
        return self.async_create_entry(
            title=self.context["title_placeholders"]["name"],
            data={}
        )

    return self.async_show_form(step_id="confirm")
```

## Platform Implementation (sensor.py example)

**Modern Entity-based Platform:**
```python
"""Sensor platform for My Integration."""
from datetime import timedelta
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)

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

class MyTemperatureSensor(CoordinatorEntity, SensorEntity):
    """Temperature sensor."""

    def __init__(self, coordinator, entry):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_temperature"
        self._attr_name = "My Device Temperature"
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data.get("temperature")

    @property
    def extra_state_attributes(self):
        """Return additional attributes."""
        return {
            "last_update": self.coordinator.data.get("last_update"),
            "sensor_id": self.coordinator.data.get("sensor_id"),
        }
```

## Data Update Coordinator

**Using Coordinator for Efficient Updates:**
```python
"""Data update coordinator for My Integration."""
from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MyDeviceAPI

_LOGGER = logging.getLogger(__name__)

class MyIntegrationCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the device."""

    def __init__(self, hass: HomeAssistant, api: MyDeviceAPI) -> None:
        """Initialize."""
        self.api = api
        super().__init__(
            hass,
            _LOGGER,
            name="My Integration",
            update_interval=timedelta(seconds=30),
        )

    async def _async_update_data(self):
        """Fetch data from device."""
        try:
            # Fetch data from your device/API
            data = await self.api.async_get_data()
            return data
        except Exception as err:
            raise UpdateFailed(f"Error communicating with device: {err}")
```

## Device Registry Integration

**Registering Devices:**
```python
from homeassistant.helpers.device_registry import DeviceInfo

class MyEntity(SensorEntity):
    """My entity with device info."""

    def __init__(self, coordinator, entry):
        """Initialize."""
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="My Device",
            manufacturer="My Company",
            model="Model X",
            sw_version="1.0.0",
            configuration_url="http://device-ip",
        )
```

## Best Practices

1. **Use Config Flow:** Implement config_flow.py for UI configuration
2. **Use Coordinators:** Centralize data fetching with DataUpdateCoordinator
3. **Proper Error Handling:** Always catch exceptions and log appropriately
4. **Device Registry:** Register devices for multi-entity integrations
5. **Unique IDs:** Always set unique_id for entities to enable customization
6. **Async/Await:** Use async functions for I/O operations
7. **Type Hints:** Use proper type hints throughout
8. **Testing:** Write tests for your integration
9. **Documentation:** Include README with setup instructions
10. **Follow HA Standards:** Check official integration quality scale

## Common Patterns

### API Client (api.py):
```python
"""API client for My Device."""
import aiohttp
import async_timeout

class MyDeviceAPI:
    """API client."""

    def __init__(self, host, port):
        """Initialize."""
        self.host = host
        self.port = port
        self.session = aiohttp.ClientSession()

    async def async_get_data(self):
        """Get data from device."""
        url = f"http://{self.host}:{self.port}/api/data"
        try:
            async with async_timeout.timeout(10):
                response = await self.session.get(url)
                return await response.json()
        except aiohttp.ClientError as err:
            raise ConnectionError(f"Error connecting: {err}")

    async def async_close(self):
        """Close session."""
        await self.session.close()
```

### Constants (const.py):
```python
"""Constants for My Integration."""
DOMAIN = "my_integration"

# Configuration
CONF_DEVICE_ID = "device_id"

# Defaults
DEFAULT_PORT = 8080
DEFAULT_SCAN_INTERVAL = 30
```
