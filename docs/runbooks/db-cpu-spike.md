# Runbook: Database CPU Spike

## Symptoms
- API responses slow (>2s)
- `/healthz` returns 503 (DB check timeout)
- PostgreSQL container high CPU in `docker stats`

## Diagnosis

### 1. Check running queries
```bash
ssh root@46.225.227.24
cd /opt/lap-api

docker compose -f docker-compose.prod.yml exec postgres psql -U telemetry -c "
SELECT pid, NOW() - query_start AS duration, state, LEFT(query, 100) AS query
FROM pg_stat_activity
WHERE state != 'idle' AND query NOT LIKE '%pg_stat_activity%'
ORDER BY duration DESC
LIMIT 10;
"
```

### 2. Check for lock contention
```bash
docker compose -f docker-compose.prod.yml exec postgres psql -U telemetry -c "
SELECT blocked.pid AS blocked_pid,
       blocked.query AS blocked_query,
       blocking.pid AS blocking_pid,
       blocking.query AS blocking_query
FROM pg_stat_activity blocked
JOIN pg_locks bl ON bl.pid = blocked.pid
JOIN pg_locks kl ON kl.locktype = bl.locktype
  AND kl.database IS NOT DISTINCT FROM bl.database
  AND kl.relation IS NOT DISTINCT FROM bl.relation
  AND kl.page IS NOT DISTINCT FROM bl.page
  AND kl.tuple IS NOT DISTINCT FROM bl.tuple
  AND kl.virtualxid IS NOT DISTINCT FROM bl.virtualxid
  AND kl.transactionid IS NOT DISTINCT FROM bl.transactionid
  AND kl.classid IS NOT DISTINCT FROM bl.classid
  AND kl.objid IS NOT DISTINCT FROM bl.objid
  AND kl.objsubid IS NOT DISTINCT FROM bl.objsubid
  AND kl.pid != bl.pid
JOIN pg_stat_activity blocking ON blocking.pid = kl.pid
WHERE NOT bl.granted
LIMIT 5;
"
```

### 3. Check table sizes and missing indexes
```bash
docker compose -f docker-compose.prod.yml exec postgres psql -U telemetry -c "
SELECT schemaname, relname, seq_scan, idx_scan,
       pg_size_pretty(pg_total_relation_size(relid)) AS size
FROM pg_stat_user_tables
WHERE seq_scan > 100
ORDER BY seq_scan DESC
LIMIT 10;
"
```

## Resolution

### Kill long-running queries
```bash
# Kill a specific query (replace PID)
docker compose -f docker-compose.prod.yml exec postgres psql -U telemetry -c "
SELECT pg_terminate_backend(<PID>);
"
```

### Add missing index
If `seq_scan` is high on a large table, check if an index would help:
```bash
# Example: if sessions table is doing seq scans
docker compose -f docker-compose.prod.yml exec postgres psql -U telemetry -c "
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sessions_workspace
ON sessions(workspace_id);
"
```

### VACUUM if bloated
```bash
docker compose -f docker-compose.prod.yml exec postgres psql -U telemetry -c "
VACUUM ANALYZE;
"
```

### Emergency: restart PostgreSQL
Last resort — drops all connections:
```bash
docker compose -f docker-compose.prod.yml restart postgres
# Wait for health check
docker compose -f docker-compose.prod.yml ps postgres
```

## Prevention
- RLS policies use indexed `workspace_id` columns
- Daily pg_dump backup at 3 AM UTC includes schema + data
- Monitor `pg_stat_user_tables.seq_scan` growth over time
