"""Schnittstelle zwischen Jukebox-Engine und Sonos (Plan 1, 4.2, Phase 1).

Die Engine kennt nur dieses Protokoll. Alle Methoden sind synchron und werden
ausschließlich vom `SonosWorker` (ein dedizierter Thread) aufgerufen – mit
Ausnahme von `track_key`, das rein rechnerisch ist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol
from urllib.parse import unquote


class SonosError(Exception):
    """Fehler bei der Kommunikation mit Sonos oder dem Musikdienst."""


class SonosTimeout(SonosError):
    """Ein Sonos-Aufruf hat das Zeitlimit überschritten."""


class TrackUnavailable(SonosError):
    """Der Titel lässt sich nicht (mehr) abspielen."""


class TransportState(StrEnum):
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    TRANSITIONING = "transitioning"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Track:
    """Ein abspielbarer Titel.

    `item_id` ist die ID beim Musikdienst (z. B. ``song:1844932150``). URI und
    DIDL-Metadaten werden für Musikdienst-Titel erst beim Einreihen aufgelöst,
    weil sie signierte, ablaufende URLs enthalten können (Plan 5.1). Nur Titel
    aus Sonos-Playlists bringen eine fertige `uri` (+ `meta`) mit.
    """

    item_id: str
    title: str
    artist: str = ""
    album: str = ""
    art_url: str = ""
    duration: int | None = None
    explicit: bool | None = None
    account_id: str = ""
    uri: str | None = None
    meta: str | None = None


@dataclass(frozen=True, slots=True)
class PlaybackStatus:
    transport: TransportState
    current_key: str | None
    position: float | None = None
    duration: float | None = None
    volume: int | None = None
    title: str = ""
    artist: str = ""


@dataclass(frozen=True, slots=True)
class SpeakerInfo:
    uid: str
    name: str
    ip: str
    is_coordinator: bool
    group_members: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MusicAccount:
    account_id: str
    service_name: str
    nickname: str = ""


@dataclass(frozen=True, slots=True)
class FallbackSource:
    source_id: str
    name: str
    kind: str  # "sonos_playlist" | "favorite"


@dataclass(frozen=True, slots=True)
class SpeakerConfig:
    coordinator_uid: str
    members: tuple[str, ...] = field(default_factory=tuple)


class SonosAdapter(Protocol):
    def discover(self) -> list[SpeakerInfo]: ...

    def configure(self, config: SpeakerConfig) -> None:
        """Koordinator festlegen und Gruppenmitglieder dazuholen."""
        ...

    def get_accounts(self) -> list[MusicAccount]: ...

    def search_tracks(self, account_id: str, term: str, count: int) -> list[Track]: ...

    def get_status(self) -> PlaybackStatus: ...

    def play_now(self, track: Track) -> None:
        """Sonos-Queue leeren, Titel einreihen und sofort abspielen."""
        ...

    def set_next(self, track: Track) -> None:
        """Alles hinter dem aktuellen Titel entfernen und `track` anhängen.

        Ergebnis: Sonos-Queue = [aktuell, track]. Bewusst *nicht* über
        ``as_next=True``, das bei Sonos nur im Shuffle-Modus wirkt.
        """
        ...

    def clear_next(self) -> None:
        """Alles hinter dem aktuellen Titel entfernen."""
        ...

    def skip(self) -> None: ...

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def set_volume(self, volume: int) -> None: ...

    def list_fallback_sources(self) -> list[FallbackSource]: ...

    def fallback_tracks(self, source_id: str) -> list[Track]: ...

    def track_key(self, track: Track) -> str:
        """Stabiler Schlüssel, um den laufenden Titel (`PlaybackStatus.current_key`)
        einem Track zuzuordnen."""
        ...


_KNOWN_EXTENSIONS = (".mp4", ".mp3", ".flac", ".wma", ".ogg", ".m4a", ".aac")


def uri_key(uri: str) -> str:
    """Leitet aus einer Sonos-URI einen vergleichbaren Schlüssel ab.

    ``x-sonos-http:song%3a123.mp4?sid=204&flags=8224&sn=3`` → ``song:123``.
    Für Sonos-Playlist-Titel wird dieselbe Funktion auf beide Seiten angewandt,
    der Schlüssel ist dann die normalisierte URI ohne Query.
    """
    body = uri.split(":", 1)[1] if ":" in uri else uri
    body = body.split("?", 1)[0]
    for ext in _KNOWN_EXTENSIONS:
        if body.lower().endswith(ext):
            body = body[: -len(ext)]
            break
    return unquote(body)
