"""Time source. The engine and the fake adapter get the clock injected so tests can fake time."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time (UTC, timezone-aware)."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class ManualClock:
    """Clock for tests: stands still until `advance()` is called."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, 20, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


class ScaledClock:
    """Accelerated clock for the fake adapter in development (e.g. 10x)."""

    def __init__(self, speed: float, base: Clock | None = None) -> None:
        self._base = base or SystemClock()
        self._speed = speed
        self._origin = self._base.now()

    def now(self) -> datetime:
        real = self._base.now()
        return self._origin + (real - self._origin) * self._speed
