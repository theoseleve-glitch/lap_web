# Lap Platform — Observability, SLOs, Incident Management

## SLOs (Service Level Objectives)

| Journey | Target Avail. | Latency p95 | Latency p99 | Measurement | Error Budget (30d) |
|---------|--------------|-------------|-------------|-------------|-------------------|
| Login (OAuth) | 99.9% | <500ms | <1.5s | `POST /auth/login`, `GET /auth/callback/*` status != 5xx | 43 min downtime |
| Upload | 99.5% | <3s (small) | <10s (small) | `POST /api/v1/sessions/upload` status != 5xx | 3.6 hr downtime |
| Analysis pipeline | 99.0% | <30s | <120s | Upload → pipeline complete (ingestion_jobs.status=completed) | 7.3 hr downtime |
| Compare | 99.5% | <2s | <5s | `GET /api/v1/sessions/compare` status != 5xx | 3.6 hr downtime |
| Export (PDF/CSV) | 99.0% | <5s | <15s | `GET /api/v1/sessions/:id/report` status != 5xx | 7.3 hr downtime |
| Health endpoint | 99.99% | <100ms | <200ms | `GET /healthz` status=200 | 4.3 min downtime |

### Error Budget Policy
- **Budget consumed >50%**: Alert, investigate top errors
- **Budget consumed >75%**: Feature freeze, focus on reliability
- **Budget consumed >90%**: Incident declared, all hands on reliability

---

## Incident Severity Matrix

| SEV | Impact | Response Time | Example | Who |
|-----|--------|--------------|---------|-----|
| SEV-0 | Total outage, data loss risk | <15 min | DB corruption, full API down, backup failure | All hands |
| SEV-1 | Major feature broken for all users | <30 min | Upload failing, auth broken, Stripe webhooks failing | On-call + backend lead |
| SEV-2 | Feature degraded or broken for some | <2 hr | Slow analysis, intermittent 500s, queue backlog | On-call |
| SEV-3 | Minor issue, workaround exists | Next business day | UI glitch, non-critical log errors, stale cache | Assigned engineer |

---

## Incident Communication Templates

### Internal (Slack/Discord)

```
[SEV-{N}] {title}
Status: INVESTIGATING | IDENTIFIED | MONITORING | RESOLVED
Impact: {who is affected, what is broken}
Timeline:
  {HH:MM UTC} — {event}
Next update: {HH:MM UTC}
Lead: {name}
```

### Customer-Facing (Status Page)

```
**{title}**
We are currently experiencing {brief description}.
{percentage}% of users may be affected.
Our team is actively working on a resolution.
Last updated: {timestamp UTC}
```

---

## Incident Runbooks

### R1: Database Down

**Symptoms**: `/healthz` returns `"db": "error"`, 500s on all data endpoints
**Diagnosis**:
```bash
ssh root@46.225.227.24
cd /opt/lap-api
docker compose -f docker-compose.prod.yml logs postgres --tail 50
docker compose -f docker-compose.prod.yml exec postgres pg_isready -U telemetry
```
**Resolution**:
1. Check disk space: `df -h /var/lib/docker/volumes/`
2. If OOM: increase `shared_buffers` or VPS RAM
3. If corrupted: restore from latest backup (see DR plan)
4. Restart: `docker compose -f docker-compose.prod.yml restart postgres pgbouncer`
5. Wait for healthcheck, then restart API: `docker compose restart api`
6. Verify: `curl -sf https://api.lap-coach.racing/healthz | jq .`

### R2: Redis Down

**Symptoms**: `/healthz` returns `"redis": "error"`, rate limiting disabled, Celery tasks not queuing
**Diagnosis**:
```bash
docker compose -f docker-compose.prod.yml logs redis --tail 50
docker compose -f docker-compose.prod.yml exec redis redis-cli ping
```
**Resolution**:
1. Check memory: `docker compose exec redis redis-cli info memory`
2. If OOM: increase `maxmemory` or flush non-critical keys
3. Restart: `docker compose restart redis`
4. Restart workers: `docker compose restart celery-pipeline celery-default`
5. API continues to function (rate limiting fails-open)

### R3: Celery Worker Backlog

**Symptoms**: Jobs stuck in "queued", upload endpoint returns 200 but pipeline never completes
**Diagnosis**:
```bash
docker compose exec redis redis-cli LLEN pipeline
docker compose exec redis redis-cli LLEN default
docker compose logs celery-pipeline --tail 100
```
**Resolution**:
1. Check if workers are alive: `docker compose exec celery-pipeline celery inspect ping`
2. If workers crashed: `docker compose restart celery-pipeline celery-default`
3. If backlog is growing: scale temporarily with `docker compose up -d --scale celery-pipeline=3`
4. If tasks are stuck: check for deadlocks in PG, restart specific worker

### R4: Stripe Webhook Failures

