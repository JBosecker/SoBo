"""switch.sobo_active – Jukebox an/aus."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SoboConfigEntry
from .api import SoboApiError
from .coordinator import SoboCoordinator
from .entity import SoboEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SoboConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([SoboActiveSwitch(entry.runtime_data.coordinator)])


class SoboActiveSwitch(SoboEntity, SwitchEntity):
    def __init__(self, coordinator: SoboCoordinator) -> None:
        super().__init__(coordinator, "active")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("active"))

    async def _set(self, active: bool) -> None:
        try:
            await self.coordinator.client.set_active(active)
        except SoboApiError as err:
            raise HomeAssistantError(f"SoBo nicht erreichbar: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
