"""Testumgebung für die Gast-Seite: verhält sich wie die Integration.

GET liefert `guest_page.html`, POST geht an die echte `GuestService` mit
simuliertem Sonos. Fehler des Cloudhook-Relays lassen sich gezielt einschalten.

Zum Ansehen im Browser:  python -m tests.guest_harness  → http://127.0.0.1:8740/g/demo
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
import threading
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from sobo.api.guest_service import GuestService
from sobo.clock import ScaledClock, SystemClock
from sobo.engine.jukebox import Jukebox
from sobo.engine.persistence import MemoryRepository
from sobo.engine.scheduler import Scheduler
from sobo.engine.settings import (
    FallbackSettings,
    GuestAccessSettings,
    JukeboxSettings,
    SpeakerSettings,
)
from sobo.sonos.fake_adapter import FakeSonosAdapter
from sobo.sonos.fixtures import FAKE_ACCOUNT_ID
from sobo.sonos.worker import SonosWorker

PAGE = Path(__file__).resolve().parents[3] / "custom_components" / "sobo" / "guest_page.html"


@dataclass
class Faults:
    """Simuliert einen Relay, der Long-Polls abbricht."""

    fail_wait: bool = False
    actions: list[str] = field(default_factory=list)


@dataclass
class Harness:
    app: Starlette
    jukebox: Jukebox
    service: GuestService
    faults: Faults
    loop: asyncio.AbstractEventLoop | None = None

    def run(self, coro: Any) -> Any:
        """Führt eine Coroutine in der Server-Loop aus (aus dem Test-Thread)."""
        assert self.loop is not None
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(10)


def settings(fallback: bool = True) -> JukeboxSettings:
    return JukeboxSettings(
        active=True,
        account_id=FAKE_ACCOUNT_ID,
        speaker=SpeakerSettings(coordinator_uid="RINCON_FAKE_LIVING"),
        fallback=FallbackSettings(source_id="fake_playlist:party" if fallback else None),
        guest_access=GuestAccessSettings(long_poll_timeout=5),
        timezone="UTC",
    )


def create_harness(speed: float = 20.0, fallback: bool = True) -> Harness:
    clock = SystemClock()
    adapter = FakeSonosAdapter(ScaledClock(speed, clock))
    repo = MemoryRepository()
    repo.save_settings(settings(fallback))
    worker = SonosWorker(adapter)
    jukebox = Jukebox(worker, repo, clock, rng=random.Random(4))
    service = GuestService(jukebox)
    scheduler = Scheduler(jukebox, interval=0.3)
    faults = Faults()
    page = PAGE.read_text(encoding="utf-8")
    holder: dict[str, Harness] = {}

    async def get_page(_: Request) -> Response:
        return HTMLResponse(page, headers={"Cache-Control": "no-store"})

    async def post_action(request: Request) -> Response:
        body = await request.body()
        try:
            action = json.loads(body).get("action", "?")
        except (ValueError, AttributeError):
            action = "?"
        faults.actions.append(action)
        if faults.fail_wait and action == "wait":
            await asyncio.sleep(0.05)
            return JSONResponse({"ok": False, "error": "unavailable"}, status_code=502)
        status, payload = await service.handle(body)
        return JSONResponse(payload, status_code=status)

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        holder["h"].loop = asyncio.get_running_loop()
        scheduler.start()
        yield
        await scheduler.stop()
        worker.shutdown()

    app = Starlette(
        routes=[
            Route("/g/{hook}", get_page, methods=["GET"]),
            Route("/g/{hook}", post_action, methods=["POST"]),
        ],
        lifespan=lifespan,
    )
    harness = Harness(app, jukebox, service, faults)
    holder["h"] = harness
    return harness


@contextlib.contextmanager
def serve(harness: Harness, port: int = 0) -> Iterator[str]:
    """Startet den Server in einem Thread und liefert die Basis-URL."""
    config = uvicorn.Config(harness.app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("Testserver startet nicht")
        time.sleep(0.02)
    sock = server.servers[0].sockets[0]
    host, actual_port = sock.getsockname()[:2]
    try:
        yield f"http://{host}:{actual_port}/g/test-hook"
    finally:
        server.should_exit = True
        thread.join(10)


if __name__ == "__main__":
    demo = create_harness()
    with serve(demo, port=8740) as url:
        print(f"Gast-Seite: {url}")
        with contextlib.suppress(KeyboardInterrupt):
            while True:
                time.sleep(1)
