"""Config-Flow: Kopplung per Supervisor-Discovery oder manuell (Plan 3.3)."""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .api import SoboApiError, SoboAuthError, SoboClient
from .const import CONF_HOST, CONF_PORT, CONF_SECRET, DEFAULT_HOST, DEFAULT_PORT, DOMAIN

TITLE = "SoBo"


async def _validate(session: aiohttp.ClientSession, data: dict[str, Any]) -> str | None:
    """Gibt einen Fehler-Schlüssel zurück oder None."""
    client = SoboClient(session, data[CONF_HOST], data[CONF_PORT], data[CONF_SECRET])
    try:
        await client.status()
    except SoboAuthError:
        return "invalid_auth"
    except SoboApiError:
        return "cannot_connect"
    return None


class SoboConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, Any] = {}
        self._app_name = "SoBo"

    async def async_step_hassio(self, discovery_info: HassioServiceInfo) -> ConfigFlowResult:
        config = discovery_info.config
        data = {
            CONF_HOST: str(config[CONF_HOST]),
            CONF_PORT: int(config[CONF_PORT]),
            CONF_SECRET: str(config[CONF_SECRET]),
        }
        await self.async_set_unique_id(DOMAIN)
        # Bereits eingerichtet: neue Verbindungsdaten übernehmen (z. B. neues Secret).
        self._abort_if_unique_id_configured(updates=data)
        self._discovered = data
        self._app_name = discovery_info.name or "SoBo"
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await _validate(async_get_clientsession(self.hass), self._discovered)
            if error is None:
                return self.async_create_entry(title=TITLE, data=self._discovered)
            errors["base"] = error
        return self.async_show_form(
            step_id="hassio_confirm",
            description_placeholders={"addon": self._app_name},
            errors=errors,
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manuell, z. B. für Entwicklung ohne Supervisor."""
        # Nur eine Instanz. Bewusst über die Unique-ID statt `single_config_entry`:
        # Letzteres würde auch die Discovery abbrechen, die ein neues Secret übernimmt.
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                CONF_HOST: user_input[CONF_HOST],
                CONF_PORT: user_input[CONF_PORT],
                CONF_SECRET: user_input[CONF_SECRET],
            }
            error = await _validate(async_get_clientsession(self.hass), data)
            if error is None:
                return self.async_create_entry(title=TITLE, data=data)
            errors["base"] = error
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=65535)
                ),
                vol.Required(CONF_SECRET): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
