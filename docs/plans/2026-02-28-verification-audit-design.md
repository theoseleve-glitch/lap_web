# Verification Audit Design

**Date**: 2026-02-28
**Scope**: Full traceability matrix + gap analysis for Lap Coach SaaS
**Approach**: Sequential deep-dive — diagrams → matrix → gaps → fixes → post-deploy suite

---

## 1. Architecture Diagrams

### A) Request Lifecycle

```
Browser (Next.js on Cloudflare Workers)
  │
  ├─ NEXT_PUBLIC_API_URL → CORS preflight (OPTIONS)
  │
  ▼
Caddy (TLS termination, security headers, gzip)
  │  ├─ HSTS, X-Frame-Options: DENY, CSP, Permissions-Policy
  │  └─ request_body max_size: 12GB
  │
  ▼
Gunicorn (4 sync workers, pre-fork)
  │
  ▼
Flask App (create_app factory, 32 blueprints)
  │
  ├─── 1. Auth Middleware (web/middleware/auth.py)
  │    ├─ Path allowlist check (public routes skip)
  │    ├─ JWT HS256 verification (access token from Authorization header)
  │    ├─ Populates g.user_id, g.user_email
  │    └─ 401 if AUTH_REQUIRED=1 and token invalid/missing
  │
  ├─── 2. Tenant Middleware (web/middleware/tenant.py)
  │    ├─ X-Workspace-Id header OR default workspace
  │    ├─ _verify_workspace_access() — user must be member
  │    ├─ SET LOCAL app.workspace_id = :id (RLS context)
  │    └─ Populates g.workspace_id, g.workspace_role
  │
  ├─── 3. Rate Limit Middleware (web/rate_limit.py)
  │    ├─ Redis sliding-window, 5 tiers (read/write/auth/sensitive/anon)
  │    └─ 429 with Retry-After header
  │
  ├─── 4. Entitlement Middleware (web/middleware/entitlements.py)
  │    ├─ _FEATURE_GATES: route → feature mapping
  │    ├─ _QUOTA_GATES: route → meter_key + cost
  │    ├─ authorize_feature() → 403 PLAN_REQUIRED + upgrade CTA
  │    └─ check_and_record_quota() → 429 QUOTA_EXCEEDED (atomic, SELECT FOR UPDATE)
  │
  ├─── 5. Route Handler (web/routes/*.py)
  │    ├─ @require_permission() decorator (RBAC)
  │    ├─ @require_feature() decorator (per-route override)
  │    ├─ @require_quota() decorator (per-route override)
  │    ├─ Pydantic validation (schemas/)
  │    └─ Business logic
  │
  ├─── 6. For async work: Celery task enqueue
  │    ├─ Pipeline queue (heavy, concurrency=2)
  │    ├─ Default queue (light, concurrency=4)
  │    └─ task_acks_late=True (at-least-once delivery)
  │
  ├─── 7. After-request: record_successful_usage()
  │    └─ Append to usage_events + upsert usage_monthly
  │
  └─── 8. Response: Standard envelope {ok, data, error, meta}
       └─ X-Request-Id header for correlation
```

### B) Data Model

