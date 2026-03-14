# CLAUDE.md

Motorsport telemetry analysis SaaS — Python Flask API + Next.js frontend. Ingests RaceChrono/RaceBox CSV from kart and car sessions. Multi-tenant with workspace isolation, Stripe billing, Celery async processing.

## Scope Discipline (MANDATORY)

- **Only touch the exact code the user asks about.** No drive-by refactors, no "improvements" to surrounding code, no adding comments or renaming variables in adjacent functions.
- **One question at a time when uncertain.** If you're unsure about scope or intent, ask exactly ONE question, wait for the answer, then act. Never dump a list of clarifications.
- If you spot something else that looks wrong, mention it briefly AFTER completing the requested change — never bundle it into the same edit.

## Ship It Live (MANDATORY)

- **Every code change must be verified stable and deployed live.** Do not consider a task done until the fix is running in production.
- **Backend**: run relevant tests → `scp` changed files to VPS → `docker compose build api && up -d api` → verify `curl https://api.lap-coach.racing/healthz` returns OK.
- **Frontend**: `npm run build` (catch errors) → `npm run cf:deploy` → confirm Cloudflare Workers deployment succeeds.
- **Never stop at "code is written".** The full cycle is: fix → test → deploy backend → deploy frontend → verify live.

## Quick Reference

```bash
# ── Backend (Python) ──────────────────────────
pytest telemetry_tool/tests/                       # all backend tests
pytest telemetry_tool/tests/test_streaming_ingest.py -k "test_chunk_cache_flush"  # single test
pytest telemetry_tool/tests/test_upload_sync.py -v                              # sync upload endpoint tests
pytest telemetry_tool/tests/test_data_api_v2.py -v                              # data API endpoint tests
pytest telemetry_tool/tests/test_re_port_correctness.py -v                      # pipeline correctness tests
pytest kart_envelope/tests/                        # kart envelope tests
python telemetry_tool/main.py --serve              # Flask dev server (localhost:5000)
python telemetry_tool/main.py data/raw/SESSION.csv # CLI single-file processing
python -m kart_envelope analyze <csv> --metadata <meta.json>
pip install -r requirements.txt                    # deps (note: gunicorn, resend, stripe NOT in file — Docker-only)

# ── Frontend (Next.js) ───────────────────────
cd lap-website && npm install
npm run dev                                        # Next.js dev (localhost:3000)
npm run build                                      # local build
npm run cf:deploy                                  # build + deploy to Cloudflare Workers
npm run lint && npm run test && npm run build       # CI pipeline
npx playwright test                                # E2E tests

# ── Docker (local dev) ───────────────────────
docker compose up -d                               # postgres:16 + redis:7 + 2 celery workers
docker compose -f docker-compose.prod.yml up -d    # full prod stack (+ caddy + api)

# ── Database ─────────────────────────────────
alembic upgrade head                               # run all migrations (16 total)
python scripts/migrate_sqlite_to_pg.py             # one-time SQLite→PG migration

# ── PyInstaller ──────────────────────────────
pyinstaller telemetry_tool.spec --clean --noconfirm
```

No linter config for Python. No `pyproject.toml` or `Makefile`.

## Architecture Overview

### System Topology

```
Browser → Cloudflare Workers (Next.js via OpenNext)
                ↓ CORS
         Caddy (TLS) → Gunicorn → Flask API
                                    ├── PostgreSQL 16 (RLS multi-tenancy)
                                    ├── Redis 7 (rate limits, idempotency, celery broker)
                                    └── Celery workers (pipeline + default queues)
```

### Two Analysis Pipelines

**Pipeline A: `telemetry_tool/pipeline.py`** — 14-stage orchestrator (2,400+ lines)
```
CSV → GPS Filter → Derived Channels → Session Trim → Track Detection
→ Corner Detection → Resampling → Features → Reference Line
→ Physics Models → Theoretical Lap → ML/Anomaly → Scoring → Reports
```

**Pipeline B: `kart_envelope/pipeline.py`** — 18-step orchestrator
```
CSV → Normalize → Clean → Track Detection → Lap Split → Outlier Filter
→ Resample → Envelope Training → Min-Time Solve → Record Calibrate
→ Delta Map → Corner Coaching → Cause Ranking → Output
```

Both use `_safe_step()`: each step catches exceptions, logs, and returns `None` so downstream gets best partial result.

### Re-Port Architecture (feat/re-port-legacy-engine)

