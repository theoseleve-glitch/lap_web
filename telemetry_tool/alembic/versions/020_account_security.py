"""020 -- Account security: password reset, session metadata, 2FA, preferences.

Creates:
- password_reset_tokens: forgot-password flow with hashed tokens

Modifies refresh_tokens:
- user_agent, ip_address, last_used_at for session management

Modifies users:
- totp_secret, totp_enabled, totp_backup_codes, totp_verified_at (2FA)
- preferences (JSONB user settings)
- terms_accepted_at, terms_version (TOS tracking)

Revision ID: 020
Revises: 019
Create Date: 2026-02-27
"""
from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. Password reset tokens ──────────────────────────────────────────
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_password_reset_token_hash", "password_reset_tokens", ["token_hash"])
    op.create_index("idx_password_reset_user", "password_reset_tokens", ["user_id"])

    # ── 2. Refresh token session metadata ─────────────────────────────────
    op.add_column("refresh_tokens",
                   sa.Column("user_agent", sa.Text(), nullable=True))
    op.add_column("refresh_tokens",
                   sa.Column("ip_address", sa.Text(), nullable=True))
    op.add_column("refresh_tokens",
                   sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))

    # ── 3. 2FA columns on users ───────────────────────────────────────────
    op.add_column("users",
                   sa.Column("totp_secret", sa.Text(), nullable=True))
    op.add_column("users",
                   sa.Column("totp_enabled", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("users",
                   sa.Column("totp_backup_codes", sa.Text(), nullable=True))  # JSON array
    op.add_column("users",
                   sa.Column("totp_verified_at", sa.DateTime(timezone=True), nullable=True))

    # ── 4. User preferences ───────────────────────────────────────────────
    op.add_column("users",
                   sa.Column("preferences", sa.Text(), server_default="{}", nullable=False))

    # ── 5. Terms acceptance tracking ──────────────────────────────────────
    op.add_column("users",
                   sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users",
                   sa.Column("terms_version", sa.Text(), nullable=True))


def downgrade():
    # Users columns
    op.drop_column("users", "terms_version")
    op.drop_column("users", "terms_accepted_at")
    op.drop_column("users", "preferences")
    op.drop_column("users", "totp_verified_at")
    op.drop_column("users", "totp_backup_codes")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")

    # Refresh token columns
    op.drop_column("refresh_tokens", "last_used_at")
    op.drop_column("refresh_tokens", "ip_address")
    op.drop_column("refresh_tokens", "user_agent")

    # Password reset tokens
    op.drop_index("idx_password_reset_user", table_name="password_reset_tokens")
    op.drop_index("idx_password_reset_token_hash", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
