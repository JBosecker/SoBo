"""Basis-Playlist: liefert Titel, wenn die Gast-Queue leer ist (Plan 5.1)."""

from __future__ import annotations

import random
from collections.abc import Callable, Collection

from ..sonos.adapter import Track


class FallbackPlaylist:
    def __init__(
        self,
        tracks: list[Track],
        shuffle: bool,
        key_fn: Callable[[Track], str],
        rng: random.Random | None = None,
    ) -> None:
        self._tracks = list(tracks)
        self._shuffle = shuffle
        self._key_fn = key_fn
        self._rng = rng or random.Random()
        self._order: list[Track] = []
        self._refill()

    @property
    def size(self) -> int:
        return len(self._tracks)

    def _refill(self) -> None:
        self._order = list(self._tracks)
        if self._shuffle:
            self._rng.shuffle(self._order)

    def next_track(self, exclude_keys: Collection[str] = ()) -> Track | None:
        """Nächster Titel, der nicht in `exclude_keys` liegt (z. B. läuft gerade)."""
        if not self._tracks:
            return None
        for _ in range(len(self._tracks) * 2):
            if not self._order:
                self._refill()
            track = self._order.pop(0)
            if self._key_fn(track) not in exclude_keys:
                return track
        return None
