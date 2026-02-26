# Backend Robustness & Compliance Overhaul — SaaS Migration Design

**Date**: 2026-02-26
**Status**: Approved
**Migration strategy**: Incremental, phased, always-working

## Decisions

| Decision | Choice |
|----------|--------|
| Deployment model | Full multi-tenant SaaS |
| Tenancy | Flexible hybrid (individual accounts + optional teams) |
| Authentication | Email/password + OAuth social login (Google, GitHub) |
| Database | PostgreSQL (self-managed or managed, cloud-agnostic) |
| Job queue | Celery + Redis |
| Infrastructure | Cloud-agnostic, containerized (Docker) |
| Migration strategy | Incremental — 5 phases, app works at each phase |
| Object storage | S3-compatible (MinIO self-hosted or cloud S3) |

---

## 1. System Architecture

```
┌─────────────────────────────────────────────────────┐
│                   CLIENTS                           │
│  (Browser SPA / Mobile / Desktop Electron)          │
└──────────────────────┬──────────────────────────────┘
                       │ HTTPS
                       ▼
┌─────────────────────────────────────────────────────┐
│              REVERSE PROXY (nginx/caddy)            │
│         TLS termination, rate limiting              │
└──────────────────────┬──────────────────────────────┘
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
┌──────────────────┐    ┌────────────────────┐
│   FLASK API      │    │   FLASK API        │
│   (Container 1)  │    │   (Container N)    │
│  Auth middleware  │    │  Auth middleware   │
│  RBAC checks     │    │  RBAC checks      │
│  Tenant scoping  │    │  Tenant scoping   │
└───────┬──────────┘    └───────┬────────────┘
        └───────────┬───────────┘
     ┌──────────────┼──────────────┐
     ▼              ▼              ▼
┌─────────┐  ┌───────────┐  ┌──────────┐
│PostgreSQL│  │   Redis   │  │S3-compat │
│  (RLS)   │  │ (cache +  │  │(CSV,     │
│          │  │  broker)  │  │ Parquet, │
│          │  │           │  │ reports) │
└─────────┘  └─────┬─────┘  └──────────┘
                    ▼
          ┌──────────────────┐
          │  CELERY WORKERS  │
          │  (Container 1-M) │
          │  Pipeline stages │
          │  Scoring engine  │
          │  Report gen      │
          └──────────────────┘
```

### Key Decisions
- **Celery + Redis**: Redis serves double duty as cache and message broker. Celery handles long-running pipelines (minutes for 10GB files) with retries, result tracking, and priority queues.
- **S3-compatible object storage**: CSVs, Parquet chunks, HTML/PDF reports move out of local filesystem. Works with MinIO (self-hosted) or any cloud S3.
- **Horizontal Flask containers**: Stateless API servers behind a load balancer. Session state in Redis, not in-process.
- **PostgreSQL with Row-Level Security**: Tenant isolation enforced at DB level, not just application code.

---

## 2. Data Model & Tenancy

### Tenant Hierarchy

```
User (account)
├── id (UUID)
├── email, password_hash, oauth_ids
├── personal workspace (implicit)
└── team_memberships[] ──┐
                         ▼
Team (optional collaboration)
├── id (UUID)
├── name, slug
├── owner_user_id
└── members[] (user_id + role)

Workspace (data isolation boundary)
├── id (UUID)
├── type: 'personal' | 'team'
├── owner_user_id OR owner_team_id
└── ALL data hangs off workspace_id
```

**Why Workspace?** A personal account IS a workspace. A team IS a workspace. Every data table gets a single `workspace_id` FK — no polymorphic conditionals. When a solo user creates a team, their data stays in personal workspace; team data goes in team workspace.

### New Identity & Access Tables

