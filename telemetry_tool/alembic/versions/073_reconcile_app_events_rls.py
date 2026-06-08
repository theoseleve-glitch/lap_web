"""073 — reconcile app_events RLS to the canonical workspace GUC.

Migration 058 ORIGINALLY created ``app_events`` with an RLS policy
(``app_events_workspace_isolation``) whose predicate used the WRONG GUC
``current_setting('app.workspace_id')::integer``. Every other RLS policy on the
platform uses the canonical GUC ``current_setting('app.current_workspace_id',
true)::int`` (set via ``SET LOCAL app.current_workspace_id`` +
``SET LOCAL ROLE telemetry_app`` in ``auth/workspace.set_workspace_context``).
A policy keyed on the never-set ``app.workspace_id`` is a live tenant-isolation
defect anywhere ``app_events`` exists.

This migration rewrites the policy (USING + WITH CHECK) to the canonical GUC.
It is:
  - idempotent — DROP POLICY IF EXISTS then CREATE (Postgres has no
    CREATE POLICY IF NOT EXISTS);
  - guarded — wrapped in ``to_regclass('public.app_events') IS NOT NULL`` so it
    is a no-op where the table was never created (058 is neutralized on prod).
"""
from alembic import op

revision = "073"
down_revision = "072_session_gamification_applied"
branch_labels = None
depends_on = None

_GUC = "current_setting('app.current_workspace_id', true)::int"


def upgrade() -> None:
    op.execute(f"""
        DO $$
        BEGIN
            IF to_regclass('public.app_events') IS NOT NULL THEN
                EXECUTE 'ALTER TABLE app_events ENABLE ROW LEVEL SECURITY';
                EXECUTE 'DROP POLICY IF EXISTS app_events_workspace_isolation ON app_events';
                EXECUTE 'CREATE POLICY app_events_workspace_isolation ON app_events '
                        'USING (workspace_id = {_GUC}) '
                        'WITH CHECK (workspace_id = {_GUC})';
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.app_events') IS NOT NULL THEN
                EXECUTE 'DROP POLICY IF EXISTS app_events_workspace_isolation ON app_events';
                EXECUTE 'CREATE POLICY app_events_workspace_isolation ON app_events '
                        'USING (workspace_id = current_setting(''app.workspace_id'')::integer) '
                        'WITH CHECK (workspace_id = current_setting(''app.workspace_id'')::integer)';
            END IF;
        END $$;
    """)
