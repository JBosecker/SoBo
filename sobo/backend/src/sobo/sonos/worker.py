"""Serialisiert alle (synchronen) Sonos-Aufrufe über einen dedizierten Thread (Plan 4.2)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

from .adapter import SonosAdapter, SonosError, SonosTimeout

_LOG = logging.getLogger(__name__)
T = TypeVar("T")


class SonosWorker:
    def __init__(self, adapter: SonosAdapter, timeout: float = 10.0) -> None:
        self.adapter = adapter
        self.timeout = timeout
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sonos")

    async def call(self, fn: Callable[[SonosAdapter], T], timeout: float | None = None) -> T:
        """Führt `fn(adapter)` im Sonos-Thread aus.

        Unerwartete Ausnahmen werden in `SonosError` verpackt, damit die Engine
        nur einen Fehlertyp behandeln muss. Bei Zeitüberschreitung läuft der
        Aufruf im Thread weiter; nachfolgende Aufrufe warten dahinter.
        """
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(self._executor, fn, self.adapter)
        try:
            return await asyncio.wait_for(future, timeout or self.timeout)
        except TimeoutError as err:
            _LOG.warning("Sonos-Aufruf hat das Zeitlimit überschritten")
            raise SonosTimeout("Zeitüberschreitung bei Sonos") from err
        except SonosError:
            raise
        except Exception as err:
            _LOG.exception("Unerwarteter Fehler im Sonos-Adapter")
            raise SonosError(str(err)) from err

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
