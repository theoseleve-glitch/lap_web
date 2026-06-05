"""064 — RLS enforcement: app/maint roles, grants, FORCE sweep (P0 launch fix).

Prod connects as the ``telemetry`` bootstrap superuser (rolsuper=t,
rolbypassrls=t), so every tenant-isolation policy created since 007 is
silently bypassed (documented in lap-website/e2e/certification-live.spec.ts).
The non-superuser role ``telemetry_app`` that auth/workspace.py drops to via
SET LOCAL ROLE was never created or granted anything by any migration — this
migration makes the intended privilege architecture real:

- ``telemetry_app``  — NOSUPERUSER NOBYPASSRLS; all request + pipeline traffic.
  The app DSN (TELEMETRY_PG_URL) must switch to this role at cutover.
- ``telemetry_maint`` — NOSUPERUSER but BYPASSRLS; legitimately cross-tenant
  maintenance only (retention enforcement, usage aggregation, admin storage
  metrics) via TELEMETRY_PG_MAINT_URL.
- the migration/owner role (currently ``telemetry``) keeps DDL: alembic +
  usage_events/audit_log partition rotation via TELEMETRY_PG_MIGRATION_URL.

Also:
- FORCE ROW LEVEL SECURITY on every table that has RLS enabled but not
  forced (dynamic sweep — tables created after 034_force_rls_on_owner were
  never re-covered: gamification trio from 041, corner_progression,
  workspace_members, endurance_stints, track_surfaces, race_actuals,
  endurance_race_anchors, track_surface_snapshots, ...).
- ALTER DEFAULT PRIVILEGES so tables/sequences created by FUTURE migrations
  are automatically granted to both roles.
- audit_log gains a system-events INSERT policy (workspace_id IS NULL):
  the Stripe webhook writes workspace-less audit rows (web/routes/billing.py)
  which the 019 tenant policy's WITH CHECK would reject for a non-superuser.

Roles are idempotent (prod already carries an unused telemetry_app) and their
safe attributes are enforced with ALTER ROLE even when pre-existing. LOGIN
passwords are deliberately NOT set here — never commit secrets; ops assigns
them out-of-band (see docs/rls-cutover-runbook.md).

Chains off 063_track_wet_pace.
"""
from alembic import op

revision = "064_rls_enforcement"
down_revision = "063_track_wet_pace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Roles (cluster-wide, idempotent, attributes enforced) ──────
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'telemetry_app') THEN
                CREATE ROLE telemetry_app WITH LOGIN NOSUPERUSER NOBYPASSRLS
                    NOCREATEDB NOCREATEROLE NOREPLICATION;
            END IF;
            -- Enforce safe attributes even if the role pre-existed (prod does).
            ALTER ROLE telemetry_app WITH LOGIN NOSUPERUSER NOBYPASSRLS
                NOCREATEDB NOCREATEROLE NOREPLICATION;

            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'telemetry_maint') THEN
                CREATE ROLE telemetry_maint WITH LOGIN NOSUPERUSER BYPASSRLS
                    NOCREATEDB NOCREATEROLE NOREPLICATION;
            END IF;
            ALTER ROLE telemetry_maint WITH LOGIN NOSUPERUSER BYPASSRLS
                NOCREATEDB NOCREATEROLE NOREPLICATION;
        END
        $$;
        """
    )

    # ── 2. Grants on existing objects ─────────────────────────────────
    op.execute("GRANT USAGE ON SCHEMA public TO telemetry_app, telemetry_maint")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
        "TO telemetry_app, telemetry_maint"
    )
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public "
        "TO telemetry_app, telemetry_maint"
    )

    # ── 3. Default privileges for FUTURE objects ──────────────────────
    # Applies to objects created by the role running migrations (the owner),
    # so tables added by later migrations are granted automatically.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES "
        "TO telemetry_app, telemetry_maint"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT USAGE, SELECT ON SEQUENCES "
        "TO telemetry_app, telemetry_maint"
    )

    # ── 4. FORCE RLS sweep ────────────────────────────────────────────
    # Every table with RLS enabled must also FORCE it so the table OWNER is
    # subject to the policies too (defence in depth — the app should no
    # longer connect as the owner at all, but FORCE removes the foot-gun).
    op.execute(
        """
        DO $$
        DECLARE
            t record;
        BEGIN
            FOR t IN
                SELECT c.relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relkind IN ('r', 'p')
                  AND c.relrowsecurity
                  AND NOT c.relforcerowsecurity
            LOOP
                EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', t.relname);
            END LOOP;
        END
        $$;
        """
    )

    # ── 5. audit_log system-events policy ─────────────────────────────
    # Webhook/system audit rows carry no workspace; the tenant policy's
    # WITH CHECK rejects them for non-superusers. Permissive policies OR
    # together, so this only ADDS the NULL-workspace insert path. Such rows
    # stay invisible to the app role's SELECT (tenant USING governs reads);
    # admin reads them via telemetry_maint (BYPASSRLS).
    op.execute(
        'DROP POLICY IF EXISTS "audit_log_system_events" ON "audit_log"'
    )
    op.execute(
        'CREATE POLICY "audit_log_system_events" ON "audit_log" '
        "FOR INSERT WITH CHECK (workspace_id IS NULL)"
    )


def downgrade() -> None:
    # Deliberately conservative: dropping cluster-wide roles or un-forcing
    # RLS on a live multi-tenant DB is a security regression we refuse to
    # automate. Only the additive audit_log policy is reverted; roles,
    # grants, default privileges and FORCE state are left in place.
    op.execute(
        'DROP POLICY IF EXISTS "audit_log_system_events" ON "audit_log"'
    )
