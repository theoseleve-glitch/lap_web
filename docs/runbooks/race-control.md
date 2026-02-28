# Race Control — Operational Runbook

## Overview

Race Control is the internal admin dashboard at `/app/race-control/`. It provides health monitoring, user management, job operations, billing oversight, entitlements enforcement, security event tracking, and infrastructure controls.

**Access:** Requires `is_superadmin=true`, `totp_enabled=true`, and `admin_verified=true` JWT claim. Roles: `root_admin`, `support_admin`, `billing_admin`, `sre_admin`, `auditor`.

## Admin Bootstrap

```bash
# Promote a user to superadmin
python -m telemetry_tool.admin.bootstrap --email admin@lap-coach.racing --role root_admin

# Then set up 2FA via:
POST /api/v1/admin/2fa/setup    → returns otpauth:// URI
POST /api/v1/admin/2fa/verify   → confirms TOTP, enables 2FA
POST /api/v1/admin/2fa/challenge → issues admin JWT
```

## Common Triage Scenarios

### 1. Failed Job — Retry or Investigate

**Symptoms:** User reports stuck analysis, health overview shows elevated failure rate.

1. Navigate to **Race Control → Jobs** and filter by `failed`
2. Click the failed job to see error class and message
3. If transient (timeout, OOM): Click **Retry** with reason
4. If systematic (bad CSV, missing column): Check user's upload, notify via support
5. If Celery worker issue: Check **Infrastructure → Servers** for CPU/memory

**Guardrails:**
- Retry resets status to `queued` and increments `retry_count`
- All retries are audited with reason
- Only `sre_admin` and `root_admin` can retry/cancel

### 2. Payment Failure — Billing Reconciliation

**Symptoms:** User on paid plan can't access features, health overview shows billing mismatch.

1. Navigate to **Race Control → Billing → Reconciliation**
2. Look for rows where DB state ≠ Stripe state
3. For each mismatch, verify in Stripe dashboard
4. Click **Heal** to sync DB to Stripe authoritative state (root_admin only)
5. Check **Webhooks** tab for failed webhook deliveries

**Guardrails:**
- Heal is audited with admin ID and reason
- Only `root_admin` can heal mismatches
- Always verify Stripe state before healing

### 3. Security Incident — Auth Failure Spike

**Symptoms:** Health overview shows elevated login failures, security events page shows IP concentration.

1. Navigate to **Race Control → Security → Events**
2. Filter by `login_failed` to see pattern
3. Check **Auth Failures** section for top IPs (24h)
4. If single IP with many failures: Likely brute force → consider blocking at Cloudflare WAF
5. If distributed: Check for credential stuffing → review affected accounts
6. Navigate to **Audit Log** to verify no admin actions were compromised

**Actions:**
- For compromised account: **Users → [user] → Invalidate Sessions** (root_admin only)
- For IP blocking: Cloudflare WAF rule (outside Race Control)

### 4. Entitlement Override — Customer Support

**Symptoms:** Customer requests temporary feature access or quota increase.

1. Navigate to **Race Control → Entitlements**
2. Review current plan definitions for the customer's tier
3. Click **Create Override** with:
   - User ID
   - Key (e.g., `reports_per_month`)
   - Value (e.g., `50`)
   - Reason (required — audit trail)
4. Override takes effect immediately via entitlement resolution chain: override > plan_definitions > deny

**Guardrails:**
- All overrides are audited
- Only `billing_admin` and `root_admin` can create overrides
- Check anomalies section for any existing issues

### 5. Maintenance Mode

**Symptoms:** Planned deployment or emergency requiring downtime.

1. Navigate to **Race Control → Infrastructure**
2. Click **Enable Maintenance** with reason
3. All non-admin API requests return 503 with maintenance message
4. Admin endpoints and `/healthz` remain accessible
5. After maintenance: Click **Disable Maintenance**

**Guardrails:**
- Maintenance toggle is audited
- Only `sre_admin` and `root_admin` can toggle
- Health check remains available for monitoring

### 6. Email Verification Issues

**Symptoms:** User reports not receiving verification email.

1. Navigate to **Race Control → Email**
2. Check verification rate — if below 80%, investigate delivery issues
3. Enter user ID and click **Resend** with reason
4. Action is audited

## RBAC Quick Reference

| Area | root_admin | sre_admin | billing_admin | support_admin | auditor |
|------|:---:|:---:|:---:|:---:|:---:|
| Health Overview | ✓ | ✓ | ✓ | ✓ | ✓ |
| Health Metrics (time-series) | ✓ | ✓ | | | |
| Users (list/detail/timeline) | ✓ | ✓ | | ✓ | |
| Invalidate Sessions | ✓ | | | | |
| Jobs (list/detail) | ✓ | ✓ | | ✓ | |
| Jobs (retry/cancel) | ✓ | ✓ | | | |
| Job Stats | ✓ | ✓ | | | |
| Billing (subscriptions/revenue) | ✓ | | ✓ | | |
| Billing (webhooks) | ✓ | | ✓ | | |
| Reconciliation (view) | ✓ | | ✓ | | |
| Reconciliation (heal) | ✓ | | | | |
| Entitlements (plans/anomalies) | ✓ | | ✓ | | |
| Entitlements (overrides) | ✓ | | ✓ | | |
| Email (stats/resend) | ✓ | | | ✓ | |
| Security Events | ✓ | ✓ | | | ✓ |
| Audit Log | ✓ | | | | ✓ |
| Incidents (create/update) | ✓ | ✓ | | | |
| Incidents (list) | ✓ | ✓ | | | ✓ |
| Infrastructure (storage) | ✓ | ✓ | | | |
| Maintenance Mode | ✓ | ✓ | | | |

## Key Architecture Notes

- Admin routes bypass RLS (no `SET LOCAL`) — they see all workspaces
- All mutating actions are logged to `admin_audit_log` with admin ID, action, target, reason, IP, request_id
- 2FA is mandatory — `require_superadmin` checks both `is_superadmin` and `admin_verified` JWT claim
- Metrics collected every 60s by Celery beat task, stored in `system_metrics_snapshots`, pruned at 7 days
- Security events are instrumented at: login (success/fail), auth denied, token expired, rate limited, webhook signature
