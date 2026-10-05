"""Fuzzing of the guest actions (plan 6, 9): arbitrary bodies never crash the guest API.

Every example goes through `GuestService.handle`, exactly like a POST forwarded by the
integration. Invariants checked for every input:

* `handle` returns, it never raises;
* the status code is one of the documented ones, never 500;
* the response is a JSON object that FastAPI can serialise (UTF-8, no lone surrogates);
* error responses have the shape ``{"ok": false, "error": "<code>"}``;
* responses never leak Sonos URIs or internal identifiers.
"""

from __future__ import annotations

import asyncio
import json
import random
import string
import urllib.parse
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from sobo.api.guest_service import MAX_BODY_BYTES, GuestService  # noqa: E402
from sobo.clock import ManualClock  # noqa: E402
from sobo.engine.jukebox import Jukebox  # noqa: E402
from sobo.engine.persistence import MemoryRepository  # noqa: E402
from sobo.engine.settings import GuestAccessSettings  # noqa: E402
from sobo.security.ratelimit import KeyedRateLimiter, TokenBucket  # noqa: E402
from sobo.security.sessions import clean_nickname  # noqa: E402
from sobo.sonos.fake_adapter import FakeSonosAdapter  # noqa: E402
from sobo.sonos.worker import SonosWorker  # noqa: E402

from .conftest import active_settings  # noqa: E402

FUZZ = settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)

ALLOWED_STATUS = {200, 400, 401, 403, 404, 409, 413, 429, 503}
ACTIONS = ["join", "state", "wait", "search", "suggest", "vote"]
FIELDS = ["action", "session", "nickname", "code", "since", "timeout", "q", "result", "item"]


