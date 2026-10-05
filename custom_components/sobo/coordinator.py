"""Fragt den App-Status ab und reagiert darauf (Rotation, erneutes Melden der URL)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SoboApiError, SoboClient
from .const import DOMAIN, SCAN_INTERVAL

if TYPE_CHECKING:
    from .guest_access import GuestAccess

_LOGGER = logging.getLogger(__name__)


class SoboCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: SoboClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self.guest_access: GuestAccess | None = None
        self._rotating = False
        # Zuletzt ausgeführte Rotation: dieselbe Anforderung nie zweimal ausführen.
        self._last_rotated: int | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.client.status()
        except SoboApiError as err:
            raise UpdateFailed(f"SoBo-App nicht erreichbar: {err}") from err
        if self.guest_access is not None:
            await self._sync_guest_access(data)
        return data

    async def _sync_guest_access(self, data: dict[str, Any]) -> None:
        guest = self.guest_access
        assert guest is not None
        # Option: Webhook nur registriert, solange die Jukebox läuft
        if data.get("unregister_when_inactive"):
            guest.set_enabled(bool(data.get("effectively_active")))
        else:
            guest.set_enabled(True)

        requested = int(data.get("rotation_requested") or 0)
        done = int(data.get("rotation_done") or 0)
        try:
            if requested > done and not self._rotating:
                if requested == self._last_rotated:
                    # Schon rotiert, aber die Bestätigung kam nicht an: nur erneut melden.
                    await guest.async_report_rotated(requested)
                else:
                    self._rotating = True
                    try:
                        await guest.async_rotate_only()
                    finally:
                        self._rotating = False
                    # Als erledigt merken, bevor gemeldet wird: Scheitert die Meldung,
                    # wird beim nächsten Abruf nur sie wiederholt.
                    self._last_rotated = requested
                    await guest.async_report_rotated(requested)
            elif not data.get("guest_access_reported"):
                # App wurde neu gestartet und kennt die URL noch nicht.
                await guest.async_report()
        except SoboApiError as err:
            _LOGGER.warning("Gastzugang konnte nicht an die App gemeldet werden: %s", err)
