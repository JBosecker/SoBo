"""Die führende Queue liegt in SoBo (Plan 5.1). Reine Datenstruktur ohne I/O."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from ..sonos.adapter import Track
from .limits import PlayedEntry
from .models import ItemState, Origin, QueueItem
from .ranking import ranked


class JukeboxQueue:
    def __init__(self, key_fn: Callable[[Track], str]) -> None:
        self._key_fn = key_fn
        self._items: dict[str, QueueItem] = {}

    def __iter__(self) -> Iterator[QueueItem]:
        return iter(self._items.values())

    def __len__(self) -> int:
        return len(self._items)

    def key(self, item: QueueItem) -> str:
        return self._key_fn(item.track)

    def add(self, item: QueueItem) -> None:
        self._items[item.id] = item

    def get(self, item_id: str) -> QueueItem | None:
        return self._items.get(item_id)

    def _first(self, state: ItemState) -> QueueItem | None:
        for item in self._items.values():
            if item.state == state:
                return item
        return None

    @property
    def playing(self) -> QueueItem | None:
        return self._first(ItemState.PLAYING)

    @property
    def next_item(self) -> QueueItem | None:
        return self._first(ItemState.NEXT)

    def waiting(self) -> list[QueueItem]:
        """Wartende Gast-/Admin-Titel in Ranking-Reihenfolge (ohne Fallback)."""
        return ranked(
            i
            for i in self._items.values()
            if i.state == ItemState.QUEUED and i.origin != Origin.FALLBACK
        )

    def best(self) -> QueueItem | None:
        waiting = self.waiting()
        return waiting[0] if waiting else None

    def open_by_key(self, key: str) -> QueueItem | None:
        for item in self._items.values():
            if item.is_open and self.key(item) == key:
                return item
        return None

    def history(self) -> list[PlayedEntry]:
        entries = [
            PlayedEntry(self.key(i), i.track.artist, i.started_at)
            for i in self._items.values()
            if i.started_at is not None
        ]
        entries.sort(key=lambda e: e.at, reverse=True)
        return entries

    def played(self, limit: int) -> list[QueueItem]:
        items = [
            i
            for i in self._items.values()
            if i.state == ItemState.PLAYED and i.started_at is not None
        ]
        items.sort(key=lambda i: i.started_at or i.submitted_at, reverse=True)
        return items[:limit]

    def prune(self, keep_closed: int = 500) -> None:
        """Hält gespielte/entfernte Einträge im Speicher begrenzt (DB behält alles)."""
        closed = [i for i in self._items.values() if not i.is_open]
        if len(closed) <= keep_closed:
            return
        closed.sort(key=lambda i: i.finished_at or i.started_at or i.submitted_at)
        for item in closed[: len(closed) - keep_closed]:
            del self._items[item.id]
