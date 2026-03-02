"""Add channel_inventory column to sessions table.

Revision ID: 017
Revises: 016
"""
from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("channel_inventory", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "channel_inventory")
