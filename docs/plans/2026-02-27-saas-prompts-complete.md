# Lap Coach SaaS — Complete Implementation Prompts

> 15 prompts (3 per section × 5 sections), optimized for Claude/AI agent execution.
> Each prompt is self-contained with exact file paths, codebase context, and acceptance criteria.
> Date: 2026-02-27

---

## SECTION 1 — TIER-BASED AUTHORIZATIONS

### PROMPT 1A — Entitlement Data Model + Plan Definitions + Migration

**Team**: Staff Backend Engineer (data model), Billing Engineer (Stripe mapping), DBA (migration safety)

**Context — What exists today**:
- 4 RBAC roles in `telemetry_tool/auth/rbac.py` (viewer/member/admin/owner) with 17 workspace-scoped permissions
- Billing columns on `users` table (migration 016): `stripe_customer_id`, `stripe_subscription_id`, `billing_plan` (VARCHAR, default="free")
- Stripe webhook handler in `telemetry_tool/web/routes/billing.py` processes 4 event types, sets `billing_plan` to Stripe status strings ("active", "past_due", "free")
- **No plan-to-feature mapping** — `billing_plan` stores Stripe status, not the actual tier (demo/racer/world-class)
- **No usage tracking tables** — no `usage_events`, `quotas`, `entitlements` tables
- 3 B2C tiers defined in `lap-website/src/data/pricing.ts`: DEMO (free), RACER (€8.99/mo), WORLD-CLASS (€13.99/mo) + B2B (contact sales)
- Feature eligibility matrix in same file: 16 features across 3 groups (engineer, strategist, data)
- Data lifecycle: raw telemetry retention 1mo/3mo/12mo per tier, reports indefinite (B2C) / 2yr (B2B)
- Alembic migrations 001–018 exist. Next migration = 019.
- SQL compatibility layer in `telemetry_tool/db/sql_compat.py` auto-translates SQLite→PG

**What you must deliver**:

**A) Fix the billing_plan semantics gap**

The current `billing_plan` column conflates Stripe subscription STATUS with plan TIER. Fix this:

1. Add `plan_tier VARCHAR(30) DEFAULT 'demo'` column to `users` table — stores the actual tier: `demo`, `racer`, `world-class`, `b2b`
2. Keep `billing_plan` as `subscription_status` (rename for clarity): `free`, `trialing`, `active`, `past_due`, `canceled`, `paused`
3. Update `telemetry_tool/web/routes/billing.py`:
   - In `_handle_checkout_completed()`: extract the plan tier from `session.metadata.plan_tier` or from the Stripe price ID → tier mapping
   - In `_handle_subscription_updated()`: only update `subscription_status`, not `plan_tier` (tier changes come from checkout or plan switch events)
   - In `_handle_subscription_deleted()`: set `subscription_status='canceled'` but keep `plan_tier` until grace period ends, then reset to `demo`

**B) Create the entitlement tables (migration 019)**

Create file `telemetry_tool/alembic/versions/019_entitlements_usage.py`:

```sql
-- Plan definitions (seeded, rarely changes)
CREATE TABLE plan_definitions (
    tier VARCHAR(30) PRIMARY KEY,           -- demo, racer, world-class, b2b
    display_name VARCHAR(100) NOT NULL,
    reports_per_month INT,                  -- NULL = unlimited
    max_upload_size_mb INT DEFAULT 500,
    telemetry_retention_days INT NOT NULL,
    api_access BOOLEAN DEFAULT FALSE,
    comparison_enabled BOOLEAN DEFAULT FALSE,
    coaching_plans_enabled BOOLEAN DEFAULT FALSE,
    visualization_enabled BOOLEAN DEFAULT FALSE,
    race_strategy_limit VARCHAR(20),        -- 'limited_3h', 'full', NULL
    live_monitoring BOOLEAN DEFAULT FALSE,
    export_formats JSONB DEFAULT '["csv"]',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Usage events (append-only, high-write)
CREATE TABLE usage_events (
    id BIGSERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id),
    workspace_id INT NOT NULL REFERENCES workspaces(id),
    event_type VARCHAR(100) NOT NULL,       -- 'report_generated', 'csv_uploaded', 'api_call', 'comparison_run'
    cost INT DEFAULT 1,                     -- for weighted metering
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_usage_events_lookup ON usage_events (workspace_id, event_type, created_at);
CREATE INDEX idx_usage_events_user ON usage_events (user_id, created_at);

-- Monthly aggregates (materialized by Celery task or trigger)
CREATE TABLE usage_monthly (
    id SERIAL PRIMARY KEY,
    workspace_id INT NOT NULL REFERENCES workspaces(id),
    period_start DATE NOT NULL,             -- first of month
    event_type VARCHAR(100) NOT NULL,
    total INT DEFAULT 0,
    UNIQUE (workspace_id, period_start, event_type)
);

-- Entitlement overrides (for grandfathering, add-ons, support credits)
CREATE TABLE entitlement_overrides (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    workspace_id INT REFERENCES workspaces(id),
    override_key VARCHAR(100) NOT NULL,     -- 'reports_per_month', 'telemetry_retention_days', etc.
    override_value JSONB NOT NULL,          -- {"value": 50} or {"value": true}
    reason VARCHAR(255),                    -- 'support_credit', 'grandfathered', 'promo_2026Q1'
    expires_at TIMESTAMPTZ,                 -- NULL = permanent
    created_by INT REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_overrides_user ON entitlement_overrides (user_id) WHERE user_id IS NOT NULL;
CREATE INDEX idx_overrides_workspace ON entitlement_overrides (workspace_id) WHERE workspace_id IS NOT NULL;

-- Audit log (billing + entitlement changes)
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    workspace_id INT REFERENCES workspaces(id),
    action VARCHAR(100) NOT NULL,           -- 'plan_changed', 'override_created', 'member_added', etc.
    details JSONB,
    ip_address INET,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_audit_log_user ON audit_log (user_id, created_at);

-- Add plan_tier column to users
ALTER TABLE users ADD COLUMN plan_tier VARCHAR(30) DEFAULT 'demo';
-- Rename billing_plan for clarity
ALTER TABLE users RENAME COLUMN billing_plan TO subscription_status;
```

**C) Seed the plan definitions**

Insert rows matching `lap-website/src/data/pricing.ts` exactly:

| tier | reports/mo | retention_days | api_access | comparison | coaching | viz | strategy | live | exports |
|------|-----------|----------------|------------|------------|----------|-----|----------|------|---------|
| demo | 1 | 30 | false | false | false | false | limited_3h | false | ["csv"] |
| racer | 10 | 90 | false | false | true | true | full | true | ["pdf","csv"] |
| world-class | NULL | 365 | true | true | true | true | full | true | ["pdf","csv","api"] |
| b2b | NULL | NULL | true | true | true | true | full | true | ["pdf","csv","api","branded"] |

**D) Add RLS policies for new tables**

Apply RLS to `usage_events`, `usage_monthly`, `entitlement_overrides`, `audit_log` — follow the pattern from migrations 004-008 (policy: `workspace_id = current_setting('app.current_workspace_id')::int`).

`plan_definitions` is NOT workspace-scoped (global config table).

**E) Write backend entitlement resolver**

Create `telemetry_tool/auth/entitlements.py`:

```python
def get_user_entitlements(conn, user_id: int) -> dict:
    """Resolve effective entitlements for a user.

    Priority: entitlement_overrides > plan_definitions > defaults
    Returns dict with all feature keys + limits + remaining quotas.
    """
```

This function must:
1. Read `plan_tier` from `users` table
2. Read matching row from `plan_definitions`
3. Read active (non-expired) `entitlement_overrides` for user/workspace
4. Merge overrides on top of plan defaults
5. Read current month's `usage_monthly` totals
6. Compute `remaining` for quota-limited features (reports_per_month - used_this_month)
7. Return a flat dict: `{"reports_per_month": 10, "reports_used": 3, "reports_remaining": 7, "api_access": false, ...}`

**F) Write Stripe price ID → tier mapping**

Create a mapping in `telemetry_tool/web/routes/billing.py` or config:

```python
STRIPE_PRICE_TO_TIER = {
    os.environ.get("STRIPE_PRICE_RACER_MONTHLY"): "racer",
    os.environ.get("STRIPE_PRICE_RACER_ANNUAL"): "racer",
    os.environ.get("STRIPE_PRICE_WORLDCLASS_MONTHLY"): "world-class",
    os.environ.get("STRIPE_PRICE_WORLDCLASS_ANNUAL"): "world-class",
}
```

Update `_handle_checkout_completed()` to resolve `plan_tier` from the line items' price IDs.

**Tests required**:
- Migration 019 up/down successfully
- `get_user_entitlements()` returns correct values for each tier
- Overrides correctly merge on top of plan defaults
- Expired overrides are ignored
- `plan_tier` correctly resolved from Stripe checkout events
- Seeded `plan_definitions` match pricing.ts exactly

**Acceptance criteria**:
- `SELECT * FROM plan_definitions` returns 4 rows matching the pricing page
- `get_user_entitlements(conn, user_id)` returns complete entitlement dict for any user
- Billing webhook correctly sets both `plan_tier` and `subscription_status`
- All new tables have RLS policies (except `plan_definitions`)
- Migration is reversible (downgrade works)

---

### PROMPT 1B — Authorization Middleware + Quota Enforcement + Usage Tracking

**Team**: Staff Backend Engineer (middleware), Security Engineer (bypass prevention), SRE (atomicity)

**Context — What exists today**:
- Entitlement resolver from PROMPT 1A: `telemetry_tool/auth/entitlements.py` with `get_user_entitlements(conn, user_id)`
- RBAC middleware in `telemetry_tool/auth/rbac.py`: `@require_role()`, `@require_permission()` — checks workspace role only
- Tenant middleware in `telemetry_tool/web/middleware/tenant.py`: sets `g.workspace_id`, `g.workspace_role` from `X-Workspace-Id` header
- Auth middleware in `telemetry_tool/web/middleware/auth.py`: JWT verification, sets `g.user_id`
- Rate limiter in `telemetry_tool/web/rate_limit.py`: 5 tiers (auth/read/write/analyze/upload), Redis sliding window, NOT plan-aware
- API response envelope: `telemetry_tool/web/api_utils.py` with `api_error(ErrorCode, message, status)` and `api_response(data, status)`
- 32 blueprints registered in `telemetry_tool/web/app.py`
- Usage tables from PROMPT 1A: `usage_events`, `usage_monthly`

**What you must deliver**:

**A) Create the authorization gate functions**

Add to `telemetry_tool/auth/entitlements.py`:

```python
def authorize_feature(conn, user_id: int, feature: str) -> tuple[bool, dict]:
    """Check if a user can access a feature.

    Returns (allowed, context) where context contains:
    - allowed: bool
    - reason: str (if denied)
    - upgrade_tier: str (the tier that unlocks this feature)
    - current_tier: str
    """

def check_quota(conn, user_id: int, workspace_id: int, meter_key: str, cost: int = 1) -> tuple[bool, dict]:
    """Check if a quota-limited action is allowed.

    Returns (allowed, context) where context contains:
    - allowed: bool
    - remaining: int
    - limit: int (NULL = unlimited → always allowed)
    - resets_at: datetime (first of next month)
    """

def record_usage(conn, user_id: int, workspace_id: int, event_type: str, cost: int = 1, metadata: dict = None):
    """Record a usage event. Idempotent via metadata.idempotency_key if provided.

    Also updates usage_monthly aggregate (upsert).
    """
```

**B) Create Flask decorators for feature gating**

Add to `telemetry_tool/auth/entitlements.py`:

```python
def require_feature(feature: str):
    """Decorator: denies requests if user's plan doesn't include this feature.

    Returns 403 with upgrade CTA:
    {
        "ok": false,
        "error": {
            "code": "PLAN_REQUIRED",
            "message": "Comparison requires World-Class plan",
            "upgrade_tier": "world-class",
            "upgrade_url": "/billing?plan=WORLD-CLASS"
        }
    }
    """

def require_quota(meter_key: str, cost: int = 1):
    """Decorator: checks + reserves quota before running endpoint.

    Returns 429 with quota info:
    {
        "ok": false,
        "error": {
            "code": "QUOTA_EXCEEDED",
            "message": "Monthly report limit reached (10/10)",
            "limit": 10,
            "remaining": 0,
            "resets_at": "2026-04-01T00:00:00Z"
        }
    }
    """
```