The SaaS telemetry system was re-ported from the working local desktop tool. The analysis pipeline runs **synchronously** in the request thread (no Celery for analysis). Previous SaaS-specific route files (`api_data.py`, `api_v1_data.py`, `analysis.py`, `comparisons.py`, `data_health.py`, `exports.py`, `batch.py`, `sessions.py`, `visualize.py`) were removed and replaced with two new endpoints: `sessions_v2.py` (upload) and `data_v2.py` (12 data-serving endpoints). The frontend chart components were gutted and rebuilt using vanilla JS modules from the working desktop tool, wrapped in React.

### Entry Points

| Mode | Command | Code |
|------|---------|------|
| Desktop .exe | double-click | `telemetry_tool/main.py` → Tkinter file picker |
| CLI | `python telemetry_tool/main.py <csv>` | same file, argparse |
| Web API | `--serve` or Docker | `telemetry_tool/web/app.py` `create_app()` factory |
| Kart envelope | `python -m kart_envelope analyze` | `kart_envelope/cli.py` |

### Flask Backend (`telemetry_tool/web/`)

- **`app.py`** — Factory with blueprints, resolves paths for dev + PyInstaller
- **`routes/sessions_v2.py`** — Synchronous upload endpoint (`POST /api/v1/sessions/upload`). Runs the full 14-stage pipeline in the request thread.
- **`routes/data_v2.py`** — 12 data-serving API endpoints: session list, detail, laps, speed-trace, gps-trace, gg-data, scores, corners, delete, compare, report download, session update.
- **`routes/`** — Other blueprints: `dashboard`, `tracks`, `api_v1_account`, `auth`, `billing`, `drivers`, `health`, `ingest`, `jobs`, `karts`, `leaderboard`, `race_strategy_v2`, `teams`, `weekends`, `workspaces`, etc.
- **Note**: Previous telemetry data routes (`api_v1_data.py`, `api_data.py`, `analysis.py`, `comparisons.py`, `data_health.py`, `exports.py`, `batch.py`, `sessions.py`, `visualize.py`) were removed in the re-port.
- **`middleware/auth.py`** — JWT verification, explicit path allowlist + `_OAUTH_PATH_RE`
- **`middleware/tenant.py`** — `X-Workspace-Id` header → RLS context via `SET LOCAL`, populates `g.workspace_id` + `g.workspace_role`
- **`schemas/`** — Pydantic v2 request/response schemas (auth, account, sessions, tracks, teams, jobs, batch, common)
- **`i18n/`** — 7 languages: de, en, es, fr, it, pt, zh
- **API infrastructure**: `api_utils.py` (envelope responses + request ID), `rate_limit.py` (Redis sliding-window, 5 tiers), `validation.py` (Pydantic decorators), `pagination.py` (keyset cursor, no OFFSET), `idempotency.py` (Redis-backed `Idempotency-Key`)
- **`templates/`** — 34+ Jinja2 templates, **`static/`** — Vanilla JS + CSS, Chart.js via CDN, dark theme

### Auth & Multi-Tenancy (`telemetry_tool/auth/`)

- **`service.py`** — Argon2id passwords, JWT HS256, single-use refresh token rotation
- **`oauth.py`** — Google OIDC + GitHub via authlib, `email_verified` check, upsert for race conditions
- **`workspace.py`** — Personal workspace auto-created on register, team workspaces, `set_workspace_context()` (SET LOCAL)
- **`teams.py`** — Create team, add/remove members, role management
- **`rbac.py`** — 4 roles (viewer < member < admin < owner), 17 permissions, `require_permission()` decorator
- **Token flow**: Access token → in-memory JS variable; Refresh token → httpOnly Secure SameSite=Lax cookie (path=/auth/refresh); Silent refresh on page load

### Celery Task System (`telemetry_tool/tasks/`)

- **`celery_app.py`** — Broker: Redis. Two queues: `pipeline` (heavy, concurrency=2), `default` (light, concurrency=4). `task_acks_late=True`.
- **`pipeline_tasks.py`** → `pipeline` queue, **`batch_tasks.py`** → `default` queue
- **`gdpr_tasks.py`** — Data export/erasure, **`job_registry.py`** — Job tracking, **`concurrency.py`** — Helpers

### Billing

- **`routes/billing.py`** — Stripe webhook at `/api/v1/billing/webhook`, verifies `Stripe-Signature`
- **Frontend plans** (`lap-website/src/lib/stripe-billing.ts`): PERFORMANCE (monthly/annual), PRO RACER (monthly/annual); B2B: TRACK ESSENTIAL, CIRCUIT PRO, CIRCUIT ENTERPRISE

### Next.js Frontend (`lap-website/`)

