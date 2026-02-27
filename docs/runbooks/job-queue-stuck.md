# Runbook: Job Queue Stuck

## Symptoms
- Users report uploads "stuck at processing"
- `ingestion_jobs` table has rows with `status='processing'` for >30 minutes
- Celery workers not consuming tasks from Redis

## Diagnosis

### 1. Check worker health
```bash
ssh root@46.225.227.24
cd /opt/lap-api

# Check worker containers are running
docker compose -f docker-compose.prod.yml ps celery-pipeline celery-default

# Check worker logs for errors
docker compose -f docker-compose.prod.yml logs --tail=50 celery-pipeline
docker compose -f docker-compose.prod.yml logs --tail=50 celery-default
```

### 2. Check Redis broker
```bash
# Redis must be healthy (Celery broker)
docker compose -f docker-compose.prod.yml exec redis redis-cli ping
# PONG = OK

# Check queue lengths
docker compose -f docker-compose.prod.yml exec redis redis-cli LLEN pipeline
docker compose -f docker-compose.prod.yml exec redis redis-cli LLEN default
```

### 3. Check for stuck tasks in DB
```bash
docker compose -f docker-compose.prod.yml exec postgres psql -U telemetry -c "
SELECT id, file_name, status, started_at, NOW() - started_at AS duration
FROM ingestion_jobs
WHERE status = 'processing'
ORDER BY started_at;
"
```

## Resolution

### Workers crashed / OOM killed
```bash
# Check if workers were OOM killed
docker compose -f docker-compose.prod.yml logs --tail=100 celery-pipeline | grep -i "kill\|oom\|memory"

# Restart workers
docker compose -f docker-compose.prod.yml restart celery-pipeline celery-default
```

### Redis full
```bash
# Check Redis memory
docker compose -f docker-compose.prod.yml exec redis redis-cli INFO memory | grep used_memory_human

# If near maxmemory (128MB), tasks are being evicted
# Increase in docker-compose.prod.yml: --maxmemory 256mb
```

### Mark stuck tasks as failed
```bash
docker compose -f docker-compose.prod.yml exec postgres psql -U telemetry -c "
UPDATE ingestion_jobs
SET status = 'failed', error_message = 'Timed out — marked by operator'
WHERE status = 'processing' AND started_at < NOW() - INTERVAL '35 minutes';
"
```
Users can then retry these uploads.

### Pipeline lock stuck
If a worker dies mid-pipeline, the workspace processing lock may be held:
```bash
docker compose -f docker-compose.prod.yml exec redis redis-cli KEYS "pipeline:lock:*"
# Delete stale locks:
docker compose -f docker-compose.prod.yml exec redis redis-cli DEL "pipeline:lock:<workspace_id>"
```

## Prevention
- Workers have `--soft-time-limit=1800` (30min) and `--time-limit=2100` (35min)
- `--max-tasks-per-child=50` recycles workers to prevent memory leaks
- Celery beat runs health checks; Docker restarts unhealthy containers
