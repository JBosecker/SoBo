"""Supervisor discovery: announces host, port and secret to HA so the integration
can pair via `async_step_hassio` (plan 3.3)."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

_LOG = logging.getLogger(__name__)

SUPERVISOR_URL = "http://supervisor"
SERVICE = "sobo"


def discovery_payload(host: str, port: int, secret: str) -> dict[str, Any]:
    return {"service": SERVICE, "config": {"host": host, "port": port, "secret": secret}}


async def announce(
    host: str, port: int, secret: str, client: httpx.AsyncClient | None = None
) -> bool:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        _LOG.info("No SUPERVISOR_TOKEN – skipping discovery (development?)")
        return False
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=10)
    try:
        response = await client.post(
            f"{SUPERVISOR_URL}/discovery",
            json=discovery_payload(host, port, secret),
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
    except httpx.HTTPError as err:
        _LOG.warning("Supervisor discovery failed: %s", err)
        return False
    finally:
        if own_client:
            await client.aclose()
    _LOG.info("Discovery announced to Home Assistant")
    return True
