"""033 -- Add CHECK constraint on users.subscription_status.

Ensures subscription_status only contains valid state machine values.
Idempotent: checks if constraint exists before creating.

Revision ID: 033
Revises: 032
Create Date: 2026-03-08
"""
from alembic import op
from sqlalchemy import text

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None

_VALID_STATES = (
    "free", "trialing", "active", "past_due",
    "unpaid", "canceled", "paused", "expired",
)

_CONSTRAINT_NAME = "chk_subscription_status"


def upgrade() -> None:
    conn = op.get_bind()

    # Check if constraint already exists
    result = conn.execute(text(
        "SELECT 1 FROM information_schema.table_constraints "
        "WHERE constraint_name = 'chk_subscription_status' "
        "AND table_name = 'users'"
    )).fetchone()

    if result is None:
        values_sql = ", ".join(f"'{s}'" for s in _VALID_STATES)
        op.execute(text(
            f"ALTER TABLE users ADD CONSTRAINT {_CONSTRAINT_NAME} "
            f"CHECK (subscription_status IN ({values_sql}))"
        ))


def downgrade() -> None:
    op.execute(text(f"ALTER TABLE users DROP CONSTRAINT IF EXISTS {_CONSTRAINT_NAME}"))
