"""068 — read-side RLS for FK-only child tables (defense-in-depth).

Several child tables (race_strategies / race_alerts / race_compound_models,
kart_sessions / kart_maintenance, sector_times, stint_laps / tyre_degradation)
carry no workspace_id and no RLS. The app reaches them today only via
RLS-filtered parent JOINs, but a direct-by-id SELECT under the non-superuser
telemetry_app role would be unfiltered (an IDOR-under-RLS gap the re-audit
flagged). This adds USING-only RLS policies that filter READS by the parent's
workspace.

Deliberately conservative so it is launch-safe:
  * USING only, NO WITH CHECK  -> cannot reject any INSERT/UPDATE.
  * ENABLE but NOT FORCE       -> binds the non-owner app role (the actual gap)
                                  without changing behaviour for the owner /
                                  BYPASSRLS maint role.
  * each policy guarded by information_schema existence checks -> a name
    mismatch or missing table silently no-ops instead of failing the deploy.
  * current_setting(..., true) -> NULL (not error) when the GUC is unset.

PG-only (DO block); the SQLite/desktop schema has no RLS. Chains off 067.
"""
from alembic import op

revision = "068_fk_child_read_rls"
down_revision = "067_sessions_list_index"
branch_labels = None
depends_on = None

# (child_table, fk_column, workspace-bearing parent, parent_pk)
_CHILD_PARENT = [
    ("race_strategies", "race_id", "race_configs", "race_id"),
    ("race_alerts", "race_id", "race_configs", "race_id"),
    ("race_compound_models", "race_id", "race_configs", "race_id"),
    ("kart_sessions", "session_id", "sessions", "session_id"),
    ("kart_maintenance", "kart_id", "karts", "kart_id"),
    ("sector_times", "session_id", "sessions", "session_id"),
    ("stint_laps", "session_id", "sessions", "session_id"),
    ("tyre_degradation", "session_id", "sessions", "session_id"),
]


def upgrade() -> None:
    values = ",\n        ".join(
        f"('{c}','{fk}','{p}','{pk}')" for c, fk, p, pk in _CHILD_PARENT
    )
    op.execute(f"""
    DO $$
    DECLARE r RECORD;
    BEGIN
      FOR r IN SELECT * FROM (VALUES
        {values}
      ) AS t(child, fk, parent, ppk) LOOP
        IF EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_schema='public' AND table_name=r.child AND column_name=r.fk)
           AND EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_schema='public' AND table_name=r.parent AND column_name='workspace_id')
        THEN
          EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', r.child);
          EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', r.child || '_ws_via_parent', r.child);
          EXECUTE format(
            'CREATE POLICY %I ON public.%I USING (%I IN '
            '(SELECT %I FROM public.%I WHERE workspace_id = current_setting(''app.current_workspace_id'', true)::int))',
            r.child || '_ws_via_parent', r.child, r.fk, r.ppk, r.parent
          );
        END IF;
      END LOOP;
    END $$;
    """)


def downgrade() -> None:
    for c, _fk, _p, _pk in _CHILD_PARENT:
        op.execute(f"DROP POLICY IF EXISTS {c}_ws_via_parent ON public.{c}")
        op.execute(f"ALTER TABLE IF EXISTS public.{c} DISABLE ROW LEVEL SECURITY")
