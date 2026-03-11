"""042 -- Add channel/adapter columns to sessions table.

Adds channel_inventory, data_tier, available_channels, source_format,
and source_metadata columns that the pipeline populates during finalize
but were missing from the PG schema (already present in SQLite via
db/schema.py).

Revision ID: 042
Revises: 041
Create Date: 2026-03-11
"""
import sqlalchemy as sa

from alembic import op

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    _add_col(conn, "sessions", "channel_inventory", "TEXT")
    _add_col(conn, "sessions", "data_tier", "INTEGER DEFAULT 1")
    _add_col(conn, "sessions", "available_channels", "TEXT DEFAULT '[]'")
    _add_col(conn, "sessions", "source_format", "TEXT DEFAULT 'racechrono'")
    _add_col(conn, "sessions", "source_metadata", "TEXT DEFAULT '{}'")


def _add_col(conn, table, column, col_type):
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :table AND column_name = :column"
    ), {"table": table, "column": column})
    if result.fetchone() is None:
        op.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))


def downgrade() -> None:
    op.drop_column("sessions", "source_metadata")
    op.drop_column("sessions", "source_format")
    op.drop_column("sessions", "available_channels")
    op.drop_column("sessions", "data_tier")
    op.drop_column("sessions", "channel_inventory")