**Symptoms**: Billing events not processing, `stripe_webhook_events_total{outcome="error"}` elevated
**Diagnosis**:
```bash
docker compose logs api --tail 200 | grep -i webhook
# Check Stripe dashboard: Developers → Webhooks → Recent Events
```
**Resolution**:
1. Check webhook signature: ensure `STRIPE_WEBHOOK_SECRET` matches Stripe dashboard
2. If endpoint unreachable: check Caddy logs, DNS, TLS certificate
3. If processing errors: check API logs for stack traces
4. Stripe retries failed webhooks for up to 3 days — no data loss if resolved within window
5. Manual reconciliation: `docker compose exec api python -c "from telemetry_tool.tasks.billing_tasks import reconcile_stripe_subscriptions; reconcile_stripe_subscriptions()"`

### R5: High Memory / OOM

**Symptoms**: Container restarts, slow responses, healthcheck failures
**Diagnosis**:
```bash
docker stats --no-stream
docker compose logs api --tail 50 | grep -i "memory\|killed\|oom"
```
**Resolution**:
1. Identify the culprit container (`docker stats`)
2. If API: large upload consuming memory — restart worker, check INGEST_V2 is enabled
3. If PG: increase `shared_buffers`, run `VACUUM FULL` on large tables
4. If Redis: check `maxmemory` setting, review eviction policy
5. Long-term: upgrade VPS RAM

---

## RTO/RPO

| Component | RPO | RTO | Method |
|-----------|-----|-----|--------|
| PostgreSQL | 24 hr (daily backup) | 1 hr | pg_restore from S3 backup |
| Redis | N/A (ephemeral) | 5 min | Restart container; data rebuilt on demand |
| Object storage (uploads) | 24 hr | 2 hr | Restore Docker volumes from backup |
| App config | 0 (git) | 15 min | git pull + docker compose up |

### DR Recovery Order

1. **PostgreSQL** — restore DB first (all state lives here)
2. **Redis** — restart (stateless, Celery resubmits)
3. **API + Workers** — restart containers
4. **Caddy** — restart (stateless, config in git)
5. **Verify**: Run `/healthz`, check all services "ok"

### Full DR Steps

```bash
# 1. Provision new VPS (if needed)
# 2. Clone repo
git clone <repo-url> /opt/lap-api && cd /opt/lap-api

# 3. Restore .env.production from secure storage (1Password/Vault)

# 4. Start infrastructure
docker compose -f docker-compose.prod.yml up -d postgres redis

# 5. Wait for PG healthy
docker compose -f docker-compose.prod.yml exec postgres pg_isready -U telemetry

# 6. Restore DB from S3
aws s3 cp s3://${S3_BUCKET}/backups/daily/latest.dump /tmp/restore.dump \
  --endpoint-url ${S3_ENDPOINT}
# Decrypt if encrypted
gpg --batch --yes --decrypt --passphrase "$BACKUP_ENCRYPTION_KEY" \
  --output /tmp/restore_plain.dump /tmp/restore.dump
pg_restore --dbname="$TELEMETRY_PG_URL" --no-owner --clean --if-exists /tmp/restore_plain.dump

# 7. Run pending migrations
docker compose -f docker-compose.prod.yml exec api alembic upgrade head

# 8. Start all services
docker compose -f docker-compose.prod.yml up -d

# 9. Verify
curl -sf https://api.lap-coach.racing/healthz | jq .
```

---

## Capacity Plan

### Current Specs (Hetzner VPS)

| Resource | Current | Usage |
|----------|---------|-------|
| CPU | 4 vCPU (shared) | ~20% avg, ~80% during analysis |
| RAM | 8 GB | ~60% (PG 2GB, API 1.5GB, Celery 2GB, Redis 128MB) |
| Disk | 80 GB SSD | ~40% (PG data, Docker images, uploads) |
| Network | 20 TB/mo | ~5% used |

### Capacity Limits

| Metric | Current Max | Bottleneck |
|--------|------------|------------|
| Concurrent API users | ~50 | Gunicorn workers (4 sync) |
| Concurrent analyses | 2 | Celery pipeline queue concurrency |
| Uploads/hour | 10 per user | Rate limit + pipeline throughput |
| DB connections | 100 (via PgBouncer) | 20 to PG, 100 client-side |
| Storage | ~40 GB free | Parquet + upload accumulation |

### Scaling Triggers

| Trigger | Threshold | Action |
|---------|-----------|--------|
| CPU sustained >75% for 1hr | Alert | Upgrade to dedicated vCPU or add worker |
| RAM >80% sustained | Alert | Upgrade VPS RAM |
| Disk >70% | Alert | Prune old data, expand disk |
| Pipeline queue >20 tasks for >10min | Alert | Scale celery-pipeline workers |
| PG connections >80 | Alert | Tune PgBouncer, check for leaks |
| p95 latency >2s sustained | SLO breach | Profile, optimize, or horizontal scale |

### Next Scaling Steps

1. **Vertical**: Hetzner CPX41 (8 vCPU, 16 GB) — simplest, ~2x capacity
2. **Horizontal**: Separate PG to managed DB (Hetzner Cloud SQL), API to 2 nodes behind LB
3. **Object storage**: Move uploads/exports to Hetzner Object Storage (S3-compatible)
4. **CDN**: Cloudflare R2 for report PDFs / export downloads