```
┌─────────────────────────────────────────────────────────────┐
│                      IDENTITY LAYER                          │
│                                                              │
│  users ──────────┬─── oauth_connections (Google, GitHub)     │
│  │ id            │                                           │
│  │ email         ├─── refresh_tokens (single-use rotation)   │
│  │ password_hash │                                           │
│  │ plan_tier ────┤    ┌── totp_secret (Fernet-encrypted)     │
│  │ stripe_*      │    │── totp_backup_codes (SHA-256 hashed) │
│  │ is_superadmin ├────┘── admin_role (ENUM)                  │
│  │ deleted_at    │                                           │
│  └───────────────┘                                           │
│         │ 1:N                                                │
│         ▼                                                    │
│  workspace_members ───── workspaces (personal / team)        │
│  │ role (viewer/member/admin/owner)                          │
│  └─ workspace_id ────→ RLS filter on ALL 44 tables           │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    SUBSCRIPTION LAYER                         │
│                                                              │
│  plan_definitions (global seed, 4 tiers)                     │
│  │ slug: demo | racer | world-class | b2b                   │
│  │ limits: reports_per_month, retention_days, upload_max_mb  │
│  │                                                           │
│  entitlement_overrides (per-user/workspace)                  │
│  │ override_key, override_value, expires_at, reason          │
│  │                                                           │
│  usage_events (append-only ledger)                           │
│  │ user_id, workspace_id, event_type, cost, created_at      │
│  │                                                           │
│  usage_monthly (pre-aggregated)                              │
│  │ workspace_id, period_start, event_type, total             │
│  │                                                           │
│  stripe_webhook_log (PCI-sanitized)                          │
│  │ event_id, event_type, processing_status, payload          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     TELEMETRY LAYER                           │
│                                                              │
│  sessions ── laps ── gps_traces                              │
│  │            │── lap_scores ── scoring_details               │
│  │            └── reference_lines                             │
│  │                                                           │
│  tracks ── track_sectors                                      │
│  drivers                                                      │
│  comparisons ── comparison_laps                               │
│  race_strategy_configs ── stints                              │
│  raw_telemetry (retention-scoped)                             │
│  driving_style_features (retention-scoped)                    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                      ADMIN LAYER                             │
│                                                              │
│  admin_audit_log (immutable, append-only)                    │
│  security_events (severity-tagged)                           │
│  incident_notes                                              │
│  system_metrics_snapshots                                    │
│  support_tickets                                             │
│  ingestion_jobs (with peak_rss_mb, throughput_mb_s)          │
└─────────────────────────────────────────────────────────────┘
```

### C) Stripe Lifecycle

```
User clicks "Subscribe" (frontend)
  │
  ▼
POST /api/v1/billing/checkout → Stripe Checkout Session
  │
  ▼
Stripe processes payment
  │
  ▼
Webhook: checkout.session.completed
  ├─ Verify Stripe-Signature (HMAC)
  ├─ Dedup: Redis fast-path + DB fallback
  ├─ Event ordering: compare created timestamps
  ├─ Activate subscription in DB:
  │   ├─ users.stripe_subscription_id
  │   ├─ users.subscription_status = 'active'
  │   ├─ users.plan_tier = resolved tier
  │   └─ State machine: validate_transition() + audit_log
  └─ Entitlements: recomputed on next request (lazy, from plan_tier)

Ongoing lifecycle:
  ├─ invoice.paid → status='active' (recovery from past_due)
  ├─ invoice.payment_failed → status='past_due' (7-day grace)
  ├─ customer.subscription.updated → fetch live from Stripe (out-of-order safe)
  ├─ customer.subscription.deleted → status='canceled' (30-day grace)
  ├─ customer.subscription.paused → status='paused' (read-only)
  ├─ customer.subscription.resumed → status='active'
  ├─ customer.subscription.trial_will_end → email notification
  └─ charge.refunded → logged (informational)

Drift Healing:
  ├─ reconcile_stripe() — Hourly Celery task
  │   ├─ Fetch all users with stripe_subscription_id
  │   ├─ Compare local status vs Stripe API
  │   ├─ Heal mismatches (update local)
  │   └─ Mark deleted if sub not found in Stripe
  └─ enforce_subscription_grace_periods() — Daily
      ├─ canceled + grace expired → downgrade to 'demo'
      ├─ past_due > 14 days → downgrade
      └─ past_due > 7 days → final warning email
```

### D) Retention Lifecycle

