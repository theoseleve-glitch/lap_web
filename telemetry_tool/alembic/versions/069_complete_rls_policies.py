"""069 — complete RLS policies for tables 064 forced but left without a
workspace-scoped policy.

The 064 FORCE-RLS sweep forced RLS on audit_log, entitlement_overrides and
support_tickets, but none had a workspace-scoped policy (audit_log only had a
``workspace_id IS NULL`` system-events INSERT policy; the other two had no
policy at all). Under the non-superuser telemetry_app role that means denied
reads/writes — caught during the live RLS cutover (the app writes audit_log on
every mutation and reads entitlement_overrides on every entitlement check).

Adds the standard ``workspace_id = current_setting('app.current_workspace_id')``
FOR ALL policy to each (the audit_log system-events NULL policy stays, OR-ed).
User-level (NULL-workspace) entitlement overrides are read via the BYPASSRLS
maint path, so they don't need an app-role policy here.

Idempotent + guarded (skips a table that lacks workspace_id). Chains off 068.
"""
from alembic import op

revision = "069_complete_rls_policies"
down_revision = "068_fk_child_read_rls"
branch_labels = None
depends_on = None

_TABLES = ["audit_log", "entitlement_overrides", "support_tickets"]


def upgrade() -> None:
    for t in _TABLES:
        op.execute(f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_schema='public' AND table_name='{t}'
                         AND column_name='workspace_id') THEN
            EXECUTE 'ALTER TABLE public.{t} ENABLE ROW LEVEL SECURITY';
            EXECUTE 'DROP POLICY IF EXISTS {t}_tenant_isolation ON public.{t}';
            EXECUTE 'CREATE POLICY {t}_tenant_isolation ON public.{t} '
                    'USING (workspace_id = current_setting(''app.current_workspace_id'', true)::int) '
                    'WITH CHECK (workspace_id = current_setting(''app.current_workspace_id'', true)::int)';
          END IF;
        END $$;
        """)


def downgrade() -> None:
    for t in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS {t}_tenant_isolation ON public.{t}")
