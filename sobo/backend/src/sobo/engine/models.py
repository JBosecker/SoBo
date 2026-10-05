"""Domain model of the jukebox (plan 5, 7)."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from ..sonos.adapter import Track


class ItemState(StrEnum):
    QUEUED = "queued"
    NEXT = "next"
    PLAYING = "playing"
    PLAYED = "played"
    REMOVED = "removed"


class Origin(StrEnum):
    GUEST = "guest"
    FALLBACK = "fallback"
    ADMIN = "admin"


def new_id() -> str:
    return secrets.token_hex(8)


@dataclass(slots=True)
class Guest:
    id: str
    token_hash: str
    nickname: str
    created_at: datetime
    last_seen: datetime
    blocked: bool = False


@dataclass(slots=True)
class Vote:
    guest_id: str
    item_id: str
    created_at: datetime
    # Counts against the vote budget? (free suggestion → False)
    counts: bool = True


@dataclass(slots=True)
class QueueItem:
    id: str
    track: Track
    origin: Origin
    submitted_at: datetime
    submitted_by: str | None = None
    state: ItemState = ItemState.QUEUED
    pinned: bool = False
    voters: set[str] = field(default_factory=set)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    removed_reason: str | None = None

    @property
    def votes(self) -> int:
        return len(self.voters)

    @property
    def is_open(self) -> bool:
        """Not yet played/removed."""
        return self.state in (ItemState.QUEUED, ItemState.NEXT, ItemState.PLAYING)


@dataclass(slots=True)
class AuditEntry:
    at: datetime
    actor: str
    action: str
    detail: str = ""