```
Upload (CSV file)
  │
  ▼
Ingest → sessions + laps + gps_traces + raw_telemetry
  │       (workspace-scoped via RLS)
  │
  ▼
Active Use (within retention window)
  │  Plan retention: demo=30d, racer=90d, world-class=365d, b2b=custom
  │
  ▼
Retention Check (enforce_raw_data_retention — daily Celery task)
  │
  ├─ Check entitlement_overrides (B2B promos, support credits)
  ├─ Calculate expiry: session.created_at + retention_days
  ├─ 7 days before expiry → pre-expiry warning email
  ├─ After expiry:
  │   ├─ DELETE: gps_traces, reference_lines, driving_style_features
  │   ├─ DELETE: raw_telemetry, session files on disk
  │   ├─ PRESERVE: reports, scores, laps, annotations (indefinite)
  │   └─ AUDIT: _write_retention_audit() to audit_log
  │
  ▼
Account Deletion (DELETE /api/v1/account)
  ├─ Soft-delete: set deleted_at (30-day grace)
  ├─ Revoke all refresh tokens
  ├─ Cancel within grace: POST /cancel-deletion
  │
  ▼
Hard Purge (purge_deleted_accounts — daily Celery task)
  │  (deleted_at < now() - 30 days)
  ├─ Cascade: workspaces, sessions, laps, scores, files, memberships
  ├─ Hard delete user row
  └─ Logged per purged account
```

---

## 2. Requirements Traceability Matrix

### A) Entitlements + Authorization + Quotas

| # | Requirement | Implemented | Enforced | Tests | Status |
|---|-------------|------------|----------|-------|--------|
| E-01 | Plan tiers (demo/racer/world-class/b2b) | auth/entitlements.py PLAN_ENTITLEMENTS | Static dict | test_entitlements.py | PASS |
| E-02 | Feature gating (comparison, viz, API) | middleware/entitlements.py _FEATURE_GATES | before_request | test_entitlement_middleware.py | PASS |
| E-03 | Quota enforcement (reports/month) | middleware/entitlements.py _QUOTA_GATES | before_request (atomic) | test_entitlement_middleware.py | PASS |
| E-04 | Atomic quota reservation | middleware/entitlements.py → check_and_record_quota() | before_request (SELECT FOR UPDATE) | test_entitlement_middleware.py | PASS — fixed c5878fb |
| E-05 | Usage recording (append-only) | auth/entitlements.py record_usage() | after_request | test_entitlements.py | PASS |
| E-06 | Monthly usage aggregation | tasks/usage_tasks.py | Daily beat | test_usage_tasks.py | PASS |
| E-07 | Entitlement overrides | admin/entitlements.py | Admin API | test_admin_entitlements.py | PASS |
| E-08 | Upgrade CTA on 403 | auth/entitlements.py @require_feature | Response body | test_entitlement_middleware.py | PASS |
| E-09 | Worker-layer entitlement check | tasks/pipeline_tasks.py _verify_task_entitlements() | pipeline_ingest() guard | test_pipeline_entitlement_guard.py | PASS — fixed 1949663 |
| E-10 | Upload quota enforcement | middleware/entitlements.py _QUOTA_GATES | before_request | test_entitlement_middleware.py | PASS — fixed dac4f28 |
| E-11 | Upload size limit per tier | middleware/entitlements.py require_upload_size() | @require_upload_size decorator | test_entitlement_middleware.py | PASS — fixed dac4f28 |
| E-12 | All mutation routes gated | middleware/entitlements.py | 14 feature + 5 quota gates | test_entitlement_middleware.py | PASS — fixed e8014a1 |
| E-13 | Race strategy v1 API gated | middleware/entitlements.py _FEATURE_GATES | POST/PUT/DELETE gates | test_entitlement_middleware.py | PASS — fixed e8014a1 |
| E-14 | Anomaly detection | admin/entitlements.py detect_anomalies() | Admin API | test_admin_entitlements.py | PASS |
| E-15 | Subscription state machine | billing/state_machine.py | Webhook + reconciliation | test_billing_tasks.py | PASS |

### B) Account / Garage

