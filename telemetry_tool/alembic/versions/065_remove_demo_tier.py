"""065 — remove the demo/free tier; the no-subscription floor is 'locked'.

The one-membership model has NO free tier. The former 'demo' tier (1 free
report/month) is replaced by 'locked' — a zero-access floor (view existing
data only; no new analyses/uploads/features). This migration:

- repoints every existing user on the demo/free tier to 'locked';
- flips the users.plan_tier column DEFAULT from 'demo' to 'locked' (new,
  never-subscribed users land locked until they start the trial/subscribe);
- renames the plan_definitions 'demo' row to 'locked' and zeroes its grants.

The code keeps 'demo'/'free' as fail-CLOSED aliases of 'locked' (auth/
entitlements.py), so this migration is safe to apply before/after the code
deploy in either order. Chains off 064_rls_enforcement.
"""
from alembic import op

revision = "065_remove_demo_tier"
down_revision = "064_rls_enforcement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Repoint existing users off the defunct free/demo tier.
    op.execute(
        "UPDATE users SET plan_tier = 'locked' "
        "WHERE plan_tier IN ('demo', 'free')"
    )

    # 2. New users default to the locked floor (was 'demo').
    op.execute("ALTER TABLE users ALTER COLUMN plan_tier SET DEFAULT 'locked'")

    # 3. Rename the plan_definitions 'demo' row to 'locked' and zero its
    #    grants (tier is the PK and is not referenced by any FK). Keep CSV
    #    export so users can still take their existing data with them.
    op.execute(
        """
        UPDATE plan_definitions SET
            tier = 'locked',
            display_name = 'No active subscription',
            reports_per_month = 0,
            max_upload_size_mb = 0,
            telemetry_retention_days = 30,
            api_access = false,
            comparison_enabled = false,
            coaching_plans_enabled = false,
            visualization_enabled = false,
            race_strategy_limit = 'none',
            live_monitoring = false,
            export_formats = '["csv"]',
            max_concurrent_jobs = 0,
            rate_multiplier = 1.0
        WHERE tier = 'demo'
        """
    )


def downgrade() -> None:
    # Restore the demo tier (best-effort: original free-tier grant values).
    op.execute(
        """
        UPDATE plan_definitions SET
            tier = 'demo',
            display_name = 'Demo',
            reports_per_month = 1,
            max_upload_size_mb = 150,
            telemetry_retention_days = 30,
            api_access = false,
            comparison_enabled = false,
            coaching_plans_enabled = false,
            visualization_enabled = false,
            race_strategy_limit = '4h_basic',
            live_monitoring = false,
            export_formats = '["csv"]',
            max_concurrent_jobs = 1,
            rate_multiplier = 1.0
        WHERE tier = 'locked'
        """
    )
    op.execute("ALTER TABLE users ALTER COLUMN plan_tier SET DEFAULT 'demo'")
    op.execute("UPDATE users SET plan_tier = 'demo' WHERE plan_tier = 'locked'")
