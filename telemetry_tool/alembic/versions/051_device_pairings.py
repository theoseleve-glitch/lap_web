"""051 – device_pairings table for logger-to-webapp pairing.

Also adds source_bundle_hash column to sessions for sync idempotency.

Revision ID: 051
Revises: 050
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "device_pairings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspaces.id"), nullable=True),
        sa.Column("pairing_code", sa.String(7), unique=True, nullable=True),
        sa.Column("pairing_id", UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("device_token_hash", sa.String(128), nullable=True),
        sa.Column("device_name", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_device_pairings_code",
        "device_pairings",
        ["pairing_code"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "idx_device_pairings_user",
        "device_pairings",
        ["user_id"],
        postgresql_where=sa.text("status = 'confirmed'"),
    )
    op.create_index(
        "idx_device_pairings_pairing_id",
        "device_pairings",
        ["pairing_id"],
    )

    # Add source_bundle_hash to sessions for sync-upload idempotency.
    # The `source` column already exists (migration 001).
    op.add_column("sessions", sa.Column("source_bundle_hash", sa.String(128), nullable=True))
    op.create_index(
        "idx_sessions_bundle_hash",
        "sessions",
        ["source_bundle_hash"],
        postgresql_where=sa.text("source_bundle_hash IS NOT NULL"),
    )


def downgrade():
    op.drop_index("idx_sessions_bundle_hash", table_name="sessions")
    op.drop_column("sessions", "source_bundle_hash")
    op.drop_table("device_pairings")
