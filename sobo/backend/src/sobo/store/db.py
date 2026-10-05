"""SQLite-Repository der Engine (write-through), Migrationen per Alembic."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine, delete, event
from sqlmodel import Session, col, create_engine, or_, select

from ..clock import Clock, SystemClock
from ..engine.models import AuditEntry, Guest, ItemState, Origin, QueueItem, Vote
from ..engine.persistence import Snapshot
from ..engine.settings import JukeboxSettings
from ..sonos.adapter import Track
from .models import AuditRow, GuestRow, QueueItemRow, SettingsRow, VoteRow

_LOG = logging.getLogger(__name__)

MIGRATIONS = Path(__file__).parent / "migrations"
SETTINGS_KEY = "jukebox"
# Wie weit zurück beim Start geladen wird (Sperrzeiten, Vote-Budgets).
HISTORY_WINDOW = timedelta(hours=24)

_OPEN_STATES = (ItemState.QUEUED.value, ItemState.NEXT.value, ItemState.PLAYING.value)


def _utc(value: datetime) -> datetime:
    """SQLite speichert ohne Zeitzone; alles ist UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _opt_utc(value: datetime | None) -> datetime | None:
    return _utc(value) if value is not None else None


def _naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def _opt_naive(value: datetime | None) -> datetime | None:
    return _naive(value) if value is not None else None


def make_engine(url: str) -> Engine:
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    return engine


