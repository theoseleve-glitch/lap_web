# GDPR Backlog Management

## Symptoms

- Users report export download links not working
- `data_exports` table has rows with `status='processing'` older than 1 hour
- `deleted_at` rows older than 30 days still exist in `users` table
- Disk usage growing in export directory

## Diagnosis

### Check export backlog

```sql
SELECT id, user_id, status, created_at, expires_at
FROM data_exports
WHERE status IN ('pending', 'processing')
ORDER BY created_at ASC;
```

### Check pending account deletions

```sql
SELECT id, email, deleted_at,
       deleted_at + INTERVAL '30 days' AS purge_due
FROM users
WHERE deleted_at IS NOT NULL
  AND deleted_at < NOW() - INTERVAL '30 days'
ORDER BY deleted_at ASC;
```

### Check Celery task status

```bash
docker compose exec api celery -A tasks.celery_app inspect active
docker compose exec api celery -A tasks.celery_app inspect reserved
```

### Check export directory disk usage

```bash
du -sh /data/exports/
ls -la /data/exports/ | wc -l
```

### Check retention enforcement status

```sql
-- Sessions past retention window that still have raw data
SELECT s.id, s.created_at, u.plan_tier,
       s.created_at + (pd.raw_retention_days || ' days')::INTERVAL AS expired_at
FROM sessions s
JOIN users u ON s.user_id = u.id
JOIN plan_definitions pd ON pd.slug = u.plan_tier
WHERE s.created_at + (pd.raw_retention_days || ' days')::INTERVAL < NOW()
  AND EXISTS (SELECT 1 FROM gps_traces g WHERE g.session_id = s.id)
ORDER BY expired_at ASC
LIMIT 20;
```

## Resolution

### Retry stuck exports

```bash
# Mark stuck exports as failed so users can re-request
docker compose exec api python -c "
from web.db_pg import get_pg_connection_standalone
conn = get_pg_connection_standalone()
conn.execute(\"\"\"
    UPDATE data_exports SET status = 'failed'
    WHERE status = 'processing'
    AND created_at < NOW() - INTERVAL '2 hours'
\"\"\")
conn.commit()
print('Done')
"
```

### Force export cleanup

```bash
docker compose exec api celery -A tasks.celery_app call tasks.gdpr_tasks.cleanup_expired_exports
```

### Force account purge

```bash
docker compose exec api celery -A tasks.celery_app call tasks.gdpr_tasks.purge_deleted_accounts
```

### Force retention enforcement

```bash
docker compose exec api celery -A tasks.celery_app call tasks.gdpr_tasks.enforce_raw_data_retention
```

### Manually re-trigger a specific export

```bash
docker compose exec api python -c "
from tasks.gdpr_tasks import export_user_data
export_user_data.delay(user_id=USER_ID, export_id=EXPORT_ID)
print('Task dispatched')
"
```

## Prevention

- Monitor `data_exports` table for stuck rows (`status='processing'` older than 1h)
- Monitor disk usage on export volume
- Verify Celery beat schedule includes all GDPR tasks:
  - `enforce-raw-data-retention` (daily 2:15 AM)
  - `purge-deleted-accounts` (daily)
  - `cleanup-expired-exports` (daily)
- Set alerting on `purge_deleted_accounts` task failures
- Review export directory size weekly
