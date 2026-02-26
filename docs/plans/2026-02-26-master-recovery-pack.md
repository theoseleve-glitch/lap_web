# Master Recovery Pack — Telemetry Analysis Platform

> **Tiger Team Deliverable** | Generated 2026-02-26
> Covers: Triage, Architecture, Merge/Release, Coverage, Security, First 20 PRs

---

## 1. CURRENT STATE TRIAGE + FORENSICS

### 1.1 Repo State Map

| Metric | Value |
|--------|-------|
| **Active branch** | `master` (230 commits) |
| **Stale branches** | `main` (1 commit — GitHub "Add files via upload"), `feat/backend-saas-phase1` (merged into master) |
| **Python files** | 258 |
| **JavaScript files** | 62 (vanilla JS, no framework) |
| **HTML templates** | 41 Jinja2 |
| **CSS files** | 10 |
| **Test files** | 65 |
| **Tests collected** | 960 (telemetry_tool) + 42 (kart_envelope) = **1,002 total** |
| **Route files** | 29 (in `web/routes/`) |
| **Registered blueprints** | ~27 (17 legacy + 10 SaaS) |
| **Schema tables (SQLite)** | 48 |
| **Schema tables (PG Alembic)** | ~57 (across 10 migrations) |
| **Plan documents** | 37 (in `docs/plans/`) |
| **Git tags/releases** | **0** |
| **CI/CD pipeline** | **None** |
| **Dockerfile** | **None** |
| **`.env` / `.env.example`** | **None** |
| **`pyproject.toml` / `Makefile`** | **None** |
| **Remote** | `origin` → `github.com/theoseleve-glitch/tele8tool.git` |

### 1.2 Branch Topology — Critical Issue

```
main ─── (1 commit: "Add files via upload")     ← ORPHAN, unrelated history
master ─ (230 commits: all development work)     ← TRUE trunk
feat/backend-saas-phase1 ─ (merged into master)  ← STALE, can delete
```

**Problem**: `main` and `master` have **unrelated histories**. `git merge master` from `main` fails with `refusing to merge unrelated histories`. GitHub likely shows `main` as default branch with zero content.

**Resolution** (see Section 4): Force-update `main` to match `master`, then delete `master`.

### 1.3 Test Suite Health

**Results** (2026-02-26): **724 passed, 1 failed, 11 skipped** (32s) + 42 kart_envelope passed

**Failure**: `test_rate_limit.py::TestRedisUnavailable::test_redis_error_allows_request`
- **Root cause**: Global logger pollution. `setup_logging()` attaches `RequestIdFilter` and `%(request_id)s` format to the **root logger**. When a test creates a minimal Flask app (without `setup_logging`), the global format persists from a prior `create_app()` call. The rate limiter's `logger.warning()` fires with the `%(request_id)s` format but without the filter having run → `KeyError: 'request_id'`.
- **Fix**: Either (a) scope logging setup to app logger instead of root, or (b) ensure `RequestIdFilter` handles the case where it hasn't been called by using `%(request_id)s` with `getattr(record, 'request_id', '-')` at format time (already done in `JsonFormatter`, but not in the human-readable `logging.Formatter`).

**11 skipped**: PG-only tests that require `TELEMETRY_PG_URL` env var (expected in SQLite-only dev).

### 1.4 Uncommitted Work (7 files)

7 modified files (not committed):
- `scoring.py` — Detrended consistency "only if it helps" guard
- `corner_replay.css`, `main.css` — UI polish
- `corner_replay_cockpit.js`, `corner_replay_map.js` — Map enhancements
- `visualize.js` — Chart fix
- `session_detail.html` — Template cleanup (-215 lines)

~80 untracked files: screenshots, `.flask_log`, `.flask_pid`, `.playwright-mcp/`, plan docs.

### 1.5 Dual Database — Schema Drift

The platform runs in two modes:
1. **SQLite** (desktop/dev) — `db/schema.py` with `ensure_schema()` (48 tables, SCHEMA_VERSION=24)
2. **PostgreSQL** (SaaS) — `alembic/versions/` with 10 migrations (001-010)

