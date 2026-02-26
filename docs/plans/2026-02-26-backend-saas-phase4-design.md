# Backend SaaS Phase 4: API v1 Hardening — Design

**Date**: 2026-02-26
**Status**: Approved
**Phase**: 4 of 5 (Backend SaaS Overhaul)
**Prerequisite**: Phase 3 (Celery + Pipeline) complete

## Decisions

| Decision | Choice |
|----------|--------|
| Scope | Full surface — migrate legacy, harden all, create GDPR endpoints |
| Rate limiting | Custom Redis sliding window (no flask-limiter dependency) |
| Validation errors | All errors at once (Pydantic v2 default) |
| Cursor pagination | Composite cursor (sort_value + id) — keyset, no OFFSET drift |
| Idempotency | Cache full response (status + body), replay on duplicate |
| Legacy migration | Proxy pattern — legacy routes wrap v1 handlers + deprecation headers |
| GDPR scope | Full compliance — export, erasure, rectification, minimization |

---

## 1. Response Envelope & Error Codes

Every `/api/v1/` endpoint returns a consistent envelope:

```json
{"ok": true, "data": {...}, "meta": {"request_id": "uuid", "pagination": null}}
{"ok": false, "error": {"code": "VALIDATION_ERROR", "message": "...", "details": [...]}, "meta": {"request_id": "uuid"}}
```

**Implementation**: `api_response(data, status, meta)` and `api_error(code, message, details, status)` helpers used by all v1 routes. A `request_id` (UUID4) is generated per request via `before_request` hook.

**Error codes** (stable string enum): `INVALID_CREDENTIALS`, `TOKEN_EXPIRED`, `FORBIDDEN`, `INSUFFICIENT_ROLE`, `VALIDATION_ERROR`, `NOT_FOUND`, `CONFLICT`, `QUOTA_EXCEEDED`, `RATE_LIMITED`, `ANALYSIS_FAILED`, `FILE_TOO_LARGE`, `UNSUPPORTED_FORMAT`, `IDEMPOTENCY_CONFLICT`, `INTERNAL_ERROR`, `SERVICE_UNAVAILABLE`, `NOT_IMPLEMENTED`.

The existing `_json_response` in `auth.py` will be replaced by the shared helpers.

---

## 2. Pydantic Request Validation

A `@validate_body(Schema)` decorator that:
1. Parses `request.get_json()` through a Pydantic v2 `BaseModel` subclass
2. On success, passes the validated model as `g.body`
3. On failure, returns all errors in the envelope format with `VALIDATION_ERROR` code

```python
class CreateTeamSchema(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    slug: str = Field(pattern=r"^[a-z0-9-]+$", min_length=2, max_length=50)

@bp.route("/teams", methods=["POST"])
@require_auth
@validate_body(CreateTeamSchema)
def create_team():
    team = g.body  # typed CreateTeamSchema instance
```

Error response includes all validation failures:
```json
{
  "ok": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed",
    "details": [
      {"field": "slug", "message": "String should match pattern '^[a-z0-9-]+$'"},
      {"field": "name", "message": "String should have at least 2 characters"}
    ]
  }
}
```

A `@validate_params(Schema)` variant handles query parameter validation for GET endpoints.

Schemas live in `telemetry_tool/web/schemas/` — one file per resource domain.

---

## 3. Rate Limiting

Custom Redis sliding window via Lua script. `@rate_limit(tier="read")` decorator per route.

| Tier | Key Scope | Limit |
|------|-----------|-------|
| `auth` | IP address | 20 req/min |
| `read` | user_id | 300 req/min |
| `write` | user_id | 60 req/min |
| `analyze` | user_id | 5 req/hour |
| `upload` | user_id | 10 req/hour |

**Lua script**: Sliding window counter using sorted set — `ZADD` with timestamp score, `ZREMRANGEBYSCORE` to trim, `ZCARD` to count. Key pattern: `ratelimit:{tier}:{scope_value}`.

When exceeded: HTTP 429 with `Retry-After` header and `RATE_LIMITED` error code.

Decorator stacking order: `@rate_limit` before `@validate_body` — reject early.

```python
@bp.route("/batch-reanalyze", methods=["POST"])
@require_auth
@rate_limit(tier="analyze")
@validate_body(BatchReanalyzeSchema)
def batch_reanalyze():
    ...
```

---

## 4. Cursor Pagination

Shared `paginate()` utility with composite cursor encoding/decoding.

**Cursor format** (opaque base64 to clients):
```json
{"s": "2026-01-15T10:30:00", "id": 125}
```

**Query params**: `?limit=25&cursor=eyJzIjoi...&sort=created_at&order=desc`

**Response meta**:
```json
{
  "ok": true,
  "data": [...],
  "meta": {
    "request_id": "...",
    "pagination": {"next_cursor": "eyJzIjoi...", "has_more": true, "limit": 25}
  }
}
```

**SQL generation**: Keyset pagination — `WHERE (sort_col, id) < (:cursor_sort, :cursor_id)`. No OFFSET drift.

Default limit 25, max 100. Paginated endpoints: sessions, jobs, batch jobs, stale sessions, track records, team members, workspaces.

---

## 5. Idempotency Keys

Write endpoints accept `Idempotency-Key` header. Full response cached in Redis (24h TTL). Scoped to workspace.

