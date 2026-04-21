# Celery queues — operational reference

| Queue | Worker service | Concurrency | Mem ceiling | Typical task | SLA |
|-------|---------------|-------------|-------------|--------------|-----|
| `pipeline` | `celery_pipeline` | 2 | 2 GB | 14-stage real-life pipeline | 5 min p95 |
| `sim` | `celery_sim` *(add to docker-compose.prod.yml)* | 2 | 4 GB | iRacing IBT / AC | 10 min p95 |
| `default` | `celery_default` | 4 | 512 MB | billing, email, gdpr | 30 s p95 |

## Adding the `sim` worker service (docker-compose.prod.yml)

```yaml
celery_sim:
  build: .
  command: celery -A telemetry_tool.celery_app worker -Q sim -c 2 -l info
  environment:
    - CELERY_BROKER_URL=${REDIS_URL}
  depends_on: [redis, postgres]
  deploy:
    resources:
      limits:
        memory: 4G
```

## Symptom → fix

- `Queue sim is empty but tasks are being enqueued` → worker not running; `docker compose ps` then `docker compose up -d celery_sim`.
- `pipeline workers OOM under concurrent IBT + CSV load` → verify sim tasks actually route to `sim` (`celery inspect active_queues`), not `pipeline`.
- `sim worker import error` → `tasks.sim_tasks` not in `include=[...]` in `celery_app.py`.