- **Next.js 14** + TypeScript + Tailwind CSS, deployed on **Cloudflare Workers** via OpenNext
- **State**: Zustand 5 (client), TanStack React Query 5 (server)
- **3D/Animation**: Three.js + React Three Fiber, GSAP, Lenis smooth scroll, Howler.js audio
- **Auth**: `src/lib/auth.ts` (`authFetch()` → `$NEXT_PUBLIC_API_URL/auth/*`), `src/lib/auth-store.ts` (in-memory tokens, NOT localStorage)
- **API client**: `src/lib/api-client.ts` (`apiFetch()` → `$NEXT_PUBLIC_API_URL/api/v1/*`), standard `{ok, data, error, meta}` envelope
- **Route groups** (App Router):
  - `(auth)/` — login, register, verify-email
  - `(free-report)/` — public free analysis tool
  - `(marketing)/` — 20+ pages: pricing, product, teams, circuits, etc.
  - `app/` — authenticated dashboard, sessions, tracks, compare, analytics, etc.
- **Middleware** (`src/middleware.ts`): Persona detection, UTM attribution, A/B experiments (`lap_exp_hero`, `lap_exp_pricing`, `lap_exp_cta`)
- **Vanilla JS charts**: Desktop tool's chart modules copied to `lap-website/public/js/` (19 modules: speed_trace_zoom, gps_trace, gg_explorer, chart_sync, module_manager, etc.). Wrapped in React via `src/components/app/charts/` (SpeedTraceZoom, GpsTrace, GGExplorer) using a shared `useVanillaChart` hook.
- **Distance-based hover sync**: Zustand store (`src/stores/hover-sync-store.ts`) provides cross-chart hover coordination via distance values.
- **Module shim**: `public/js/module-shim.js` rewrites API paths so vanilla JS `fetch()` calls route to the correct backend URL.
- **Tests**: Vitest (unit), Playwright (E2E in `e2e/` directory)

### Persistence

- **PostgreSQL 16** — 16 Alembic migrations. RLS policies auto-filter all 44 workspace-scoped tables. Per-request connections (no pool — avoids Gunicorn pre-fork exhaustion).
- **SQLite** (`telemetry.db`) — v15 schema (`db/schema.py`), ~30 tables. Used in desktop/CLI mode. Migrations via `db/migrate.py` `ensure_schema()` (idempotent).
- **SQL compat** (`db/sql_compat.py`): Auto-translates SQLite syntax → PG at call time (`:name`→`%(name)s`, `?`→`%s`, `INSERT OR IGNORE`→`ON CONFLICT DO NOTHING`)
- **Parquet** — ML features via `parquet_manager.py` with file locking and dedup
- **Redis 7** — Rate limit counters, idempotency cache, Celery broker/results (24h TTL)

### INGEST_V2 Streaming Pipeline

Handles 10GB+ files with <1GB peak memory. Modules in `telemetry_tool/ingest/`:

- **Feature flag**: `TELEMETRY_INGEST_V2` env var, default ON. Set `=0` for legacy path.
- `streaming.py` (chunked reader, adaptive chunk sizing), `cache.py` (Parquet chunk cache + resume + PyArrow streaming merge), `pool.py` (bounded WriteQueue), `checksum.py` (SHA-256), `progress.py` (callbacks)
- **Routing**: `io_racechrono.py` checks flag at top of `read_racechrono_csv()` and routes accordingly
- **Key invariant**: `flush_chunk()` is idempotent (index-based), `merge_chunks()` uses PyArrow streaming writer (O(1 chunk) memory)

### Scoring

`scoring.py` (2,700 lines): Pace, Consistency, Execution, Robustness — each /25, total /100 with letter grades.

## Alembic Migrations

001 initial_schema → 002 auth_tables → 003 oauth_tables → 004-008 workspace+RLS → 009 celery_pipeline → 010 gdpr_account → 011 race_strategy → 012 karts_catalog → 013 track_sectors → 014 stints_analysis → 015 export_templates → 016 billing_columns

## Key Conventions

- **Column names**: RaceChrono headers (`"Lap #"`, `"Speed (m/s)"`) preserved through pipeline; snake_case mapping at feature schema boundary
- **Graceful degradation**: Pipeline steps never crash the pipeline (`_safe_step()` catches, logs, returns `None`)
- **In-place coercion**: Streaming pipeline does numeric coercion in-place (no `.copy()`) for memory budget
- **Import paths**: `conftest.py` files add project root to `sys.path` — no package install needed
- **PyInstaller**: `web/app.py`, `web/config.py` handle `sys._MEIPASS`; `path_manager.py` resolves base dir for frozen builds
- **API responses**: Standard envelope `{ok, data, error, meta}`. File uploads expose `file_name` only, never full path.
- **Auth routes are PG-only**: `_get_conn()` raises RuntimeError if `USE_PG` not set
- **RLS context**: `SET LOCAL` scoped to transaction — resets if `conn.commit()` happens mid-request

