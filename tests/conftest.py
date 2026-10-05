"""Gemeinsame Fixtures für die Integrationstests."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sobo.const import CONF_HOST, CONF_PORT, CONF_SECRET, DOMAIN

ENTRY_DATA = {CONF_HOST: "127.0.0.1", CONF_PORT: 8738, CONF_SECRET: "s" * 43}

STATUS: dict[str, Any] = {
    "version": 3,
    "active": True,
    "effectively_active": True,
    "state": "playing_guest",
    "now_playing": {"title": "Slow Comet", "artist": "Mira Okonkwo"},
    "queue_length": 2,
    "active_guests": 5,
    "rotation_requested": 0,
    "rotation_done": 0,
    "guest_access_reported": True,
    "long_poll_timeout": 20,
    "unregister_when_inactive": False,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Lädt custom_components/ aus dem Repository."""


@pytest.fixture
def client() -> Generator[AsyncMock]:
    """Ersetzt den API-Client der App in Setup und Config-Flow."""
    with (
        patch("custom_components.sobo.SoboClient", autospec=True) as cls,
        patch("custom_components.sobo.config_flow.SoboClient", new=cls),
    ):
        instance = cls.return_value
        instance.status.return_value = dict(STATUS)
        instance.guest_action.return_value = (200, '{"ok":true}')
        yield instance


async def setup_sobo(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data=dict(ENTRY_DATA), title="SoBo")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
