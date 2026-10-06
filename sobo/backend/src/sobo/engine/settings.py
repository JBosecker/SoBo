"""Jukebox settings maintained by the admin in the ingress UI (plan 4.3)."""

from __future__ import annotations

from datetime import time

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class SpeakerSettings(_Model):
    coordinator_uid: str | None = None
    members: list[str] = Field(default_factory=list)
    start_volume: int | None = Field(default=None, ge=0, le=100)
    max_volume: int = Field(default=60, ge=0, le=100)


class FallbackSettings(_Model):
    source_id: str | None = None
    shuffle: bool = True
    # How many base playlist songs the queue shows after the requests; 0 shows all.
    preview_count: int = Field(default=0, ge=0, le=500)


class VoteSettings(_Model):
    votes_per_window: int = Field(default=5, ge=1, le=100)
    window_minutes: int = Field(default=30, ge=1, le=24 * 60)
    suggestion_costs_vote: bool = True
    # The next song is fixed (and handed to Sonos) only this long before the current
    # one ends; until then votes still decide what comes next.
    lock_next_seconds: int = Field(default=30, ge=5, le=600)


class LimitSettings(_Model):
    suggestions_per_window: int = Field(default=3, ge=0, le=100)
    suggestion_window_minutes: int = Field(default=30, ge=1, le=24 * 60)
    max_track_seconds: int = Field(default=600, ge=30, le=3 * 3600)
    track_cooldown_minutes: int = Field(default=120, ge=0, le=24 * 60)
    artist_cooldown_minutes: int = Field(default=0, ge=0, le=24 * 60)
    explicit_filter: bool = False
    blocklist: list[str] = Field(default_factory=list, max_length=500)

    @field_validator("blocklist")
    @classmethod
    def _clean_blocklist(cls, value: list[str]) -> list[str]:
        cleaned = []
        for entry in value:
            entry = entry.strip()
            if entry:
                cleaned.append(entry[:200])
        return cleaned


class GuestAccessSettings(_Model):
    max_active_guests: int = Field(default=100, ge=1, le=1000)
    session_hours: int = Field(default=12, ge=1, le=72)
    presence_code: str | None = Field(default=None, pattern=r"^[0-9]{4,8}$")
    show_covers: bool = True
    long_poll_timeout: int = Field(default=20, ge=5, le=60)
    max_open_long_polls: int = Field(default=150, ge=1, le=2000)
    joins_per_minute: int = Field(default=20, ge=1, le=600)
    unregister_when_inactive: bool = False


class ScheduleSettings(_Model):
    enabled: bool = False
    start: time = time(18, 0)
    end: time = time(2, 0)

    def contains(self, moment: time) -> bool:
        if not self.enabled:
            return True
        if self.start <= self.end:
            return self.start <= moment < self.end
        # time window across midnight
        return moment >= self.start or moment < self.end


class JukeboxSettings(_Model):
    active: bool = False
    schedule: ScheduleSettings = Field(default_factory=ScheduleSettings)
    account_id: str | None = None
    speaker: SpeakerSettings = Field(default_factory=SpeakerSettings)
    fallback: FallbackSettings = Field(default_factory=FallbackSettings)
    votes: VoteSettings = Field(default_factory=VoteSettings)
    limits: LimitSettings = Field(default_factory=LimitSettings)
    guest_access: GuestAccessSettings = Field(default_factory=GuestAccessSettings)
    # time zone for the schedule window
    timezone: str = "Europe/Berlin"