class Env:
    """Guest service with a simulated Sonos on its own event loop (shared by all examples)."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        clock = ManualClock()
        self.adapter = FakeSonosAdapter(clock)
        self.worker = SonosWorker(self.adapter, timeout=5)
        repo = MemoryRepository()
        repo.save_settings(
            active_settings(guest_access=GuestAccessSettings(max_active_guests=1000))
        )
        self.jukebox = Jukebox(self.worker, repo, clock, rng=random.Random(3))
        # Generous limits: the fuzzer should reach the actions, not the rate limiter.
        self.service = GuestService(
            self.jukebox, global_rate=1e9, session_capacity=1e9, session_rate=1e9
        )
        self.service.join_limiter = TokenBucket(capacity=1e9, rate=1e9)
        self.service.search_limiter = KeyedRateLimiter(capacity=1e9, rate=1e9)
        self.session = self.call({"action": "join", "nickname": "Fuzz"})[1]["session"]

    def raw(self, body: bytes) -> tuple[int, dict[str, Any]]:
        status, response = self.loop.run_until_complete(
            asyncio.wait_for(self.service.handle(body), timeout=10)
        )
        check_response(status, response)
        return status, response

    def call(self, payload: Any) -> tuple[int, dict[str, Any]]:
        return self.raw(json.dumps(payload).encode())

    def close(self) -> None:
        self.worker.shutdown()
        self.loop.close()


@contextmanager
def environment() -> Iterator[Env]:
    env = Env()
    try:
        yield env
    finally:
        env.close()


def check_response(status: int, response: dict[str, Any]) -> None:
    assert status in ALLOWED_STATUS, (status, response)
    assert isinstance(response, dict)
    # FastAPI's JSONResponse: ensure_ascii=False, then UTF-8 → must not fail.
    text = json.dumps(response, ensure_ascii=False, allow_nan=False)
    text.encode("utf-8")
    if status != 200:
        assert response.get("ok") is False
        assert isinstance(response.get("error"), str)
    for leak in ("x-sonos", "x-rincon", "RINCON_", "token_hash", "fake_playlist"):
        assert leak not in text, leak


json_values = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**70), max_value=2**70)
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=40),
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=10), children, max_size=4)
    ),
    max_leaves=12,
)

field_values = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**64), max_value=2**64),
    st.floats(),
    st.text(max_size=120),
    st.text(alphabet=string.digits, min_size=1, max_size=10),
    st.text(min_size=20, max_size=100),  # passes the session length check
    st.lists(st.text(max_size=5), max_size=3),
    st.dictionaries(st.text(max_size=5), st.integers(), max_size=2),
)


@pytest.fixture(scope="module")
def env() -> Iterator[Env]:
    with environment() as e:
        yield e


@FUZZ
@given(body=st.binary(max_size=MAX_BODY_BYTES + 64))
def test_arbitrary_bytes(env: Env, body: bytes) -> None:
    status, _ = env.raw(body)
    if len(body) > MAX_BODY_BYTES:
        assert status == 413


@FUZZ
@given(value=json_values)
def test_arbitrary_json(env: Env, value: Any) -> None:
    status, _ = env.call(value)
    assert status != 200 or (isinstance(value, dict) and value.get("action") in ACTIONS)


@FUZZ
@given(
    action=st.sampled_from(ACTIONS),
    fields=st.dictionaries(st.sampled_from(FIELDS), field_values, max_size=5),
)
def test_actions_with_random_fields(env: Env, action: str, fields: dict[str, Any]) -> None:
    fields.pop("action", None)
    if action == "wait" and isinstance(fields.get("timeout"), int):
        fields["timeout"] = 5  # keep valid long polls short
    env.call({"action": action, **fields})


@FUZZ
@given(q=st.text(max_size=100), result=st.text(max_size=80), item=st.text(max_size=80))
def test_valid_session_with_hostile_strings(env: Env, q: str, result: str, item: str) -> None:
    env.call({"action": "search", "session": env.session, "q": q})
    env.call({"action": "suggest", "session": env.session, "result": result})
    env.call({"action": "vote", "session": env.session, "item": item})
    status, body = env.call({"action": "state", "session": env.session})
    assert status == 200
    assert body["state"]["me"]["nickname"] == "Fuzz"


@FUZZ
@given(nickname=st.text(min_size=1, max_size=64))
def test_nicknames_are_cleaned(env: Env, nickname: str) -> None:
    status, body = env.call({"action": "join", "nickname": nickname})
    cleaned = clean_nickname(nickname)
    if cleaned is None:
        assert (status, body["error"]) == (400, "bad_nickname")
        return
    assert status == 200
    assert body["state"]["me"]["nickname"] == cleaned
    for char in cleaned:
        assert char.isprintable() or char == " ", repr(char)


def test_deeply_nested_json(env: Env) -> None:
    depth = MAX_BODY_BYTES // 2
    assert env.raw(b"[" * depth + b"]" * depth)[0] == 400
    assert env.raw(b'{"a":' * 600 + b"1" + b"}" * 600)[0] == 400


def test_duplicate_keys_and_type_confusion(env: Env) -> None:
    # The last "action" wins in json.loads; strict validation still applies.
    assert env.raw(b'{"action":"state","action":"join","nickname":"A"}')[0] == 200
    assert env.call({"action": "vote", "session": env.session, "item": 1})[0] == 400
    assert env.call({"action": "wait", "session": env.session, "since": "1"})[0] == 400
    assert env.call({"action": "wait", "session": env.session, "since": True})[0] == 400
    assert env.call({"action": "join", "nickname": "A", "admin": True})[0] == 400


# --------------------------------------------------------------------------- admin and internal API


class HttpEnv:
    """Admin and internal FastAPI apps on their own event loop."""

    def __init__(self, data_dir: Path) -> None:
        pytest.importorskip("fastapi")
        import httpx

        from sobo.api.admin import create_admin_app
        from sobo.api.internal import SECRET_HEADER, create_internal_app
        from sobo.config import AppOptions
        from sobo.context import AppContext

        self.loop = asyncio.new_event_loop()
        clock = ManualClock()
        repo = MemoryRepository()
        repo.save_settings(active_settings())
        self.ctx = AppContext.build(
            AppOptions(data_dir=data_dir), adapter=FakeSonosAdapter(clock), repo=repo, clock=clock
        )
        self.admin = httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_admin_app(self.ctx), client=("172.30.32.2", 50000)
            ),
            base_url="http://sobo",
            headers={"X-SoBo-Request": "1"},
        )
        self.internal = httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_internal_app(self.ctx), client=("127.0.0.1", 1)
            ),
            base_url="http://sobo",
            headers={SECRET_HEADER: self.ctx.secret},
        )

    def run(self, coro: Any) -> Any:
        return self.loop.run_until_complete(coro)

    def close(self) -> None:
        self.run(self.admin.aclose())
        self.run(self.internal.aclose())
        self.run(self.ctx.stop())
        self.loop.close()


@pytest.fixture(scope="module")
def http_env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[HttpEnv]:
    e = HttpEnv(tmp_path_factory.mktemp("fuzz-http"))
    try:
        yield e
    finally:
        e.close()


def _leaf_paths(value: Any, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    if isinstance(value, dict):
        paths = [prefix] if prefix else []
        for key, child in value.items():
            paths += _leaf_paths(child, (*prefix, key))
        return paths
    return [prefix]


@FUZZ
@given(data=st.data(), replacement=json_values)
def test_settings_mutations(http_env: HttpEnv, data: st.DataObject, replacement: Any) -> None:
    current = http_env.run(http_env.admin.get("/api/settings")).json()
    path = data.draw(st.sampled_from(_leaf_paths(current)))
    draft = json.loads(json.dumps(current))
    target = draft
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    response = http_env.run(http_env.admin.put("/api/settings", json=draft))
    assert response.status_code in {200, 422}, (path, replacement, response.text)
    after = http_env.run(http_env.admin.get("/api/settings")).json()
    if response.status_code == 422:
        assert after == current
    else:
        assert after == response.json()


@FUZZ
@given(
    endpoint=st.sampled_from(["/internal/guest-access", "/internal/rotated", "/internal/active"]),
    body=json_values,
)
def test_internal_reports(http_env: HttpEnv, endpoint: str, body: Any) -> None:
    response = http_env.run(http_env.internal.post(endpoint, json=body))
    assert response.status_code in {204, 422}, response.text
    url = http_env.ctx.guest_access.url
    assert url is None or url.startswith("https://")


@FUZZ
@given(path=st.text(max_size=40), limit=st.integers(min_value=-(2**70), max_value=2**70))
def test_admin_paths_and_queries(http_env: HttpEnv, path: str, limit: int) -> None:
    quoted = urllib.parse.quote(path, safe="")
    for method, url in (
        ("POST", f"/api/queue/{quoted}/remove"),
        ("POST", f"/api/guests/{quoted}/block"),
        ("GET", f"/api/audit?limit={limit}"),
        ("GET", f"/api/guest-access/qr.svg?which={quoted}"),
    ):
        response = http_env.run(http_env.admin.request(method, url, json={"blocked": True}))
        assert response.status_code < 500, (method, url, response.text)
