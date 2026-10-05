"""Ranking with upvotes only (plan 5.2): pinned DESC, votes DESC, submitted_at ASC."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from .models import QueueItem


def rank_key(item: QueueItem) -> tuple[bool, int, datetime, str]:
    # `id` as the final tie-breaker makes the order fully deterministic.
    return (not item.pinned, -item.votes, item.submitted_at, item.id)


def ranked(items: Iterable[QueueItem]) -> list[QueueItem]:
    return sorted(items, key=rank_key)
