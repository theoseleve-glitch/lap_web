# Rollback Procedures

Emergency rollback procedures for Lap Coach SaaS platform.

## 1. Backend Rollback

### Revert to previous Docker image

```bash
ssh root@46.225.227.24
cd /opt/lap-api

# List recent images
docker images lap-api --format "table {{.Repository}}\t{{.Tag}}\t{{.CreatedAt}}" | head -5

# Restart with previous image (Compose rebuilds from source)
git log --oneline -5  # find previous commit
git checkout <previous-commit>
docker compose build api
docker compose up -d api

# Verify
curl -sf https://api.lap-coach.racing/healthz | jq .
```

### Revert Alembic migration

```bash
ssh root@46.225.227.24
cd /opt/lap-api

# Check current migration
docker compose exec api alembic current

# Downgrade one step
docker compose exec api alembic downgrade -1

# Verify
docker compose exec api alembic current

# Restart API to pick up schema changes
docker compose restart api
```

**Warning**: Destructive migrations (DROP COLUMN, DROP TABLE) cannot be reversed.
Check the migration file before running downgrade.

## 2. Frontend Rollback

### Cloudflare Workers rollback

```bash
cd lap-website

# Cloudflare Workers keeps previous deployments
npx wrangler rollback

# Or deploy a specific previous version
git checkout <previous-commit>
npm run cf:deploy
```

### Verify frontend

```bash
curl -sf https://lap-coach.racing | head -1
# Should return HTML
```

## 3. Database Rollback

### Restore from daily backup

```bash
ssh root@46.225.227.24
cd /opt/lap-api/backups

# List available backups
ls -la daily/

# Stop API to prevent writes during restore
docker compose stop api

# Restore from backup
docker compose exec -T postgres pg_restore \
  --dbname=telemetry \
  --clean --if-exists \
  --no-owner \
  daily/telemetry_YYYY-MM-DD.dump

# Restart API
docker compose start api

# Verify
curl -sf https://api.lap-coach.racing/healthz | jq .
```

**Warning**: This replaces ALL data since the backup. Any writes between
the backup time and now will be lost.

## 4. Feature Flag Rollback

Disable new features without redeployment by toggling env vars:

```bash
ssh root@46.225.227.24
cd /opt/lap-api

# Edit .env.production
# AUTH_REQUIRED=0       → Disable auth enforcement
# RATE_LIMIT_ENABLED=0  → Disable rate limiting
# TELEMETRY_INGEST_V2=0 → Revert to legacy ingest

# Restart to pick up changes
docker compose restart api
```

Key feature flags:

| Variable | Default | Effect when OFF |
|----------|---------|-----------------|
| `AUTH_REQUIRED` | `1` | No JWT auth enforcement |
| `USE_PG` | `1` | Falls back to SQLite (desktop mode) |
| `RATE_LIMIT_ENABLED` | `1` | No rate limiting |
| `TELEMETRY_INGEST_V2` | `1` | Legacy single-read ingest |

## Decision Tree

```
Is the issue...

├── API returning 500s?
│   ├── Check logs: docker compose logs api --tail=50
│   ├── Migration issue? → alembic downgrade -1
│   └── Code issue? → git checkout + rebuild
│
├── Frontend broken?
│   ├── npx wrangler rollback
│   └── Or: git checkout + npm run cf:deploy
│
├── Data corruption?
│   ├── Stop API first
│   ├── pg_restore from daily backup
│   └── Accept data loss since backup
│
└── Feature causing issues?
    ├── Toggle feature flag in .env
    └── docker compose restart api
```

## Post-Rollback Checklist

1. Verify health endpoint: `curl https://api.lap-coach.racing/healthz`
2. Verify frontend loads: `curl https://lap-coach.racing`
3. Test login flow manually
4. Check error logs: `docker compose logs api --tail=100`
5. Notify team of rollback and root cause
