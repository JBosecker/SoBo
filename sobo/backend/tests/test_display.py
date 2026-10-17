"""Party display: `display` action, key, long polling, join info (backlog item, 0.3.0)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from sobo.access import DISPLAY_QUERY, DisplayKey, GuestAccessInfo
from sobo.api.guest_service import MAX_OPEN_DISPLAY_POLLS, GuestService
from sobo.engine.jukebox import DISPLAY_QUEUE_LIMIT, Jukebox
from sobo.engine.settings import DisplaySettings, GuestAccessSettings, PosterSettings
from sobo.qr import qr_rows

from .conftest import active_settings, make_guest, suggest_title

pytestmark = pytest.mark.anyio

GUEST_URL = "https://hooks.nabu.casa/AAAA"


@pytest.fixture
def key(tmp_path: Path) -> DisplayKey:
    return DisplayKey(tmp_path / "display_key")


@pytest.fixture
def access() -> GuestAccessInfo:
    return GuestAccessInfo(url=GUEST_URL)


@pytest.fixture
async def service(jukebox: Jukebox, key: DisplayKey, access: GuestAccessInfo) -> GuestService:
    await jukebox.update_settings(active_settings(display=DisplaySettings(enabled=True)), "test")
    return GuestService(jukebox, guest_access=access, display_key=key)


async def call(service: GuestService, **payload: Any) -> tuple[int, dict[str, Any]]:
    return await service.handle(json.dumps({"action": "display", **payload}).encode())


async def test_state_with_join_info(service: GuestService, key: DisplayKey) -> None:
    status, body = await call(service, key=key.value)
    assert status == 200 and body["changed"] is True
    state = body["state"]
    assert state["active"] is True
    assert state["join"]["qr"] == list(qr_rows(GUEST_URL))
    assert "code" not in state["join"] and "title" not in state["join"]
    # Neither the key nor guest data end up in the state.
    text = json.dumps(state)
    assert key.value not in text and GUEST_URL not in text


@pytest.mark.parametrize("given", ["x" * 43, None])
async def test_wrong_key_is_denied(
    service: GuestService, key: DisplayKey, given: str | None
) -> None:
    status, body = await call(service, key=given or key.value[::-1])
    assert (status, body["error"]) == (403, "display_denied")


async def test_disabled_display_is_denied_with_the_same_answer(
    service: GuestService, jukebox: Jukebox, key: DisplayKey
) -> None:
    await jukebox.update_settings(active_settings(), "test")
    status, body = await call(service, key=key.value)
    assert (status, body["error"]) == (403, "display_denied")


async def test_without_a_key_the_display_stays_closed(jukebox: Jukebox) -> None:
    await jukebox.update_settings(active_settings(display=DisplaySettings(enabled=True)), "t")
    service = GuestService(jukebox)
    status, body = await call(service, key="k" * 43)
    assert (status, body["error"]) == (403, "display_denied")


async def test_short_key_is_a_bad_request(service: GuestService) -> None:
    status, body = await call(service, key="short")
    assert (status, body["error"]) == (400, "bad_request")


async def test_renewed_key_replaces_the_old_one(service: GuestService, key: DisplayKey) -> None:
    old = key.value
    key.renew()
    assert key.value != old
    assert (await call(service, key=old))[0] == 403
    assert (await call(service, key=key.value))[0] == 200
    # Survives a restart of the app
    assert DisplayKey(key._path).value == key.value


async def test_works_without_guests_and_while_off(
    service: GuestService, jukebox: Jukebox, key: DisplayKey
) -> None:
    await jukebox.update_settings(
        active_settings(active=False, display=DisplaySettings(enabled=True)), "test"
    )
    status, body = await call(service, key=key.value)
    assert status == 200
    assert body["state"]["active"] is False
    assert "join" not in body["state"]  # nobody can join while the jukebox is off


async def test_presence_code_and_poster_texts(
    service: GuestService, jukebox: Jukebox, key: DisplayKey
) -> None:
    await jukebox.update_settings(
        active_settings(
            display=DisplaySettings(enabled=True),
            guest_access=GuestAccessSettings(presence_code="4711"),
            poster=PosterSettings(title="Wünsch dir was", text="Zeile 1\nZeile 2"),
        ),
        "test",
    )
    join = (await call(service, key=key.value))[1]["state"]["join"]
    assert join["code"] == "4711"
    assert (join["title"], join["text"]) == ("Wünsch dir was", "Zeile 1\nZeile 2")
    await jukebox.update_settings(
        jukebox.settings.model_copy(
            update={"display": DisplaySettings(enabled=True, show_code=False)}
        ),
        "test",
    )
    assert "code" not in (await call(service, key=key.value))[1]["state"]["join"]


async def test_local_link_when_there_is_no_cloudhook(
    service: GuestService, access: GuestAccessInfo, key: DisplayKey
) -> None:
    access.url, access.local_url = None, "http://192.168.1.20:8123/api/webhook/x"
    join = (await call(service, key=key.value))[1]["state"]["join"]
    assert join["qr"] == list(qr_rows("http://192.168.1.20:8123/api/webhook/x"))
    access.local_url = None
    assert "join" not in (await call(service, key=key.value))[1]["state"]


async def test_queue_without_guest_details(
    service: GuestService, jukebox: Jukebox, key: DisplayKey
) -> None:
    mia = make_guest(jukebox, "Mia")
    tom = make_guest(jukebox, "Tom")
    await suggest_title(jukebox, mia, "Slow Comet")
    item = await suggest_title(jukebox, tom, "Neon Harbor")
    await jukebox.vote(mia, item.id)
    state = (await call(service, key=key.value))[1]["state"]
    assert [(e["title"], e["votes"]) for e in state["queue"]] == [
        ("Neon Harbor", 2),
        ("Slow Comet", 1),
    ]
    assert state["requests"] == 2
    text = json.dumps(state)
    for private in ("Mia", "Tom", mia.id, item.id, "mine", "voted"):
        assert private not in text


async def test_queue_is_limited(jukebox: Jukebox) -> None:
    guest = make_guest(jukebox)
    titles = [h.track.title for h in await jukebox.search(guest, "a")]
    jukebox.settings = jukebox.settings.model_copy(
        update={
            "limits": jukebox.settings.limits.model_copy(update={"suggestions_per_window": 100})
        }
    )
    for _ in range(DISPLAY_QUEUE_LIMIT + 2):
        make_guest(jukebox)
    for index, title in enumerate(titles[: DISPLAY_QUEUE_LIMIT + 1]):
        g = list(jukebox.guests.values())[index]
        await suggest_title(jukebox, g, title)
    view = jukebox.display_view()
    assert len(view["queue"]) == DISPLAY_QUEUE_LIMIT
    assert view["requests"] == DISPLAY_QUEUE_LIMIT + 1


async def test_long_poll_wakes_on_change(
    service: GuestService, jukebox: Jukebox, key: DisplayKey
) -> None:
    _, first = await call(service, key=key.value)
    since, epoch = first["version"], first["state"]["epoch"]
    task = asyncio.create_task(call(service, key=key.value, since=since, epoch=epoch))
    await asyncio.sleep(0.05)
    assert not task.done()
    await suggest_title(jukebox, make_guest(jukebox), "Slow Comet")
    status, body = await asyncio.wait_for(task, 2)
    assert status == 200 and body["changed"] is True
    assert body["state"]["queue"][0]["title"] == "Slow Comet"


async def test_long_poll_answers_at_once_for_another_epoch(
    service: GuestService, key: DisplayKey
) -> None:
    _, first = await call(service, key=key.value)
    status, body = await call(service, key=key.value, since=first["version"], epoch="other")
    assert status == 200 and body["changed"] is True


async def test_ending_display_polls_answers_open_polls(
    service: GuestService, jukebox: Jukebox, key: DisplayKey
) -> None:
    _, first = await call(service, key=key.value)
    jukebox.settings = jukebox.settings.model_copy(
        update={"guest_access": GuestAccessSettings(long_poll_timeout=5)}
    )
    task = asyncio.create_task(call(service, key=key.value, since=first["version"], timeout=5))
    await asyncio.sleep(0.05)
    service.end_display_polls()  # like a renewal: the open poll answers right away
    status, body = await asyncio.wait_for(task, 2)
    assert (status, body["changed"]) == (200, False)


async def test_open_display_polls_are_capped(service: GuestService, key: DisplayKey) -> None:
    _, first = await call(service, key=key.value)
    since = first["version"]
    tasks = [
        asyncio.create_task(call(service, key=key.value, since=since))
        for _ in range(MAX_OPEN_DISPLAY_POLLS)
    ]
    await asyncio.sleep(0.05)
    status, body = await call(service, key=key.value, since=since)
    assert status == 200 and body["mode"] == "poll"
    service.reset()  # a rotation ends open display polls too
    results = await asyncio.wait_for(asyncio.gather(*tasks), 2)
    assert all(result[1]["changed"] is False for result in results)


async def test_rate_limited(service: GuestService, key: DisplayKey) -> None:
    statuses = [(await call(service, key=key.value))[0] for _ in range(40)]
    assert 429 in statuses


def test_display_url() -> None:
    key = DisplayKey.__new__(DisplayKey)
    key.value = "k" * 43
    assert key.url(GUEST_URL) == f"{GUEST_URL}?{DISPLAY_QUERY}#key={'k' * 43}"


def test_qr_rows_are_square() -> None:
    rows = qr_rows(GUEST_URL)
    assert len(rows) >= 21 and all(len(r) == len(rows) and set(r) <= {"0", "1"} for r in rows)
