# Production SaaS Hardening — Design Document

**Date**: 2026-02-27
**Status**: Approved
**Scope**: Audit + hardening across billing, security, jobs, GDPR, observability, email, infrastructure

## Executive Summary

Comprehensive audit of Lap Coach production SaaS identified ~30 gaps across 9 areas. This document defines a 3-phase risk-prioritized approach. Phase 1 (CRITICAL) ships 5 fixes in this session. Phases 2-3 are designed here and implemented in follow-up sessions.

## Current State Assessment

### What's Strong
- Auth & tokens: JWT + refresh rotation, httpOnly cookies, Argon2id
- RLS / multi-tenancy (PostgreSQL mode): 44 tables, SET LOCAL, workspace isolation
- Rate limiting: 5-tier Redis sliding-window
- Security headers: Caddy + Next.js both hardened
- Structured logging: JSON format with request_id, workspace_id, user_id correlation
- Reverse proxy: Caddy with auto-HTTPS, security headers
- Docker stack: PG16, Redis 7, healthchecks, restart policies

### Gap Inventory

| # | Gap | Severity | Area | Phase |
|---|-----|----------|------|-------|
| 1 | Stripe webhook deduplication missing | CRITICAL | Billing | 1 |
| 2 | No Stripe reconciliation job | CRITICAL | Billing | 1 |
| 3 | Legacy routes bypass tenancy | CRITICAL | Security | 1 |
| 4 | GDPR Celery beat not configured | CRITICAL | GDPR | 1 |
| 5 | No Celery worker time/memory limits | CRITICAL | Reliability | 1 |
| 6 | No CSRF protection | HIGH | Security | 2 |
| 7 | Audit log table empty | HIGH | Compliance | 2 |
| 8 | No metrics/alerting (Prometheus) | HIGH | Observability | 2 |
| 9 | Invitation acceptance flow missing | HIGH | Multi-tenancy | 2 |
| 10 | File upload magic-number validation | MEDIUM | Security | 2 |
| 11 | Out-of-order webhook handling | HIGH | Billing | 2 |
| 12 | Email retries missing | MEDIUM | Email | 3 |
| 13 | Docker runs as root | MEDIUM | Infrastructure | 3 |
| 14 | No CI/CD deploy step | MEDIUM | Infrastructure | 3 |
| 15 | No export file encryption | MEDIUM | GDPR | 3 |
| 16 | Stuck task detection | MEDIUM | Reliability | 3 |
| 17 | No Celery beat in code for purge | CRITICAL | GDPR | 1 |
| 18 | Export files accumulate on disk | HIGH | GDPR | 1 |
| 19 | No defense-in-depth on API queries | MEDIUM | Security | 2 |
| 20 | No task deduplication | MEDIUM | Reliability | 2 |
| 21 | Temp dir leaks on cancel | MEDIUM | Reliability | 2 |
| 22 | Email environment separation | LOW | Email | 3 |
| 23 | Bounce/complaint handling | LOW | Email | 3 |
| 24 | Runbooks for incident response | LOW | Observability | 3 |
| 25 | Backup restore drill | LOW | Infrastructure | 3 |
| 26 | Queue length monitoring | MEDIUM | Observability | 2 |
| 27 | No Stripe test clock staging | LOW | Billing | 3 |
| 28 | CSP unsafe-inline review | LOW | Security | 3 |
| 29 | Workspace lock timeout race | LOW | Reliability | 3 |
| 30 | Pipeline context TTL too short | LOW | Reliability | 3 |

---

## Phase 1: CRITICAL — "Stop the Bleeding"

### P1-1: Stripe Webhook Deduplication

**Problem**: Webhook handler processes every event without checking if already seen. Stripe retries on timeout. Duplicates re-execute UPDATE statements.

**Solution**: Event ID tracking table + check-before-process.

**New table** (Alembic 017):
```sql
CREATE TABLE stripe_events (
    id SERIAL PRIMARY KEY,
    stripe_event_id TEXT UNIQUE NOT NULL,
    event_type TEXT NOT NULL,
    processed_at TIMESTAMP DEFAULT now(),
    payload_hash TEXT
);
CREATE INDEX idx_stripe_events_event_id ON stripe_events(stripe_event_id);
CREATE INDEX idx_stripe_events_type ON stripe_events(event_type);
```

**Handler flow**:
1. Verify Stripe-Signature (existing)
2. CHECK: `SELECT 1 FROM stripe_events WHERE stripe_event_id = %(eid)s`
3. If exists: return 200 with `skipped: true`
4. Process event (existing dispatch logic)
5. INSERT into stripe_events (UNIQUE constraint prevents race)
6. Return 200

**Partial out-of-order mitigation**: For `subscription.updated`, fetch current status from Stripe API rather than trusting event payload. One extra API call per event; negligible at current scale.

**Files**: `alembic/versions/017_stripe_events.py`, `web/routes/billing.py`

### P1-2: Stripe Reconciliation Job

**Problem**: Lost webhooks = stale billing state forever. No recovery mechanism.

**Solution**: Hourly Celery beat task comparing local DB state with Stripe API.

