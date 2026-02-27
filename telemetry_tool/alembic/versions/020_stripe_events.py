"""Add stripe_events table for webhook deduplication.

Revision ID: 020
Revises: 019
Create Date: 2026-02-27
"""
from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"


def upgrade():
    op.create_table(
        "stripe_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("stripe_event_id", sa.Text, unique=True, nullable=False),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("processed_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("payload_hash", sa.Text, nullable=True),
    )
    op.create_index(
        "idx_stripe_events_event_id",
        "stripe_events",
        ["stripe_event_id"],
        unique=True,
    )
    op.create_index(
        "idx_stripe_events_type",
        "stripe_events",
        ["event_type"],
    )


def downgrade():
    op.drop_index("idx_stripe_events_type", table_name="stripe_events")
    op.drop_index("idx_stripe_events_event_id", table_name="stripe_events")
    op.drop_table("stripe_events")
