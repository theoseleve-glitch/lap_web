# Race Control — Operational Command Center Design

**Date**: 2026-02-28
**Status**: Approved
**Approach**: Monolith Extension (Approach A)

## Summary

Production-grade admin dashboard ("Race Control") for Lap Coach that monitors, triages, and helps fix issues across: entitlements/authorization, usage & quotas, billing (Stripe), email (Resend), jobs/processing pipeline, storage/retention, security events, and infrastructure health (Hetzner + Cloudflare).

## Decisions

| Dimension | Decision |
|-----------|----------|
| Scope | Full v1, all modules, single phase |
| Frontend | Inside `lap-website` as `app/race-control/` route group |
| Admin auth | `is_superadmin` + `admin_role` on users table |
| 2FA | TOTP from scratch, required for admin accounts |
| Integrations | Server-side API calls to Stripe/Resend/Cloudflare/Hetzner |
| Entitlements | New system: plan_definitions + usage tracking + overrides (migration 019 tables) |
| Email | Resend is live — surface delivery stats via API |
| Observability | Lightweight: Celery periodic collector + PostgreSQL snapshots + on-demand external APIs |

## Existing Building Blocks

| Component | Location | Reusable? |
|-----------|----------|-----------|
| RBAC (4 roles, 17 permissions) | `auth/rbac.py` | Yes — extend PERMISSIONS |
| Auth middleware (JWT + allowlist) | `middleware/auth.py` | Yes — auto-protects `/api/v1/admin/*` |
| Tenant middleware (RLS) | `middleware/tenant.py` | Yes — admin bypasses RLS |
| Audit log table | Migration 019 | Yes — workspace-scoped events |
| API envelope + request ID | `api_utils.py` | Yes |
| Pydantic validation | `validation.py` | Yes |
| Rate limiting (5 tiers) | `rate_limit.py` | Yes |
| Idempotency (Redis) | `idempotency.py` | Yes |
| Job registry | `tasks/job_registry.py` | Yes — extend for admin queries |
| Celery (2 queues) | `tasks/pipeline_tasks.py` | Yes — add periodic beat |
| Health check | `routes/health.py` | Yes — extend |
| Stripe webhook handler | `routes/billing.py` | Yes — wrap with logging |
| Blueprint system | `web/app.py` | Yes — register `admin_bp` |
| Frontend auth + API client | `lap-website/src/lib/` | Yes |

---

## Section 1: Admin Auth & RBAC

### New DB Columns on `users` (Migration 020)

```sql
ALTER TABLE users ADD COLUMN is_superadmin BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN admin_role TEXT;
ALTER TABLE users ADD COLUMN totp_secret TEXT;
ALTER TABLE users ADD COLUMN totp_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN totp_recovery TEXT;
```

- `admin_role`: `root_admin` | `support_admin` | `billing_admin` | `sre_admin` | `auditor` | NULL
- `totp_secret`: AES-256 encrypted with `TELEMETRY_ADMIN_KEY` env var
- `totp_recovery`: Encrypted JSON array of single-use recovery codes

### Admin Role Permissions

| Role | Can View | Can Act | Cannot |
|------|----------|---------|--------|
| `root_admin` | Everything | Everything | — |
| `support_admin` | Users, plans, usage, jobs | Resend email, retry jobs, grant temp overrides | Change billing, view secrets |
| `billing_admin` | Users, billing, revenue | Apply credits, trigger entitlement refresh | Retry jobs, view infra |
| `sre_admin` | Infra, jobs, health, logs | Retry/cancel jobs, toggle maintenance | Change billing, modify users |
| `auditor` | Everything (read-only) | Nothing | All mutations |

### Admin Middleware

- `@require_superadmin`: checks `is_superadmin=True` AND `totp_enabled=True`
- `@require_admin_role(*roles)`: checks `admin_role` is in allowed set
- All `/api/v1/admin/*` routes auto-protected
- Admin queries bypass workspace RLS

### TOTP 2FA Flow