**C) Wire decorators to existing routes**

Apply `@require_feature` and `@require_quota` to ALL relevant API routes. Key mappings:

| Route file | Endpoint | Feature gate | Quota gate |
|-----------|----------|-------------|------------|
| `routes/ingest.py` | POST /upload | — | `@require_quota("csv_uploads")` |
| `routes/analysis.py` | POST /analyze | — | `@require_quota("reports")` |
| `routes/comparisons.py` | POST /compare | `@require_feature("comparison")` | — |
| `routes/visualize.py` | GET /visualize/* | `@require_feature("visualization")` | — |
| `routes/race_strategy_v2.py` | POST /strategy | `@require_feature("race_strategy")` | — |
| `routes/api_v1_data.py` | GET /data/* | `@require_feature("api_access")` | `@require_quota("api_calls")` |
| `routes/exports.py` | POST /export | `@require_feature("export_pdf")` | — |

For race strategy with the DEMO 3-hour limit: check inside the route handler (not decorator) — `if plan_tier == "demo" and race_duration_hours > 3: deny()`.

**D) Enforce quotas atomically**

The `check_quota` + `record_usage` pattern must be atomic to prevent race conditions:

```python
def check_and_record_quota(conn, user_id, workspace_id, meter_key, cost=1, metadata=None):
    """Atomic check-then-record using SELECT FOR UPDATE on usage_monthly."""
    # BEGIN TRANSACTION (already in request context)
    # SELECT ... FROM usage_monthly WHERE ... FOR UPDATE
    # If total + cost > limit: return denied
    # INSERT INTO usage_events + UPSERT usage_monthly
    # COMMIT happens at request end
```

Use `FOR UPDATE` on the `usage_monthly` row to prevent concurrent over-spending.

**E) Record usage after successful actions**

In each gated route, after the action succeeds, call `record_usage()`. Do NOT record usage if the action fails. Pattern:

```python
@bp.route("/analyze", methods=["POST"])
@require_quota("reports", cost=1)
def analyze():
    result = run_analysis(...)
    if result.success:
        record_usage(conn, g.user_id, g.workspace_id, "report_generated", metadata={"session_id": sid})
    return api_response(result.data)
```

**F) Create Celery task for monthly usage aggregation**

Create `telemetry_tool/tasks/usage_tasks.py`:
- `aggregate_monthly_usage()` — runs daily via Celery Beat, materializes `usage_monthly` from `usage_events` for current month
- `cleanup_old_usage_events()` — runs weekly, deletes `usage_events` older than 90 days (aggregates are kept)

**G) Expose entitlements on /api/v1/me**

Update the `/api/v1/me` endpoint (in `telemetry_tool/web/routes/auth.py`) to include the user's resolved entitlements:

```json
{
    "ok": true,
    "data": {
        "user_id": 42,
        "email": "user@example.com",
        "plan_tier": "racer",
        "subscription_status": "active",
        "entitlements": {
            "reports_per_month": 10,
            "reports_used": 3,
            "reports_remaining": 7,
            "api_access": false,
            "comparison_enabled": false,
            "visualization_enabled": true,
            "telemetry_retention_days": 90
        }
    }
}
```

**Tests required**:
- `authorize_feature()` correctly allows/denies for each tier × feature combination
- `check_quota()` correctly counts current month usage
- `check_and_record_quota()` is atomic under concurrent requests (test with threading)
- Decorators return correct error format with upgrade CTA
- `/api/v1/me` includes resolved entitlements
- Usage recording is idempotent when `idempotency_key` is provided
- Monthly aggregation Celery task produces correct totals

**Acceptance criteria**:
- No API route allows a feature the user's plan doesn't include
- Quota-limited actions fail with 429 when quota is exceeded
- Error responses include machine-readable upgrade path
- Usage is tracked for every billable action
- Race conditions on quota spending are prevented via `FOR UPDATE`

---

### PROMPT 1C — Plan-Aware Rate Limiting + Retention Enforcement + Frontend Feature Gating

**Team**: SRE (rate limits), Backend Engineer (retention), Staff Frontend Engineer (UI gating)

**Context — What exists today**:
- Rate limiter in `telemetry_tool/web/rate_limit.py`: 5 tiers with fixed limits (e.g., `analyze: 5/hr`, `upload: 10/hr`), NOT plan-aware
- Entitlement resolver + authorization from PROMPTS 1A/1B
- Data lifecycle defined in `lap-website/src/data/pricing.ts`: raw telemetry retention 30/90/365 days per tier
- GDPR purge task in `telemetry_tool/tasks/gdpr_tasks.py`: handles account deletion, NOT retention-based cleanup
- Celery Beat configured in `telemetry_tool/tasks/celery_app.py` with `pipeline` and `default` queues
- Frontend state: Zustand 5 (`lap-website/src/lib/auth-store.ts`), React Query 5 for server state
- Frontend auth: `authFetch()` in `lap-website/src/lib/auth.ts`, `apiFetch()` in `lap-website/src/lib/api-client.ts`
- API envelope: `{ok, data, error, meta}` — frontend expects this shape

**What you must deliver**:

**A) Make rate limits plan-aware**

Update `telemetry_tool/web/rate_limit.py`:

```python
PLAN_RATE_MULTIPLIERS = {
    "demo": 1.0,
    "racer": 2.0,
    "world-class": 5.0,
    "b2b": 10.0,
}
```

Modify the `rate_limit()` decorator to:
1. Read `g.plan_tier` (set by tenant middleware or a new entitlement middleware)
2. Multiply the base tier limits by the plan multiplier
3. Keep the fail-open behavior (no Redis → allow through)
4. Log plan-aware rate limit hits for observability

Add `g.plan_tier` to the tenant middleware (`telemetry_tool/web/middleware/tenant.py`): after resolving `g.user_id`, read the user's `plan_tier` from the `users` table and set `g.plan_tier`.

**B) Implement telemetry retention enforcement**

Create `telemetry_tool/tasks/retention_tasks.py`:

```python
@celery.task(queue="default")
def enforce_telemetry_retention():
    """Daily Celery Beat task: delete raw telemetry past plan retention window.

    For each workspace:
    1. Resolve the plan_tier of the workspace owner
    2. Look up telemetry_retention_days from plan_definitions
    3. Find sessions where created_at < now() - retention_days
    4. Delete: gps_traces, raw_telemetry_chunks, session files
    5. Keep: processed reports, scores, laps (these have indefinite retention)
    6. Mark sessions as 'retention_expired' (don't delete the session row)
    7. Log deletions to audit_log
    """
```

Must handle:
- Sessions with `retention_expired` status are skipped (idempotent)
- B2B with NULL retention = never auto-delete
- Entitlement overrides for retention (check `entitlement_overrides` first)
- Batch processing (don't load all sessions at once)
- Dry-run mode via env var `RETENTION_DRY_RUN=1`

**C) Notify users before retention deletion**

Create email notifications (using Resend, pattern from `telemetry_tool/auth/email.py`):
- 7 days before deletion: "Your raw telemetry for session X will be deleted in 7 days. Export now or upgrade."
- Day of deletion: "Raw telemetry for session X has been deleted. Your reports are still available."

Add to `telemetry_tool/auth/email.py`:
```python
def send_retention_warning(email: str, sessions: list[dict], days_remaining: int):
    """Send retention warning email with list of expiring sessions."""

def send_retention_deleted(email: str, sessions: list[dict]):
    """Send notification that sessions' raw data has been deleted."""
```

**D) Build frontend entitlement hook**

Create `lap-website/src/hooks/useEntitlements.ts`:

```typescript
interface Entitlements {
  planTier: 'demo' | 'racer' | 'world-class' | 'b2b';
  subscriptionStatus: 'free' | 'active' | 'past_due' | 'canceled' | 'trialing';
  reportsPerMonth: number | null;  // null = unlimited
  reportsUsed: number;
  reportsRemaining: number | null;
  apiAccess: boolean;
  comparisonEnabled: boolean;
  coachingPlansEnabled: boolean;
  visualizationEnabled: boolean;
  raceStrategyLimit: 'limited_3h' | 'full' | null;
  liveMonitoring: boolean;
  exportFormats: string[];
  telemetryRetentionDays: number;
}

export function useEntitlements(): {
  entitlements: Entitlements | null;
  isLoading: boolean;
  canUse: (feature: string) => boolean;
  remainingQuota: (key: string) => number | null;
  requiresUpgrade: (feature: string) => { required: boolean; tier: string; url: string } | null;
}
```

This hook should:
1. Fetch from `/api/v1/me` (which now includes entitlements from PROMPT 1B)
2. Cache in Zustand store (not just React Query — needs to be available outside React tree)
3. Provide `canUse()` helper for conditional rendering
4. Provide `requiresUpgrade()` for upgrade CTA context

**E) Build UpgradeBanner component**

Create `lap-website/src/components/billing/UpgradeBanner.tsx`:

```tsx
interface UpgradeBannerProps {
  feature: string;        // "comparison", "api_access", etc.
  context?: string;       // "You've used 10/10 reports this month"
  variant?: 'inline' | 'modal' | 'toast';
}
```

Shows contextual upgrade prompts:
- Inline: subtle banner above gated content
- Modal: triggered when user clicks a gated action
- Toast: triggered when API returns `PLAN_REQUIRED` or `QUOTA_EXCEEDED`

Design must match the existing Tailwind dark theme (check `lap-website/tailwind.config.ts` and existing component styles).

**F) Gate frontend features**

Apply the `useEntitlements()` hook across the app:

| Page/Component | Feature key | Gated behavior |
|---------------|-------------|----------------|
| Compare page (`app/compare/`) | `comparison` | Show UpgradeBanner (inline), disable compare button |
| Visualization (`app/visualize/`) | `visualization` | Show UpgradeBanner (inline) |
| API docs page | `api_access` | Show "Available on World-Class" badge |
| Export PDF button | `export_pdf` | Disable button, show tooltip |
| Upload button | quota `reports` | Show "X/10 reports remaining" counter |
| Race Strategy | `race_strategy` | Allow but limit to 3h for demo |

**Tests required**:
- Rate limits scale correctly per plan tier
- Retention task deletes raw data at correct thresholds per plan
- Retention task skips B2B (NULL retention) and override users
- Retention emails sent 7 days before and on deletion day
- `useEntitlements()` hook returns correct data for each tier
- Gated components render UpgradeBanner when feature is locked
- UpgradeBanner links to correct billing page with plan pre-selected

**Acceptance criteria**:
- DEMO users get base rate limits, WORLD-CLASS get 5× higher limits
- Raw telemetry auto-deleted after plan retention window (with 7-day warning email)
- Every gated feature in the UI shows a contextual upgrade prompt (never a dead end)
- Frontend `canUse()` matches backend `authorize_feature()` — no desync

---

## SECTION 2 — ACCOUNT SECTION

### PROMPT 2A — Profile, Preferences & Security Backend

**Team**: Staff Backend Engineer (endpoints), Security Engineer (2FA, sessions), QA Lead (auth edge cases)

**Context — What exists today**:
- Profile update: `PATCH /api/v1/account/profile` in `telemetry_tool/web/routes/api_v1_account.py` — updates `display_name` and `email` (email change resets `email_verified`)
- Auth service in `telemetry_tool/auth/service.py`: `hash_password()` (Argon2id), `verify_password()`, `create_access_token()`, `create_refresh_token()`, `register_user()`, `login_user()`
- Refresh token rotation: single-use tokens stored as SHA-256 hash in `refresh_tokens` table, rotated on each refresh
- OAuth: Google OIDC + GitHub in `telemetry_tool/auth/oauth.py`, stores connections in `oauth_connections` table
- Email: Resend integration in `telemetry_tool/auth/email.py` with `send_verification_email()` and `send_welcome_email()`
- No password reset flow, no 2FA, no session management, no login history, no preference storage
- Users table has: `id`, `email`, `password_hash`, `display_name`, `created_at`, `deleted_at`, `email_verified`, `stripe_customer_id`, `stripe_subscription_id`, `plan_tier`, `subscription_status`, `default_workspace_id`

**What you must deliver**:

**A) Password reset flow**

Add to `telemetry_tool/auth/service.py`:
```python
def create_password_reset_token(conn, email: str) -> str | None:
    """Generate a time-limited reset token (1 hour expiry).
    Returns token if user exists, None otherwise (don't leak user existence).
    Store SHA-256 hash of token in new password_reset_tokens table.
    """

def reset_password(conn, token: str, new_password: str) -> bool:
    """Verify token, update password_hash, revoke all refresh tokens.
    Single-use: delete token after use.
    """
```

Add to `telemetry_tool/auth/email.py`:
```python
def send_password_reset_email(email: str, token: str):
    """Send reset link: {FRONTEND_URL}/reset-password?token={token}"""
```

Add routes to `telemetry_tool/web/routes/auth.py`:
- `POST /auth/forgot-password` — accepts `{email}`, always returns 200 (timing-safe)
- `POST /auth/reset-password` — accepts `{token, new_password}`, returns 200 or 400

Migration 020: `CREATE TABLE password_reset_tokens (id SERIAL, user_id INT REFERENCES users, token_hash VARCHAR(64), expires_at TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT now())` + index on `token_hash`.

**B) Password change (authenticated)**

Add route to `telemetry_tool/web/routes/api_v1_account.py`:
- `POST /api/v1/account/change-password` — accepts `{current_password, new_password}`
- Verify current password first (timing-safe)
- Update `password_hash`
- Revoke all refresh tokens EXCEPT the current one
- Record in `audit_log`: `password_changed`

**C) Session management**

Add to `telemetry_tool/web/routes/api_v1_account.py`:
- `GET /api/v1/account/sessions` — list active sessions (from `refresh_tokens` table, with user_agent and created_at)
- `DELETE /api/v1/account/sessions/:token_id` — revoke a specific session
- `POST /api/v1/account/sessions/revoke-all` — revoke all sessions except current (logout everywhere)

To support this, update `refresh_tokens` table (migration 020 or 021):
- Add `user_agent VARCHAR(500)`
- Add `ip_address INET`
- Add `last_used_at TIMESTAMPTZ`

Capture these fields in the login and refresh endpoints.

**D) Two-factor authentication (TOTP)**

Migration: Add `totp_secret VARCHAR(100)`, `totp_enabled BOOLEAN DEFAULT FALSE`, `totp_backup_codes JSONB` to `users` table.

Create `telemetry_tool/auth/totp.py`:
```python
def generate_totp_secret() -> str:
    """Generate a TOTP secret (base32 encoded)."""

def generate_totp_uri(secret: str, email: str) -> str:
    """Generate otpauth:// URI for QR code generation."""

def verify_totp(secret: str, code: str) -> bool:
    """Verify a TOTP code (allow ±1 time step for clock skew)."""

def generate_backup_codes() -> list[str]:
    """Generate 10 single-use backup codes (8-char hex each)."""
```

Add routes:
- `POST /api/v1/account/2fa/setup` — generate secret + QR URI, return to user (don't enable yet)
- `POST /api/v1/account/2fa/confirm` — verify a TOTP code to activate 2FA, return backup codes
- `POST /api/v1/account/2fa/disable` — requires current password + TOTP code
- `POST /api/v1/account/2fa/backup-codes` — regenerate backup codes (requires TOTP)

Update login flow in `telemetry_tool/auth/service.py`:
- If `totp_enabled`, login returns `{"requires_2fa": true, "temp_token": "..."}` instead of access+refresh tokens
- New endpoint: `POST /auth/2fa/verify` — accepts `{temp_token, totp_code}`, returns full auth tokens
- Backup codes accepted in place of TOTP code (single-use, consume on use)

**E) User preferences storage**

Migration: Add `preferences JSONB DEFAULT '{}'` to `users` table.

Add route:
- `PATCH /api/v1/account/preferences` — accepts partial JSON merge into `preferences`
- `GET /api/v1/account/preferences` — return current preferences

Preference keys (initially):
```json
{
    "units": "metric",           // "metric" | "imperial"
    "speed_unit": "kmh",         // "kmh" | "mph" | "ms"
    "timezone": "Europe/Paris",
    "language": "en",            // "en" | "fr" | "de" | "es" | "it" | "pt" | "zh"
    "notifications": {
        "report_ready": true,
        "weekly_summary": true,
        "billing_events": true,
        "retention_warnings": true
    }
}
```

**F) OAuth account linking/unlinking**

Add routes:
- `GET /api/v1/account/connections` — list OAuth connections (provider, provider_email, connected_at)
- `DELETE /api/v1/account/connections/:provider` — unlink OAuth provider (must have password set OR another provider linked)
- Use existing `oauth_connections` table

**G) Login activity log**

Record every login (password, OAuth, refresh) in `audit_log`:
- action: `login_password`, `login_oauth_google`, `login_oauth_github`, `token_refresh`
- details: `{ip, user_agent, country}` (IP geolocation via header or simple lookup)

Add route:
- `GET /api/v1/account/activity` — paginated list of recent login activity (from `audit_log`)

**Tests required**:
- Password reset: token generation, email sending, token consumption, expiry
- Password change: current password verification, token revocation
- Session listing: shows correct user_agent/IP, revocation works
- 2FA setup: secret generation, QR URI format, code verification with clock skew
- 2FA login flow: requires TOTP after password, backup codes work (single-use)
- Preferences: partial merge, validation of known keys
- OAuth unlinking: prevents orphaned accounts (no password + no OAuth = blocked)
- Audit log: all auth events logged with correct metadata

**Acceptance criteria**:
- Users can reset forgotten passwords via email link
- Users can change password (with current password verification)
- Users can see and revoke active sessions
- Users can enable/disable 2FA with backup codes
- Users can set preferences (units, timezone, language, notifications)
- Users can link/unlink OAuth providers (with safety check)
- All auth events are logged in audit_log

---

### PROMPT 2B — Plan, Billing & Usage Dashboard (Backend + Frontend)

**Team**: Billing Engineer (Stripe integration), Staff Frontend Engineer (UI), UX Designer (dashboard)

**Context — What exists today**:
- Stripe checkout flow: `lap-website/src/app/api/billing/checkout/route.ts` creates Stripe checkout sessions
- Stripe portal: `lap-website/src/app/api/billing/portal/route.ts` creates Stripe Customer Portal links
- Stripe webhook: `telemetry_tool/web/routes/billing.py` handles 4 event types
- Pricing page at `lap-website/src/app/(marketing)/pricing/` with `pricing.ts` data
- Entitlements on `/api/v1/me` from PROMPT 1B (plan_tier, quotas, remaining)
- Usage tables from PROMPT 1A: `usage_events`, `usage_monthly`
- Billing columns on users: `stripe_customer_id`, `stripe_subscription_id`, `plan_tier`, `subscription_status`
- No invoicing page, no usage visualization, no plan comparison from within the app

**What you must deliver**:

**A) Backend: billing info endpoint**

Create `telemetry_tool/web/routes/api_v1_billing.py`:

- `GET /api/v1/billing/subscription` — returns current subscription details:
```json
{
    "plan_tier": "racer",
    "subscription_status": "active",
    "current_period_end": "2026-03-15T00:00:00Z",
    "cancel_at_period_end": false,
    "payment_method": { "brand": "visa", "last4": "4242" },
    "next_invoice_amount": 899,
    "next_invoice_currency": "eur"
}
```
Fetch from Stripe API using `stripe_subscription_id` (cached 5min in Redis).

- `GET /api/v1/billing/invoices` — paginated list of past invoices from Stripe:
```json
{
    "invoices": [
        { "id": "in_xxx", "date": "2026-02-01", "amount": 899, "currency": "eur", "status": "paid", "pdf_url": "https://..." }
    ]
}
```

- `GET /api/v1/billing/usage` — current month usage summary:
```json
{
    "period": "2026-02",
    "reports": { "used": 3, "limit": 10, "remaining": 7 },
    "uploads": { "used": 5, "limit": null, "remaining": null },
    "api_calls": { "used": 0, "limit": 0, "remaining": 0 },
    "storage_mb": { "used": 245, "limit": 5000, "remaining": 4755 }
}
```

- `POST /api/v1/billing/portal` — generate Stripe Customer Portal URL (move from Next.js API route to Flask for single source of truth)

**B) Frontend: Account billing page**

Create `lap-website/src/app/app/account/billing/page.tsx`:

Layout sections:
1. **Current Plan** — tier badge, status indicator, renewal date, price
2. **Usage This Month** — progress bars for each quota (reports, storage, API calls)
3. **Quick Actions** — "Change Plan", "Update Payment Method", "Cancel Subscription" (all link to Stripe Portal)
4. **Invoice History** — table with date, amount, status, PDF download link

Use TanStack React Query to fetch from the new billing endpoints. Style with existing Tailwind dark theme.

**C) Frontend: Usage visualization component**

Create `lap-website/src/components/billing/UsageDashboard.tsx`:

- Circular progress indicators for each quota (like a fitness app)
- Color coding: green (<50%), yellow (50-80%), red (>80%), gray (unlimited)
- "Resets in X days" countdown
- Click to expand: usage history chart (last 6 months, bar chart using existing Chart.js CDN)

**D) Plan comparison & upgrade flow**

Create `lap-website/src/app/app/account/billing/upgrade/page.tsx`:

- Show all plans side-by-side (reuse data from `pricing.ts`)
- Highlight current plan
- "Upgrade" buttons link to Stripe Checkout with pre-selected plan
- "Downgrade" buttons show warning about feature loss + retention reduction
- For downgrades: show what the user will lose (specific features, retention change)

**E) Webhook enhancements**

Update `telemetry_tool/web/routes/billing.py` to handle additional events:
- `customer.subscription.trial_will_end` — send email "Your trial ends in 3 days"
- `invoice.paid` — update `subscription_status` to "active" (handles past_due → active recovery)
- `customer.subscription.paused` — set `subscription_status` to "paused"

Add email notifications (via Resend):
- Trial ending (3 days before)
- Payment failed (with retry info)
- Subscription canceled (with what they'll lose)
- Payment recovered (past_due → active)

**F) Handle subscription state transitions correctly**

The entitlement system must react to subscription states:

| State | Feature access | Quota enforcement | Raw data |
|-------|---------------|-------------------|----------|
| `active` | Full per plan | Enforced | Retained per plan |
| `trialing` | Full per plan | Enforced (generous) | Retained per plan |
| `past_due` | Full per plan (grace) | Enforced | Retained per plan |
| `canceled` | Downgrade to demo after period ends | Demo limits | Demo retention (1 month countdown starts) |
| `paused` | Read-only (no new uploads/analyses) | Blocked | Frozen (no deletion) |

Implement this logic in `telemetry_tool/auth/entitlements.py` → `get_user_entitlements()`.

**Tests required**:
- Billing endpoint returns correct Stripe data (mock Stripe API)
- Usage endpoint aggregates correctly from `usage_monthly`
- Invoices endpoint returns paginated results
- Portal URL generation works
- Subscription state transitions update entitlements correctly
- Frontend renders usage bars with correct colors
- Upgrade/downgrade flow links to correct Stripe checkout
- Email notifications sent for trial ending, payment failed, canceled

**Acceptance criteria**:
- Users can view their current plan, usage, and invoices from within the app
- Usage visualization shows real-time quota consumption with clear limits
- Plan comparison page shows what changes on upgrade/downgrade
- All subscription state transitions handled correctly (no feature access when it shouldn't be)
- Stripe is the single source of truth for billing state

---

### PROMPT 2C — Data & Privacy Controls + Support Section (Backend + Frontend)

**Team**: Backend Engineer (GDPR endpoints), Frontend Engineer (UI), Legal/Compliance Advisor (policy display)

**Context — What exists today**:
- GDPR export: `POST /api/v1/account/export`, `GET /status`, `GET /download` in `telemetry_tool/web/routes/api_v1_account.py`
- GDPR export Celery task in `telemetry_tool/tasks/gdpr_tasks.py`: exports user data as ZIP with GPS precision reduction
- Account deletion: `DELETE /api/v1/account/` (soft delete, 30-day grace) + `cancel-deletion` endpoint
- Daily purge task: `purge_deleted_accounts()` hard-deletes after 30 days
- Retention enforcement task from PROMPT 1C: auto-deletes raw telemetry per plan
- Data lifecycle defined in `lap-website/src/data/pricing.ts` (retention per tier)
- No frontend UI for any of these features
- No cookie consent, no privacy policy display, no terms acceptance tracking

**What you must deliver**:

**A) Backend: data management endpoints**

Add to `telemetry_tool/web/routes/api_v1_account.py`:

- `GET /api/v1/account/data-summary` — overview of user's stored data:
```json
{
    "sessions_count": 47,
    "total_storage_mb": 1250,
    "oldest_session": "2025-09-15",
    "retention_policy": {
        "plan_tier": "racer",
        "raw_retention_days": 90,
        "sessions_expiring_soon": [
            { "id": 123, "name": "Session 2025-12-01", "expires_at": "2026-03-01", "days_remaining": 2 }
        ]
    },
    "exports": [
        { "id": "exp_1", "status": "completed", "created_at": "2026-02-20", "expires_at": "2026-02-27" }
    ]
}
```

- `POST /api/v1/account/data/delete-sessions` — batch-delete specific sessions (with confirmation token pattern):
  1. First call: returns `{confirmation_token, sessions_to_delete: [...]}` (valid 5 minutes)
  2. Second call with `confirmation_token`: actually deletes

- `GET /api/v1/account/data/retention-schedule` — full schedule of upcoming deletions:
```json
{
    "retention_days": 90,
    "deletions": [
        { "date": "2026-03-15", "sessions": [{"id": 45, "name": "..."}] },
        { "date": "2026-04-01", "sessions": [{"id": 52, "name": "..."}] }
    ],
    "export_recommended": true
}
```

**B) Frontend: Data & Privacy page**

Create `lap-website/src/app/app/account/data/page.tsx`:

Sections:
1. **Your Data** — storage usage, session count, data breakdown chart
2. **Retention Schedule** — timeline showing when raw data will be auto-deleted, with "Export Before Expiry" buttons
3. **Export Your Data** — trigger GDPR export, show past exports with download links
4. **Delete Sessions** — select sessions for manual deletion (with confirmation step)
5. **Delete Account** — clear warning about irreversibility, 30-day grace period explanation, "Delete My Account" button (red, requires password re-entry)

**C) Frontend: Cookie consent**

Create `lap-website/src/components/legal/CookieConsent.tsx`:
- Banner at bottom of page for first-time visitors
- Categories: Necessary (always on), Analytics (optional), Marketing (optional)
- Store consent in localStorage + send to backend
- Respect consent: only load analytics/marketing scripts after consent
- "Manage cookies" link in footer

**D) Terms acceptance tracking**

Migration: Add `terms_accepted_at TIMESTAMPTZ`, `terms_version VARCHAR(20)` to `users` table.

Update registration flow:
- Frontend: checkbox "I agree to Terms of Service and Privacy Policy"
- Backend: record `terms_accepted_at` and `terms_version` on register
- If terms version changes: show "Updated Terms" banner on next login, require re-acceptance

**E) Privacy information pages**

These are static but must exist and be linked from the app:

- `lap-website/src/app/(marketing)/privacy/page.tsx` — Privacy Policy
- `lap-website/src/app/(marketing)/terms/page.tsx` — Terms of Service
- Both should include: data collected, retention policy, third-party processors (Stripe, Resend, Cloudflare, Hetzner), GDPR rights, contact info

Content framework (the actual legal text should be reviewed by legal):
- **Data collected**: account info, telemetry CSVs, GPS traces, usage analytics
- **Processors**: Stripe (payments), Resend (email), Cloudflare (CDN/DNS), Hetzner (hosting)
- **Retention**: per plan (link to pricing page retention table)
- **Rights**: access, rectification, erasure, portability, restriction, objection
- **Contact**: DPO email

**F) Support section**

Create `lap-website/src/app/app/account/support/page.tsx`:

Sections:
1. **Status** — link to status page (even if simple)
2. **Contact Support** — form that sends email via Resend to support address, pre-fills user ID, plan tier, and browser info
3. **Bug Report** — form with auto-diagnostics: browser, OS, last 5 API errors from local storage, user ID, workspace ID
4. **Documentation** — link to help center / FAQ

Backend route for support:
- `POST /api/v1/support/ticket` — creates support email via Resend, stores in `support_tickets` table for tracking
- Rate limited: 5 tickets per hour

**Tests required**:
- Data summary endpoint returns correct counts and retention schedule
- Session deletion requires confirmation token (2-step pattern)
- Export endpoints work end-to-end (create → status → download)
- Cookie consent component renders on first visit, respects stored preferences
- Terms acceptance recorded on registration
- Support ticket creation sends email and stores record

**Acceptance criteria**:
- Users can see exactly what data is stored, when it expires, and export/delete it
- Cookie consent follows EU requirements (opt-in for non-essential)
- Terms of Service and Privacy Policy pages exist with correct content
- Support contact form works with pre-filled diagnostics
- Account deletion has clear warnings and requires password confirmation

---

## SECTION 3 — OTHER SAAS TOPICS

### PROMPT 3A — Auth Lifecycle + Organizations + Subscription States (Topics A-C)

**Team**: Staff Backend Engineer (auth flows), Security Engineer (abuse prevention), Billing Engineer (state machine)

**Context — What exists today**:
- Registration: `register_user()` in `telemetry_tool/auth/service.py` — creates user + personal workspace
- Login: `login_user()` — Argon2id verify, returns access+refresh tokens
- Email verification: `send_verification_email()` in `telemetry_tool/auth/email.py`
- OAuth: Google + GitHub in `telemetry_tool/auth/oauth.py`
- Workspaces: personal (auto-created) + team in `telemetry_tool/auth/workspace.py`
- Teams: CRUD in `telemetry_tool/auth/teams.py` with roles
- Stripe webhook: handles `checkout.session.completed`, `subscription.updated`, `subscription.deleted`, `invoice.payment_failed`
- **Missing**: Email verification enforcement (unverified users can use everything), invite flow for teams, account lockout, abuse detection, complete subscription state machine

**What you must deliver**:

**A) Email verification enforcement**

Currently `email_verified` column exists but is NOT enforced. Implement:

1. Add `@require_email_verified` decorator to `telemetry_tool/auth/rbac.py`:
   - Check `g.email_verified` (set from JWT payload or DB lookup)
   - If not verified: return 403 with `{"code": "EMAIL_NOT_VERIFIED", "message": "Please verify your email"}`
   - Apply to all write endpoints (upload, analyze, create, etc.)
   - Read endpoints remain accessible (user can browse but not create)

2. Resend verification email endpoint:
   - `POST /auth/resend-verification` — rate limited (3/hour), requires auth
   - Generate new token, send new email, invalidate old token

3. Frontend handling:
   - After login, if `email_verified === false`: show banner "Verify your email to unlock full access"
   - Banner has "Resend email" button
   - Check verification status on each page load (via `/api/v1/me`)

**B) Invite flow for team workspaces**

Create `telemetry_tool/auth/invites.py`:

```python
def create_invite(conn, team_id: int, inviter_id: int, email: str, role: str = "member") -> str:
    """Create a team invitation. Returns invite token.

    - Store in invitations table: team_id, email, role, token_hash, inviter_id, expires_at (7 days)
    - Send invitation email via Resend
    - If user already exists: direct add (if they accept)
    - If user doesn't exist: invite link goes to register page with pre-filled email + team context
    """

def accept_invite(conn, token: str, user_id: int) -> dict:
    """Accept an invitation. Adds user to team with specified role.

    - Verify token not expired
    - Add user to team_members
    - Add user to team's workspace
    - Delete invitation
    - Send "X joined your team" email to inviter
    """

def decline_invite(conn, token: str):
    """Decline/delete an invitation."""

def list_pending_invites(conn, team_id: int) -> list[dict]:
    """List all pending invitations for a team."""
```

Migration: `CREATE TABLE invitations (id SERIAL, team_id INT REFERENCES teams, email VARCHAR(255), role VARCHAR(20), token_hash VARCHAR(64), inviter_id INT REFERENCES users, expires_at TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT now())`

Routes:
- `POST /api/v1/teams/:id/invitations` — create invite (requires `invite_members` permission)
- `GET /api/v1/teams/:id/invitations` — list pending (requires `manage_members` permission)
- `DELETE /api/v1/teams/:id/invitations/:invite_id` — cancel invite
- `POST /api/v1/invitations/accept` — accept invite (requires auth)
- `POST /api/v1/invitations/decline` — decline invite

**C) Account lockout + abuse prevention**

Add to `telemetry_tool/auth/service.py`:

1. **Failed login tracking**: after 5 failed password attempts in 15 minutes, lock account for 30 minutes
   - Store in Redis: `login_attempts:{email}` as sorted set (like rate limiter)
   - Return 429 with `Retry-After` header
   - Don't reveal whether the account exists (same error for wrong email vs wrong password)

2. **Account suspension by admin**: add `suspended_at TIMESTAMPTZ`, `suspension_reason VARCHAR(255)` to users table
   - Suspended users get 403 on all endpoints
   - Admin can suspend/unsuspend via admin API (PROMPT 3C)

3. **Login anomaly detection** (simple):
   - Record login IP + country in `audit_log`
   - If new country detected: send "New login location" email
   - Don't block (just notify) — blocking would be too aggressive at this stage

**D) Complete subscription state machine**

Create `telemetry_tool/billing/state_machine.py`:

```python
SUBSCRIPTION_STATES = {
    "free": {"allowed_transitions": ["trialing", "active"]},
    "trialing": {"allowed_transitions": ["active", "canceled"], "grace_days": 0},
    "active": {"allowed_transitions": ["past_due", "canceled", "paused"], "grace_days": 0},
    "past_due": {"allowed_transitions": ["active", "canceled"], "grace_days": 7},
    "canceled": {"allowed_transitions": ["active"], "grace_days": 30},  # 30 days before downgrade
    "paused": {"allowed_transitions": ["active", "canceled"], "grace_days": 0},
}

def transition_subscription(conn, user_id: int, new_status: str, metadata: dict = None) -> bool:
    """Transition subscription state. Validates allowed transitions.

    Records in audit_log. Sends appropriate emails.
    Returns True if transition succeeded.
    """
```

Update the Stripe webhook handler to use this state machine instead of raw status updates:
- `checkout.session.completed` → `transition_subscription(user, "active")`
- `customer.subscription.deleted` → `transition_subscription(user, "canceled")` (NOT immediate downgrade)
- For `canceled`: start 30-day grace countdown. After period_end, actually downgrade to demo tier.

**E) Celery task: subscription grace period enforcement**

Create `telemetry_tool/tasks/billing_tasks.py`:

```python
@celery.task(queue="default")
def enforce_subscription_grace_periods():
    """Daily task: check for expired grace periods and downgrade.

    - canceled + period_end passed + 30 days → plan_tier = 'demo'
    - past_due > 7 days → send final warning email
    - past_due > 14 days → plan_tier = 'demo' (but keep data for 30 more days)
    """
```

**Tests required**:
- Email verification enforcement blocks writes for unverified users
- Invite flow: create, accept (existing user), accept (new user), decline, expire
- Account lockout after 5 failed attempts in 15 minutes
- Subscription state machine validates allowed transitions
- Grace period enforcement correctly downgrades after timeout
- Login anomaly detection sends email for new country

**Acceptance criteria**:
- Unverified users can browse but not create content
- Team invitations work for both existing and new users
- Account locked after repeated failed logins (with unlock after timeout)
- Subscription state transitions follow the defined state machine
- Grace periods prevent immediate feature loss on cancellation/payment failure

---

### PROMPT 3B — Payments Correctness + Metering + Jobs + Observability (Topics D-G)

**Team**: Billing Engineer (Stripe hardening), SRE (observability), Backend Engineer (jobs UX)

**Context — What exists today**:
- Stripe webhook in `telemetry_tool/web/routes/billing.py`: verifies signature, handles 4 events, returns 200 even on error (prevents Stripe retry loops)
- Idempotency middleware in `telemetry_tool/web/idempotency.py`: Redis-backed `Idempotency-Key` header
- Rate limiter in `telemetry_tool/web/rate_limit.py`: 5 tiers, Redis sliding window
- Celery: 2 queues (`pipeline` concurrency=2, `default` concurrency=4), `task_acks_late=True` in `telemetry_tool/tasks/celery_app.py`
- Pipeline tasks in `telemetry_tool/tasks/pipeline_tasks.py` — dispatches analysis jobs
- Job tracking in `telemetry_tool/tasks/job_registry.py` — tracks Celery job status
- Ingest jobs table with `peak_rss_mb`, `throughput_mb_s` columns
- Health check at `GET /healthz` checks DB, Redis, Celery
- Logging: standard Python `logging` module, no structured format, no correlation IDs in logs
- No Stripe event replay handling, no webhook idempotency, no detailed job status page, no metrics collection

**What you must deliver**:

**A) Stripe webhook hardening**

Update `telemetry_tool/web/routes/billing.py`:

1. **Webhook idempotency**: Store processed event IDs in Redis (24hr TTL):
   ```python
   def _is_event_processed(event_id: str) -> bool:
       r = get_redis()
       return r.set(f"stripe_event:{event_id}", "1", nx=True, ex=86400) is None
   ```
   Skip already-processed events (return 200 immediately).

2. **Event replay safety**: Handle out-of-order events by checking timestamps:
   - Store `last_event_timestamp` per customer in Redis
   - If incoming event is older than last processed: log warning, skip

3. **Reconciliation task**: Daily Celery task that syncs Stripe → DB:
   ```python
   @celery.task(queue="default")
   def reconcile_stripe_subscriptions():
       """Fetch all active subscriptions from Stripe, compare with DB.
       Log and fix any discrepancies. Stripe is always authoritative."""
   ```

4. **Handle additional Stripe events**:
   - `customer.subscription.trial_will_end` → email notification
   - `invoice.paid` → clear past_due status
   - `charge.refunded` → log to audit_log
   - `customer.subscription.paused` / `resumed` → update status

**B) Per-plan metering and compute caps**

Extend the rate limiter to be plan-aware (from PROMPT 1C), plus add compute-specific caps:

Create `telemetry_tool/web/compute_budget.py`:
```python
COMPUTE_BUDGETS = {
    "demo": {"max_concurrent_jobs": 1, "max_job_duration_minutes": 10},
    "racer": {"max_concurrent_jobs": 2, "max_job_duration_minutes": 30},
    "world-class": {"max_concurrent_jobs": 5, "max_job_duration_minutes": 60},
    "b2b": {"max_concurrent_jobs": 10, "max_job_duration_minutes": 120},
}

def check_compute_budget(conn, user_id: int, workspace_id: int) -> tuple[bool, dict]:
    """Check if user can launch another job.
    Returns (allowed, {running_jobs, max_jobs, oldest_job_started}).
    """
```

Wire into job submission endpoints:
- `telemetry_tool/web/routes/ingest.py` (upload + process)
- `telemetry_tool/web/routes/analysis.py` (re-analyze)
- `telemetry_tool/web/routes/batch.py` (batch analysis)

**C) Job status page (backend + frontend)**

Backend — update `telemetry_tool/web/routes/jobs.py`:

- `GET /api/v1/jobs` — list user's jobs with pagination:
  ```json
  {
      "jobs": [
          {
              "id": "job_123",
              "type": "analysis",
              "status": "running",
              "progress": 65,
              "session_name": "Spa 2026-02-15",
              "created_at": "2026-02-27T10:00:00Z",
              "started_at": "2026-02-27T10:00:05Z",
              "estimated_completion": "2026-02-27T10:02:00Z",
              "error_message": null
          }
      ]
  }
  ```

- `POST /api/v1/jobs/:id/cancel` — cancel a running job (set Celery `revoke` with `terminate=True`)
- `POST /api/v1/jobs/:id/retry` — retry a failed job (create new Celery task)

Frontend — create `lap-website/src/app/app/jobs/page.tsx`:
- Table with status badges (queued=gray, running=blue+spinner, done=green, failed=red)
- Progress bars for running jobs
- Cancel/Retry buttons
- Auto-refresh every 5 seconds (React Query `refetchInterval`)
- User-friendly error messages (map internal errors to readable text)

**D) Structured logging with correlation IDs**

Update logging across the backend:

1. Create `telemetry_tool/web/logging_config.py`:
   ```python
   def setup_structured_logging():
       """Configure JSON-structured logging with correlation IDs."""
       # Format: {"timestamp", "level", "message", "request_id", "user_id", "workspace_id", "module"}
   ```

2. Add `X-Request-Id` header support:
   - Generate UUID in request middleware if not present
   - Set `g.request_id`
   - Include in all log entries
   - Return in response headers

3. Add to `telemetry_tool/web/app.py` `create_app()`:
   ```python
   @app.before_request
   def inject_request_id():
       g.request_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))

   @app.after_request
   def add_request_id_header(response):
       response.headers["X-Request-Id"] = g.request_id
       return response
   ```

4. Update all existing `logger.info/warning/error` calls to include context:
   ```python
   logger.info("Analysis completed", extra={"request_id": g.request_id, "session_id": sid, "duration_ms": elapsed})
   ```

**E) Metrics collection**

Create `telemetry_tool/web/metrics.py`:

Collect key metrics (store in Redis, expose via `/api/v1/admin/metrics`):
- `api_requests_total` (by route, status code)
- `api_request_duration_seconds` (histogram by route)
- `active_jobs` (gauge by type)
- `job_duration_seconds` (histogram by type)
- `upload_size_bytes` (histogram)
- `stripe_webhook_events_total` (by event type)
- `rate_limit_hits_total` (by tier)

Add `@app.after_request` hook to record request metrics automatically.

Expose via:
- `GET /api/v1/admin/metrics` — JSON format (admin-only, for dashboard consumption)
- Future: Prometheus `/metrics` endpoint (not required now, but design for it)

**F) Alerting (email-based)**

Create `telemetry_tool/tasks/alert_tasks.py`:

Celery Beat tasks:
- Every 5 minutes: check for elevated error rates (>5% 5xx in last 5 min) → email alert
- Every 15 minutes: check job queue depth (>50 pending) → email alert
- Every hour: check Stripe webhook failures (>3 failures in last hour) → email alert

Send via Resend to configurable `ALERT_EMAIL` env var.

**Tests required**:
- Webhook idempotency: same event ID processed only once
- Event replay: out-of-order events handled correctly
- Reconciliation task detects and fixes Stripe/DB discrepancies
- Compute budget enforcement: concurrent job limits respected
- Job cancel/retry works correctly
- Structured logging outputs valid JSON with correlation IDs
- Metrics collected and exposed correctly
- Alert tasks fire on correct thresholds

**Acceptance criteria**:
- Stripe webhooks are idempotent and replay-safe
- Daily reconciliation ensures Stripe/DB consistency
- Users see job status with progress, cancel, and retry
- All API requests have correlation IDs in logs and response headers
- Operational metrics are collected and accessible
- Alerts fire on elevated errors / queue depth

---

### PROMPT 3C — Email System + Compliance + Security + Admin Backoffice (Topics H-K)

**Team**: Backend Engineer (email + admin), Security Engineer (hardening), Compliance Advisor (GDPR), Frontend Engineer (admin UI)

**Context — What exists today**:
- Email: Resend integration in `telemetry_tool/auth/email.py` — 2 email types (verification, welcome), HTML templates with LAP green (#B6FF2E)
- i18n: 7 language files in `telemetry_tool/web/i18n/` (de, en, es, fr, it, pt, zh)
- Security: JWT HS256, Argon2id passwords, CORS, Stripe webhook signature verification
- Security headers: configured in Caddy (HSTS, X-Frame-Options, etc.) + Next.js middleware
- File upload validation: content-type checking in ingest routes
- No email templates for billing events, no complete email system
- No admin backoffice, no impersonation, no platform-level admin role
- No formal audit log UI, no subprocessor list page

**What you must deliver**:

**A) Complete email template system**

Create `telemetry_tool/auth/email_templates.py`:

Define all transactional email templates (reuse existing HTML style from `email.py`):

| Template | Trigger | Variables |
|----------|---------|-----------|
| `verification` | Registration | verify_url |
| `welcome` | Email verified | dashboard_url |
| `password_reset` | Forgot password | reset_url, expires_in |
| `password_changed` | Password changed | datetime, support_url |
| `team_invitation` | Team invite | inviter_name, team_name, accept_url |
| `team_joined` | Invite accepted | member_name, team_name |
| `report_ready` | Analysis complete | session_name, report_url |
| `retention_warning` | 7 days before deletion | sessions[], export_url, days_remaining |
| `retention_deleted` | Data deleted | sessions[], upgrade_url |
| `trial_ending` | 3 days before trial end | plan_name, upgrade_url, days_remaining |
| `payment_failed` | Invoice payment failed | amount, retry_date, update_payment_url |
| `subscription_canceled` | User cancels | plan_name, features_losing, reactivate_url |
| `payment_recovered` | Past due → active | plan_name, dashboard_url |
| `new_login_location` | Login from new country | country, ip, datetime, revoke_url |
| `weekly_summary` | Weekly Celery Beat | sessions_count, best_score, improvement |
| `quota_warning` | 80% of monthly quota | feature, used, limit, upgrade_url |

All templates must:
- Use responsive HTML (single column, 600px max width)
- Include unsubscribe link (per email type, linked to preferences)
- Include Lap Coach logo + footer
- Support i18n (use user's language preference)

Create `telemetry_tool/tasks/email_tasks.py`:
```python
@celery.task(queue="default")
def send_email_async(template: str, to: str, variables: dict, language: str = "en"):
    """Render template and send via Resend. Logs to email_log table."""
```

Migration: `CREATE TABLE email_log (id SERIAL, user_id INT, template VARCHAR(50), to_email VARCHAR(255), status VARCHAR(20), sent_at TIMESTAMPTZ DEFAULT now(), error TEXT)`

**B) SPF/DKIM/DMARC setup instructions**

Document (not code) the DNS records needed for Resend deliverability:
- SPF record for sending domain
- DKIM via Resend dashboard
- DMARC policy (start with `p=none` for monitoring)

Add as comment block in `telemetry_tool/auth/email.py` or as `docs/email-deliverability.md`.

**C) Security hardening**

1. **Signed download URLs**: Create `telemetry_tool/web/signed_urls.py`:
   ```python
   def create_signed_url(path: str, expires_in: int = 3600) -> str:
       """Generate HMAC-signed URL for file downloads (exports, reports)."""

   def verify_signed_url(url: str) -> tuple[bool, str]:
       """Verify HMAC signature and expiry. Returns (valid, path)."""
   ```
   Apply to: GDPR export download, report PDF download, any file serve endpoint.

2. **IDOR prevention audit**: Review all endpoints that take resource IDs in URL params. Ensure every one checks `workspace_id` ownership:
   ```python
   # BAD: SELECT * FROM sessions WHERE id = :session_id
   # GOOD: SELECT * FROM sessions WHERE id = :session_id AND workspace_id = current_setting('app.current_workspace_id')::int
   ```
   The RLS policies should handle this, but verify they're active on ALL queries.

3. **Input sanitization**: Add to `telemetry_tool/web/validation.py`:
   - `sanitize_filename(name)` — strip path traversal, limit length
   - `sanitize_html(text)` — strip HTML tags from user-provided text (display_name, team_name, etc.)
   - Apply to all user-input string fields

4. **Rate limit on auth endpoints**: Ensure all auth endpoints have aggressive rate limits:
   - `/auth/login`: 20/minute per IP
   - `/auth/register`: 5/minute per IP
   - `/auth/forgot-password`: 3/minute per IP
   - `/auth/2fa/verify`: 5/minute per IP

**D) Platform admin role + backoffice API**

Migration: Add `is_platform_admin BOOLEAN DEFAULT FALSE` to `users` table.

Create `telemetry_tool/web/routes/admin.py`:

```python
bp = Blueprint("admin", __name__, url_prefix="/api/v1/admin")

@bp.before_request
def require_platform_admin():
    """Block all non-admin requests."""
    if not getattr(g, "is_platform_admin", False):
        return api_error(ErrorCode.FORBIDDEN, "Platform admin required", status=403)
```

Admin endpoints:

- `GET /api/v1/admin/users` — paginated user list with search (email, name), filters (plan_tier, subscription_status, created date range)
- `GET /api/v1/admin/users/:id` — full user detail (profile, plan, usage, sessions, audit log)
- `POST /api/v1/admin/users/:id/suspend` — suspend account (requires reason)
- `POST /api/v1/admin/users/:id/unsuspend` — unsuspend account
- `POST /api/v1/admin/users/:id/override` — create entitlement override (for support credits, grandfathering)
- `POST /api/v1/admin/users/:id/impersonate` — generate short-lived (15min) access token for the target user, logged in audit_log with admin's ID
- `GET /api/v1/admin/workspaces` — list all workspaces
- `GET /api/v1/admin/metrics` — system metrics (from PROMPT 3B)
- `GET /api/v1/admin/audit-log` — paginated audit log with filters
- `GET /api/v1/admin/billing/overview` — MRR, churn, plan distribution (aggregate from Stripe)

**E) Admin frontend (minimal)**

Create `lap-website/src/app/admin/` (separate route group, protected by `is_platform_admin` check):

Pages:
1. **Dashboard** — key metrics: total users, MRR, active subscriptions, jobs running, error rate
2. **Users** — searchable table, click to view detail, suspend/unsuspend buttons
3. **Audit Log** — filterable log viewer (action type, user, date range)

Keep it functional, not fancy. Use existing Tailwind dark theme. Table components can be basic `<table>` with pagination.

**F) Compliance pages**

Create/update:
- `lap-website/src/app/(marketing)/privacy/page.tsx` — Privacy Policy (from PROMPT 2C)
- `lap-website/src/app/(marketing)/terms/page.tsx` — Terms of Service
- `lap-website/src/app/(marketing)/subprocessors/page.tsx` — List of subprocessors:
  - Stripe (payments, Ireland)
  - Resend (email, US)
  - Cloudflare (CDN/DNS, global)
  - Hetzner (hosting, Germany)
- `lap-website/src/app/(marketing)/dpa/page.tsx` — Data Processing Agreement (for B2B)

All linked from footer.

**Tests required**:
- All 16 email templates render correctly with variables
- Email sends are logged in `email_log` table
- Signed URLs: generation, verification, expiry
- IDOR: test accessing another user's session returns 403/empty (RLS)
- Admin endpoints require `is_platform_admin`
- Impersonation generates valid short-lived token + audit log entry
- User suspension blocks all API access

**Acceptance criteria**:
- Complete email system with 16 templates, async sending, logging
- File downloads use signed URLs (not guessable paths)
- No IDOR vulnerabilities (RLS + explicit workspace checks)
- Platform admin can manage users, view audit log, grant overrides
- Admin impersonation is time-limited and fully audited
- Compliance pages exist and are linked from footer

---

## SECTION 4 — DATA MODEL

### PROMPT 4A — Core Entity Design + Migration Strategy

**Team**: DBA (schema design), Staff Backend Engineer (migration implementation), Billing Engineer (Stripe entity mapping)

**Context — What exists today**:
- 18 Alembic migrations (001–018) in `telemetry_tool/alembic/versions/`
- 44 workspace-scoped tables with RLS policies (migrations 004-008)
- Users table: `id`, `email`, `password_hash`, `display_name`, `created_at`, `deleted_at`, `email_verified`, `default_workspace_id`, `stripe_customer_id`, `stripe_subscription_id`, `billing_plan`
- Workspaces: `id`, `name`, `slug`, `type` (personal/team), `owner_user_id`, `owner_team_id`
- Teams: `id`, `name`, `slug`, `created_at` + `team_members` junction table
- RLS enforced via `SET LOCAL app.current_workspace_id` per-request
- SQL compat layer in `telemetry_tool/db/sql_compat.py` translates SQLite→PG syntax
- No entitlement/usage/audit tables yet (introduced in PROMPT 1A migration 019)

**What you must deliver**:

**A) Complete entity-relationship design**

Create the FULL data model document showing all entities and relationships. This is the authoritative reference for all other prompts.

```
users
├── stripe_customer_id → Stripe Customer
├── plan_tier → plan_definitions.tier
├── subscription_status (free/trialing/active/past_due/canceled/paused)
├── is_platform_admin
├── totp_secret, totp_enabled, totp_backup_codes
├── preferences (JSONB)
├── terms_accepted_at, terms_version
├── suspended_at, suspension_reason
├── deleted_at (soft delete)
│
├─── refresh_tokens (1:N)
│    ├── token_hash, user_agent, ip_address, last_used_at
│
├─── oauth_connections (1:N)
│    ├── provider, provider_user_id, provider_email
│
├─── password_reset_tokens (1:N)
│    ├── token_hash, expires_at
│
├─── email_verify_tokens (1:N)
│    ├── token, expires_at
│
├─── data_exports (1:N)
│    ├── status, format, file_path, expires_at
│
├─── entitlement_overrides (1:N, also via workspace)
│    ├── override_key, override_value, reason, expires_at
│
└─── workspaces (via team_members or owner)
     ├── type (personal/team)
     ├── All 44 domain tables (sessions, laps, tracks, etc.)
     ├── usage_events (1:N)
     ├── usage_monthly (1:N)
     └── audit_log (1:N)

plan_definitions (global, not workspace-scoped)
├── tier (PK), display_name, reports_per_month, max_upload_size_mb
├── telemetry_retention_days, api_access, comparison_enabled, etc.

teams
├── name, slug
├── team_members (M:N with users, includes role)
├── invitations (pending invites)

support_tickets (workspace-scoped)
├── user_id, subject, body, status

email_log (global)
├── user_id, template, to_email, status, sent_at, error
```

**B) Migration consolidation strategy**

All new tables from PROMPTS 1A through 3C should be organized into a minimal number of migrations:

| Migration | Tables/Columns | Dependencies |
|-----------|---------------|-------------|
| 019 | `plan_definitions`, `usage_events`, `usage_monthly`, `entitlement_overrides`, `audit_log` + `users.plan_tier`, rename `billing_plan→subscription_status` | None |
| 020 | `password_reset_tokens`, `users.totp_*`, `users.preferences`, `users.terms_*`, `users.suspended_*`, `users.is_platform_admin` + `refresh_tokens.user_agent/ip_address/last_used_at` | 019 |
| 021 | `invitations`, `support_tickets`, `email_log` + RLS policies for all new workspace-scoped tables | 020 |

Write all three migrations with proper `upgrade()` and `downgrade()` functions.

**C) Seed data**

Create `telemetry_tool/alembic/versions/019_*.py` seed section:

```python
def upgrade():
    # ... create tables ...

    # Seed plan_definitions
    op.execute("""
        INSERT INTO plan_definitions (tier, display_name, reports_per_month, ...) VALUES
        ('demo', 'Demo', 1, ...),
        ('racer', 'Racer', 10, ...),
        ('world-class', 'World-Class', NULL, ...),
        ('b2b', 'B2B', NULL, ...);
    """)

    # Backfill existing users: set plan_tier based on current subscription
    op.execute("""
        UPDATE users SET plan_tier = CASE
            WHEN billing_plan = 'active' AND stripe_subscription_id IS NOT NULL THEN 'racer'
            WHEN billing_plan = 'free' OR billing_plan IS NULL THEN 'demo'
            ELSE 'demo'
        END;
    """)
```

**D) Index strategy**

Document and create all necessary indexes:

```sql
-- High-frequency queries
CREATE INDEX idx_users_email ON users (email);  -- already exists
CREATE INDEX idx_users_stripe ON users (stripe_customer_id) WHERE stripe_customer_id IS NOT NULL;
CREATE INDEX idx_usage_events_ws_type_created ON usage_events (workspace_id, event_type, created_at);
CREATE INDEX idx_usage_monthly_ws_period ON usage_monthly (workspace_id, period_start);
CREATE INDEX idx_audit_log_user_created ON audit_log (user_id, created_at);
CREATE INDEX idx_audit_log_ws_created ON audit_log (workspace_id, created_at);
CREATE INDEX idx_invitations_token ON invitations (token_hash);
CREATE INDEX idx_invitations_team ON invitations (team_id, expires_at);
CREATE INDEX idx_email_log_user ON email_log (user_id, sent_at);
CREATE INDEX idx_password_reset_token ON password_reset_tokens (token_hash);
```

**E) RLS policy application**

Apply RLS to all new workspace-scoped tables:

```sql
-- Pattern (repeat for each workspace-scoped table)
ALTER TABLE usage_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY usage_events_workspace ON usage_events
    USING (workspace_id = current_setting('app.current_workspace_id')::int);
```

Tables that need RLS: `usage_events`, `usage_monthly`, `entitlement_overrides` (when workspace_id is set), `audit_log`, `support_tickets`.

Tables that do NOT get RLS: `plan_definitions`, `email_log`, `password_reset_tokens`, `invitations` (cross-workspace by nature).

**Tests required**:
- All migrations run cleanly up and down (alembic upgrade/downgrade cycle)
- Seed data matches `pricing.ts` exactly
- Backfill correctly maps existing users
- RLS policies filter correctly for each new table
- Indexes exist and are used by key queries (EXPLAIN ANALYZE)

**Acceptance criteria**:
- Complete ER diagram matches all entities from all prompts
- 3 migrations (019-021) create all necessary schema
- Existing data is preserved and correctly backfilled
- RLS applied to all workspace-scoped tables
- All indexes created for query performance

---

### PROMPT 4B — Query Patterns, Connection Management & Performance

**Team**: DBA (query optimization), SRE (connection management), Backend Engineer (query implementation)

**Context — What exists today**:
- Per-request PostgreSQL connections (pool removed — exhausted under Gunicorn pre-fork): `telemetry_tool/web/db_pg.py`
- `PgConnectionWrapper` wraps psycopg2 with `.execute()` that auto-translates SQL via `sql_compat.translate_params()`
- `close_pg()` teardown always closes in `finally` block
- `SET LOCAL app.current_workspace_id` for RLS — scoped to transaction, resets on `conn.commit()`
- Keyset pagination in `telemetry_tool/web/pagination.py` (cursor-based, no OFFSET)
- Redis for rate limiting, idempotency, Celery broker
- No query monitoring, no slow query detection, no connection pooling

**What you must deliver**:

**A) Connection pooling (revisited)**

The original pool was removed because Gunicorn pre-fork exhausted it. Implement a safe pool:

Option 1 (recommended): Use PgBouncer as an external connection pooler (Docker sidecar):
- Add `pgbouncer` service to `docker-compose.prod.yml`
- Configure in transaction mode (compatible with `SET LOCAL`)
- Flask connects to PgBouncer instead of PG directly
- Pool size: 20 connections (shared across all Gunicorn workers)

Option 2 (fallback): Keep per-request connections but add monitoring:
- Log connection creation/destruction counts
- Alert if connection count exceeds threshold

Document the trade-offs and implement Option 1.

**B) Common query patterns**

Create `telemetry_tool/web/queries/` package with reusable query functions:

```python
# telemetry_tool/web/queries/entitlements.py
def get_user_plan_tier(conn, user_id: int) -> str:
    """Fast lookup, cached in g.plan_tier."""

def get_effective_entitlements(conn, user_id: int, workspace_id: int) -> dict:
    """Plan + overrides + usage = resolved entitlements. Cached per-request."""

# telemetry_tool/web/queries/usage.py
def get_monthly_usage(conn, workspace_id: int, event_type: str) -> int:
    """Current month usage for a specific event type."""

def record_usage_event(conn, user_id: int, workspace_id: int, event_type: str, cost: int = 1, metadata: dict = None):
    """Insert usage_event + upsert usage_monthly."""

# telemetry_tool/web/queries/audit.py
def log_audit_event(conn, action: str, details: dict = None):
    """Record audit event using g.user_id, g.workspace_id, request.remote_addr."""
```

**C) Per-request caching**

Implement request-scoped caching to avoid repeated DB lookups:

```python
# In middleware or utility
def get_cached(key: str, loader: callable):
    """Cache a value on Flask g for the duration of the request."""
    cached = getattr(g, f"_cache_{key}", None)
    if cached is not None:
        return cached
    value = loader()
    setattr(g, f"_cache_{key}", value)
    return value
```

Apply to:
- `g.plan_tier` — loaded once per request
- `g.entitlements` — loaded once per request
- `g.workspace_role` — already loaded by tenant middleware

**D) Slow query detection**

Add to `telemetry_tool/web/db_pg.py`:

```python
class PgConnectionWrapper:
    def execute(self, query, params=None):
        start = time.monotonic()
        result = self._conn.execute(translated_query, translated_params)
        elapsed_ms = (time.monotonic() - start) * 1000
        if elapsed_ms > 500:  # 500ms threshold
            logger.warning("Slow query (%dms): %s", elapsed_ms, query[:200],
                          extra={"duration_ms": elapsed_ms, "request_id": getattr(g, "request_id", None)})
        return result
```

**E) Pagination for new endpoints**

Apply keyset pagination (from `telemetry_tool/web/pagination.py`) to all list endpoints:
- `GET /api/v1/admin/users` — cursor on `users.id`
- `GET /api/v1/admin/audit-log` — cursor on `audit_log.id`
- `GET /api/v1/account/activity` — cursor on `audit_log.id`
- `GET /api/v1/billing/invoices` — cursor on Stripe invoice date
- `GET /api/v1/jobs` — cursor on `celery_jobs.id`

**F) Database health monitoring**

Extend `GET /healthz` to include:
- Connection count (from pg_stat_activity)
- Slow query count in last 5 minutes (from our logging)
- Table bloat estimate for high-write tables (usage_events)
- Replication lag (if replica exists)

**Tests required**:
- PgBouncer configuration works in Docker Compose
- Query functions return correct results
- Per-request cache prevents duplicate DB lookups (mock and verify call count)
- Slow query detection logs correctly (threshold test)
- Pagination returns correct pages with cursor tokens
- Health check reports accurate connection stats

**Acceptance criteria**:
- Connection pooling via PgBouncer (or documented alternative)
- Common queries extracted into reusable functions
- Per-request caching eliminates redundant lookups
- Slow queries (>500ms) are logged with context
- All list endpoints use keyset pagination
- Health check includes database performance indicators

---

### PROMPT 4C — Data Lifecycle, Archival & Backup Strategy

**Team**: DBA (archival), SRE (backup/restore), Backend Engineer (retention implementation)

**Context — What exists today**:
- Daily `pg_dump` at 3 AM UTC, 7-day retention, stored at `/opt/lap-api/backups/`
- Retention enforcement task from PROMPT 1C: deletes raw telemetry per plan
- GDPR purge task: hard-deletes accounts after 30-day grace period
- `usage_events` table will be high-write (every billable action creates a row)
- `audit_log` table will grow indefinitely
- No archival strategy, no table partitioning, no backup verification

**What you must deliver**:

**A) Table partitioning for high-write tables**

Partition `usage_events` by month:
```sql
-- In migration 019 (or modify the CREATE TABLE)
CREATE TABLE usage_events (
    id BIGSERIAL,
    user_id INT NOT NULL,
    workspace_id INT NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    cost INT DEFAULT 1,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
) PARTITION BY RANGE (created_at);

-- Create partitions for current + next 3 months
CREATE TABLE usage_events_2026_02 PARTITION OF usage_events
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
-- ... etc
```

Create Celery task to auto-create partitions 3 months ahead:
```python
@celery.task(queue="default")
def create_future_partitions():
    """Monthly task: create usage_events partitions for next 3 months."""
```

Similarly partition `audit_log` by month.

**B) Data archival strategy**

For `usage_events` older than 12 months:
1. Export to Parquet files (using existing `parquet_manager.py` patterns)
2. Store in `/opt/lap-api/archives/usage/YYYY-MM.parquet`
3. Drop the old partition: `DROP TABLE usage_events_2025_02`
4. Keep `usage_monthly` aggregates forever (small, needed for historical reporting)

Create `telemetry_tool/tasks/archival_tasks.py`:
```python
@celery.task(queue="default")
def archive_old_usage_events():
    """Monthly task: archive usage_events older than 12 months to Parquet, drop partition."""
```

For `audit_log`: keep 24 months in PostgreSQL, archive older to Parquet.

**C) Backup hardening**

Update the backup script (`/opt/lap-api/backups/backup.sh` or Docker cron):

1. **Backup verification**: after `pg_dump`, run `pg_restore --list` on the dump to verify it's valid
2. **Backup encryption**: encrypt dumps with `gpg --symmetric` using env var `BACKUP_ENCRYPTION_KEY`
3. **Off-site copy**: upload to S3-compatible storage (Hetzner Object Storage) daily
4. **Retention tiers**:
   - Daily: keep 7 days
   - Weekly (Sunday): keep 4 weeks
   - Monthly (1st): keep 12 months
5. **Restore test**: monthly Celery task that restores the latest backup to a temp database and runs basic sanity checks

Create `scripts/backup.sh` with all of the above.

**D) Storage monitoring**

Add to health check and admin metrics:
- Total database size
- Per-table sizes (top 10)
- Partition sizes for `usage_events` and `audit_log`
- Backup size trend
- Archive storage size
- Disk space remaining on VPS

Create admin endpoint: `GET /api/v1/admin/storage` with this data.

**E) Data deletion cascade documentation**

Document the exact cascade for each deletion scenario:

1. **User account deletion** (GDPR erasure):
   ```
   users → refresh_tokens (CASCADE)
         → oauth_connections (CASCADE)
         → password_reset_tokens (CASCADE)
         → email_verify_tokens (CASCADE)
         → data_exports (CASCADE)
         → entitlement_overrides (CASCADE)
         → team_members (CASCADE) → if last member, delete team + workspace
         → workspaces (owned) → sessions → laps, gps_traces, scores, etc.
         → usage_events (anonymize, don't delete — needed for aggregate accuracy)
         → audit_log (anonymize user_id, keep action/details)
   ```

2. **Workspace deletion**:
   ```
   workspaces → all 44 domain tables (CASCADE via RLS)
              → usage_events (CASCADE)
              → usage_monthly (CASCADE)
              → audit_log (archive, don't delete)
   ```

3. **Session retention expiry**:
   ```
   sessions → gps_traces (DELETE)
            → raw_telemetry_chunks (DELETE)
            → session files on disk (DELETE)
            → KEEP: laps, scores, annotations, processed reports
            → SET sessions.retention_expired = TRUE
   ```

**Tests required**:
- Partition creation works correctly (boundaries, no gaps)
- Archive task exports to Parquet and drops partition
- Backup script produces valid, encrypted dumps
- Restore test passes on backup
- Storage metrics are accurate
- Deletion cascades work correctly for each scenario
- Usage event anonymization preserves aggregate accuracy

**Acceptance criteria**:
- `usage_events` and `audit_log` are partitioned by month
- Old partitions archived to Parquet after 12/24 months
- Backups are encrypted, verified, and copied off-site
- Storage monitoring prevents disk space surprises
- Deletion cascades are documented and tested

---

## SECTION 5 — NEXT STEPS / INTEGRATION

### PROMPT 5A — Entitlement Matrix Definition + Stripe Product Reconciliation

**Team**: Billing Engineer (Stripe setup), Product Manager (tier definitions), Backend Engineer (reconciliation)

**Context — What exists today**:
- Plan definitions seeded in `plan_definitions` table (from PROMPT 1A/4A)
- Stripe checkout creates sessions with price IDs from env vars (`STRIPE_PRICE_RACER_MONTHLY`, etc.)
- Frontend pricing defined in `lap-website/src/data/pricing.ts`
- Stripe price → tier mapping in backend (from PROMPT 1A)
- No formal entitlement matrix document, no Stripe product setup documentation

**What you must deliver**:

**A) Authoritative entitlement matrix**

Create `docs/entitlement-matrix.md` — THE single source of truth:

| Feature | Code Key | Demo | Racer | World-Class | B2B |
|---------|----------|------|-------|-------------|-----|
| Analysis Reports / month | `reports_per_month` | 1 | 10 | Unlimited | Unlimited |
| 4-Pillar Scoring | `scoring` | Full | Full | Full | Full |
| Corner Coaching | `corner_coaching` | Full | Full | Full | Full |
| Session Intelligence | `session_intelligence` | Full | Full | Full | Full |
| Comparison & Progress | `comparison` | ❌ | ❌ | ✅ | ✅ |
| Coaching Plans | `coaching_plans` | ❌ | ✅ | ✅ | ✅ |
| Visualization | `visualization` | ❌ | ✅ | ✅ | ✅ |
| Race Strategy | `race_strategy` | 3h limit | Full | Full | Full |
| Live Monitoring | `live_monitoring` | ❌ | ✅ | ✅ | ✅ |
| Pit Stop Planning | `pit_planning` | ❌ | ✅ | ✅ | ✅ |
| Incident Queue | `incident_queue` | ❌ | ✅ | ✅ | ✅ |
| PDF Reports | `export_pdf` | ❌ | ✅ | ✅ | ✅ |
| API Access | `api_access` | ❌ | ❌ | ✅ | ✅ |
| Raw Retention | `telemetry_retention_days` | 30 | 90 | 365 | Custom |
| Max Upload Size | `max_upload_size_mb` | 500 | 2000 | 5000 | 10000 |
| Max Concurrent Jobs | `max_concurrent_jobs` | 1 | 2 | 5 | 10 |
| CSV Export | `export_csv` | ✅ | ✅ | ✅ | ✅ |
| Branded Reports | `branded_reports` | ❌ | ❌ | ❌ | ✅ |
| Rate Limit Multiplier | `rate_multiplier` | 1× | 2× | 5× | 10× |

**B) Stripe product + price configuration**

Document the exact Stripe product structure to create:

```
Product: "Lap Coach Racer"
├── Price: racer_monthly  (€8.99/mo, recurring)
├── Price: racer_annual   (€69/yr, recurring)
│
Product: "Lap Coach World-Class"
├── Price: worldclass_monthly  (€13.99/mo, recurring)
├── Price: worldclass_annual   (€109/yr, recurring)
│
Product: "Lap Coach B2B"
├── Price: b2b_custom  (custom, not self-serve)
```

Create a script `scripts/setup_stripe_products.py` that:
1. Creates/updates Stripe products and prices via API
2. Outputs the price IDs for `.env.production`
3. Is idempotent (uses metadata to find existing products)

**C) Reconciliation between frontend, backend, and Stripe**

Create `scripts/verify_entitlement_consistency.py`:

```python
def verify():
    """Check that pricing.ts, plan_definitions DB, and Stripe products are in sync.

    1. Parse pricing.ts → expected tiers + features
    2. Query plan_definitions → actual DB tiers + features
    3. Query Stripe API → actual products + prices
    4. Compare all three → report discrepancies
    """
```

Run this as part of CI/CD to catch drift.

**D) Stripe Customer Portal configuration**

Document and script the Stripe Customer Portal setup:
- Allow plan switching (upgrade/downgrade)
- Allow payment method updates
- Allow cancellation (with cancel_at_period_end = true, NOT immediate)
- Show invoice history
- Redirect after changes: `https://lap-coach.racing/app/account/billing`

**E) Stripe test mode verification**

Create `scripts/test_stripe_flows.py`:
- Use Stripe test mode API keys
- Create a test customer
- Subscribe to each plan (monthly + annual)
- Upgrade/downgrade between plans
- Simulate payment failure + recovery
- Cancel subscription
- Verify DB state after each action
- Verify entitlements after each action

**Tests required**:
- Entitlement matrix matches pricing.ts
- Stripe setup script is idempotent
- Reconciliation script detects discrepancies
- Stripe test flows produce correct DB state
- Customer Portal configured correctly

**Acceptance criteria**:
- Single source of truth document for entitlements exists
- Stripe products/prices match the matrix
- CI check prevents drift between frontend/backend/Stripe
- Customer Portal allows self-service plan management
- All Stripe flows verified in test mode

---

### PROMPT 5B — Account UI Implementation (Next.js Frontend)

**Team**: Staff Frontend Engineer (architecture), UI Engineer (components), UX Designer (flow design)

**Context — What exists today**:
- Next.js 14 + TypeScript + Tailwind CSS, App Router
- Zustand 5 for client state, TanStack React Query 5 for server state
- Auth: `authFetch()` in `src/lib/auth.ts`, `apiFetch()` in `src/lib/api-client.ts`
- Auth store: `src/lib/auth-store.ts` (in-memory tokens)
- Route groups: `(auth)/`, `(free-report)/`, `(marketing)/`, `app/`
- Existing authenticated pages in `app/`: dashboard, sessions, tracks, compare, analytics
- Tailwind dark theme configured in `tailwind.config.ts`
- LAP brand colors: primary green #B6FF2E, dark backgrounds
- No `/app/account/` route group exists yet
- Backend API endpoints from PROMPTS 2A-2C ready to consume

**What you must deliver**:

**A) Account route group + layout**

Create `lap-website/src/app/app/account/layout.tsx`:
- Sidebar navigation:
  - Profile & Preferences
  - Security
  - Plan & Billing
  - Usage
  - Data & Privacy
  - Support
- Mobile: collapsible sidebar or tab bar
- Active route highlighting
- Breadcrumbs: App > Account > [Section]

**B) Profile & Preferences page**

Create `lap-website/src/app/app/account/profile/page.tsx`:

Sections:
1. **Avatar + Name** — display_name edit (inline save)
2. **Email** — current email, "Change email" button (triggers verification)
3. **Connected Accounts** — Google/GitHub OAuth status, connect/disconnect buttons
4. **Preferences** — units (metric/imperial), speed (km/h, mph, m/s), timezone (dropdown), language (7 options)
5. **Notifications** — toggle switches for each notification type

All changes save via PATCH `/api/v1/account/profile` or `/api/v1/account/preferences`.

**C) Security page**

Create `lap-website/src/app/app/account/security/page.tsx`:

Sections:
1. **Password** — "Change password" form (current + new + confirm)
2. **Two-Factor Authentication** — setup wizard:
   - Step 1: Generate QR code (display with `qrcode.react` library)
   - Step 2: Enter TOTP code to verify
   - Step 3: Show backup codes (one-time display, encourage saving)
   - Toggle to disable (requires TOTP code + password)
3. **Active Sessions** — table with browser/device, IP, last active, "Revoke" button per session, "Log out everywhere" button
4. **Login Activity** — timeline of recent logins with location/device

**D) Plan & Billing page** (from PROMPT 2B frontend)

Create `lap-website/src/app/app/account/billing/page.tsx` — already designed in PROMPT 2B.

**E) Usage page**

Create `lap-website/src/app/app/account/usage/page.tsx`:

- Large circular/arc progress indicators for each quota
- Usage history chart (bar chart, last 6 months)
- Table with daily breakdown of usage events
- "Projected usage" estimate for end of month

**F) Data & Privacy page** (from PROMPT 2C frontend)

Create `lap-website/src/app/app/account/data/page.tsx` — already designed in PROMPT 2C.

**G) Support page** (from PROMPT 2C frontend)

Create `lap-website/src/app/app/account/support/page.tsx` — already designed in PROMPT 2C.

**H) Shared components**

Create reusable components in `lap-website/src/components/account/`:

```
AccountSidebar.tsx          — navigation sidebar
FormField.tsx               — labeled input with validation
ToggleSwitch.tsx            — on/off toggle for preferences/notifications
ProgressRing.tsx            — circular progress indicator (quota visualization)
ConfirmationDialog.tsx      — modal for destructive actions (delete account, revoke sessions)
SectionCard.tsx             — card container for account sections
StatusBadge.tsx             — colored badge for plan tier / subscription status
```

**I) State management**

Add to Zustand store (`src/lib/auth-store.ts` or new `src/stores/account-store.ts`):

```typescript
interface AccountState {
  entitlements: Entitlements | null;
  preferences: UserPreferences | null;
  fetchEntitlements: () => Promise<void>;
  updatePreferences: (partial: Partial<UserPreferences>) => Promise<void>;
}
```

React Query hooks in `lap-website/src/hooks/`:
- `useProfile()` — GET /api/v1/me
- `useEntitlements()` — from /api/v1/me (from PROMPT 1C)
- `useSessions()` — GET /api/v1/account/sessions
- `useUsage()` — GET /api/v1/billing/usage
- `useInvoices()` — GET /api/v1/billing/invoices
- `useAuditLog()` — GET /api/v1/account/activity

**Tests required**:
- Vitest: all hooks return correct data shapes
- Vitest: components render correctly for each plan tier
- Vitest: form validation (password change, email change)
- Playwright E2E: complete account settings flow (profile → security → billing)
- Playwright E2E: 2FA setup + login with TOTP
- Playwright E2E: session revocation
- Responsive: all pages work on mobile (375px)

**Acceptance criteria**:
- Complete account section with 6 pages accessible from sidebar
- All forms save correctly via API
- 2FA setup wizard works end-to-end
- Usage visualization shows real quota data
- Dark theme consistent with rest of app
- Mobile responsive (no horizontal scroll, usable on phone)

---

### PROMPT 5C — End-to-End Integration Testing + Deployment

**Team**: QA Automation Lead (test design), SRE (deployment), Security Engineer (penetration testing)

**Context — What exists today**:
- Backend tests: pytest in `telemetry_tool/tests/` — 572 passed, 11 skipped
- Frontend tests: Vitest (unit) + Playwright (E2E in `lap-website/e2e/`)
- Test fixtures: `test_db` (in-memory SQLite), `seeded_db` (sample data)
- CI: `npm run lint && npm run test && npm run build` for frontend
- Deploy: `scp` files → `docker compose build api && up -d api` for backend, `npm run cf:deploy` for frontend
- Docker Compose: postgres:16 + redis:7 + 2 celery workers + caddy + api
- No integration tests that cover the full auth → billing → entitlements flow
- No staging environment, no canary deployment
- No security penetration testing

**What you must deliver**:

**A) Integration test suite**

Create `telemetry_tool/tests/integration/` directory:

**`test_auth_lifecycle.py`** — complete auth flows:
```python
def test_register_verify_login_logout():
    """Register → verify email → login → use API → refresh token → logout."""

def test_register_unverified_blocked():
    """Register → skip verification → attempt write → blocked."""

def test_oauth_login_first_time():
    """OAuth redirect → callback → auto-register → login."""

def test_password_reset_flow():
    """Forgot password → email → reset → login with new password."""

def test_2fa_setup_and_login():
    """Enable 2FA → logout → login with TOTP → success."""

def test_2fa_backup_code():
    """Enable 2FA → login with backup code → code consumed."""

def test_account_lockout():
    """5 failed logins → locked → wait → unlocked."""
```

**`test_billing_entitlements.py`** — billing + entitlements:
```python
def test_free_user_feature_gating():
    """Demo user → attempt comparison → blocked with upgrade CTA."""

def test_subscription_activates_features():
    """Demo → Stripe checkout → webhook → racer → features unlocked."""

def test_quota_enforcement():
    """Racer → generate 10 reports → 11th blocked with quota error."""

def test_quota_resets_monthly():
    """Use all quota → advance clock to next month → quota available."""

def test_downgrade_preserves_data():
    """World-Class → cancel → period ends → demo → data still readable but gated."""

def test_past_due_grace_period():
    """Payment fails → past_due → features still work → 7 days → warning."""

def test_stripe_webhook_idempotency():
    """Send same event twice → only processed once."""

def test_stripe_reconciliation():
    """Manually desync DB → run reconciliation → DB matches Stripe."""
```

**`test_workspace_teams.py`** — multi-tenancy:
```python
def test_workspace_isolation():
    """User A creates session → User B (different workspace) cannot see it."""

def test_team_invite_accept():
    """Owner invites member → member accepts → member sees team workspace."""

def test_rbac_enforcement():
    """Viewer cannot upload. Member can upload. Admin can delete. Owner can change billing."""

def test_idor_prevention():
    """User A attempts to access User B's session by ID → 403 or empty."""
```

**`test_data_lifecycle.py`** — retention + GDPR:
```python
def test_retention_enforcement():
    """Create session → advance clock past retention → session raw data deleted, reports kept."""

def test_gdpr_export():
    """Request export → wait for completion → download ZIP → contains all user data."""

def test_account_deletion():
    """Delete account → 30 day grace → purge → all data gone."""

def test_account_deletion_cancel():
    """Delete account → cancel within grace → account restored."""
```

**B) E2E frontend tests**

Create Playwright tests in `lap-website/e2e/`:

```
account-profile.spec.ts     — edit name, change email, update preferences
account-security.spec.ts    — change password, 2FA setup, session revoke
account-billing.spec.ts     — view plan, usage bars, invoice list
account-data.spec.ts        — view retention, request export, delete sessions
feature-gating.spec.ts      — demo user sees upgrade banners, paid user sees features
upgrade-flow.spec.ts        — click upgrade → Stripe checkout → return → features unlocked
```

**C) Security testing checklist**

Create `docs/security-testing.md` with manual + automated checks:

1. **Authentication**:
   - [ ] Expired JWT rejected
   - [ ] Invalid JWT signature rejected
   - [ ] Refresh token single-use (replay rejected)
   - [ ] Account lockout after 5 failed logins
   - [ ] Password reset token single-use + expires

2. **Authorization**:
   - [ ] IDOR: cannot access other workspace's data (test with direct API calls)
   - [ ] RBAC: viewer cannot perform admin actions
   - [ ] Feature gating: demo cannot access racer features via API
   - [ ] Admin endpoints require `is_platform_admin`

3. **Input validation**:
   - [ ] SQL injection (parameterized queries everywhere)
   - [ ] XSS (sanitized user inputs)
   - [ ] Path traversal (file upload/download)
   - [ ] CSRF (SameSite cookies + origin check)
   - [ ] Content-type validation on uploads

4. **Rate limiting**:
   - [ ] Auth endpoints rate limited per IP
   - [ ] Write endpoints rate limited per user
   - [ ] Rate limits scale per plan

5. **Billing**:
   - [ ] Webhook signature verified
   - [ ] Events processed idempotently
   - [ ] Cannot self-service upgrade to B2B

**D) Deployment pipeline**

Create `scripts/deploy.sh` with these stages:

```bash
#!/bin/bash
# 1. Pre-flight checks
echo "Running pre-flight checks..."
python scripts/verify_entitlement_consistency.py
pytest telemetry_tool/tests/ -x --timeout=120
cd lap-website && npm run lint && npm test && npm run build

# 2. Backend deploy
echo "Deploying backend..."
scp -r telemetry_tool/ root@46.225.227.24:/opt/lap-api/
scp docker-compose.prod.yml root@46.225.227.24:/opt/lap-api/
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose build api && docker compose up -d api"

# 3. Run migrations
echo "Running migrations..."
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose exec api alembic upgrade head"

# 4. Health check
echo "Checking health..."
for i in {1..10}; do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://api.lap-coach.racing/healthz)
    if [ "$STATUS" = "200" ]; then echo "API healthy!"; break; fi
    sleep 5
done

# 5. Frontend deploy
echo "Deploying frontend..."
cd lap-website && npm run cf:deploy

# 6. Smoke tests
echo "Running smoke tests..."
curl -sf https://api.lap-coach.racing/healthz | jq .
curl -sf https://lap-coach.racing | head -1
```

**E) Rollback procedure**

Document in `docs/rollback.md`:
1. Backend: `docker compose exec api alembic downgrade -1` + redeploy previous image
2. Frontend: `wrangler rollback` (Cloudflare Workers keeps previous versions)
3. Database: restore from daily backup if migration is destructive
4. Feature flags: disable new features via env vars without redeployment

**F) Monitoring dashboard**

Create a simple monitoring page (can be a static HTML file or admin route):
- API response times (from metrics)
- Error rate (5xx / total)
- Active jobs + queue depth
- Stripe webhook success rate
- User registrations (last 7 days)
- Revenue metrics (from Stripe API or DB)

**Tests required**:
- All integration tests pass in CI
- All E2E tests pass against staging
- Security checklist all items verified
- Deploy script succeeds in dry-run mode
- Rollback procedure tested and documented

**Acceptance criteria**:
- Complete integration test suite covering auth, billing, entitlements, teams, data lifecycle
- E2E tests covering all account pages
- Security testing checklist with all items passing
- Automated deployment script with health checks
- Documented rollback procedure
- Monitoring dashboard accessible to platform admins

---

## EXECUTION ORDER

The prompts should be executed in this order for correct dependency resolution:

```
Phase 1 (Foundation):
  1A → 1B → 1C              (Entitlements: data model → middleware → frontend)
  4A (in parallel with 1A)    (Data model design can start immediately)

Phase 2 (Backend):
  2A → 3A                    (Account backend → auth lifecycle)
  2B → 3B                    (Billing backend → payments + observability)
  4B (in parallel)            (Query patterns)

Phase 3 (Frontend + Integration):
  5B                          (Account UI — depends on all backend prompts)
  2C → 3C                    (Data/privacy + compliance + admin)
  4C                          (Data lifecycle + archival)

Phase 4 (Verification):
  5A                          (Entitlement matrix reconciliation)
  5C                          (Integration testing + deployment)
```

Estimated effort: ~20-25 Claude agent sessions across all 15 prompts.
