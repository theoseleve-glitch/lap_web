# Production Deployment Design — Backend API + Third-Party Services

> **Status**: Draft | **Date**: 2026-02-27

## Context

The Next.js marketing site and app frontend are deployed at `www.lap-coach.racing` on Cloudflare Workers. All pages render correctly (login, register, demo, free-report, billing, app/*). However, **no backend API exists in production** — the frontend's `next.config.mjs` rewrites `/api/v1/*` to `NEXT_PUBLIC_API_URL`, which currently defaults to `http://localhost:5000`. All interactive features (auth, upload, analysis, payments) are non-functional.

This design covers everything needed to make the full website operational.

## Goal

Deploy the Flask API backend to a Hetzner VPS with PostgreSQL, connect all third-party services (Stripe, Google OAuth, Resend email), and update the frontend to point to the live API — making auth, the free report funnel, billing, and the demo page fully functional.

## Architecture

```
                    www.lap-coach.racing
                    (Cloudflare Workers)
                 ┌────────────────────────┐
                 │  Next.js 14 App Router  │
                 │  Marketing + Auth UI +  │
                 │  App Dashboard + Free   │
                 │  Report Funnel          │
                 └──────────┬─────────────┘
                            │
              /api/v1/* rewrite (next.config.mjs)
              /auth/*   direct browser redirect (OAuth)
                            │
                            ▼
                   api.lap-coach.racing
                   (Hetzner CX22 VPS)
        ┌──────────────────────────────────────┐
        │  Caddy (reverse proxy, auto-HTTPS)   │
        │         :443 → :5000                 │
        ├──────────────────────────────────────┤
        │  Docker Compose                      │
        │  ┌────────────┐  ┌────────────────┐  │
        │  │ Flask API   │  │ PostgreSQL 16  │  │
        │  │ (Gunicorn)  │  │ (data on       │  │
        │  │ port 5000   │  │  100GB Volume) │  │
        │  └──────┬──────┘  └────────────────┘  │
        │         │                             │
        └─────────┼─────────────────────────────┘
                  │
      ┌───────────┼────────────┬────────────────┐
      │           │            │                │
      ▼           ▼            ▼                ▼
   Stripe     Google OAuth   Resend         Plausible
   Payments   (OIDC)        Email           Analytics
   (API)      (redirect)    (API)           (already live)
```

## Infrastructure

### Hetzner VPS — Start Small, Scale Later

| Phase | Timeline | Server | Storage | Monthly Cost |
|-------|----------|--------|---------|-------------|
| **Launch** | Now | CX22 (2 vCPU, 4 GB RAM) | 100 GB Volume | ~€10 |
| **Growth** | ~50-100 active users | CX32 (4 vCPU, 8 GB RAM) | 500 GB Volume | ~€33 |
| **Scale** | 500+ users / 1 TB data | AX42 Dedicated (6-core, 64 GB RAM, 1 TB NVMe) | Built-in | ~€51 |

**Why this path works:**
- Volume resizes are instant, no downtime, no data migration
- Docker Compose config is identical on cloud VPS and dedicated server
- CX22 compute is sufficient — the streaming ingest pipeline peaks at <1 GB RAM
- PostgreSQL on 100 GB Volume handles thousands of sessions before needing more

### Domain & DNS

| Record | Type | Value | Where |
|--------|------|-------|-------|
| `api.lap-coach.racing` | A | `<VPS IPv4>` | Cloudflare DNS (proxied OFF — direct to VPS for WebSocket/SSE) |
| `api.lap-coach.racing` | AAAA | `<VPS IPv6>` | Cloudflare DNS (optional) |

**Important:** Cloudflare proxy must be OFF (grey cloud) for the API subdomain. The VPS runs Caddy which handles HTTPS directly via Let's Encrypt. Cloudflare proxying would break SSE streaming and OAuth redirects.

### Docker Compose Stack

```yaml
# docker-compose.prod.yml
services:
  api:
    build: .
    command: gunicorn -w 4 -b 0.0.0.0:5000 "telemetry_tool.web.app:create_app()"
    env_file: .env
    volumes:
      - upload_data:/data/uploads
      - parquet_data:/data/parquet
    depends_on:
      - postgres
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: telemetry
      POSTGRES_USER: telemetry
      POSTGRES_PASSWORD: ${PG_PASSWORD}
    volumes:
      - /mnt/volume/pgdata:/var/lib/postgresql/data
    restart: unless-stopped

  caddy:
    image: caddy:2-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
    restart: unless-stopped

volumes:
  upload_data:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /mnt/volume/uploads
  parquet_data:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /mnt/volume/parquet
  caddy_data:
```

```
# Caddyfile
api.lap-coach.racing {
    reverse_proxy api:5000
    encode gzip
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
    }
}
```

## Third-Party Services

### 1. Stripe (Payments)

**Purpose:** Process subscriptions for Performance (€69/yr) and Pro Racer (€109/yr) plans.

**Sign up:** https://dashboard.stripe.com/register

**Setup steps:**
1. Create Stripe account, complete business verification (can use test mode initially)
2. Create 4 Products/Prices:
   - Performance Monthly: €8.99/mo recurring
   - Performance Annual: €69/yr recurring
   - Pro Racer Monthly: €13.99/mo recurring
   - Pro Racer Annual: €109/yr recurring
3. Copy each Price ID (`price_...`)
4. Go to Developers → API Keys → copy publishable and secret keys
5. Go to Developers → Webhooks → add endpoint:
   - URL: `https://api.lap-coach.racing/api/v1/billing/webhook`
   - Events: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`
6. Copy webhook signing secret (`whsec_...`)

**Environment variables produced:**
```bash
STRIPE_SECRET_KEY=sk_test_...           # Backend (.env)
STRIPE_WEBHOOK_SECRET=whsec_...         # Backend (.env)
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_test_...  # Frontend (Cloudflare env)
STRIPE_PRICE_PERFORMANCE_MONTHLY=price_...      # Frontend (Cloudflare env)
STRIPE_PRICE_PERFORMANCE_ANNUAL=price_...       # Frontend (Cloudflare env)
STRIPE_PRICE_PRO_RACER_MONTHLY=price_...        # Frontend (Cloudflare env)
STRIPE_PRICE_PRO_RACER_ANNUAL=price_...         # Frontend (Cloudflare env)
```

**Cost:** Free to create. 2.9% + €0.25 per successful charge. No monthly fee.

**Code status:** Frontend billing routes (`/api/billing/checkout`, `/api/billing/portal`, `/api/billing/switch`) exist in `lap-website/src/app/api/billing/`. Backend webhook handler may need creation at `telemetry_tool/web/routes/billing.py`.

### 2. Google OAuth (Social Login)

**Purpose:** "Sign in with Google" button on login/register pages.

**Sign up:** https://console.cloud.google.com

**Setup steps:**
1. Create new project (name: "LAP Racing" or similar)
2. APIs & Services → OAuth consent screen:
   - User type: External
   - App name: "LAP"
   - Authorized domains: `lap-coach.racing`
   - Scopes: `openid`, `email`, `profile`
3. APIs & Services → Credentials → Create OAuth 2.0 Client ID:
   - Application type: Web application
   - Authorized JavaScript origins: `https://www.lap-coach.racing`
   - Authorized redirect URI: `https://api.lap-coach.racing/auth/oauth/google/callback`
4. Copy Client ID and Client Secret

**Environment variables produced:**
```bash
GOOGLE_CLIENT_ID=...apps.googleusercontent.com    # Backend (.env)
GOOGLE_CLIENT_SECRET=GOCSPX-...                    # Backend (.env)
OAUTH_REDIRECT_BASE=https://api.lap-coach.racing   # Backend (.env)
```

**Cost:** Free.

**Code status:** Fully implemented in `telemetry_tool/auth/oauth.py` and `telemetry_tool/web/routes/auth.py`. Uses authlib. No code changes needed — just env vars.

### 3. Resend (Transactional Email)

**Purpose:** Email verification after registration, future password reset and receipts.

**Sign up:** https://resend.com

**Setup steps:**
1. Create account
2. Domains → Add Domain → `lap-coach.racing`
3. Add DNS records at your registrar/Cloudflare:
   - SPF TXT record
   - DKIM CNAME records (Resend provides exact values)
   - DMARC TXT record (recommended)
4. Wait for verification (usually <5 minutes)
5. API Keys → Create API Key → copy

**Environment variables produced:**
```bash
RESEND_API_KEY=re_...                    # Backend (.env)
EMAIL_FROM=LAP <team@lap-coach.racing>   # Backend (.env) — team@, NOT noreply@
```

**Cost:** Free up to 3,000 emails/month. $20/mo for 50,000/mo.

**Code status:** Backend generates `email_verify_token` and `email_verify_expires` in the users table (migration 003) but does **not send emails yet**. A new module `telemetry_tool/auth/email.py` is needed to call Resend's API and send the verification email after registration.

### 4. Plausible Analytics

**Status:** Already live. Script tag loads from `https://plausible.io/js/script.js` in the Next.js layout. No action needed.

### 5. Status Page (Optional)

**Status:** Frontend fetches from `https://status.lap.racing/api/v2/status.json` with fallback. Currently returns a "fallback" operational response. Can set up a real status page later (e.g., Instatus free tier or self-hosted Upptime on GitHub Pages).

## Code Changes Required

### Backend Changes

| # | File | Change | Priority |
|---|------|--------|----------|
| 1 | **New: `telemetry_tool/auth/email.py`** | Resend SDK integration. `send_verification_email(to, token, base_url)` function. Called from `register_user()` after inserting user. | High |
| 2 | **New: `telemetry_tool/web/routes/billing.py`** | Stripe webhook handler. Verify signature, handle `checkout.session.completed` (activate subscription), `customer.subscription.deleted` (downgrade to free), `invoice.payment_failed` (mark past-due). | High |
| 3 | **`telemetry_tool/web/app.py`** | Register billing blueprint. Add `RESEND_API_KEY` to config loading. | Medium |
| 4 | **`.env` on VPS** | All production env vars (see complete list below). | High |
| 5 | **New: `Dockerfile`** | Multi-stage: Python 3.11-slim, pip install requirements, Gunicorn entrypoint. | High |
| 6 | **New: `docker-compose.prod.yml`** | Flask + PostgreSQL + Caddy (see Architecture section above). | High |
| 7 | **New: `Caddyfile`** | Reverse proxy config with auto-HTTPS (see Architecture section above). | High |

### Frontend Changes

| # | File | Change | Priority |
|---|------|--------|----------|
| 1 | **Cloudflare Worker env** | Set `NEXT_PUBLIC_API_URL=https://api.lap-coach.racing` | Critical |
| 2 | **Rebuild + redeploy** | `npm run cf:build && npm run cf:deploy` after env change | Critical |

### Database Setup

| # | Action | Command |
|---|--------|---------|
| 1 | Create PostgreSQL database | `CREATE DATABASE telemetry;` (handled by Docker) |
| 2 | Run Alembic migrations 001-008 | `alembic upgrade head` (creates 48+ tables, users, auth, workspaces, RLS) |

## Complete Environment Variables (Backend .env)

```bash
# ── Flask ─────────────────────────────────────
TELEMETRY_SECRET_KEY=<generate: openssl rand -hex 32>
TELEMETRY_HOST=0.0.0.0
TELEMETRY_PORT=5000
TELEMETRY_DEBUG=0

# ── PostgreSQL ────────────────────────────────
USE_PG=1
TELEMETRY_PG_URL=postgresql://telemetry:<PG_PASSWORD>@postgres:5432/telemetry

# ── Auth ──────────────────────────────────────
AUTH_REQUIRED=1
TELEMETRY_JWT_SECRET=<generate: openssl rand -hex 32>

# ── Google OAuth ──────────────────────────────
GOOGLE_CLIENT_ID=<from Google Cloud Console>
GOOGLE_CLIENT_SECRET=<from Google Cloud Console>
OAUTH_REDIRECT_BASE=https://api.lap-coach.racing

# ── Email (Resend) ────────────────────────────
RESEND_API_KEY=<from Resend dashboard>
EMAIL_FROM=LAP <team@lap-coach.racing>

# ── Observability (Sentry) ────────────────────
# Init is wired + DSN-gated (web/app.py, celery_app.py). UNSET = launch
# flies blind on errors. Set both; DSNs come from the Sentry project.
SENTRY_DSN_API=<from Sentry project — Flask API>
SENTRY_DSN_WORKER=<from Sentry project — Celery workers>
SENTRY_ENVIRONMENT=production
SENTRY_TRACES_RATE=0.1
# Frontend DSN: NEXT_PUBLIC_SENTRY_DSN — set in lap-website at cf:build.

# ── Stripe ────────────────────────────────────
STRIPE_SECRET_KEY=<from Stripe dashboard>
STRIPE_WEBHOOK_SECRET=<from Stripe webhook config>

# ── Ingest ────────────────────────────────────
TELEMETRY_INGEST_V2=1

# ── CORS ──────────────────────────────────────
CORS_ALLOWED_ORIGINS=https://www.lap-coach.racing

# ── Rate Limiting ─────────────────────────────
RATE_LIMIT_ENABLED=1

# ── Data Paths (mapped to Volume) ─────────────
TELEMETRY_UPLOAD_DIR=/data/uploads
TELEMETRY_PARQUET_DIR=/data/parquet
TELEMETRY_EXPORT_DIR=/data/exports
```

## Deployment Sequence

```
Phase 1: Infrastructure                    (you do manually)
─────────────────────────────────────────────────────────────
1. Sign up for Hetzner Cloud
2. Create CX22 server (Ubuntu 24.04, EU datacenter)
3. Attach 100 GB Volume, mount at /mnt/volume
4. SSH in, install Docker + Docker Compose
5. Add DNS: api.lap-coach.racing → A → <VPS IP>  (Cloudflare, proxy OFF)

Phase 2: Third-party service accounts      (you do manually)
─────────────────────────────────────────────────────────────
6. Create Stripe account → 4 Price IDs + API keys + webhook
7. Create Google Cloud project → OAuth 2.0 credentials
8. Create Resend account → verify domain → API key
9. Add Resend DNS records (SPF, DKIM) at Cloudflare

Phase 3: Backend deployment                (we do together)
─────────────────────────────────────────────────────────────
10. Write Dockerfile, docker-compose.prod.yml, Caddyfile
11. Write telemetry_tool/auth/email.py (Resend integration)
12. Write telemetry_tool/web/routes/billing.py (Stripe webhooks)
13. Push to repo, clone on VPS
14. Create .env with all production values
15. docker compose up -d
16. Run Alembic migrations: alembic upgrade head
17. Verify: curl https://api.lap-coach.racing/api/v1/me → 401 (good!)

Phase 4: Frontend connection               (we do together)
─────────────────────────────────────────────────────────────
18. Set NEXT_PUBLIC_API_URL=https://api.lap-coach.racing in Cloudflare Worker env
19. Rebuild and redeploy: npm run cf:build && npm run cf:deploy
20. Test full flows:
    - Register with email/password → verify email → login
    - Sign in with Google → redirect → logged in
    - Upload CSV → free report generated
    - Subscribe to Performance plan → Stripe checkout → active subscription

Phase 5: Go live                           (you decide)
─────────────────────────────────────────────────────────────
21. Switch Stripe from test mode to live mode
22. Submit Google OAuth for verification (removes "unverified app" warning)
23. Monitor via Plausible analytics + server logs
```

## Security Considerations

- **JWT secret**: Generate with `openssl rand -hex 32`. Never commit to git.
- **PostgreSQL password**: Generate strong password. Only accessible within Docker network.
- **Stripe webhook signature**: Always verify `Stripe-Signature` header before processing.
- **CORS**: Restrict to `https://www.lap-coach.racing` only.
- **Cloudflare proxy OFF for API**: Caddy handles HTTPS directly. This avoids Cloudflare buffering breaking SSE streams and keeps OAuth redirects clean.
- **Firewall**: Only ports 22 (SSH), 80 (HTTP→HTTPS redirect), 443 (HTTPS) open on VPS.
- **Volume permissions**: PostgreSQL data dir owned by postgres user (uid 999 in Docker).
- **Backups**: Set up daily pg_dump to a separate directory on the Volume.

## Scaling Triggers

| Signal | Action |
|--------|--------|
| Volume usage > 80% | Resize Volume (instant, no downtime) |
| RAM usage > 80% consistently | Upgrade to CX32 (4 vCPU, 8 GB) |
| Response times > 500ms p95 | Add Gunicorn workers or upgrade CPU |
| Volume cost > €40/mo | Migrate to AX42 dedicated (1 TB NVMe included for €51) |
| Concurrent uploads > 10 | Add Redis + Celery for background processing |

## Open Questions

1. **Lead CRM**: Where should B2B demo form submissions go? (CRM_WEBHOOK_URL, EMAIL_WEBHOOK_URL) — can defer, forms will gracefully fail.
2. **Redis/Celery**: Not needed at launch. Add when concurrent processing becomes a bottleneck.
3. **Backup strategy**: Daily pg_dump is minimum. Consider Hetzner snapshots (€0.01/GB/mo) for full VPS backup.
4. **Monitoring**: Start with Caddy access logs + `docker logs`. Add Uptime Robot (free) for basic alerting.
