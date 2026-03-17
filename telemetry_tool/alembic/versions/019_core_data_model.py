"""019 -- Core data model: entitlements, usage tracking, audit, stripe events.

Consolidates all schema from PROMPTS 1A-3C into the authoritative data model.

Creates:
- plan_definitions: global tier config (seeded)
- usage_events: append-only billable-action log
- usage_monthly: pre-aggregated monthly usage per workspace
- entitlement_overrides: per-user/workspace overrides (grandfathering, credits)
- audit_log: security + billing change log (workspace-scoped)
- stripe_events: webhook deduplication

Modifies users:
- plan_tier (actual tier: demo/racer/world-class/b2b)
- Renames billing_plan -> subscription_status
- suspended_at, suspension_reason
- grace_period_end
- is_platform_admin

Modifies sessions:
- retention_expired, retention_warning_sent

Applies RLS to workspace-scoped tables.
Seeds plan_definitions from pricing.ts.
Backfills plan_tier from existing subscription data.

Revision ID: 019
Revises: 018
Create Date: 2026-02-27
"""
import sqlalchemy as sa

from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # ── 1. Fix users table ────────────────────────────────────────────────
    # Add plan_tier (the actual tier), rename billing_plan → subscription_status
    op.add_column(
        "users",
        sa.Column("plan_tier", sa.Text(), server_default="demo", nullable=False),
    )
    op.alter_column("users", "billing_plan", new_column_name="subscription_status")

    # Suspension columns
    op.add_column(
        "users",
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("suspension_reason", sa.Text(), nullable=True),
    )

    # Grace period tracking
    op.add_column(
        "users",
        sa.Column("grace_period_end", sa.DateTime(timezone=True), nullable=True),
    )

    # Platform admin flag
    op.add_column(
        "users",
        sa.Column(
            "is_platform_admin",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    # Stripe customer index
    op.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_users_stripe_customer
        ON users (stripe_customer_id) WHERE stripe_customer_id IS NOT NULL
    """))

    # ── 2. Sessions: retention tracking columns ───────────────────────────
    op.execute(sa.text("""
        ALTER TABLE sessions
        ADD COLUMN IF NOT EXISTS retention_expired BOOLEAN DEFAULT FALSE
    """))
    op.execute(sa.text("""
        ALTER TABLE sessions
        ADD COLUMN IF NOT EXISTS retention_warning_sent BOOLEAN DEFAULT FALSE
    """))
    op.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_sessions_retention
        ON sessions (workspace_id, created_at)
        WHERE retention_expired IS NOT TRUE
    """))

    # ── 3. plan_definitions (global, NOT workspace-scoped) ────────────────
    op.create_table(
        "plan_definitions",
        sa.Column("tier", sa.Text(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("reports_per_month", sa.Integer(), nullable=True),  # NULL = unlimited
        sa.Column("max_upload_size_mb", sa.Integer(), server_default="500"),
        sa.Column("telemetry_retention_days", sa.Integer(), nullable=True),
        sa.Column("api_access", sa.Boolean(), server_default="false"),
        sa.Column("comparison_enabled", sa.Boolean(), server_default="false"),
        sa.Column("coaching_plans_enabled", sa.Boolean(), server_default="false"),
        sa.Column("visualization_enabled", sa.Boolean(), server_default="false"),
        sa.Column("race_strategy_limit", sa.Text(), nullable=True),
        sa.Column("live_monitoring", sa.Boolean(), server_default="false"),
        sa.Column("export_formats", sa.Text(), server_default='["csv"]'),
        sa.Column("max_concurrent_jobs", sa.Integer(), server_default="1"),
        sa.Column("rate_multiplier", sa.Float(), server_default="1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # ── 4. usage_events (workspace-scoped, high-write) ────────────────────
    op.create_table(
        "usage_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("cost", sa.Integer(), server_default="1"),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_usage_events_ws_type_created", "usage_events",
                     ["workspace_id", "event_type", "created_at"])
    op.create_index("idx_usage_events_user_created", "usage_events",
                     ["user_id", "created_at"])

    # ── 5. usage_monthly (workspace-scoped, pre-aggregated) ───────────────
    op.create_table(
        "usage_monthly",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("total", sa.Integer(), server_default="0"),
        sa.UniqueConstraint("workspace_id", "period_start", "event_type",
                            name="uq_usage_monthly_ws_period_type"),
    )
    op.create_index("idx_usage_monthly_ws_period", "usage_monthly",
                     ["workspace_id", "period_start"])

    # ── 6. entitlement_overrides ──────────────────────────────────────────
    op.create_table(
        "entitlement_overrides",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=True),
        sa.Column("override_key", sa.Text(), nullable=False),
        sa.Column("override_value", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_overrides_user", "entitlement_overrides", ["user_id"])
    op.create_index("idx_overrides_workspace", "entitlement_overrides", ["workspace_id"])

    # ── 7. audit_log (workspace-scoped) ───────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_audit_log_user_created", "audit_log", ["user_id", "created_at"])
    op.create_index("idx_audit_log_ws_created", "audit_log", ["workspace_id", "created_at"])
    op.create_index("idx_audit_log_action", "audit_log", ["action"])

    # ── 8. stripe_events (global, webhook dedup) ──────────────────────────
    op.create_table(
        "stripe_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stripe_event_id", sa.Text(), unique=True, nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("payload_hash", sa.Text(), nullable=True),
    )
    op.create_index("idx_stripe_events_event_id", "stripe_events",
                     ["stripe_event_id"], unique=True)
    op.create_index("idx_stripe_events_type", "stripe_events", ["event_type"])

    # ── 9. RLS on workspace-scoped tables ─────────────────────────────────
    rls_tables = ["usage_events", "usage_monthly", "entitlement_overrides", "audit_log"]
    for table in rls_tables:
        conn.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
        conn.execute(sa.text(
            f'CREATE POLICY "{table}_tenant_isolation" ON "{table}" '
            f"USING (workspace_id = current_setting('app.current_workspace_id')::integer) "
            f"WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer)"
        ))

    # ── 10. Seed plan_definitions (matches pricing.ts exactly) ────────────
    conn.execute(sa.text("""
        INSERT INTO plan_definitions
            (tier, display_name, reports_per_month, max_upload_size_mb,
             telemetry_retention_days, api_access, comparison_enabled,
             coaching_plans_enabled, visualization_enabled, race_strategy_limit,
             live_monitoring, export_formats, max_concurrent_jobs, rate_multiplier)
        VALUES
            ('demo', 'Demo', 1, 150, 30, false, false, false, false,
             '4h_basic', false, '["csv"]', 1, 1.0),
            ('racer', 'Racer', 10, 2500, 90, false, false, true, true,
             '24h_complex', true, '["pdf","csv"]', 2, 2.0),
            ('world-class', 'World-Class', NULL, NULL, 365, true, true, true, true,
             'unlimited', true, '["pdf","csv","api"]', 5, 5.0),
            ('b2b', 'B2B', NULL, NULL, NULL, true, true, true, true,
             'unlimited', true, '["pdf","csv","api","branded"]', 10, 10.0)
    """))

    # ── 11. Backfill plan_tier from existing subscription data ────────────
    conn.execute(sa.text("""
        UPDATE users SET plan_tier = CASE
            WHEN subscription_status = 'active' AND stripe_subscription_id IS NOT NULL THEN 'racer'
            WHEN subscription_status IN ('free', '') OR subscription_status IS NULL THEN 'demo'
            ELSE 'demo'
        END
    """))


def downgrade():
    conn = op.get_bind()

    # Remove RLS policies
    rls_tables = ["audit_log", "entitlement_overrides", "usage_monthly", "usage_events"]
    for table in rls_tables:
        conn.execute(sa.text(f'DROP POLICY IF EXISTS "{table}_tenant_isolation" ON "{table}"'))
        conn.execute(sa.text(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY'))

    # Drop tables
    op.drop_table("stripe_events")
    op.drop_table("audit_log")
    op.drop_table("entitlement_overrides")
    op.drop_table("usage_monthly")
    op.drop_table("usage_events")
    op.drop_table("plan_definitions")

    # Revert sessions columns
    op.execute(sa.text("DROP INDEX IF EXISTS idx_sessions_retention"))
    op.execute(sa.text("ALTER TABLE sessions DROP COLUMN IF EXISTS retention_warning_sent"))
    op.execute(sa.text("ALTER TABLE sessions DROP COLUMN IF EXISTS retention_expired"))

    # Revert users columns
    op.execute(sa.text("DROP INDEX IF EXISTS idx_users_stripe_customer"))
    op.drop_column("users", "is_platform_admin")
    op.drop_column("users", "grace_period_end")
    op.drop_column("users", "suspension_reason")
    op.drop_column("users", "suspended_at")
    op.alter_column("users", "subscription_status", new_column_name="billing_plan")
    op.drop_column("users", "plan_tier")
