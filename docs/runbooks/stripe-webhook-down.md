# Runbook: Stripe Webhook Down

## Symptoms
- Users report billing status not updating after payment
- `stripe_webhook_events_total` counter stops incrementing (if Prometheus is set up)
- Stripe Dashboard → Developers → Webhooks shows failed deliveries

## Diagnosis

### 1. Check Stripe Dashboard
Go to https://dashboard.stripe.com/webhooks → click your endpoint → check "Recent deliveries":
- **HTTP 4xx/5xx**: API is receiving but rejecting events
- **Timeout/Connection refused**: API not reachable by Stripe

### 2. Check API container health
```bash
ssh root@46.225.227.24
cd /opt/lap-api
docker compose -f docker-compose.prod.yml ps api
docker compose -f docker-compose.prod.yml logs --tail=50 api | grep -i "webhook\|stripe\|billing"
curl -sf http://localhost:5000/healthz
```

### 3. Check webhook secret
```bash
# Compare configured secret with Stripe Dashboard → Webhooks → Signing secret
docker compose -f docker-compose.prod.yml exec api env | grep STRIPE_WEBHOOK_SECRET
```

## Resolution

### Webhook secret mismatch
1. Copy correct signing secret from Stripe Dashboard
2. Update in `/opt/lap-api/.env.production`
3. Restart: `docker compose -f docker-compose.prod.yml restart api`

### API unreachable
1. Check Caddy: `docker compose -f docker-compose.prod.yml logs --tail=20 caddy`
2. Check firewall: `ufw status` — ports 80/443 must be open
3. Check DNS: `dig api.lap-coach.racing` should resolve to VPS IP

### Events backed up in Stripe
After fixing the root cause, Stripe auto-retries failed events for up to 3 days.
The deduplication table (`stripe_events`) prevents double-processing.
Verify with: `SELECT COUNT(*) FROM stripe_events WHERE processed_at > NOW() - INTERVAL '1 hour';`

### Force reconciliation
If events are lost beyond retry window:
```bash
docker compose -f docker-compose.prod.yml exec api python -c "
from tasks.billing_tasks import _reconcile_stripe_impl
_reconcile_stripe_impl()
"
```

## Prevention
- Hourly `reconcile_stripe` Celery beat task auto-heals mismatches
- Monitor `stripe_webhook_events_total` counter for drops
