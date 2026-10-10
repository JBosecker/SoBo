"""Ranking with upvotes only (plan 5.2): pinned DESC, votes DESC, reached_at ASC.

On a tie the item that reached its vote count first comes first: a song that got its
second vote at 20:02 stays ahead of one that only got its second vote at 20:05, even if
the latter was requested earlier.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from .models import QueueItem


def rank_key(item: QueueItem) -> tuple[bool, int, datetime, str]:
    # `id` as the final tie-breaker makes the order fully deterministic.
    return (not item.pinned, -item.votes, item.reached_at, item.id)


def ranked(items: Iterable[QueueItem]) -> list[QueueItem]:
    return sorted(items, key=rank_key)
