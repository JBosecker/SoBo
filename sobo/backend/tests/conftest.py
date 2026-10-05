from __future__ import annotations

import random
from collections.abc import AsyncIterator

import pytest

from sobo.clock import ManualClock
from sobo.engine.jukebox import Jukebox
from sobo.engine.models import Guest
from sobo.engine.persistence import MemoryRepository
from sobo.engine.settings import JukeboxSettings, SpeakerSettings
from sobo.sonos.fake_adapter import FakeSonosAdapter
from sobo.sonos.fixtures import FAKE_ACCOUNT_ID
from sobo.sonos.worker import SonosWorker


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def fake(clock: ManualClock) -> FakeSonosAdapter:
    return FakeSonosAdapter(clock)


@pytest.fixture
def repo() -> MemoryRepository:
    return MemoryRepository()


def active_settings(**overrides: object) -> JukeboxSettings:
    base = JukeboxSettings(
        active=True,
        account_id=FAKE_ACCOUNT_ID,
        speaker=SpeakerSettings(coordinator_uid="RINCON_FAKE_LIVING", max_volume=60),
        timezone="UTC",
    )
    return base.model_copy(update=overrides)


@pytest.fixture
async def jukebox(
    fake: FakeSonosAdapter, clock: ManualClock, repo: MemoryRepository
) -> AsyncIterator[Jukebox]:
    repo.save_settings(active_settings())
    worker = SonosWorker(fake, timeout=5)
    jb = Jukebox(worker, repo, clock, rng=random.Random(7))
    yield jb
    worker.shutdown()


_counter = 0


def make_guest(jb: Jukebox, nickname: str = "Gast") -> Guest:
    global _counter
    _counter += 1
    return jb.join(nickname, f"hash-{_counter}", None)


async def suggest_title(jb: Jukebox, guest: Guest, title: str):  # type: ignore[no-untyped-def]
    hits = await jb.search(guest, title)
    hit = next(h for h in hits if h.track.title == title)
    item = await jb.suggest(guest, hit.opaque_id)
    # Realistischer Abstand zwischen Vorschlägen; sonst entscheidet bei
    # Gleichstand die zufällige ID über die Reihenfolge.
    if isinstance(jb.clock, ManualClock):
        jb.clock.advance(1)
    return item
