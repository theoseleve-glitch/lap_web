"""Add GDPR support — deleted_at on users, data_exports table.

Revision ID: 010
Revises: 009
"""
from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"


def upgrade() -> None:
    # 1. Add soft-delete column to users table
    op.add_column("users", sa.Column("deleted_at", sa.DateTime, nullable=True))
    op.create_index("idx_users_deleted_at", "users", ["deleted_at"])

    # 2. Create data_exports table for GDPR data portability requests
    op.create_table(
        "data_exports",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Text,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("file_path", sa.Text),
        sa.Column("format", sa.Text, nullable=False, server_default="zip"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime),
        sa.Column("completed_at", sa.DateTime),
    )
    op.create_index("idx_data_exports_user", "data_exports", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_data_exports_user", "data_exports")
    op.drop_table("data_exports")
    op.drop_index("idx_users_deleted_at", "users")
    op.drop_column("users", "deleted_at")
