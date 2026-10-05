"""Treibt die Engine: Polling des Transport-Status alle 1–2 s (Plan 4.2) und
sofortige Reaktion auf Gast-Aktionen über `Jukebox.wakeup`."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from .jukebox import Jukebox

_LOG = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, jukebox: Jukebox, interval: float = 1.5) -> None:
        self.jukebox = jukebox
        self.interval = interval
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="sobo-scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        wakeup = self.jukebox.wakeup
        while True:
            wakeup.clear()
            try:
                await self.jukebox.tick()
            except Exception:  # Der Scheduler darf nie sterben.
                _LOG.exception("Fehler im Jukebox-Tick")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(wakeup.wait(), self.interval)