```sql
users (id, email, password_hash, display_name, avatar_url,
       email_verified, mfa_secret, created_at, updated_at, deleted_at)

oauth_connections (id, user_id→users, provider, provider_user_id,
                   access_token_enc, refresh_token_enc, expires_at)

teams (id, name, slug UNIQUE, owner_user_id→users, billing_plan,
       created_at, updated_at)

team_members (team_id→teams, user_id→users,
              role ENUM('owner','admin','member','viewer'),
              invited_at, accepted_at, PRIMARY KEY(team_id, user_id))

workspaces (id, type ENUM('personal','team'), owner_user_id→users NULL,
            owner_team_id→teams NULL, display_name, created_at,
            CHECK (owner_user_id IS NOT NULL OR owner_team_id IS NOT NULL))

audit_log (id, workspace_id, user_id, action, entity_type, entity_id,
           old_value JSONB, new_value JSONB, ip_address, user_agent,
           request_id, created_at)

refresh_tokens (id, user_id→users, token_hash, device_info,
                expires_at, revoked_at, created_at)
```

### Existing Tables — Tenant Scoping

All existing data tables gain `workspace_id UUID NOT NULL REFERENCES workspaces(id)`:

| Group | Tables |
|-------|--------|
| Core | drivers, tracks, sessions, laps, gps_traces |
| Scores | score_details, condition_phases, stint_analysis |
| Corners | corner_metrics, corner_best_practices, track_key_corners |
| Profiles | driver_profiles, driver_progression, driving_style_features, driver_badges |
| Physics | theoretical_data, reference_lines, session_sectors |
| Quality | data_health, session_tags |
| Setup | vehicle_setups, what_if_scenarios |
| Annotations | session_annotations, development_plans, plan_drill_sessions |
| Weather | session_weather, condition_markers |
| Weekends | weekends, weekend_sessions |
| Race | race_configs + all race_* tables |
| Karts | karts |
| Ingestion | ingestion_jobs |
| Dashboards | custom_dashboards, export_templates |

**Global tables** (no workspace_id): predefined_tracks, predefined_karts, predefined_track_coords, schema_version.

### Row-Level Security

```sql
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY sessions_tenant_isolation ON sessions
  USING (workspace_id = current_setting('app.current_workspace_id')::uuid);
```

Request flow:
1. Auth middleware extracts user_id from JWT
2. Tenant middleware resolves workspace_id (from header or user default)
3. Before DB query: `SET LOCAL app.current_workspace_id = 'uuid'`
4. RLS auto-filters every SELECT/INSERT/UPDATE/DELETE

### Key Invariants

| Invariant | Enforcement |
|-----------|-------------|
| Every data row belongs to exactly one workspace | NOT NULL workspace_id + FK |
| Users only see their workspace's data | RLS + application middleware |
| Drivers unique per workspace | UNIQUE(workspace_id, driver_name) |
| Tracks unique per workspace | UNIQUE(workspace_id, track_fingerprint) |
| Sessions reference valid driver + track in same workspace | FK + CHECK |
| Team owner always a member with 'owner' role | Trigger |
| Deleted users soft-deleted, data retained | deleted_at timestamp |

### Cross-Workspace Sharing

```sql
workspace_shares (id, source_workspace_id→workspaces,
                  target_workspace_id→workspaces,
                  entity_type ENUM('session','driver','track'),
                  entity_id UUID,
                  permission ENUM('view','comment'),
                  granted_by→users, granted_at, expires_at)
```

Read-only views — data stays in source workspace.

---

## 3. Authentication & Authorization

### Token Strategy

| Token | Lifetime | Storage | Transport |
|-------|----------|---------|-----------|
| Access (JWT) | 15 min | Not stored (stateless) | Authorization: Bearer header |
| Refresh | 30 days | Hashed in DB | httpOnly secure cookie |

Refresh tokens are single-use (rotated on every refresh). Revoking all refresh tokens = force logout.

### Auth Endpoints

