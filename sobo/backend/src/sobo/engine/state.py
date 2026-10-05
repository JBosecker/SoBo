"""Jukebox-Zustände und globales Änderungssignal (Plan 4.2, 5.4)."""

from __future__ import annotations

import asyncio
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
    """Versionszähler + Weckruf für Long-Poll-Anfragen.

    Jede relevante Änderung ruft `bump()` auf. Wartende werden über ein Event
    geweckt, das bei jedem Bump ersetzt wird; so braucht `bump()` keinen Lock
    und ist auch aus synchronem Code innerhalb der Event-Loop aufrufbar.
    """

    def __init__(self) -> None:
        self._version = 0
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
        """Wartet, bis die Version neuer als `since` ist.

        Gibt True zurück bei Änderung, False bei Timeout oder Abbruch über `cancel`.
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
            # Event wurde durch bump() gesetzt → nächste Runde liefert True.
