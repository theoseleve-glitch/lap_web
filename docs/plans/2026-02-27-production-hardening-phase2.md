# Production Hardening — Phase 2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close HIGH-severity gaps: CSRF protection, audit logging on mutations, file upload hardening, Prometheus metrics.

**Architecture:** Middleware-first approach — CSRF and audit log are `before_request`/decorator hooks. File upload hardening extends existing validation. Prometheus adds `/metrics` scrape endpoint.

**Tech Stack:** Flask, Python stdlib (no new deps except `prometheus_client` for Task 4)

**Revised scope (from exploration):**
- P2-4 (Invitations): Already implemented — SKIPPED
- P2-6 (Out-of-order webhooks): Done in Phase 1 — SKIPPED

---

### Task 1: CSRF Protection — Double-Submit Cookie Middleware

**Context:** Zero CSRF protection exists. 129+ state-changing endpoints exposed. The design calls for double-submit cookie: set `csrf_token` cookie on login, require `X-CSRF-Token` header on mutations.

**Files:**
- Create: `telemetry_tool/web/middleware/csrf.py`
- Modify: `telemetry_tool/web/routes/auth.py` (set cookie on login/refresh)
- Modify: `telemetry_tool/web/app.py` (register middleware)
- Create: `telemetry_tool/tests/test_csrf.py`

**How it works:**
1. On successful login/refresh, set `csrf_token` cookie (httpOnly=False so JS can read it, Secure, SameSite=Lax)
2. `before_request` hook checks: for POST/PUT/DELETE/PATCH on `/api/v1/*`, require `X-CSRF-Token` header matching cookie value
3. Exempt: `/api/v1/billing/webhook` (uses Stripe signature), OPTIONS (CORS preflight)
4. Only active when `AUTH_REQUIRED=1`

**Implementation:**

```python
# web/middleware/csrf.py
"""CSRF protection via double-submit cookie pattern."""
import logging
import secrets

from flask import request, g, current_app, make_response

logger = logging.getLogger(__name__)

_CSRF_COOKIE = "csrf_token"
_CSRF_HEADER = "X-CSRF-Token"
_EXEMPT_PATHS = {"/api/v1/billing/webhook"}
_MUTATING_METHODS = {"POST", "PUT", "DELETE", "PATCH"}


def csrf_middleware():
    """Before-request: validate CSRF token on state-changing requests."""
    if not current_app.config.get("AUTH_REQUIRED"):
        return

    if request.method not in _MUTATING_METHODS:
        return

    if not request.path.startswith("/api/v1/"):
        return

    if request.path in _EXEMPT_PATHS:
        return

    cookie_token = request.cookies.get(_CSRF_COOKIE)
    header_token = request.headers.get(_CSRF_HEADER)

    if not cookie_token or not header_token:
        from web.api_utils import api_error, ErrorCode
        return api_error(ErrorCode.FORBIDDEN, "CSRF token missing", status=403)

    if not secrets.compare_digest(cookie_token, header_token):
        from web.api_utils import api_error, ErrorCode
        return api_error(ErrorCode.FORBIDDEN, "CSRF token mismatch", status=403)


def generate_csrf_token() -> str:
    """Generate a new CSRF token (64 URL-safe bytes)."""
    return secrets.token_urlsafe(48)


def set_csrf_cookie(response, token: str):
    """Set the CSRF cookie on a response."""
    response.set_cookie(
        _CSRF_COOKIE,
        value=token,
        httponly=False,  # JS must read this
        secure=True,
        samesite="Lax",
        max_age=30 * 24 * 3600,  # 30 days (matches refresh token)
        path="/",
    )
    return response
```

**Auth route changes** — In login/refresh success handlers, after building the response:
```python
from web.middleware.csrf import generate_csrf_token, set_csrf_cookie

# After building response JSON
csrf_token = generate_csrf_token()
resp = make_response(jsonify({...}))
set_csrf_cookie(resp, csrf_token)
return resp
```

**App registration** — In `app.py`, after auth_middleware:
```python
from .middleware.csrf import csrf_middleware
app.before_request(csrf_middleware)
```

**Tests (5):**
1. `test_csrf_blocks_post_without_token` — POST to `/api/v1/sessions/` without CSRF → 403
2. `test_csrf_allows_matching_token` — POST with matching cookie + header → passes through
3. `test_csrf_blocks_mismatched_token` — Different cookie vs header → 403
4. `test_csrf_skips_webhook` — POST to `/api/v1/billing/webhook` → passes through
5. `test_csrf_skips_when_auth_not_required` — AUTH_REQUIRED=0 → passes through

