"""Konstanten der SoBo-Integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "sobo"

CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_SECRET: Final = "secret"  # noqa: S105 – Schlüsselname
CONF_WEBHOOK_ID: Final = "webhook_id"

DEFAULT_HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8738

SECRET_HEADER: Final = "X-SoBo-Secret"  # noqa: S105 – Header-Name
SCAN_INTERVAL: Final = timedelta(seconds=5)

# Gast-Anfragen (Plan 6): kleine Bodies, Long-Poll-Wartezeit + Puffer
MAX_GUEST_BODY: Final = 4096
DEFAULT_LONG_POLL_TIMEOUT: Final = 20
PROXY_TIMEOUT_EXTRA: Final = 5
REQUEST_TIMEOUT: Final = 10

WEBHOOK_NAME: Final = "SoBo Gastzugang"