**Flow**:
1. `@idempotent` decorator checks Redis key `idempotency:{workspace_id}:{key}`
2. If found: return cached response (same status code + body)
3. If not found: `SET NX` processing lock (60s TTL), execute handler, cache response (24h TTL)
4. If handler fails (5xx): don't cache — let client retry
5. Concurrent duplicate: return 409 `IDEMPOTENCY_CONFLICT`

**Required on**: `POST /batch-reanalyze`, `POST /api/v1/sessions/import`, `POST /api/v1/teams`, `POST /api/v1/teams/:id/members`, `POST /api/v1/account/export`, `DELETE /api/v1/account`.

---

## 6. Legacy Route Migration (Proxy Pattern)

Legacy `/api/` endpoints get `/api/v1/` equivalents with full hardening. Legacy routes become thin proxies.

**New route file**: `api_v1_data.py` — v1 implementations with schemas, pagination, envelope.

**Proxy pattern**: Legacy handler calls v1 handler internally, adds deprecation headers:
- `Deprecation: true`
- `Sunset: 2026-09-01`
- `Link: </api/v1/...>; rel="successor-version"`

**URL normalization** for v1:
- `/api/v1/sessions/<id>/laps/gps` (was `/api/session/<id>/gps_laps`)
- `/api/v1/sessions/<id>/speed-trace` (was `/api/session/<id>/speed_trace`)
- `/api/v1/tracks/<id>/records` (was `/api/track/<id>/records`)

**Resource grouping**: `/api/v1/sessions/`, `/api/v1/tracks/`, `/api/v1/files/`, `/api/v1/drivers/`

---

## 7. GDPR & Data Management

New endpoints under `/api/v1/account/`:

**Data Export** (Right of Access + Portability):
- `POST /api/v1/account/export` — initiates async Celery export job
- `GET /api/v1/account/export/<id>/status` — poll progress
- `GET /api/v1/account/export/<id>/download` — download ZIP

Export gathers: profile, sessions (metadata + laps), scores, fingerprints, annotations, team memberships. GPS precision reduced to 3 decimal places. ZIP stored in upload dir, auto-deleted after 7 days.

**Account Deletion** (Right of Erasure):
- `DELETE /api/v1/account` — soft-delete, 30-day grace period
- `POST /api/v1/account/cancel-deletion` — cancel during grace

Soft delete: sets `users.deleted_at`, revokes tokens, removes from teams. Celery beat daily task hard-purges accounts past 30 days.

**Profile Rectification**:
- `PATCH /api/v1/account/profile` — update display_name, email (re-verification)

**Migration 010**: `deleted_at` column on `users`, new `data_exports` table.

---

## 8. Request ID & Structured Logging

Every request gets a UUID4 `request_id` via `before_request` hook (stored in `g.request_id`):
- Included in response envelope `meta`
- Passed to Celery task headers
- Added to log records via `RequestIdFilter`

**Log filter** adds: `request_id`, `workspace_id`, `user_id` to every log record.

**Log format**: JSON when `TELEMETRY_LOG_FORMAT=json` (production). Human-readable default (development).

---

## 9. File Structure

**New files:**
```
web/api_utils.py              — envelope helpers, request_id hook
web/rate_limit.py             — @rate_limit + Lua sliding window
web/pagination.py             — paginate(), cursor encode/decode
web/idempotency.py            — @idempotent + Redis cache
web/validation.py             — @validate_body, @validate_params
web/logging_setup.py          — RequestIdFilter, setup_logging()
web/schemas/                  — Pydantic schemas per domain
web/routes/api_v1_data.py     — v1 data endpoints
web/routes/api_v1_account.py  — GDPR endpoints
alembic/versions/010_gdpr_account.py
tasks/gdpr_tasks.py           — export + purge Celery tasks
tests/test_api_utils.py
tests/test_rate_limit.py
tests/test_pagination.py
tests/test_idempotency.py
tests/test_validation.py
tests/test_api_v1_data.py
tests/test_api_v1_account.py
tests/test_gdpr_tasks.py
tests/test_legacy_proxy.py
```

**Modified**: `app.py`, `config.py`, `auth.py`, `teams.py`, `jobs.py`, `batch.py`, `versioning.py`, `workspaces.py`, `api_data.py`.

---

## 10. Testing Strategy

~180 new tests across 9 test files:

| Test File | Tests | Coverage |
|-----------|-------|----------|
| test_api_utils.py | 15 | Envelope, error codes, request_id, meta |
| test_rate_limit.py | 25 | Lua script, 5 tiers, 429, Retry-After, IP vs user |
| test_pagination.py | 20 | Cursor round-trip, keyset SQL, asc/desc, empty, max limit |
| test_idempotency.py | 20 | Miss/hit, concurrent lock, 5xx skip, TTL, workspace scope |
| test_validation.py | 20 | Valid/invalid, all-errors, types, query params, nested |
| test_api_v1_data.py | 30 | All v1 data endpoints with envelope + pagination |
| test_api_v1_account.py | 20 | Export, deletion, cancel, profile, re-verification |
| test_gdpr_tasks.py | 15 | Export ZIP, GPS precision, purge window, cascade |
| test_legacy_proxy.py | 15 | Deprecation headers, Sunset, body equivalence, Link |

All tests use Flask test client with mocked PG/Redis.