1. `POST /api/v1/admin/2fa/setup` — returns QR code URI + recovery codes
2. `POST /api/v1/admin/2fa/verify` — confirm setup with first code, sets `totp_enabled=TRUE`
3. Login flow: normal JWT + `POST /api/v1/admin/2fa/challenge` with TOTP code → `admin_verified` claim in JWT
4. Bootstrap: `python -m telemetry_tool.admin.bootstrap --email <email> --role root_admin`

---

## Section 2: Database Schema (Migration 020)

### `admin_audit_log` — Immutable, No RLS

```sql
CREATE TABLE admin_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    admin_user_id   INTEGER REFERENCES users(id) NOT NULL,
    action          TEXT NOT NULL,
    target_type     TEXT,
    target_id       TEXT,
    reason          TEXT,
    details_json    TEXT,
    ip_address      TEXT,
    request_id      TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_admin_audit_admin ON admin_audit_log(admin_user_id, created_at);
CREATE INDEX idx_admin_audit_target ON admin_audit_log(target_type, target_id);
CREATE INDEX idx_admin_audit_action ON admin_audit_log(action, created_at);
```

### `system_metrics_snapshots` — No RLS

```sql
CREATE TABLE system_metrics_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    collected_at    TIMESTAMPTZ DEFAULT now(),
    metrics_json    TEXT NOT NULL
);
CREATE INDEX idx_metrics_collected ON system_metrics_snapshots(collected_at);
```

### `stripe_webhook_log` — No RLS

```sql
CREATE TABLE stripe_webhook_log (
    id              BIGSERIAL PRIMARY KEY,
    stripe_event_id TEXT UNIQUE NOT NULL,
    event_type      TEXT NOT NULL,
    payload_json    TEXT,
    signature_valid BOOLEAN NOT NULL,
    processing_status TEXT DEFAULT 'pending',
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_stripe_wh_type ON stripe_webhook_log(event_type, created_at);
CREATE INDEX idx_stripe_wh_status ON stripe_webhook_log(processing_status);
```

### `security_events` — No RLS

```sql
CREATE TABLE security_events (
    id              BIGSERIAL PRIMARY KEY,
    event_type      TEXT NOT NULL,
    user_id         INTEGER REFERENCES users(id),
    ip_address      TEXT,
    user_agent      TEXT,
    details_json    TEXT,
    severity        TEXT DEFAULT 'info',
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_security_type_created ON security_events(event_type, created_at);
CREATE INDEX idx_security_ip ON security_events(ip_address, created_at);
```

### `incident_notes` — No RLS

```sql
CREATE TABLE incident_notes (
    id              BIGSERIAL PRIMARY KEY,
    admin_user_id   INTEGER REFERENCES users(id) NOT NULL,
    title           TEXT NOT NULL,
    body            TEXT,
    severity        TEXT DEFAULT 'p3',
    status          TEXT DEFAULT 'open',
    linked_entities TEXT,
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_incidents_status ON incident_notes(status, created_at);
```

**Design note**: Admin tables are NOT workspace-scoped and have NO RLS policies. Admins operate across all workspaces. The existing `audit_log` (migration 019) remains workspace-scoped for per-tenant activity.

---

## Section 3: Admin API Endpoints

### Backend Structure

