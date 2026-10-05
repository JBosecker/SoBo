"""SonosAdapter based on the SoCo fork with the music services browser (plan 4.2).

All SoCo calls are encapsulated here so that switching or updating the fork only
affects this file. The methods run exclusively on the Sonos worker thread.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from typing import Any, TypeVar
from urllib.parse import unquote

from .adapter import (
    FallbackSource,
    MusicAccount,
    MusicServiceAuthError,
    PlaybackStatus,
    SonosError,
    SpeakerConfig,
    SpeakerInfo,
    Track,
    TrackUnavailable,
    TransportState,
    uri_key,
)

_LOG = logging.getLogger(__name__)
T = TypeVar("T")

SERVICE_NAME = "Apple Music"

_TRANSPORT_MAP = {
    "PLAYING": TransportState.PLAYING,
    "PAUSED_PLAYBACK": TransportState.PAUSED,
    "STOPPED": TransportState.STOPPED,
    "TRANSITIONING": TransportState.TRANSITIONING,
}

_CONTAINER_PREFIX = "x-rincon-cpcontainer:"


def parse_hms(value: str | None) -> float | None:
    """'0:03:25' → 205.0; empty or invalid values → None."""
    if not value or value == "NOT_IMPLEMENTED":
        return None
    try:
        parts = [float(p) for p in value.split(":")]
    except ValueError:
        return None
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def explicit_flag(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes"):
        return True
    if text in ("0", "false", "no"):
        return False
    return None


def _as_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def https_or_empty(url: str) -> str:
    return url if url.startswith("https://") else ""


def decode_container_favorite(uri: str) -> tuple[str, int | None] | None:
    """Split a favourite URI ``x-rincon-cpcontainer:<8 hex><id>?sid=…``.

    Returns (container ID, service ID), or None if it is not a container.
    """
    if not uri.startswith(_CONTAINER_PREFIX):
        return None
    body, _, query = uri[len(_CONTAINER_PREFIX) :].partition("?")
    body = unquote(body)
    if len(body) > 8 and re.fullmatch(r"[0-9a-fA-F]{8}", body[:8]):
        body = body[8:]
    body = body.split("#", 1)[0]
    sid: int | None = None
    for pair in query.split("&"):
        key, _, value = pair.partition("=")
        if key == "sid":
            sid = _as_int(value)
    return body, sid


def track_from_browse_item(item: Any, account_id: str) -> Track | None:
    """MusicServiceBrowseItem → Track (playable tracks only)."""
    raw: Mapping[str, Any] = item.raw or {}
    item_type = str(item.item_type or raw.get("itemType", "")).rsplit(".", 1)[-1].lower()
    if item.kind == "mediaCollection" or (item_type and item_type != "track"):
        return None
    meta = raw.get("trackMetadata")
    meta = meta if isinstance(meta, Mapping) else {}
    explicit = explicit_flag(raw.get("isExplicit", meta.get("isExplicit")))
    return Track(
        item_id=str(item.item_id),
        title=str(item.title or ""),
        artist=str(item.artist or meta.get("artist", "") or ""),
        album=str(meta.get("album", "") or ""),
        art_url=https_or_empty(str(item.album_art_uri or meta.get("albumArtURI", "") or "")),
        duration=_as_int(meta.get("duration")),
        explicit=explicit,
        account_id=account_id,
    )


class SoCoAdapter:
    def __init__(
        self,
        discover_fn: Callable[[], set[Any] | None] | None = None,
        browser_factory: Callable[[Any, Any], Any] | None = None,
        accounts_fn: Callable[[Any], list[Any]] | None = None,
    ) -> None:
        # Dependencies are injectable so tests run without a network.
        self._discover_fn = discover_fn or _default_discover
        self._browser_factory = browser_factory or _default_browser
        self._accounts_fn = accounts_fn or _default_accounts
        self._coordinator: Any | None = None
        self._browsers: dict[str, Any] = {}
        self._accounts: dict[str, Any] = {}

    # -- Helpers -------------------------------------------------------------

    @property
    def coordinator(self) -> Any:
        if self._coordinator is None:
            raise SonosError("No speaker configured")
        return self._coordinator

    def _speakers(self) -> list[Any]:
        return list(self._discover_fn() or [])

    def _browser(self, account_id: str) -> Any:
        if account_id not in self._browsers:
            if account_id not in self._accounts:
                self.get_accounts()
            account = self._accounts.get(account_id)
            if account is None:
                raise SonosError(f"Account {account_id} not found")
            self._browsers[account_id] = self._browser_factory(self.coordinator, account)
        return self._browsers[account_id]

    def _with_browser(self, account_id: str, fn: Callable[[Any], T]) -> T:
        """Run `fn(browser)`; on an auth fault re-read the household credentials once.

        Sonos players refresh music-service tokens themselves and store the new ones
        in the household. Credentials SoBo read earlier can therefore be outdated;
        reading them again and retrying fixes that. If the service still rejects
        the sign-in, the stored authorization itself is invalid.
        """
        try:
            return fn(self._browser(account_id))
        except Exception as err:
            if not _is_auth_error(err):
                raise
            _LOG.info("Music service rejected the sign-in, re-reading accounts: %s", err)
        self._browsers.pop(account_id, None)
        self.get_accounts()
        try:
            return fn(self._browser(account_id))
        except Exception as err:
            if _is_auth_error(err):
                _LOG.warning(
                    "Music service still rejects the sign-in after re-reading it (%s)",
                    _describe_account(self._accounts.get(account_id)),
                )
                raise MusicServiceAuthError(str(err)) from err
            raise

    def _resolve(self, track: Track) -> tuple[str, str]:
        if track.uri:
            return track.uri, track.meta or ""
        from soco.exceptions import MusicServiceException
        from soco.music_services.browser.playback import build_metadata, build_uri, resolve_item

        def resolve(browser: Any) -> tuple[str, str]:
            item_id, item_type, mime, title = resolve_item(browser, track.item_id)
            uri = build_uri(browser, item_id, item_type or "track", mime)
            meta = build_metadata(
                browser, item_id, title or track.title, item_type or "track", mime=mime, uri=uri
            )
            return str(uri), str(meta)

        try:
            return self._with_browser(track.account_id, resolve)
        except MusicServiceAuthError:
            raise
        except MusicServiceException as err:
            raise TrackUnavailable(str(err)) from err

    def _enqueue_at_end(self, uri: str, meta: str) -> None:
        self.coordinator.avTransport.AddURIToQueue(
            [
                ("InstanceID", 0),
                ("EnqueuedURI", uri),
                ("EnqueuedURIMetaData", meta),
                ("DesiredFirstTrackNumberEnqueued", 0),
                ("EnqueueAsNext", 0),
            ]
        )

    def _remove_after_current(self) -> None:
        coord = self.coordinator
        info = coord.get_current_track_info()
        position = _as_int(info.get("playlist_position")) or 0  # 1-based, 0 = none
        size = int(coord.queue_size)
        for index in range(size - 1, max(position, 1) - 1, -1):
            coord.remove_from_queue(index)

    # -- SonosAdapter -------------------------------------------------------

    def discover(self) -> list[SpeakerInfo]:
        result = []
        for speaker in self._speakers():
            group = speaker.group
            result.append(
                SpeakerInfo(
                    uid=speaker.uid,
                    name=speaker.player_name,
                    ip=speaker.ip_address,
                    is_coordinator=bool(speaker.is_coordinator),
                    group_members=tuple(m.uid for m in group.members) if group else (),
                )
            )
        return sorted(result, key=lambda s: s.name)

    def configure(self, config: SpeakerConfig) -> None:
        speakers = {s.uid: s for s in self._speakers()}
        coord = speakers.get(config.coordinator_uid)
        if coord is None:
            raise SonosError(f"Speaker {config.coordinator_uid} not found")
        if not coord.is_coordinator:
            coord.unjoin()
        for uid in config.members:
            member = speakers.get(uid)
            if member is None or uid == coord.uid:
                continue
            if member.group is None or member.group.coordinator.uid != coord.uid:
                member.join(coord)
        self._coordinator = coord
        self._browsers.clear()
        self._accounts.clear()

    def get_accounts(self) -> list[MusicAccount]:
        accounts = self._accounts_fn(self.coordinator)
        self._accounts = {str(a.serial_number): a for a in accounts}
        return [
            MusicAccount(str(a.serial_number), SERVICE_NAME, str(a.nickname or ""))
            for a in accounts
        ]

    def search_tracks(self, account_id: str, term: str, count: int) -> list[Track]:
        from soco.exceptions import MusicServiceException

        try:
            result = self._with_browser(account_id, lambda b: b.search("tracks", term, 0, count))
        except MusicServiceAuthError:
            raise
        except MusicServiceException as err:
            raise SonosError(str(err)) from err
        tracks = [track_from_browse_item(item, account_id) for item in result.items]
        return [t for t in tracks if t is not None][:count]

    def get_status(self) -> PlaybackStatus:
        coord = self.coordinator
        transport = coord.get_current_transport_info()
        info = coord.get_current_track_info()
        state = _TRANSPORT_MAP.get(
            str(transport.get("current_transport_state", "")), TransportState.UNKNOWN
        )
        uri = str(info.get("uri") or "")
        volume: int | None
        try:
            volume = int(coord.group.volume)
        except Exception:  # group volume is optional
            volume = None
        return PlaybackStatus(
            transport=state,
            current_key=uri_key(uri) if uri else None,
            position=parse_hms(info.get("position")),
            duration=parse_hms(info.get("duration")),
            volume=volume,
            title=str(info.get("title") or ""),
            artist=str(info.get("artist") or ""),
        )

    def play_now(self, track: Track) -> None:
        uri, meta = self._resolve(track)
        coord = self.coordinator
        coord.clear_queue()
        self._enqueue_at_end(uri, meta)
        coord.play_from_queue(0)

    def set_next(self, track: Track) -> None:
        uri, meta = self._resolve(track)
        self._remove_after_current()
        self._enqueue_at_end(uri, meta)

    def clear_next(self) -> None:
        self._remove_after_current()

    def skip(self) -> None:
        from soco.exceptions import SoCoUPnPException

        try:
            self.coordinator.next()
        except SoCoUPnPException:
            # No further track in the Sonos queue → stop; the engine starts the next one.
            self.coordinator.stop()

    def pause(self) -> None:
        self.coordinator.pause()

    def resume(self) -> None:
        self.coordinator.play()

    def set_volume(self, volume: int) -> None:
        self.coordinator.group.volume = max(0, min(100, int(volume)))

    def list_fallback_sources(self) -> list[FallbackSource]:
        coord = self.coordinator
        sources = [
            FallbackSource(f"sonos_playlist:{p.item_id}", str(p.title), "sonos_playlist")
            for p in coord.get_sonos_playlists()
        ]
        for fav in coord.music_library.get_sonos_favorites():
            resources = getattr(fav, "resources", None) or []
            uri = str(resources[0].uri) if resources else ""
            decoded = decode_container_favorite(uri)
            if decoded:
                sources.append(FallbackSource(f"favorite:{decoded[0]}", str(fav.title), "favorite"))
        return sources

    def fallback_tracks(self, source_id: str) -> list[Track]:
        kind, _, ident = source_id.partition(":")
        if kind == "sonos_playlist":
            return self._sonos_playlist_tracks(ident)
        if kind == "favorite":
            return self._service_container_tracks(ident)
        raise SonosError(f"Unknown source {source_id}")

    def _sonos_playlist_tracks(self, playlist_id: str) -> list[Track]:
        from soco.data_structures import to_didl_string

        items = self.coordinator.music_library.browse_by_idstring(
            "sonos_playlists", playlist_id, max_items=500
        )
        tracks = []
        for item in items:
            resources = getattr(item, "resources", None) or []
            if not resources:
                continue
            uri = str(resources[0].uri)
            tracks.append(
                Track(
                    item_id=uri_key(uri),
                    title=str(getattr(item, "title", "") or ""),
                    artist=str(getattr(item, "creator", "") or ""),
                    album=str(getattr(item, "album", "") or ""),
                    uri=uri,
                    meta=to_didl_string(item),
                )
            )
        return tracks

    def _service_container_tracks(self, container_id: str) -> list[Track]:
        if not self._accounts:
            self.get_accounts()
        if not self._accounts:
            raise SonosError("No Apple Music account in the Sonos household")
        account_id = next(iter(self._accounts))
        result = self._with_browser(account_id, lambda b: b.get_metadata(container_id, 0, 200))
        tracks = [track_from_browse_item(item, account_id) for item in result.items]
        return [t for t in tracks if t is not None]

    def track_key(self, track: Track) -> str:
        return uri_key(track.uri) if track.uri else track.item_id


# -- Default dependencies (real SoCo) ------------------------------------


def _default_discover() -> set[Any] | None:
    import soco

    result: set[Any] | None = soco.discover(timeout=5)
    return result


def _default_accounts(device: Any) -> list[Any]:
    from soco.music_services import MusicService
    from soco.music_services.browser import MusicServiceBrowser

    service_id = int(MusicService(SERVICE_NAME, device=device).service_id)
    return [a for a in MusicServiceBrowser.get_accounts(device) if a.service_id == service_id]


def _default_browser(device: Any, account: Any) -> Any:
    from soco.music_services.browser import MusicServiceBrowser

    return use_household_identity_if_unscoped(
        MusicServiceBrowser(SERVICE_NAME, account=account, device=device)
    )


def use_household_identity_if_unscoped(browser: Any) -> Any:
    """Send SMAPI calls under the plain household ID for accounts without an account UID.

    The SoCo fork derives an account-scoped identity (``<household>_<uid:08x>``) from
    the account UDN. Accounts stored as ``…_X_#Svc52231-0-Token`` have the UID 0;
    Apple rejects the resulting ``<household>_00000000`` with ``AuthTokenExpired``
    (``InvalidTokenException``), while the plain household ID works for search,
    metadata and token refresh (verified on a real household,
    `scripts/diagnose_apple_music.py`). Accounts with a real UID keep the fork's
    behaviour.
    """
    try:
        uid = int(browser.account.account_uid)
    except Exception:  # no UID in the UDN: the fork does not scope either
        return browser
    if uid == 0 and hasattr(browser, "_scoped_client") and hasattr(browser, "_client"):
        browser._scoped_client = lambda force_scoped=False: browser._client
    return browser


def _is_auth_error(err: BaseException) -> bool:
    """Music service rejected the stored sign-in (expired/invalid token)."""
    from soco.exceptions import MusicServiceAuthException

    if isinstance(err, MusicServiceAuthException):
        return True
    text = str(err).lower()
    return any(marker in text for marker in ("authtokenexpired", "invalidtoken", "unauthorized"))


# Marker the Sonos household stores instead of a token when it needs re-authorization
NEEDS_REAUTH = "needs_reauth"


def _describe_account(account: Any) -> str:
    """Shape of the stored credentials for the log – never the secrets themselves."""
    if account is None:
        return "account not found"
    token = str(getattr(account, "token", "") or "")
    key = str(getattr(account, "key", "") or "")
    return (
        f"serial={getattr(account, 'serial_number', '?')} "
        f"udn={str(getattr(account, 'udn', '')).split('_X_')[0]} "
        f"token={'needs_reauth' if token == NEEDS_REAUTH else len(token)} chars, "
        f"key={len(key)} chars"
    )