## Environment Variables

### Backend (Flask API)

| Variable | Default | Purpose |
|----------|---------|---------|
| `USE_PG` | `"0"` (OFF) | Use PostgreSQL instead of SQLite |
| `AUTH_REQUIRED` | `"0"` (OFF) | Require JWT auth on all routes |
| `TELEMETRY_PG_URL` | `postgresql://telemetry:telemetry@localhost:5432/telemetry` | PG connection string |
| `TELEMETRY_DB_PATH` | `telemetry.db` | SQLite path (when USE_PG=0) |
| `TELEMETRY_SECRET_KEY` | `"telemetry-local-dev-key"` | Flask secret |
| `TELEMETRY_JWT_SECRET` | (required when AUTH_REQUIRED=1) | JWT signing key |
| `TELEMETRY_HOST` | `"127.0.0.1"` | Flask bind address |
| `TELEMETRY_PORT` | `"5000"` | Flask port |
| `TELEMETRY_DEBUG` | `"0"` | Flask debug mode |
| `TELEMETRY_INGEST_V2` | `"1"` (ON) | Streaming ingest feature flag |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `CELERY_BROKER_URL` | (from REDIS_URL) | Celery broker |
| `CORS_ALLOWED_ORIGINS` | `""` (empty) | Comma-separated allowlist; explicit origins required in production |
| `RATE_LIMIT_ENABLED` | `"1"` | Redis-based rate limiting |
| `STRIPE_SECRET_KEY` | — | Stripe API key |
| `STRIPE_WEBHOOK_SECRET` | — | Stripe webhook signature |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | — | Google OAuth |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | — | GitHub OAuth |

### Frontend (Next.js)

| Variable | Purpose |
|----------|---------|
| `NEXT_PUBLIC_API_URL` | Backend API base URL (e.g. `https://api.lap-coach.racing`) |

## Production Deployment

- **Domain**: `api.lap-coach.racing` (API), `lap-coach.racing` / `www.lap-coach.racing` (frontend)
- **VPS**: Hetzner `46.225.227.24`, SSH `root@46.225.227.24`
- **Deploy path**: `/opt/lap-api/` — Caddyfile, docker-compose.prod.yml, .env.production
- **Stack**: Docker Compose — Caddy (TLS) → Gunicorn (4 workers) → Flask; PG 16; Redis 7; Celery
- **Frontend**: Cloudflare Workers via `npm run cf:deploy` in `lap-website/`
- **API deploy**: `scp` files → `docker compose build api && docker compose up -d api`
- **Health**: `GET /healthz` checks DB, Redis, Celery — returns 200 or 503
- **Backups**: Daily `pg_dump` at 3 AM UTC, 7-day retention, `/opt/lap-api/backups/`

## Gotchas

- `gunicorn`, `resend`, `stripe` are **not** in `requirements.txt` — installed only in Dockerfile. Local dev may miss these.
- `psutil` used by `ingest/streaming.py` but not in `requirements.txt`.
- Frontend calls backend directly via CORS — no Next.js API rewrites (Cloudflare Workers don't forward POST bodies through rewrites).
- `SET LOCAL` for RLS resets on mid-request `conn.commit()` — current routes don't trigger this but be cautious adding new ones.
- Auth token stored in-memory JS (NOT localStorage) — page refresh requires silent refresh via httpOnly cookie.
- `docs/deployment.md` is outdated (references nginx/Vercel) — this CLAUDE.md and the Docker configs are the source of truth.
- Alembic migrations 004-008 (workspace/RLS) may not be applied in prod — verify with `alembic current`.
- **Docker deploy requires `build`, not just `restart`**: API source code is `COPY`'d into the Docker image at build time — there are NO bind mounts for source files. `scp` + `docker compose restart` does NOTHING because the container still runs the old image. The correct deploy sequence is: `scp files → docker compose -f docker-compose.prod.yml build api && docker compose -f docker-compose.prod.yml up -d api`. NEVER use `restart` alone after updating source files.

## Test Fixtures

- `test_db` — In-memory SQLite with full schema via `ensure_schema()`
- `seeded_db` — Sample driver, track, two sessions with laps and scores
- `synthetic_oval_laps` (kart_envelope) — Physics-realistic 500m oval, 3 laps
- `known_envelope` / `oval_geometry` — Pre-built envelope + track geometry for solver tests
