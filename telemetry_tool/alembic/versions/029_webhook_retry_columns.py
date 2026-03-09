"""029 -- Add retry + dead-letter columns to stripe_webhook_log.

Adds: attempt_count, next_retry_at, processed_at, received_at, livemode.
Adds: billing_idempotency table for endpoint-level idempotency.

Revision ID: 029
Revises: 028
Create Date: 2026-03-06
"""
import sqlalchemy as sa

from alembic import op

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # ── 1. stripe_webhook_log: retry + dead-letter columns (idempotent) ─
    _add_column_if_not_exists(conn, "stripe_webhook_log", "attempt_count",
                              "INTEGER DEFAULT 1 NOT NULL")
    _add_column_if_not_exists(conn, "stripe_webhook_log", "next_retry_at",
                              "TIMESTAMPTZ")
    _add_column_if_not_exists(conn, "stripe_webhook_log", "processed_at",
                              "TIMESTAMPTZ")
    _add_column_if_not_exists(conn, "stripe_webhook_log", "received_at",
                              "TIMESTAMPTZ DEFAULT now() NOT NULL")
    _add_column_if_not_exists(conn, "stripe_webhook_log", "livemode",
                              "BOOLEAN DEFAULT true NOT NULL")

    # Index for retry worker: find retryable events efficiently
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_stripe_wh_retry "
        "ON stripe_webhook_log (processing_status, next_retry_at)"
    ))

    # ── 2. billing_idempotency: endpoint-level dedup ────────────────
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS billing_idempotency (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            operation TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT,
            response_status INTEGER,
            response_body TEXT,
            stripe_idempotency_key TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_billing_idemp_user_op_key
                UNIQUE (user_id, operation, idempotency_key)
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_billing_idemp_expires "
        "ON billing_idempotency (expires_at)"
    ))


def _add_column_if_not_exists(conn, table, column, col_type):
    """Add a column only if it doesn't already exist (PostgreSQL)."""
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :table AND column_name = :column"
    ), {"table": table, "column": column})
    if result.fetchone() is None:
        op.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))


def downgrade():
    op.drop_table("billing_idempotency")
    op.drop_index("idx_stripe_wh_retry", table_name="stripe_webhook_log")
    op.drop_column("stripe_webhook_log", "livemode")
    op.drop_column("stripe_webhook_log", "received_at")
    op.drop_column("stripe_webhook_log", "processed_at")
    op.drop_column("stripe_webhook_log", "next_retry_at")
    op.drop_column("stripe_webhook_log", "attempt_count")
