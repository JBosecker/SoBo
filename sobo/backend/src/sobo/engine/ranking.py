"""Ranking nur mit Upvotes (Plan 5.2): pinned DESC, votes DESC, submitted_at ASC."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from .models import QueueItem


def rank_key(item: QueueItem) -> tuple[bool, int, datetime, str]:
    # `id` als letzter Tie-Breaker macht die Reihenfolge vollständig deterministisch.
    return (not item.pinned, -item.votes, item.submitted_at, item.id)


def ranked(items: Iterable[QueueItem]) -> list[QueueItem]:
    return sorted(items, key=rank_key)
