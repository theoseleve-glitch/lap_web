# W9 — Unified Ingest/Storage Rollback Runbook

## When to use this

Any of:
- `POST /api/v1/sessions/upload` error rate > 5% over 10 min after deploy.
- Celery `sim` workers crash-looping.
- Alembic 059 post-deploy leaves rows with NULL source/capabilities.
- User reports "session missing from list" after upload.

## Level 1 — runtime kill switch (≤ 2 min)

1. SSH to VPS: `ssh root@46.225.227.24`.
2. Edit `/opt/lap-api/.env.production` and set:
   ```
   INGEST_ROUTER_ENABLED=0
   ```
3. `docker compose -f /opt/lap-api/docker-compose.prod.yml restart api`
4. Verify: `curl https://api.lap-coach.racing/healthz` = 200.

At this point the new routing path is bypassed — the pre-W2 real-life-only
upload path runs.

## Level 2 — revert the merge (≤ 15 min)

1. `cd /opt/lap-api && git log --oneline | head -20`, find the W2+W9 merge commit.
2. On your dev box: `git revert -m 1 <merge-sha> && git push origin main`.
3. Trigger the regular deploy pipeline.
4. Workers will re-deploy without the `sim` queue; this is safe — no
   `tasks.sim_tasks.*` messages are in flight unless session #5 has landed.

## Level 3 — Alembic downgrade (≤ 30 min, invasive)

Only use if migration 059 is causing schema-level issues (unlikely — it
only adds three columns with defaults).

1. Take a DB backup FIRST: `/opt/lap-api/scripts/backup_pg.sh now`.
2. Stop the API: `docker compose stop api celery_pipeline celery_default celery_sim`.
3. Downgrade:
   ```bash
   docker compose run --rm api alembic downgrade 058
   ```
4. Restart with reverted code (Level 2 already done).
5. Verify `\d sessions` in psql — columns `source / data_profile / capabilities`
   should be gone.

## Level 4 — nuke sidecars (optional, data-loss)

Only if `/data/sidecars` is full or corrupted.

```bash
docker exec lap-api-1 rm -rf /data/sidecars
```

Raw re-analysis capability is lost for affected sessions until they are
re-uploaded.

## Contacts

- Deploy + infra: `ssh root@46.225.227.24`
- Alembic + schema: backend lead
- Celery behaviour: see `docs/runbooks/celery-queues.md`
