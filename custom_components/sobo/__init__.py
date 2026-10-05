"""SoBo-Integration: öffentlicher Gast-Einstieg (Webhook/Cloudhook) und Entitäten."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_CLOSE, Platform
from homeassistant.core import Event, HomeAssistant

from .api import SoboClient
from .const import CONF_HOST, CONF_PORT, CONF_SECRET, CONF_WEBHOOK_ID
from .coordinator import SoboCoordinator
from .guest_access import GuestAccess, delete_cloudhook

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.SENSOR, Platform.SWITCH]
GUEST_PAGE = Path(__file__).parent / "guest_page.html"


@dataclass
class SoboRuntimeData:
    client: SoboClient
    coordinator: SoboCoordinator
    guest_access: GuestAccess
    session: aiohttp.ClientSession


type SoboConfigEntry = ConfigEntry[SoboRuntimeData]


def _load_page() -> str:
    return GUEST_PAGE.read_text(encoding="utf-8")


async def async_setup_entry(hass: HomeAssistant, entry: SoboConfigEntry) -> bool:
    # Eigene Session: Viele gleichzeitige Long-Polls gehen an denselben Host,
    # HAs gemeinsame Session begrenzt auf 100 Verbindungen pro Host.
    session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0, limit_per_host=0))
    try:
        client = SoboClient(
            session, entry.data[CONF_HOST], entry.data[CONF_PORT], entry.data[CONF_SECRET]
        )
        coordinator = SoboCoordinator(hass, entry, client)
        await coordinator.async_config_entry_first_refresh()

        page = await hass.async_add_executor_job(_load_page)
        guest_access = GuestAccess(hass, entry, client, page, coordinator)
        await guest_access.async_start()
        coordinator.guest_access = guest_access
    except Exception:
        await session.close()
        raise

    entry.runtime_data = SoboRuntimeData(client, coordinator, guest_access, session)

    async def _close_session(_: Event) -> None:
        await session.close()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_CLOSE, _close_session))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SoboConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        runtime = entry.runtime_data
        await runtime.guest_access.async_stop()
        await runtime.session.close()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: SoboConfigEntry) -> None:
    """Integration gelöscht: Cloudhook entfernen, damit die URL nicht weiterlebt."""
    if webhook_id := entry.data.get(CONF_WEBHOOK_ID):
        await delete_cloudhook(hass, webhook_id)
