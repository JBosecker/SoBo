"""Contract tests: the same suite against FakeSonosAdapter and SoCoAdapter with a
mocked SoCo device (plan 9)."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from soco.exceptions import SoCoUPnPException

from sobo.clock import ManualClock
from sobo.sonos.adapter import (
    MusicServiceAuthError,
    SonosAdapter,
    SpeakerConfig,
    Track,
    TransportState,
    uri_key,
)
from sobo.sonos.fake_adapter import FakeSonosAdapter
from sobo.sonos.fixtures import FAKE_ACCOUNT_ID, fake_catalog
from sobo.sonos.soco_adapter import (
    SoCoAdapter,
    decode_container_favorite,
    library_playlists,
    parse_hms,
    track_from_browse_item,
    use_household_identity_if_unscoped,
)

# --------------------------------------------------------------------------- SoCo mocks


class _Group:
    def __init__(self, device: FakeSoCoDevice) -> None:
        self.volume = 15
        self.members = [device]
        self.coordinator = device


class _AVTransport:
    def __init__(self, device: FakeSoCoDevice) -> None:
        self.device = device

    def AddURIToQueue(self, args: list[tuple[str, Any]]) -> dict[str, str]:
        values = dict(args)
        assert values["EnqueueAsNext"] == 0
        assert values["DesiredFirstTrackNumberEnqueued"] == 0
        self.device.queue.append((values["EnqueuedURI"], values["EnqueuedURIMetaData"]))
        return {"FirstTrackNumberEnqueued": str(len(self.device.queue))}


class FakeSoCoDevice:
    def __init__(self, uid: str = "RINCON_1", name: str = "Wohnzimmer") -> None:
        self.uid = uid
        self.player_name = name
        self.ip_address = "192.0.2.20"
        self.is_coordinator = True
        self.queue: list[tuple[str, str]] = []
        self.index = -1
        self.state = "STOPPED"
        self.group = _Group(self)
        self.avTransport = _AVTransport(self)
        self.joined: list[str] = []

    @property
    def queue_size(self) -> int:
        return len(self.queue)

    def clear_queue(self) -> None:
        self.queue.clear()
        self.index = -1
        self.state = "STOPPED"

    def play_from_queue(self, index: int) -> None:
        self.index = index
        self.state = "PLAYING"

    def remove_from_queue(self, index: int) -> None:
        assert index != self.index, "the playing track must never be removed"
        del self.queue[index]
        if index < self.index:
            self.index -= 1

    def get_current_track_info(self) -> dict[str, str]:
        if self.index < 0:
            return {"playlist_position": "0", "uri": "", "position": "", "duration": ""}
        return {
            "playlist_position": str(self.index + 1),
            "uri": self.queue[self.index][0],
            "position": "0:00:10",
            "duration": "0:03:20",
            "title": "x",
            "artist": "y",
        }

    def get_current_transport_info(self) -> dict[str, str]:
        return {"current_transport_state": self.state}

    def next(self) -> None:
        if self.index + 1 >= len(self.queue):
            raise SoCoUPnPException("no next", 711, "")
        self.index += 1

    def stop(self) -> None:
        self.state = "STOPPED"

    def pause(self) -> None:
        self.state = "PAUSED_PLAYBACK"

    def play(self) -> None:
        self.state = "PLAYING"

    def join(self, master: FakeSoCoDevice) -> None:
        master.joined.append(self.uid)
        self.group = master.group

    def unjoin(self) -> None:
        self.unjoined = True
        self.group = _Group(self)


class _Account:
    service_id = 204
    serial_number = 3
    udn = "SA_RINCON52231_X_#Svc52231-0-Token"
    nickname = "Familie"


class _BrowseItem:
    def __init__(self, track: Track) -> None:
        self.item_id = track.item_id
        self.title = track.title
        self.artist = track.artist
        self.kind = "mediaMetadata"
        self.item_type = "track"
        self.album_art_uri = track.art_url.replace("example.invalid", "is1-ssl.mzstatic.com")
        self.raw = {
            "itemType": "track",
            "trackMetadata": {"album": track.album, "duration": str(track.duration)},
            "isExplicit": "1" if track.explicit else "0",
        }


class _SearchResult:
    def __init__(self, items: list[_BrowseItem]) -> None:
        self.items = items


class _MusicService:
    desc = "SA_RINCON52231_X_#Svc52231-0-Token"


class FakeBrowser:
    service_id = "204"
    service_name = "Apple Music"

    def __init__(self) -> None:
        self.account = _Account()
        self.music_service = _MusicService()
        self.catalog = fake_catalog()

    def search(self, category: str, term: str, index: int, count: int) -> _SearchResult:
        assert category == "tracks"
        needle = term.casefold()
        hits = [
            t for t in self.catalog if needle in t.title.casefold() or needle in t.artist.casefold()
        ]
        return _SearchResult([_BrowseItem(t) for t in hits[:count]])

    def get_media_metadata(self, item_id: str) -> dict[str, str]:
        return {"itemType": "track", "mimeType": "audio/aac", "title": "T"}


def make_soco_adapter() -> tuple[SoCoAdapter, FakeSoCoDevice]:
    device = FakeSoCoDevice()
    other = FakeSoCoDevice("RINCON_2", "Kitchen")
    adapter = SoCoAdapter(
        discover_fn=lambda: {device, other},
        browser_factory=lambda dev, acc: FakeBrowser(),
        accounts_fn=lambda dev: [_Account()],
    )
    adapter.configure(SpeakerConfig("RINCON_1", ("RINCON_2",)))
    return adapter, device


# --------------------------------------------------------------------------- contract


@pytest.fixture(params=["fake", "soco"])
def adapter(request: pytest.FixtureRequest) -> SonosAdapter:
    if request.param == "fake":
        fake = FakeSonosAdapter(ManualClock())
        fake.configure(SpeakerConfig("RINCON_FAKE_LIVING"))
        return fake
    soco_adapter, _ = make_soco_adapter()
    return soco_adapter


def _account(adapter: SonosAdapter) -> str:
    accounts = adapter.get_accounts()
    assert len(accounts) == 1
    assert accounts[0].service_name == "Apple Music"
    return accounts[0].account_id


def _tracks(adapter: SonosAdapter, term: str) -> list[Track]:
    return adapter.search_tracks(_account(adapter), term, 10)


def test_search_returns_tracks(adapter: SonosAdapter) -> None:
    tracks = _tracks(adapter, "disco atlas")
    assert [t.title for t in tracks] == [
        "Dancefloor Cartography",
        "Mirrorball Weather",
        "Basement Constellations",
    ]
    assert all(t.duration and t.duration > 0 for t in tracks)
    assert tracks[2].explicit is True


def test_play_now_then_status(adapter: SonosAdapter) -> None:
    track = _tracks(adapter, "neon")[0]
    adapter.play_now(track)
    status = adapter.get_status()
    assert status.transport == TransportState.PLAYING
    assert status.current_key == adapter.track_key(track)


def test_set_next_replaces_previous_next_and_skip_reaches_it(adapter: SonosAdapter) -> None:
    first, second, third = _tracks(adapter, "disco atlas")
    adapter.play_now(first)
    adapter.set_next(second)
    adapter.set_next(third)  # replaces `second`
    adapter.skip()
    assert adapter.get_status().current_key == adapter.track_key(third)


def test_clear_next_then_skip_stops(adapter: SonosAdapter) -> None:
    first, second, _ = _tracks(adapter, "disco atlas")
    adapter.play_now(first)
    adapter.set_next(second)
    adapter.clear_next()
    adapter.skip()
    assert adapter.get_status().transport == TransportState.STOPPED


def test_pause_resume(adapter: SonosAdapter) -> None:
    adapter.play_now(_tracks(adapter, "neon")[0])
    adapter.pause()
    assert adapter.get_status().transport == TransportState.PAUSED
    adapter.resume()
    assert adapter.get_status().transport == TransportState.PLAYING


def test_volume(adapter: SonosAdapter) -> None:
    adapter.set_volume(130)
    assert adapter.get_status().volume == 100
    adapter.set_volume(33)
    assert adapter.get_status().volume == 33


def test_discover(adapter: SonosAdapter) -> None:
    speakers = adapter.discover()
    assert len(speakers) == 2
    assert all(s.uid and s.name for s in speakers)


# --------------------------------------------------------------------------- SoCo specific


def test_soco_enqueue_uses_apple_music_uri_and_account_descriptor() -> None:
    adapter, device = make_soco_adapter()
    track = adapter.search_tracks("3", "neon", 1)[0]
    adapter.play_now(track)
    uri, meta = device.queue[0]
    assert uri == "x-sonos-http:song%3a1000001.mp4?sid=204&flags=8224&sn=3"
    assert 'id="cdudn"' in meta and "Svc52231-0-Token" in meta
    assert uri_key(uri) == "song:1000001" == adapter.track_key(track)


def test_soco_set_next_keeps_current_and_removes_rest() -> None:
    adapter, device = make_soco_adapter()
    tracks = adapter.search_tracks("3", "disco", 3)
    adapter.play_now(tracks[0])
    adapter.set_next(tracks[1])
    adapter.set_next(tracks[2])
    assert [uri_key(u) for u, _ in device.queue] == [tracks[0].item_id, tracks[2].item_id]
    assert device.index == 0


def test_soco_configure_joins_members() -> None:
    _, device = make_soco_adapter()
    assert device.joined == ["RINCON_2"]


def test_soco_release_ungroups_members() -> None:
    adapter, device = make_soco_adapter()
    other = next(s for s in adapter._speakers() if s.uid == "RINCON_2")
    assert other.group.coordinator is device
    adapter.release(SpeakerConfig("RINCON_1", ("RINCON_2",)))
    assert other.unjoined
    assert not getattr(device, "unjoined", False)


def test_soco_search_filters_non_https_art() -> None:
    adapter, _ = make_soco_adapter()
    track = adapter.search_tracks("3", "neon", 1)[0]
    assert track.art_url.startswith("https://is1-ssl.mzstatic.com/")
    assert track.account_id == "3"


def test_track_from_browse_item_skips_containers() -> None:
    item = _BrowseItem(fake_catalog()[0])
    item.kind = "mediaCollection"
    assert track_from_browse_item(item, "3") is None


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("x-sonos-http:song%3a123.mp4?sid=204&flags=8224&sn=3", "song:123"),
        ("x-sonos-http:song%3a123.flac?sid=204&flags=0&sn=3", "song:123"),
        ("x-file-cifs://nas/music/a%20b.mp3", "//nas/music/a b"),
        ("song:1", "1"),
    ],
)
def test_uri_key(uri: str, expected: str) -> None:
    assert uri_key(uri) == expected


def test_decode_container_favorite() -> None:
    uri = "x-rincon-cpcontainer:1006206cplaylist%3apl.abc?sid=204&flags=8300&sn=3"
    assert decode_container_favorite(uri) == ("playlist:pl.abc", 204)
    assert decode_container_favorite("x-sonosapi-stream:s1?sid=254") is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [("0:03:25", 205.0), ("1:00:00", 3600.0), ("", None), ("NOT_IMPLEMENTED", None), ("x", None)],
)
def test_parse_hms(value: str, expected: float | None) -> None:
    assert parse_hms(value) == expected


def test_fake_playback_advances_with_clock() -> None:
    clock = ManualClock()
    fake = FakeSonosAdapter(clock)
    first, second = fake.catalog[0], fake.catalog[1]
    fake.play_now(first)
    fake.set_next(second)
    clock.advance((first.duration or 0) + 5)
    status = fake.get_status()
    assert status.current_key == second.item_id
    assert status.position == pytest.approx(5)
    clock.advance(second.duration or 0)
    assert fake.get_status().transport == TransportState.STOPPED


def test_fixture_account() -> None:
    assert FAKE_ACCOUNT_ID


def test_soco_can_decrypt_the_account_envelope() -> None:
    """Accounts arrive AES-encrypted from the speaker; the fork needs `cryptography`.

    Without it, release 0.1.0 could not list the Apple Music account. This builds an
    envelope the way Sonos does and decrypts it with the fork's own code.
    """
    import base64
    import hashlib
    import os

    pytest.importorskip("soco")
    import cryptography  # noqa: F401 – must be installed with the app (soco[music-services])
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from soco.music_services.browser import credentials

    household = "Sonos_TESTHOUSEHOLD"
    payload = (
        b'<MediaServers><MediaServer UDN="SA_RINCON52231_X_#Svc52231-0-Token" '
        b'SerialNum0="3" Nickname0="Party" Token0="t" Key0="k"/></MediaServers>'
    )
    plaintext = payload + hashlib.md5(payload).digest()[:4]  # noqa: S324 – Sonos protocol
    iv = os.urandom(16)
    global_key = hashlib.md5(household.encode() + credentials._ACCOUNT_SALT).digest()  # noqa: S324
    key = hashlib.md5(iv + global_key).digest()  # noqa: S324
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    encoded = "2:" + base64.b64encode(iv + encryptor.update(padded) + encryptor.finalize()).decode()

    decrypted = credentials._decrypt_account_payload(encoded, household)
    [account] = credentials.ConfiguredMusicServiceAccount.from_payload(decrypted)
    assert (account.service_id, account.serial_number, account.nickname) == (204, 3, "Party")


class _ExpiringBrowser(FakeBrowser):
    """Rejects credentials until the household hands out fresh ones."""

    def __init__(self, generation: int, valid_from: int) -> None:
        super().__init__()
        self.generation = generation
        self.valid_from = valid_from

    def search(self, category: str, term: str, index: int, count: int) -> _SearchResult:
        from soco.exceptions import MusicServiceAuthException

        if self.generation < self.valid_from:
            raise MusicServiceAuthException(
                "SOAP-ENV:Client.AuthTokenExpired: InvalidTokenException (HTTP 500)"
            )
        return super().search(category, term, index, count)


def _expiring_adapter(valid_from: int) -> tuple[SoCoAdapter, list[int]]:
    reads: list[int] = []

    def accounts(_: object) -> list[_Account]:
        reads.append(len(reads) + 1)
        return [_Account()]

    adapter = SoCoAdapter(
        discover_fn=lambda: {FakeSoCoDevice()},
        browser_factory=lambda dev, acc: _ExpiringBrowser(len(reads), valid_from),
        accounts_fn=accounts,
    )
    adapter.configure(SpeakerConfig("RINCON_1", ()))
    return adapter, reads


def test_soco_rereads_household_credentials_after_auth_fault() -> None:
    # Credentials read first are outdated (rotated by the players), the second read works.
    adapter, reads = _expiring_adapter(valid_from=2)
    assert adapter.search_tracks("3", "neon", 1)
    assert reads == [1, 2]
    assert adapter.search_tracks("3", "neon", 1)  # the fresh browser is kept
    assert reads == [1, 2]


def test_soco_reports_rejected_sign_in() -> None:
    adapter, reads = _expiring_adapter(valid_from=99)
    with pytest.raises(MusicServiceAuthError, match="AuthTokenExpired"):
        adapter.search_tracks("3", "neon", 1)
    assert reads == [1, 2]  # retried exactly once


class _IdentityBrowser:
    def __init__(self, uid: int | None) -> None:
        self._client = object()
        self._scoped = object()
        self.uid = uid

        class _Acc:
            @property
            def account_uid(acc_self) -> int:
                if uid is None:
                    raise ValueError("no account UID in the UDN")
                return uid

        self.account = _Acc()

    def _scoped_client(self, force_scoped: bool = False) -> object:
        return self._scoped


@pytest.mark.parametrize(("uid", "plain"), [(0, True), (0x97D97447, False), (None, False)])
def test_household_identity_for_accounts_without_uid(uid: int | None, plain: bool) -> None:
    """Apple rejects `<household>_00000000` (real household, diagnose_apple_music.py)."""
    browser = use_household_identity_if_unscoped(_IdentityBrowser(uid))
    expected = browser._client if plain else browser._scoped
    assert browser._scoped_client() is expected
    assert browser._scoped_client(True) is expected


class _LibraryClient:
    TREE: ClassVar[dict[str, list[dict[str, str]]]] = {
        "root": [
            {"id": "library", "title": "Mediathek", "itemType": "container"},
            {"id": "browse", "title": "Entdecken", "itemType": "container"},
            {"id": "playlist:pl.editorial", "title": "Top Hits", "itemType": "playlist"},
        ],
        "library": [
            {"id": "libraryfolder:f.1", "title": "Playlists", "itemType": "container"},
            {"id": "libraryalbums", "title": "Alben", "itemType": "album"},
        ],
        "libraryfolder:f.1": [
            {"id": "libraryplaylist:p.b", "title": "Zeta", "itemType": "playlist"},
            {"id": "libraryplaylist:p.a", "title": "Abendessen", "itemType": "playlist"},
        ],
    }

    def __init__(self) -> None:
        self.opened: list[str] = []

    def get_metadata(self, object_id: str, index: int, count: int) -> dict[str, object]:
        self.opened.append(object_id)
        items = self.TREE.get(object_id, [])
        return {"items": items[index : index + count], "total": len(items)}


class _Page:
    def __init__(self, items: list[_BrowseItem], total: int) -> None:
        self.items = items
        self.total = total


class _LibraryBrowser(FakeBrowser):
    def __init__(self) -> None:
        super().__init__()
        self.client = _LibraryClient()

    def _scoped_client(self, force_scoped: bool = False) -> _LibraryClient:
        return self.client

    def get_metadata(self, container: str, index: int, count: int) -> _Page:
        assert container == "libraryplaylist:p.a"
        tracks = [_BrowseItem(t) for t in self.catalog * 30][:250]  # more than one page
        return _Page(tracks[index : index + count], len(tracks))


def test_library_playlists_walks_only_the_library() -> None:
    browser = _LibraryBrowser()
    assert library_playlists(browser) == [
        ("libraryplaylist:p.a", "Abendessen"),
        ("libraryplaylist:p.b", "Zeta"),
    ]
    assert "browse" not in browser.client.opened  # no library hint in id or title
    assert "libraryalbums" not in browser.client.opened


def test_soco_apple_playlists_as_fallback_sources() -> None:
    adapter = SoCoAdapter(
        discover_fn=lambda: {FakeSoCoDevice()},
        browser_factory=lambda dev, acc: _LibraryBrowser(),
        accounts_fn=lambda dev: [_Account()],
    )
    adapter.configure(SpeakerConfig("RINCON_1", ()))
    assert adapter.list_fallback_sources(None) == []
    sources = adapter.list_fallback_sources("3")
    assert [(s.name, s.kind) for s in sources] == [
        ("Abendessen", "apple_playlist"),
        ("Zeta", "apple_playlist"),
    ]
    assert sources[0].source_id == "apple_playlist:3:libraryplaylist:p.a"
    tracks = adapter.fallback_tracks(sources[0].source_id)
    assert len(tracks) == 250 and all(t.account_id == "3" for t in tracks)


def test_library_playlists_skips_folders_apple_cannot_open() -> None:
    from soco.exceptions import MusicServiceException

    class Client(_LibraryClient):
        def get_metadata(self, object_id: str, index: int, count: int) -> dict[str, object]:
            if object_id == "libraryfolder:broken":
                self.opened.append(object_id)
                raise MusicServiceException("SOAP-ENV:Server: There was an error (HTTP 500)")
            page = super().get_metadata(object_id, index, count)
            if object_id == "library":
                broken = {"id": "libraryfolder:broken", "title": "Playlists 2", "itemType": "x"}
                page["items"] = [broken, *page["items"]]  # type: ignore[misc]
            return page

    browser = _LibraryBrowser()
    browser.client = Client()
    assert [title for _, title in library_playlists(browser)] == ["Abendessen", "Zeta"]
    assert "libraryfolder:broken" in browser.client.opened
