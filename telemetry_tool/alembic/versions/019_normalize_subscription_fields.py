"""Normalize Stripe subscription fields on users.

Revision ID: 019
Revises: 018
"""

from alembic import op
import sqlalchemy as sa

revision = "019"
down_revision = "018"


def upgrade() -> None:
    op.add_column("users", sa.Column("plan_tier", sa.Text(), server_default="free", nullable=False))
    op.add_column("users", sa.Column("billing_status", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("stripe_price_id", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("period_end", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("cancel_at", sa.DateTime(), nullable=True))

    op.execute(
        """
        UPDATE users
        SET
            billing_status = CASE
                WHEN billing_plan IN (
                    'trialing', 'active', 'past_due', 'canceled',
                    'unpaid', 'incomplete', 'incomplete_expired'
                ) THEN billing_plan
                WHEN billing_plan IS NULL OR billing_plan = '' OR billing_plan = 'free' THEN 'inactive'
                ELSE 'active'
            END,
            plan_tier = CASE
                WHEN billing_plan IN ('racer', 'world_class', 'paid') THEN billing_plan
                WHEN billing_plan IN ('trialing', 'active', 'past_due') THEN 'paid'
                ELSE 'free'
            END
        """
    )


def downgrade() -> None:
    op.drop_column("users", "cancel_at")
    op.drop_column("users", "period_end")
    op.drop_column("users", "stripe_price_id")
    op.drop_column("users", "billing_status")
    op.drop_column("users", "plan_tier")
