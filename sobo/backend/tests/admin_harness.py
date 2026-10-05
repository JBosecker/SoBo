"""Test environment for the admin UI: the real admin app (FastAPI) with a simulated
Sonos, the SQLite store and a mocked integration.

To look at it in a browser:  python -m tests.admin_harness  → http://127.0.0.1:8741/
"""

from __future__ import annotations

import asyncio
import contextlib
import tempfile
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI

from sobo.api.admin import create_admin_app
from sobo.clock import ScaledClock, SystemClock
from sobo.config import AppOptions
from sobo.context import AppContext
from sobo.sonos.fake_adapter import FakeSonosAdapter
from sobo.store.db import SqlRepository

CLOUD_URL = "https://hooks.nabu.casa/demo-AbCdEfGhIjKlMnOp"


@dataclass
class AdminHarness:
    app: FastAPI
    ctx: AppContext
    adapter: FakeSonosAdapter
    loop: asyncio.AbstractEventLoop | None = None

    def run(self, coro: Any) -> Any:
        assert self.loop is not None
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(10)


async def _fake_integration(ctx: AppContext) -> None:
    """Reports the guest link and executes requested rotations – like the integration."""
    generation = 0
    while True:
        ctx.integration_seen()
        if ctx.rotation_requested > ctx.rotation_done:
            generation += 1
            ctx.guest_access.url = f"{CLOUD_URL}-{generation}"
            ctx.rotation_done = ctx.rotation_requested
            ctx.guest_service.reset()
            await ctx.jukebox.rotate_sessions("integration")
        await asyncio.sleep(0.2)


def create_admin_harness(
    data_dir: Path | None = None, speed: float = 20.0, integration: bool = True
) -> AdminHarness:
    data_dir = data_dir or Path(tempfile.mkdtemp(prefix="sobo-admin-"))
    clock = SystemClock()
    adapter = FakeSonosAdapter(ScaledClock(speed, clock))
    options = AppOptions(data_dir=data_dir, trusted_ingress=frozenset({"127.0.0.1"}))
    repo = SqlRepository.for_path(options.db_path, clock)
    ctx = AppContext.build(options, adapter=adapter, repo=repo, clock=clock)
    if integration:
        ctx.guest_access.url = CLOUD_URL
        ctx.guest_access.local_url = "http://192.168.1.20:8123/api/webhook/demo"
        ctx.guest_access.cloud_connected = True
    app = create_admin_app(ctx)
    harness = AdminHarness(app, ctx, adapter)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        harness.loop = asyncio.get_running_loop()
        ctx.start()
        task = asyncio.create_task(_fake_integration(ctx)) if integration else None
        yield
        if task:
            task.cancel()
        await ctx.stop()

    app.router.lifespan_context = lifespan
    return harness


@contextlib.contextmanager
def serve(harness: AdminHarness, port: int = 0) -> Iterator[str]:
    config = uvicorn.Config(harness.app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    import threading

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("Test server does not start")
        time.sleep(0.02)
    host, actual_port = server.servers[0].sockets[0].getsockname()[:2]
    try:
        yield f"http://{host}:{actual_port}/"
    finally:
        server.should_exit = True
        thread.join(10)


if __name__ == "__main__":
    demo = create_admin_harness()
    with serve(demo, port=8741) as url:
        print(f"Admin UI: {url}")
        with contextlib.suppress(KeyboardInterrupt):
            while True:
                time.sleep(1)
