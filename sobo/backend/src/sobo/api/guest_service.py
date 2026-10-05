"""Interne Gast-API: verarbeitet die POST-Aktionen, die die Integration vom
Cloudhook weiterleitet (Plan 3.2, 4.4, 6).

Framework-unabhängig: `handle(body)` bekommt den rohen Body und liefert
(HTTP-Status, JSON-Objekt). Die FastAPI-Route ist nur eine dünne Hülle.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from ..engine.jukebox import Jukebox, SearchHit
from ..engine.limits import RuleViolation
from ..engine.models import Guest
from ..security.ratelimit import KeyedRateLimiter, TokenBucket
from ..security.sessions import clean_nickname, hash_token, new_session_token
from ..sonos.adapter import SonosError

_LOG = logging.getLogger(__name__)

MAX_BODY_BYTES = 4096
Response = tuple[int, dict[str, Any]]

# ---------------------------------------------------------------- Schemas (strikte Aktionsliste)

_Session = Annotated[str, Field(min_length=20, max_length=100)]


class _Action(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class JoinAction(_Action):
    action: Literal["join"]
    nickname: str = Field(min_length=1, max_length=64)
    code: str | None = Field(default=None, max_length=8)


class StateAction(_Action):
    action: Literal["state"]
    session: _Session


class WaitAction(_Action):
    action: Literal["wait"]
    session: _Session
    since: int = Field(ge=0, le=2**53)
    # Die Gast-Seite verkürzt die Wartezeit nach Abbrüchen (Plan 4.4); nie länger als im Admin.
    timeout: int | None = Field(default=None, ge=5, le=60)


class SearchAction(_Action):
    action: Literal["search"]
    session: _Session
    q: str = Field(min_length=2, max_length=80)


class SuggestAction(_Action):
    action: Literal["suggest"]
    session: _Session
    result: str = Field(min_length=1, max_length=64)


class VoteAction(_Action):
    action: Literal["vote"]
    session: _Session
    item: str = Field(min_length=1, max_length=64)


GuestAction = Annotated[
    JoinAction | StateAction | WaitAction | SearchAction | SuggestAction | VoteAction,
    Field(discriminator="action"),
]
_ACTION_ADAPTER: TypeAdapter[
    JoinAction | StateAction | WaitAction | SearchAction | SuggestAction | VoteAction
] = TypeAdapter(GuestAction)

# Regelverstöße → HTTP-Status. Alles andere aus RuleViolation → 409.
_STATUS = {
    "inactive": 503,
    "not_configured": 503,
    "blocked": 403,
    "wrong_code": 403,
    "too_many_guests": 429,
}


def _error(status: int, code: str, retry_after: float | None = None) -> Response:
    body: dict[str, Any] = {"ok": False, "error": code}
    if retry_after is not None:
        body["retry_after"] = round(retry_after)
    return status, body


class GuestService:
    def __init__(
        self,
        jukebox: Jukebox,
        global_rate: float = 100.0,
        session_capacity: float = 20,
        session_rate: float = 2.0,
    ) -> None:
        self.jb = jukebox
        joins = jukebox.settings.guest_access.joins_per_minute
        self.join_limiter = TokenBucket(capacity=joins, rate=joins / 60)
        self.global_limiter = TokenBucket(capacity=global_rate * 2, rate=global_rate)
        self.session_limiter = KeyedRateLimiter(session_capacity, session_rate)
        self.search_limiter = KeyedRateLimiter(capacity=6, rate=0.5)
        self.open_polls: dict[str, asyncio.Event] = {}

    # ------------------------------------------------------------------ Einstieg

    async def handle(self, body: bytes) -> Response:
        if len(body) > MAX_BODY_BYTES:
            return _error(413, "too_large")
        if not self.global_limiter.allow():
            return _error(429, "busy", self.global_limiter.retry_after())
        try:
            action = _ACTION_ADAPTER.validate_python(json.loads(body))
        except (ValueError, ValidationError):
            return _error(400, "bad_request")
        try:
            return await self._dispatch(action)
        except RuleViolation as violation:
            return _error(_STATUS.get(violation.code, 409), violation.code, violation.retry_after)
        except SonosError as err:
            _LOG.warning("Gast-Aktion %s: Sonos-Fehler %s", action.action, err)
            return _error(503, "sonos_unavailable")

    async def _dispatch(
        self,
        action: JoinAction | StateAction | WaitAction | SearchAction | SuggestAction | VoteAction,
    ) -> Response:
        if isinstance(action, JoinAction):
            return self._join(action)
        guest = self.jb.guest_for_token(hash_token(action.session))
        if guest is None:
            return _error(401, "invalid_session")
        if not self.session_limiter.allow(guest.id):
            return _error(429, "slow_down")
        self.jb.touch(guest)
        match action:
            case StateAction():
                return 200, {"ok": True, "state": self.jb.guest_view(guest)}
            case WaitAction():
                return await self._wait(guest, action.since, action.timeout)
            case SearchAction():
                return await self._search(guest, action.q)
            case SuggestAction():
                await self.jb.suggest(guest, action.result)
                return 200, {"ok": True, "state": self.jb.guest_view(guest)}
            case VoteAction():
                await self.jb.vote(guest, action.item)
                return 200, {"ok": True, "state": self.jb.guest_view(guest)}
        raise AssertionError("unreachable")  # pragma: no cover

    # ------------------------------------------------------------------ Aktionen

    def _join(self, action: JoinAction) -> Response:
        nickname = clean_nickname(action.nickname)
        if nickname is None:
            return _error(400, "bad_nickname")
        if not self.join_limiter.allow():
            return _error(429, "busy", self.join_limiter.retry_after())
        token, token_hash = new_session_token()
        guest = self.jb.join(nickname, token_hash, action.code)
        return 200, {"ok": True, "session": token, "state": self.jb.guest_view(guest)}

    async def _wait(self, guest: Guest, since: int, timeout: int | None = None) -> Response:
        access = self.jb.settings.guest_access
        notifier = self.jb.notifier
        if notifier.version > since:
            return 200, self._changed(guest)
        previous = self.open_polls.get(guest.id)
        if previous is not None:
            previous.set()  # höchstens ein offenes `wait` pro Session
        elif len(self.open_polls) >= access.max_open_long_polls:
            return 200, {"ok": True, "changed": False, "version": notifier.version, "mode": "poll"}
        cancel = asyncio.Event()
        self.open_polls[guest.id] = cancel
        try:
            limit = access.long_poll_timeout
            changed = await notifier.wait(since, min(timeout or limit, limit), cancel)
        finally:
            if self.open_polls.get(guest.id) is cancel:
                del self.open_polls[guest.id]
        if changed:
            return 200, self._changed(guest)
        body: dict[str, Any] = {"ok": True, "changed": False, "version": notifier.version}
        if cancel.is_set():
            body["replaced"] = True
        return 200, body

    def _changed(self, guest: Guest) -> dict[str, Any]:
        state = self.jb.guest_view(guest)
        return {"ok": True, "changed": True, "version": state["version"], "state": state}

    async def _search(self, guest: Guest, term: str) -> Response:
        if not self.search_limiter.allow(guest.id):
            return _error(429, "slow_down")
        hits = await self.jb.search(guest, term.strip())
        covers = self.jb.settings.guest_access.show_covers
        return 200, {"ok": True, "results": [self._hit_view(h, covers) for h in hits]}

    @staticmethod
    def _hit_view(hit: SearchHit, covers: bool) -> dict[str, Any]:
        track = hit.track
        view: dict[str, Any] = {"id": hit.opaque_id, "title": track.title, "artist": track.artist}
        if track.album:
            view["album"] = track.album
        if track.duration:
            view["duration"] = track.duration
        if track.explicit:
            view["explicit"] = True
        if covers and track.art_url.startswith("https://"):
            view["art"] = track.art_url
        if hit.queued_item_id:
            view["queued"] = hit.queued_item_id
        if hit.blocked:
            view["blocked"] = hit.blocked
        return view

    def reset(self) -> None:
        """Nach einer Rotation: offene Long-Polls beenden, Limits zurücksetzen."""
        for cancel in self.open_polls.values():
            cancel.set()
        self.session_limiter.reset()
        self.search_limiter.reset()
