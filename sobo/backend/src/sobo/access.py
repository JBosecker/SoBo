"""Guest access as reported by the integration, and the key of the party display."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .security.secrets import constant_time_equals, create_secret, load_or_create_secret

# Query parameter on the guest link that makes the integration serve the display page.
DISPLAY_QUERY = "view=display"


@dataclass
class GuestAccessInfo:
    """Guest access state as reported by the integration (plan 3.3)."""

    url: str | None = None
    local_url: str | None = None
    cloud_connected: bool | None = None
    reported_at: datetime | None = None

    @property
    def join_url(self) -> str | None:
        """The link guests should use: the cloudhook, otherwise the local webhook."""
        return self.url or self.local_url


class DisplayKey:
    """Opens the party display (a TV or tablet) without a guest session.

    The key travels in the URL fragment, so the relay and HA never log it; the display
    page sends it in the POST body. Stored in plain text like the shared secret: the
    admin UI shows the full link again and again.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self.value = load_or_create_secret(path)

    def renew(self) -> None:
        """New key: every open display has to be opened again with the new link."""
        self.value = create_secret(self._path)

    def matches(self, given: str | None) -> bool:
        return constant_time_equals(given, self.value)

    def url(self, join_url: str) -> str:
        return f"{join_url}?{DISPLAY_QUERY}#key={self.value}"
