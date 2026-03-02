"""Add channel metadata columns to sessions table.

Stores data_tier (1-5), available_channels JSON list, source format name,
and source metadata dict from the adapter registry.

Revision ID: 018
Revises: 017
"""
from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("data_tier", sa.Integer(), server_default="1"))
    op.add_column("sessions", sa.Column("available_channels", sa.Text(), nullable=True))
    op.add_column("sessions", sa.Column("source_format", sa.String(32), server_default="'racechrono'"))
    op.add_column("sessions", sa.Column("source_metadata", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "source_metadata")
    op.drop_column("sessions", "source_format")
    op.drop_column("sessions", "available_channels")
    op.drop_column("sessions", "data_tier")
