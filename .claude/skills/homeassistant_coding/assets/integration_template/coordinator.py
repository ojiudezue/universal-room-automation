"""Data update coordinator for My Integration."""
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class MyIntegrationCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the device."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize coordinator."""
        self.host = entry.data[CONF_HOST]
        self.port = entry.data[CONF_PORT]

        super().__init__(
            hass,
            _LOGGER,
            name="My Integration",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    async def _async_update_data(self):
        """Fetch data from device."""
        try:
            # TODO: Replace with your actual data fetching logic
            # Example:
            # api = MyDeviceAPI(self.host, self.port)
            # data = await api.async_get_data()
            # await api.async_close()
            # return data

            # Placeholder data
            return {
                "temperature": 22.5,
                "humidity": 45,
                "last_update": self.hass.helpers.dt_util.utcnow().isoformat(),
            }
        except Exception as err:
            raise UpdateFailed(f"Error communicating with device: {err}") from err
