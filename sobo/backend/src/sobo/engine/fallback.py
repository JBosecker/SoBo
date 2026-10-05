"""Base playlist: provides tracks while the guest queue is empty (plan 5.1)."""

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

    def _ensure(self, count: int) -> None:
        """Plan further rounds ahead so a preview matches what plays later."""
        while self._tracks and len(self._order) < count:
            round_ = list(self._tracks)
            if self._shuffle:
                self._rng.shuffle(round_)
            self._order.extend(round_)

    def upcoming(self, count: int, exclude_keys: Collection[str] = ()) -> list[Track]:
        """The next `count` tracks `next_track` will hand out (without consuming them)."""
        if not self._tracks or count <= 0:
            return []
        self._ensure(count + len(exclude_keys))
        result: list[Track] = []
        seen: set[str] = set()
        for track in self._order:
            key = self._key_fn(track)
            if key in exclude_keys or key in seen:
                continue
            seen.add(key)
            result.append(track)
            if len(result) == count:
                break
        return result

    def next_track(self, exclude_keys: Collection[str] = ()) -> Track | None:
        """Next track that is not in `exclude_keys` (e.g. currently playing)."""
        if not self._tracks:
            return None
        for _ in range(len(self._tracks) * 2):
            if not self._order:
                self._refill()
            track = self._order.pop(0)
            if self._key_fn(track) not in exclude_keys:
                return track
        return None
