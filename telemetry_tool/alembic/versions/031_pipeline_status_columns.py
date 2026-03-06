"""031 -- Add pipeline versioning columns to sessions.

Adds pipeline_version_hash (deterministic structural hash) and
model_version (ML model identifier) columns to the sessions table
so analysis provenance is persisted alongside results.

Existing sessions get 'unknown' as backfill values.

Revision ID: 031
Revises: 030
Create Date: 2026-03-06
"""
from alembic import op
import sqlalchemy as sa

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "pipeline_version_hash",
            sa.Text(),
            nullable=True,
            server_default="unknown",
            comment="Deterministic pipeline version string (e.g. v2-a3f8b2c1)",
        ),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "model_version",
            sa.Text(),
            nullable=True,
            server_default="none",
            comment="ML model version identifier at analysis time",
        ),
    )
    # Backfill existing sessions
    op.execute(
        "UPDATE sessions SET pipeline_version_hash = 'unknown' "
        "WHERE pipeline_version_hash IS NULL"
    )
    op.execute(
        "UPDATE sessions SET model_version = 'none' "
        "WHERE model_version IS NULL"
    )


def downgrade() -> None:
    op.drop_column("sessions", "model_version")
    op.drop_column("sessions", "pipeline_version_hash")
