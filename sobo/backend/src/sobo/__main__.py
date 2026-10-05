"""Startpunkt der App: zwei uvicorn-Server in einer Event-Loop.

* Admin/Ingress auf `0.0.0.0:8737` (Zugriff nur von der Ingress-IP)
* Interne API für die Integration auf `127.0.0.1:8738` (Secret)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from datetime import timedelta

import uvicorn

from .api.admin import create_admin_app
from .api.internal import create_internal_app
from .config import AppOptions
from .context import AppContext
from .discovery import announce

_LOG = logging.getLogger("sobo")

LOG_LEVELS = {
    "trace": logging.DEBUG,
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}
HISTORY_RETENTION = timedelta(days=30)


async def _housekeeping(ctx: AppContext) -> None:
    purge = getattr(ctx.jukebox.repo, "purge_history", None)
    while True:
        if purge is not None:
            try:
                purge(HISTORY_RETENTION)
            except Exception:
                _LOG.exception("Aufräumen der Historie fehlgeschlagen")
        await asyncio.sleep(6 * 3600)


async def run(options: AppOptions) -> None:
    ctx = AppContext.build(options)
    level = options.log_level.lower()
    admin = uvicorn.Server(
        uvicorn.Config(
            create_admin_app(ctx),
            host=options.host,
            port=options.port,
            log_level=level if level != "trace" else "debug",
            proxy_headers=False,
            server_header=False,
            access_log=level in ("trace", "debug"),
        )
    )
    internal = uvicorn.Server(
        uvicorn.Config(
            create_internal_app(ctx),
            host=options.internal_host,
            port=options.internal_port,
            log_level="warning",
            proxy_headers=False,
            server_header=False,
            access_log=False,
            # Long-Poll-Anfragen dürfen länger offen bleiben als der Standard.
            timeout_keep_alive=75,
        )
    )
    # Signale selbst behandeln: uvicorns eigene Behandlung ist pro Server gedacht
    # und würde sich bei zwei Servern gegenseitig überschreiben.
    admin.capture_signals = contextlib.nullcontext  # type: ignore[method-assign,assignment]
    internal.capture_signals = contextlib.nullcontext  # type: ignore[method-assign,assignment]

    def _shutdown() -> None:
        admin.should_exit = True
        internal.should_exit = True

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    ctx.start()
    house = asyncio.create_task(_housekeeping(ctx))
    await announce(options.internal_host, options.internal_port, ctx.secret)
    try:
        await asyncio.gather(admin.serve(), internal.serve())
    finally:
        house.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await house
        await ctx.stop()


def main() -> None:
    options = AppOptions.load()
    logging.basicConfig(
        level=LOG_LEVELS.get(options.log_level.lower(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run(options))


if __name__ == "__main__":
    main()
