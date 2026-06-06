# LAP production launch-deploy runbook

Full go-live sequence for `feat/founding-50-offer`. Complements
[`rls-cutover-runbook.md`](./rls-cutover-runbook.md) (which covers the RLS DSN
switch in depth) — this is the end-to-end order.

- **Branch:** `feat/founding-50-offer`
- **VPS:** `root@46.225.227.24:/opt/lap-api`
- **API:** `api.lap-coach.racing` · **Web worker:** `lap-website` (serves
  `lap-coach.racing/app/*` AND `lap-website.theos-eleve.workers.dev` — same worker)

> Ordering principle: the **RLS cutover + migrations land with the backend**, and
> the **frontend goes last**. Do not deploy the new webapp UI to `lap-website`
> until the backend matches it (the frontend talks to `api.lap-coach.racing`).

> ⚠️ Do NOT run `scripts/deploy.sh` blindly: its Stage-1 pre-flight is
> `pytest tests/ -x`, which stops at the first failure and will abort on the
> documented pre-existing test failures (stale-mock account-purge test,
> theoretical/corner-positions, admin-middleware param-style). Use the manual
> commands below (the same ones the script runs internally), or pre-deselect
> those tests.

---

## Phase 0 — Prerequisites

Confirm the live env has the required secrets:

```bash
ssh root@46.225.227.24 "grep -E 'STRIPE_PRICE_STANDARD_MONTHLY|STRIPE_PRICE_FOUNDING_MONTHLY|EMAIL_FROM|SENTRY_DSN_API|SENTRY_DSN_WORKER' /opt/lap-api/.env.production"
```

Must show: both live Stripe price IDs, `EMAIL_FROM=team@lap-coach.racing`, Sentry
DSNs. Missing Stripe prices → run `scripts/setup_stripe_products.py` locally and
set the printed IDs. `SIDECAR_ROOT=/data/sidecars` is already in
`docker-compose.prod.yml`.

## Phase 1 — Apply-test migrations 067 + 068 on a throwaway clone

(Could not be done from the dev sandbox — do it against a temp DB, never prod.)

```bash
ssh root@46.225.227.24
cd /opt/lap-api
docker compose exec -T postgres pg_dump -U telemetry --schema-only telemetry > /tmp/schema.sql
docker compose exec -T postgres psql -U telemetry -c "CREATE DATABASE migtest"
docker compose exec -T postgres psql -U telemetry -d migtest -f /tmp/schema.sql
docker compose exec -T -w /app/telemetry_tool api env TELEMETRY_PG_URL=postgresql://telemetry@postgres:5432/migtest alembic stamp 066_workspace_storage_quota
docker compose exec -T -w /app/telemetry_tool api env TELEMETRY_PG_URL=postgresql://telemetry@postgres:5432/migtest alembic upgrade head
docker compose exec -T postgres psql -U telemetry -c "DROP DATABASE migtest"
```

**Gate:** `upgrade head` exits 0 and reaches `068_fk_child_read_rls`; 067's index
builds without error.

## Phase 2 — RLS cutover (P0-A), part A

Temporarily allow the privileged DSN so the app can boot while the deploy's
migration step creates the `telemetry_app`/`telemetry_maint` roles (064):

```bash
ssh root@46.225.227.24 "echo 'TELEMETRY_ALLOW_PRIVILEGED_DB=1' >> /opt/lap-api/.env.production"
```

Then run Phase 3. **After** the backend deploy succeeds, continue with Phase 2B.

## Phase 3 — Backend deploy (from the `lap_web-wt-founding50` worktree)

```bash
cd /c/Users/Admin/lap_web-wt-founding50
scp -r telemetry_tool/ root@46.225.227.24:/opt/lap-api/
scp docker-compose.prod.yml root@46.225.227.24:/opt/lap-api/
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose build api celery-pipeline celery-default celery-beat && docker compose up -d api celery-pipeline celery-default celery-beat"
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose exec -T -w /app/telemetry_tool api alembic upgrade head && docker compose exec -T -w /app/telemetry_tool api alembic current"
```

