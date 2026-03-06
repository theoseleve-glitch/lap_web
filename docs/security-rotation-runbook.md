# Secret Rotation Runbook

## Secrets Inventory

| Secret | Location | Rotation Frequency | Owner |
|--------|----------|-------------------|-------|
| `TELEMETRY_SECRET_KEY` | `.env.production` on VPS | 90 days | Backend lead |
| `TELEMETRY_JWT_SECRET` | `.env.production` on VPS | 90 days | Backend lead |
| `PG_PASSWORD` | `.env.production` + docker-compose | 90 days | Infra lead |
| `STRIPE_SECRET_KEY` | `.env.production` | 180 days (or on compromise) | Billing lead |
| `STRIPE_WEBHOOK_SECRET` | `.env.production` + Stripe dashboard | 180 days | Billing lead |
| `GOOGLE_CLIENT_SECRET` | `.env.production` + Google Cloud Console | 180 days | Auth lead |
| `GITHUB_CLIENT_SECRET` | `.env.production` + GitHub OAuth settings | 180 days | Auth lead |
| `VPS_SSH_KEY` | GitHub Secrets + `~/.ssh/` | 365 days | Infra lead |
| `SENTRY_DSN_API` | `.env.production` | On compromise only | Backend lead |
| `SENTRY_DSN_WORKER` | `.env.production` | On compromise only | Backend lead |

## Rotation Procedures

### 1. Flask Secret Key (`TELEMETRY_SECRET_KEY`)

```bash
# Generate new secret
NEW_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")

# Update on VPS
ssh root@46.225.227.24
cd /opt/lap-api
# Edit .env.production — replace TELEMETRY_SECRET_KEY value
sed -i "s/^TELEMETRY_SECRET_KEY=.*/TELEMETRY_SECRET_KEY=${NEW_SECRET}/" .env.production

# Restart API (active sessions will be invalidated)
docker compose -f docker-compose.prod.yml restart api celery-pipeline celery-default
```

**Impact**: All active Flask sessions invalidated. Users must re-login.

**Verification**:
```bash
curl -sf https://api.lap-coach.racing/healthz | jq .
```

### 2. JWT Secret (`TELEMETRY_JWT_SECRET`)

Same procedure as Flask Secret Key but for `TELEMETRY_JWT_SECRET`.

**Impact**: All active JWT access tokens and refresh tokens invalidated. All users must re-authenticate.

### 3. PostgreSQL Password (`PG_PASSWORD`)

```bash
ssh root@46.225.227.24
cd /opt/lap-api

# Generate new password
NEW_PG_PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

# 1. Change in PostgreSQL first
docker compose -f docker-compose.prod.yml exec postgres \
  psql -U telemetry -c "ALTER USER telemetry WITH PASSWORD '${NEW_PG_PASS}';"

# 2. Update .env.production
sed -i "s/^PG_PASSWORD=.*/PG_PASSWORD=${NEW_PG_PASS}/" .env.production

# 3. Restart all services that connect to PG
docker compose -f docker-compose.prod.yml restart api celery-pipeline celery-default pgbouncer
```

**Verification**:
```bash
curl -sf https://api.lap-coach.racing/healthz | jq .
docker compose -f docker-compose.prod.yml exec postgres pg_isready -U telemetry
```

### 4. Stripe Keys

1. Go to Stripe Dashboard → Developers → API Keys
2. Roll the secret key (Stripe provides a grace period)
3. Update `STRIPE_SECRET_KEY` in `.env.production`
4. For webhook secret: recreate endpoint in Stripe → update `STRIPE_WEBHOOK_SECRET`
5. Restart API: `docker compose -f docker-compose.prod.yml restart api`

**Verification**:
```bash
# Test webhook endpoint responds
curl -sf https://api.lap-coach.racing/api/v1/billing/webhook -X POST -d '{}' -H "Content-Type: application/json"
# Should return 400 (bad signature), not 500
```

### 5. OAuth Client Secrets

1. Google: Google Cloud Console → Credentials → OAuth 2.0 → Edit → Reset secret
2. GitHub: GitHub Settings → Developer Settings → OAuth Apps → Generate new client secret
3. Update corresponding env vars in `.env.production`
4. Restart API

**Verification**: Test OAuth login flow end-to-end.

### 6. VPS SSH Key

```bash
# Generate new key locally
ssh-keygen -t ed25519 -f ~/.ssh/lap-vps-new -C "lap-deploy"

# Add to VPS (while still having access with old key)
ssh root@46.225.227.24 "cat >> ~/.ssh/authorized_keys" < ~/.ssh/lap-vps-new.pub

# Test new key
ssh -i ~/.ssh/lap-vps-new root@46.225.227.24 echo "OK"

# Remove old key from VPS authorized_keys
# Update GitHub Actions secret VPS_SSH_KEY with new private key

# Remove old key from VPS authorized_keys after CI is verified
```

## Rotation Schedule

| Month | Secrets to Rotate |
|-------|------------------|
| Q1 (Jan) | Flask secret, JWT secret, PG password |
| Q2 (Apr) | Flask secret, JWT secret, PG password |
| Q3 (Jul) | Flask secret, JWT secret, PG password, Stripe keys, OAuth secrets |
| Q4 (Oct) | Flask secret, JWT secret, PG password |
| Annual (Jan) | VPS SSH key, all of the above |

## CI Reminder

Add a scheduled GitHub Actions workflow that opens an issue as a reminder:

The `.github/workflows/security-rotation-reminder.yml` workflow creates a GitHub issue every 90 days as a rotation reminder.

## Emergency Rotation (Compromise)

1. Rotate ALL secrets immediately (not just the compromised one)
2. Revoke all active sessions: restart API
3. Force password reset for affected users if credential DB was accessed
4. Review access logs: `docker compose logs api --since 48h | grep -i "auth\|login\|token"`
5. Check for unauthorized data access in PG audit logs
6. Notify affected users per GDPR Article 33 (72h deadline)
