"""076 — telemetry_maint role (NOSUPERUSER BYPASSRLS) + SELECT grants.

The admin/analytics surface reads cross-tenant aggregates of behavioral events
through a role that BYPASSes RLS. ``telemetry_maint`` already exists on prod, so:

  - CREATE ROLE is GUARDED on ``pg_roles`` (a bare CREATE ROLE on an existing
    role raises and aborts the whole migration transaction); the role's
    attributes are otherwise ensured via ALTER ROLE.
  - The role is granted **SELECT only** on ``app_events`` and
    ``marketing_events``. Because it BYPASSes RLS, any write grant would let an
    admin mutate any tenant's rows — read-only is the security boundary.

Grants are themselves guarded on table presence (``to_regclass``) so the
migration is a no-op for tables that don't exist yet. Downgrade revokes the
grants but DOES NOT drop the role — it predates this migration.
"""
from alembic import op

revision = "076"
down_revision = "075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'telemetry_maint') THEN
        CREATE ROLE telemetry_maint NOSUPERUSER BYPASSRLS;
    ELSE
        ALTER ROLE telemetry_maint NOSUPERUSER BYPASSRLS;
    END IF;
END $$;""")

    op.execute("""DO $$
BEGIN
    IF to_regclass('public.app_events') IS NOT NULL THEN
        EXECUTE 'GRANT SELECT ON app_events TO telemetry_maint';
    END IF;
    IF to_regclass('public.marketing_events') IS NOT NULL THEN
        EXECUTE 'GRANT SELECT ON marketing_events TO telemetry_maint';
    END IF;
END $$;""")


def downgrade() -> None:
    # Revoke grants only — the role itself is left intact (telemetry_maint
    # predates this migration on prod and must survive a downgrade). Guarded on
    # table + role presence for idempotency.
    op.execute("""DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'telemetry_maint') THEN
        IF to_regclass('public.app_events') IS NOT NULL THEN
            EXECUTE 'REVOKE SELECT ON app_events FROM telemetry_maint';
        END IF;
        IF to_regclass('public.marketing_events') IS NOT NULL THEN
            EXECUTE 'REVOKE SELECT ON marketing_events FROM telemetry_maint';
        END IF;
    END IF;
END $$;""")
