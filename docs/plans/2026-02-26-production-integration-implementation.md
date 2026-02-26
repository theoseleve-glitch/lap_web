# Production Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild the Flask frontend as a unified Next.js app with the `lap-website` design system, harden the Flask API backend, and deploy both to production.

**Architecture:** Next.js 14 App Router serves marketing pages (existing) + product pages (new, under `/app/*`). Flask becomes a headless API at `api.lap.racing`. All 44 Jinja2 templates are rebuilt as React components. 35 Canvas visualizations reuse existing draw logic via `useCanvas` hook.

**Tech Stack:** Next.js 14, React 18, TypeScript, Tailwind CSS, React Query, React Hook Form + Zod, react-leaflet, react-chartjs-2, Framer Motion, GSAP, Zustand, Vitest, Playwright. Backend: Flask, PostgreSQL 16, Redis 7, Celery, Gunicorn, nginx, Docker.

---

## Phase 0: Emergency Fixes (Day 1)

### Task 1: Fix branch topology

**Files:**
- No code files modified

**Step 1: Stash uncommitted work**
```bash
cd /c/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai
git stash push -m "uncommitted-fe-work"
```

**Step 2: Force-update main to match master**
```bash
git checkout main
git reset --hard master
```

**Step 3: Push main to remote**
```bash
git push --force-with-lease origin main
```

**Step 4: Clean up branches**
```bash
git branch -d master
git branch -d feat/backend-saas-phase1
```

**Step 5: Restore stash and commit**
```bash
git stash pop
git add telemetry_tool/scoring.py telemetry_tool/web/static/css/ telemetry_tool/web/static/js/corner_replay_cockpit.js telemetry_tool/web/static/js/corner_replay_map.js telemetry_tool/web/static/js/visualize.js telemetry_tool/web/templates/session_detail.html
git commit -m "fix: commit pending frontend polish (scoring guard, corner replay map, UI cleanup)"
```

**Step 6: Update .gitignore**
```bash
cat >> .gitignore << 'EOF'

# Generated / temporary
*.png
.flask_log
.flask_pid
.playwright-mcp/
__pycache__/
*.pyc
.env
*.egg-info/
EOF
git add .gitignore
git commit -m "chore: add .gitignore for generated files"
```

---

### Task 2: Add GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

**Step 1: Write CI workflow**

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test-backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - run: pytest telemetry_tool/tests/ -q --tb=short
      - run: pytest kart_envelope/tests/ -q --tb=short

  test-frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: lap-website
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
          cache-dependency-path: lap-website/package-lock.json
      - run: npm ci
      - run: npm run lint
      - run: npm run test
      - run: npm run build
```

**Step 2: Commit**
```bash
git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions pytest + Next.js build workflow"
```

---

### Task 3: Add .env.example

**Files:**
- Create: `.env.example`

**Step 1: Write .env.example documenting all env vars from web/config.py**

```bash
# Flask
TELEMETRY_SECRET_KEY=change-me-to-random-secret
TELEMETRY_HOST=0.0.0.0
TELEMETRY_PORT=5000
TELEMETRY_DEBUG=0
TELEMETRY_LOG_FORMAT=json

# Database
USE_PG=1
TELEMETRY_PG_URL=postgresql://telemetry:telemetry@localhost:5432/telemetry
TELEMETRY_DB_PATH=telemetry.db

# Redis + Celery
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Auth
AUTH_REQUIRED=1
TELEMETRY_JWT_SECRET=change-me-to-random-jwt-secret
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
OAUTH_REDIRECT_BASE=https://app.lap.racing

# Ingest
TELEMETRY_INGEST_V2=1

# GDPR
TELEMETRY_EXPORT_DIR=/data/exports

# Rate limiting
RATE_LIMIT_ENABLED=1

# CORS (new)
CORS_ALLOWED_ORIGINS=https://lap.racing