**Drift evidence**:
- SQLite has tables PG lacks: `race_configs`, `race_drivers`, `race_stints`, `race_windows`, `race_messages`, `race_neutralizations`, `race_rivals`, `race_rival_events`, `race_pit_stops`, `stint_analysis`, `predefined_tracks`, `predefined_karts`, `predefined_track_coords`, `karts`, `track_sectors`, `export_templates`
- PG has tables SQLite lacks: `users`, `refresh_tokens`, `oauth_accounts`, `workspaces`, `teams`, `team_members`, `workspace_invitations`, `batch_jobs`, `data_exports`
- SQL compat layer (`db/sql_compat.py`) translates `?` → `%s`, `:name` → `%(name)s`, `INSERT OR IGNORE` → `ON CONFLICT DO NOTHING` at runtime
- Some routes use raw `?` params (found and fixed one in `api_v1_data.py`), others use `:name` — inconsistent

### 1.6 Security Surface — Stop the Bleeding

| Issue | Severity | Evidence |
|-------|----------|----------|
| **0 auth decorators across 29 route files** | CRITICAL | `grep -c "require_auth\|login_required" routes/*.py` = 0. Auth is inline `getattr(g, "user_id", None)` checks — easy to miss |
| **No CSRF protection** | CRITICAL | No `CSRFProtect`, no CSRF tokens in forms. All POST forms vulnerable |
| **No CORS configuration** | HIGH | No `flask-cors`, no `Access-Control` headers. SaaS mode with API clients needs explicit CORS |
| **Tenant middleware only on `/api/v1/`** | HIGH | Legacy `/api/` endpoints bypass workspace isolation entirely |
| **`AUTH_REQUIRED` defaults to `"0"`** | MEDIUM | Multi-tenant endpoints accessible without auth in default config |
| **No rate limiting on legacy endpoints** | MEDIUM | Rate limiting only on v1 endpoints; legacy `/api/session/` etc. unprotected |
| **No secrets management** | MEDIUM | `JWT_SECRET` defaults to `"telemetry-jwt-dev-key-change-me"`, `SECRET_KEY` defaults to `"telemetry-local-dev-key"` |
| **No input sanitization on SQL** | MEDIUM | `sql_compat.py` does regex-based translation — edge cases possible |
| **Redis fail-open in idempotency** | LOW | Fixed in Phase 4 commit `352fcfc`, but `rate_limit` also degrades silently |

### 1.7 Environment Parity

| Component | Dev (local) | Docker-compose | Production |
|-----------|-------------|----------------|------------|
| Database | SQLite file | PostgreSQL 16 | ??? |
| Cache | None | Redis 7 | ??? |
| Task queue | None | Celery (2 workers) | ??? |
| Auth | Disabled | Disabled | ??? |
| Secrets | Hardcoded defaults | Hardcoded in YAML | ??? |
| Monitoring | None | None | ??? |

**No production environment exists.** Docker-compose is the closest to prod but has hardcoded credentials and no TLS.

### 1.8 Frontend Architecture

- **Vanilla JS** (62 files) — no framework, no bundler, no minification
- **Chart.js via CDN** — no version pinning
- **`FetchHelper`** — custom wrapper around `fetch()` with retry logic
- **`/api/` endpoints** — ~40 unique API URLs called from JS
- **`/api/v1/` endpoints** — 15 data + 6 account endpoints (new, Phase 4)
- **No frontend tests** — zero JS test files
- **Separate Next.js site** (`lap-website/`) — marketing/sales page, React + Three.js + GSAP, completely disconnected from the Flask app

---

## 2. CONTRACT-FIRST INTEGRATION LAYER

### 2.1 Current API Surface

**Legacy endpoints** (`/api/`): 40+ routes across `api_data.py` and inline in templates
- URL pattern: `/api/session/<id>/speed_trace` (snake_case, singular)
- Response: raw JSON (no envelope, no request_id, no pagination metadata)
- Auth: none
- Rate limiting: none
- Validation: none

**v1 endpoints** (`/api/v1/`): 21 routes
- URL pattern: `/api/v1/sessions/<id>/speed-trace` (kebab-case, plural)
- Response: `{"ok": true, "data": {...}, "meta": {"request_id": "..."}}`
- Auth: inline `getattr(g, "user_id", None)` guard
- Rate limiting: Redis sliding window (5 tiers)
- Validation: Pydantic v2 schemas