---

### Task 2: Audit Log Decorator + High-Priority Route Wiring

**Context:** `_log_audit(conn, user_id, action, details)` exists in `auth/service.py:418`. Currently only 5 call sites (login, 2FA, password ops). Need decorator for mutation routes.

**Files:**
- Create: `telemetry_tool/web/middleware/audit.py`
- Modify: `telemetry_tool/web/routes/teams.py` (add audit to team mutations)
- Modify: `telemetry_tool/web/routes/api_v1_account.py` (add audit to profile/subscription mutations)
- Modify: `telemetry_tool/web/routes/billing.py` (add audit to webhook events)
- Create: `telemetry_tool/tests/test_audit_decorator.py`

**Approach:** Rather than a decorator (which requires access to `conn` and parsed request data), use an `audit_log()` helper function that's called explicitly in high-priority routes. This is more practical than a decorator because the action details vary per route.

**Priority routes to wire (security-critical mutations):**
- Team: create team, add member, remove member, change role
- Account: profile update, email change, account deletion request
- Billing: webhook events (checkout, subscription changes)

**Implementation:**

```python
# web/middleware/audit.py
"""Centralized audit logging helper."""
import json
import logging

from flask import g, request

logger = logging.getLogger(__name__)


def audit_log(conn, action: str, details: dict | None = None):
    """Log an auditable action for the current request context.

    Uses g.current_user_id if available, plus request IP and user-agent.
    """
    user_id = getattr(g, "current_user_id", None)
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    ua = request.headers.get("User-Agent", "")

    conn.execute(
        "INSERT INTO audit_log (user_id, action, details, ip_address, user_agent) "
        "VALUES (%(uid)s, %(action)s, %(details)s, %(ip)s, %(ua)s)",
        {
            "uid": user_id,
            "action": action,
            "details": json.dumps(details or {}),
            "ip": ip[:45] or None,
            "ua": ua[:500] or None,
        },
    )
```

**Route wiring examples:**

```python
# In teams.py - after team creation
from web.middleware.audit import audit_log
audit_log(conn, "team_created", {"team_id": team["id"], "name": team["name"]})

# In teams.py - after member added
audit_log(conn, "team_member_added", {"team_id": team_id, "target_user_email": email, "role": role})

# In teams.py - after member removed
audit_log(conn, "team_member_removed", {"team_id": team_id, "target_user_id": user_id})
```

**Tests (4):**
1. `test_audit_log_inserts_row` — Verify INSERT into audit_log table
2. `test_audit_log_uses_request_context` — Check IP/UA from Flask request
3. `test_audit_log_handles_missing_user` — No g.current_user_id → user_id=None
4. `test_audit_log_truncates_long_values` — IP > 45 chars, UA > 500 chars truncated

---

### Task 3: File Upload Hardening

**Context:** Current validation: extension check (.csv) + null-byte binary detection. Design calls for: proper CSV text validation, per-route MAX_CONTENT_LENGTH.

**Files:**
- Modify: `telemetry_tool/web/routes/api_data.py` (enhance `files_upload()`)
- Create: `telemetry_tool/tests/test_upload_hardening.py`

**Enhancements:**
1. **Text content validation**: Check first 8KB is valid UTF-8 or Latin-1 text (not just null-byte absence)
2. **CSV structure check**: First line must be parseable as CSV headers (at least 2 columns)
3. **Double-extension rejection**: Reject `.csv.exe`, `.csv.php` etc.
4. **Size limit on this route**: 500MB max for direct upload (streaming ingest handles larger)

**Implementation:**