```
POST /auth/register        — email + password → create user + workspace
POST /auth/login           — email + password → access + refresh tokens
POST /auth/refresh         — refresh cookie → new tokens
POST /auth/logout          — revoke refresh token
POST /auth/forgot-password — send reset email
POST /auth/reset-password  — token → new password
POST /auth/verify-email    — token → mark verified
GET  /auth/oauth/:provider — redirect to OAuth provider
GET  /auth/oauth/:provider/callback — exchange code → tokens
POST /auth/mfa/setup       — generate TOTP secret
POST /auth/mfa/verify      — verify TOTP, enable MFA
POST /auth/mfa/challenge   — verify during login
```

### Password Hashing

Argon2id (memory-hard): 64MB memory, 3 iterations, 1 parallelism.

### RBAC Permission Matrix

| Action | Owner | Admin | Member | Viewer |
|--------|-------|-------|--------|--------|
| View sessions/tracks/drivers | Y | Y | Y | Y |
| Upload & analyze CSV | Y | Y | Y | N |
| Edit own sessions/annotations | Y | Y | Y | N |
| Edit any session | Y | Y | N | N |
| Delete sessions/tracks | Y | Y | N | N |
| Manage drivers | Y | Y | Y(own) | N |
| Race strategy CRUD | Y | Y | Y | N |
| Invite team members | Y | Y | N | N |
| Change member roles | Y | Y | N | N |
| Delete workspace/team | Y | N | N | N |
| Billing & plan changes | Y | N | N | N |
| GDPR export | Y | N | N | N |

### Three-Layer Authorization

1. **Route decorator** (coarse): `@require_auth`, `@require_role('member')`
2. **Service-level** (object): ownership checks, business rules
3. **PostgreSQL RLS** (safety net): even buggy app code can't leak cross-tenant data

### Middleware Pipeline

```
Request → Rate limiter → CORS → Auth decode → Workspace resolver
→ DB connection + RLS setup → Request ID → Route handler
→ Audit log → Response + security headers
```

### Backward Compatibility

`AUTH_REQUIRED` config flag (default False during migration). Legacy mode creates anonymous context with default workspace.

---

## 4. API Layer Hardening

### Versioned Routes

New: `/api/v1/...` (JSON-only). Legacy routes kept alive with deprecation headers.

### Response Envelope

```json
{"ok": true, "data": {...}, "meta": {"request_id": "...", "page": 1, ...}}
{"ok": false, "error": {"code": "VALIDATION_ERROR", "message": "...", "details": [...]}, "meta": {...}}
```

### Request Validation

Pydantic v2 schemas for all request bodies. `@validate_body(Schema)` decorator.

### Idempotency Keys

Write endpoints accept `Idempotency-Key` header. Cached in Redis (24h TTL). Scoped to workspace.

Required on: POST /analyze, POST /sessions/import, POST /races, POST /teams/invite.

### Cursor Pagination

```
GET /api/v1/sessions?limit=25&cursor=eyJpZCI6MTI1fQ==
→ {"data": [...], "meta": {"next_cursor": "...", "has_more": true}}
```

### Rate Limiting (Redis sliding window)

| Tier | Limit |
|------|-------|
| Unauthenticated (auth endpoints only) | 20 req/min per IP |
| Read endpoints (per user) | 300 req/min |
| Write endpoints (per user) | 60 req/min |
| Analysis start (per user) | 5 req/hour |
| File upload (per user) | 10 req/hour |
| Pipeline (per workspace) | 20 concurrent max |

### Error Codes

Stable string enum: INVALID_CREDENTIALS, TOKEN_EXPIRED, MFA_REQUIRED, FORBIDDEN, INSUFFICIENT_ROLE, VALIDATION_ERROR, NOT_FOUND, CONFLICT, QUOTA_EXCEEDED, RATE_LIMITED, ANALYSIS_FAILED, FILE_TOO_LARGE, UNSUPPORTED_FORMAT, INTERNAL_ERROR, SERVICE_UNAVAILABLE.

### Full v1 API Surface

