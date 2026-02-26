"""Alembic env.py -- env-var-driven configuration for PostgreSQL migrations.

The database URL is resolved in order of priority:
  1. TELEMETRY_PG_URL environment variable
  2. sqlalchemy.url in alembic.ini

No SQLAlchemy ORM metadata is used; migrations are written with raw SQL
via ``op.execute()`` and ``op.create_table()`` / ``op.drop_table()``.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Alembic Config object -- provides access to .ini values.
config = context.config

# Set up Python logging from the config file.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url from environment variable when available.
pg_url = os.environ.get("TELEMETRY_PG_URL")
if pg_url:
    config.set_main_option("sqlalchemy.url", pg_url)

# No SQLAlchemy metadata -- we use raw DDL in migrations.
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL script output without connecting to the database.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Creates an Engine and associates a connection with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
