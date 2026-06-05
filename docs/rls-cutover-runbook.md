# RLS cutover runbook — P0 cross-tenant isolation fix

**Status:** branch-only (`feat/founding-50-offer`), NOT deployed.
**Fixes:** launch-audit P0 (2026-06-03) — prod app connects as the `telemetry`
bootstrap **superuser** (`rolsuper=t, rolbypassrls=t`), so every row-level
security policy is silently bypassed and tenants can read each other's data
(documented in `lap-website/e2e/certification-live.spec.ts:235`).

## What the code now expects

Three DSNs, three privilege levels:

| Env var | Role | Privileges | Used by |
|---|---|---|---|
| `TELEMETRY_PG_URL` | `telemetry_app` | NOSUPERUSER, NOBYPASSRLS — RLS enforced | Web requests, Celery pipeline/rollup tasks (all tenant traffic) |
| `TELEMETRY_PG_MAINT_URL` | `telemetry_maint` | NOSUPERUSER, **BYPASSRLS** | Legitimately cross-tenant jobs: retention enforcement (`tasks/retention_tasks.py`), usage aggregation (`tasks/usage_tasks.py`), admin storage metrics (`web/routes/admin/infra.py`) |
| `TELEMETRY_PG_MIGRATION_URL` | `telemetry` (owner) | Owner/superuser — DDL | Alembic (deploy + `init_pg`), partition rotation (`tasks/archival_tasks.py`) |

Both new vars **fall back to `TELEMETRY_PG_URL`** when unset, so dev/test
single-role environments keep working unchanged.

Migration `064_rls_enforcement` (applied by the normal deploy migration step)
creates/repairs the roles idempotently, grants table/sequence privileges
(+ default privileges for future migrations), FORCEs RLS on every
ENABLE-but-not-FORCE table, and adds the `audit_log` system-events policy
(the Stripe webhook writes workspace-less audit rows).

**Startup guard:** with `AUTH_REQUIRED=1`, the app now **refuses to start**
if `TELEMETRY_PG_URL` connects as a superuser/BYPASSRLS role.
Escape hatch (dev only): `TELEMETRY_ALLOW_PRIVILEGED_DB=1`.

## Cutover steps (prod, ~10 min, do during low traffic)

1. **Deploy the branch** as usual. The deploy migration step (running as
   `telemetry` via the existing DSN) applies 064 → roles exist, grants set,
   RLS forced. **The app is still on the superuser DSN at this point and
   will refuse to boot** because of the startup guard — set the env first
   (step 3) or deploy code+env together.

2. **Set passwords** (roles are created without one — never in git):

   ```sql
   ALTER ROLE telemetry_app   LOGIN PASSWORD '<generate-strong-1>';
   ALTER ROLE telemetry_maint LOGIN PASSWORD '<generate-strong-2>';
   ```

3. **Update `.env.production`:**

   ```bash
   TELEMETRY_PG_URL=postgresql://telemetry_app:<pw1>@postgres:5432/telemetry
   TELEMETRY_PG_MAINT_URL=postgresql://telemetry_maint:<pw2>@postgres:5432/telemetry
   TELEMETRY_PG_MIGRATION_URL=postgresql://telemetry:${PG_PASSWORD}@postgres:5432/telemetry
   ```

4. **pgbouncer — IMPORTANT.** `docker-compose.prod.yml` runs pgbouncer with
   `POOL_MODE: transaction`. Two constraints:
   - The middleware path uses `SET LOCAL` (transaction-scoped) — **safe**
     under transaction pooling.
   - The Celery persist path (`tasks/pipeline_tasks.py::_persist_session_data`)
     uses a **session-scoped** `SET app.current_workspace_id` that does NOT
     survive transaction pooling (the GUC lands on one server connection,
     later statements run on others). **Point the workers' `TELEMETRY_PG_URL`
     directly at `postgres:5432`, not at pgbouncer**, or switch pgbouncer to
     a session-mode pool for the worker user. Web traffic may stay on
     pgbouncer.
   - If pgbouncer carries per-user pools, add the two new users to its
     `auth_file`/`auth_query` config.

5. **Restart** api + workers. The startup guard should log
   `RLS enforcement check OK — app role is non-privileged`.

6. **Verify** (read-only):

   ```sql
   -- 1. no privileged app role
   SELECT rolname, rolsuper, rolbypassrls FROM pg_roles
    WHERE rolname IN ('telemetry_app','telemetry_maint');
   -- 2. nothing left ENABLE-but-not-FORCE
   SELECT c.relname FROM pg_class c
    JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relrowsecurity AND NOT c.relforcerowsecurity;
   ```

   Then the live e2e: `lap-website/e2e/certification-live.spec.ts` — the
   "Tenant Isolation" tests can now be hardened from structure-only checks
   to real isolation asserts (line 235's KNOWN ISSUE comment becomes stale).

7. **Watch:** upload→report E2E for one session (pipeline persist path),
   one admin storage-metrics page load (maint path), Stripe webhook delivery
   (system audit insert). Beat jobs to watch overnight: rollups, retention,
   usage aggregation, partition rotation.

## Rollback

Set `TELEMETRY_ALLOW_PRIVILEGED_DB=1` and point `TELEMETRY_PG_URL` back at
the `telemetry` user, restart. (This re-opens the P0 — emergency-only.)
Migration 064's downgrade intentionally does NOT drop roles or un-FORCE
tables; it only removes the audit_log system policy.

## Known follow-ups (P1, not launch-blocking)

- Tables tenant-scoped only via parent FK (`race_strategies`, `kart_sessions`,
  `sector_times`, `stint_laps`, `tyre_degradation`, …, from migrations
  011–015) have **no workspace_id and no RLS**. App queries reach them via
  RLS-filtered parent JOINs, but defence-in-depth policies
  (EXISTS-subquery to the parent) are still worth adding.
- `dead_letter_queue` / `retention_audit` have nullable `workspace_id` and
  no RLS (operational tables; app role has table grants).
- `_persist_session_data`'s session-scoped GUC should eventually become
  per-transaction `SET LOCAL` so workers can also sit behind pgbouncer.
