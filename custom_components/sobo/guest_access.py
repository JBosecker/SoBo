"""Öffentlicher Gast-Einstieg: Webhook + Nabu-Casa-Cloudhook (Plan 3).

* GET  → in sich geschlossene Gast-Seite (oder neutrale „Jukebox ist aus“-Seite)
* POST → JSON-Aktion, unverändert an die App weitergeleitet

Über den Cloudhook-Relay kommen nur Status, Body (Text) und `Content-Type` an.
Zusätzliche Header setzen wir trotzdem: Sie wirken beim lokalen Zugriff.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .api import SoboApiError, SoboClient
from .const import (
    CONF_WEBHOOK_ID,
    DEFAULT_LONG_POLL_TIMEOUT,
    DOMAIN,
    MAX_GUEST_BODY,
    PROXY_TIMEOUT_EXTRA,
    WEBHOOK_NAME,
)

if TYPE_CHECKING:
    from .coordinator import SoboCoordinator

_LOGGER = logging.getLogger(__name__)

# Gilt nur beim lokalen Zugriff; über den Relay ersetzt das Meta-CSP der Seite diese Header.
# X-Frame-Options setzt HA selbst (SAMEORIGIN).
_PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

INACTIVE_PAGE = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy"
 content="default-src 'none'; style-src 'sha256-{style_hash}'">
<meta name="referrer" content="no-referrer">
<title>Jukebox</title>
<style>{style}</style></head>
<body><main><h1>Die Jukebox ist gerade aus.</h1>
<p>Schau später noch einmal vorbei.</p></main></body></html>
"""
_INACTIVE_STYLE = (
    "body{margin:0;min-height:100vh;display:grid;place-items:center;"
    "font:17px/1.5 system-ui,sans-serif;background:#14121a;color:#f3eee6;text-align:center}"
    "main{padding:24px}h1{font-size:22px;margin:0 0 8px}p{margin:0;color:#b9b0a3}"
)


def _inactive_page() -> str:
    import base64
    import hashlib

    digest = base64.b64encode(hashlib.sha256(_INACTIVE_STYLE.encode()).digest()).decode()
    return INACTIVE_PAGE.replace("{style_hash}", digest).replace("{style}", _INACTIVE_STYLE)