# Next.js frontend (in lap-website/.env.local)
# NEXT_PUBLIC_API_URL=https://api.lap.racing
```

**Step 2: Commit**
```bash
git add .env.example
git commit -m "chore: add .env.example with all environment variables"
```

---

## Phase 1: Flask Security Hardening (Week 1-2)

### Task 4: Create @require_auth decorator

**Files:**
- Create: `telemetry_tool/web/decorators.py`
- Test: `telemetry_tool/tests/test_decorators.py`

**Step 1: Write failing test**

```python
"""Tests for auth decorator."""
import pytest
from flask import Flask, g
from web.api_utils import init_request_id
from web.decorators import require_auth


def _make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["AUTH_REQUIRED"] = True
    init_request_id(app)

    @app.route("/protected")
    @require_auth
    def protected():
        from web.api_utils import api_response
        return api_response({"user_id": g.user_id})

    return app


class TestRequireAuth:
    def test_returns_401_without_token(self):
        app = _make_app()
        client = app.test_client()
        resp = client.get("/protected")
        assert resp.status_code == 401
        assert resp.get_json()["ok"] is False

    def test_returns_200_with_valid_user(self):
        app = _make_app()
        client = app.test_client()
        with app.test_request_context():
            # Simulate auth middleware having set g.user_id
            pass
        # Test with mock auth header — implementation will decode JWT

    def test_skipped_when_auth_not_required(self):
        app = _make_app()
        app.config["AUTH_REQUIRED"] = False
        client = app.test_client()
        resp = client.get("/protected")
        # Should pass through with g.user_id = None
        assert resp.status_code == 200
```

**Step 2: Run test to verify it fails**
```bash
pytest telemetry_tool/tests/test_decorators.py -v
```
Expected: FAIL (module not found)

**Step 3: Implement decorator**

```python
"""Centralized auth and permission decorators."""
from __future__ import annotations

import functools
import logging

from flask import current_app, g, request

from web.api_utils import api_error, ErrorCode

logger = logging.getLogger(__name__)


