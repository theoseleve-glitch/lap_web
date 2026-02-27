# Account Experience & Billing Ops — Design

**Date:** 2026-02-27
**Status:** Approved
**Scope:** Self-serve Account section for Lap Coach SaaS

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Billing management | Stripe hosted Customer Portal | PCI-compliant, less dev work, always current |
| 2FA | Full TOTP implementation | Ship complete with backup codes |
| Usage enforcement | Full enforcement now | Match marketing claims, block at limit |
| Navigation | Sidebar sub-navigation | Each section its own page, like Stripe Dashboard |
| Architecture | Entitlement-First | Local entitlements module, no external deps |

## 1. Information Architecture

### Navigation

Account section accessed via user avatar/menu in the app sidebar header. Opens a dedicated layout with its own sidebar:

```
/app/account                → redirect to /app/account/profile
/app/account/profile        → Profile & Preferences
/app/account/security       → Password, 2FA, Sessions, OAuth
/app/account/billing        → Plan, Stripe Portal, billing email
/app/account/usage          → Usage dashboard, limits, retention
/app/account/data           → Export, delete, consent
/app/account/support        → Contact form, status, changelog
```

### Subscription States

| State | Badge Color | Actions |
|-------|-------------|---------|
| `free` | steel | Upgrade CTA |
| `trialing` | marshal-yellow | Upgrade, cancel trial |
| `active` | acid-green | Manage, downgrade, cancel |
| `past_due` | safety-red | Update payment (urgent) |
| `canceled` | steel | Reactivate, shows end date |
| `unpaid` | safety-red | Update payment, contact support |

## 2. Entitlements System

### Module: `auth/entitlements.py`

Pure Python mapping from `billing_plan` to capabilities:

```python
PLAN_ENTITLEMENTS = {
    "free": {
        "reports_per_month": 1,
        "uploads_per_month": 1,
        "raw_retention_days": 30,
        "report_retention": "indefinite",
        "comparison_progress": False,
        "coaching_drills": False,
        "viz_workspace": False,
        "strategy_dashboard": "3h_limit",
        "live_pace": False,
        "pit_planning": False,
        "pdf_reports": False,
        "api_access": False,
        "track_management": "basic",
        "max_workspace_members": 1,
    },
    "racer": {
        "reports_per_month": 10,
        "uploads_per_month": 10,
        "raw_retention_days": 90,
        "report_retention": "indefinite",
        "comparison_progress": False,
        "coaching_drills": True,
        "viz_workspace": True,
        "strategy_dashboard": "full",
        "live_pace": True,
        "pit_planning": True,
        "pdf_reports": True,
        "api_access": False,
        "track_management": "full",
        "max_workspace_members": 1,
    },
    "world_class": {
        "reports_per_month": -1,  # unlimited
        "uploads_per_month": -1,
        "raw_retention_days": 365,
        "report_retention": "indefinite",
        "comparison_progress": True,
        "coaching_drills": True,
        "viz_workspace": True,
        "strategy_dashboard": "full",
        "live_pace": True,
        "pit_planning": True,
        "pdf_reports": True,
        "api_access": True,
        "track_management": "full",
        "max_workspace_members": 5,
    },
}
```

### Usage Tracking

New table:

```sql
CREATE TABLE usage_counters (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
    metric TEXT NOT NULL,
    period TEXT NOT NULL,           -- 'YYYY-MM'
    count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (workspace_id, metric, period)
);
```

### Enforcement

```
User action → @require_entitlement("upload_csv")
  → get_entitlements(workspace_id)  # plan → PLAN_ENTITLEMENTS
  → get_usage(workspace_id, metric, period)
  → count >= limit → 403 {error: "limit_reached", limit, used, upgrade_url}
  → else → allow + increment counter
```

### Limit-Hit Behavior

| Action | Behavior | Response |
|--------|----------|----------|
| Upload at limit | Blocked (403) | "10/10 uploads used. Upgrade or wait until [reset]." |
| Report at limit | Blocked (403) | Same pattern |
| Gated feature | Blocked (403) | "Available on Racer plan. [Upgrade]" |
| 80% threshold | Warning header | Soft banner in UI |

### Data Retention Enforcement

Celery beat task `enforce_data_retention` (daily):
1. Look up plan → `raw_retention_days` per workspace
2. Find sessions past retention window
3. Delete raw telemetry (keep processed reports)
4. Email notification 7 days before deletion

