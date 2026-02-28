# 5xx Origin Errors (Cloudflare / Caddy)

## Symptoms

- Users see 502 Bad Gateway or 503 Service Unavailable
- Cloudflare shows "Error 521: Web server is down" or "Error 522: Connection timed out"
- API health check fails from external but works from VPS localhost
- `scripts/verify_production.sh` reports failures on API health or security headers

## Diagnosis

### Check if API container is running

```bash
ssh root@46.225.227.24
cd /opt/lap-api
docker compose ps
docker compose logs api --tail=50
```

### Check Caddy logs

```bash
docker compose logs caddy --tail=50
```

### Check if Gunicorn workers are alive

```bash
docker compose exec api ps aux | grep gunicorn
```

### Check TLS certificate

```bash
curl -vI https://api.lap-coach.racing 2>&1 | grep -i "ssl\|certificate\|expire"
```

### Check if ports 443/80 are listening

```bash
ss -tlnp | grep -E ':(80|443)\s'
```

### Check system resources

```bash
free -h
df -h
docker stats --no-stream
```

### Check from localhost (bypasses Cloudflare)

```bash
curl -sf http://localhost:5000/healthz | python3 -m json.tool
```

## Resolution

### Restart API (most common fix)

```bash
cd /opt/lap-api
docker compose restart api
# Wait 30s then verify
curl -sf http://localhost:5000/healthz | python3 -m json.tool
```

### Restart Caddy (TLS or routing issues)

```bash
docker compose restart caddy
# Caddy auto-provisions TLS certificates from Let's Encrypt
```

### Gunicorn workers unresponsive (OOM)

```bash
# Check if workers were killed by OOM
dmesg | grep -i "oom\|kill" | tail -20

# Restart API with fresh workers
docker compose restart api
```

### Full stack restart

```bash
cd /opt/lap-api
docker compose down
docker compose up -d
# Monitor logs
docker compose logs -f api caddy --tail=20
```

### Database connection exhaustion

```bash
# Check active connections
docker compose exec postgres psql -U telemetry -c \
  "SELECT count(*) FROM pg_stat_activity WHERE state = 'active';"

# If too many connections, restart API (per-request connections, no pool)
docker compose restart api
```

### Cloudflare cache purge (stale error pages)

Cloudflare dashboard > Caching > Purge Everything

## Prevention

- Health check in deploy script retries 10x with 5s interval
- Set up uptime monitoring (e.g., UptimeRobot) on `/healthz`
- Set Gunicorn `--timeout 120` to avoid premature worker kills
- Monitor container memory via `docker stats`
- Keep daily `pg_dump` backups at 3 AM UTC (already configured)
- Run `scripts/verify_production.sh` after every deploy