```
telemetry_tool/
├── admin/                          # Service layer
│   ├── __init__.py
│   ├── bootstrap.py                # CLI: promote user to superadmin
│   ├── totp.py                     # TOTP setup, verify, recovery
│   ├── audit.py                    # log_admin_action(), log_security_event(), log_stripe_webhook()
│   ├── entitlements.py             # check_entitlement(), record_usage(), overrides
│   ├── metrics_collector.py        # Celery periodic task
│   ├── stripe_admin.py             # Stripe API queries
│   ├── resend_admin.py             # Resend API queries
│   ├── infra_poller.py             # Hetzner + Cloudflare API queries
│   └── reconciliation.py           # Stripe<->DB mismatch detection + heal
│
└── web/routes/admin/               # Blueprint package
    ├── __init__.py                 # admin_bp, registers sub-blueprints
    ├── middleware.py               # @require_superadmin, @require_admin_role
    ├── auth_admin.py               # 2FA setup/verify/challenge
    ├── users.py                    # User search, detail, timeline
    ├── jobs.py                     # Job list, detail, retry, cancel
    ├── billing.py                  # Stripe state, webhooks, reconciliation, revenue
    ├── entitlements.py             # Plan defs, overrides, quota usage, anomalies
    ├── email.py                    # Resend delivery stats, resend actions
    ├── security.py                 # Security events, audit log viewer
    ├── infra.py                    # Hetzner, Cloudflare, storage, maintenance
    └── health.py                   # System overview (aggregates all services)
```

### Endpoint Map (~35 endpoints)

#### Auth & 2FA
| Method | Path | Roles | Description |
|--------|------|-------|-------------|
| POST | `/admin/2fa/setup` | any admin | Generate TOTP secret + QR URI |
| POST | `/admin/2fa/verify` | any admin | Confirm TOTP setup |
| POST | `/admin/2fa/challenge` | any admin | Submit TOTP code during login |
| DELETE | `/admin/2fa` | root_admin | Disable 2FA for another admin |

#### System Health
| Method | Path | Roles | Description |
|--------|------|-------|-------------|
| GET | `/admin/health/overview` | any admin | Aggregated dashboard data |
| GET | `/admin/health/metrics` | sre, root | Time-series metrics snapshots |

#### Users
| Method | Path | Roles | Description |
|--------|------|-------|-------------|
| GET | `/admin/users` | support, root | Search/list users (paginated) |
| GET | `/admin/users/:id` | support, root | User detail |
| GET | `/admin/users/:id/timeline` | support, root | Recent user events |
| GET | `/admin/users/:id/workspaces` | support, root | Workspace memberships |
| POST | `/admin/users/:id/invalidate-sessions` | root | Force logout |

#### Jobs
| Method | Path | Roles | Description |
|--------|------|-------|-------------|
| GET | `/admin/jobs` | sre, support, root | Cross-workspace job list |
| GET | `/admin/jobs/:id` | sre, support, root | Job detail |
| POST | `/admin/jobs/:id/retry` | sre, root | Re-dispatch (audited, reason required) |
| POST | `/admin/jobs/:id/cancel` | sre, root | Cancel (audited, reason required) |
| GET | `/admin/jobs/stats` | any admin | Pipeline stats |

#### Billing
| Method | Path | Roles | Description |
|--------|------|-------|-------------|
| GET | `/admin/billing/subscriptions` | billing, root | Subscription list |
| GET | `/admin/billing/subscriptions/:id` | billing, root | Subscription detail |
| GET | `/admin/billing/webhooks` | billing, sre, root | Webhook event log |
| GET | `/admin/billing/reconciliation` | billing, root | DB<->Stripe mismatches |
| POST | `/admin/billing/reconciliation/:id/heal` | root | Sync DB to Stripe (audited) |
| GET | `/admin/billing/revenue` | billing, root | MRR/ARR snapshot |

#### Entitlements
| Method | Path | Roles | Description |
|--------|------|-------|-------------|
| GET | `/admin/entitlements/plans` | any admin | Plan definitions |
| GET | `/admin/entitlements/usage/:workspace_id` | support, billing, root | Usage per meter |
| GET | `/admin/entitlements/anomalies` | support, root | Quota/plan anomalies |
| POST | `/admin/entitlements/overrides` | support, root | Grant override (audited) |
| POST | `/admin/entitlements/refresh/:user_id` | support, root | Re-derive from Stripe |

#### Email
| Method | Path | Roles | Description |
|--------|------|-------|-------------|
| GET | `/admin/email/stats` | support, sre, root | Delivery dashboard |
| GET | `/admin/email/search` | support, root | Search emails |
| POST | `/admin/email/resend-verification/:user_id` | support, root | Resend verification |
| POST | `/admin/email/resend-export/:job_id` | support, root | Resend export link |

