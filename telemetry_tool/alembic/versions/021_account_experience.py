"""021 -- Account experience: preferences, TOTP 2FA, usage counters, support tickets.

Adds user preferences (JSONB), TOTP 2FA columns, usage_counters table
with RLS, support_tickets table with RLS, and device-info columns on
refresh_tokens.

Revision ID: 021
Revises: 020
Create Date: 2026-02-27
"""
from alembic import op
import sqlalchemy as sa


revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # ── 1. User preferences & TOTP columns ───────────────────────────
    try:
        op.add_column("users", sa.Column("preferences", sa.JSON(), server_default="{}"))
    except Exception:
        pass  # Column may already exist

    try:
        op.add_column("users", sa.Column("totp_secret", sa.Text(), nullable=True))
    except Exception:
        pass

    try:
        op.add_column("users", sa.Column("totp_enabled", sa.Boolean(), server_default="false"))
    except Exception:
        pass

    try:
        op.add_column("users", sa.Column("totp_backup_codes", sa.ARRAY(sa.Text()), nullable=True))
    except Exception:
        pass

    try:
        op.add_column("users", sa.Column("totp_verified_at", sa.DateTime(timezone=True), nullable=True))
    except Exception:
        pass

    # ── 2. Usage counters ────────────────────────────────────────────
    op.create_table(
        "usage_counters",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("period", sa.Text(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "metric", "period", name="uq_usage_ws_metric_period"),
    )
    op.create_index(
        "idx_usage_counters_lookup",
        "usage_counters",
        ["workspace_id", "metric", "period"],
    )

    # RLS for usage_counters
    conn.execute(sa.text('ALTER TABLE "usage_counters" ENABLE ROW LEVEL SECURITY'))
    conn.execute(sa.text(
        'CREATE POLICY "usage_counters_tenant_isolation" ON "usage_counters" '
        "USING (workspace_id = current_setting('app.current_workspace_id')::integer)"
    ))

    # ── 3. Support tickets ───────────────────────────────────────────
    op.create_table(
        "support_tickets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("issue_type", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("diagnostics", sa.JSON(), nullable=True),
        sa.Column("status", sa.Text(), server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_support_tickets_user", "support_tickets", ["user_id"])

    # RLS for support_tickets
    conn.execute(sa.text('ALTER TABLE "support_tickets" ENABLE ROW LEVEL SECURITY'))
    conn.execute(sa.text(
        'CREATE POLICY "support_tickets_tenant_isolation" ON "support_tickets" '
        "USING (workspace_id = current_setting('app.current_workspace_id')::integer)"
    ))

    # ── 4. Add device-info tracking to refresh_tokens ────────────────
    try:
        op.add_column("refresh_tokens", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
    except Exception:
        pass  # Column may already exist

    try:
        op.add_column("refresh_tokens", sa.Column("ip_address", sa.Text(), nullable=True))
    except Exception:
        pass

    try:
        op.add_column("refresh_tokens", sa.Column("user_agent", sa.Text(), nullable=True))
    except Exception:
        pass


def downgrade():
    conn = op.get_bind()

    # ── Drop RLS policies ────────────────────────────────────────────
    conn.execute(sa.text('DROP POLICY IF EXISTS "support_tickets_tenant_isolation" ON "support_tickets"'))
    conn.execute(sa.text('ALTER TABLE "support_tickets" DISABLE ROW LEVEL SECURITY'))
    conn.execute(sa.text('DROP POLICY IF EXISTS "usage_counters_tenant_isolation" ON "usage_counters"'))
    conn.execute(sa.text('ALTER TABLE "usage_counters" DISABLE ROW LEVEL SECURITY'))

    # ── Drop tables ──────────────────────────────────────────────────
    op.drop_table("support_tickets")
    op.drop_index("idx_usage_counters_lookup", table_name="usage_counters")
    op.drop_table("usage_counters")

    # ── Drop user columns ────────────────────────────────────────────
    try:
        op.drop_column("users", "totp_verified_at")
    except Exception:
        pass
    try:
        op.drop_column("users", "totp_backup_codes")
    except Exception:
        pass
    try:
        op.drop_column("users", "totp_enabled")
    except Exception:
        pass
    try:
        op.drop_column("users", "totp_secret")
    except Exception:
        pass
    try:
        op.drop_column("users", "preferences")
    except Exception:
        pass

    # ── Drop refresh_tokens columns ──────────────────────────────────
    try:
        op.drop_column("refresh_tokens", "user_agent")
    except Exception:
        pass
    try:
        op.drop_column("refresh_tokens", "ip_address")
    except Exception:
        pass
    try:
        op.drop_column("refresh_tokens", "last_used_at")
    except Exception:
        pass
