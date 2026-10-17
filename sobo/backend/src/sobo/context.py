"""Wiring of all building blocks; shared by the admin app and the internal app."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .access import DisplayKey, GuestAccessInfo
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


__all__ = ["AppContext", "GuestAccessInfo"]


@dataclass
class AppContext:
    options: AppOptions
    clock: Clock
    worker: SonosWorker
    jukebox: Jukebox
    guest_service: GuestService
    scheduler: Scheduler
    secret: str
    display_key: DisplayKey
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
        guest_access = GuestAccessInfo()
        display_key = DisplayKey(options.display_key_path)
        return cls(
            options=options,
            clock=clock,
            worker=worker,
            jukebox=jukebox,
            guest_service=GuestService(jukebox, guest_access=guest_access, display_key=display_key),
            scheduler=Scheduler(jukebox, options.poll_interval),
            secret=load_or_create_secret(options.secret_path),
            display_key=display_key,
            guest_access=guest_access,
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
            "display_url": self.display_url,
        }

    @property
    def display_url(self) -> str | None:
        """Link for the party display; None while it is off or no guest link is known."""
        join_url = self.guest_access.join_url
        if not self.jukebox.settings.display.enabled or not join_url:
            return None
        return self.display_key.url(join_url)

    def renew_display_key(self) -> None:
        self.display_key.renew()
        # Open displays get their next answer now and find the old key rejected.
        self.guest_service.end_display_polls()
