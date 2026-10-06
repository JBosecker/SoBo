"""Guest API: actions, sessions, limits, long polling (plan 6, 9)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from sobo.api.guest_service import MAX_BODY_BYTES, GuestService
from sobo.engine.jukebox import Jukebox
from sobo.engine.settings import GuestAccessSettings
from sobo.security.ratelimit import KeyedRateLimiter, TokenBucket
from sobo.security.sessions import clean_nickname, hash_token

from .conftest import active_settings

pytestmark = pytest.mark.anyio


@pytest.fixture
def service(jukebox: Jukebox) -> GuestService:
    return GuestService(jukebox)


async def call(service: GuestService, **payload: Any) -> tuple[int, dict[str, Any]]:
    return await service.handle(json.dumps(payload).encode())


async def joined(service: GuestService, nickname: str = "Mia") -> str:
    status, body = await call(service, action="join", nickname=nickname)
    assert status == 200, body
    return str(body["session"])


async def test_join_and_state(service: GuestService) -> None:
    session = await joined(service)
    status, body = await call(service, action="state", session=session)
    assert status == 200
    assert body["state"]["me"]["nickname"] == "Mia"
    assert body["state"]["active"] is True


async def test_token_is_stored_hashed_only(service: GuestService, jukebox: Jukebox) -> None:
    session = await joined(service)
    guest = next(iter(jukebox.guests.values()))
    assert guest.token_hash == hash_token(session)
    assert session not in json.dumps([g.token_hash for g in jukebox.guests.values()])


async def test_search_suggest_vote_flow(service: GuestService) -> None:
    mia = await joined(service, "Mia")
    tom = await joined(service, "Tom")
    status, body = await call(service, action="search", session=mia, q="comet")
    assert status == 200
    result = body["results"][0]
    assert set(result) >= {"id", "title", "artist"}
    assert "uri" not in json.dumps(body)
    status, body = await call(service, action="suggest", session=mia, result=result["id"])
    assert status == 200
    item = body["state"]["queue"][0]
    assert item["mine"] is True and item["votes"] == 1
    status, body = await call(service, action="vote", session=tom, item=item["id"])
    assert status == 200
    assert body["state"]["queue"][0]["votes"] == 2
    status, body = await call(service, action="vote", session=tom, item=item["id"])
    assert (status, body["error"]) == (409, "already_voted")


async def test_search_marks_queued_tracks(service: GuestService) -> None:
    session = await joined(service)
    _, body = await call(service, action="search", session=session, q="comet")
    _, state = await call(
        service, action="suggest", session=session, result=body["results"][0]["id"]
    )
    _, body = await call(service, action="search", session=session, q="comet")
    assert body["results"][0]["queued"] == state["state"]["queue"][0]["id"]


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"not json",
        b"[]",
        b'{"action":"delete_everything"}',
        b'{"action":"state"}',
        b'{"action":"join","nickname":"x","extra":1}',
        b'{"action":"wait","session":"' + b"a" * 30 + b'","since":"5"}',
        b'{"action":"search","session":"' + b"a" * 30 + b'","q":"x"}',
        b'{"action":"suggest","session":"' + b"a" * 30 + b'","result":"x","uri":"x-file:..."}',
    ],
)
async def test_bad_requests(service: GuestService, payload: bytes) -> None:
    status, body = await service.handle(payload)
    assert (status, body["error"]) == (400, "bad_request")


async def test_body_size_limit(service: GuestService) -> None:
    status, body = await service.handle(b"{" + b" " * MAX_BODY_BYTES + b"}")
    assert (status, body["error"]) == (413, "too_large")


async def test_invalid_session(service: GuestService) -> None:
    status, body = await call(service, action="state", session="x" * 40)
    assert (status, body["error"]) == (401, "invalid_session")


async def test_switching_off_ends_sessions(service: GuestService, jukebox: Jukebox) -> None:
    session = await joined(service)
    await jukebox.tick()
    await jukebox.set_active(False, "admin")
    await jukebox.tick()
    # While off, the old session reports "off" instead of asking to join again …
    status, body = await call(service, action="state", session=session)
    assert (status, body["error"]) == (503, "inactive")
    # … and once the next party starts, the guest joins again.
    await jukebox.set_active(True, "admin")
    status, body = await call(service, action="state", session=session)
    assert (status, body["error"]) == (401, "invalid_session")


async def test_rotation_invalidates_sessions(service: GuestService, jukebox: Jukebox) -> None:
    session = await joined(service)
    await jukebox.rotate_sessions("admin")
    status, _ = await call(service, action="state", session=session)
    assert status == 401


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Mia  ", "Mia"),
        ("Jo‮hannes", "Johannes"),  # bidi override removed
        ("a\nb\tc", "abc"),
        ("x" * 40, "x" * 24),
        ("   ", None),
        ("!!!", None),
        ("<script>", "<script>"),  # only ever rendered via textContent
        ("Zoë 🎉", "Zoë 🎉"),
    ],
)
def test_clean_nickname(raw: str, expected: str | None) -> None:
    assert clean_nickname(raw) == expected


async def test_bad_nickname(service: GuestService) -> None:
    status, body = await call(service, action="join", nickname="​​")
    assert (status, body["error"]) == (400, "bad_nickname")


async def test_presence_code(service: GuestService, jukebox: Jukebox) -> None:
    await jukebox.update_settings(
        active_settings(guest_access=GuestAccessSettings(presence_code="1234")), "admin"
    )
    status, body = await call(service, action="join", nickname="Mia", code="9999")
    assert (status, body["error"]) == (403, "wrong_code")
    status, _ = await call(service, action="join", nickname="Mia", code="1234")
    assert status == 200


async def test_inactive_jukebox(service: GuestService, jukebox: Jukebox) -> None:
    await jukebox.update_settings(active_settings(active=False), "admin")
    status, body = await call(service, action="join", nickname="Mia")
    assert (status, body["error"]) == (503, "inactive")


async def test_global_join_limit(jukebox: Jukebox) -> None:
    await jukebox.update_settings(
        active_settings(guest_access=GuestAccessSettings(joins_per_minute=3)), "admin"
    )
    service = GuestService(jukebox)
    results = [await call(service, action="join", nickname=f"G{i}") for i in range(5)]
    assert [s for s, _ in results] == [200, 200, 200, 429, 429]
    assert results[3][1]["error"] == "busy"


async def test_session_rate_limit(jukebox: Jukebox) -> None:
    service = GuestService(jukebox, session_capacity=3, session_rate=0.001)
    session = await joined(service)
    statuses = [(await call(service, action="state", session=session))[0] for _ in range(4)]
    assert statuses == [200, 200, 200, 429]


async def test_search_rate_limit(service: GuestService) -> None:
    session = await joined(service)
    statuses = [
        (await call(service, action="search", session=session, q="neon"))[0] for _ in range(8)
    ]
    assert statuses.count(429) >= 1


async def test_sonos_error_maps_to_503(service: GuestService, fake: Any) -> None:
    session = await joined(service)
    fake.fail_calls.add("search_tracks")
    status, body = await call(service, action="search", session=session, q="neon")
    assert (status, body["error"]) == (503, "sonos_unavailable")


# --------------------------------------------------------------------------- Long Polling


async def test_wait_returns_immediately_when_newer(service: GuestService, jukebox: Jukebox) -> None:
    session = await joined(service)
    jukebox.notifier.bump()
    status, body = await call(service, action="wait", session=session, since=0)
    assert status == 200 and body["changed"] is True
    assert body["state"]["version"] == body["version"]


async def test_wait_wakes_on_change(service: GuestService, jukebox: Jukebox) -> None:
    session = await joined(service)
    version = jukebox.notifier.version
    task = asyncio.create_task(call(service, action="wait", session=session, since=version))
    await asyncio.sleep(0.02)
    assert not task.done()
    jukebox.notifier.bump()
    _, body = await asyncio.wait_for(task, 1)
    assert body["changed"] is True and body["version"] == version + 1


async def test_wait_timeout(service: GuestService, jukebox: Jukebox) -> None:
    session = await joined(service)
    jukebox.settings.guest_access.long_poll_timeout = 5
    jukebox.notifier.wait = _fast_wait(jukebox.notifier.wait)  # type: ignore[method-assign]
    status, body = await call(
        service, action="wait", session=session, since=jukebox.notifier.version
    )
    assert (status, body["changed"]) == (200, False)
    assert service.open_polls == {}


def _fast_wait(original: Any) -> Any:
    async def wait(since: int, timeout: float, cancel: Any = None) -> bool:
        return bool(await original(since, 0.02, cancel))

    return wait


async def test_new_wait_replaces_old(service: GuestService, jukebox: Jukebox) -> None:
    session = await joined(service)
    version = jukebox.notifier.version
    first = asyncio.create_task(call(service, action="wait", session=session, since=version))
    await asyncio.sleep(0.02)
    second = asyncio.create_task(call(service, action="wait", session=session, since=version))
    _, body = await asyncio.wait_for(first, 1)
    assert body == {"ok": True, "changed": False, "version": version, "replaced": True}
    assert len(service.open_polls) == 1
    jukebox.notifier.bump()
    _, body = await asyncio.wait_for(second, 1)
    assert body["changed"] is True
    assert service.open_polls == {}


async def test_global_long_poll_cap(jukebox: Jukebox) -> None:
    await jukebox.update_settings(
        active_settings(guest_access=GuestAccessSettings(max_open_long_polls=2)), "admin"
    )
    service = GuestService(jukebox)
    sessions = [await joined(service, f"G{i}") for i in range(3)]
    version = jukebox.notifier.version
    waits = [
        asyncio.create_task(call(service, action="wait", session=s, since=version))
        for s in sessions[:2]
    ]
    await asyncio.sleep(0.02)
    status, body = await call(service, action="wait", session=sessions[2], since=version)
    assert (status, body["mode"]) == (200, "poll")
    jukebox.notifier.bump()
    await asyncio.gather(*waits)


async def test_rule_violation_has_retry_after(service: GuestService, jukebox: Jukebox) -> None:
    from sobo.engine.settings import VoteSettings

    await jukebox.update_settings(
        active_settings(votes=VoteSettings(votes_per_window=1, window_minutes=10)), "admin"
    )
    session = await joined(service)
    _, body = await call(service, action="search", session=session, q="disco atlas")
    first, second = body["results"][0]["id"], body["results"][1]["id"]
    await call(service, action="suggest", session=session, result=first)
    status, body = await call(service, action="suggest", session=session, result=second)
    assert status == 409
    assert body["error"] == "no_votes_left"
    assert body["retry_after"] == 600


def test_token_bucket() -> None:
    now = [0.0]
    bucket = TokenBucket(2, 1, clock=lambda: now[0])
    assert bucket.allow() and bucket.allow() and not bucket.allow()
    assert bucket.retry_after() == pytest.approx(1)
    now[0] = 1.0
    assert bucket.allow()


def test_keyed_limiter_lru() -> None:
    limiter = KeyedRateLimiter(1, 0.0001, max_keys=2, clock=lambda: 0.0)
    assert limiter.allow("a") and not limiter.allow("a")
    assert limiter.allow("b") and limiter.allow("c")
    assert limiter.allow("a")  # "a" was evicted → new bucket


async def test_wait_respects_shorter_client_timeout(
    service: GuestService, jukebox: Jukebox
) -> None:
    session = await joined(service)
    seen: list[float] = []
    original = jukebox.notifier.wait

    async def spy(since: int, timeout: float, cancel: Any = None) -> bool:
        seen.append(timeout)
        return bool(await original(since, 0.01, cancel))

    jukebox.notifier.wait = spy  # type: ignore[method-assign]
    version = jukebox.notifier.version
    await call(service, action="wait", session=session, since=version, timeout=10)
    await call(service, action="wait", session=session, since=version, timeout=60)
    await call(service, action="wait", session=session, since=version)
    assert seen == [10, 20, 20]
    status, _ = await call(service, action="wait", session=session, since=version, timeout=2)
    assert status == 400
