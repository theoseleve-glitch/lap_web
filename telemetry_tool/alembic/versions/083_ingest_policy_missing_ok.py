"""083 -- reconcile ingestion_jobs RLS to the canonical missing_ok GUC.

007_enable_rls created ``ingestion_jobs_tenant_isolation`` using
``current_setting('app.current_workspace_id')::integer`` -- the *raising*
form. Every other RLS policy on the platform (068/069/073/081/082) uses the
canonical ``current_setting('app.current_workspace_id', true)::int``
(missing_ok) so an unset GUC yields NULL -- the predicate then evaluates to
false and the query returns nothing -- instead of throwing.

This mattered in practice: ``web/routes/ingest.py`` (the old streaming-ingest
SSE/polling blueprint, mounted at ``/api/ingest/*``) sits outside the
``/api/v1/`` prefix that ``web/middleware/auth.py`` and
``web/middleware/tenant.py`` gate on, so it ran fully unauthenticated with no
``app.current_workspace_id`` ever set. Today that is safe only by accident:
the raising form makes ``JobStore.get``/``list_recent``'s bare SQL query
throw, which the surrounding ``except Exception: pass`` swallows into an
empty result / 404. Any future change that leaves a stale GUC set on a
pooled connection (e.g. a request whose transaction isn't cleanly committed
before the connection returns to the pool) flips this from "hides all rows"
to "leaks whatever workspace_id happens to be set" -- a live cross-tenant
read. Migrating to missing_ok makes isolation an explicit predicate instead
of an exception-handling side effect.

Paired with (not a substitute for): auth/tenant middleware now covering
``/api/ingest/`` (defense layer 1), an explicit ``workspace_id`` predicate
added directly to ``JobStore.get``/``list_recent`` (layer 2, mirrors
``tasks/job_registry.py``), and ``/api/ingest`` added to
``web/middleware/legacy_guard.py`` (layer 3 -- the route is fully superseded
by the workspace-scoped ``/api/v1/jobs`` blueprint and is blocked outright in
production; this migration is the last line of defense if that guard is ever
relaxed).

Idempotent (DROP POLICY IF EXISTS then CREATE -- Postgres has no CREATE
POLICY IF NOT EXISTS). Guarded with ``to_regclass`` so a dev DB without the
table still migrates cleanly as a no-op (073's idiom). Dollar-quoted CREATE
POLICY EXECUTE string (073's fix for the single-quote escaping bug in
019/inline-quoted EXECUTE strings).

Chains off 082_user_corners_rls (current head).
"""
from alembic import op

revision = "083_ingest_policy_missing_ok"
down_revision = "082_user_corners_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.ingestion_jobs') IS NOT NULL THEN
                EXECUTE 'ALTER TABLE public.ingestion_jobs ENABLE ROW LEVEL SECURITY';
                EXECUTE 'DROP POLICY IF EXISTS "ingestion_jobs_tenant_isolation" ON public.ingestion_jobs';
                EXECUTE $q$CREATE POLICY "ingestion_jobs_tenant_isolation" ON public.ingestion_jobs
                    USING (workspace_id = current_setting('app.current_workspace_id', true)::int)
                    WITH CHECK (workspace_id = current_setting('app.current_workspace_id', true)::int)$q$;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF to_regclass('public.ingestion_jobs') IS NOT NULL THEN
                EXECUTE 'DROP POLICY IF EXISTS "ingestion_jobs_tenant_isolation" ON public.ingestion_jobs';
                EXECUTE $q$CREATE POLICY "ingestion_jobs_tenant_isolation" ON public.ingestion_jobs
                    USING (workspace_id = current_setting('app.current_workspace_id')::integer)
                    WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer)$q$;
            END IF;
        END $$;
    """)