60+ endpoints across: Auth, Sessions, Drivers, Tracks, Analysis, Race Strategy, Teams/Workspaces, Comparisons/Analytics, Data Management/GDPR.

---

## 5. Pipeline & Job System

### Current → New

| Aspect | Current | New |
|--------|---------|-----|
| Execution | threading.Thread | Celery task chain |
| Job registry | In-memory dict (lost on restart) | Redis + PostgreSQL |
| Concurrency control | None | Per-workspace lock + queue depth |
| Retry | None | 3x exponential backoff |
| Dead letter | None | DLQ + admin replay endpoint |
| User interaction (joker) | Blocks thread 300s | Pause/resume pattern |
| Progress streaming | Poll in-memory dict | Redis pub/sub → SSE |
| Batch re-analysis | Sequential in-process | Celery group (parallel) |
| Processing versioning | None | Version stamped on every result |

### Pipeline as Celery Chain

14 stages decomposed into individual tasks chained together. Each stage:
- Loads PipelineContext from Redis
- Processes its step
- Saves updated context
- Publishes progress to Redis pub/sub

### PipelineContext

Stored in Redis (metadata) + S3 (large blobs like DataFrames as Parquet).

Fields: job_id, workspace_id, pipeline_version, stage results (S3 keys for large data, inline for small), progress tracking, interaction state.

### Joker Confirmation — Pause/Resume

Pipeline splits into pre-interaction chain (stages 1–8j) and post-interaction chain (stages 9–15). When user input is needed, first chain completes and saves state. User responds via API, which dispatches second chain. No blocked threads.

### Error Classification

| Type | Action | Example |
|------|--------|---------|
| TransientError | Retry 3x with backoff | S3 timeout, Redis reset |
| FatalError | Fail → DLQ | CSV has no GPS columns |
| InteractionRequired | Pause, notify client | Joker lap detected |
| Worker crash | reject_on_worker_lost → requeue | OOM kill |

### Concurrency & Backpressure

- Pipeline queue: Celery concurrency=2/worker, max 1 active pipeline per workspace (Redis lock)
- Queue depth: alert at 50, reject at 200
- File upload: streaming to S3, per-workspace quota, 3 concurrent uploads
- Memory: 4GB worker limit, restart after 50 tasks

### Processing Versioning

`pipeline_version` and `scoring_version` columns on sessions table. Enables selective batch re-scoring when algorithms change.

---

## 6. Observability, Security & Compliance

### Structured Logging

JSON logs with mandatory fields: timestamp, level, message, request_id, workspace_id, user_id, job_id, service, version. PII never logged (GPS coords, emails hashed).

### SLOs

| Service | Metric | Target |
|---------|--------|--------|
| API | Availability | 99.5% monthly |
| API | p95 latency (reads) | < 500ms |
| API | p95 latency (writes) | < 2s |
| API | 5xx error rate | < 1% |
| Pipeline | Success rate | > 95% |
| Pipeline | p95 completion (< 100MB) | < 5 min |
| Pipeline | p95 completion (> 1GB) | < 30 min |
| Data | Cross-tenant leakage | Zero (hard SLO) |

### Metrics (Prometheus)

API request duration/count, pipeline job counts/durations/queue depth, auth events, DB pool health, storage usage.

### Distributed Tracing (OpenTelemetry)

trace_id propagated through API → Celery task headers → DB queries. Export to any OTLP backend.

### Threat Model (STRIDE)

| Threat | Mitigation |
|--------|------------|
| Spoofing | Argon2id, JWT RS256, MFA, OAuth state param |
| Tampering | FK constraints, RLS, audit log, input validation |
| Repudiation | Audit log with user_id + timestamp + old/new values |
| Info disclosure | RLS, workspace scoping, no PII in logs, encryption |
| DoS | Rate limiting, queue limits, file size caps, backpressure |
| Privilege escalation | 3-layer RBAC, role changes audit-logged |

### GDPR Controls

