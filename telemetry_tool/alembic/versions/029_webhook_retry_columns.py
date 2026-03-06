"""029 -- Add retry + dead-letter columns to stripe_webhook_log.

Adds: attempt_count, next_retry_at, processed_at, received_at, livemode.
Adds: billing_idempotency table for endpoint-level idempotency.

Revision ID: 029
Revises: 028
Create Date: 2026-03-06
"""
from alembic import op
import sqlalchemy as sa

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. stripe_webhook_log: retry + dead-letter columns ──────────
    op.add_column(
        "stripe_webhook_log",
        sa.Column("attempt_count", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "stripe_webhook_log",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "stripe_webhook_log",
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "stripe_webhook_log",
        sa.Column("received_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.add_column(
        "stripe_webhook_log",
        sa.Column("livemode", sa.Boolean(), server_default="true", nullable=False),
    )

    # Index for retry worker: find retryable events efficiently
    op.create_index(
        "idx_stripe_wh_retry",
        "stripe_webhook_log",
        ["processing_status", "next_retry_at"],
    )

    # ── 2. billing_idempotency: endpoint-level dedup ────────────────
    op.create_table(
        "billing_idempotency",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("stripe_idempotency_key", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "operation", "idempotency_key",
                            name="uq_billing_idemp_user_op_key"),
    )
    op.create_index(
        "idx_billing_idemp_expires",
        "billing_idempotency",
        ["expires_at"],
    )


def downgrade():
    op.drop_table("billing_idempotency")
    op.drop_index("idx_stripe_wh_retry", table_name="stripe_webhook_log")
    op.drop_column("stripe_webhook_log", "livemode")
    op.drop_column("stripe_webhook_log", "received_at")
    op.drop_column("stripe_webhook_log", "processed_at")
    op.drop_column("stripe_webhook_log", "next_retry_at")
    op.drop_column("stripe_webhook_log", "attempt_count")