| # | Requirement | Implemented | Tests | Status |
|---|-------------|------------|-------|--------|
| A-01 | Profile editing | api_v1_account.py:294-398 | test_account_experience.py | PASS |
| A-02 | Preferences (JSONB merge) | api_v1_account.py:924-944 | test_account_experience.py | PASS |
| A-03 | Active sessions list | api_v1_account.py:463-516 | test_account_security.py | PASS |
| A-04 | Logout everywhere | api_v1_account.py:555-591 | test_account_security.py | PASS |
| A-05 | OAuth unlink (lockout safe) | api_v1_account.py:951-1047 | test_account_experience.py | PASS |
| A-06 | Stripe portal link | api_v1_billing.py:341-383 | test_billing_portal.py | PASS |
| A-07 | Usage dashboard | api_v1_billing.py:257-334 | test_billing_api.py | PASS |
| A-08 | GDPR export | api_v1_account.py:71-185, gdpr_tasks.py | test_gdpr_tasks.py | PASS |
| A-09 | GDPR delete (soft+hard) | api_v1_account.py:192-287, gdpr_tasks.py:272-375 | test_gdpr_tasks.py | PASS |
| A-10 | Support tickets | api_v1_support.py:52-170 | test_support.py | PASS |
| A-11 | 2FA setup/confirm/disable | api_v1_account.py:598-861 | test_account_security.py | PASS |
| A-12 | Password change + revoke | api_v1_account.py:408-456 | test_account_security.py | PASS |
| A-13 | Login activity log | api_v1_account.py:1054-1093 | test_account_experience.py | PASS |
| A-14 | Data retention schedule | api_v1_account.py:1589-1670 | test_retention_tasks.py | PASS |
| A-15 | Export encryption at rest | NOT IMPLEMENTED | None | **FAIL** |

### C) Production Hardening

| # | Requirement | Implemented | Tests | Status |
|---|-------------|------------|-------|--------|
| H-01 | HSTS | Caddyfile | check_api_security_headers.sh | PASS |
| H-02 | X-Content-Type-Options | Caddyfile | check_api_security_headers.sh | PASS |
| H-03 | X-Frame-Options | Caddyfile | check_api_security_headers.sh | PASS |
| H-04 | Referrer-Policy | Caddyfile | check_api_security_headers.sh | PASS |
| H-05 | Permissions-Policy | Caddyfile | check_api_security_headers.sh | PASS |
| H-06 | CSP | Caddyfile | check_api_security_headers.sh | PASS |
| H-07 | Server banner hidden | Caddyfile | check_api_security_headers.sh | PASS |
| H-08 | CORS explicit origins | web/app.py | deploy.sh | PARTIAL |
| H-09 | Rate limiting (5 tiers) | web/rate_limit.py | test_rate_limit.py | PASS |
| H-10 | Idempotency keys | web/idempotency.py | test_idempotency.py | PASS |
| H-11 | Request IDs | web/api_utils.py | test_api_utils.py | PASS |
| H-12 | Health check (DB+Redis+Celery) | routes/health.py | deploy.sh | PASS |
| H-13 | Daily DB backups | pg_dump cron 3 AM UTC | Manual | PASS |
| H-14 | Stripe webhook signature | routes/billing.py:224-233 | test_billing_webhook.py | PASS |
| H-15 | Webhook dedup | routes/billing.py:82-148 | test_billing_webhook.py | PASS |
| H-16 | Webhook event ordering | routes/billing.py:100-128 | test_billing_webhook.py | PASS |
| H-17 | Reconciliation job | tasks/billing_tasks.py hourly | test_billing_tasks.py | PASS |
| H-18 | Grace period enforcement | tasks/billing_tasks.py daily | test_billing_tasks.py | PASS |

### D) Race Control Admin