#### Security
| Method | Path | Roles | Description |
|--------|------|-------|-------------|
| GET | `/admin/security/events` | any admin | Security event list |
| GET | `/admin/security/audit-log` | auditor, root | Admin audit log |
| GET | `/admin/security/auth-failures` | any admin | Failure aggregations |
| POST | `/admin/incidents` | sre, root | Create incident note |
| PATCH | `/admin/incidents/:id` | sre, root | Update incident |
| GET | `/admin/incidents` | any admin | List incidents |

#### Infrastructure
| Method | Path | Roles | Description |
|--------|------|-------|-------------|
| GET | `/admin/infra/hetzner` | sre, root | Server metrics |
| GET | `/admin/infra/cloudflare` | sre, root | CDN/WAF stats |
| GET | `/admin/infra/storage` | sre, root | Storage breakdown |
| POST | `/admin/infra/maintenance` | sre, root | Toggle maintenance mode |

---

## Section 4: Frontend — Race Control UI

### Route Structure

```
lap-website/src/app/app/race-control/
├── layout.tsx              # Admin layout: sidebar, topbar, auth guard
├── page.tsx                # System Health Overview
├── users/
│   ├── page.tsx            # User search + list
│   └── [id]/page.tsx       # User detail + timeline
├── jobs/
│   ├── page.tsx            # Job list with filters
│   └── [id]/page.tsx       # Job detail + actions
├── billing/
│   ├── page.tsx            # Subscriptions + revenue
│   ├── webhooks/page.tsx   # Webhook event log
│   └── reconciliation/page.tsx
├── entitlements/
│   ├── page.tsx            # Plan defs + overrides
│   └── usage/[workspaceId]/page.tsx
├── email/page.tsx          # Delivery dashboard
├── security/
│   ├── page.tsx            # Security events
│   └── audit-log/page.tsx  # Admin audit log
├── infra/page.tsx          # Hetzner + Cloudflare + maintenance
└── incidents/
    ├── page.tsx            # Incident list
    └── [id]/page.tsx       # Incident detail
```

### Layout

- Distinct visual identity: red/amber accent (not acid-green)
- Topbar: "RACE CONTROL" + admin role badge
- Sidebar nav groups: OVERVIEW, OPERATIONS, REVENUE, COMMUNICATIONS, SECURITY, INFRASTRUCTURE
- Auth guard: check admin claim on mount, redirect to `/app/dashboard` if missing

### Shared Components

| Component | Purpose |
|-----------|---------|
| `AdminTable` | Paginated table, sorting, filters, CSV export |
| `AdminSearchBar` | Debounced search, query params |
| `StatusBadge` | Colored status badges |
| `CorrelationLink` | Cross-entity navigation |
| `ActionButton` | Confirmed mutation with reason input |
| `TimelineView` | Chronological event list |
| `MetricCard` | Stat card with trend + sparkline |
| `MetricGrid` | Grid of MetricCards |
| `AuditEntry` | Audit log row |

### State Management

- TanStack React Query (same as user app)
- `src/lib/admin-api.ts` — wrapper prefixing `/admin/`
- 30s polling on overview, manual refresh on drill-downs
- Next.js middleware checks `admin_role` JWT claim for `/app/race-control/*`

---

## Section 5: Entitlements System

### Core Service: `admin/entitlements.py`

```python
check_entitlement(conn, user_id, workspace_id, action) -> EntitlementResult
record_usage(conn, user_id, workspace_id, event_type, cost=1, metadata=None)
get_effective_entitlement(conn, user_id, workspace_id, key)
```

### Resolution Order

1. Check `entitlement_overrides` (user-level > workspace-level, skip expired)
2. Look up `plan_tier` → `plan_definitions` row
3. For quota actions, check `usage_monthly` against limit
4. Return allowed/denied with reason + remaining count

