"""Add Stripe webhook idempotency events table.

Revision ID: 019
Revises: 018
Create Date: 2026-02-27
"""
from alembic import op
import sqlalchemy as sa

revision = "019"
down_revision = "018"


def upgrade():
    op.create_table(
        "stripe_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_stripe_events_event_id"),
    )
    op.create_index("idx_stripe_events_event_id", "stripe_events", ["event_id"], unique=True)


def downgrade():
    op.drop_index("idx_stripe_events_event_id", table_name="stripe_events")
    op.drop_table("stripe_events")
