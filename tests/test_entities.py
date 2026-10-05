"""Entitäten: Schalter, Sensoren, Buttons (Plan 4.5)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.sobo.api import SoboApiError
from custom_components.sobo.const import CONF_WEBHOOK_ID

from .conftest import setup_sobo


def entity_id(hass: HomeAssistant, domain: str, key: str) -> str:
    registry = er.async_get(hass)
    entry = next(e for e in registry.entities.values() if e.unique_id.endswith(f"_{key}"))
    assert entry.domain == domain
    return entry.entity_id


async def test_sensors(hass: HomeAssistant, client: AsyncMock) -> None:
    await setup_sobo(hass)
    assert (
        hass.states.get(entity_id(hass, "sensor", "now_playing")).state
        == "Mira Okonkwo – Slow Comet"
    )
    assert hass.states.get(entity_id(hass, "sensor", "queue_length")).state == "2"
    assert hass.states.get(entity_id(hass, "sensor", "active_guests")).state == "5"


async def test_guest_url_falls_back_to_local(hass: HomeAssistant, client: AsyncMock) -> None:
    entry = await setup_sobo(hass)
    state = hass.states.get(entity_id(hass, "sensor", "guest_url"))
    assert state.attributes["cloud_url"] is None
    local = state.attributes["local_url"]
    if local is not None:  # nur wenn HA eine interne URL kennt
        assert local.endswith(entry.data[CONF_WEBHOOK_ID])
        assert state.state == local


async def test_switch(hass: HomeAssistant, client: AsyncMock) -> None:
    await setup_sobo(hass)
    switch = entity_id(hass, "switch", "active")
    assert hass.states.get(switch).state == "on"
    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    client.set_active.assert_awaited_once_with(False)

    client.set_active.side_effect = SoboApiError("weg")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)


async def test_skip_button(hass: HomeAssistant, client: AsyncMock) -> None:
    await setup_sobo(hass)
    button = entity_id(hass, "button", "skip")
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    client.skip.assert_awaited_once()


async def test_rotate_button(hass: HomeAssistant, client: AsyncMock) -> None:
    entry = await setup_sobo(hass)
    old_id = entry.data[CONF_WEBHOOK_ID]
    button = entity_id(hass, "button", "rotate_guest_access")
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    assert entry.data[CONF_WEBHOOK_ID] != old_id
    client.report_rotated.assert_awaited_once()


async def test_entities_unavailable_when_app_down(hass: HomeAssistant, client: AsyncMock) -> None:
    entry = await setup_sobo(hass)
    client.status.side_effect = SoboApiError("weg")
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, "switch", "active")).state == "unavailable"
