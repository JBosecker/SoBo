"""Server-side search cache: guests only see opaque IDs, never URIs (plan 6)."""

from __future__ import annotations

import secrets
from collections import OrderedDict
from datetime import datetime, timedelta

from ..clock import Clock
from ..sonos.adapter import Track


class SearchCache:
    def __init__(
        self, clock: Clock, ttl: timedelta = timedelta(minutes=30), max_entries: int = 5000
    ):
        self._clock = clock
        self._ttl = ttl
        self._max = max_entries
        self._entries: OrderedDict[str, tuple[Track, datetime]] = OrderedDict()

    def put(self, track: Track) -> str:
        self._prune()
        opaque = secrets.token_urlsafe(12)
        self._entries[opaque] = (track, self._clock.now() + self._ttl)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)
        return opaque

    def get(self, opaque: str) -> Track | None:
        entry = self._entries.get(opaque)
        if entry is None:
            return None
        track, expires = entry
        if expires <= self._clock.now():
            del self._entries[opaque]
            return None
        return track

    def clear(self) -> None:
        self._entries.clear()

    def _prune(self) -> None:
        now = self._clock.now()
        while self._entries:
            opaque, (_, expires) = next(iter(self._entries.items()))
            if expires > now:
                break
            del self._entries[opaque]

    def __len__(self) -> int:
        return len(self._entries)
