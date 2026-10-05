"""Gastzugang: Webhook GET/POST, Relay-Verhalten, Cloudhook und Rotation (Plan 3, 9)."""

from __future__ import annotations

import json
from collections.abc import Generator
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util.aiohttp import MockRequest, serialize_response
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.sobo.api import SoboApiError
from custom_components.sobo.const import CONF_WEBHOOK_ID, DOMAIN, MAX_GUEST_BODY

from .conftest import ENTRY_DATA, STATUS, setup_sobo

CLOUD_URL = "https://hooks.nabu.casa/AAAA"


def path(entry: MockConfigEntry) -> str:
    return f"/api/webhook/{entry.data[CONF_WEBHOOK_ID]}"


async def test_get_serves_guest_page(
    hass: HomeAssistant, client: AsyncMock, hass_client_no_auth: ClientSessionGenerator
) -> None:
    entry = await setup_sobo(hass)
    http = await hass_client_no_auth()
    response = await http.get(path(entry))
    assert response.status == 200
    assert response.content_type == "text/html"
    html = await response.text()
    assert "Was soll als Nächstes laufen?" in html
    assert "default-src 'none'" in html
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"
    # Keine HA-Interna in der Seite
    for leak in ("homeassistant", "/api/", entry.data[CONF_WEBHOOK_ID]):
        assert leak not in html


async def test_get_when_jukebox_off(
    hass: HomeAssistant, client: AsyncMock, hass_client_no_auth: ClientSessionGenerator
) -> None:
    client.status.return_value = {**STATUS, "effectively_active": False}
    entry = await setup_sobo(hass)
    http = await hass_client_no_auth()
    html = await (await http.get(path(entry))).text()
    assert "Die Jukebox ist gerade aus." in html
    assert "<script" not in html


async def test_post_is_forwarded(
    hass: HomeAssistant, client: AsyncMock, hass_client_no_auth: ClientSessionGenerator
) -> None:
    client.guest_action.return_value = (409, '{"ok":false,"error":"already_voted"}')
    entry = await setup_sobo(hass)
    http = await hass_client_no_auth()
    body = b'{"action":"vote","session":"x","item":"y"}'
    response = await http.post(path(entry), data=body)
    assert response.status == 409
    assert await response.json() == {"ok": False, "error": "already_voted"}
    sent_body, timeout = client.guest_action.call_args.args
    assert sent_body == body
    assert timeout == 25  # long_poll_timeout + Puffer


async def test_post_too_large(
    hass: HomeAssistant, client: AsyncMock, hass_client_no_auth: ClientSessionGenerator
) -> None:
    entry = await setup_sobo(hass)
    http = await hass_client_no_auth()
    response = await http.post(path(entry), data=b"x" * (MAX_GUEST_BODY + 1))
    assert response.status == 413
    client.guest_action.assert_not_called()


async def test_post_when_app_down(
    hass: HomeAssistant, client: AsyncMock, hass_client_no_auth: ClientSessionGenerator
) -> None:
    client.guest_action.side_effect = SoboApiError("weg")
    entry = await setup_sobo(hass)
    http = await hass_client_no_auth()
    response = await http.post(path(entry), data=b"{}")
    assert response.status == 503
    assert (await response.json())["error"] == "unavailable"


async def test_other_methods_rejected(
    hass: HomeAssistant, client: AsyncMock, hass_client_no_auth: ClientSessionGenerator
) -> None:
    entry = await setup_sobo(hass)
    http = await hass_client_no_auth()
    response = await http.put(path(entry), data=b"{}")
    assert response.status == 405


@pytest.mark.parametrize(
    ("method", "content_type"), [("GET", "text/html"), ("POST", "application/json")]
)
async def test_response_survives_cloud_relay(
    hass: HomeAssistant, client: AsyncMock, method: str, content_type: str
) -> None:
    """Wie der Nabu-Casa-Relay: MockRequest ohne remote, nur Status/Body/Content-Type zurück."""
    entry = await setup_sobo(hass)
    request = MockRequest(
        content=b'{"action":"state","session":"x"}',
        mock_source="cloud",
        method=method,
        headers={"Content-Type": "application/json"},
        query_string="",
        remote=None,
    )
    response = await webhook.async_handle_webhook(hass, entry.data[CONF_WEBHOOK_ID], request)
    serialized = serialize_response(response)
    assert serialized["status"] == 200
    assert response.content_type == content_type
    assert isinstance(serialized["body"], str) and serialized["body"]
    if method == "POST":
        assert json.loads(serialized["body"]) == {"ok": True}


# --------------------------------------------------------------------------- Cloudhook


class CloudNotAvailableError(Exception):
    """Ersatz für cloud.CloudNotAvailable."""