## 3. Security

### Password Change

`POST /api/v1/account/password`
- Requires `current_password` + `new_password`
- Argon2id validation and hashing
- Revokes all refresh tokens except current
- Sends "password changed" email

### Password Reset

`POST /auth/forgot-password` → sends reset email (1-hour token)
`POST /auth/reset-password` → validates token, sets password, revokes all sessions

### 2FA (TOTP)

**DB migration:**
```sql
ALTER TABLE users ADD COLUMN totp_secret TEXT;
ALTER TABLE users ADD COLUMN totp_enabled BOOLEAN DEFAULT false;
ALTER TABLE users ADD COLUMN totp_backup_codes TEXT[];
ALTER TABLE users ADD COLUMN totp_verified_at TIMESTAMPTZ;
```

**Endpoints:**
- `POST /api/v1/account/2fa/setup` → generates secret, returns otpauth URI + QR + backup codes
- `POST /api/v1/account/2fa/verify` → confirms setup with a valid code
- `DELETE /api/v1/account/2fa` → disables (requires password + TOTP code)
- `POST /api/v1/account/2fa/backup-codes/regenerate` → new codes (requires password + TOTP)

**Login with 2FA:**
1. `POST /auth/login` → `{ requires_2fa: true, temp_token }` (no access token)
2. `POST /auth/login/2fa` → `temp_token` + `totp_code` → normal tokens
3. Backup codes accepted as TOTP alternative (single-use, hashed)

### Session Management

- `GET /api/v1/account/sessions` → active refresh tokens with device_info, created_at
- `DELETE /api/v1/account/sessions/<id>` → revoke specific session
- `POST /api/v1/account/sessions/revoke-others` → revoke all except current

Device info captured from User-Agent on login/refresh.

### OAuth Management

- `GET /api/v1/account/oauth-connections` → linked providers with email and date
- `DELETE /api/v1/account/oauth-connections/<provider>` → unlink (blocked if last auth method)

## 4. Plan & Billing

### Endpoints

`GET /api/v1/account/billing` → live subscription status:
```json
{
  "plan": "racer",
  "status": "active",
  "billing_cycle": "monthly",
  "current_period_end": "2026-03-15T00:00:00Z",
  "cancel_at_period_end": false,
  "amount": 1990,
  "currency": "eur",
  "payment_method_last4": "4242",
  "payment_method_brand": "visa"
}
```

`POST /api/v1/account/billing/portal` → creates Stripe Customer Portal session, returns redirect URL

`POST /api/v1/account/billing/checkout` → upgrade/change plan:
- Existing subscribers: Stripe Portal with plan-change flow
- Free users: Stripe Checkout session

`PATCH /api/v1/account/billing/email` → update billing email on Stripe

### Stripe Customer Portal Config

Portal allows: update payment, view/download invoices, cancel, switch plans.

### Webhook Additions

- `invoice.paid` → clear past_due state
- `customer.subscription.updated` → track cancel_at_period_end, current_period_end

## 5. Profile & Preferences

### Endpoint Enhancement

`PATCH /api/v1/account/profile` extended:
```json
{
  "display_name": "string",
  "email": "string",
  "avatar_url": "string|null",
  "preferences": {
    "language": "en",
    "timezone": "Europe/Amsterdam",
    "units": "metric",
    "notifications": {
      "report_ready": true,
      "billing_alerts": true,
      "product_updates": false,
      "weekly_digest": true
    }
  }
}
```

**DB:** `ALTER TABLE users ADD COLUMN preferences JSONB DEFAULT '{}';`

Avatar: URL-only (Gravatar or OAuth provider). No file upload.

## 6. Data & Privacy

### Existing Endpoints (no changes needed)

| Action | Endpoint |
|--------|----------|
| Export data | `POST /api/v1/account/export` |
| Export status | `GET /api/v1/account/export/<id>/status` |
| Download export | `GET /api/v1/account/export/<id>/download` |
| Delete account | `DELETE /api/v1/account/` |
| Cancel deletion | `POST /api/v1/account/cancel-deletion` |

### New: Retention Visibility

`GET /api/v1/account/retention` → per-session expiry dates based on plan

### Frontend

