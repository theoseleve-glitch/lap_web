"""Add Stripe billing columns to users table.

Revision ID: 016
Revises: 015
Create Date: 2026-02-27
"""
import sqlalchemy as sa

from alembic import op

revision = "016"
down_revision = "015"


def upgrade():
    op.add_column("users", sa.Column("stripe_customer_id", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("stripe_subscription_id", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("billing_plan", sa.Text(), server_default="free", nullable=False))
    op.create_index("idx_users_stripe_customer_id", "users", ["stripe_customer_id"], unique=True)


def downgrade():
    op.drop_index("idx_users_stripe_customer_id", table_name="users")
    op.drop_column("users", "billing_plan")
    op.drop_column("users", "stripe_subscription_id")
    op.drop_column("users", "stripe_customer_id")
