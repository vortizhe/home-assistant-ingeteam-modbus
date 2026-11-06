"""Config and options flow for the Ingeteam Modbus integration."""
import ipaddress
import re

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback

from .const import (
    DOMAIN,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_MODBUS_ADDRESS,
    CONF_MODBUS_ADDRESS,
)

DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_MODBUS_ADDRESS, default=DEFAULT_MODBUS_ADDRESS): int,
    }
)


def host_valid(host: str) -> bool:
    """Return True if hostname or IP address is valid."""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        disallowed = re.compile(r"[^a-zA-Z\d\-]")
        return all(x and not disallowed.search(x) for x in host.split("."))
    return True


@callback
def ingeteam_modbus_entries(hass: HomeAssistant):
    """Return the hosts already configured."""
    return set(
        entry.data[CONF_HOST] for entry in hass.config_entries.async_entries(DOMAIN)
    )


@callback
def ingeteam_modbus_names(hass: HomeAssistant):
    """Return the hub names already configured."""
    return set(
        entry.data[CONF_NAME] for entry in hass.config_entries.async_entries(DOMAIN)
    )


class IngeteamModbusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Ingeteam Modbus configflow."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            name = user_input[CONF_NAME]

            if not host_valid(host):
                errors[CONF_HOST] = "invalid_host"
            elif host in ingeteam_modbus_entries(self.hass):
                errors[CONF_HOST] = "already_configured"
            elif name in ingeteam_modbus_names(self.hass):
                # The hub name is the prefix of every entity id and of every
                # unique id, so two entries may not share it.
                errors[CONF_NAME] = "name_exists"
            else:
                await self.async_set_unique_id(host)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=name, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return IngeteamModbusOptionsFlow()


class IngeteamModbusOptionsFlow(config_entries.OptionsFlow):
    """Allow the modbus address to be changed after setup.

    Nothing else is configurable: every register block has a fixed interval and
    offset in const.py, picked so that two reads never land on the device at
    the same instant, and every sensor the register map covers is created.
    """

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data = self.config_entry.data
        options = self.config_entry.options

        def current(key, default):
            return options.get(key, data.get(key, default))

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_MODBUS_ADDRESS,
                    default=current(CONF_MODBUS_ADDRESS, DEFAULT_MODBUS_ADDRESS),
                ): int,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
