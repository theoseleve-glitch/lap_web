# Security Remediation Tracker

Source: Pentest 2026-03-07 (`docs/security/PENTEST_REPORT_2026-03-07.md`)

## Active Findings

| ID | Severity | Finding | Component | Owner | Due | Fix PR | Retest |
|----|----------|---------|-----------|-------|-----|--------|--------|
| M-04 | MEDIUM | No SRI on frontend scripts | Next.js config | frontend | 2026-03-14 | — | accepted |

## Closed Findings

| ID | Severity | Finding | Closed | Fix PR | Verified |
|----|----------|---------|--------|--------|----------|
| H-01 | HIGH | `/metrics` blocked in Caddyfile | 2026-03-07 | direct commit | pending retest |
| H-02 | HIGH | `/healthz` returns status-only; detail behind auth | 2026-03-07 | direct commit | pending retest |
| H-03 | HIGH | API root returns JSON 404, not HTML | 2026-03-07 | direct commit | pending retest |
| M-01 | MEDIUM | HSTS max-age=31536000 in middleware + next.config | 2026-03-07 | direct commit | pending retest |
| M-02 | MEDIUM | `unsafe-eval` removed from CSP script-src | 2026-03-07 | direct commit | pending retest |
| M-03 | MEDIUM | APP_VERSION default changed from "dev" to "1.4.0" | 2026-03-07 | direct commit | pending retest |
| L-01 | LOW | TLS 1.2+ enforced in Caddyfile | 2026-03-07 | direct commit | pending retest |
| L-02 | LOW | Via + Server headers stripped in Caddyfile | 2026-03-07 | direct commit | pending retest |
| L-03 | LOW | lap_session_id now httpOnly | 2026-03-07 | direct commit | pending retest |
| L-04 | LOW | lap_persona deferred until explicit interaction | 2026-03-07 | direct commit | pending retest |

## Status Legend

- **pending** — Not yet fixed
- **in-progress** — Fix PR open
- **fixed** — PR merged, awaiting retest
- **verified** — Retested and confirmed resolved
- **accepted** — Risk accepted with documented justification

## Quick Fix Guide

### H-01: Block /metrics in Caddyfile
```caddyfile
@metrics path /metrics
respond @metrics 404
```

### H-02: Strip db_stats from healthz
Return `{"status":"ok"}` only. Move detailed stats to `/api/v1/admin/health` behind auth.

### H-03: Add JSON error handler for API root
```python
@app.errorhandler(500)
def handle_500(e):
    return jsonify(ok=False, error="Internal server error"), 500
```
Also add a catch-all route that returns 404 JSON instead of the desktop HTML template.

### M-01: HSTS in middleware.ts
```typescript
response.headers.set('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');
```

### M-03: Set VERSION in .env.production
```
VERSION=1.4.0
```

### L-01: TLS minimum in Caddyfile
```caddyfile
api.lap-coach.racing {
    tls {
        protocols tls1.2 tls1.3
    }
}
```

### L-02 + H-01 combined Caddyfile block
```caddyfile
api.lap-coach.racing {
    tls {
        protocols tls1.2 tls1.3
    }
    header -Via
    header -Server
    @metrics path /metrics
    respond @metrics 404
    reverse_proxy localhost:5000
}
```

### L-03: HttpOnly on session cookie
In `middleware.ts`, add `httpOnly: true` to the `lap_session_id` Set-Cookie.
