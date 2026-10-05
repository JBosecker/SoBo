"""Jukebox-Engine: Gast-Aktionen, Admin-Aktionen und Wiedergabesteuerung (Plan 5).

Prinzip „SoBo führt, Sonos spielt“: Die Sonos-Queue enthält nur
[aktuell, nächster]. Sobald ein Titel startet, wird der dann beste Titel als
nächster eingereiht und ist ab dann fixiert. `tick()` wird vom Scheduler
regelmäßig (und nach Gast-Aktionen sofort) aufgerufen.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..clock import Clock
from ..sonos.adapter import (
    PlaybackStatus,
    SonosAdapter,
    SonosError,
    SpeakerConfig,
    Track,
    TrackUnavailable,
    TransportState,
)
from ..sonos.worker import SonosWorker
from .fallback import FallbackPlaylist
from .limits import RuleViolation, check_track, sliding_budget
from .models import AuditEntry, Guest, ItemState, Origin, QueueItem, Vote, new_id
from .persistence import Repository
from .queue import JukeboxQueue
from .search_cache import SearchCache
from .settings import JukeboxSettings
from .state import ChangeNotifier, JukeboxState

_LOG = logging.getLogger(__name__)

SEARCH_RESULTS = 20
GUEST_QUEUE_LIMIT = 30
MAX_ENQUEUE_ATTEMPTS = 3
# Ein STOPPED kurz nach dem Start ist ein Übergang, kein Titelende.
MIN_PLAY_SECONDS = 5
FALLBACK_RETRY = timedelta(seconds=60)


def _play_now(track: Track) -> Callable[[SonosAdapter], None]:
    return lambda adapter: adapter.play_now(track)


def _set_next(track: Track) -> Callable[[SonosAdapter], None]:
    return lambda adapter: adapter.set_next(track)


@dataclass(frozen=True, slots=True)
class SearchHit:
    opaque_id: str
    track: Track
    queued_item_id: str | None  # bereits in der Queue → Vorschlag zählt als Vote
    blocked: str | None  # Regelverstoß, der einen Vorschlag verhindern würde


class Jukebox:
    def __init__(
        self,
        worker: SonosWorker,
        repo: Repository,
        clock: Clock,
        notifier: ChangeNotifier | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.worker = worker
        self.adapter = worker.adapter
        self.repo = repo
        self.clock = clock
        self.notifier = notifier or ChangeNotifier()
        self._rng = rng or random.Random()
        self._lock = asyncio.Lock()
        self.wakeup = asyncio.Event()

        snapshot = repo.load()
        self.settings = snapshot.settings or JukeboxSettings()
        self.guests: dict[str, Guest] = {g.id: g for g in snapshot.guests}
        self._guest_by_token = {g.token_hash: g.id for g in snapshot.guests}
        self.queue = JukeboxQueue(self.adapter.track_key)
        self._votes: dict[str, list[Vote]] = {}
        for item in snapshot.items:
            if item.origin == Origin.FALLBACK and item.state in (ItemState.QUEUED, ItemState.NEXT):
                item.state = ItemState.REMOVED
                item.removed_reason = "restart"
                repo.save_item(item)
            elif item.state == ItemState.NEXT:
                # Nach einem Neustart wird der nächste Titel neu bestimmt.
                item.state = ItemState.QUEUED
                repo.save_item(item)
            self.queue.add(item)
        for vote in snapshot.votes:
            self._votes.setdefault(vote.guest_id, []).append(vote)
            voted = self.queue.get(vote.item_id)
            if voted is not None:
                voted.voters.add(vote.guest_id)

        self.state = JukeboxState.INACTIVE
        self.frozen = False
        self.last_status: PlaybackStatus | None = None
        self.last_error: str | None = None
        self.override_info: str | None = None
        self.fallback_error: str | None = None
        self.search_cache = SearchCache(clock)
        self._fallback: FallbackPlaylist | None = None
        self._fallback_source: str | None = None
        self._fallback_retry_at: datetime | None = None
        self._configured: SpeakerConfig | None = None
        self._next_dirty = False
        self._was_active = False

    # ------------------------------------------------------------------ Hilfen

    def _now(self) -> datetime:
        return self.clock.now()

    def _changed(self) -> None:
        self.notifier.bump()

    def _kick(self) -> None:
        self.wakeup.set()

    def _audit(self, actor: str, action: str, detail: str = "") -> None:
        self.repo.add_audit(AuditEntry(self._now(), actor, action, detail))

    def record(self, actor: str, action: str, detail: str = "") -> None:
        """Audit-Eintrag von außerhalb der Engine (API, Integration)."""
        self._audit(actor, action, detail)

    def _set_state(self, state: JukeboxState) -> None:
        if state != self.state:
            _LOG.info("Zustand %s → %s", self.state, state)
            self.state = state
            self._changed()

    def _save(self, item: QueueItem) -> None:
        self.repo.save_item(item)

    @property
    def effectively_active(self) -> bool:
        if not self.settings.active:
            return False
        try:
            zone = ZoneInfo(self.settings.timezone)
        except ZoneInfoNotFoundError:
            zone = ZoneInfo("UTC")
        local = self._now().astimezone(zone).time()
        return self.settings.schedule.contains(local)

    def key(self, item: QueueItem) -> str:
        return self.queue.key(item)

    # ------------------------------------------------------------------ Gäste

    def guest_for_token(self, token_hash: str) -> Guest | None:
        guest_id = self._guest_by_token.get(token_hash)
        guest = self.guests.get(guest_id) if guest_id else None
        if guest is None:
            return None
        lifetime = timedelta(hours=self.settings.guest_access.session_hours)
        if guest.created_at + lifetime <= self._now():
            return None
        return guest

    def touch(self, guest: Guest) -> None:
        now = self._now()
        # Nicht bei jeder Anfrage schreiben – minütlich genügt für „aktive Gäste“.
        if (now - guest.last_seen).total_seconds() >= 60:
            guest.last_seen = now
            self.repo.save_guest(guest)

    def active_guest_count(self) -> int:
        cutoff = self._now() - timedelta(minutes=30)
        return sum(1 for g in self.guests.values() if g.last_seen > cutoff and not g.blocked)

    def join(self, nickname: str, token_hash: str, code: str | None) -> Guest:
        access = self.settings.guest_access
        if not self.effectively_active:
            raise RuleViolation("inactive")
        if access.presence_code and code != access.presence_code:
            raise RuleViolation("wrong_code")
        if self.active_guest_count() >= access.max_active_guests:
            raise RuleViolation("too_many_guests")
        now = self._now()
        guest = Guest(new_id(), token_hash, nickname, now, now)
        self.guests[guest.id] = guest
        self._guest_by_token[token_hash] = guest.id
        self.repo.save_guest(guest)
        return guest

    def _require_guest_can_act(self, guest: Guest) -> None:
        if guest.blocked:
            raise RuleViolation("blocked")
        if not self.effectively_active:
            raise RuleViolation("inactive")
        if self.frozen:
            raise RuleViolation("frozen")

    def vote_budget(self, guest_id: str) -> tuple[int, float | None]:
        cfg = self.settings.votes
        events = [v.created_at for v in self._votes.get(guest_id, []) if v.counts]
        state = sliding_budget(
            events, cfg.votes_per_window, timedelta(minutes=cfg.window_minutes), self._now()
        )
        return state.remaining, state.next_free_in

    def suggestion_budget(self, guest_id: str) -> tuple[int, float | None]:
        cfg = self.settings.limits
        events = [
            i.submitted_at
            for i in self.queue
            if i.submitted_by == guest_id and i.origin == Origin.GUEST
        ]
        state = sliding_budget(
            events,
            cfg.suggestions_per_window,
            timedelta(minutes=cfg.suggestion_window_minutes),
            self._now(),
        )
        return state.remaining, state.next_free_in

    def _rule_check(self, track: Track) -> str | None:
        try:
            check_track(
                track,
                self.adapter.track_key(track),
                self.settings.limits,
                self.queue.history(),
                self._now(),
            )
        except RuleViolation as violation:
            return violation.code
        return None

    async def search(self, guest: Guest, term: str) -> list[SearchHit]:
        if guest.blocked:
            raise RuleViolation("blocked")
        if not self.effectively_active:
            raise RuleViolation("inactive")
        account_id = self.settings.account_id
        if not account_id:
            raise RuleViolation("not_configured")
        tracks = await self.worker.call(lambda a: a.search_tracks(account_id, term, SEARCH_RESULTS))
        hits = []
        for track in tracks:
            existing = self.queue.open_by_key(self.adapter.track_key(track))
            hits.append(
                SearchHit(
                    opaque_id=self.search_cache.put(track),
                    track=track,
                    queued_item_id=existing.id if existing else None,
                    blocked=None if existing else self._rule_check(track),
                )
            )
        return hits

    async def suggest(self, guest: Guest, opaque_id: str) -> QueueItem:
        async with self._lock:
            self._require_guest_can_act(guest)
            track = self.search_cache.get(opaque_id)
            if track is None:
                raise RuleViolation("unknown_result")
            existing = self.queue.open_by_key(self.adapter.track_key(track))
            if existing is not None:
                if existing.state == ItemState.QUEUED:
                    self._add_vote(guest, existing)
                    return existing
                raise RuleViolation(
                    "already_next" if existing.state == ItemState.NEXT else "now_playing"
                )

            check_track(
                track,
                self.adapter.track_key(track),
                self.settings.limits,
                self.queue.history(),
                self._now(),
            )
            remaining, retry = self.suggestion_budget(guest.id)
            if remaining <= 0:
                raise RuleViolation("no_suggestions_left", retry_after=retry)
            costs = self.settings.votes.suggestion_costs_vote
            if costs:
                votes_left, vote_retry = self.vote_budget(guest.id)
                if votes_left <= 0:
                    raise RuleViolation("no_votes_left", retry_after=vote_retry)

            now = self._now()
            item = QueueItem(new_id(), track, Origin.GUEST, now, submitted_by=guest.id)
            item.voters.add(guest.id)
            self.queue.add(item)
            self._save(item)
            vote = Vote(guest.id, item.id, now, counts=costs)
            self._votes.setdefault(guest.id, []).append(vote)
            self.repo.save_vote(vote)
            self._changed()
            self._kick()
            return item

    async def vote(self, guest: Guest, item_id: str) -> QueueItem:
        async with self._lock:
            self._require_guest_can_act(guest)
            item = self.queue.get(item_id)
            if item is None or not item.is_open:
                raise RuleViolation("unknown_item")
            if item.state != ItemState.QUEUED:
                raise RuleViolation("locked")
            self._add_vote(guest, item)
            return item

    def _add_vote(self, guest: Guest, item: QueueItem) -> None:
        if guest.id in item.voters:
            raise RuleViolation("already_voted")
        remaining, retry = self.vote_budget(guest.id)
        if remaining <= 0:
            raise RuleViolation("no_votes_left", retry_after=retry)
        vote = Vote(guest.id, item.id, self._now(), counts=True)
        item.voters.add(guest.id)
        self._votes.setdefault(guest.id, []).append(vote)
        self.repo.save_vote(vote)
        self._changed()
        self._kick()

    # ------------------------------------------------------------------ Admin

    async def update_settings(self, new: JukeboxSettings, actor: str) -> None:
        async with self._lock:
            old = self.settings
            self.settings = new
            self.repo.save_settings(new)
            if new.fallback != old.fallback:
                self._fallback = None
                self._fallback_source = None
                self._fallback_retry_at = None
                self._next_dirty = True
            if new.speaker.coordinator_uid != old.speaker.coordinator_uid or (
                new.speaker.members != old.speaker.members
            ):
                self._configured = None
            if new.account_id != old.account_id:
                self.search_cache.clear()
            self._audit(actor, "settings")
            self._changed()
            self._kick()

    async def set_active(self, active: bool, actor: str) -> None:
        new = self.settings.model_copy(update={"active": active})
        await self.update_settings(new, actor)
        self._audit(actor, "jukebox_on" if active else "jukebox_off")

    async def set_frozen(self, frozen: bool, actor: str) -> None:
        async with self._lock:
            self.frozen = frozen
            self._audit(actor, "freeze" if frozen else "unfreeze")
            self._changed()

    async def remove_item(self, item_id: str, actor: str) -> None:
        async with self._lock:
            item = self.queue.get(item_id)
            if item is None or item.state not in (ItemState.QUEUED, ItemState.NEXT):
                raise RuleViolation("unknown_item")
            if item.state == ItemState.NEXT:
                self._next_dirty = True
            item.state = ItemState.REMOVED
            item.removed_reason = "admin"
            item.finished_at = self._now()
            self._save(item)
            self._audit(actor, "remove", f"{item.track.artist} – {item.track.title}")
            self._changed()
            self._kick()

    async def pin_item(self, item_id: str, pinned: bool, actor: str) -> None:
        async with self._lock:
            item = self.queue.get(item_id)
            if item is None or item.state != ItemState.QUEUED:
                raise RuleViolation("unknown_item")
            item.pinned = pinned
            self._save(item)
            self._audit(actor, "pin" if pinned else "unpin", item.track.title)
            self._changed()

    async def block_guest(self, guest_id: str, blocked: bool, actor: str) -> None:
        async with self._lock:
            guest = self.guests.get(guest_id)
            if guest is None:
                raise RuleViolation("unknown_guest")
            guest.blocked = blocked
            self.repo.save_guest(guest)
            self._audit(actor, "block" if blocked else "unblock", guest.nickname)
            self._changed()

    async def skip(self, actor: str) -> None:
        await self.worker.call(lambda a: a.skip())
        self._audit(actor, "skip")
        self._kick()

    async def resume_control(self, actor: str) -> None:
        """Nach `manual_override` übernimmt SoBo wieder und startet den besten Titel."""
        async with self._lock:
            current = self.queue.playing
            if current is not None:
                self._finish(current, ItemState.PLAYED)
            nxt = self.queue.next_item
            if nxt is not None:
                self._unset_next(nxt)
            self.override_info = None
            self.state = JukeboxState.IDLE
            self._audit(actor, "resume_control")
            self._changed()
            self._kick()

    async def rotate_sessions(self, actor: str) -> None:
        async with self._lock:
            self.guests.clear()
            self._guest_by_token.clear()
            self.repo.delete_all_guests()
            self.search_cache.clear()
            self._audit(actor, "rotate_guest_access")
            self._changed()

    # ------------------------------------------------------------------ Wiedergabe

    def _finish(self, item: QueueItem, state: ItemState) -> None:
        item.state = state
        item.finished_at = self._now()
        self._save(item)

    def _unset_next(self, item: QueueItem) -> None:
        if item.origin == Origin.FALLBACK:
            item.state = ItemState.REMOVED
            item.removed_reason = "preempted"
        else:
            item.state = ItemState.QUEUED
        self._save(item)

    def _mark_playing(self, item: QueueItem) -> None:
        item.state = ItemState.PLAYING
        item.started_at = self._now()
        self._save(item)

    async def _ensure_fallback(self) -> None:
        source = self.settings.fallback.source_id
        if not source:
            self._fallback = None
            self._fallback_source = None
            return
        if self._fallback is not None and self._fallback_source == source:
            return
        if self._fallback_retry_at is not None and self._now() < self._fallback_retry_at:
            return
        try:
            tracks = await self.worker.call(lambda a: a.fallback_tracks(source), timeout=30)
        except SonosError as err:
            _LOG.warning("Basis-Playlist %s nicht ladbar: %s", source, err)
            self.fallback_error = str(err)
            self._fallback_retry_at = self._now() + FALLBACK_RETRY
            return
        self.fallback_error = None
        self._fallback_retry_at = None
        self._fallback = FallbackPlaylist(
            tracks, self.settings.fallback.shuffle, self.adapter.track_key, self._rng
        )
        self._fallback_source = source

    def _candidate(self, exclude: set[str]) -> QueueItem | None:
        """Bester wartender Gasttitel, sonst ein neuer Titel aus der Basis-Playlist."""
        for item in self.queue.waiting():
            if self.key(item) not in exclude:
                return item
        if self._fallback is not None:
            track = self._fallback.next_track(exclude)
            if track is not None:
                item = QueueItem(new_id(), track, Origin.FALLBACK, self._now())
                self.queue.add(item)
                self._save(item)
                return item
        return None

    def _reject(self, item: QueueItem, reason: str) -> None:
        _LOG.warning("Titel %s nicht abspielbar: %s", item.track.item_id, reason)
        item.state = ItemState.REMOVED
        item.removed_reason = "unavailable"
        item.finished_at = self._now()
        self._save(item)
        self._changed()

    async def _start_playback(self) -> bool:
        exclude: set[str] = set()
        for _ in range(MAX_ENQUEUE_ATTEMPTS):
            item = self._candidate(exclude)
            if item is None:
                return False
            try:
                await self.worker.call(_play_now(item.track))
            except TrackUnavailable as err:
                self._reject(item, str(err))
                exclude.add(self.key(item))
                continue
            self._mark_playing(item)
            self._changed()
            await self._fill_next()
            return True
        return False

    async def _fill_next(self) -> None:
        """Sorgt dafür, dass hinter dem aktuellen Titel genau der richtige nächste steht."""
        current = self.queue.playing
        if current is None:
            return
        nxt = self.queue.next_item
        # Fixiert – außer ein Fallback-Titel wartet, während Gasttitel da sind.
        if (
            nxt is not None
            and not self._next_dirty
            and (nxt.origin != Origin.FALLBACK or not self.queue.waiting())
        ):
            return
        had_next = nxt is not None or self._next_dirty
        if nxt is not None:
            self._unset_next(nxt)
        self._next_dirty = False

        exclude = {self.key(current)}
        for _ in range(MAX_ENQUEUE_ATTEMPTS):
            candidate = self._candidate(exclude)
            if candidate is None:
                if had_next:
                    await self.worker.call(lambda a: a.clear_next())
                    self._changed()
                return
            try:
                await self.worker.call(_set_next(candidate.track))
            except TrackUnavailable as err:
                self._reject(candidate, str(err))
                exclude.add(self.key(candidate))
                continue
            candidate.state = ItemState.NEXT
            self._save(candidate)
            self._changed()
            return

    async def _apply_speaker_config(self) -> bool:
        speaker = self.settings.speaker
        if not speaker.coordinator_uid:
            return False
        config = SpeakerConfig(speaker.coordinator_uid, tuple(speaker.members))
        if self._configured != config:
            await self.worker.call(lambda a: a.configure(config), timeout=30)
            self._configured = config
        return True

    async def ensure_speaker(self) -> None:
        """Lautsprecher konfigurieren (z. B. bevor die Admin-UI Konten abfragt).

        Sonst geschieht das erst beim ersten Tick einer eingeschalteten Jukebox.
        """
        async with self._lock:
            if not await self._apply_speaker_config():
                raise RuleViolation("no_speaker")

    async def _deactivate(self) -> None:
        nxt = self.queue.next_item
        if nxt is not None:
            self._unset_next(nxt)
            try:
                await self.worker.call(lambda a: a.clear_next())
            except SonosError as err:
                _LOG.warning("Konnte nächsten Titel nicht entfernen: %s", err)
        self._set_state(JukeboxState.INACTIVE)

    async def tick(self) -> None:
        """Ein Schritt der Wiedergabesteuerung. Fehler landen in `last_error`."""
        async with self._lock:
            try:
                await self._tick()
            except SonosError as err:
                _LOG.warning("Sonos-Fehler: %s", err)
                self.last_error = str(err)
                self._set_state(JukeboxState.ERROR)
            self.queue.prune()

    async def _tick(self) -> None:
        if not self.effectively_active:
            if self._was_active:
                self._was_active = False
                await self._deactivate()
            self._set_state(JukeboxState.INACTIVE)
            return

        if not await self._apply_speaker_config():
            self.last_error = "no_speaker"
            self._set_state(JukeboxState.ERROR)
            return

        first_activation = not self._was_active
        self._was_active = True
        if first_activation and self.settings.speaker.start_volume is not None:
            volume = min(self.settings.speaker.start_volume, self.settings.speaker.max_volume)
            await self.worker.call(lambda a: a.set_volume(volume))

        await self._ensure_fallback()
        status = await self.worker.call(lambda a: a.get_status())
        previous_status, self.last_status = self.last_status, status
        self.last_error = None

        max_volume = self.settings.speaker.max_volume
        if status.volume is not None and status.volume > max_volume:
            await self.worker.call(lambda a: a.set_volume(max_volume))

        if self.state == JukeboxState.MANUAL_OVERRIDE:
            if previous_status is None or previous_status.current_key != status.current_key:
                self.override_info = f"{status.artist} – {status.title}".strip(" –")
                self._changed()
            return

        current = self.queue.playing
        nxt = self.queue.next_item
        key = status.current_key

        if current is None:
            if await self._start_playback():
                self._set_state(self._playing_state())
            else:
                self._set_state(JukeboxState.IDLE)
            return

        settled = (
            current.started_at is None
            or (self._now() - current.started_at).total_seconds() >= MIN_PLAY_SECONDS
        )

        if key is not None and key == self.key(current):
            if status.transport == TransportState.STOPPED and nxt is None and settled:
                # Queue ist ausgelaufen: der letzte Titel ist zu Ende.
                self._finish(current, ItemState.PLAYED)
                if await self._start_playback():
                    self._set_state(self._playing_state())
                else:
                    self._set_state(JukeboxState.IDLE)
                return
            if status.transport in (TransportState.PAUSED, TransportState.STOPPED):
                self._set_state(JukeboxState.PAUSED)
            else:
                self._set_state(self._playing_state())
            await self._fill_next()
            return

        if nxt is not None and key is not None and key == self.key(nxt):
            # Regulärer Übergang zum fixierten nächsten Titel.
            self._finish(current, ItemState.PLAYED)
            self._mark_playing(nxt)
            self._changed()
            await self._fill_next()
            self._set_state(self._playing_state())
            return

        if key is None:
            if status.transport == TransportState.STOPPED and settled:
                # Sonos-Queue wurde geleert, z. B. durch Auslaufen ohne nächsten Titel.
                self._finish(current, ItemState.PLAYED)
                if nxt is not None:
                    self._unset_next(nxt)
                if await self._start_playback():
                    self._set_state(self._playing_state())
                else:
                    self._set_state(JukeboxState.IDLE)
            # Sonst: Übergang abwarten.
            return

        # Etwas anderes läuft: externer Eingriff über die Sonos-App.
        _LOG.info("Externer Eingriff erkannt (%s)", key)
        self.override_info = f"{status.artist} – {status.title}".strip(" –")
        self._audit("sonos", "manual_override", self.override_info)
        self._set_state(JukeboxState.MANUAL_OVERRIDE)

    def _playing_state(self) -> JukeboxState:
        current = self.queue.playing
        if current is not None and current.origin == Origin.FALLBACK:
            return JukeboxState.PLAYING_FALLBACK
        return JukeboxState.PLAYING_GUEST

    # ------------------------------------------------------------------ Ansichten

    def _track_view(self, track: Track, covers: bool) -> dict[str, Any]:
        view: dict[str, Any] = {"title": track.title, "artist": track.artist}
        if track.duration:
            view["duration"] = track.duration
        if covers and track.art_url.startswith("https://"):
            view["art"] = track.art_url
        return view

    def guest_view(self, guest: Guest | None) -> dict[str, Any]:
        """Kompakter Zustand für die Gast-Seite (Ziel < 10 KB)."""
        covers = self.settings.guest_access.show_covers
        view: dict[str, Any] = {
            "version": self.notifier.version,
            "active": self.effectively_active,
            "state": self.state.value,
            "frozen": self.frozen,
        }
        current = self.queue.playing
        if current is not None and self.state != JukeboxState.MANUAL_OVERRIDE:
            now_playing = self._track_view(current.track, covers)
            if self.last_status and self.last_status.position is not None:
                now_playing["position"] = round(self.last_status.position)
            view["now_playing"] = now_playing
        nxt = self.queue.next_item
        if nxt is not None:
            view["next"] = self._track_view(nxt.track, covers)
        entries = []
        for item in self.queue.waiting()[:GUEST_QUEUE_LIMIT]:
            entry = self._track_view(item.track, covers)
            entry["id"] = item.id
            entry["votes"] = item.votes
            if item.pinned:
                entry["pinned"] = True
            if guest is not None:
                if guest.id in item.voters:
                    entry["voted"] = True
                if item.submitted_by == guest.id:
                    entry["mine"] = True
            entries.append(entry)
        view["queue"] = entries
        if guest is not None:
            votes_left, vote_retry = self.vote_budget(guest.id)
            sugg_left, sugg_retry = self.suggestion_budget(guest.id)
            me: dict[str, Any] = {
                "nickname": guest.nickname,
                "votes_left": votes_left,
                "suggestions_left": sugg_left,
            }
            if vote_retry is not None:
                me["votes_refill_in"] = round(vote_retry)
            if sugg_retry is not None:
                me["suggestions_refill_in"] = round(sugg_retry)
            if guest.blocked:
                me["blocked"] = True
            view["me"] = me
        return view

    def _admin_item(self, item: QueueItem) -> dict[str, Any]:
        guest = self.guests.get(item.submitted_by) if item.submitted_by else None
        return {
            "id": item.id,
            "title": item.track.title,
            "artist": item.track.artist,
            "album": item.track.album,
            "art": item.track.art_url,
            "duration": item.track.duration,
            "explicit": item.track.explicit,
            "origin": item.origin.value,
            "state": item.state.value,
            "votes": item.votes,
            "pinned": item.pinned,
            "submitted_by": guest.nickname if guest else None,
            "submitted_by_id": item.submitted_by,
            "submitted_at": item.submitted_at.isoformat(),
        }

    def admin_view(self) -> dict[str, Any]:
        status = self.last_status
        current = self.queue.playing
        nxt = self.queue.next_item
        return {
            "version": self.notifier.version,
            "state": self.state.value,
            "active": self.settings.active,
            "effectively_active": self.effectively_active,
            "frozen": self.frozen,
            "last_error": self.last_error,
            "override_info": self.override_info,
            "fallback_loaded": self._fallback.size if self._fallback else None,
            "fallback_error": self.fallback_error,
            "playback": {
                "transport": status.transport.value,
                "position": status.position,
                "duration": status.duration,
                "volume": status.volume,
            }
            if status
            else None,
            "now_playing": self._admin_item(current) if current else None,
            "next": self._admin_item(nxt) if nxt else None,
            "queue": [self._admin_item(i) for i in self.queue.waiting()],
            "history": [self._admin_item(i) for i in self.queue.played(20)],
            "guests": {"total": len(self.guests), "active": self.active_guest_count()},
        }

    def admin_guests(self) -> list[dict[str, Any]]:
        result = []
        for guest in sorted(self.guests.values(), key=lambda g: g.created_at):
            votes_left, _ = self.vote_budget(guest.id)
            result.append(
                {
                    "id": guest.id,
                    "nickname": guest.nickname,
                    "created_at": guest.created_at.isoformat(),
                    "last_seen": guest.last_seen.isoformat(),
                    "blocked": guest.blocked,
                    "votes_left": votes_left,
                    "suggestions": sum(1 for i in self.queue if i.submitted_by == guest.id),
                }
            )
        return result
