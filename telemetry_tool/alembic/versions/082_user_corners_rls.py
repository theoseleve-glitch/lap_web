"""082 — RLS for user_corners (FK-child IDOR fix, BLOCKER).

user_corners (added in 059_user_corners_and_track_surface_mu_defaults) carries
no workspace_id column and was never covered by any RLS migration -- absent
from the FK-child read sweep in 068_fk_child_read_rls, and from 007/064/069/
073. 064's blanket "GRANT ... ON ALL TABLES" gave telemetry_app full CRUD with
no RLS gate at all, so a session_id-only WHERE clause (which is all
web/routes/data_v2.py's GET/POST /api/v1/sessions/<id>/user-corners handlers
filtered on, before their app-level ownership check was added alongside this
migration) let any workspace read AND overwrite another tenant's corner
apex/entry/exit GPS. Confirmed live cross-tenant IDOR.

Mirrors the FK-child idiom from 068_fk_child_read_rls (USING via a subquery
through the owning `sessions` row -- user_corners has no workspace_id of its
own to key a direct policy on) combined with the ENABLE+FORCE+WITH CHECK
pattern from 069_complete_rls_policies / 073_reconcile_app_events_rls /
081_feeling_competition. Unlike 068's read-only sweep, user_corners IS written
by the app (the POST handler upserts corners), so this policy also needs
WITH CHECK to scope INSERT/UPDATE -- 068 deliberately left WITH CHECK off
because its child tables are read-only from the app's perspective; that
exemption doesn't apply here.

Canonical GUC: current_setting('app.current_workspace_id', true)::int -- set
via auth.workspace.set_workspace_context's `SET LOCAL app.current_workspace_id`
+ `SET LOCAL ROLE telemetry_app`. Same GUC as 068/069/073/081; the missing_ok
(", true") form so an unset GUC yields NULL (query returns nothing / WITH
CHECK rejects) rather than erroring, matching every existing policy.

Guarded with information_schema existence checks (068/069/073's idiom) so a
dev DB without the table, or without sessions.workspace_id, still migrates
cleanly as a no-op. Idempotent (DROP POLICY IF EXISTS before CREATE). Uses
dollar-quoting for the CREATE POLICY EXECUTE (073's fix for the single-quote
escaping bug in 019/inline-quoted EXECUTE strings).

Chains off 081_feeling_competition (current head).
"""
from alembic import op

revision = "082_user_corners_rls"
down_revision = "081_feeling_competition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM information_schema.tables
                     WHERE table_schema = 'public' AND table_name = 'user_corners')
           AND EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_schema = 'public' AND table_name = 'sessions'
                       AND column_name = 'workspace_id')
        THEN
            EXECUTE 'ALTER TABLE public.user_corners ENABLE ROW LEVEL SECURITY';
            EXECUTE 'ALTER TABLE public.user_corners FORCE ROW LEVEL SECURITY';
            EXECUTE 'DROP POLICY IF EXISTS user_corners_ws_via_session ON public.user_corners';
            EXECUTE $q$CREATE POLICY user_corners_ws_via_session ON public.user_corners
                USING (session_id IN (
                    SELECT session_id FROM public.sessions
                    WHERE workspace_id = current_setting('app.current_workspace_id', true)::int
                ))
                WITH CHECK (session_id IN (
                    SELECT session_id FROM public.sessions
                    WHERE workspace_id = current_setting('app.current_workspace_id', true)::int
                ))$q$;
        END IF;
    END $$;
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS user_corners_ws_via_session ON public.user_corners")
    op.execute("ALTER TABLE IF EXISTS public.user_corners NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE IF EXISTS public.user_corners DISABLE ROW LEVEL SECURITY")