Table showing each session with upload date and expiry date. Clear explanation of what's kept indefinitely (reports) vs. time-limited (raw telemetry).

Delete account: warning modal with 30-day grace period explanation.

## 7. Support

`POST /api/v1/support/ticket` → sends structured email via Resend:
- Fields: issue_type (bug/billing/feature/other), session_id (optional), description
- Auto-includes: user email, plan, browser info
- Sends to `support@lap-coach.racing`

Links to status page and changelog (external).

## 8. Email Templates (Resend)

| Email | Trigger |
|-------|---------|
| Password changed | Password update |
| Password reset link | Forgot password |
| 2FA enabled | TOTP setup complete |
| 2FA disabled | TOTP removed |
| Export ready | Export job complete |
| Account deletion scheduled | Delete request |
| Retention warning | 7 days before data deletion |
| New device login | Login from new device/IP |

## 9. New API Endpoints Summary

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/account/entitlements` | Plan features & limits |
| `GET` | `/api/v1/account/usage` | Monthly usage counters |
| `GET` | `/api/v1/account/billing` | Live subscription status |
| `POST` | `/api/v1/account/billing/portal` | Stripe Portal session |
| `POST` | `/api/v1/account/billing/checkout` | Upgrade/change plan |
| `PATCH` | `/api/v1/account/billing/email` | Billing email |
| `POST` | `/api/v1/account/password` | Change password |
| `POST` | `/auth/forgot-password` | Request password reset |
| `POST` | `/auth/reset-password` | Complete password reset |
| `POST` | `/api/v1/account/2fa/setup` | TOTP setup |
| `POST` | `/api/v1/account/2fa/verify` | Confirm TOTP setup |
| `DELETE` | `/api/v1/account/2fa` | Disable 2FA |
| `POST` | `/api/v1/account/2fa/backup-codes/regenerate` | New backup codes |
| `POST` | `/auth/login/2fa` | 2FA login step |
| `GET` | `/api/v1/account/sessions` | Active sessions list |
| `DELETE` | `/api/v1/account/sessions/<id>` | Revoke session |
| `POST` | `/api/v1/account/sessions/revoke-others` | Revoke other sessions |
| `GET` | `/api/v1/account/oauth-connections` | Linked OAuth providers |
| `DELETE` | `/api/v1/account/oauth-connections/<provider>` | Unlink provider |
| `GET` | `/api/v1/account/retention` | Data retention per session |
| `POST` | `/api/v1/support/ticket` | Submit support ticket |

## 10. New Migrations

**Migration 017: account_preferences_usage**
```sql
ALTER TABLE users ADD COLUMN preferences JSONB DEFAULT '{}';
ALTER TABLE users ADD COLUMN totp_secret TEXT;
ALTER TABLE users ADD COLUMN totp_enabled BOOLEAN DEFAULT false;
ALTER TABLE users ADD COLUMN totp_backup_codes TEXT[];
ALTER TABLE users ADD COLUMN totp_verified_at TIMESTAMPTZ;

CREATE TABLE usage_counters (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    metric TEXT NOT NULL,
    period TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (workspace_id, metric, period)
);

CREATE INDEX idx_usage_counters_lookup ON usage_counters(workspace_id, metric, period);
```

## 11. Frontend Components

### New Route Group: `/app/account/`

Layout with sidebar sub-navigation (6 items) and "Back to Dashboard" link.

### Pages

1. **Profile** — display name, email (with verification badge), avatar, language/timezone/units selectors, notification toggles
2. **Security** — password change form, 2FA setup wizard (QR + code input + backup codes display), active sessions table, OAuth connections list
3. **Billing** — plan card with status badge, quick action cards linking to Stripe Portal, billing email field
4. **Usage** — progress bars for each metric, reset date, limit-hit explanations, upgrade CTA
5. **Data** — export button + status, retention table, delete account with confirmation modal
6. **Support** — structured contact form, external links

### New Hooks

- `useAccount()` — fetches profile + preferences via `/api/v1/me`
- `useEntitlements()` — fetches plan features + limits
- `useUsage()` — fetches monthly usage counters
- `useBilling()` — fetches subscription status

### Design Tokens

Uses existing Tailwind theme: asphalt backgrounds, chalk text, acid-green accents, steel secondary. Teko headings, Inter body, IBM Plex Mono for data.