| Right | Implementation |
|-------|----------------|
| Access | GET /api/v1/export/gdpr — ZIP of all user data |
| Erasure | DELETE /api/v1/account — soft delete + 30-day hard purge |
| Portability | Same GDPR export (machine-readable JSON) |
| Rectification | PATCH endpoints for profile data |
| Minimization | Only collect needed data, GPS precision reduced in exports |
| Retention | Active: indefinite. Deleted: 30d. Audit: 1y. Jobs: 90d |

### CI/CD Security

On every PR: Bandit (SAST), pip-audit + Safety (dependencies), detect-secrets, SQL injection rule, Trivy (containers). On merge: + e2e tests, SBOM generation. Weekly: Dependabot, DAST scan.

---

## 7. Testing Strategy

### Test Pyramid

| Layer | Count | Scope |
|-------|-------|-------|
| Unit | 200+ | Scoring logic, parsing, permissions, fingerprinting |
| Contract | 15-25 | API response schemas, Celery message formats |
| Integration | 50-80 | Real PG + Redis, RLS isolation, pipeline stages, API CRUD |
| E2E | 5-10 | Full user journeys (register → upload → analyze → view) |
| Property-based | 10-15 | Scoring bounds, tenant isolation, fingerprint determinism |
| Load | 3 | API throughput, pipeline concurrency, soak test |
| Chaos | 5 | Worker kill, Redis restart, PG drop, S3 latency, full disk |

### Key Test Fixtures

- `db`: Per-test PG transaction with rollback (real constraints, fast isolation)
- `redis_client`: Real Redis via testcontainers
- `s3_mock`: Mocked S3 (moto or MinIO container)
- `auth_headers`: Pre-built JWT for each role (owner/admin/member/viewer)
- `seeded_workspace`: Workspace with driver, track, 2 sessions, laps, scores

---

## 8. Phased Migration Plan

### Phase Overview

| Phase | Scope | Duration | Backward Compat |
|-------|-------|----------|-----------------|
| 1 | PostgreSQL + Auth | 4-6 weeks | Legacy routes work, auth opt-in |
| 2 | Tenancy + RBAC | 3-4 weeks | AUTH_REQUIRED=false allowed |
| 3 | Celery + Pipeline | 4-5 weeks | USE_CELERY flag, threading fallback |
| 4 | API v1 Hardening | 3-4 weeks | Legacy routes deprecated |
| 5 | Observability + Compliance | 3-4 weeks | Transparent (additive) |

### Frontend Coordination

- Backward-compatible endpoints during transition
- API versioning (/api/v1/) — legacy routes stay alive
- AUTH_REQUIRED flag — frontend adds auth when ready
- Each PR includes "Frontend Impact" section

### First 10 PRs

| # | Title | Phase | Risk | Key Files |
|---|-------|-------|------|-----------|
| 1 | Alembic + PostgreSQL schema | 1a | Low | db/, alembic/ |
| 2 | SQLite → PG data migration script | 1a | Medium | scripts/ |
| 3 | SQLAlchemy connection pool | 1a | Medium | web/app.py, web/models.py |
| 4 | Auth: registration, login, JWT | 1b | Low | auth/ |
| 5 | Auth: OAuth + email verification | 1b | Low | auth/ |
| 6 | Workspace + team model with RLS | 2 | High | db/migrations/ |
| 7 | Tenant middleware + workspace_id everywhere | 2 | High | web/middleware/, db/ |
| 8 | RBAC permission checks | 2 | Medium | auth/, web/routes/ |
| 9 | Celery setup + ingest task | 3 | Medium | celery_app.py, tasks/ |
| 10 | Full pipeline chain + SSE progress | 3 | High | tasks/, web/routes/ |

Each PR includes:
- Acceptance criteria with specific test counts
- Feature flag for rollback (USE_PG, AUTH_REQUIRED, USE_CELERY)
- Rollback plan (revert PR or flip flag)
- Frontend impact assessment
