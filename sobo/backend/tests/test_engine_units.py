from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime, time, timedelta

import pytest

from sobo.clock import ManualClock
from sobo.engine.fallback import FallbackPlaylist
from sobo.engine.limits import sliding_budget
from sobo.engine.models import ItemState, Origin, QueueItem
from sobo.engine.ranking import ranked
from sobo.engine.search_cache import SearchCache
from sobo.engine.settings import JukeboxSettings, ScheduleSettings
from sobo.engine.state import ChangeNotifier
from sobo.sonos.fixtures import fake_catalog

T0 = datetime(2026, 1, 1, 20, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- change signal


@pytest.mark.anyio
async def test_notifier_returns_immediately_when_newer() -> None:
    notifier = ChangeNotifier()
    notifier.bump()
    assert await notifier.wait(0, timeout=5) is True


@pytest.mark.anyio
async def test_notifier_wakes_on_change() -> None:
    notifier = ChangeNotifier()
    waiter = asyncio.create_task(notifier.wait(0, timeout=5))
    await asyncio.sleep(0.01)
    assert not waiter.done()
    notifier.bump()
    assert await asyncio.wait_for(waiter, 1) is True


@pytest.mark.anyio
async def test_notifier_timeout() -> None:
    notifier = ChangeNotifier()
    assert await notifier.wait(0, timeout=0.02) is False


@pytest.mark.anyio
async def test_notifier_cancel() -> None:
    notifier = ChangeNotifier()
    cancel = asyncio.Event()
    waiter = asyncio.create_task(notifier.wait(0, timeout=5, cancel=cancel))
    await asyncio.sleep(0.01)
    cancel.set()
    assert await asyncio.wait_for(waiter, 1) is False


@pytest.mark.anyio
async def test_notifier_many_waiters() -> None:
    notifier = ChangeNotifier()
    waiters = [asyncio.create_task(notifier.wait(0, timeout=5)) for _ in range(200)]
    await asyncio.sleep(0.01)
    notifier.bump()
    assert all(await asyncio.gather(*waiters))


# ------------------------------------------------------------- Budget, Ranking, Fallback


def test_sliding_budget() -> None:
    window = timedelta(minutes=10)
    state = sliding_budget([], 3, window, T0)
    assert (state.remaining, state.next_free_in) == (3, None)
    events = [T0 - timedelta(minutes=12), T0 - timedelta(minutes=4), T0 - timedelta(minutes=1)]
    state = sliding_budget(events, 2, window, T0)
    assert state.remaining == 0
    assert state.next_free_in == pytest.approx(6 * 60)


def _item(n: int, votes: int, pinned: bool = False, offset: int = 0) -> QueueItem:
    item = QueueItem(
        f"id{n}", fake_catalog()[n], Origin.GUEST, T0 + timedelta(seconds=offset), pinned=pinned
    )
    item.voters = {f"g{i}" for i in range(votes)}
    return item


def test_ranking_order() -> None:
    a = _item(0, votes=1, offset=0)
    b = _item(1, votes=3, offset=10)
    c = _item(2, votes=3, offset=5)
    d = _item(3, votes=0, pinned=True, offset=20)
    assert [i.id for i in ranked([a, b, c, d])] == ["id3", "id2", "id1", "id0"]


def test_fallback_ordered_cycles_and_excludes() -> None:
    tracks = fake_catalog()[:3]
    playlist = FallbackPlaylist(tracks, shuffle=False, key_fn=lambda t: t.item_id)
    titles = [playlist.next_track().title for _ in range(4)]  # type: ignore[union-attr]
    assert titles == ["Neon Harbor", "Paper Satellites", "Salt & Static", "Neon Harbor"]
    nxt = playlist.next_track(exclude_keys={tracks[1].item_id})
    assert nxt is tracks[2]


def test_fallback_shuffle_deterministic_with_seed() -> None:
    tracks = fake_catalog()
    one = FallbackPlaylist(tracks, True, lambda t: t.item_id, random.Random(3))
    two = FallbackPlaylist(tracks, True, lambda t: t.item_id, random.Random(3))
    assert [one.next_track() for _ in range(10)] == [two.next_track() for _ in range(10)]


def test_fallback_empty() -> None:
    assert FallbackPlaylist([], True, lambda t: t.item_id).next_track() is None


def test_search_cache_expiry() -> None:
    clock = ManualClock()
    cache = SearchCache(clock, ttl=timedelta(minutes=1), max_entries=2)
    track = fake_catalog()[0]
    first = cache.put(track)
    assert cache.get(first) is track
    clock.advance(61)
    assert cache.get(first) is None
    ids = [cache.put(track) for _ in range(3)]
    assert len(cache) == 2
    assert cache.get(ids[0]) is None


# --------------------------------------------------------------------------- settings


@pytest.mark.parametrize(
    ("start", "end", "moment", "expected"),
    [
        (time(18), time(23), time(19), True),
        (time(18), time(23), time(23, 30), False),
        (time(18), time(2), time(1), True),
        (time(18), time(2), time(12), False),
    ],
)
def test_schedule_window(start: time, end: time, moment: time, expected: bool) -> None:
    schedule = ScheduleSettings(enabled=True, start=start, end=end)
    assert schedule.contains(moment) is expected


def test_settings_validation() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        JukeboxSettings.model_validate({"speaker": {"max_volume": 101}})
    with pytest.raises(ValidationError):
        JukeboxSettings.model_validate({"guest_access": {"presence_code": "12a4"}})
    with pytest.raises(ValidationError):
        JukeboxSettings.model_validate({"unbekannt": True})
    settings = JukeboxSettings.model_validate({"limits": {"blocklist": ["  x ", "", "y"]}})
    assert settings.limits.blocklist == ["x", "y"]


def test_item_open_states() -> None:
    item = _item(0, 0)
    for state, is_open in [
        (ItemState.QUEUED, True),
        (ItemState.NEXT, True),
        (ItemState.PLAYING, True),
        (ItemState.PLAYED, False),
        (ItemState.REMOVED, False),
    ]:
        item.state = state
        assert item.is_open is is_open
