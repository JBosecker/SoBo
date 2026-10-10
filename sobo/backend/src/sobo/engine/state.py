"""Jukebox states and the global change signal (plan 4.2, 5.4)."""

from __future__ import annotations

import asyncio
import secrets
from enum import StrEnum


class JukeboxState(StrEnum):
    INACTIVE = "inactive"
    IDLE = "idle"
    PLAYING_GUEST = "playing_guest"
    PLAYING_FALLBACK = "playing_fallback"
    PAUSED = "paused"
    MANUAL_OVERRIDE = "manual_override"
    ERROR = "error"


class ChangeNotifier:
    """Version counter + wake-up for long-poll requests.

    Every relevant change calls `bump()`. Waiters are woken through an event that
    is replaced on every bump, so `bump()` needs no lock and can also be called
    from synchronous code inside the event loop.
    """

    def __init__(self) -> None:
        self._version = 0
        # Changes with every start of the app: the version starts at 0 again, so pages
        # compare versions only within the same epoch.
        self.epoch = secrets.token_hex(4)
        self._event = asyncio.Event()

    @property
    def version(self) -> int:
        return self._version

    def bump(self) -> int:
        self._version += 1
        event, self._event = self._event, asyncio.Event()
        event.set()
        return self._version

    async def wait(self, since: int, timeout: float, cancel: asyncio.Event | None = None) -> bool:
        """Wait until the version is newer than `since`.

        Returns True on a change, False on timeout or cancellation via `cancel`.
        """
        while True:
            if self._version > since:
                return True
            waiters = [asyncio.ensure_future(self._event.wait())]
            if cancel is not None:
                if cancel.is_set():
                    waiters[0].cancel()
                    return False
                waiters.append(asyncio.ensure_future(cancel.wait()))
            try:
                done, _ = await asyncio.wait(
                    waiters, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
                )
            finally:
                for waiter in waiters:
                    waiter.cancel()
            if not done:
                return self._version > since
            if cancel is not None and cancel.is_set():
                return self._version > since
            # The event was set by bump() → the next round returns True.