### 2.2 Proposed Contract

**Target**: All new frontend work uses `/api/v1/` exclusively. Legacy `/api/` gets deprecation headers (already added in Phase 4).

**Missing v1 coverage** (endpoints the FE calls but v1 doesn't wrap):

| Legacy endpoint | FE usage | v1 equivalent needed |
|-----------------|----------|---------------------|
| `/api/session/<id>/cross_session` | `chart_sync.js` | `/api/v1/sessions/<id>/cross-session` |
| `/api/session/<id>/sectors` | `focus_tools.js` | `/api/v1/sessions/<id>/sectors` |
| `/api/session/<id>/sector_times` | `focus_tools.js` | `/api/v1/sessions/<id>/sector-times` |
| `/api/session/<id>/delta` | `chart_sync.js` | `/api/v1/sessions/<id>/delta` |
| `/api/session/<id>/corner-metrics` | `focus_tools.js` | `/api/v1/sessions/<id>/corner-metrics` |
| `/api/session/<id>/corner-coaching` | `corner_map_view.js` | `/api/v1/sessions/<id>/corner-coaching` |
| `/api/session/<id>/corner-replay-data` | `corner_replay.js` | `/api/v1/sessions/<id>/corner-replay` |
| `/api/session/<id>/badges` | `session_badges.js` | `/api/v1/sessions/<id>/badges` |
| `/api/session/<id>/driving-style` | templates | `/api/v1/sessions/<id>/driving-style` |
| `/api/session/<id>/brake-precision` | `focus_tools.js` | `/api/v1/sessions/<id>/brake-precision` |
| `/api/session/<id>/energy-balance` | `focus_tools.js` | `/api/v1/sessions/<id>/energy-balance` |
| `/api/session/<id>/fitness` | `focus_tools.js` | `/api/v1/sessions/<id>/fitness` |
| `/api/session/<id>/consistency-heatmap` | `focus_tools.js` | `/api/v1/sessions/<id>/consistency-heatmap` |
| `/api/session/<id>/comparison-matrix` | `focus_tools.js` | `/api/v1/sessions/<id>/comparison-matrix` |
| `/api/session/<id>/brake-throttle-tradeoff` | `focus_tools.js` | `/api/v1/sessions/<id>/brake-throttle-tradeoff` |
| `/api/session/<id>/corner-positions` | templates | `/api/v1/sessions/<id>/corner-positions` |
| `/api/sessions/search` | templates | `/api/v1/sessions/search` |
| `/api/sessions/browse` | templates | `/api/v1/sessions/browse` |
| `/api/sessions/recent` | templates | `/api/v1/sessions/recent` |
| `/api/files/upload` | `analyze_form.js` | `/api/v1/files/upload` |
| `/api/drivers/list` | templates | `/api/v1/drivers` |
| `/api/drivers/normalize` | `analyze_form.js` | `/api/v1/drivers/normalize` |
| `/api/track/<id>/key-corners` | `corner_replay.js` | `/api/v1/tracks/<id>/key-corners` |
| `/api/annotations/*` | templates | `/api/v1/annotations/*` |
| `/api/dashboards/*` | templates | `/api/v1/dashboards/*` |
| `/api/data-health` | templates | `/api/v1/data-health` |
| `/api/predefined-tracks` | `analyze_form.js` | `/api/v1/predefined-tracks` |
| `/api/predefined-karts` | `analyze_form.js` | `/api/v1/predefined-karts` |
| `/api/race-strategy/*` | templates | `/api/v1/race-strategy/*` |
| `/api/meteo/*` | templates | `/api/v1/meteo/*` |
| `/api/rivals/*` | templates | `/api/v1/rivals/*` |

**~30 additional v1 endpoints needed** to achieve full parity.

### 2.3 Response Envelope Standard (already implemented)

```python
# Success
{"ok": True, "data": {...}, "meta": {"request_id": "uuid", "deprecated": False}}

# Error
{"ok": False, "error": {"code": "NOT_FOUND", "message": "..."}, "meta": {"request_id": "uuid"}}

# Paginated
{"ok": True, "data": [...], "meta": {"request_id": "uuid", "cursor": "next_cursor", "has_more": True}}
```

---

## 3. INTEGRATED TARGET ARCHITECTURE

### 3.1 Current State Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    FRONTEND (Browser)                    │
│  41 Jinja2 templates + 62 vanilla JS files + Chart.js   │
│  FetchHelper → /api/ (legacy, no auth/envelope)         │
│              → /api/v1/ (new, envelope+rate limit)      │
└───────────────────────┬─────────────────────────────────┘
                        │ HTTP
┌───────────────────────▼─────────────────────────────────┐
│                    FLASK APP (app.py)                    │
│  create_app() factory │ 27 blueprints │ WSGI            │
│  Middleware: tenant (v1 only), request_id, logging       │
│  NO: auth decorator, CSRF, CORS                         │
├─────────────────────────────────────────────────────────┤
│  Routes: 29 files │ ~150 endpoints                      │
│  Legacy: raw SQL via get_db_connection()                 │
│  v1: Pydantic validation + api_response envelope        │
├─────────────────────────────────────────────────────────┤
│  Pipeline: 14-stage CSV→Features→Scoring→Reports        │
│  Scoring: 4D × 25pt system (Pace/Consistency/Exec/Rob)  │
│  Ingest: Streaming V2 (chunked, <1GB peak for 10GB)     │
├──────────────┬──────────────┬───────────────────────────┤
│   SQLite     │  PostgreSQL  │  Redis                    │
│   (desktop)  │  (SaaS/PG)  │  (rate limit, idempotency)│
│   48 tables  │  ~57 tables  │  Celery broker            │
│   schema.py  │  Alembic 010 │                           │
└──────────────┴──────────────┴───────────────────────────┘
                                        │
                              ┌─────────▼─────────┐
                              │  Celery Workers    │
                              │  pipeline queue    │
                              │  default queue     │
                              └────────────────────┘
```

### 3.2 Target State (6-month)

```
┌─────────────────────────────────────────────────────────┐
│                    FRONTEND (Browser)                    │
│  SAME 41 templates + 62 JS files (incremental migration)│
│  FetchHelper upgraded: always use /api/v1/              │
│  + CSRF token in all forms                              │
└───────────────────────┬─────────────────────────────────┘
                        │ HTTPS
┌───────────────────────▼─────────────────────────────────┐
│               REVERSE PROXY (nginx/caddy)               │
│  TLS termination │ CORS headers │ Rate limiting (L7)    │
├─────────────────────────────────────────────────────────┤
│                    FLASK APP (Gunicorn)                  │
│  create_app() factory │ all blueprints                  │
│  Middleware: auth_required decorator (all routes)        │
│              tenant (all /api/ routes)                   │
│              request_id, structured logging, CSRF        │
├─────────────────────────────────────────────────────────┤
│  /api/v1/ — FULL coverage (all FE endpoints)            │
│  /api/    — Deprecated, 301 redirects → /api/v1/        │
│  /        — HTML pages (Jinja2, auth-gated)             │
├──────────────┬──────────────┬───────────────────────────┤
│   SQLite     │  PostgreSQL  │  Redis                    │
│   (desktop   │  (SINGLE     │  (sessions, cache,        │
│    .exe      │   source of  │   rate limit, celery)     │
│    mode)     │   truth)     │                           │
│   schema.py  │  Alembic     │                           │
│   READ-ONLY  │  (unified)   │                           │
└──────────────┴──────────────┴───────────────────────────┘
                                        │
                              ┌─────────▼─────────┐
                              │  Celery Workers    │
                              │  pipeline queue    │
                              │  default queue     │
                              │  beat (GDPR purge) │
                              └────────────────────┘
                              ┌────────────────────┐
                              │  GitHub Actions CI  │
                              │  pytest → lint →    │
                              │  build → deploy     │
                              └────────────────────┘
```

### 3.3 Key Architectural Decisions

1. **No frontend rewrite** — keep vanilla JS + Jinja2. Incrementally update `FetchHelper` to prefer `/api/v1/`.
2. **PostgreSQL becomes single source of truth** — desktop .exe mode continues with SQLite but all new SaaS features are PG-only.
3. **Auth decorator replaces inline checks** — create `@require_auth` that sets `g.user_id` and `g.workspace_id`, use on all `/api/` routes.
4. **Feature flags via env vars** — continue existing pattern (`AUTH_REQUIRED`, `USE_PG`, `RATE_LIMIT_ENABLED`).
5. **No ORM** — keep raw SQL with `sql_compat.py` translation layer. Add a thin repository layer for common queries.

---

## 4. MERGE + RELEASE RECOVERY PLAN

### Phase 0: Emergency Branch Fix (Day 1)

| Step | Command | Rationale |
|------|---------|-----------|
| 1. Stash uncommitted work | `git stash push -m "uncommitted-fe-work"` | Preserve 7 modified files |
| 2. Force-update main | `git checkout main && git reset --hard master` | Make `main` = `master` (all 230 commits) |
| 3. Push main | `git push --force-with-lease origin main` | Update GitHub default branch |
| 4. Delete stale branch | `git branch -d feat/backend-saas-phase1` | Already merged |
| 5. Delete local master | `git checkout main && git branch -d master` | Single trunk going forward |
| 6. Restore stash | `git stash pop` | Get uncommitted work back |
| 7. Commit FE work | `git add -p && git commit` | Selective commit of the 7 files |

**Outcome**: Single `main` branch with full history. `master` gone.

### Phase 1: CI Foundation (Week 1)

1. **`.github/workflows/ci.yml`** — pytest on push/PR, Python 3.11+
2. **`.env.example`** — document all 20+ env vars with safe defaults
3. **`Dockerfile`** — multi-stage build (deps → app → gunicorn)
4. **`docker-compose.prod.yml`** — with secrets, health checks, restart policies
5. **`.gitignore` update** — add screenshots, `.flask_*`, `.playwright-mcp/`

### Phase 2: Security Hardening (Week 2-3)

1. **`@require_auth` decorator** — centralized auth check, sets `g.user_id` + `g.workspace_id`
2. **CSRF protection** — `flask-wtf` CSRFProtect for form routes
3. **CORS configuration** — `flask-cors` with explicit allowed origins
4. **Secrets rotation** — fail if `JWT_SECRET` or `SECRET_KEY` are defaults in production
5. **Tenant middleware expansion** — apply to all `/api/` routes, not just `/api/v1/`

### Phase 3: Schema Unification (Week 3-4)

1. **Audit** — generate diff between SQLite 48 tables and PG Alembic tables
2. **Migration 011-015** — add missing PG tables (race_strategy, karts, predefined catalogs, etc.)
3. **Schema version sync** — SQLite SCHEMA_VERSION should match Alembic head
4. **Test dual-path** — every migration tested against both SQLite (`ensure_schema`) and PG (`alembic upgrade`)

### Phase 4: API Completeness (Week 4-6)

1. **v1 endpoint batch 2** — 15 more session endpoints (sectors, delta, corner-metrics, badges, etc.)
2. **v1 endpoint batch 3** — search/browse/recent, drivers, annotations, dashboards
3. **v1 endpoint batch 4** — race-strategy, meteo, predictions, data-health
4. **FetchHelper upgrade** — `API_VERSION` constant, all calls route through `/api/v1/`
5. **Deprecation sunset** — legacy `/api/` returns 301 redirects to v1 equivalents

### Phase 5: Observability + Reliability (Week 6-8)

1. **Structured logging** — already built (Phase 4), needs deployment config
2. **Health check endpoint** — `/healthz` (DB ping, Redis ping, Celery ping)
3. **Metrics** — request latency, error rates, queue depth (Prometheus or StatsD)
4. **Error tracking** — Sentry integration
5. **Backup strategy** — PG `pg_dump` on cron, Parquet file backup

### Phase 6: First Release (Week 8)

1. **Tag `v1.0.0`** — semantic versioning starts
2. **Release notes** — auto-generated from conventional commits
3. **Deployment runbook** — step-by-step for first production deploy
4. **Rollback plan** — feature flags for every new feature, instant rollback

---

## 5. WORKFLOW COVERAGE MATRIX

### 5.1 End-to-End Workflows

| Workflow | Steps | Current Coverage | Gap |
|----------|-------|------------------|-----|
| **CSV Upload → Analysis** | Upload → Ingest → Pipeline → Score → Display | Full (tested, 50 ingest tests) | No auth on upload |
| **Session Browse** | List → Filter → Detail → Charts | Partial (FE works, no v1 API) | Missing v1 search/browse |
| **Corner Replay** | Select session → Load corners → Play replay | Full FE, no v1 API | No v1 corner endpoints |
| **Driver Profile** | List → Select → Progression → Style | Full FE | No v1 driver endpoints |
| **Track Management** | List → Detail → Rename → Records | Full FE | No v1 track CRUD |
| **Race Strategy** | Create → Config → Go Live → Manage | Full FE | No v1 race-strategy endpoints |
| **GDPR Export** | Request → Process → Download → Delete | v1 API built | No FE, no Celery beat |
| **Team Management** | Create → Invite → Accept → Scope | v1 API built | No FE, workspace isolation partial |
| **User Registration** | Register → Verify → Login → OAuth | API built | No FE registration flow |
| **Batch Reanalysis** | Select → Dispatch → Monitor → Complete | Full (Celery tasks) | No progress UI |

### 5.2 Test Coverage by Component

| Component | Test Files | Tests | Coverage Quality |
|-----------|-----------|-------|------------------|
| Pipeline/Scoring | 8 | ~200 | Strong |
| Streaming Ingest | 1 | 50 | Strong |
| Auth/OAuth | 2 | ~60 | Good |
| API v1 (data) | 1 | ~30 | Good |
| API v1 (account) | 1 | 13 | Good |
| GDPR Tasks | 1 | 11 | Good |
| Schemas (Pydantic) | 1 | 25 | Good |
| Phase 4 Integration | 1 | 14 | Good |
| DB Schema/Migration | 3 | ~30 | Moderate |
| Celery Tasks | 2 | ~20 | Moderate |
| Legacy API Routes | 0 | 0 | **NONE** |
| Frontend (JS) | 0 | 0 | **NONE** |
| Race Strategy | 0 | 0 | **NONE** |
| End-to-End | 0 | 0 | **NONE** |

---

## 6. COMPLIANCE + SECURITY + RELIABILITY PACK

### 6.1 GDPR Compliance Status

| Requirement | Status | Evidence |
|-------------|--------|----------|
| Data export | BUILT | `tasks/gdpr_tasks.py::export_user_data` — ZIP with 6 JSON files |
| GPS precision reduction | BUILT | `_reduce_gps_precision()` — 3 decimal places (~100m) |
| Soft delete (30-day grace) | BUILT | `api_v1_account.py::delete_account` — sets `deleted_at` |
| Cancel deletion | BUILT | `api_v1_account.py::cancel_deletion` — clears `deleted_at` |
| Hard purge | BUILT | `tasks/gdpr_tasks.py::purge_deleted_accounts` — cascading delete |
| Celery beat scheduling | NOT WIRED | Task exists but beat schedule not configured |
| Audit log | NOT BUILT | No record of who accessed what data |
| Consent tracking | NOT BUILT | No cookie consent, no data processing agreements |
| Data retention policy | NOT DOCUMENTED | No documented retention periods |

### 6.2 Security Checklist

| Control | Status | Priority |
|---------|--------|----------|
| Authentication decorator | MISSING | P0 — inline checks are error-prone |
| CSRF protection | MISSING | P0 — all POST forms vulnerable |
| CORS configuration | MISSING | P1 — needed for SaaS mode |
| Input validation (all routes) | PARTIAL | P1 — only v1 routes have Pydantic |
| SQL injection prevention | PARTIAL | P1 — `sql_compat.py` + parameterized queries, but inconsistent |
| Rate limiting (all routes) | PARTIAL | P2 — only v1 routes |
| Secrets management | MISSING | P2 — hardcoded defaults in source |
| TLS/HTTPS | MISSING | P2 — no reverse proxy config |
| Dependency scanning | MISSING | P2 — no `pip-audit` or Dependabot |
| Session management | MISSING | P2 — no session timeout, no revocation |
| Logging (security events) | PARTIAL | P3 — structured logging built, not deployed |
| Penetration testing | NOT DONE | P3 |

### 6.3 Reliability

| Control | Status |
|---------|--------|
| Health check endpoint | MISSING |
| Graceful shutdown | PARTIAL — pipeline `_safe_step()` catches errors |
| Database backups | MISSING |
| Connection pooling | MISSING — new connection per request |
| Circuit breaker (Redis) | PARTIAL — fail-open on rate_limit and idempotency |
| Queue depth monitoring | MISSING |
| Memory budget enforcement | BUILT — streaming ingest <1GB peak |
| Error tracking (Sentry) | MISSING |

---

## 7. FIRST 20 PRs TO OPEN

Listed in dependency order. Each PR is independently mergeable.

### Tier 0: Stop the Bleeding (Week 1)

| # | PR Title | Files | Description | Gate |
|---|----------|-------|-------------|------|
| 1 | **fix: force-update main branch to match master** | — | `git reset --hard master` on main, push, delete master. Single trunk. | Manual |
| 2 | **chore: add .gitignore for generated files** | `.gitignore` | Add: `*.png`, `.flask_*`, `.playwright-mcp/`, `__pycache__/`, `*.pyc`, `.env` | CI |
| 3 | **ci: add GitHub Actions pytest workflow** | `.github/workflows/ci.yml` | Run `pytest telemetry_tool/tests/ kart_envelope/tests/` on push + PR. Python 3.11. | Passing tests |
| 4 | **chore: add .env.example with all env vars** | `.env.example` | Document all 20+ env vars from `web/config.py` with safe defaults | Review |

### Tier 1: Security Foundation (Week 2)

| # | PR Title | Files | Description | Gate |
|---|----------|-------|-------------|------|
| 5 | **feat(auth): add @require_auth decorator** | `web/decorators.py`, tests | Centralized auth check, sets `g.user_id` + `g.workspace_id`. Replaces inline `getattr` | Tests pass |
| 6 | **refactor(routes): apply @require_auth to all v1 endpoints** | `routes/api_v1_*.py` | Replace inline auth guards with decorator | Tests pass |
| 7 | **feat(security): add CSRF protection** | `web/app.py`, `base.html` | `flask-wtf` CSRFProtect, meta tag in base template, exempt JSON API routes | Tests pass |
| 8 | **feat(security): add CORS configuration** | `web/app.py`, `web/config.py` | `flask-cors` with `CORS_ORIGINS` env var, default `["http://localhost:5000"]` | Tests pass |
| 9 | **fix(secrets): fail on default secrets in production** | `web/config.py` | If `FLASK_ENV=production` and secrets are defaults, raise `RuntimeError` | Tests pass |

### Tier 2: Infrastructure (Week 2-3)

| # | PR Title | Files | Description | Gate |
|---|----------|-------|-------------|------|
| 10 | **feat(infra): add Dockerfile with multi-stage build** | `Dockerfile`, `.dockerignore` | Python 3.11-slim → install deps → copy app → gunicorn entrypoint | Docker build succeeds |
| 11 | **feat(infra): add production docker-compose** | `docker-compose.prod.yml` | Secrets via env_file, health checks, restart policies, volume mounts | `docker-compose up` works |
| 12 | **feat(health): add /healthz endpoint** | `web/routes/health.py`, `web/app.py` | Returns `{"status": "ok", "db": "ok", "redis": "ok/unavailable", "celery": "ok/unavailable"}` | Tests pass |
| 13 | **ci: add Docker build + push to CI** | `.github/workflows/ci.yml` | Build Docker image on tag push, push to GHCR | CI passes |

### Tier 3: Schema + API Completeness (Week 3-5)

| # | PR Title | Files | Description | Gate |
|---|----------|-------|-------------|------|
| 14 | **feat(schema): Alembic 011-013 — race strategy + catalogs tables** | `alembic/versions/011-013_*.py` | Add 16 missing PG tables that exist in SQLite | `alembic upgrade head` succeeds |
| 15 | **feat(api): v1 session analysis endpoints batch 2** | `routes/api_v1_data.py` | Add 15 session endpoints: sectors, delta, corner-metrics, badges, driving-style, brake-precision, energy-balance, fitness, consistency-heatmap, comparison-matrix, brake-throttle, corner-coaching, corner-replay, corner-positions, cross-session | Tests pass |
| 16 | **feat(api): v1 search/browse/drivers endpoints** | `routes/api_v1_data.py` | Add: sessions/search, sessions/browse, sessions/recent, drivers, drivers/normalize | Tests pass |
| 17 | **feat(api): v1 tracks, annotations, dashboards endpoints** | `routes/api_v1_tracks.py`, `routes/api_v1_annotations.py`, `routes/api_v1_dashboards.py` | Full CRUD for tracks, annotations, dashboards via v1 envelope | Tests pass |

### Tier 4: Observability + Polish (Week 5-6)

| # | PR Title | Files | Description | Gate |
|---|----------|-------|-------------|------|
| 18 | **feat(tenant): expand workspace isolation to all /api/ routes** | `middleware/tenant.py`, route files | Apply tenant middleware to legacy `/api/` routes, not just `/api/v1/` | Tests pass |
| 19 | **feat(logging): add request latency + error rate metrics** | `web/middleware/metrics.py` | After-request hook logs latency, status code. Optional Prometheus export. | Tests pass |
| 20 | **feat(fe): upgrade FetchHelper to prefer /api/v1/** | `static/js/fetch_helper.js` | Add `API_BASE = '/api/v1'` prefix, version header, error envelope parsing | Manual QA |

---

## Appendix A: Environment Variables (Complete)

| Variable | Default | Required for Prod | Section |
|----------|---------|-------------------|---------|
| `TELEMETRY_SECRET_KEY` | `"telemetry-local-dev-key"` | YES — must change | Flask |
| `TELEMETRY_DB_PATH` | `telemetry.db` | No (PG mode) | Database |
| `TELEMETRY_HOST` | `127.0.0.1` | YES — `0.0.0.0` | Server |
| `TELEMETRY_PORT` | `5000` | Optional | Server |
| `TELEMETRY_DEBUG` | `0` | Must be `0` | Server |
| `TELEMETRY_LOG_FORMAT` | `text` | Set `json` for prod | Logging |
| `USE_PG` | `0` | Set `1` for SaaS | Database |
| `TELEMETRY_PG_URL` | — | YES if USE_PG=1 | Database |
| `REDIS_URL` | `redis://localhost:6379/0` | YES for SaaS | Cache |
| `CELERY_BROKER_URL` | (falls back to REDIS_URL) | Optional | Queue |
| `CELERY_RESULT_BACKEND` | (falls back to REDIS_URL) | Optional | Queue |
| `AUTH_REQUIRED` | `0` | Set `1` for SaaS | Auth |
| `JWT_SECRET` | `"telemetry-jwt-dev-key-change-me"` | YES — must change | Auth |
| `GOOGLE_CLIENT_ID` | `""` | If OAuth enabled | Auth |
| `GOOGLE_CLIENT_SECRET` | `""` | If OAuth enabled | Auth |
| `GITHUB_CLIENT_ID` | `""` | If OAuth enabled | Auth |
| `GITHUB_CLIENT_SECRET` | `""` | If OAuth enabled | Auth |
| `OAUTH_REDIRECT_BASE` | `http://localhost:5000` | YES for OAuth | Auth |
| `TELEMETRY_INGEST_V2` | `1` | Optional | Ingest |
| `TELEMETRY_EXPORT_DIR` | `/tmp/telemetry_exports` | YES — persistent path | GDPR |
| `RATE_LIMIT_ENABLED` | `1` | Optional | API |

## Appendix B: File Counts by Directory

```
telemetry_tool/
├── alembic/versions/    10 migrations
├── auth/                 4 modules (service, workspace, oauth, helpers)
├── db/                   5 modules (schema, migrate, queries, sql_compat, helpers)
├── ingest/               7 modules (streaming pipeline)
├── tasks/                3 modules (celery, pipeline, gdpr)
├── tests/               65 test files
├── web/
│   ├── routes/          29 route files (~150 endpoints)
│   ├── templates/       41 Jinja2 templates
│   ├── static/js/       62 JavaScript files
│   ├── static/css/      10 CSS files
│   ├── schemas/          8 Pydantic schema files
│   └── middleware/       3 middleware modules
├── pipeline.py        2,400+ lines (14-stage orchestrator)
├── scoring.py         2,700+ lines (4D scoring engine)
└── feature_builder.py   650+ lines (ML feature extraction)
```