### Three Entitlement Types

- **Flag**: boolean (comparison_enabled, api_access)
- **Quota**: count/month (reports_per_month)
- **Limit**: numeric threshold (max_upload_size_mb, max_concurrent_jobs)

### Action Map

| Action | Plan Column | Type |
|--------|------------|------|
| `report.create` | `reports_per_month` | quota |
| `file.upload` | `max_upload_size_mb` | limit |
| `comparison.use` | `comparison_enabled` | flag |
| `coaching.use` | `coaching_plans_enabled` | flag |
| `visualization.use` | `visualization_enabled` | flag |
| `api.access` | `api_access` | flag |
| `strategy.use` | `race_strategy_limit` | enum |
| `export.format` | `export_formats` | set |
| `job.concurrent` | `max_concurrent_jobs` | limit |

### Enforcement

- `@require_entitlement(action)` decorator for routes
- Returns 403 with `QUOTA_EXCEEDED` or `FEATURE_NOT_AVAILABLE`
- Usage recorded after successful completion, not at check time

### Override Design

- `override_value = "null"` means unlimited (matches plan_definitions semantics)
- All overrides require `reason` and `expires_at`
- Created via `POST /api/v1/admin/entitlements/overrides` (audited)

### Anomaly Detection

- Quota overspend (usage > limit)
- Missing usage events (jobs exist but no usage_events)
- Stale overrides (expired but not cleaned)
- Plan/subscription mismatch (tier vs subscription_status)

---

## Section 6: Metrics Collection & Infrastructure

### Periodic Collector (Celery Beat, every 60s)

Collects from local sources only:

| Metric | Source |
|--------|--------|
| CPU/memory/disk | psutil |
| Celery queue depth | Redis LLEN |
| Active workers | celery.control.inspect |
| DB connections | pg_stat_activity |
| Job stats (1h) | ingestion_jobs aggregate |
| Security events (1h) | security_events count |
| Upload stats (today) | ingestion_jobs aggregate |

Stores as JSON in `system_metrics_snapshots`. Retention: 7 days (10,080 rows). Pruned on each collection run.

### On-Demand External APIs (5-min Redis cache)

