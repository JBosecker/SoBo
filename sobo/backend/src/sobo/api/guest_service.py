"""Internal guest API: processes the POST actions the integration forwards from the
cloudhook (plan 3.2, 4.4, 6).

Framework-independent: `handle(body)` receives the raw body and returns
(HTTP status, JSON object). The FastAPI route is only a thin wrapper.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from ..access import DisplayKey, GuestAccessInfo
from ..engine.jukebox import Jukebox, SearchHit
from ..engine.limits import RuleViolation
from ..engine.models import Guest
from ..qr import qr_rows
from ..security.ratelimit import KeyedRateLimiter, TokenBucket
from ..security.sessions import clean_nickname, hash_token, new_session_token
from ..sonos.adapter import SonosError

_LOG = logging.getLogger(__name__)

MAX_BODY_BYTES = 4096
Response = tuple[int, dict[str, Any]]

# ---------------------------------------------------------------- schemas (strict action list)

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
    # Epoch of `since` (see ChangeNotifier); a different one means the app restarted.
    epoch: str | None = Field(default=None, min_length=1, max_length=32)
    # The guest page shortens the wait after aborts (plan 4.4); never longer than the admin setting.
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


class DisplayAction(_Action):
    """Party display: state right away, or a long poll when `since` is given."""

    action: Literal["display"]
    key: str = Field(min_length=32, max_length=100)
    since: int | None = Field(default=None, ge=0, le=2**53)
    epoch: str | None = Field(default=None, min_length=1, max_length=32)
    timeout: int | None = Field(default=None, ge=5, le=60)


AnyAction = (
    JoinAction
    | StateAction
    | WaitAction
    | SearchAction
    | SuggestAction
    | VoteAction
    | DisplayAction
)
GuestAction = Annotated[AnyAction, Field(discriminator="action")]
_ACTION_ADAPTER: TypeAdapter[AnyAction] = TypeAdapter(GuestAction)

# Open long polls of party displays; there are only a few screens at a party.
MAX_OPEN_DISPLAY_POLLS = 10

# Rule violations → HTTP status. Everything else from RuleViolation → 409.
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
        guest_access: GuestAccessInfo | None = None,
        display_key: DisplayKey | None = None,
    ) -> None:
        self.jb = jukebox
        self.guest_access = guest_access or GuestAccessInfo()
        # Without a key (tests, harness without a display) the display stays closed.
        self.display_key = display_key
        joins = jukebox.settings.guest_access.joins_per_minute
        self.join_limiter = TokenBucket(capacity=joins, rate=joins / 60)
        self.global_limiter = TokenBucket(capacity=global_rate * 2, rate=global_rate)
        self.session_limiter = KeyedRateLimiter(session_capacity, session_rate)
        self.search_limiter = KeyedRateLimiter(capacity=6, rate=0.5)
        self.open_polls: dict[str, asyncio.Event] = {}
        # All displays share one key, so they share one bucket: a few screens at most.
        self.display_limiter = TokenBucket(capacity=30, rate=5)
        self.open_display_polls: set[asyncio.Event] = set()

    # ------------------------------------------------------------------ entry point

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
            _LOG.warning("Guest action %s: Sonos error %s", action.action, err)
            return _error(503, "sonos_unavailable")

    async def _dispatch(self, action: AnyAction) -> Response:
        if isinstance(action, JoinAction):
            return self._join(action)
        if isinstance(action, DisplayAction):
            return await self._display(action)
        guest = self.jb.guest_for_token(hash_token(action.session))
        if guest is None:
            if not self.jb.effectively_active:
                # Switching off ends all sessions: show "off" until the next party starts.
                return _error(_STATUS["inactive"], "inactive")
            return _error(401, "invalid_session")
        if not self.session_limiter.allow(guest.id):
            return _error(429, "slow_down")
        self.jb.touch(guest)
        match action:
            case StateAction():
                return 200, {"ok": True, "state": self.jb.guest_view(guest)}
            case WaitAction():
                return await self._wait(guest, action.since, action.timeout, action.epoch)
            case SearchAction():
                return await self._search(guest, action.q)
            case SuggestAction():
                await self.jb.suggest(guest, action.result)
                return 200, {"ok": True, "state": self.jb.guest_view(guest)}
            case VoteAction():
                await self.jb.vote(guest, action.item)
                return 200, {"ok": True, "state": self.jb.guest_view(guest)}
        raise AssertionError("unreachable")  # pragma: no cover

    # ------------------------------------------------------------------ actions

    def _join(self, action: JoinAction) -> Response:
        nickname = clean_nickname(action.nickname)
        if nickname is None:
            return _error(400, "bad_nickname")
        if not self.join_limiter.allow():
            return _error(429, "busy", self.join_limiter.retry_after())
        token, token_hash = new_session_token()
        guest = self.jb.join(nickname, token_hash, action.code)
        return 200, {"ok": True, "session": token, "state": self.jb.guest_view(guest)}

    async def _wait(
        self, guest: Guest, since: int, timeout: int | None = None, epoch: str | None = None
    ) -> Response:
        access = self.jb.settings.guest_access
        notifier = self.jb.notifier
        # Newer, or `since` is from before a restart of the app (other epoch, or a version
        # the counter has not reached yet): answer right away with the current state.
        if since != notifier.version or (epoch is not None and epoch != notifier.epoch):
            return 200, self._changed(guest)
        previous = self.open_polls.get(guest.id)
        if previous is not None:
            previous.set()  # at most one open `wait` per session
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

    # ------------------------------------------------------------------ party display

    async def _display(self, action: DisplayAction) -> Response:
        key = self.display_key
        if key is None or not self.jb.settings.display.enabled or not key.matches(action.key):
            # Same answer for "off" and "wrong key": no hint which one it is.
            return _error(403, "display_denied")
        if not self.display_limiter.allow():
            return _error(429, "slow_down", self.display_limiter.retry_after())
        notifier = self.jb.notifier
        if (
            action.since is None
            or action.since != notifier.version
            or (action.epoch is not None and action.epoch != notifier.epoch)
        ):
            return 200, self._display_changed()
        if len(self.open_display_polls) >= MAX_OPEN_DISPLAY_POLLS:
            return 200, {"ok": True, "changed": False, "version": notifier.version, "mode": "poll"}
        cancel = asyncio.Event()
        self.open_display_polls.add(cancel)
        try:
            limit = self.jb.settings.guest_access.long_poll_timeout
            changed = await notifier.wait(action.since, min(action.timeout or limit, limit), cancel)
        finally:
            self.open_display_polls.discard(cancel)
        if changed:
            return 200, self._display_changed()
        return 200, {"ok": True, "changed": False, "version": notifier.version}

    def _display_changed(self) -> dict[str, Any]:
        state = self.display_state()
        return {"ok": True, "changed": True, "version": state["version"], "state": state}

    def display_state(self) -> dict[str, Any]:
        """Display state plus how to join: QR code, presence code and the poster texts."""
        state = self.jb.display_view()
        settings = self.jb.settings
        url = self.guest_access.join_url
        if url and state["active"]:
            join: dict[str, Any] = {"qr": list(qr_rows(url))}
            code = settings.guest_access.presence_code
            if code and settings.display.show_code:
                join["code"] = code
            if settings.poster.title:
                join["title"] = settings.poster.title
            if settings.poster.text:
                join["text"] = settings.poster.text
            state["join"] = join
        return state

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

    def end_display_polls(self) -> None:
        for cancel in self.open_display_polls:
            cancel.set()

    def reset(self) -> None:
        """After a rotation: end open long polls, reset limits."""
        for cancel in [*self.open_polls.values(), *self.open_display_polls]:
            cancel.set()
        self.session_limiter.reset()
        self.search_limiter.reset()