```python
# Enhanced validation in files_upload()
import csv
import io

# 1. Size check (500MB for direct upload)
content_length = request.content_length or 0
if content_length > 500 * 1024 * 1024:
    return jsonify({"error": "File too large for direct upload (max 500MB)"}), 413

# 2. Extension check (reject double extensions)
basename = f.filename.rsplit("/", 1)[-1] if f.filename else ""
parts = basename.split(".")
if len(parts) > 2 or not basename.lower().endswith(".csv"):
    return jsonify({"error": "only .csv files allowed"}), 400

# 3. Content validation: read sample, check text + CSV structure
sample = f.read(8192)
f.seek(0)

if b"\x00" in sample:
    return jsonify({"error": "File appears to be binary, not CSV"}), 400

# Try decoding as UTF-8, fall back to Latin-1
try:
    text_sample = sample.decode("utf-8")
except UnicodeDecodeError:
    try:
        text_sample = sample.decode("latin-1")
    except UnicodeDecodeError:
        return jsonify({"error": "File is not valid text"}), 400

# Check first line looks like CSV headers (at least 2 columns)
first_line = text_sample.split("\n", 1)[0].strip()
reader = csv.reader(io.StringIO(first_line))
try:
    headers = next(reader)
    if len(headers) < 2:
        return jsonify({"error": "CSV must have at least 2 columns"}), 400
except (csv.Error, StopIteration):
    return jsonify({"error": "File does not appear to be valid CSV"}), 400
```

**Tests (5):**
1. `test_upload_rejects_binary_file` — ELF/PE magic bytes → 400
2. `test_upload_rejects_double_extension` — `data.csv.exe` → 400
3. `test_upload_rejects_single_column_csv` — Only 1 column → 400
4. `test_upload_accepts_valid_csv` — Proper CSV → 200
5. `test_upload_accepts_latin1_csv` — Latin-1 encoded CSV → 200

---

### Task 4: Prometheus Metrics Endpoint

**Context:** Zero metrics infrastructure. Design calls for `/metrics` scrape endpoint.

**Files:**
- Create: `telemetry_tool/web/middleware/metrics.py`
- Modify: `telemetry_tool/web/app.py` (register metrics)
- Create: `telemetry_tool/tests/test_metrics.py`

**Approach:** Use `prometheus_client` (Docker-only dep, like gunicorn/stripe). Register counters and histograms. Expose `/metrics` endpoint.

**Implementation:**

```python
# web/middleware/metrics.py
"""Prometheus metrics for Flask app."""
import logging
import time

from flask import request, g

logger = logging.getLogger(__name__)

try:
    from prometheus_client import (
        Counter, Histogram, Gauge,
        generate_latest, CONTENT_TYPE_LATEST,
    )
    HAS_PROMETHEUS = True
except ImportError:
    HAS_PROMETHEUS = False
    logger.info("prometheus_client not installed; /metrics disabled")

if HAS_PROMETHEUS:
    REQUEST_COUNT = Counter(
        "http_requests_total",
        "Total HTTP requests",
        ["method", "endpoint", "status"],
    )
    REQUEST_LATENCY = Histogram(
        "http_request_duration_seconds",
        "HTTP request latency",
        ["method", "endpoint"],
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    )
    WEBHOOK_EVENTS = Counter(
        "stripe_webhook_events_total",
        "Stripe webhook events processed",
        ["event_type", "outcome"],
    )
    ACTIVE_REQUESTS = Gauge(
        "http_requests_active",
        "Currently active HTTP requests",
    )


def init_metrics(app):
    """Register metrics middleware and /metrics endpoint."""
    if not HAS_PROMETHEUS:
        return

    @app.before_request
    def _start_timer():
        g._metrics_start = time.monotonic()
        ACTIVE_REQUESTS.inc()

    @app.after_request
    def _record_metrics(response):
        if hasattr(g, "_metrics_start"):
            latency = time.monotonic() - g._metrics_start
            endpoint = request.endpoint or "unknown"
            REQUEST_LATENCY.labels(
                method=request.method,
                endpoint=endpoint,
            ).observe(latency)
            REQUEST_COUNT.labels(
                method=request.method,
                endpoint=endpoint,
                status=response.status_code,
            ).inc()
            ACTIVE_REQUESTS.dec()
        return response

    @app.route("/metrics")
    def metrics_endpoint():
        from flask import Response
        return Response(
            generate_latest(),
            mimetype=CONTENT_TYPE_LATEST,
        )

    logger.info("Prometheus metrics enabled at /metrics")
```

**Tests (4):**
1. `test_metrics_endpoint_returns_prometheus_format` — GET /metrics → 200 with text/plain content
2. `test_request_counter_increments` — After a request, counter > 0
3. `test_request_latency_recorded` — After a request, histogram has observations
4. `test_metrics_graceful_without_prometheus` — When prometheus_client missing → no crash

---

## Execution Order

Tasks are independent. Execute 1 → 2 → 3 → 4 sequentially.

## Testing

After all tasks, run full test suite:
```bash
cd telemetry_tool && python -m pytest tests/ -x -q
```

Expected: All existing tests pass + ~18 new tests.