| Service | What | Env Vars |
|---------|------|----------|
| Hetzner | CPU/disk/network (24h), server status | `HETZNER_API_TOKEN`, `HETZNER_SERVER_ID` |
| Cloudflare | Requests, bandwidth, cache ratio, WAF | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ZONE_ID` |
| Stripe | Events (cross-ref), subscriptions (reconciliation) | `STRIPE_SECRET_KEY` (existing) |
| Resend | Delivery stats, domain health | `RESEND_API_KEY` (existing) |

### Maintenance Mode

- Redis key `lap:maintenance_mode` (JSON: enabled, message, enabled_by, enabled_at)
- Flask `before_request` returns 503 for non-admin, non-health routes
- Frontend shows maintenance banner
- Admin routes remain accessible
- Toggle via `POST /api/v1/admin/infra/maintenance` (audited)

### Storage Monitoring

- `pg_total_relation_size()` / `pg_database_size()` for DB
- Filesystem checks for Parquet cache + report artifacts
- Upcoming deletions from `telemetry_retention_days` join

---

## Section 7: Security Events, Audit Logging & Webhook Logging

### Audit Helpers (`admin/audit.py`)

```python
log_admin_action(conn, admin_user_id, action, target_type, target_id, reason, details, ip, request_id)
log_security_event(conn, event_type, user_id, ip_address, user_agent, details, severity)
log_stripe_webhook(conn, stripe_event_id, event_type, payload, signature_valid, status, error)
```

### Security Event Instrumentation Points

| Location | Event | Severity |
|----------|-------|----------|
| `auth/service.py` login | `login_failed` / `login_success` | warning / info |
| `middleware/auth.py` | `auth_denied`, `token_expired` | warning / info |
| `auth/oauth.py` | `oauth_failed` | warning |
| `rate_limit.py` | `rate_limited` | warning |
| `middleware/tenant.py` | `workspace_access_denied` | warning |
| `admin/middleware.py` | `admin_access_denied` | critical |
| `admin/totp.py` | `totp_failed` | warning |
| `billing.py` webhook | `webhook_signature_invalid` | critical |

### Stripe Webhook Logging

Wrap existing `stripe_webhook()` handler:
1. Log event on receipt (`processing_status='pending'`)
2. After processing: update to `'processed'` or `'failed'`
3. `_sanitize_payload()` strips PCI-sensitive fields before storage

### Admin Actions Requiring `reason`

job.retry, job.cancel, entitlement.override_create, entitlement.refresh, billing.reconciliation_heal, email.resend_verification, email.resend_export, user.invalidate_sessions, maintenance.toggle, admin.2fa_disable

### Audit Log Details

```json
{
  "before": { "status": "failed" },
  "after": { "status": "pending" },
  "params": { "job_id": "abc-123" }
}
```

### Retention

- `security_events`: 90 days
- `admin_audit_log`: never deleted
- `stripe_webhook_log`: 90 days

---

## Section 8: Testing Strategy & Operational Runbooks

### Test Structure

```
telemetry_tool/tests/
├── test_admin_auth.py          # Superadmin, TOTP
├── test_admin_rbac.py          # Exhaustive role x endpoint matrix
├── test_admin_audit.py         # Log insertion, immutability
├── test_admin_jobs.py          # Cross-workspace list/retry/cancel
├── test_admin_billing.py       # Webhook log, reconciliation
├── test_admin_entitlements.py  # check/record/override/anomalies
├── test_admin_security.py      # Event logging, aggregation
├── test_admin_metrics.py       # Collector, snapshots, pruning
├── test_admin_email.py         # Resend mock, resend actions
├── test_admin_infra.py         # Maintenance mode

lap-website/e2e/admin/
├── job-triage.spec.ts          # Failed job -> retry -> verify
├── user-entitlement.spec.ts    # Access denied -> override -> verify
└── billing-reconcile.spec.ts   # Payment fail -> heal -> verify
```

### Permission Matrix Test

Parametrized: ~35 endpoints x 5 roles = ~175 test cases in one function.

### E2E Triage Flows

**Flow 1**: Failed job -> Jobs page -> filter failed -> job detail -> retry with reason -> verify recovered

**Flow 2**: User can't access feature -> Users search -> check entitlements -> create override -> verify access

**Flow 3**: Payment failure -> overview alert -> billing subscriptions -> check Stripe -> heal mismatch -> verify

### Operational Runbooks

| Scenario | Steps |
|----------|-------|
| User can't upload | Users -> search -> plan_tier -> usage check -> override or suggest upgrade |
| Stuck job (>30m) | Jobs -> filter running >30m -> cancel -> retry with reason |
| Webhook failures | Billing -> Webhooks -> filter failed -> check error -> Stripe auto-retries |
| Login failure spike | Security -> Auth Failures -> top IPs -> Cloudflare block if brute force |
| Disk limit | Infra -> Storage -> large workspaces -> enforce retention |
| Deploy | Maintenance ON -> deploy -> /healthz check -> maintenance OFF |

### Guardrails

- Never heal reconciliation without checking Stripe Dashboard
- Never retry >3x without investigating root cause
- Never disable 2FA without verbal confirmation
- Never grant overrides without expiry

---

## New Environment Variables

| Variable | Purpose |
|----------|---------|
| `TELEMETRY_ADMIN_KEY` | AES-256 key for TOTP secret encryption |
| `HETZNER_API_TOKEN` | Hetzner Cloud API (read-only) |
| `HETZNER_SERVER_ID` | Hetzner server ID |
| `CLOUDFLARE_API_TOKEN` | Cloudflare API (Analytics:Read, Firewall:Read) |
| `CLOUDFLARE_ZONE_ID` | Cloudflare zone for lap-coach.racing |
