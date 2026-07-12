"""Add source, data_profile, capabilities to sessions (W1.T1.5).

Backfill policy:
  - source          = 'real_life'   (every existing session came from GPS+IMU)
  - data_profile    = '{}'::jsonb   (unknown; profiler will enrich on next re-ingest)
  - capabilities    = '{"channels": ["gps"]}'::jsonb  (safe minimum; GPS always present)

Rollback drops the three columns.

Revision ID: 022
Revises: 021
"""
from alembic import op
import sqlalchemy as sa

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sessions", sa.Column("source", sa.Text(), nullable=True))
    op.add_column(
        "sessions",
        sa.Column("data_profile", sa.dialects.postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("capabilities", sa.dialects.postgresql.JSONB(), nullable=True),
    )

    # Backfill existing rows
    op.execute(
        """
        UPDATE sessions
           SET source = 'real_life'
         WHERE source IS NULL
        """
    )
    op.execute(
        """
        UPDATE sessions
           SET data_profile = '{}'::jsonb
         WHERE data_profile IS NULL
        """
    )
    op.execute(
        """
        UPDATE sessions
           SET capabilities = '{"channels": ["gps"]}'::jsonb
         WHERE capabilities IS NULL
        """
    )

    # Lock in NOT NULL now that backfill is done
    op.alter_column("sessions", "source", nullable=False)
    op.alter_column("sessions", "data_profile", nullable=False)
    op.alter_column("sessions", "capabilities", nullable=False)


def downgrade():
    op.drop_column("sessions", "capabilities")
    op.drop_column("sessions", "data_profile")
    op.drop_column("sessions", "source")
