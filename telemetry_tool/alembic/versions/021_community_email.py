"""021 -- Community + email: invitations, support tickets, usage counters, email log.

Creates:
- invitations: team invite flow with hashed tokens
- support_tickets: in-app support (workspace-scoped, RLS)
- usage_counters: workspace-scoped metric counters (RLS)
- email_log: transactional email tracking (global)

Revision ID: 021
Revises: 020
Create Date: 2026-02-27
"""
import sqlalchemy as sa

from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # ── 1. Invitations (cross-workspace, no RLS) ─────────────────────────
    op.create_table(
        "invitations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("team_id", sa.Integer(),
                   sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="member"),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("inviter_id", sa.Integer(),
                   sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_invitations_email", "invitations", ["email"])
    op.create_index("idx_invitations_team", "invitations", ["team_id"])
    op.create_index("idx_invitations_token", "invitations", ["token_hash"], unique=True)

    # ── 2. Support tickets (workspace-scoped, RLS) ────────────────────────
    op.create_table(
        "support_tickets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(),
                   sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.Integer(),
                   sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("issue_type", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("diagnostics", sa.Text(), nullable=True),  # JSON
        sa.Column("status", sa.Text(), server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_support_tickets_user", "support_tickets", ["user_id"])
    op.create_index("idx_support_tickets_ws", "support_tickets", ["workspace_id"])

    # RLS for support_tickets
    conn.execute(sa.text('ALTER TABLE "support_tickets" ENABLE ROW LEVEL SECURITY'))
    conn.execute(sa.text(
        'CREATE POLICY "support_tickets_tenant_isolation" ON "support_tickets" '
        "USING (workspace_id = current_setting('app.current_workspace_id')::integer) "
        "WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer)"
    ))

    # ── 3. Usage counters (workspace-scoped, RLS) ─────────────────────────
    op.create_table(
        "usage_counters",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(),
                   sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("period", sa.Text(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("workspace_id", "metric", "period",
                            name="uq_usage_ws_metric_period"),
    )
    op.create_index("idx_usage_counters_lookup", "usage_counters",
                     ["workspace_id", "metric", "period"])

    # RLS for usage_counters
    conn.execute(sa.text('ALTER TABLE "usage_counters" ENABLE ROW LEVEL SECURITY'))
    conn.execute(sa.text(
        'CREATE POLICY "usage_counters_tenant_isolation" ON "usage_counters" '
        "USING (workspace_id = current_setting('app.current_workspace_id')::integer) "
        "WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer)"
    ))

    # ── 4. Email log (global, not workspace-scoped) ───────────────────────
    op.create_table(
        "email_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("to_email", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("idx_email_log_user", "email_log", ["user_id"])
    op.create_index("idx_email_log_template", "email_log", ["template"])
    op.create_index("idx_email_log_sent_at", "email_log", ["sent_at"])


def downgrade():
    conn = op.get_bind()

    # Drop email_log
    op.drop_index("idx_email_log_sent_at", table_name="email_log")
    op.drop_index("idx_email_log_template", table_name="email_log")
    op.drop_index("idx_email_log_user", table_name="email_log")
    op.drop_table("email_log")

    # Drop usage_counters RLS + table
    conn.execute(sa.text('DROP POLICY IF EXISTS "usage_counters_tenant_isolation" ON "usage_counters"'))
    conn.execute(sa.text('ALTER TABLE "usage_counters" DISABLE ROW LEVEL SECURITY'))
    op.drop_index("idx_usage_counters_lookup", table_name="usage_counters")
    op.drop_table("usage_counters")

    # Drop support_tickets RLS + table
    conn.execute(sa.text('DROP POLICY IF EXISTS "support_tickets_tenant_isolation" ON "support_tickets"'))
    conn.execute(sa.text('ALTER TABLE "support_tickets" DISABLE ROW LEVEL SECURITY'))
    op.drop_index("idx_support_tickets_ws", table_name="support_tickets")
    op.drop_index("idx_support_tickets_user", table_name="support_tickets")
    op.drop_table("support_tickets")

    # Drop invitations
    op.drop_index("idx_invitations_token", table_name="invitations")
    op.drop_index("idx_invitations_team", table_name="invitations")
    op.drop_index("idx_invitations_email", table_name="invitations")
    op.drop_table("invitations")
