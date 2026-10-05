"""Constants of the SoBo integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "sobo"

CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_SECRET: Final = "secret"  # noqa: S105 – key name
CONF_WEBHOOK_ID: Final = "webhook_id"

DEFAULT_HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8738

SECRET_HEADER: Final = "X-SoBo-Secret"  # noqa: S105 – header name
SCAN_INTERVAL: Final = timedelta(seconds=5)

# Guest requests (plan 6): small bodies, long-poll wait time + buffer
MAX_GUEST_BODY: Final = 4096
DEFAULT_LONG_POLL_TIMEOUT: Final = 20
PROXY_TIMEOUT_EXTRA: Final = 5
REQUEST_TIMEOUT: Final = 10

WEBHOOK_NAME: Final = "SoBo guest access"
