"""Add oauth_connections table.

Revision ID: 003
Revises: 002
"""
import sqlalchemy as sa

from alembic import op

revision = "003"
down_revision = "002"


def upgrade() -> None:
    op.create_table(
        "oauth_connections",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("provider_user_id", sa.Text, nullable=False),
        sa.Column("access_token_enc", sa.Text),
        sa.Column("refresh_token_enc", sa.Text),
        sa.Column("expires_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "provider_user_id"),
    )
    op.create_index("idx_oauth_user", "oauth_connections", ["user_id"])

    # Email verification token column
    op.add_column("users", sa.Column("email_verify_token", sa.Text))
    op.add_column("users", sa.Column("email_verify_expires", sa.DateTime))


def downgrade() -> None:
    op.drop_column("users", "email_verify_expires")
    op.drop_column("users", "email_verify_token")
    op.drop_table("oauth_connections")
