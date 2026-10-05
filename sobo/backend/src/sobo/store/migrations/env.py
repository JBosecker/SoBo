"""Alembic-Umgebung. Wird programmatisch aus `sobo.store.db.migrate()` gestartet."""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

from sobo.store import models  # noqa: F401  – registriert die Tabellen

config = context.config
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # Batch-Modus: SQLite kann ALTER TABLE nur eingeschränkt.
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
