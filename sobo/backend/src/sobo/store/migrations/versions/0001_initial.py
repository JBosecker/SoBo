"""Initiales Schema (Plan 7)

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "guest",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("session_token_hash", sa.String(), nullable=False),
        sa.Column("nickname", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen", sa.DateTime(), nullable=False),
        sa.Column("blocked", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_guest_session_token_hash", "guest", ["session_token_hash"], unique=True)
    op.create_table(
        "queue_item",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("service_item_id", sa.String(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("artist", sa.String(), nullable=False),
        sa.Column("album", sa.String(), nullable=False),
        sa.Column("art_url", sa.String(), nullable=False),
        sa.Column("duration", sa.Integer(), nullable=True),
        sa.Column("explicit", sa.Boolean(), nullable=True),
        sa.Column("uri", sa.String(), nullable=True),
        sa.Column("meta", sa.String(), nullable=True),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("submitted_by", sa.String(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("removed_reason", sa.String(), nullable=True),
    )
    op.create_index("ix_queue_item_submitted_by", "queue_item", ["submitted_by"])
    op.create_index("ix_queue_item_state", "queue_item", ["state"])
    op.create_index("ix_queue_item_started_at", "queue_item", ["started_at"])
    op.create_table(
        "vote",
        sa.Column("guest_id", sa.String(), primary_key=True),
        sa.Column("queue_item_id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("counts", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_vote_queue_item_id", "vote", ["queue_item_id"])
    op.create_index("ix_vote_created_at", "vote", ["created_at"])
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("detail", sa.String(), nullable=False),
    )
    op.create_index("ix_audit_log_at", "audit_log", ["at"])


def downgrade() -> None:
    for table in ("audit_log", "vote", "queue_item", "guest", "settings"):
        op.drop_table(table)
