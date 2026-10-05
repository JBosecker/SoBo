"""Sensoren: läuft gerade, Queue-Länge, aktive Gäste, Gast-URL (für eine QR-Karte)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SoboConfigEntry
from .coordinator import SoboCoordinator
from .entity import SoboEntity
from .guest_access import GuestAccess


def _now_playing(data: dict[str, Any]) -> str | None:
    track = data.get("now_playing")
    if not track:
        return None
    text = f"{track.get('artist', '')} – {track.get('title', '')}".strip(" –")
    return text[:255] or None


@dataclass(frozen=True, kw_only=True)
class SoboSensorDescription(SensorEntityDescription):
    value: Callable[[dict[str, Any]], Any]


SENSORS = (
    SoboSensorDescription(key="now_playing", value=_now_playing),
    SoboSensorDescription(
        key="queue_length",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: d.get("queue_length"),
    ),
    SoboSensorDescription(
        key="active_guests",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: d.get("active_guests"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SoboConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    entities: list[SensorEntity] = [
        SoboSensor(runtime.coordinator, description) for description in SENSORS
    ]
    entities.append(SoboGuestUrlSensor(runtime.coordinator, runtime.guest_access))
    async_add_entities(entities)


class SoboSensor(SoboEntity, SensorEntity):
    entity_description: SoboSensorDescription

    def __init__(self, coordinator: SoboCoordinator, description: SoboSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.coordinator.data)


class SoboGuestUrlSensor(SoboEntity, SensorEntity):
    """Cloudhook-URL, ersatzweise die lokale URL – für eine QR-Karte im Dashboard."""

    def __init__(self, coordinator: SoboCoordinator, guest_access: GuestAccess) -> None:
        super().__init__(coordinator, "guest_url")
        self._guest_access = guest_access

    @property
    def native_value(self) -> str | None:
        state = self._guest_access.state
        return state.url or state.local_url

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self._guest_access.state
        return {
            "cloud_url": state.url,
            "local_url": state.local_url,
            "cloud_connected": state.cloud_connected,
        }
