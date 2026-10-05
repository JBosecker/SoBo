"""In-Memory-Sonos für Tests und den Devcontainer (Plan 9, Phase 1).

Simuliert einen Koordinator mit Queue, Transport-Zustand und Wiedergabezeit.
Die Zeit kommt aus einer injizierten Uhr; mit `ManualClock` steuern Tests sie
exakt, mit `ScaledClock` läuft sie im Devcontainer beschleunigt.
"""

from __future__ import annotations

import threading
from datetime import timedelta

from ..clock import Clock, SystemClock
from .adapter import (
    FallbackSource,
    MusicAccount,
    PlaybackStatus,
    SonosError,
    SpeakerConfig,
    SpeakerInfo,
    Track,
    TrackUnavailable,
    TransportState,
    uri_key,
)
from .fixtures import FAKE_ACCOUNT_ID, fake_catalog

_DEFAULT_DURATION = 200


class FakeSonosAdapter:
    def __init__(self, clock: Clock | None = None, catalog: list[Track] | None = None) -> None:
        self._clock = clock or SystemClock()
        self.catalog = catalog if catalog is not None else fake_catalog()
        self.queue: list[Track] = []
        self.index = 0
        self.transport = TransportState.STOPPED
        self.volume = 20
        self._elapsed_before_pause = 0.0
        self._started_at = self._clock.now()
        self.unavailable_ids: set[str] = set()
        self.fail_calls: set[str] = set()
        self.calls: list[str] = []
        self.configured: SpeakerConfig | None = None
        self._lock = threading.Lock()
        self.playlists: dict[str, tuple[str, list[Track]]] = {
            "fake_playlist:party": ("Party-Basis", self.catalog[:12]),
            "fake_playlist:chill": ("Chill", self.catalog[20:28]),
        }

    # -- Simulation ---------------------------------------------------------

    def _record(self, name: str) -> None:
        self.calls.append(name)
        if name in self.fail_calls:
            raise SonosError(f"simulierter Fehler in {name}")

    def _position(self) -> float:
        if self.transport == TransportState.PLAYING:
            delta = (self._clock.now() - self._started_at).total_seconds()
            return self._elapsed_before_pause + max(0.0, delta)
        return self._elapsed_before_pause

    def _advance(self) -> None:
        """Simulation bis zur aktuellen Uhrzeit vorspulen."""
        while self.transport == TransportState.PLAYING and self.queue:
            current = self.queue[self.index]
            duration = float(current.duration or _DEFAULT_DURATION)
            position = self._position()
            if position < duration:
                return
            overflow = position - duration
            if self.index + 1 < len(self.queue):
                self.index += 1
                self._elapsed_before_pause = 0.0
                # Der nächste Titel startete genau am Ende des vorherigen.
                self._started_at = self._clock.now() - timedelta(seconds=overflow)
            else:
                self.transport = TransportState.STOPPED
                self._elapsed_before_pause = 0.0

    def _start(self) -> None:
        self.transport = TransportState.PLAYING
        self._elapsed_before_pause = 0.0
        self._started_at = self._clock.now()

    def _check_available(self, track: Track) -> None:
        if track.item_id in self.unavailable_ids:
            raise TrackUnavailable(f"{track.item_id} nicht verfügbar")

    @property
    def current(self) -> Track | None:
        with self._lock:
            self._advance()
            return self.queue[self.index] if self.queue else None

    def external_play(self, track: Track) -> None:
        """Simuliert einen Eingriff über die Sonos-App."""
        with self._lock:
            self.queue = [track]
            self.index = 0
            self._start()

    # -- SonosAdapter -------------------------------------------------------

    def discover(self) -> list[SpeakerInfo]:
        self._record("discover")
        return [
            SpeakerInfo(
                "RINCON_FAKE_LIVING", "Wohnzimmer", "192.0.2.10", True, ("RINCON_FAKE_LIVING",)
            ),
            SpeakerInfo(
                "RINCON_FAKE_KITCHEN", "Küche", "192.0.2.11", True, ("RINCON_FAKE_KITCHEN",)
            ),
        ]

    def configure(self, config: SpeakerConfig) -> None:
        self._record("configure")
        self.configured = config

    def get_accounts(self) -> list[MusicAccount]:
        self._record("get_accounts")
        return [MusicAccount(FAKE_ACCOUNT_ID, "Apple Music", "Fake-Konto")]

    def search_tracks(self, account_id: str, term: str, count: int) -> list[Track]:
        self._record("search_tracks")
        needle = term.casefold().strip()
        hits = [
            t for t in self.catalog if needle in t.title.casefold() or needle in t.artist.casefold()
        ]
        return hits[:count]

    def get_status(self) -> PlaybackStatus:
        self._record("get_status")
        with self._lock:
            self._advance()
            current = self.queue[self.index] if self.queue else None
            return PlaybackStatus(
                transport=self.transport,
                current_key=self.track_key(current) if current else None,
                position=self._position() if current else None,
                duration=float(current.duration or _DEFAULT_DURATION) if current else None,
                volume=self.volume,
                title=current.title if current else "",
                artist=current.artist if current else "",
            )

    def play_now(self, track: Track) -> None:
        self._record("play_now")
        self._check_available(track)
        with self._lock:
            self.queue = [track]
            self.index = 0
            self._start()

    def set_next(self, track: Track) -> None:
        self._record("set_next")
        self._check_available(track)
        with self._lock:
            self._advance()
            self.queue = [*self.queue[: self.index + 1], track]

    def clear_next(self) -> None:
        self._record("clear_next")
        with self._lock:
            self._advance()
            self.queue = self.queue[: self.index + 1]

    def skip(self) -> None:
        self._record("skip")
        with self._lock:
            self._advance()
            if self.index + 1 < len(self.queue):
                self.index += 1
                self._start()
            else:
                self.transport = TransportState.STOPPED
                self._elapsed_before_pause = 0.0

    def pause(self) -> None:
        self._record("pause")
        with self._lock:
            self._advance()
            if self.transport == TransportState.PLAYING:
                self._elapsed_before_pause = self._position()
                self.transport = TransportState.PAUSED

    def resume(self) -> None:
        self._record("resume")
        with self._lock:
            if self.transport in (TransportState.PAUSED, TransportState.STOPPED) and self.queue:
                elapsed = self._elapsed_before_pause
                self._start()
                self._elapsed_before_pause = elapsed

    def set_volume(self, volume: int) -> None:
        self._record("set_volume")
        self.volume = max(0, min(100, int(volume)))

    def list_fallback_sources(self) -> list[FallbackSource]:
        self._record("list_fallback_sources")
        return [
            FallbackSource(sid, name, "sonos_playlist") for sid, (name, _) in self.playlists.items()
        ]

    def fallback_tracks(self, source_id: str) -> list[Track]:
        self._record("fallback_tracks")
        if source_id not in self.playlists:
            raise SonosError(f"unbekannte Quelle {source_id}")
        return list(self.playlists[source_id][1])

    def track_key(self, track: Track) -> str:
        return uri_key(track.uri) if track.uri else track.item_id
