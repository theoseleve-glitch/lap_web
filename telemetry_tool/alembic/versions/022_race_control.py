"""022 -- Race Control: admin audit, security events, metrics, incidents.

Adds admin-specific columns to users (is_superadmin, admin_role).
Creates admin_audit_log, system_metrics_snapshots, stripe_webhook_log,
security_events, incident_notes tables (all global, no RLS).

Note: totp_secret, totp_enabled, totp_backup_codes already exist from 020.

Revision ID: 022
Revises: 021
Create Date: 2026-02-28
"""
from alembic import op
import sqlalchemy as sa

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. Admin columns on users ──────────────────────────────────────────
    op.add_column(
        "users",
        sa.Column(
            "is_superadmin",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("admin_role", sa.Text(), nullable=True),
    )

    # ── 2. admin_audit_log (no RLS — admin actions are cross-workspace) ────
    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "admin_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=True),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_admin_audit_admin",
        "admin_audit_log",
        ["admin_user_id", "created_at"],
    )
    op.create_index(
        "idx_admin_audit_target",
        "admin_audit_log",
        ["target_type", "target_id"],
    )
    op.create_index(
        "idx_admin_audit_action",
        "admin_audit_log",
        ["action", "created_at"],
    )

    # ── 3. system_metrics_snapshots (no RLS) ───────────────────────────────
    op.create_table(
        "system_metrics_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column("metrics_json", sa.Text(), nullable=False),
    )
    op.create_index(
        "idx_metrics_collected",
        "system_metrics_snapshots",
        ["collected_at"],
    )

    # ── 4. stripe_webhook_log (no RLS) ─────────────────────────────────────
    op.create_table(
        "stripe_webhook_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("stripe_event_id", sa.Text(), nullable=False, unique=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("signature_valid", sa.Boolean(), nullable=False),
        sa.Column(
            "processing_status", sa.Text(), server_default="pending"
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_stripe_wh_type",
        "stripe_webhook_log",
        ["event_type", "created_at"],
    )
    op.create_index(
        "idx_stripe_wh_status",
        "stripe_webhook_log",
        ["processing_status"],
    )

    # ── 5. security_events (no RLS) ────────────────────────────────────────
    op.create_table(
        "security_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column("severity", sa.Text(), server_default="info"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_security_type_created",
        "security_events",
        ["event_type", "created_at"],
    )
    op.create_index(
        "idx_security_ip",
        "security_events",
        ["ip_address", "created_at"],
    )

    # ── 6. incident_notes (no RLS) ─────────────────────────────────────────
    op.create_table(
        "incident_notes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "admin_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("severity", sa.Text(), server_default="p3"),
        sa.Column("status", sa.Text(), server_default="open"),
        sa.Column("linked_entities", sa.Text(), nullable=True),
        sa.Column(
            "resolved_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_incidents_status",
        "incident_notes",
        ["status", "created_at"],
    )


def downgrade():
    op.drop_table("incident_notes")
    op.drop_table("security_events")
    op.drop_table("stripe_webhook_log")
    op.drop_table("system_metrics_snapshots")
    op.drop_table("admin_audit_log")
    op.drop_column("users", "admin_role")
    op.drop_column("users", "is_superadmin")