def _json_response(status: int, payload: dict[str, Any]) -> web.Response:
    return web.Response(
        text=json.dumps(payload, separators=(",", ":")),
        status=status,
        content_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@dataclass
class GuestAccessState:
    url: str | None = None
    local_url: str | None = None
    cloud_connected: bool | None = None


class GuestAccess:
    """Verwaltet Webhook/Cloudhook und leitet Gast-Anfragen an die App weiter."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: SoboClient,
        page_html: str,
        coordinator: SoboCoordinator,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.client = client
        self.coordinator = coordinator
        self._page = page_html
        self._inactive = _inactive_page()
        self.state = GuestAccessState()
        self._registered = False
        self._lock = asyncio.Lock()
        self._unsub_cloud: Callable[[], None] | None = None

    # ------------------------------------------------------------------ Lebenszyklus

    @property
    def webhook_id(self) -> str:
        return str(self.entry.data[CONF_WEBHOOK_ID])

    async def async_start(self) -> None:
        if CONF_WEBHOOK_ID not in self.entry.data:
            self._set_webhook_id(webhook.async_generate_id())
        self._register()
        await self._refresh_urls()
        if "cloud" in self.hass.config.components:
            from homeassistant.components import cloud

            self._unsub_cloud = cloud.async_listen_connection_change(
                self.hass, self._on_cloud_change
            )
        try:
            await self.async_report()
        except SoboApiError as err:
            # Kein Abbruch: Der Coordinator meldet erneut, solange die App die URL nicht kennt.
            _LOGGER.debug("Gastzugang konnte nicht gemeldet werden: %s", err)

    async def async_stop(self) -> None:
        """Beim Entladen: Webhook abmelden, Cloudhook behalten (QR-Code bleibt gültig)."""
        if self._unsub_cloud:
            self._unsub_cloud()
            self._unsub_cloud = None
        self._unregister()

    def _set_webhook_id(self, webhook_id: str) -> None:
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, CONF_WEBHOOK_ID: webhook_id}
        )

    def _register(self) -> None:
        if self._registered:
            return
        webhook.async_register(
            self.hass,
            DOMAIN,
            WEBHOOK_NAME,
            self.webhook_id,
            self._handle,
            local_only=False,
            allowed_methods=("GET", "POST"),
        )
        self._registered = True

    def _unregister(self) -> None:
        if self._registered:
            webhook.async_unregister(self.hass, self.webhook_id)
            self._registered = False

    @callback
    def set_enabled(self, enabled: bool) -> None:
        """Option „bei Jukebox aus ganz abmelden“ (Plan 3.2, Schritt 6)."""
        if enabled:
            self._register()
        else:
            self._unregister()

    async def _on_cloud_change(self, _state: Any) -> None:
        await self._refresh_urls()
        try:
            await self.async_report()
        except SoboApiError as err:
            _LOGGER.debug("Gastzugang konnte nicht gemeldet werden: %s", err)

    async def _refresh_urls(self) -> None:
        self.state.url, self.state.cloud_connected = await _get_cloudhook(
            self.hass, self.webhook_id
        )
        try:
            self.state.local_url = webhook.async_generate_url(
                self.hass,
                self.webhook_id,
                allow_internal=True,
                allow_external=False,
                allow_ip=True,
                prefer_external=False,
            )
        except HomeAssistantError:
            self.state.local_url = None

    async def async_report(self) -> None:
        await self.client.report_guest_access(
            self.state.url, self.state.local_url, self.state.cloud_connected
        )

    async def async_rotate(self, generation: int) -> None:
        """Neue Webhook-ID + neuer Cloudhook; alte QR-Codes laufen ins Leere (Plan 3.2)."""
        async with self._lock:
            old_id = self.webhook_id
            self._unregister()
            await delete_cloudhook(self.hass, old_id)
            self._set_webhook_id(webhook.async_generate_id())
            self._register()
            await self._refresh_urls()
            await self.client.report_rotated(
                generation, self.state.url, self.state.local_url, self.state.cloud_connected
            )
            _LOGGER.info("Gastzugang erneuert")

    # ------------------------------------------------------------------ Anfragen

    async def _handle(
        self, hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        # HA beantwortet Ausnahmen aus Handlern mit 200 – deshalb alles selbst abfangen.
        try:
            if request.method == "GET":
                return self._page_response()
            if request.method == "POST":
                return await self._proxy(request)
            return _json_response(405, {"ok": False, "error": "method_not_allowed"})
        except Exception:
            _LOGGER.exception("Fehler bei Gast-Anfrage")
            return _json_response(500, {"ok": False, "error": "internal"})

    def _page_response(self) -> web.Response:
        data = self.coordinator.data or {}
        active = bool(data.get("effectively_active")) and self.coordinator.last_update_success
        html = self._page if active else self._inactive
        return web.Response(
            text=html, content_type="text/html", charset="utf-8", headers=_PAGE_HEADERS
        )

    async def _proxy(self, request: web.Request) -> web.Response:
        # Cloud-Anfragen kommen als MockRequest ohne `content_length`.
        declared = getattr(request, "content_length", None)
        if declared is not None and declared > MAX_GUEST_BODY:
            return _json_response(413, {"ok": False, "error": "too_large"})
        body = (await request.text()).encode("utf-8")
        if len(body) > MAX_GUEST_BODY:
            return _json_response(413, {"ok": False, "error": "too_large"})
        data = self.coordinator.data or {}
        wait = int(data.get("long_poll_timeout") or DEFAULT_LONG_POLL_TIMEOUT)
        try:
            status, text = await self.client.guest_action(body, wait + PROXY_TIMEOUT_EXTRA)
        except SoboApiError as err:
            _LOGGER.debug("App für Gast-Anfrage nicht erreichbar: %s", err)
            return _json_response(503, {"ok": False, "error": "unavailable"})
        return web.Response(
            text=text,
            status=status,
            content_type="application/json",
            headers={"Cache-Control": "no-store"},
        )


async def _get_cloudhook(hass: HomeAssistant, webhook_id: str) -> tuple[str | None, bool | None]:
    """Cloudhook-URL holen oder anlegen; (None, False/None) ohne Nabu Casa."""
    if "cloud" not in hass.config.components:
        return None, None
    from homeassistant.components import cloud

    if not cloud.async_active_subscription(hass):
        return None, False
    try:
        url = await cloud.async_get_or_create_cloudhook(hass, webhook_id)
    except cloud.CloudNotAvailable:  # schließt CloudNotConnected ein
        return None, False
    return url, True


async def delete_cloudhook(hass: HomeAssistant, webhook_id: str) -> None:
    if "cloud" not in hass.config.components:
        return
    from homeassistant.components import cloud

    if not cloud.async_is_logged_in(hass):
        return
    try:
        await cloud.async_delete_cloudhook(hass, webhook_id)
    except (cloud.CloudNotAvailable, ValueError) as err:
        # ValueError: Hook existierte nicht (hass_nabucasa)
        _LOGGER.debug("Cloudhook nicht gelöscht: %s", err)
