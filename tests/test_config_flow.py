"""Config-Flow: Supervisor-Discovery und manuelle Einrichtung (Plan 3.3)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_HASSIO, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.hassio import HassioServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sobo.api import SoboApiError, SoboAuthError
from custom_components.sobo.const import DOMAIN

from .conftest import ENTRY_DATA

DISCOVERY = HassioServiceInfo(
    config={"host": "127.0.0.1", "port": 8738, "secret": "s" * 43},
    name="SoBo",
    slug="abc123_sobo",
    uuid="1234",
)


@pytest.fixture(autouse=True)
def no_setup() -> None:
    with patch("custom_components.sobo.async_setup_entry", return_value=True):
        yield


async def test_hassio_discovery(hass: HomeAssistant, client: AsyncMock) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_HASSIO}, data=DISCOVERY
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "hassio_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == ENTRY_DATA
    assert result["result"].unique_id == DOMAIN


async def test_hassio_discovery_updates_secret(hass: HomeAssistant, client: AsyncMock) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=DOMAIN, data={**ENTRY_DATA, "secret": "alt" * 15}
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_HASSIO}, data=DISCOVERY
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data["secret"] == "s" * 43


@pytest.mark.parametrize(
    ("error", "key"), [(SoboAuthError("x"), "invalid_auth"), (SoboApiError("x"), "cannot_connect")]
)
async def test_hassio_confirm_errors(
    hass: HomeAssistant, client: AsyncMock, error: Exception, key: str
) -> None:
    client.status.side_effect = error
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_HASSIO}, data=DISCOVERY
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}


async def test_user_flow(hass: HomeAssistant, client: AsyncMock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    client.status.side_effect = SoboAuthError("x")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], ENTRY_DATA)
    assert result["errors"] == {"base": "invalid_auth"}
    client.status.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], ENTRY_DATA)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == ENTRY_DATA


async def test_only_one_instance(hass: HomeAssistant, client: AsyncMock) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data=ENTRY_DATA).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
