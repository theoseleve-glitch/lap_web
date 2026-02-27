"""Add kart_envelope coaching columns to theoretical_data.

Revision ID: 018
Revises: 017
Create Date: 2026-02-27
"""
from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"


def upgrade():
    op.add_column(
        "theoretical_data",
        sa.Column("corner_coaching_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "theoretical_data",
        sa.Column("delta_map_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "theoretical_data",
        sa.Column("session_scalars_json", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("theoretical_data", "session_scalars_json")
    op.drop_column("theoretical_data", "delta_map_json")
    op.drop_column("theoretical_data", "corner_coaching_json")
