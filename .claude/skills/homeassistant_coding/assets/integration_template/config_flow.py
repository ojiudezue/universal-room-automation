"""Config flow for My Integration."""
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, DEFAULT_PORT

_LOGGER = logging.getLogger(__name__)


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
            except ConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
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
                vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors
        )

    async def _test_connection(self, host: str, port: int) -> bool:
        """Test if we can connect to the device."""
        # TODO: Add your connection test logic here
        # Example:
        # api = MyDeviceAPI(host, port)
        # await api.async_get_data()
        # await api.async_close()
        return True
