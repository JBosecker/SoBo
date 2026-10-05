"""In-process load test (plan 9): ~100 guests, all with an open long poll.

Complements the Locust scenario in `loadtest/` (which runs against a real app over
HTTP) with fast, deterministic checks that run in CI.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import pytest

from sobo.api.guest_service import GuestService
from sobo.engine.jukebox import Jukebox
from sobo.engine.settings import GuestAccessSettings
from sobo.security.ratelimit import TokenBucket

from .conftest import active_settings

pytestmark = pytest.mark.anyio

GUESTS = 100


async def call(service: GuestService, **payload: Any) -> tuple[int, dict[str, Any]]:
    return await service.handle(json.dumps(payload).encode())


async def crowd(
    jukebox: Jukebox, *, max_open: int, guests: int = GUESTS
) -> tuple[GuestService, list[str]]:
    access = GuestAccessSettings(
        max_active_guests=1000, joins_per_minute=600, max_open_long_polls=max_open
    )
    await jukebox.update_settings(active_settings(guest_access=access), "test")
    service = GuestService(jukebox)
    service.join_limiter = TokenBucket(capacity=guests, rate=10)  # a party arriving at once
    sessions = []
    for n in range(guests):
        status, body = await call(service, action="join", nickname=f"Guest {n}")
        assert status == 200, body
        sessions.append(body["session"])
    # The joins happened "earlier": start with a full global budget (defaults).
    service.global_limiter = TokenBucket(capacity=200, rate=100)
    return service, sessions


async def open_polls(
    service: GuestService, sessions: list[str], version: int
) -> list[asyncio.Task[Any]]:
    tasks = [
        asyncio.create_task(call(service, action="wait", session=s, since=version, timeout=30))
        for s in sessions
    ]
    for _ in range(100):
        await asyncio.sleep(0.01)
        if len(service.open_polls) >= min(
            len(sessions), service.jb.settings.guest_access.max_open_long_polls
        ):
            break
    return tasks


async def test_one_change_wakes_every_guest(jukebox: Jukebox) -> None:
    service, sessions = await crowd(jukebox, max_open=150)
    version = jukebox.notifier.version
    tasks = await open_polls(service, sessions, version)
    assert len(service.open_polls) == GUESTS

    started = time.perf_counter()
    status, body = await call(service, action="search", session=sessions[0], q="comet")
    assert status == 200
    status, body = await call(
        service, action="suggest", session=sessions[0], result=body["results"][0]["id"]
    )
    assert status == 200, body
    results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)
    elapsed = time.perf_counter() - started

    assert all(status == 200 and body["changed"] for status, body in results)
    assert not service.open_polls
    assert elapsed < 2, f"waking {GUESTS} guests took {elapsed:.2f} s"
    # Every guest sees the new request in its own view.
    assert all(body["state"]["queue"] or body["state"]["now_playing"] for _, body in results)


async def test_cap_sends_the_rest_to_polling(jukebox: Jukebox) -> None:
    service, sessions = await crowd(jukebox, max_open=60)
    version = jukebox.notifier.version
    tasks = await open_polls(service, sessions, version)
    done, pending = await asyncio.wait(tasks, timeout=0.5)
    # 40 guests got an immediate "use polling" answer, 60 are held open.
    assert len(done) == GUESTS - 60
    assert all(t.result()[1]["mode"] == "poll" for t in done)
    assert len(pending) == 60 == len(service.open_polls)

    service.reset()  # like a rotation: end everything that is still open
    results = await asyncio.wait_for(asyncio.gather(*pending), timeout=5)
    assert all(status == 200 for status, _ in results)
    assert not service.open_polls


async def test_burst_of_actions_stays_fast(jukebox: Jukebox) -> None:
    """Every guest searches, suggests and votes at the same moment (engine throughput).

    The global limiter is lifted here; `test_default_limits_absorb_a_wake_up_storm`
    covers the default limits.
    """
    service, sessions = await crowd(jukebox, max_open=150)
    service.global_limiter = TokenBucket(capacity=1e6, rate=1e6)
    status, body = await call(service, action="search", session=sessions[0], q="co")
    hits = body["results"]
    assert status == 200 and hits

    async def guest(n: int, session: str) -> list[int]:
        statuses = []
        s, b = await call(service, action="search", session=session, q="on")
        statuses.append(s)
        if s == 200 and b["results"]:
            s, _ = await call(
                service,
                action="suggest",
                session=session,
                result=b["results"][n % len(b["results"])]["id"],
            )
            statuses.append(s)
        s, b = await call(service, action="state", session=session)
        statuses.append(s)
        for item in b["state"]["queue"][:2]:
            s, _ = await call(service, action="vote", session=session, item=item["id"])
            statuses.append(s)
        return statuses

    started = time.perf_counter()
    results = await asyncio.wait_for(
        asyncio.gather(*(guest(n, s) for n, s in enumerate(sessions))), timeout=20
    )
    elapsed = time.perf_counter() - started
    flat = [s for statuses in results for s in statuses]
    # Rule violations (409, e.g. already voted / budgets) and rate limits (429) are fine,
    # server errors are not.
    assert all(s in (200, 409, 429) for s in flat), sorted(set(flat))
    assert flat.count(200) > GUESTS
    assert elapsed < 10, f"{len(flat)} actions took {elapsed:.2f} s"
    state = jukebox.guest_view(next(iter(jukebox.guests.values())))
    assert len(json.dumps(state)) < 10 * 1024  # plan 4.4: compact state


async def test_default_limits_absorb_a_wake_up_storm(jukebox: Jukebox) -> None:
    """After a change all guests return from `wait` at once and immediately wait again."""
    service, sessions = await crowd(jukebox, max_open=150)
    for _ in range(2):
        version = jukebox.notifier.version
        tasks = await open_polls(service, sessions, version)
        jukebox.notifier.bump()
        results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)
        assert all(status == 200 and body["changed"] for status, body in results)
