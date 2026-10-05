"""Wiring of all building blocks; shared by the admin app and the internal app."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .api.guest_service import GuestService
from .clock import Clock, ScaledClock, SystemClock
from .config import AppOptions
from .engine.jukebox import Jukebox
from .engine.persistence import Repository
from .engine.scheduler import Scheduler
from .security.secrets import load_or_create_secret
from .sonos.adapter import SonosAdapter
from .sonos.worker import SonosWorker

_LOG = logging.getLogger(__name__)

INTEGRATION_TIMEOUT = timedelta(seconds=60)


@dataclass
class GuestAccessInfo:
    """Guest access state as reported by the integration (plan 3.3)."""

    url: str | None = None
    local_url: str | None = None
    cloud_connected: bool | None = None
    reported_at: datetime | None = None


@dataclass
class AppContext:
    options: AppOptions
    clock: Clock
    worker: SonosWorker
    jukebox: Jukebox
    guest_service: GuestService
    scheduler: Scheduler
    secret: str
    guest_access: GuestAccessInfo = field(default_factory=GuestAccessInfo)
    # A counter instead of a callback: the integration polls /internal/status and
    # rotates as soon as the counter increases.
    rotation_requested: int = 0
    rotation_done: int = 0
    last_integration_contact: datetime | None = None

    @classmethod
    def build(
        cls,
        options: AppOptions,
        adapter: SonosAdapter | None = None,
        repo: Repository | None = None,
        clock: Clock | None = None,
    ) -> AppContext:
        clock = clock or SystemClock()
        if adapter is None:
            if options.fake_sonos:
                from .sonos.fake_adapter import FakeSonosAdapter

                _LOG.warning("Sonos simulation active (fake_sonos)")
                adapter = FakeSonosAdapter(ScaledClock(options.fake_speed, clock))
            else:
                from .sonos.soco_adapter import SoCoAdapter

                adapter = SoCoAdapter()
        if repo is None:
            from .store.db import SqlRepository

            repo = SqlRepository.for_path(options.db_path, clock)
        worker = SonosWorker(adapter)
        jukebox = Jukebox(worker, repo, clock)
        return cls(
            options=options,
            clock=clock,
            worker=worker,
            jukebox=jukebox,
            guest_service=GuestService(jukebox),
            scheduler=Scheduler(jukebox, options.poll_interval),
            secret=load_or_create_secret(options.secret_path),
        )

    def start(self) -> None:
        self.scheduler.start()

    async def stop(self) -> None:
        await self.scheduler.stop()
        self.worker.shutdown()

    def integration_seen(self) -> None:
        self.last_integration_contact = self.clock.now()

    @property
    def integration_connected(self) -> bool:
        last = self.last_integration_contact
        return last is not None and self.clock.now() - last < INTEGRATION_TIMEOUT

    def guest_access_view(self) -> dict[str, Any]:
        info = self.guest_access
        return {
            "integration_connected": self.integration_connected,
            "url": info.url,
            "local_url": info.local_url,
            "cloud_connected": info.cloud_connected,
            "rotation_pending": self.rotation_requested > self.rotation_done,
        }