**Gate:** `alembic current` → `068_fk_child_read_rls (head)`;
`curl -s https://api.lap-coach.racing/healthz` → `{"status":"ok"...}`.

## Phase 2 — RLS cutover (P0-A), part B (after Phase 3)

```bash
# set role passwords (generate two strong ones; never commit)
docker compose exec -T postgres psql -U telemetry -c "ALTER ROLE telemetry_app   LOGIN PASSWORD '<pw1>';"
docker compose exec -T postgres psql -U telemetry -c "ALTER ROLE telemetry_maint LOGIN PASSWORD '<pw2>';"
```

Edit `/opt/lap-api/.env.production`:

```
TELEMETRY_PG_URL=postgresql://telemetry_app:<pw1>@postgres:5432/telemetry
TELEMETRY_PG_MAINT_URL=postgresql://telemetry_maint:<pw2>@postgres:5432/telemetry
TELEMETRY_PG_MIGRATION_URL=postgresql://telemetry:${PG_PASSWORD}@postgres:5432/telemetry
# celery-* services: TELEMETRY_PG_URL must point DIRECT at postgres:5432, NOT pgbouncer
#   (the worker persist path uses a session-scoped SET that transaction-pooling drops)
# REMOVE the TELEMETRY_ALLOW_PRIVILEGED_DB=1 line added in Phase 2A
```

```bash
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose up -d api celery-pipeline celery-default celery-beat"
```

**Gate:** logs show `RLS enforcement check OK — app role is non-privileged` for
both the api and the worker boot guard. If a DSN is still privileged the
processes refuse to boot — that is the guard working.

## Phase 4 — Frontend deploy (the real `lap-website` worker = live `lap-coach.racing/app/*`)

```bash
cd /c/Users/Admin/lap_web-wt-founding50/lap-website
NEXT_PUBLIC_API_URL=https://api.lap-coach.racing CLOUDFLARE_ACCOUNT_ID=2d81a695df4b36d38ee2edef8385005a npm run cf:deploy
```

Both env vars mandatory (build throws otherwise). wrangler must be the
`theos.eleve@gmail.com` account.

## Phase 5 — Post-deploy verification

```sql
SELECT rolname,rolsuper,rolbypassrls FROM pg_roles WHERE rolname IN ('telemetry_app','telemetry_maint');
SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='public' AND c.relrowsecurity AND NOT c.relforcerowsecurity;   -- expect 0 rows
SELECT tablename FROM pg_policies WHERE policyname LIKE '%_ws_via_parent';        -- expect the 8 FK-child tables
```

- **P0-B smoke:** GDPR export for a real non-admin account → ZIP must contain
  non-empty `sessions.json` + `gps_traces.json`.
- **Delete smoke:** delete a session in the UI → gone, and STAYS gone on reload;
  confirm `deleted_at` set (soft delete), not a hard delete.
- Watch overnight beat jobs: rollups, retention, the new
  `purge_soft_deleted_sessions`, usage aggregation, partition rotation.

## Rollback

- **RLS only:** set `TELEMETRY_ALLOW_PRIVILEGED_DB=1` + point `TELEMETRY_PG_URL`
  back at `telemetry`, restart (re-opens the P0 — emergency only).
- **Frontend:** `npx wrangler rollback` on the `lap-website` worker.
- Migration 064's downgrade intentionally does NOT drop roles / un-FORCE tables.

## Notes

- Migration `068_fk_child_read_rls` closes the FK-child defense-in-depth
  follow-up that `rls-cutover-runbook.md` listed as P1.
- The `founding-50 → main` merge will conflict in the 3 session-delete files
  (`data_v2.py`, `audit.py`, `sessions/page.tsx`) — resolve by keeping the
  founding-50 version (it carries the purge file-cleanup).
- Do not touch the waitlist flow during this deploy.
