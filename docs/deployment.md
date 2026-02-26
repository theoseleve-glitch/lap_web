# Deployment Guide

## Architecture

```
lap.racing (Vercel)          api.lap.racing (VPS/Railway)
┌──────────────────┐         ┌──────────────────────────┐
│  Next.js 14      │ ──API──▶│  nginx → Flask/Gunicorn  │
│  Marketing + App │         │  PostgreSQL 16            │
│  Stripe billing  │         │  Redis 7 + Celery worker  │
└──────────────────┘         └──────────────────────────┘
```

## 1. Deploy Flask API

### Option A: Docker Compose on VPS

```bash
# On the server
git clone https://github.com/theoseleve-glitch/tele8tool.git
cd tele8tool

# Create .env from template
cp .env.example .env
# Edit: set TELEMETRY_SECRET_KEY, TELEMETRY_JWT_SECRET, PG_PASSWORD
# Set: AUTH_REQUIRED=1, CORS_ALLOWED_ORIGINS=https://lap.racing

# Start all services
docker compose -f docker-compose.prod.yml up -d

# Run migrations (first deploy only)
docker compose -f docker-compose.prod.yml exec api \
  alembic -c telemetry_tool/alembic/alembic.ini upgrade head

# Verify
curl http://localhost:5000/healthz
```

### Option B: Railway / Fly.io

1. Connect GitHub repo
2. Set root directory to `/` (Dockerfile at repo root)
3. Add environment variables from `.env.example`
4. Add PostgreSQL and Redis add-ons
5. Set `TELEMETRY_USE_PG=1` and connection strings

### DNS for API

```
api.lap.racing  A     → <server-ip>
```

### TLS for API

**With nginx on VPS:**
```bash
apt install certbot python3-certbot-nginx
certbot --nginx -d api.lap.racing
```

**With Railway/Fly:** TLS is automatic.

## 2. Deploy Next.js Frontend

### Vercel (recommended)

```bash
cd lap-website
vercel --prod
```

Or connect the GitHub repo in Vercel dashboard:
- Root directory: `lap-website`
- Framework: Next.js (auto-detected)
- Build command: `npm run build`
- Output directory: `.next`

**Environment variables in Vercel:**
```
NEXT_PUBLIC_API_URL=https://api.lap.racing
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_live_...
```

### DNS for Frontend

```
lap.racing      A/CNAME → Vercel
www.lap.racing  CNAME   → cname.vercel-dns.com
```

## 3. Post-Deploy Verification

```bash
# Marketing pages
curl -s https://lap.racing | grep -q "lap.racing" && echo "OK"

# API health
curl -s https://api.lap.racing/healthz | jq .

# CORS headers
curl -s -H "Origin: https://lap.racing" \
  -I https://api.lap.racing/api/v1/dashboard/stats \
  | grep -i access-control

# Auth flow
curl -s -X POST https://api.lap.racing/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@test.com","password":"test"}' | jq .
```

## 4. Environment Checklist

| Variable | Backend (.env) | Frontend (Vercel) |
|----------|---------------|-------------------|
| `TELEMETRY_SECRET_KEY` | Random 32+ chars | - |
| `TELEMETRY_JWT_SECRET` | Random 32+ chars | - |
| `PG_PASSWORD` | Random 32+ chars | - |
| `AUTH_REQUIRED` | `1` | - |
| `CORS_ALLOWED_ORIGINS` | `https://lap.racing` | - |
| `NEXT_PUBLIC_API_URL` | - | `https://api.lap.racing` |
| `STRIPE_SECRET_KEY` | - | `sk_live_...` |