def require_auth(fn):
    """Decorator that enforces authentication on a route.

    When AUTH_REQUIRED is False (desktop mode), sets g.user_id to None
    and allows the request through. When True, decodes the JWT from
    the Authorization header and sets g.user_id and g.workspace_id.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_app.config.get("AUTH_REQUIRED"):
            g.user_id = getattr(g, "user_id", None)
            g.workspace_id = getattr(g, "workspace_id", 1)
            return fn(*args, **kwargs)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return api_error(ErrorCode.FORBIDDEN, "Authentication required", status=401)

        token = auth_header[7:]
        try:
            import jwt
            secret = current_app.config["JWT_SECRET"]
            payload = jwt.decode(token, secret, algorithms=["HS256"])
            g.user_id = payload["sub"]
            g.workspace_id = payload.get("workspace_id", 1)
        except Exception as exc:
            logger.warning("JWT decode failed: %s", exc)
            return api_error(ErrorCode.TOKEN_EXPIRED, "Invalid or expired token", status=401)

        return fn(*args, **kwargs)
    return wrapper
```

**Step 4: Run tests**
```bash
pytest telemetry_tool/tests/test_decorators.py -v
```
Expected: PASS

**Step 5: Commit**
```bash
git add telemetry_tool/web/decorators.py telemetry_tool/tests/test_decorators.py
git commit -m "feat(auth): add @require_auth decorator with JWT decode"
```

---

### Task 5: Add CORS configuration

**Files:**
- Modify: `requirements.txt` (add `flask-cors>=4.0`)
- Modify: `telemetry_tool/web/app.py` (add CORS init)
- Modify: `telemetry_tool/web/config.py` (add CORS_ALLOWED_ORIGINS)

**Step 1: Add dependency**
```bash
echo "flask-cors>=4.0" >> requirements.txt
pip install flask-cors
```

**Step 2: Add config**

In `web/config.py`, add after `RATE_LIMIT_ENABLED`:
```python
    CORS_ALLOWED_ORIGINS: str = os.environ.get(
        "CORS_ALLOWED_ORIGINS", "http://localhost:3000"
    )
```

**Step 3: Wire CORS in app factory**

In `web/app.py`, after `init_request_id(app)`:
```python
    from flask_cors import CORS
    origins = [o.strip() for o in cfg.CORS_ALLOWED_ORIGINS.split(",")]
    CORS(app, origins=origins, supports_credentials=True)
```

**Step 4: Commit**
```bash
git add requirements.txt telemetry_tool/web/app.py telemetry_tool/web/config.py
git commit -m "feat(security): add CORS configuration with configurable origins"
```

---

### Task 6: Secrets fail on defaults in production

**Files:**
- Modify: `telemetry_tool/web/config.py`

**Step 1: Update Config.validate()**

```python
    def validate(self) -> None:
        """Raise if configuration is unsafe for production."""
        if self.AUTH_REQUIRED:
            if self.JWT_SECRET in ("jwt-dev-secret-change-me", "telemetry-jwt-dev-key-change-me"):
                raise ValueError("TELEMETRY_JWT_SECRET must be changed for production")
            if self.SECRET_KEY == "telemetry-local-dev-key":
                raise ValueError("TELEMETRY_SECRET_KEY must be changed for production")
```

**Step 2: Call validate() in app factory when AUTH_REQUIRED**

In `web/app.py` after config load:
```python
    if cfg.AUTH_REQUIRED:
        cfg.validate()
```

**Step 3: Commit**
```bash
git add telemetry_tool/web/config.py telemetry_tool/web/app.py
git commit -m "fix(security): fail on default secrets when AUTH_REQUIRED=1"
```

---

### Task 7: Add Dockerfile

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

**Step 1: Write multi-stage Dockerfile**

```dockerfile
FROM python:3.11-slim AS base
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY telemetry_tool/ telemetry_tool/
COPY kart_envelope/ kart_envelope/

EXPOSE 5000
CMD ["gunicorn", "-b", "0.0.0.0:5000", "-w", "4", "--timeout", "120", "telemetry_tool.web.app:create_app()"]
```

**Step 2: Write .dockerignore**
```
.git
__pycache__
*.pyc
.env
lap-website/
docs/
*.png
.flask_*
.playwright-mcp/
benchmarks/
```

**Step 3: Verify build**
```bash
docker build -t telemetry-api .
```

**Step 4: Commit**
```bash
git add Dockerfile .dockerignore
git commit -m "feat(infra): add multi-stage Dockerfile for Flask API"
```

---

### Task 8: Add /healthz endpoint

**Files:**
- Create: `telemetry_tool/web/routes/health.py`
- Modify: `telemetry_tool/web/app.py` (register blueprint)
- Test: `telemetry_tool/tests/test_health.py`

**Step 1: Write test**

```python
"""Tests for /healthz endpoint."""
import pytest
from flask import Flask
from web.routes.health import bp


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(bp)
    return app.test_client()


class TestHealthz:
    def test_returns_200(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"

    def test_includes_db_check(self, client):
        resp = client.get("/healthz")
        data = resp.get_json()
        assert "db" in data
```

**Step 2: Implement**

```python
"""Health check endpoint."""
import logging

from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

bp = Blueprint("health", __name__)


@bp.route("/healthz")
def healthz():
    checks = {"status": "ok", "db": "unknown", "redis": "unknown"}

    # DB check
    try:
        from web.db import get_db_connection
        conn = get_db_connection()
        conn.execute("SELECT 1")
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = f"error: {exc}"
        checks["status"] = "degraded"

    # Redis check
    try:
        from web.redis_client import get_redis
        r = get_redis()
        if r and r.ping():
            checks["redis"] = "ok"
        else:
            checks["redis"] = "unavailable"
    except Exception:
        checks["redis"] = "unavailable"

    status_code = 200 if checks["status"] == "ok" else 503
    return jsonify(checks), status_code
```

**Step 3: Register in app.py**

**Step 4: Run tests, commit**
```bash
pytest telemetry_tool/tests/test_health.py -v
git add telemetry_tool/web/routes/health.py telemetry_tool/tests/test_health.py telemetry_tool/web/app.py
git commit -m "feat(health): add /healthz endpoint with DB and Redis checks"
```

---

### Task 9: Flask v1 endpoint batch 2 — 15 session analysis endpoints

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py`
- Test: `telemetry_tool/tests/test_api_v1_data_batch2.py`

Add v1 wrappers for: `cross-session`, `sectors`, `sector-times`, `delta`, `corner-metrics`, `corner-coaching`, `corner-replay`, `badges`, `driving-style`, `brake-precision`, `energy-balance`, `fitness`, `consistency-heatmap`, `comparison-matrix`, `brake-throttle-tradeoff`.

Each follows the same pattern as existing v1 endpoints — read data from legacy route's DB query, wrap in `api_response()` envelope, add rate limiting. Follow the exact pattern of `v1_speed_trace()` in `api_v1_data.py`.

**Step 1: Write tests (one per endpoint)**
**Step 2: Implement all 15 wrappers**
**Step 3: Run full test suite**
**Step 4: Commit**
```bash
git commit -m "feat(api): v1 session analysis endpoints batch 2 — 15 wrappers"
```

---

### Task 10: Flask v1 endpoint batch 3 — search, browse, drivers, annotations

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_data.py`
- Create: `telemetry_tool/web/routes/api_v1_annotations.py`
- Test files for each

Add v1 wrappers for: `sessions/search`, `sessions/browse`, `sessions/recent`, `drivers`, `drivers/normalize`, `predefined-tracks`, `predefined-karts`, `track/<id>/key-corners`, `annotations/*`, `dashboards/*`, `data-health`.

**Step 1-4: Same TDD pattern as Task 9**
**Step 5: Commit**
```bash
git commit -m "feat(api): v1 search, drivers, annotations, dashboards endpoints"
```

---

### Task 11: Alembic migrations 011-015 — missing PG tables

**Files:**
- Create: `telemetry_tool/alembic/versions/011_race_strategy.py`
- Create: `telemetry_tool/alembic/versions/012_karts_catalog.py`
- Create: `telemetry_tool/alembic/versions/013_track_sectors.py`
- Create: `telemetry_tool/alembic/versions/014_stints_analysis.py`
- Create: `telemetry_tool/alembic/versions/015_export_templates.py`

Port 16 missing tables from `db/schema.py` SQLite definitions to Alembic PG migrations.

**Step 1: For each migration, copy the CREATE TABLE from schema.py, convert to op.create_table() with PG-native types**
**Step 2: Test with `alembic upgrade head` on a fresh PG database**
**Step 3: Commit**
```bash
git commit -m "feat(schema): Alembic 011-015 — race strategy, karts, sectors, stints, exports"
```

---

## Phase 2: Next.js Foundation (Week 1-2, parallel with Phase 1)

### Task 12: Next.js app scaffold — route groups and shared layout

**Files:**
- Create: `lap-website/src/app/(marketing)/layout.tsx` (move existing marketing routes here)
- Create: `lap-website/src/app/(app)/layout.tsx` (product app layout with sidebar nav)
- Create: `lap-website/src/app/(app)/dashboard/page.tsx` (placeholder)
- Create: `lap-website/src/app/(auth)/login/page.tsx` (placeholder)
- Modify: `lap-website/next.config.mjs` (add API proxy rewrite)

**Step 1: Create route groups**

Move all existing marketing pages into `(marketing)` route group. This is a Next.js convention — parenthesized folder names create layout groups without affecting URL.

Create `(app)` group for all product pages. Create `(auth)` group for login/register.

**Step 2: Add API proxy in next.config.mjs**
```javascript
const nextConfig = {
  images: { unoptimized: true },
  async rewrites() {
    return [
      {
        source: '/api/v1/:path*',
        destination: `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000'}/api/v1/:path*`,
      },
    ];
  },
};
```

**Step 3: Create app layout with navigation**

`(app)/layout.tsx` — dark theme, sidebar with all product nav links, uses the `lap-website` design tokens.

**Step 4: Run `npm run build` to verify**
**Step 5: Commit**
```bash
git commit -m "feat(app): Next.js route groups — marketing, app, auth with API proxy"
```

---

### Task 13: API client + React Query setup

**Files:**
- Create: `lap-website/src/lib/api-client.ts`
- Create: `lap-website/src/lib/api-types.ts`
- Create: `lap-website/src/providers/query-provider.tsx`
- Modify: `lap-website/package.json` (add @tanstack/react-query)

**Step 1: Install dependencies**
```bash
cd lap-website
npm install @tanstack/react-query
```

**Step 2: Create API client**

```typescript
// src/lib/api-client.ts
const API_BASE = '/api/v1';

export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) {
    super(message);
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
    credentials: 'include',
  });
  const body = await res.json();
  if (!body.ok) {
    throw new ApiError(body.error?.code ?? 'UNKNOWN', body.error?.message ?? 'Request failed', res.status);
  }
  return body.data as T;
}
```

**Step 3: Create QueryProvider**

```typescript
// src/providers/query-provider.tsx
'use client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';

export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
  }));
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
```

**Step 4: Wire into (app)/layout.tsx**
**Step 5: Commit**
```bash
git commit -m "feat(app): API client + React Query provider with envelope unwrapping"
```

---

### Task 14: Shared product components — design system port

**Files:**
- Create: `lap-website/src/components/app/DataTable.tsx`
- Create: `lap-website/src/components/app/ChartPanel.tsx`
- Create: `lap-website/src/components/app/StatCard.tsx`
- Create: `lap-website/src/components/app/FormField.tsx`
- Create: `lap-website/src/components/app/AppNav.tsx`
- Create: `lap-website/src/components/app/PageHeader.tsx`
- Create: `lap-website/src/hooks/useCanvas.ts`
- Create: `lap-website/src/lib/chart-theme.ts`
- Test: `lap-website/src/__tests__/components/`

**Step 1: Create chart theme constants**
```typescript
// src/lib/chart-theme.ts
import { colors } from '@/lib/tokens';

export const chartTheme = {
  bg: colors.concrete,
  gridLine: 'rgba(138, 143, 152, 0.2)', // steel at 20%
  axisLabel: colors.chalk,
  primary: colors.acidGreen,
  secondary: colors.pitOrange,
  danger: colors.safetyRed,
  warning: colors.marshalYellow,
} as const;
```

**Step 2: Create useCanvas hook**
```typescript
// src/hooks/useCanvas.ts
'use client';
import { useEffect, useRef } from 'react';

export function useCanvas(
  draw: (ctx: CanvasRenderingContext2D, width: number, height: number) => void,
  deps: unknown[] = [],
) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    draw(ctx, rect.width, rect.height);
  }, deps);

  return canvasRef;
}
```

**Step 3: Build each component using lap-website design tokens**

Each component uses: `bg-concrete`, `text-chalk`, `text-steel`, `border-steel/20`, `font-monument`, `font-telemetry`, `font-body` classes from the existing Tailwind config.

**Step 4: Write Vitest tests for each component (renders, accepts props)**
**Step 5: Commit**
```bash
git commit -m "feat(app): shared product components — DataTable, ChartPanel, StatCard, AppNav, useCanvas"
```

---

### Task 15: Auth pages — login, register, verify-email

**Files:**
- Create: `lap-website/src/app/(auth)/layout.tsx`
- Create: `lap-website/src/app/(auth)/login/page.tsx`
- Create: `lap-website/src/app/(auth)/register/page.tsx`
- Create: `lap-website/src/app/(auth)/verify-email/page.tsx`
- Create: `lap-website/src/hooks/useAuth.ts`
- Create: `lap-website/src/lib/auth.ts`

**Step 1: Create auth hook (JWT in httpOnly cookie via Flask, state via React Query)**
**Step 2: Build login page** — email + password form, PitButton submit, Google/GitHub OAuth buttons, link to register. Uses FormField component with Zod validation.
**Step 3: Build register page** — email + password + display name, same design.
**Step 4: Build verify-email page** — token from URL, calls Flask `/auth/verify-email`.
**Step 5: Add Next.js middleware to protect /app/* routes**

```typescript
// src/middleware.ts
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export function middleware(request: NextRequest) {
  const token = request.cookies.get('access_token');
  if (!token && request.nextUrl.pathname.startsWith('/app')) {
    return NextResponse.redirect(new URL('/login', request.url));
  }
  return NextResponse.next();
}

export const config = { matcher: ['/app/:path*'] };
```

**Step 6: Tests + commit**
```bash
git commit -m "feat(auth): login, register, verify-email pages with JWT middleware"
```

---

## Phase 3: CRUD Pages — Tier 1 (Week 3-4)

### Task 16: Sessions list page
- Create: `lap-website/src/app/(app)/sessions/page.tsx`
- DataTable with columns: date, track, driver, laps, best time, score, grade
- Search bar, filter by track/driver
- Calls `GET /api/v1/sessions/browse`

### Task 17: Session detail page
- Create: `lap-website/src/app/(app)/sessions/[id]/page.tsx`
- Header with session metadata (editable inline)
- Tab system for charts (loaded lazily)
- This is the most complex page — will be expanded in Phase 4

### Task 18: Tracks list + detail pages
- Create: `lap-website/src/app/(app)/tracks/page.tsx`
- Create: `lap-website/src/app/(app)/tracks/[id]/page.tsx`
- Card grid with track stats, detail page with evolution chart + leaderboard

### Task 19: Drivers list + detail pages
- Create: `lap-website/src/app/(app)/drivers/page.tsx`
- Create: `lap-website/src/app/(app)/drivers/[id]/page.tsx`
- Card grid, profile page with progression chart + session history

### Task 20: Karts list + detail + form pages
- Create: `lap-website/src/app/(app)/karts/page.tsx`
- Create: `lap-website/src/app/(app)/karts/[id]/page.tsx`
- Create: `lap-website/src/app/(app)/karts/new/page.tsx`

### Task 21: Weekends list + detail + form pages
- Create: `lap-website/src/app/(app)/weekends/page.tsx`
- Create: `lap-website/src/app/(app)/weekends/[id]/page.tsx`
- Create: `lap-website/src/app/(app)/weekends/new/page.tsx`

### Task 22: Leaderboard page
- Create: `lap-website/src/app/(app)/leaderboard/page.tsx`
- DataTable sorted by best lap time, filterable by track

### Task 23: Annotations + Data health pages
- Create: `lap-website/src/app/(app)/annotations/page.tsx`
- Create: `lap-website/src/app/(app)/data-health/page.tsx`
- Create: `lap-website/src/app/(app)/data-health/[id]/page.tsx`

**Each task follows the pattern:**
1. Write Vitest test (page renders, displays mock data)
2. Build page component using DataTable, StatCard, PageHeader
3. Wire React Query hook to `/api/v1/` endpoint
4. Verify `npm run build` passes
5. Commit

---

## Phase 4: Visualization Pages — Tier 2 (Week 5-7)

### Task 24: Dashboard page with sparklines
- Create: `lap-website/src/app/(app)/dashboard/page.tsx`
- 4 StatCards (total sessions, PB, avg score, total drivers)
- Score trend sparkline + lap time sparkline (port `dashboard_charts.js` draw functions)

### Task 25: Session detail — chart modules (24 charts)
- Create one React component per chart, each using `useCanvas` hook:
  - `SpeedTrace.tsx`, `GGDiagram.tsx`, `LapProgress.tsx`, `TrackMap.tsx`
  - `DrivingStyle.tsx`, `Fingerprint.tsx`, `BrakeScatter.tsx`
  - `ConsistencyHeatmap.tsx`, `SectorChart.tsx`, `EnergyBalance.tsx`
  - `FatigueChart.tsx`, `SpeedProfile.tsx`, `ThrottleHeatmap.tsx`
  - `LapDistribution.tsx`, `LapOverlay.tsx`, `RivalChart.tsx`
  - `WorkloadChart.tsx`, `TyreChart.tsx`, `WeatherChart.tsx`
  - `TrendChart.tsx`, `StintChart.tsx`, `PitWindowChart.tsx`
  - `CornerMastery.tsx`, `ComparisonMatrix.tsx`
- Each extracts the draw logic from the corresponding Flask JS file as a pure function
- Tab navigation to switch between chart groups

### Task 26: Visualize workspace
- Create: `lap-website/src/app/(app)/visualize/[id]/page.tsx`
- Three-panel layout: GPS map (react-leaflet), speed chart (useCanvas), GG scatter (useCanvas)
- Sidebar with lap checkboxes

### Task 27: Compare sessions + drivers pages
- Create: `lap-website/src/app/(app)/compare/page.tsx`
- Create: `lap-website/src/app/(app)/compare/sessions/page.tsx`
- Create: `lap-website/src/app/(app)/compare/drivers/page.tsx`

### Task 28: Analytics pages (weather, trends, meteo, weight sim, pace predictor)
- Create: `lap-website/src/app/(app)/analytics/page.tsx` (hub)
- Create: `lap-website/src/app/(app)/analytics/weather/page.tsx`
- Create: `lap-website/src/app/(app)/analytics/trends/page.tsx`
- Create: `lap-website/src/app/(app)/analytics/meteo/page.tsx`
- Create: `lap-website/src/app/(app)/analytics/weight-simulator/page.tsx`
- Create: `lap-website/src/app/(app)/analytics/pace-predictor/page.tsx`

### Task 29: Track evolution + driver progression chart pages
- Port `track_evolution.js` and `progression.js` draw functions

---

## Phase 5: Complex Interactive Pages — Tier 3 (Week 8-10)

### Task 30: Analyze wizard (3-step upload)
- Create: `lap-website/src/app/(app)/analyze/page.tsx`
- Step 1: File selector (drag-drop + file browser)
- Step 2: Configure driver/track/kart/session type
- Step 3: Progress with SSE polling
- Uses React Hook Form + Zod for validation
- Port: `analyze_form.js` logic

### Task 31: Corner replay
- Create: `lap-website/src/components/app/corner-replay/`
  - `CornerReplay.tsx` (orchestrator + state machine)
  - `CornerReplayMap.tsx` (react-leaflet)
  - `CornerReplayCockpit.tsx` (canvas gauges)
  - `CornerReplayControls.tsx` (play/pause, scrubber, mode tabs)
- Port: `corner_replay.js`, `corner_replay_map.js`, `corner_replay_cockpit.js`, `corner_replay_controls.js`
- State machine via Zustand store

### Task 32: Focus mode (split pane + tool registry)
- Create: `lap-website/src/components/app/focus-mode/`
  - `FocusMode.tsx` (overlay)
  - `SplitPane.tsx` (drag-to-resize panels)
  - `ToolDock.tsx` (icon sidebar)
- Port: `focus_mode.js`, `split_pane.js`, `focus_tools.js`

### Task 33: Race strategy — config, live, summary
- Create: `lap-website/src/app/(app)/race-strategy/page.tsx` (list)
- Create: `lap-website/src/app/(app)/race-strategy/new/page.tsx` (config)
- Create: `lap-website/src/app/(app)/race-strategy/[id]/page.tsx` (detail)
- Create: `lap-website/src/app/(app)/race-strategy/[id]/live/page.tsx` (real-time)
- Create: `lap-website/src/app/(app)/race-strategy/[id]/summary/page.tsx`
- Port: `race_strategy.js`, `race_strategy_live.js`
- Real-time updates via SSE + React Query polling

### Task 34: Dev plans + exports + setup tracker
- Create: `lap-website/src/app/(app)/dev-plans/page.tsx`
- Create: `lap-website/src/app/(app)/dev-plans/[id]/page.tsx`
- Create: `lap-website/src/app/(app)/exports/page.tsx`
- Create: `lap-website/src/app/(app)/setup-tracker/page.tsx`

---

## Phase 6: Integration Testing + Deploy (Week 11-12)

### Task 35: Playwright E2E tests — 10 critical flows

**Files:**
- Create: `lap-website/e2e/`
- Install: `npm install -D @playwright/test`

**Flows to test:**
1. Marketing page loads → click "Login" → login form
2. Register → verify email → dashboard
3. Login → dashboard shows stats
4. Upload CSV → analyze wizard → session created
5. Sessions list → click session → detail loads with charts
6. Session detail → open corner replay → plays animation
7. Tracks list → track detail → evolution chart renders
8. Compare two sessions → delta chart renders
9. Race strategy → create → go live → real-time updates
10. Account → export data → download ZIP

### Task 36: Production docker-compose

**Files:**
- Create: `docker-compose.prod.yml`

```yaml
version: "3.9"

services:
  api:
    build: .
    env_file: .env
    ports:
      - "5000:5000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000/healthz"]
      interval: 30s
      timeout: 10s
      retries: 3

  postgres:
    image: postgres:16-alpine
    env_file: .env
    environment:
      POSTGRES_USER: ${PG_USER:-telemetry}
      POSTGRES_PASSWORD: ${PG_PASSWORD}
      POSTGRES_DB: ${PG_DB:-telemetry}
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U telemetry"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  celery-pipeline:
    build: .
    command: celery -A telemetry_tool.celery_app worker -Q pipeline --concurrency=2 -l info
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

  celery-default:
    build: .
    command: celery -A telemetry_tool.celery_app worker -Q default --concurrency=4 -l info
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

  celery-beat:
    build: .
    command: celery -A telemetry_tool.celery_app beat -l info
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

volumes:
  pg_data:
```

### Task 37: DNS + TLS + deployment

**Step 1: Deploy Flask API**
- Push Docker image to GHCR or Docker Hub
- Deploy to VPS / Railway / Fly.io
- Configure `api.lap.racing` DNS A record
- TLS via Let's Encrypt (certbot or platform-managed)

**Step 2: Deploy Next.js**
- Push `lap-website/` to Vercel
- Configure `lap.racing` domain
- Set `NEXT_PUBLIC_API_URL=https://api.lap.racing` env var

**Step 3: Verify end-to-end**
- Marketing pages load at `lap.racing`
- Login redirects work
- API calls from browser reach Flask
- CORS headers correct
- All charts render

---

## Summary

| Phase | Tasks | Duration |
|-------|-------|----------|
| Phase 0: Emergency fixes | 1-3 | Day 1 |
| Phase 1: Flask hardening | 4-11 | Week 1-2 |
| Phase 2: Next.js foundation | 12-15 | Week 1-2 (parallel) |
| Phase 3: CRUD pages | 16-23 | Week 3-4 |
| Phase 4: Visualization pages | 24-29 | Week 5-7 |
| Phase 5: Complex interactives | 30-34 | Week 8-10 |
| Phase 6: Integration + deploy | 35-37 | Week 11-12 |

**Total: 37 tasks across 6 phases, ~12 weeks.**
