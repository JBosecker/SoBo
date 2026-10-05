"""Serialises all (synchronous) Sonos calls through a dedicated thread (plan 4.2)."""

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
        """Run `fn(adapter)` on the Sonos thread.

        Unexpected exceptions are wrapped in `SonosError` so the engine only has to
        handle one error type. On timeout the call keeps running in the thread;
        subsequent calls queue up behind it.
        """
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(self._executor, fn, self.adapter)
        try:
            return await asyncio.wait_for(future, timeout or self.timeout)
        except TimeoutError as err:
            _LOG.warning("Sonos call timed out")
            raise SonosTimeout("Sonos call timed out") from err
        except SonosError:
            raise
        except Exception as err:
            _LOG.exception("Unexpected error in the Sonos adapter")
            raise SonosError(str(err)) from err

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
