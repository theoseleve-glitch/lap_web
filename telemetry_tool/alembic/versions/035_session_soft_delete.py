"""035 -- Add soft-delete and favorite support for sessions.

Adds ``deleted_at`` column (soft delete) and ``is_favorite`` column
(bookmark) to the ``sessions`` table.

Roadmap items #0579 and #0157.
"""

import sqlalchemy as sa
from alembic import op

revision = "035"
down_revision = "034"


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("deleted_at", sa.DateTime, nullable=True),
    )
    op.create_index(
        "idx_sessions_deleted_at",
        "sessions",
        ["deleted_at"],
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )
    op.add_column(
        "sessions",
        sa.Column("is_favorite", sa.Boolean, server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("sessions", "is_favorite")
    op.drop_index("idx_sessions_deleted_at", "sessions")
    op.drop_column("sessions", "deleted_at")
