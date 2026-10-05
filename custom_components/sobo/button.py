"""button.sobo_skip und button.sobo_rotate_guest_access."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SoboConfigEntry
from .api import SoboApiError
from .coordinator import SoboCoordinator
from .entity import SoboEntity
from .guest_access import GuestAccess


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SoboConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    async_add_entities(
        [
            SoboSkipButton(runtime.coordinator),
            SoboRotateButton(runtime.coordinator, runtime.guest_access),
        ]
    )


class SoboSkipButton(SoboEntity, ButtonEntity):
    def __init__(self, coordinator: SoboCoordinator) -> None:
        super().__init__(coordinator, "skip")

    async def async_press(self) -> None:
        try:
            await self.coordinator.client.skip()
        except SoboApiError as err:
            raise HomeAssistantError(f"SoBo nicht erreichbar: {err}") from err
        await self.coordinator.async_request_refresh()


class SoboRotateButton(SoboEntity, ButtonEntity):
    def __init__(self, coordinator: SoboCoordinator, guest_access: GuestAccess) -> None:
        super().__init__(coordinator, "rotate_guest_access")
        self._guest_access = guest_access

    async def async_press(self) -> None:
        generation = int(self.coordinator.data.get("rotation_requested") or 0)
        try:
            await self._guest_access.async_rotate(generation)
        except SoboApiError as err:
            raise HomeAssistantError(f"SoBo nicht erreichbar: {err}") from err
        await self.coordinator.async_request_refresh()
