# Runbook: Upload Failures

## Symptoms
- Users report "upload failed" or "processing failed" errors
- Ingestion jobs stuck in `pending` or `failed` status
- Disk space alerts from Docker volumes

## Diagnosis

### 1. Check disk space
```bash
ssh root@46.225.227.24

# Host disk
df -h /

# Docker volumes
docker system df
docker volume ls --format "{{.Name}}: {{.Size}}" 2>/dev/null || docker system df -v | grep "VOLUME"
```

### 2. Check recent failed jobs
```bash
cd /opt/lap-api
docker compose -f docker-compose.prod.yml exec postgres psql -U telemetry -c "
SELECT id, file_name, status, error_message, created_at
FROM ingestion_jobs
WHERE status = 'failed'
ORDER BY created_at DESC
LIMIT 10;
"
```

### 3. Check upload directory
```bash
docker compose -f docker-compose.prod.yml exec api ls -lah /data/uploads/ | tail -20
docker compose -f docker-compose.prod.yml exec api du -sh /data/uploads/
docker compose -f docker-compose.prod.yml exec api du -sh /data/parquet/
docker compose -f docker-compose.prod.yml exec api du -sh /data/exports/
```

### 4. Check worker logs for errors
```bash
docker compose -f docker-compose.prod.yml logs --tail=50 celery-pipeline | grep -i "error\|fail\|exception"
```

## Resolution

### Disk full
```bash
# Clean old exports (>7 days — normally done by Celery beat)
docker compose -f docker-compose.prod.yml exec api find /data/exports -name "*.zip" -mtime +7 -delete

# Clean old upload files (>30 days)
docker compose -f docker-compose.prod.yml exec api find /data/uploads -name "*.csv" -mtime +30 -delete

# Docker cleanup
docker system prune -f
docker image prune -a -f --filter "until=168h"  # remove images >7 days old
```

### File validation errors
If uploads fail with "binary" or "not CSV" errors:
- User is uploading wrong file type
- Validation is working correctly (Phase 2 hardening)
- No action needed — inform user to upload valid CSV

### Pipeline processing errors
```bash
# Check specific job error
docker compose -f docker-compose.prod.yml exec postgres psql -U telemetry -c "
SELECT error_message, peak_rss_mb, throughput_mb_s
FROM ingestion_jobs WHERE id = <JOB_ID>;
"

# If OOM: file too large for direct upload, user should use streaming ingest
# If timeout: check celery-pipeline worker soft-time-limit (30min)
```

### Temp directory leaks
If `/tmp` fills up from cancelled uploads:
```bash
docker compose -f docker-compose.prod.yml exec api find /tmp -name "telemetry_*" -mtime +1 -delete
docker compose -f docker-compose.prod.yml exec celery-pipeline find /tmp -name "telemetry_*" -mtime +1 -delete
```

## Prevention
- Celery beat `cleanup_expired_exports` runs daily (removes ZIPs >7 days)
- Upload validation rejects binary files, double extensions, single-column CSVs
- 500MB size limit on direct upload route; streaming ingest for larger files
- Worker `--max-tasks-per-child=50` prevents memory leak accumulation
