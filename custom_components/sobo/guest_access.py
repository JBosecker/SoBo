"""Public guest entry point: webhook + Nabu Casa cloudhook (plan 3).

* GET  → self-contained guest page (or a neutral "jukebox is off" page)
* POST → JSON action, forwarded unchanged to the app

Through the cloudhook relay only status, body (text) and `Content-Type` arrive.
We still set additional headers: they take effect for local access.
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

# Only applies to local access; through the relay the page's meta CSP replaces these headers.
# HA sets X-Frame-Options itself (SAMEORIGIN).
_PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

INACTIVE_PAGE = """<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy"
 content="default-src 'none'; style-src 'sha256-{style_hash}'">
<meta name="referrer" content="no-referrer">
<title>Jukebox</title>
<style>{style}</style></head>
<body><main><h1>{title}</h1>
<p>{text}</p></main></body></html>
"""
_INACTIVE_STYLE = (
    "body{margin:0;min-height:100vh;display:grid;place-items:center;"
    "font:17px/1.5 system-ui,sans-serif;background:#14121a;color:#f3eee6;text-align:center}"
    "main{padding:24px}h1{font-size:22px;margin:0 0 8px}p{margin:0;color:#b9b0a3}"
)


# Texts of the "jukebox is off" page; English is the default (see `_pick_language`).
INACTIVE_TEXTS: dict[str, tuple[str, str]] = {
    "en": ("The jukebox is off right now.", "Check back later."),
    "de": ("Die Jukebox ist gerade aus.", "Schau später noch einmal vorbei."),
}


def _inactive_page(lang: str) -> str:
    import base64
    import hashlib

    title, text = INACTIVE_TEXTS[lang]
    digest = base64.b64encode(hashlib.sha256(_INACTIVE_STYLE.encode()).digest()).decode()
    replacements = {
        "{lang}": lang,
        "{title}": title,
        "{text}": text,
        "{style_hash}": digest,
        "{style}": _INACTIVE_STYLE,
    }
    page = INACTIVE_PAGE
    for marker, value in replacements.items():
        page = page.replace(marker, value)
    return page


def _pick_language(accept_language: str | None) -> str:
    """First supported language from an `Accept-Language` header (fallback: English)."""
    ranked: list[tuple[float, int, str]] = []
    for index, part in enumerate((accept_language or "").split(",")):
        tag, _, params = part.strip().partition(";")
        quality = 1.0
        if params.strip().startswith("q="):
            try:
                quality = float(params.strip()[2:])
            except ValueError:
                quality = 0.0
        ranked.append((-quality, index, tag.strip().lower().split("-")[0]))
    for quality, _, base in sorted(ranked):
        if quality < 0 and base in INACTIVE_TEXTS:
            return base
    return "en"


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
    """Manages webhook/cloudhook and forwards guest requests to the app."""

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
        self._inactive = {lang: _inactive_page(lang) for lang in INACTIVE_TEXTS}
        self.state = GuestAccessState()
        self._registered = False
        self._lock = asyncio.Lock()
        self._unsub_cloud: Callable[[], None] | None = None

    # ------------------------------------------------------------------ lifecycle

    @property
    def webhook_id(self) -> str:
        return str(self.entry.data[CONF_WEBHOOK_ID])

    async def async_start(self) -> None:
        if CONF_WEBHOOK_ID not in self.entry.data:
            self._set_webhook_id(webhook.async_generate_id())
        self._register()
        await self._refresh_urls()
        if (cloud := cloud_api(self.hass)) is not None:
            self._unsub_cloud = cloud.async_listen_connection_change(
                self.hass, self._on_cloud_change
            )
        try:
            await self.async_report()
        except SoboApiError as err:
            # Not fatal: the coordinator reports again as long as the app does not know the URL.
            _LOGGER.debug("Could not report the guest access: %s", err)

    async def async_stop(self) -> None:
        """On unload: unregister the webhook, keep the cloudhook (the QR code stays valid)."""
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
        """Option "unregister completely while the jukebox is off" (plan 3.2, step 6)."""
        if enabled:
            self._register()
        else:
            self._unregister()

    async def _on_cloud_change(self, _state: Any) -> None:
        await self._refresh_urls()
        try:
            await self.async_report()
        except SoboApiError as err:
            _LOGGER.debug("Could not report the guest access: %s", err)

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
        """Rotate and report to the app (e.g. via the button)."""
        await self.async_rotate_only()
        await self.async_report_rotated(generation)

    async def async_rotate_only(self) -> None:
        """New webhook ID + new cloudhook; old QR codes lead nowhere (plan 3.2)."""
        async with self._lock:
            old_id = self.webhook_id
            self._unregister()
            await delete_cloudhook(self.hass, old_id)
            self._set_webhook_id(webhook.async_generate_id())
            self._register()
            await self._refresh_urls()
            _LOGGER.info("Guest access renewed")

    async def async_report_rotated(self, generation: int) -> None:
        await self.client.report_rotated(
            generation, self.state.url, self.state.local_url, self.state.cloud_connected
        )

    # ------------------------------------------------------------------ requests

    async def _handle(
        self, hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        # HA answers exceptions from handlers with 200 – so catch everything ourselves.
        try:
            if request.method == "GET":
                return self._page_response(request)
            if request.method == "POST":
                return await self._proxy(request)
            return _json_response(405, {"ok": False, "error": "method_not_allowed"})
        except Exception:
            _LOGGER.exception("Error in guest request")
            return _json_response(500, {"ok": False, "error": "internal"})

    def _page_response(self, request: web.Request) -> web.Response:
        data = self.coordinator.data or {}
        active = bool(data.get("effectively_active")) and self.coordinator.last_update_success
        if active:
            # The guest page picks its language itself (navigator.languages).
            html = self._page
        else:
            headers = getattr(request, "headers", None) or {}
            html = self._inactive[_pick_language(headers.get("Accept-Language"))]
        return web.Response(
            text=html, content_type="text/html", charset="utf-8", headers=_PAGE_HEADERS
        )

    async def _proxy(self, request: web.Request) -> web.Response:
        # Cloud requests arrive as a MockRequest without `content_length`.
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
            _LOGGER.debug("App not reachable for guest request: %s", err)
            return _json_response(503, {"ok": False, "error": "unavailable"})
        return web.Response(
            text=text,
            status=status,
            content_type="application/json",
            headers={"Cache-Control": "no-store"},
        )


def cloud_api(hass: HomeAssistant) -> Any | None:
    """The HA `cloud` module if loaded – otherwise None (no Nabu Casa).

    Deliberately a separate function: without `hass_nabucasa` installed the module
    cannot be imported, and tests replace the cloud connection here.
    """
    if "cloud" not in hass.config.components:
        return None
    try:
        from homeassistant.components import cloud
    except ImportError:
        return None
    return cloud


async def _get_cloudhook(hass: HomeAssistant, webhook_id: str) -> tuple[str | None, bool | None]:
    """Get or create the cloudhook URL; (None, False/None) without Nabu Casa."""
    if (cloud := cloud_api(hass)) is None:
        return None, None
    if not cloud.async_active_subscription(hass):
        return None, False
    try:
        url = await cloud.async_get_or_create_cloudhook(hass, webhook_id)
    except cloud.CloudNotAvailable:  # includes CloudNotConnected
        return None, False
    return url, True


async def delete_cloudhook(hass: HomeAssistant, webhook_id: str) -> None:
    if (cloud := cloud_api(hass)) is None:
        return
    if not cloud.async_is_logged_in(hass):
        return
    try:
        await cloud.async_delete_cloudhook(hass, webhook_id)
    except (cloud.CloudNotAvailable, ValueError) as err:
        # ValueError: the hook did not exist (hass_nabucasa)
        _LOGGER.debug("Cloudhook not deleted: %s", err)
