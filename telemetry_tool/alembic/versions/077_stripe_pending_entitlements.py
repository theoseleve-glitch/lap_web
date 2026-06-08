"""073 — stripe_pending_entitlements: unmatched-checkout reconciliation table.

When a Stripe ``checkout.session.completed`` webhook fires but no user row can
be matched to the paying customer (edge case: account deleted between checkout
and webhook, or email mismatch), billing.py records the raw entitlement here
keyed by stripe_session_id so an operator can reconcile it later.

Design notes
────────────
- Global / server-side table (no RLS, no workspace_id) — mirrors stripe_events
  and stripe_webhook_log.
- UNIQUE on stripe_session_id: the billing.py INSERT uses
  ON CONFLICT (stripe_session_id) DO NOTHING for idempotency.
- payload_json TEXT: stores JSON-serialised session data for full auditability.
- No RLS: only telemetry_app (writes) + telemetry_maint (reads/reconciliation)
  touch this table; it has no workspace_id column, so tenant isolation does not
  apply.

Chains off 072_session_gamification_applied.
"""
from alembic import op

revision = "073_stripe_pending_entitlements"
down_revision = "072_session_gamification_applied"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS stripe_pending_entitlements (
            id                      BIGSERIAL PRIMARY KEY,
            stripe_session_id       TEXT UNIQUE NOT NULL,
            stripe_customer_id      TEXT,
            stripe_subscription_id  TEXT,
            customer_email          TEXT,
            plan_tier               TEXT,
            payload_json            TEXT,
            reconciled_at           TIMESTAMPTZ,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stripe_pending_ents_customer "
        "ON stripe_pending_entitlements (stripe_customer_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stripe_pending_ents_email "
        "ON stripe_pending_entitlements (customer_email)"
    )
    # Grants guarded so a dev DB without the app roles still migrates cleanly
    # (mirrors the pattern in 070_quests, 071_phase2b_retention).
    op.execute("""
        DO $$ BEGIN
            GRANT SELECT, INSERT, UPDATE ON stripe_pending_entitlements TO telemetry_app;
            GRANT USAGE, SELECT ON SEQUENCE stripe_pending_entitlements_id_seq TO telemetry_app;
        EXCEPTION WHEN undefined_object THEN NULL; END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            GRANT SELECT, INSERT, UPDATE ON stripe_pending_entitlements TO telemetry_maint;
            GRANT USAGE, SELECT ON SEQUENCE stripe_pending_entitlements_id_seq TO telemetry_maint;
        EXCEPTION WHEN undefined_object THEN NULL; END $$;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS stripe_pending_entitlements")
