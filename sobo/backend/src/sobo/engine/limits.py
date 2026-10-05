"""Rules for votes and suggestions (plan 5.3)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..sonos.adapter import Track
from .settings import LimitSettings


class RuleViolation(Exception):
    """A guest action breaks a rule. `code` is sent to the guest page."""

    def __init__(self, code: str, retry_after: float | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class BudgetState:
    remaining: int
    # seconds until a vote/suggestion becomes available again (None = nothing used)
    next_free_in: float | None


def sliding_budget(
    events: Iterable[datetime], limit: int, window: timedelta, now: datetime
) -> BudgetState:
    """Sliding window: counts events in (now - window, now]."""
    recent = sorted(e for e in events if e > now - window)
    remaining = max(0, limit - len(recent))
    next_free_in: float | None = None
    if recent:
        # A slot frees up as soon as the oldest event leaves the window.
        next_free_in = max(0.0, (recent[0] + window - now).total_seconds())
    return BudgetState(remaining=remaining, next_free_in=next_free_in)


@dataclass(frozen=True, slots=True)
class PlayedEntry:
    key: str
    artist: str
    at: datetime


def _matches_blocklist(track: Track, blocklist: Sequence[str]) -> bool:
    haystack = f"{track.title}\n{track.artist}\n{track.album}".casefold()
    for entry in blocklist:
        needle = entry.casefold()
        if needle == track.item_id.casefold() or needle in haystack:
            return True
    return False


def check_track(
    track: Track,
    key: str,
    limits: LimitSettings,
    history: Sequence[PlayedEntry],
    now: datetime,
) -> None:
    """Check the content rules for a suggestion; raises `RuleViolation`."""
    if track.duration is not None and track.duration > limits.max_track_seconds:
        raise RuleViolation("too_long")
    if limits.explicit_filter and track.explicit is True:
        raise RuleViolation("explicit")
    if _matches_blocklist(track, limits.blocklist):
        raise RuleViolation("blocked_content")
    if limits.track_cooldown_minutes:
        cutoff = now - timedelta(minutes=limits.track_cooldown_minutes)
        for entry in history:
            if entry.key == key and entry.at > cutoff:
                retry = (entry.at - cutoff).total_seconds()
                raise RuleViolation("recently_played", retry_after=retry)
    if limits.artist_cooldown_minutes and track.artist:
        cutoff = now - timedelta(minutes=limits.artist_cooldown_minutes)
        artist = track.artist.casefold()
        for entry in history:
            if entry.artist.casefold() == artist and entry.at > cutoff:
                retry = (entry.at - cutoff).total_seconds()
                raise RuleViolation("artist_cooldown", retry_after=retry)
