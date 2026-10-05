"""Interface between the jukebox engine and Sonos (plan 1, 4.2, phase 1).

The engine only knows this protocol. All methods are synchronous and are called
exclusively by the `SonosWorker` (a dedicated thread) – except `track_key`, which
is a pure computation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol
from urllib.parse import unquote


class SonosError(Exception):
    """Error while talking to Sonos or the music service."""


class SonosTimeout(SonosError):
    """A Sonos call exceeded its time limit."""


class TrackUnavailable(SonosError):
    """The track cannot be played (any more)."""


class TransportState(StrEnum):
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    TRANSITIONING = "transitioning"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Track:
    """A playable track.

    `item_id` is the music service ID (e.g. ``song:1844932150``). For music service
    tracks, URI and DIDL metadata are resolved only when enqueuing because they may
    contain signed, expiring URLs (plan 5.1). Only tracks from Sonos playlists come
    with a ready-made `uri` (+ `meta`).
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
        """Set the coordinator and join the group members."""
        ...

    def get_accounts(self) -> list[MusicAccount]: ...

    def search_tracks(self, account_id: str, term: str, count: int) -> list[Track]: ...

    def get_status(self) -> PlaybackStatus: ...

    def play_now(self, track: Track) -> None:
        """Clear the Sonos queue, enqueue the track and play it right away."""
        ...

    def set_next(self, track: Track) -> None:
        """Remove everything after the current track and append `track`.

        Result: Sonos queue = [current, track]. Deliberately *not* via
        ``as_next=True``, which Sonos only honours in shuffle mode.
        """
        ...

    def clear_next(self) -> None:
        """Remove everything after the current track."""
        ...

    def skip(self) -> None: ...

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def set_volume(self, volume: int) -> None: ...

    def list_fallback_sources(self) -> list[FallbackSource]: ...

    def fallback_tracks(self, source_id: str) -> list[Track]: ...

    def track_key(self, track: Track) -> str:
        """Stable key to match the playing track (`PlaybackStatus.current_key`)
        to a track."""
        ...


_KNOWN_EXTENSIONS = (".mp4", ".mp3", ".flac", ".wma", ".ogg", ".m4a", ".aac")


def uri_key(uri: str) -> str:
    """Derive a comparable key from a Sonos URI.

    ``x-sonos-http:song%3a123.mp4?sid=204&flags=8224&sn=3`` → ``song:123``.
    For Sonos playlist tracks the same function is applied on both sides; the key
    is then the normalised URI without its query.
    """
    body = uri.split(":", 1)[1] if ":" in uri else uri
    body = body.split("?", 1)[0]
    for ext in _KNOWN_EXTENSIONS:
        if body.lower().endswith(ext):
            body = body[: -len(ext)]
            break
    return unquote(body)
