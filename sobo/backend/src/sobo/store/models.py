"""SQLite-Tabellen (Plan 7)."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class SettingsRow(SQLModel, table=True):
    __tablename__ = "settings"

    key: str = Field(primary_key=True)
    value: str
    version: int = 1
    updated_at: datetime


class GuestRow(SQLModel, table=True):
    __tablename__ = "guest"

    id: str = Field(primary_key=True)
    session_token_hash: str = Field(index=True, unique=True)
    nickname: str
    created_at: datetime
    last_seen: datetime
    blocked: bool = False


class QueueItemRow(SQLModel, table=True):
    __tablename__ = "queue_item"

    id: str = Field(primary_key=True)
    service_item_id: str
    account_id: str = ""
    title: str
    artist: str = ""
    album: str = ""
    art_url: str = ""
    duration: int | None = None
    explicit: bool | None = None
    uri: str | None = None
    meta: str | None = None
    origin: str
    submitted_by: str | None = Field(default=None, index=True)
    submitted_at: datetime
    state: str = Field(index=True)
    pinned: bool = False
    started_at: datetime | None = Field(default=None, index=True)
    finished_at: datetime | None = None
    removed_reason: str | None = None


class VoteRow(SQLModel, table=True):
    __tablename__ = "vote"

    guest_id: str = Field(primary_key=True)
    queue_item_id: str = Field(primary_key=True, index=True)
    created_at: datetime = Field(index=True)
    counts: bool = True


class AuditRow(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: int | None = Field(default=None, primary_key=True)
    at: datetime = Field(index=True)
    actor: str
    action: str
    detail: str = ""
