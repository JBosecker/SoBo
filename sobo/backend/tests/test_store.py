"""SQLite store: migration, round trip, engine restart (plan 7)."""

from __future__ import annotations

import random
from datetime import timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlmodel")
pytest.importorskip("alembic")

from sobo.clock import ManualClock
from sobo.engine.jukebox import Jukebox
from sobo.engine.models import AuditEntry, ItemState
from sobo.sonos.fake_adapter import FakeSonosAdapter
from sobo.sonos.worker import SonosWorker
from sobo.store.db import SqlRepository

from .conftest import active_settings, suggest_title

pytestmark = pytest.mark.anyio


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "sobo.db"


def test_migration_is_idempotent(db_path: Path) -> None:
    clock = ManualClock()
    SqlRepository.for_path(db_path, clock).dispose()
    repo = SqlRepository.for_path(db_path, clock)
    assert repo.load().settings is None
    repo.dispose()


async def test_engine_restart_with_sqlite(db_path: Path) -> None:
    clock = ManualClock()
    fake = FakeSonosAdapter(clock)
    repo = SqlRepository.for_path(db_path, clock)
    repo.save_settings(active_settings())
    jb = Jukebox(SonosWorker(fake), repo, clock, rng=random.Random(1))
    a = jb.join("Mia", "hash-a", None)
    b = jb.join("Tom", "hash-b", None)
    first = await suggest_title(jb, a, "Slow Comet")
    await jb.tick()
    queued = await suggest_title(jb, a, "Copper Sky")
    await jb.vote(b, queued.id)
    await jb.pin_item(queued.id, True, "admin")
    jb.worker.shutdown()
    repo.dispose()

    repo2 = SqlRepository.for_path(db_path, clock)
    restarted = Jukebox(SonosWorker(fake), repo2, clock, rng=random.Random(1))
    assert restarted.settings.active is True
    playing = restarted.queue.get(first.id)
    assert playing is not None and playing.state == ItemState.PLAYING
    assert playing.started_at == first.started_at
    restored = restarted.queue.get(queued.id)
    assert restored is not None
    assert restored.voters == {a.id, b.id} and restored.pinned
    assert restored.track == queued.track
    assert restarted.guest_for_token("hash-a") is not None
    assert restarted.vote_budget(b.id)[0] == restarted.settings.votes.votes_per_window - 1
    restarted.worker.shutdown()
    repo2.dispose()


def test_audit_and_purge(db_path: Path) -> None:
    clock = ManualClock()
    repo = SqlRepository.for_path(db_path, clock)
    repo.add_audit(AuditEntry(clock.now(), "admin", "old"))
    clock.advance(31 * 24 * 3600)
    repo.add_audit(AuditEntry(clock.now(), "admin", "new"))
    assert [e.action for e in repo.recent_audit(10)] == ["new", "old"]
    repo.purge_history(timedelta(days=30))
    assert [e.action for e in repo.recent_audit(10)] == ["new"]
    repo.dispose()


def test_delete_all_guests(db_path: Path) -> None:
    from sobo.engine.models import Guest

    clock = ManualClock()
    repo = SqlRepository.for_path(db_path, clock)
    repo.save_guest(Guest("g1", "h1", "Mia", clock.now(), clock.now()))
    assert len(repo.load().guests) == 1
    repo.delete_all_guests()
    assert repo.load().guests == []
    repo.dispose()