def migrate(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")


class SqlRepository:
    def __init__(self, url: str, clock: Clock | None = None, run_migrations: bool = True) -> None:
        if run_migrations:
            migrate(url)
        self._engine = make_engine(url)
        self._clock = clock or SystemClock()

    @classmethod
    def for_path(cls, path: Path, clock: Clock | None = None) -> SqlRepository:
        path.parent.mkdir(parents=True, exist_ok=True)
        return cls(f"sqlite:///{path}", clock)

    # ------------------------------------------------------------------ Laden

    def load(self) -> Snapshot:
        cutoff = _naive(self._clock.now() - HISTORY_WINDOW)
        with Session(self._engine) as session:
            settings_row = session.get(SettingsRow, SETTINGS_KEY)
            settings = None
            if settings_row is not None:
                try:
                    settings = JukeboxSettings.model_validate_json(settings_row.value)
                except ValueError:
                    _LOG.exception("Gespeicherte Einstellungen ungültig – Standardwerte")
            guests = [self._guest(r) for r in session.exec(select(GuestRow)).all()]
            item_rows = session.exec(
                select(QueueItemRow).where(
                    or_(
                        col(QueueItemRow.state).in_(_OPEN_STATES),
                        col(QueueItemRow.started_at) >= cutoff,
                        col(QueueItemRow.submitted_at) >= cutoff,
                    )
                )
            ).all()
            items = [self._item(r) for r in item_rows]
            item_ids = {i.id for i in items}
            vote_rows = session.exec(
                select(VoteRow).where(
                    or_(col(VoteRow.created_at) >= cutoff, col(VoteRow.queue_item_id).in_(item_ids))
                )
            ).all()
            votes = [
                Vote(r.guest_id, r.queue_item_id, _utc(r.created_at), r.counts) for r in vote_rows
            ]
        return Snapshot(settings=settings, guests=guests, items=items, votes=votes)

    @staticmethod
    def _guest(row: GuestRow) -> Guest:
        return Guest(
            id=row.id,
            token_hash=row.session_token_hash,
            nickname=row.nickname,
            created_at=_utc(row.created_at),
            last_seen=_utc(row.last_seen),
            blocked=row.blocked,
        )

    @staticmethod
    def _item(row: QueueItemRow) -> QueueItem:
        track = Track(
            item_id=row.service_item_id,
            title=row.title,
            artist=row.artist,
            album=row.album,
            art_url=row.art_url,
            duration=row.duration,
            explicit=row.explicit,
            account_id=row.account_id,
            uri=row.uri,
            meta=row.meta,
        )
        return QueueItem(
            id=row.id,
            track=track,
            origin=Origin(row.origin),
            submitted_at=_utc(row.submitted_at),
            submitted_by=row.submitted_by,
            state=ItemState(row.state),
            pinned=row.pinned,
            started_at=_opt_utc(row.started_at),
            finished_at=_opt_utc(row.finished_at),
            removed_reason=row.removed_reason,
        )

    # ------------------------------------------------------------------ Schreiben

    def save_settings(self, settings: JukeboxSettings) -> None:
        with Session(self._engine) as session:
            row = session.get(SettingsRow, SETTINGS_KEY)
            now = _naive(self._clock.now())
            value = settings.model_dump_json()
            if row is None:
                row = SettingsRow(key=SETTINGS_KEY, value=value, version=1, updated_at=now)
            else:
                row.value = value
                row.version += 1
                row.updated_at = now
            session.add(row)
            session.commit()

    def save_guest(self, guest: Guest) -> None:
        with Session(self._engine) as session:
            session.merge(
                GuestRow(
                    id=guest.id,
                    session_token_hash=guest.token_hash,
                    nickname=guest.nickname,
                    created_at=_naive(guest.created_at),
                    last_seen=_naive(guest.last_seen),
                    blocked=guest.blocked,
                )
            )
            session.commit()

    def delete_all_guests(self) -> None:
        with Session(self._engine) as session:
            session.execute(delete(GuestRow))
            session.commit()

    def save_item(self, item: QueueItem) -> None:
        track = item.track
        with Session(self._engine) as session:
            session.merge(
                QueueItemRow(
                    id=item.id,
                    service_item_id=track.item_id,
                    account_id=track.account_id,
                    title=track.title,
                    artist=track.artist,
                    album=track.album,
                    art_url=track.art_url,
                    duration=track.duration,
                    explicit=track.explicit,
                    uri=track.uri,
                    meta=track.meta,
                    origin=item.origin.value,
                    submitted_by=item.submitted_by,
                    submitted_at=_naive(item.submitted_at),
                    state=item.state.value,
                    pinned=item.pinned,
                    started_at=_opt_naive(item.started_at),
                    finished_at=_opt_naive(item.finished_at),
                    removed_reason=item.removed_reason,
                )
            )
            session.commit()

    def save_vote(self, vote: Vote) -> None:
        with Session(self._engine) as session:
            session.merge(
                VoteRow(
                    guest_id=vote.guest_id,
                    queue_item_id=vote.item_id,
                    created_at=_naive(vote.created_at),
                    counts=vote.counts,
                )
            )
            session.commit()

    def add_audit(self, entry: AuditEntry) -> None:
        with Session(self._engine) as session:
            session.add(
                AuditRow(
                    at=_naive(entry.at), actor=entry.actor, action=entry.action, detail=entry.detail
                )
            )
            session.commit()

    def recent_audit(self, limit: int) -> list[AuditEntry]:
        with Session(self._engine) as session:
            rows = session.exec(
                select(AuditRow).order_by(col(AuditRow.id).desc()).limit(limit)
            ).all()
            return [AuditEntry(_utc(r.at), r.actor, r.action, r.detail) for r in rows]

    def purge_history(self, older_than: timedelta) -> None:
        """Aufbewahrungsfrist (Plan 6, Datenschutz): alte Einträge löschen."""
        cutoff = _naive(self._clock.now() - older_than)
        closed_and_old = (
            col(QueueItemRow.state).not_in(_OPEN_STATES),
            col(QueueItemRow.submitted_at) < cutoff,
        )
        with Session(self._engine) as session:
            old_items = select(QueueItemRow.id).where(*closed_and_old)
            session.execute(delete(VoteRow).where(col(VoteRow.queue_item_id).in_(old_items)))
            session.execute(delete(QueueItemRow).where(*closed_and_old))
            session.execute(delete(AuditRow).where(col(AuditRow.at) < cutoff))
            session.commit()

    def dispose(self) -> None:
        self._engine.dispose()
