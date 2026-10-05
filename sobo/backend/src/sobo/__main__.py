"""App entry point: two uvicorn servers in one event loop.

* Admin/ingress on `0.0.0.0:8737` (only reachable from the ingress IP)
* Internal API for the integration on `127.0.0.1:8738` (shared secret)
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
                _LOG.exception("Purging the history failed")
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
            # Long-poll requests may stay open longer than the default.
            timeout_keep_alive=75,
        )
    )
    # Handle signals ourselves: uvicorn's handling is per server and two servers
    # would overwrite each other's handlers.
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