| # | Requirement | Implemented | Tests | Status |
|---|-------------|------------|-------|--------|
| R-01 | Superadmin + TOTP required | admin/middleware.py:90-118 | test_admin_middleware.py | PASS |
| R-02 | 5 admin roles | admin/middleware.py require_admin_role | test_admin_rbac_matrix.py | PASS |
| R-03 | Inspect failing jobs | routes/admin/jobs.py | test_admin_jobs.py | PASS |
| R-04 | Retry jobs safely | routes/admin/jobs.py | test_admin_jobs.py | PASS |
| R-05 | Entitlement snapshot | routes/admin/entitlements.py | test_admin_entitlements_route.py | PASS |
| R-06 | Quota counters | routes/admin/entitlements.py | test_admin_entitlements_route.py | PASS |
| R-07 | Webhook events | routes/admin/billing.py | test_admin_billing.py | PASS |
| R-08 | Heal Stripe mismatches | routes/admin/billing.py | test_admin_billing.py | PASS |
| R-09 | Email delivery logs | routes/admin/email.py | test_admin_email.py | PASS |
| R-10 | Audit log immutability | admin_audit_log append-only | test_admin_security_route.py | PASS |
| R-11 | Admin actions logged | admin/audit.py | test_admin_security_route.py | PASS |
| R-12 | Incident tracking | routes/admin/security.py | test_admin_security_route.py | PASS |
| R-13 | Frontend (16 pages) | app/race-control/ | e2e/ tests | PASS |
| R-14 | Retention deletion queue | routes/admin/entitlements.py GET /retention/pending | test_admin_retention_queue.py | PASS — fixed 819fb70 |

### E) Multi-Tenant + Security

| # | Requirement | Implemented | Tests | Status |
|---|-------------|------------|-------|--------|
| S-01 | RLS on 44 tables | 007_enable_rls.py | test_tenant_middleware.py | PASS |
| S-02 | No cross-workspace access | RLS USING+WITH CHECK | Mocked only | PARTIAL |
| S-03 | JWT HS256 with expiry | auth/service.py:57-80 | test_auth_service.py | PASS |
| S-04 | Refresh token rotation | routes/auth.py:325-365 | test_auth_service.py | PASS |
| S-05 | Refresh httpOnly cookie | routes/auth.py:23-34 | test_auth_service.py | PASS |
| S-06 | TOTP RFC 6238 | auth/totp.py:43-163 | test_account_security.py | PASS |
| S-07 | Backup codes | auth/totp.py:130-162 | test_account_security.py | PASS |
| S-08 | OAuth email_verified | auth/oauth.py:72-78 | test_auth_oauth.py | PASS |
| S-09 | CSRF double-submit | middleware/csrf.py | test_csrf.py | PASS |
| S-10 | Account suspension | middleware/auth.py:88-104 | test_auth_middleware.py | PASS |
| S-11 | Legacy route IDOR | No workspace filter in SQLite | None | PARTIAL |

### F) Infrastructure

| # | Requirement | Implemented | Status |
|---|-------------|------------|--------|
| I-01 | Celery beat (10 tasks) | celery_app.py:68-120 | PASS |
| I-02 | Deploy script (6 stages) | scripts/deploy.sh | PASS |
| I-03 | Security headers script | scripts/check_api_security_headers.sh | PASS |
| I-04 | Entitlement consistency | scripts/verify_entitlement_consistency.py | PASS |
| I-05 | Runbook: Stripe down | docs/runbooks/stripe-webhook-down.md | PASS |
| I-06 | Runbook: Queue stuck | docs/runbooks/job-queue-stuck.md | PASS |
| I-07 | Runbook: DB spike | docs/runbooks/db-cpu-spike.md | PASS |
| I-08 | Runbook: Upload failures | docs/runbooks/upload-failures.md | PASS |
| I-09 | Runbook: GDPR backlog | docs/runbooks/gdpr-backlog.md | PASS — fixed 606e829 |
| I-10 | Runbook: 5xx origin | docs/runbooks/origin-5xx-errors.md | PASS — fixed 606e829 |
| I-11 | Post-deploy CORS check | scripts/verify_production.sh (test 3) | PASS — fixed 606e829 |
| I-12 | Post-deploy OPTIONS | scripts/verify_production.sh (test 4) | PASS — fixed 606e829 |
| I-13 | Post-deploy auth smoke | scripts/verify_production.sh (test 5) | PASS — fixed 606e829 |

---

## 3. Gap Analysis

