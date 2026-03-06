# CORS + Cloudflare Edge Hardening — Design

**Date**: 2026-03-06
**Status**: Implemented

## Problem

1. CORS default `http://localhost:3000` leaks to prod if env var unset
2. `flask_cors` `always_send=True` returns ACAO for non-matching origins
3. No prod guard prevents localhost in allowlist
4. No Cloudflare WAF, rate limits, or bot protection
5. Origin server accepts connections from any IP (not just Cloudflare)

## Solution

### Approach: Custom CORS middleware (replaced flask_cors)

Single `after_request` handler in `web/middleware/cors.py`:
- Validates `Origin` header against explicit allowlist from `CORS_ALLOWED_ORIGINS` env var
- Sets headers only when origin matches — blocked origins get no ACAO
- Same logic for OPTIONS, normal requests, and error responses
- Always sets `Vary: Origin` to prevent cache poisoning
- `Access-Control-Max-Age: 86400` on preflight

### Config changes

- `CORS_ALLOWED_ORIGINS` default changed from `http://localhost:3000` to empty string
- `validate()` rejects any origin containing `localhost` or `127.0.0.1` when `ENV=production`

### Cloudflare configuration (dashboard)

- API domain proxied (orange cloud)
- SSL mode: Full (strict)
- Managed WAF rules (OWASP Core Ruleset)
- Rate limiting rules for auth/compute/global
- Bot protection on auth endpoints
- Exceptions for Stripe webhooks, health checks

### Hetzner firewall

- Allow only Cloudflare IP ranges to port 443
- Allow SSH from VPN/bastion only

## Files Changed

| File | Change |
|------|--------|
| `telemetry_tool/web/middleware/cors.py` | New — custom CORS middleware |
| `telemetry_tool/web/app.py` | Replaced flask_cors with custom middleware |
| `telemetry_tool/web/config.py` | Empty default, prod localhost guard |
| `telemetry_tool/tests/test_cors.py` | 19 tests covering all scenarios |

## Prod Environment Variable

```
CORS_ALLOWED_ORIGINS=https://lap-coach.racing,https://www.lap-coach.racing
```
