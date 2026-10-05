"""Shared Secret zwischen App und Integration (Plan 3.3, 4.2)."""

from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path


def load_or_create_secret(path: Path) -> str:
    """Liest das Secret aus `path` oder erzeugt es (256 Bit) mit Dateirechten 0600."""
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if len(value) >= 32:
            return value
    value = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(value)
    return value


def constant_time_equals(given: str | None, expected: str) -> bool:
    if not given:
        return False
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))
