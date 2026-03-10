"""038 -- Add race_sleep_windows table for driver sleep management in 12h+ races.

Revision ID: 038
Revises: 037
Create Date: 2026-03-10
"""

import sqlalchemy as sa
from alembic import op

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "race_sleep_windows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "race_id",
            sa.Integer(),
            sa.ForeignKey("race_configs.race_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "driver_id",
            sa.Integer(),
            sa.ForeignKey("race_drivers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_s", sa.Integer(), nullable=False),
        sa.Column("end_s", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("actual_wake_s", sa.Integer(), nullable=True),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default="planned"
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("race_sleep_windows")