**Algorithm**:
1. Query all users with `stripe_subscription_id IS NOT NULL`
2. For each: `stripe.Subscription.retrieve(sub_id)`
3. Compare `billing_plan` with `subscription.status`
4. If mismatch: UPDATE local to match Stripe (Stripe is source of truth)
5. Log all healed mismatches as warnings

**Scaling**: At ~100 subscribers, 100 API calls/hour. Well within Stripe's 100 req/sec limit. At 10K+, would batch with Stripe List API.

**Files**: `tasks/billing_tasks.py` (new), `tasks/celery_app.py` (beat schedule)

### P1-3: Legacy Route Blocking

**Problem**: Jinja2 routes (`/sessions/*`, `/drivers/*`, `/compare/*`, etc.) bypass tenant middleware. In production, these allow cross-workspace data access.

**Solution**: `before_request` middleware returning 404 for legacy prefixes when `AUTH_REQUIRED=1`.

**Blocked prefixes**: `/sessions`, `/drivers`, `/compare`, `/visualize`, `/analysis`, `/dashboard`, `/exports`, `/weekends`, `/race-strategy`

**Allowed**: `/api/v1/*`, `/auth/*`, `/healthz`, `/static/*`, `/api/ingest/*`

**Key decision**: 404 (not 403) — don't reveal route existence. Only active when `AUTH_REQUIRED=1` (production). Desktop/CLI mode unchanged.

**Files**: `web/middleware/legacy_guard.py` (new), `web/app.py` (register)

### P1-4: GDPR Celery Beat Schedule

**Problem**: `purge_deleted_accounts()` exists but never runs. Export ZIPs accumulate on disk forever.

**Solution**:
1. Register beat schedule in `celery_app.py`
2. Add `cleanup_expired_exports()` task
3. Add `celery-beat` container to docker-compose.prod.yml

**Beat schedule**:
- `purge_deleted_accounts`: daily at 3:00 UTC
- `cleanup_expired_exports`: daily at 4:00 UTC
- `reconcile_stripe`: hourly at :00

**Export cleanup**: Deletes ZIP files older than 7 days from `TELEMETRY_EXPORT_DIR`.

**Files**: `tasks/celery_app.py`, `tasks/gdpr_tasks.py`, `docker-compose.prod.yml`

### P1-5: Celery Worker Hardening

**Problem**: No per-task time limits (tasks run forever), no max-tasks-per-child (memory leaks), production worker config incomplete.

**Solution**: Split into two dedicated workers with explicit limits.

**Pipeline worker** (heavy processing):
- Queue: `pipeline`
- Concurrency: 2
- Soft time limit: 1800s (30 min) — raises `SoftTimeLimitExceeded`
- Hard time limit: 2100s (35 min) — SIGKILL
- Max tasks per child: 50

**Default worker** (light tasks):
- Queue: `default`
- Concurrency: 4
- Soft time limit: 600s (10 min)
- Hard time limit: 900s (15 min)
- Max tasks per child: 200

**Files**: `docker-compose.prod.yml`, `tasks/celery_app.py` (task-level soft limit config)

---

## Phase 2: HIGH — "Defense in Depth" (follow-up session)

### P2-1: CSRF Protection
Double-submit cookie pattern. Generate `csrf_token` cookie on login; require `X-CSRF-Token` header on state-changing API requests. Exempt webhooks.

### P2-2: Audit Log Population
`@audit_logged` decorator on mutation routes. Auto-INSERTs into `audit_log` with action, entity_type, entity_id, old_value, new_value, ip, request_id.

### P2-3: Prometheus Metrics
`/metrics` endpoint via `prometheus_flask_instrumentator`. Counters: requests, errors, webhook events, job completions/failures. Histograms: request latency, job duration, queue time.

### P2-4: Invitation Acceptance Flow
- `GET /api/v1/invitations` — list pending invitations for current user
- `POST /api/v1/invitations/<id>/accept` — set accepted_at
- `POST /api/v1/invitations/<id>/reject` — delete row
- Invite-by-email: generate cryptographic token, send via Resend, verify on accept

### P2-5: File Upload Hardening
Magic-number validation for CSV files. Reject non-text content. Add per-route `MAX_CONTENT_LENGTH` overrides.

### P2-6: Webhook Out-of-Order Handling
Add `stripe_event_sequence` column to stripe_events. On `subscription.updated`, compare event timestamp with last processed event. Skip if older.

---

## Phase 3: MEDIUM — "Operational Excellence" (follow-up session)

### P3-1: Email System
- Jinja2 template engine for emails
- Celery task for sending (retries on transient failure)
- Dev/staging env suppression (`EMAIL_SUPPRESS=1`)

### P3-2: Dockerfile Hardening
- Non-root user (`RUN adduser --system app`)
- Multi-stage build (remove gcc/libpq-dev from final image)

### P3-3: CI/CD Deploy
- GitHub Actions deploy step: SSH → docker compose pull → up -d
- Staging environment on separate VPS (optional)

