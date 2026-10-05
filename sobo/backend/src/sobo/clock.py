"""Zeitquelle. Engine und Fake-Adapter bekommen die Uhr injiziert, damit Tests Zeit simulieren."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Aktuelle Zeit (UTC, timezone-aware)."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class ManualClock:
    """Uhr für Tests: steht still, bis `advance()` aufgerufen wird."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, 20, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


class ScaledClock:
    """Beschleunigte Uhr für den Fake-Adapter im Devcontainer (z. B. 10x)."""

    def __init__(self, speed: float, base: Clock | None = None) -> None:
        self._base = base or SystemClock()
        self._speed = speed
        self._origin = self._base.now()

    def now(self) -> datetime:
        real = self._base.now()
        return self._origin + (real - self._origin) * self._speed
