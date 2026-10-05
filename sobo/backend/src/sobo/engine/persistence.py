"""Persistence interface of the engine.

The engine keeps its state in memory and writes changes through immediately
(write-through). On start it loads the last state. `MemoryRepository` is for
tests; the SQLite implementation lives in `sobo.store`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .models import AuditEntry, Guest, QueueItem, Vote
from .settings import JukeboxSettings


@dataclass(slots=True)
class Snapshot:
    settings: JukeboxSettings | None = None
    guests: list[Guest] = field(default_factory=list)
    items: list[QueueItem] = field(default_factory=list)
    votes: list[Vote] = field(default_factory=list)


class Repository(Protocol):
    def load(self) -> Snapshot: ...

    def save_settings(self, settings: JukeboxSettings) -> None: ...

    def save_guest(self, guest: Guest) -> None: ...

    def delete_all_guests(self) -> None: ...

    def save_item(self, item: QueueItem) -> None: ...

    def save_vote(self, vote: Vote) -> None: ...

    def add_audit(self, entry: AuditEntry) -> None: ...

    def recent_audit(self, limit: int) -> list[AuditEntry]: ...


class MemoryRepository:
    def __init__(self) -> None:
        self.settings: JukeboxSettings | None = None
        self.guests: dict[str, Guest] = {}
        self.items: dict[str, QueueItem] = {}
        self.votes: dict[tuple[str, str], Vote] = {}
        self.audit: list[AuditEntry] = []

    def load(self) -> Snapshot:
        return Snapshot(
            settings=self.settings,
            guests=list(self.guests.values()),
            items=list(self.items.values()),
            votes=list(self.votes.values()),
        )

    def save_settings(self, settings: JukeboxSettings) -> None:
        self.settings = settings.model_copy(deep=True)

    def save_guest(self, guest: Guest) -> None:
        self.guests[guest.id] = guest

    def delete_all_guests(self) -> None:
        self.guests.clear()

    def save_item(self, item: QueueItem) -> None:
        self.items[item.id] = item

    def save_vote(self, vote: Vote) -> None:
        self.votes[(vote.guest_id, vote.item_id)] = vote

    def add_audit(self, entry: AuditEntry) -> None:
        self.audit.append(entry)

    def recent_audit(self, limit: int) -> list[AuditEntry]:
        return list(reversed(self.audit[-limit:]))