@pytest.fixture
def cloud() -> Generator[dict[str, AsyncMock]]:
    """Nabu Casa verbunden – ersetzt das HA-Modul `cloud` (in Tests nicht importierbar)."""
    fake = SimpleNamespace(
        async_active_subscription=lambda hass: True,
        async_is_logged_in=lambda hass: True,
        async_get_or_create_cloudhook=AsyncMock(return_value=CLOUD_URL),
        async_delete_cloudhook=AsyncMock(),
        async_listen_connection_change=lambda hass, target: lambda: None,
        CloudNotAvailable=CloudNotAvailableError,
    )
    with patch("custom_components.sobo.guest_access.cloud_api", return_value=fake):
        yield {
            "create": fake.async_get_or_create_cloudhook,
            "delete": fake.async_delete_cloudhook,
        }


async def test_cloudhook_reported(
    hass: HomeAssistant, client: AsyncMock, cloud: dict[str, AsyncMock]
) -> None:
    entry = await setup_sobo(hass)
    cloud["create"].assert_awaited_once_with(hass, entry.data[CONF_WEBHOOK_ID])
    url, _local, connected = client.report_guest_access.call_args.args
    assert (url, connected) == (CLOUD_URL, True)
    state = hass.states.get("sensor.sobo_guest_url")
    assert state is not None and state.state == CLOUD_URL


async def test_without_nabu_casa(hass: HomeAssistant, client: AsyncMock) -> None:
    await setup_sobo(hass)
    url, _local, connected = client.report_guest_access.call_args.args
    assert url is None and connected is None


async def test_rotation_requested_by_app(
    hass: HomeAssistant,
    client: AsyncMock,
    cloud: dict[str, AsyncMock],
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    entry = await setup_sobo(hass)
    old_id = entry.data[CONF_WEBHOOK_ID]
    http = await hass_client_no_auth()

    client.status.return_value = {**STATUS, "rotation_requested": 2, "rotation_done": 1}
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    new_id = entry.data[CONF_WEBHOOK_ID]
    assert new_id != old_id
    cloud["delete"].assert_awaited_once_with(hass, old_id)
    generation, url, _local, _connected = client.report_rotated.call_args.args
    assert (generation, url) == (2, CLOUD_URL)
    # Alter Link liefert keine Seite mehr, der neue schon.
    assert "Was soll" not in await (await http.get(f"/api/webhook/{old_id}")).text()
    assert "Was soll" in await (await http.get(f"/api/webhook/{new_id}")).text()

    # Nicht doppelt rotieren, solange die App den alten Stand meldet
    await entry.runtime_data.coordinator.async_refresh()
    assert client.report_rotated.await_count == 1


async def test_reports_url_again_after_app_restart(hass: HomeAssistant, client: AsyncMock) -> None:
    entry = await setup_sobo(hass)
    calls = client.report_guest_access.await_count
    client.status.return_value = {**STATUS, "guest_access_reported": False}
    await entry.runtime_data.coordinator.async_refresh()
    assert client.report_guest_access.await_count == calls + 1


async def test_unregister_when_inactive(
    hass: HomeAssistant, client: AsyncMock, hass_client_no_auth: ClientSessionGenerator
) -> None:
    entry = await setup_sobo(hass)
    http = await hass_client_no_auth()
    client.status.return_value = {
        **STATUS,
        "effectively_active": False,
        "unregister_when_inactive": True,
    }
    await entry.runtime_data.coordinator.async_refresh()
    assert "Jukebox" not in await (await http.get(path(entry))).text()
    client.status.return_value = dict(STATUS)
    await entry.runtime_data.coordinator.async_refresh()
    assert "Was soll" in await (await http.get(path(entry))).text()


async def test_unload_keeps_cloudhook_remove_deletes_it(
    hass: HomeAssistant, client: AsyncMock, cloud: dict[str, AsyncMock]
) -> None:
    entry = await setup_sobo(hass)
    webhook_id = entry.data[CONF_WEBHOOK_ID]
    assert await hass.config_entries.async_unload(entry.entry_id)
    cloud["delete"].assert_not_called()
    assert await hass.config_entries.async_remove(entry.entry_id)
    cloud["delete"].assert_awaited_once_with(hass, webhook_id)


async def test_webhook_id_stable_across_reload(hass: HomeAssistant, client: AsyncMock) -> None:
    entry = await setup_sobo(hass)
    webhook_id = entry.data[CONF_WEBHOOK_ID]
    assert len(webhook_id) >= 32
    assert await hass.config_entries.async_reload(entry.entry_id)
    assert entry.data[CONF_WEBHOOK_ID] == webhook_id


async def test_setup_retries_when_app_unreachable(hass: HomeAssistant, client: AsyncMock) -> None:
    client.status.side_effect = SoboApiError("weg")
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data=dict(ENTRY_DATA))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
