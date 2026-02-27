# Security Testing Checklist

Manual and automated security verification for Lap Coach SaaS platform.

## 1. Authentication

- [x] Expired JWT rejected — `decode_access_token()` raises `AuthError` on `exp` past
- [x] Invalid JWT signature rejected — wrong secret → `AuthError`
- [x] Refresh token single-use — hash stored in DB, deleted after rotation
- [x] Account lockout after 5 failed logins — tracked via `failed_login_count` column
- [x] Password reset token single-use + expires — SHA-256 hash stored, 1-hour TTL, deleted after use
- [x] Timing-safe password verification — `_DUMMY_HASH` used for non-existent users

## 2. Authorization

- [x] IDOR: cannot access other workspace's data — RLS policies via `SET LOCAL` + `CREATE POLICY`
- [x] RBAC: viewer cannot perform admin actions — `has_permission()` returns False
- [x] Feature gating: demo cannot access racer features via API — `authorize_feature()` checks plan
- [x] Admin endpoints require `is_platform_admin` — `before_request` guard on admin blueprint
- [x] Email verification required for write operations — `require_email_verified` decorator

## 3. Input Validation

- [x] SQL injection: parameterized queries everywhere — `%(name)s` syntax, no string formatting
- [x] XSS: sanitized user inputs — `sanitize_html()` strips tags, length-limited
- [x] Path traversal: file upload/download — `sanitize_filename()` strips `..`, `/`, `\`
- [x] CSRF: SameSite cookies + origin check — `SameSite=Lax` on refresh cookie
- [x] Content-type validation on uploads — MIME check + header sniffing

## 4. Rate Limiting

- [x] Auth endpoints rate limited per IP — Redis sliding-window, tier `auth` (10/min)
- [x] Write endpoints rate limited per user — tier `write` (30/min)
- [x] Rate limits scale per plan — `rate_multiplier` in plan_definitions (1x/2x/5x/10x)
- [x] Rate limit headers in response — `X-RateLimit-Remaining`, `X-RateLimit-Reset`
- [x] `RATE_LIMIT_ENABLED` env var toggle — graceful fallback when Redis unavailable

## 5. Billing

- [x] Webhook signature verified — `stripe.Webhook.construct_event()` with `STRIPE_WEBHOOK_SECRET`
- [x] Events processed idempotently — Redis SETNX + `stripe_events` DB table dedup
- [x] Cannot self-service upgrade to B2B — B2B has no self-serve prices
- [x] Event ordering enforced — timestamp comparison via `stripe_last_event:{customer_id}` (Redis)

## 6. Data Protection

- [x] Passwords hashed with Argon2id — `time_cost=3`, `memory_cost=65536`, `parallelism=1`
- [x] Refresh tokens hashed in DB — SHA-256, plain text never stored
- [x] Access tokens in-memory only — NOT localStorage (XSS-resistant)
- [x] GPS data precision reduced in exports — 3 decimal places (~111m precision)
- [x] GDPR export + deletion with 30-day grace period
- [x] PII never in URL paths — user IDs only, no email/name in URLs

## 7. Infrastructure

- [x] TLS via Caddy automatic certificates — HTTPS everywhere
- [x] Security headers: `X-Content-Type-Options`, `X-Frame-Options`, `Strict-Transport-Security`
- [x] `X-Powered-By` disabled — removed from Flask + Next.js
- [x] `.env` files in `.gitignore` — credentials never committed
- [x] Database backups encrypted — GPG AES256 (when `BACKUP_ENCRYPTION_KEY` set)
- [x] Daily backups with 7-day retention — pg_dump at 3 AM UTC

## Automated Testing

Run security-related tests:

```bash
# Auth service (password hashing, JWT, timing-safe)
pytest tests/test_auth_service.py -v

# RBAC permissions matrix
pytest tests/test_rbac.py -v

# Rate limiting
pytest tests/test_rate_limit.py -v

# Input sanitization
pytest tests/test_prompt_3c.py -k "sanitiz" -v

# Admin access control
pytest tests/test_admin_middleware.py -v

# Billing webhook verification
pytest tests/test_billing_webhook.py -v

# Integration: full auth lifecycle
pytest tests/integration/test_auth_lifecycle.py -v

# Integration: workspace isolation + RBAC
pytest tests/integration/test_workspace_teams.py -v
```

## Manual Verification Steps

1. **JWT replay**: Copy expired access token → use in API call → verify 401
2. **IDOR**: Create session as User A → try GET/DELETE as User B → verify 403/empty
3. **SQL injection**: Insert `'; DROP TABLE users; --` in form field → verify no error
4. **Path traversal**: Upload file named `../../../etc/passwd.csv` → verify sanitized filename
5. **Rate limit**: Send 15 requests in 10 seconds to `/auth/login` → verify 429 after limit