### P3-4: Runbooks
- "Stripe webhook down" — check Stripe dashboard, verify secret, restart webhook
- "Job queue stuck" — inspect workers, check Redis, restart Celery
- "DB CPU spike" — check slow queries, add indexes, scale PG
- "Upload failures" — check disk space, worker health, error logs

### P3-5: Backup Restore Drill
- Document RTO/RPO targets
- Execute restore from pg_dump backup
- Verify data integrity post-restore

---

## Architecture Diagrams

### Runtime Architecture (Target)
```
Browser → Cloudflare Workers (Next.js)
                ↓ CORS
         Caddy (TLS + security headers)
           ↓
         Gunicorn (4 workers)
           ↓
         Flask API
           ├── Legacy Guard middleware (404 in prod)
           ├── Auth middleware (JWT verify)
           ├── Tenant middleware (X-Workspace-Id → SET LOCAL)
           ├── Rate limit middleware (Redis sliding-window)
           ↓
         Route handlers
           ├── /api/v1/billing/webhook → dedup check → process → record
           ├── /api/v1/* → Pydantic validation → business logic → response
           ↓
         PostgreSQL 16 (RLS auto-filter)
         Redis 7 (rate limits, idempotency, Celery broker)

Celery Beat → schedule:
  ├── reconcile_stripe (hourly)
  ├── purge_deleted_accounts (daily 3:00 UTC)
  └── cleanup_expired_exports (daily 4:00 UTC)

Celery Pipeline Worker (concurrency=2, soft_limit=30min):
  └── pipeline_ingest → 14-stage analysis

Celery Default Worker (concurrency=4, soft_limit=10min):
  ├── batch_dispatch
  ├── gdpr_export / gdpr_purge
  └── reconcile_stripe
```

### Webhook Flow (Target)
```
Stripe → POST /api/v1/billing/webhook
           ↓
         Verify Stripe-Signature
           ↓
         Check stripe_events table (dedup)
           ├── Already processed → 200 OK (skip)
           └── New event →
                 ↓
               Dispatch by event.type
                 ├── checkout.session.completed → activate user
                 ├── subscription.updated → fetch Stripe API → update
                 ├── subscription.deleted → downgrade to free
                 └── invoice.payment_failed → mark past_due
                 ↓
               INSERT INTO stripe_events → 200 OK

Celery Beat (hourly):
  reconcile_stripe → for each subscriber:
    Stripe API → compare → heal mismatches
```

### Job System (Target)
```
Upload API → create ingestion_job → dispatch to Celery
                                         ↓
Pipeline Worker (soft_limit=30min, max_tasks=50):
  acquire_lock(workspace) → 14-stage pipeline → release_lock
  ↓ on SoftTimeLimitExceeded:
    log warning → set job status=failed → cleanup temp dir
  ↓ on hard timeout:
    SIGKILL → Celery replaces child → lock expires in 30min

Default Worker (soft_limit=10min, max_tasks=200):
  batch_dispatch → create N ingestion_jobs → dispatch each
  gdpr_export → query all user data → ZIP → store
  gdpr_purge → cascade delete old soft-deleted users
  reconcile_stripe → compare local ↔ Stripe → heal
```

---

## Testing Strategy

### Phase 1 Tests
| Fix | Test | Type |
|-----|------|------|
| P1-1 | Duplicate webhook returns 200 + skipped=true | Unit |
| P1-1 | Concurrent duplicate webhooks (race condition) | Unit |
| P1-1 | Out-of-order subscription.updated fetches Stripe API | Unit |
| P1-2 | Reconciliation heals mismatch | Unit |
| P1-2 | Reconciliation handles deleted subscription | Unit |
| P1-3 | Legacy route returns 404 when AUTH_REQUIRED=1 | Unit |
| P1-3 | Legacy route works when AUTH_REQUIRED=0 | Unit |
| P1-3 | API routes not affected by legacy guard | Unit |
| P1-4 | Beat schedule has all 3 tasks | Unit |
| P1-4 | Export cleanup deletes old files, keeps recent | Unit |
| P1-5 | Worker config has correct limits in compose | Verify |

---

## Rollback Strategy

Each Phase 1 fix is independent and reversible:
- **P1-1**: Migration 017 can be downgraded. Billing.py changes are backward-compatible.
- **P1-2**: Reconciliation task can be disabled by removing from beat schedule.
- **P1-3**: Legacy guard is feature-flagged by `AUTH_REQUIRED`.
- **P1-4**: Beat schedule additions are additive; removing them returns to current behavior.
- **P1-5**: Worker limits are Docker Compose config changes; revert compose file to restore.

---

## Success Criteria

### Phase 1 Complete When:
- [ ] Duplicate Stripe webhooks are silently deduplicated (test passes)
- [ ] Reconciliation job runs hourly and heals mismatches (test passes)
- [ ] Legacy routes return 404 in production mode (test passes)
- [ ] GDPR purge runs daily via Celery beat (configuration verified)
- [ ] Export files cleaned up after 7 days (test passes)
- [ ] Workers have time limits and memory recycling (compose config verified)
- [ ] All existing tests still pass (CI green)