### Critical (must fix) — ALL RESOLVED

| ID | Gap | Fix | Commit |
|----|-----|-----|--------|
| G-01 | Middleware uses check_quota() not check_and_record_quota() | Switched to atomic check_and_record_quota() with SELECT FOR UPDATE | c5878fb |
| G-02 | ~50+ mutation routes have zero entitlement gates | Expanded to 14 feature gates + 5 quota gates | e8014a1 |
| G-03 | /files/upload has no quota or tier-aware size limit | Added @require_upload_size decorator with tier-aware limits | dac4f28 |
| G-04 | Celery workers don't re-check entitlements | Added _verify_task_entitlements() fail-open guard | 1949663 |
| G-05 | /api/v1/race-strategy/* routes not covered by middleware | Added POST/PUT/DELETE gates for v1 race strategy | e8014a1 |

### High (should fix) — 4/5 RESOLVED

| ID | Gap | Fix | Status |
|----|-----|-----|--------|
| G-06 | 2 missing runbooks (GDPR backlog, 5xx origin) | Created both runbooks | FIXED 606e829 |
| G-07 | Post-deploy suite missing CORS/OPTIONS/auth smoke | Created scripts/verify_production.sh (8 checks) | FIXED 606e829 |
| G-08 | Export files not encrypted at rest | Accepted risk — 7-day TTL, server-only | ACCEPTED |
| G-09 | No admin endpoint for pending deletion queue | Added GET /admin/retention/pending | FIXED 819fb70 |
| G-10 | No real PG RLS integration test | Deferred — requires PG test container | OPEN |

### Medium (nice to have)

| ID | Gap | Impact |
|----|-----|--------|
| G-11 | No .env.production template | Onboarding friction |
| G-12 | Audit log retention unbounded | Storage growth |

---

## 4. Fix Plan

### G-01: Atomic Quota Enforcement
Change middleware/entitlements.py to call check_and_record_quota() instead of check_quota(). Move usage recording INTO the atomic check (eliminate after-request double-write for quota-gated routes).

### G-02: Expand Entitlement Gates
Add comprehensive _FEATURE_GATES and _QUOTA_GATES covering all mutation routes:
- Upload routes → "uploads" quota
- Race strategy v1/v2 → "race_strategy" feature
- Batch reanalyze → "reports" quota
- Annotations/dev-plans/dashboards → "member" feature (basic write access)
- Exports → "exports" feature
- Simulations → "race_strategy" feature

### G-03: Upload Quota + Tier Size Limits
Add @require_quota("uploads", 1) to upload route. Read max_upload_mb from user's plan entitlements and reject oversized files.

### G-04: Worker Entitlement Guard
Add _verify_entitlements() at top of Celery pipeline tasks. Fail fast with QUOTA_EXCEEDED if user has exhausted quota. Log as security event.

### G-05: V1 Race Strategy Gates
Add "/api/v1/race-strategy/" to _FEATURE_GATES alongside existing "/race-strategy/".

### G-06: Missing Runbooks
Write docs/runbooks/gdpr-backlog.md and docs/runbooks/origin-5xx-errors.md.

### G-07: Post-Deploy Verification Suite
Create scripts/verify_production.sh covering:
1. Marketing page availability
2. API health (/healthz)
3. CORS headers for both frontend origins
4. Preflight OPTIONS check
5. Auth smoke test (login endpoint returns 200 or 401, not 500)
6. Security headers contract (7 headers)

### G-08: Export Encryption
Document as accepted risk — exports are short-lived (7-day TTL), server-only storage, no external access. Add to GDPR compliance notes.

### G-09: Admin Retention Queue
Add GET /api/v1/admin/retention/pending endpoint showing users approaching retention expiry + pending deletions.

### G-10: RLS Integration Test
Add test_rls_isolation.py using real PG (test container or dedicated test DB) that verifies cross-workspace queries return empty results.

---

## 5. Post-Deploy Verification Suite Specification

Script: scripts/verify_production.sh

```
1. Marketing page: curl -sL https://lap-coach.racing → expect 200
2. API health: GET https://api.lap-coach.racing/healthz → expect 200 + JSON {ok: true}
3. CORS (lap-coach.racing): curl -H "Origin: https://lap-coach.racing" → check Access-Control-Allow-Origin
4. CORS (www): curl -H "Origin: https://www.lap-coach.racing" → check Access-Control-Allow-Origin
5. Preflight: OPTIONS /api/v1/sessions → check Allow-Methods includes GET,POST
6. Auth smoke: POST /auth/login with bad creds → expect 401 (not 500)
7. Security headers: check all 7 headers present + correct values
8. Stripe webhook: POST /api/v1/billing/webhook with no signature → expect 400 (not 500)
```

Exit codes: 0 = all pass, 1 = any failure (with details).

---

## 6. Environment Parity Table

| Variable | Required In | Default | Risk If Missing |
|----------|-------------|---------|-----------------|
| USE_PG | Backend prod | "0" | SQLite mode — no RLS, no multi-tenancy |
| AUTH_REQUIRED | Backend prod | "0" | No authentication — all routes open |
| TELEMETRY_JWT_SECRET | Backend prod | dev key | Token forgery possible |
| TELEMETRY_SECRET_KEY | Backend prod | dev key | Session/cookie forgery |
| STRIPE_SECRET_KEY | Backend prod | None | Billing non-functional |
| STRIPE_WEBHOOK_SECRET | Backend prod | None | Webhooks rejected |
| REDIS_URL | Backend prod | localhost | Rate limits, idempotency, Celery broken |
| TELEMETRY_PG_URL | Backend prod | localhost | DB connection failure |
| CORS_ALLOWED_ORIGINS | Backend prod | * | Open CORS in production |
| GOOGLE_CLIENT_ID | Backend prod | "" | Google OAuth disabled |
| GITHUB_CLIENT_ID | Backend prod | "" | GitHub OAuth disabled |
| NEXT_PUBLIC_API_URL | Frontend build | None | API calls fail |

---

## 7. Scorecard

### Before (pre-audit)

| Category | PASS | PARTIAL | FAIL | Total |
|----------|------|---------|------|-------|
| Entitlements (E) | 9 | 2 | 4 | 15 |
| Account (A) | 14 | 0 | 1 | 15 |
| Hardening (H) | 17 | 1 | 0 | 18 |
| Race Control (R) | 13 | 0 | 1 | 14 |
| Security (S) | 9 | 2 | 0 | 11 |
| Infrastructure (I) | 8 | 0 | 5 | 13 |
| **Total** | **70** | **5** | **11** | **86** |

### After (post-audit fixes)

| Category | PASS | PARTIAL | FAIL | Total | Delta |
|----------|------|---------|------|-------|-------|
| Entitlements (E) | 15 | 0 | 0 | 15 | +6 PASS |
| Account (A) | 14 | 0 | 1 | 15 | — |
| Hardening (H) | 17 | 1 | 0 | 18 | — |
| Race Control (R) | 14 | 0 | 0 | 14 | +1 PASS |
| Security (S) | 9 | 2 | 0 | 11 | — |
| Infrastructure (I) | 13 | 0 | 0 | 13 | +5 PASS |
| **Total** | **82** | **3** | **1** | **86** | **+12 PASS** |

**Overall: 82 PASS / 3 PARTIAL / 1 FAIL (95% pass rate, up from 81%)**

### Remaining items

| ID | Status | Notes |
|----|--------|-------|
| A-15 | FAIL (accepted risk) | Export files not encrypted at rest — 7-day TTL, server-only |
| H-08 | PARTIAL | CORS explicit origins — works but uses env var, not strict allowlist |
| S-02 | PARTIAL | RLS isolation verified via mocks only, no PG integration test |
| S-11 | PARTIAL | Legacy SQLite routes lack workspace filter (USE_PG=0 only) |
| G-10 | OPEN (deferred) | Real PG RLS integration test requires test container |
