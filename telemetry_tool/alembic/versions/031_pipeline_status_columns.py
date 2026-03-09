"""031 -- Add pipeline versioning columns to sessions.

Adds pipeline_version_hash (deterministic structural hash) and
model_version (ML model identifier) columns to the sessions table
so analysis provenance is persisted alongside results.

Existing sessions get 'unknown' as backfill values.

Revision ID: 031
Revises: 030
Create Date: 2026-03-06
"""
import sqlalchemy as sa

from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    _add_col(conn, "sessions", "pipeline_version_hash", "TEXT DEFAULT 'unknown'")
    _add_col(conn, "sessions", "model_version", "TEXT DEFAULT 'none'")

    # Backfill existing sessions
    op.execute(sa.text(
        "UPDATE sessions SET pipeline_version_hash = 'unknown' "
        "WHERE pipeline_version_hash IS NULL"
    ))
    op.execute(sa.text(
        "UPDATE sessions SET model_version = 'none' "
        "WHERE model_version IS NULL"
    ))


def _add_col(conn, table, column, col_type):
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :table AND column_name = :column"
    ), {"table": table, "column": column})
    if result.fetchone() is None:
        op.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))


def downgrade() -> None:
    op.drop_column("sessions", "model_version")
    op.drop_column("sessions", "pipeline_version_hash")
