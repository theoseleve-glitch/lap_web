# SEO + LLM Optimization + App Consumption Tracking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add server-side engagement tracking to the authenticated app, harden SEO with structured data stacking and meta completeness, and optimize for LLM crawlers via llms.txt and AI-specific robots.txt directives.

**Architecture:** New `app_events` table captures engagement events from the frontend via `POST /api/v1/events`. Billing metering uses the existing entitlements system (already tracks upload quotas). Frontend hooks batch and deduplicate events. SEO/LLM changes are all frontend: route handlers for `llms.txt`/`llms-full.txt`, enhanced `robots.ts`, JSON-LD schema stacking, and semantic HTML components.

**Tech Stack:** Flask + PostgreSQL (backend), Next.js 14 + TypeScript (frontend), Vitest (frontend tests), pytest (backend tests)

**Design revision**: The spec called for a separate `usage_counters` table, but the existing `entitlements.py` already handles billing metering via `check_and_record_quota()`. We use `app_events` for engagement analytics and the existing entitlements system for billing — no duplicate metering.

---

## Task 1: Migration 022 — `app_events` Table

**Files:**
- Create: `alembic/versions/022_app_events.py`

- [ ] **Step 1: Write the migration**

```python
"""Create app_events table for engagement tracking.

Stores raw user interaction events from the authenticated app.
Partitioned by month for efficient 90-day retention pruning.

Revision ID: 022
Revises: 021
"""
from alembic import op
import sqlalchemy as sa

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade():
    # Create partitioned parent table
    op.execute("""
        CREATE TABLE app_events (
            id          BIGSERIAL,
            workspace_id INTEGER NOT NULL,
            user_id     INTEGER NOT NULL,
            event_type  TEXT NOT NULL,
            properties  JSONB NOT NULL DEFAULT '{}',
            path        TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at)
    """)

    # Create initial partitions (current month + next month)
    op.execute("""
        CREATE TABLE app_events_2026_04 PARTITION OF app_events
            FOR VALUES FROM ('2026-04-01') TO ('2026-05-01')
    """)
    op.execute("""
        CREATE TABLE app_events_2026_05 PARTITION OF app_events
            FOR VALUES FROM ('2026-05-01') TO ('2026-06-01')
    """)

    # Indexes on the parent (automatically created on partitions)
    op.execute("""
        CREATE INDEX ix_app_events_ws_type_ts
            ON app_events (workspace_id, event_type, created_at)
    """)
    op.execute("""
        CREATE INDEX ix_app_events_user_ts
            ON app_events (user_id, created_at)
    """)

    # RLS policy
    op.execute("ALTER TABLE app_events ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY app_events_workspace_isolation ON app_events
            USING (workspace_id = current_setting('app.workspace_id')::integer)
            WITH CHECK (workspace_id = current_setting('app.workspace_id')::integer)
    """)


def downgrade():
    op.execute("DROP POLICY IF EXISTS app_events_workspace_isolation ON app_events")
    op.execute("ALTER TABLE app_events DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TABLE IF EXISTS app_events CASCADE")
```

- [ ] **Step 2: Run migration against local PG**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && alembic upgrade head`
Expected: Migration 022 applies successfully.

- [ ] **Step 3: Verify table exists**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python -c "import psycopg2; conn = psycopg2.connect('postgresql://telemetry:telemetry@localhost:5432/telemetry'); cur = conn.cursor(); cur.execute(\"SELECT tablename FROM pg_tables WHERE tablename LIKE 'app_events%'\"); print(cur.fetchall())"`
Expected: `[('app_events',), ('app_events_2026_04',), ('app_events_2026_05',)]`

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/022_app_events.py
git commit -m "feat(db): migration 022 — app_events partitioned table for engagement tracking"
```

---

## Task 2: Events API Blueprint + Tests

**Files:**
- Create: `telemetry_tool/web/routes/events.py`
- Create: `telemetry_tool/tests/test_events_api.py`
- Modify: `telemetry_tool/web/app.py` (add blueprint to `_blueprint_imports`)

- [ ] **Step 1: Write the test file**

```python
"""Tests for the events API (POST /api/v1/events, GET /api/v1/usage)."""
import json
from unittest.mock import patch, MagicMock
import pytest
from flask import Flask, g

def _make_app():
    """Create minimal Flask app with events blueprint."""
    from web.api_utils import init_request_id, api_response
    from web.routes.events import bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = True
    app.config["AUTH_REQUIRED"] = True
    app.config["JWT_SECRET"] = "test-secret"
    init_request_id(app)

    @app.before_request
    def _set_fake_user():
        g.current_user_id = 1
        g.workspace_id = 1

    app.register_blueprint(bp)
    return app


class TestPostEvents:
    def test_accepts_single_event(self):
        app = _make_app()
        client = app.test_client()
        with patch("web.routes.events._insert_events") as mock_insert:
            resp = client.post(
                "/api/v1/events",
                data=json.dumps({"events": [{"event": "session.view", "path": "/app/sessions/1"}]}),
                content_type="application/json",
            )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        mock_insert.assert_called_once()
        args = mock_insert.call_args[0]
        assert len(args[0]) == 1
        assert args[0][0]["event"] == "session.view"

    def test_rejects_empty_events(self):
        app = _make_app()
        client = app.test_client()
        resp = client.post(
            "/api/v1/events",
            data=json.dumps({"events": []}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_rejects_oversized_batch(self):
        app = _make_app()
        client = app.test_client()
        events = [{"event": f"test.{i}"} for i in range(51)]
        resp = client.post(
            "/api/v1/events",
            data=json.dumps({"events": events}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_rejects_missing_event_field(self):
        app = _make_app()
        client = app.test_client()
        resp = client.post(
            "/api/v1/events",
            data=json.dumps({"events": [{"path": "/app/dashboard"}]}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_strips_unknown_event_types(self):
        app = _make_app()
        client = app.test_client()
        with patch("web.routes.events._insert_events") as mock_insert:
            resp = client.post(
                "/api/v1/events",
                data=json.dumps({"events": [
                    {"event": "session.view"},
                    {"event": "malicious.event"},
                ]}),
                content_type="application/json",
            )
        assert resp.status_code == 200
        inserted = mock_insert.call_args[0][0]
        assert len(inserted) == 1
        assert inserted[0]["event"] == "session.view"


class TestGetUsage:
    def test_returns_usage_snapshot(self):
        app = _make_app()
        client = app.test_client()
        mock_snapshot = {
            "plan_tier": "racer",
            "analyses_used": 5,
            "analyses_per_month": 50,
            "max_upload_size_mb": 500,
        }
        with patch("web.routes.events.entitlement_snapshot", return_value=mock_snapshot):
            resp = client.get("/api/v1/usage")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["data"]["plan_tier"] == "racer"
        assert body["data"]["analyses_used"] == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python -m pytest telemetry_tool/tests/test_events_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'web.routes.events'`

- [ ] **Step 3: Write the events blueprint**

```python
"""Events API — engagement tracking + usage dashboard.

POST /api/v1/events   — receive batched events from the frontend
GET  /api/v1/usage    — return current usage snapshot for the workspace
GET  /api/v1/analytics/engagement — engagement summary (last 30 days)
"""
from __future__ import annotations

import json as _json
import logging
from datetime import datetime, timezone

from flask import Blueprint, g, request

from web.api_utils import ErrorCode, api_error, api_response

logger = logging.getLogger(__name__)

bp = Blueprint("events", __name__, url_prefix="/api/v1")

_MAX_BATCH_SIZE = 50
_ALLOWED_EVENT_PREFIXES = (
    "page.", "session.", "chart.", "report.", "compare.",
    "corner.", "track.", "weekend.", "search.", "export.", "limit.",
)


def _validate_events(raw: list[dict]) -> tuple[list[dict], str | None]:
    """Validate and sanitize a batch of events. Returns (events, error_msg)."""
    if not raw:
        return [], "events array must not be empty"
    if len(raw) > _MAX_BATCH_SIZE:
        return [], f"batch size {len(raw)} exceeds maximum {_MAX_BATCH_SIZE}"

    cleaned = []
    for item in raw:
        event_type = item.get("event")
        if not event_type or not isinstance(event_type, str):
            return [], "each event must have a string 'event' field"
        if not any(event_type.startswith(p) for p in _ALLOWED_EVENT_PREFIXES):
            continue  # silently drop unknown event types
        cleaned.append({
            "event": event_type[:128],
            "properties": item.get("properties") or {},
            "path": (item.get("path") or "")[:512] or None,
        })

    if not cleaned:
        return [], "no valid events in batch"
    return cleaned, None


def _insert_events(events: list[dict], user_id: int, workspace_id: int) -> None:
    """Bulk insert events into app_events table."""
    try:
        from web.db_pg import get_pg_connection
        conn = get_pg_connection()
    except Exception:
        from web.db import get_db_connection
        conn = get_db_connection()

    now = datetime.now(timezone.utc)
    values_parts = []
    params: dict = {}
    for i, evt in enumerate(events):
        values_parts.append(
            f"(%(ws)s, %(uid)s, %(et_{i})s, %(pr_{i})s, %(pa_{i})s, %(ts)s)"
        )
        params[f"et_{i}"] = evt["event"]
        params[f"pr_{i}"] = _json.dumps(evt["properties"])
        params[f"pa_{i}"] = evt["path"]

    params["ws"] = workspace_id
    params["uid"] = user_id
    params["ts"] = now

    sql = (
        "INSERT INTO app_events (workspace_id, user_id, event_type, properties, path, created_at) "
        f"VALUES {', '.join(values_parts)}"
    )
    conn.execute(sql, params)
    conn.commit()


def entitlement_snapshot() -> dict:
    """Import and call the entitlement snapshot from middleware."""
    from web.middleware.entitlements import entitlement_snapshot as _snapshot
    return _snapshot()


@bp.route("/events", methods=["POST"])
def post_events():
    """Receive a batch of engagement events from the frontend."""
    user_id = getattr(g, "current_user_id", None)
    workspace_id = getattr(g, "workspace_id", None)
    if user_id is None or workspace_id is None:
        return api_error(ErrorCode.UNAUTHORIZED, "Authentication required", status=401)

    body = request.get_json(silent=True)
    if not body or "events" not in body:
        return api_error(ErrorCode.VALIDATION_ERROR, "Request must contain 'events' array", status=400)

    events, err = _validate_events(body["events"])
    if err:
        return api_error(ErrorCode.VALIDATION_ERROR, err, status=400)

    try:
        _insert_events(events, user_id, workspace_id)
    except Exception:
        logger.warning("Failed to insert app_events", exc_info=True)
        # Fail silently — tracking must never break the UX

    return api_response({"accepted": len(events)})


@bp.route("/usage", methods=["GET"])
def get_usage():
    """Return current usage snapshot for the workspace."""
    user_id = getattr(g, "current_user_id", None)
    if user_id is None:
        return api_error(ErrorCode.UNAUTHORIZED, "Authentication required", status=401)

    try:
        snapshot = entitlement_snapshot()
    except Exception:
        logger.warning("Failed to load entitlement snapshot", exc_info=True)
        snapshot = {}

    return api_response({
        "plan_tier": snapshot.get("plan_tier", "demo"),
        "analyses_used": snapshot.get("analyses_used", 0),
        "analyses_limit": snapshot.get("analyses_per_month", 0),
        "max_upload_size_mb": snapshot.get("max_upload_size_mb", 0),
    })


@bp.route("/analytics/engagement", methods=["GET"])
def get_engagement():
    """Return engagement summary for the last 30 days."""
    workspace_id = getattr(g, "workspace_id", None)
    if workspace_id is None:
        return api_error(ErrorCode.UNAUTHORIZED, "Authentication required", status=401)

    try:
        from web.db_pg import get_pg_connection
        conn = get_pg_connection()

        cur = conn.execute(
            """SELECT event_type, COUNT(*) as cnt
               FROM app_events
               WHERE workspace_id = %(ws)s
                 AND created_at >= now() - interval '30 days'
               GROUP BY event_type ORDER BY cnt DESC LIMIT 10""",
            {"ws": workspace_id},
        )
        top_features = [{"event": r[0], "count": r[1]} for r in cur.fetchall()]

        cur = conn.execute(
            """SELECT COUNT(DISTINCT user_id)
               FROM app_events
               WHERE workspace_id = %(ws)s
                 AND created_at >= now() - interval '30 days'""",
            {"ws": workspace_id},
        )
        active_users = cur.fetchone()[0] or 0

        cur = conn.execute(
            """SELECT COUNT(*)
               FROM app_events
               WHERE workspace_id = %(ws)s
                 AND created_at >= now() - interval '30 days'""",
            {"ws": workspace_id},
        )
        total_events = cur.fetchone()[0] or 0

    except Exception:
        logger.warning("Failed to query engagement data", exc_info=True)
        return api_response({"active_users": 0, "total_events": 0, "top_features": []})

    return api_response({
        "active_users": active_users,
        "total_events": total_events,
        "top_features": top_features,
    })
```

- [ ] **Step 4: Register blueprint in app.py**

Add to the `_blueprint_imports` list in `telemetry_tool/web/app.py`:

```python
('.routes.events',             'bp', 'events_bp'),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python -m pytest telemetry_tool/tests/test_events_api.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/web/routes/events.py telemetry_tool/tests/test_events_api.py telemetry_tool/web/app.py
git commit -m "feat(api): events endpoint for engagement tracking + usage dashboard"
```

---

## Task 3: Frontend `useTrackEvent` + `usePageView` Hooks

**Files:**
- Create: `lap-website/src/hooks/useTrackEvent.ts`
- Create: `lap-website/src/hooks/usePageView.ts`
- Create: `lap-website/src/__tests__/track-event.test.ts`

- [ ] **Step 1: Write the test**

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock consent
vi.mock('@/lib/consent', () => ({
  hasAnalyticsConsent: vi.fn(() => true),
}));

// Mock api-client
const mockPost = vi.fn().mockResolvedValue({ accepted: 1 });
vi.mock('@/lib/api-client', () => ({
  api: { post: (...args: unknown[]) => mockPost(...args) },
}));

describe('trackEvent', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockPost.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('batches events and flushes after 5 seconds', async () => {
    const { trackEvent, _flushNow } = await import('@/hooks/useTrackEvent');
    trackEvent('session.view', { session_id: 1 });
    trackEvent('chart.interact', { chart: 'speed' });

    // Not flushed yet
    expect(mockPost).not.toHaveBeenCalled();

    await _flushNow();

    expect(mockPost).toHaveBeenCalledWith('/events', expect.objectContaining({
      events: expect.arrayContaining([
        expect.objectContaining({ event: 'session.view' }),
        expect.objectContaining({ event: 'chart.interact' }),
      ]),
    }));
  });

  it('does not send when consent is denied', async () => {
    const { hasAnalyticsConsent } = await import('@/lib/consent');
    (hasAnalyticsConsent as ReturnType<typeof vi.fn>).mockReturnValue(false);

    const { trackEvent, _flushNow } = await import('@/hooks/useTrackEvent');
    trackEvent('session.view');
    await _flushNow();

    expect(mockPost).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx vitest run src/__tests__/track-event.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `useTrackEvent.ts`**

```typescript
/**
 * Client-side engagement event tracker.
 *
 * Batches events (up to 10 or 5 seconds), deduplicates within 2s,
 * and ships to POST /api/v1/events via apiFetch.
 * Consent-gated — sends nothing without analytics consent.
 */
'use client';

import { useCallback } from 'react';
import { api } from '@/lib/api-client';
import { hasAnalyticsConsent } from '@/lib/consent';

interface QueuedEvent {
  event: string;
  properties?: Record<string, string | number | boolean>;
  path?: string;
  ts: number;
}

const _queue: QueuedEvent[] = [];
const _dedup = new Map<string, number>();
let _timer: ReturnType<typeof setTimeout> | null = null;

const FLUSH_INTERVAL_MS = 5_000;
const FLUSH_BATCH_SIZE = 10;
const DEDUP_WINDOW_MS = 2_000;

function _dedupKey(event: string, path?: string): string {
  return `${event}:${path ?? ''}`;
}

function _scheduleFlush(): void {
  if (_timer) return;
  _timer = setTimeout(() => {
    _timer = null;
    void _flush();
  }, FLUSH_INTERVAL_MS);
}

async function _flush(): Promise<void> {
  if (_queue.length === 0) return;
  if (!hasAnalyticsConsent()) {
    _queue.length = 0;
    return;
  }

  const batch = _queue.splice(0, _queue.length);
  const payload = batch.map(({ event, properties, path }) => ({
    event,
    properties: properties ?? {},
    path: path ?? (typeof window !== 'undefined' ? window.location.pathname : undefined),
  }));

  try {
    api.post('/events', { events: payload }).catch(() => {});
  } catch {
    // Fire-and-forget — never break UX
  }
}

/**
 * Track an engagement event. Fire-and-forget.
 * Events are batched and sent periodically.
 */
export function trackEvent(
  event: string,
  properties?: Record<string, string | number | boolean>,
  path?: string,
): void {
  if (typeof window === 'undefined') return;

  const now = Date.now();
  const key = _dedupKey(event, path ?? window.location.pathname);
  const lastSeen = _dedup.get(key);
  if (lastSeen && now - lastSeen < DEDUP_WINDOW_MS) return;
  _dedup.set(key, now);

  _queue.push({ event, properties, path, ts: now });

  if (_queue.length >= FLUSH_BATCH_SIZE) {
    void _flush();
  } else {
    _scheduleFlush();
  }
}

/** React hook wrapper — returns a stable trackEvent callback. */
export function useTrackEvent() {
  return useCallback(trackEvent, []);
}

/** Flush now — exported for page-unload and tests. */
export async function _flushNow(): Promise<void> {
  if (_timer) {
    clearTimeout(_timer);
    _timer = null;
  }
  await _flush();
}

// Flush on page unload via sendBeacon
if (typeof window !== 'undefined') {
  window.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden' && _queue.length > 0 && hasAnalyticsConsent()) {
      const batch = _queue.splice(0, _queue.length);
      const payload = JSON.stringify({
        events: batch.map(({ event, properties, path }) => ({
          event,
          properties: properties ?? {},
          path: path ?? window.location.pathname,
        })),
      });
      const url = `${process.env.NEXT_PUBLIC_API_URL || ''}/api/v1/events`;
      navigator.sendBeacon(url, new Blob([payload], { type: 'application/json' }));
    }
  });
}
```

- [ ] **Step 4: Write `usePageView.ts`**

```typescript
/**
 * Track page views on /app/* route transitions.
 * Captures path, referrer (previous path), and time-on-page.
 */
'use client';

import { useEffect, useRef } from 'react';
import { usePathname } from 'next/navigation';
import { trackEvent } from './useTrackEvent';

export function usePageView(): void {
  const pathname = usePathname();
  const prevPath = useRef<string | null>(null);
  const enterTime = useRef<number>(Date.now());

  useEffect(() => {
    if (!pathname?.startsWith('/app')) return;

    const now = Date.now();
    if (prevPath.current) {
      const duration = now - enterTime.current;
      if (duration > 500) {
        trackEvent('page.time_on_page', { duration_ms: duration }, prevPath.current);
      }
    }

    trackEvent('page.view', {
      referrer: prevPath.current ?? document.referrer ?? '',
    }, pathname);

    prevPath.current = pathname;
    enterTime.current = now;
  }, [pathname]);
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx vitest run src/__tests__/track-event.test.ts`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add lap-website/src/hooks/useTrackEvent.ts lap-website/src/hooks/usePageView.ts lap-website/src/__tests__/track-event.test.ts
git commit -m "feat(fe): useTrackEvent + usePageView hooks with batching and dedup"
```

---

## Task 4: Frontend Event Instrumentation

**Files:**
- Create: `lap-website/src/components/app/AppEventTracker.tsx`
- Modify: `lap-website/src/app/app/layout.tsx` (add AppEventTracker)
- Modify: `lap-website/src/app/app/sessions/[id]/page.tsx` (session.view, tab_switch)
- Modify: `lap-website/src/app/app/sessions/upload/page.tsx` (session.upload)
- Modify: `lap-website/src/app/app/compare/sessions/page.tsx` (compare.run)

- [ ] **Step 1: Create AppEventTracker provider**

```typescript
'use client';

import { usePageView } from '@/hooks/usePageView';

export function AppEventTracker() {
  usePageView();
  return null;
}
```

- [ ] **Step 2: Add AppEventTracker to app layout**

In `lap-website/src/app/app/layout.tsx`, import and render `<AppEventTracker />` alongside existing providers.

```typescript
import { AppEventTracker } from '@/components/app/AppEventTracker';
```

Render inside the layout body:
```tsx
<AppEventTracker />
```

- [ ] **Step 3: Add session.view + session.tab_switch to session detail page**

In `lap-website/src/app/app/sessions/[id]/page.tsx`:

```typescript
import { trackEvent } from '@/hooks/useTrackEvent';
```

Add useEffect for session.view (fires once on mount with sessionId):
```typescript
useEffect(() => {
  if (sessionId) {
    trackEvent('session.view', { session_id: sessionId });
  }
}, [sessionId]);
```

On tab switch handler, add:
```typescript
trackEvent('session.tab_switch', { tab: newTab, session_id: sessionId });
```

- [ ] **Step 4: Add session.upload to upload page**

In `lap-website/src/app/app/sessions/upload/page.tsx`, inside the `event.status === 'completed'` handler (around line 615):

```typescript
import { trackEvent } from '@/hooks/useTrackEvent';
```

```typescript
if (event.status === 'completed') {
  const sid = event.session_id || jId;
  trackEvent('session.upload', { session_id: sid ?? '' });
  // ... rest of existing handler
```

- [ ] **Step 5: Add compare.run to compare page**

In `lap-website/src/app/app/compare/sessions/page.tsx`, when both sessions are loaded and comparison data fetches:

```typescript
import { trackEvent } from '@/hooks/useTrackEvent';
```

```typescript
trackEvent('compare.run', { session_a: sessionAId, session_b: sessionBId });
```

- [ ] **Step 6: Verify build**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npm run build`
Expected: Build succeeds with no errors.

- [ ] **Step 7: Commit**

```bash
git add lap-website/src/components/app/AppEventTracker.tsx lap-website/src/app/app/layout.tsx lap-website/src/app/app/sessions/ lap-website/src/app/app/compare/
git commit -m "feat(fe): instrument session view, upload, compare with engagement events"
```

---

## Task 5: `llms.txt` + `llms-full.txt` Route Handlers

**Files:**
- Create: `lap-website/src/app/llms.txt/route.ts`
- Create: `lap-website/src/app/llms-full.txt/route.ts`
- Create: `lap-website/src/__tests__/llms-txt.test.ts`

- [ ] **Step 1: Write the test**

```typescript
import { describe, it, expect } from 'vitest';

describe('llms.txt route', () => {
  it('returns text/plain with correct header structure', async () => {
    const { GET } = await import('@/app/llms.txt/route');
    const response = GET();
    const text = await response.text();

    expect(response.headers.get('Content-Type')).toBe('text/plain; charset=utf-8');
    expect(text).toMatch(/^# LAP/);
    expect(text).toContain('> ');
    expect(text).toContain('## About');
    expect(text).toContain('## Key Pages');
    expect(text).toContain('## Canonical');
  });
});

describe('llms-full.txt route', () => {
  it('returns text/plain with FAQ and pricing content', async () => {
    const { GET } = await import('@/app/llms-full.txt/route');
    const response = GET();
    const text = await response.text();

    expect(response.headers.get('Content-Type')).toBe('text/plain; charset=utf-8');
    expect(text).toContain('## FAQ');
    expect(text).toContain('## Pricing');
    expect(text).toContain('## Glossary');
    expect(new TextEncoder().encode(text).length).toBeLessThan(100_000);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx vitest run src/__tests__/llms-txt.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `llms.txt` route handler**

```typescript
import { routeMap } from '@/data/route-map';
import { BRAND } from '@/data/brand';

const SITE_URL = 'https://www.lap-coach.racing';

export function GET() {
  const now = new Date();
  const lastUpdated = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;

  const keyPages = Object.values(routeMap)
    .filter((r) => !r.noIndex && r.path !== '/' && r.metaDescription)
    .slice(0, 15)
    .map((r) => `- [${r.title}](${r.path}): ${r.metaDescription?.slice(0, 120)}`)
    .join('\n');

  const content = `# ${BRAND.productName} — Motorsport Telemetry Analysis Platform

> Ingests GPS and sensor telemetry from RaceChrono, RaceBox, AiM, and MoTeC.
> Scores driving across four pillars (Pace, Consistency, Execution, Robustness),
> detects corners from GPS data, and generates per-corner coaching insights
> for kart and car drivers.

## About

- **Type**: WebApplication
- **Category**: Motorsport / Telemetry Analysis / Driver Coaching
- **Language**: English
- **Audience**: Kart drivers, car racing teams, track day enthusiasts, racing coaches
- **Pricing**: Free demo, paid plans from \u20ac5.75/month
- **Last Updated**: ${lastUpdated}

## Key Pages

${keyPages}

## Canonical

- **Primary URL**: ${SITE_URL}
- **llms.txt Location**: ${SITE_URL}/llms.txt
- **API**: https://api.lap-coach.racing

## Optional

- [Changelog](/changelog): Release notes and new features
- [Waitlist](/waitlist): Early access signup
- [Contact](/contact): Sales and partnership enquiries
`;

  return new Response(content, {
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      'Cache-Control': 'public, s-maxage=3600, stale-while-revalidate=600',
    },
  });
}
```

- [ ] **Step 4: Write `llms-full.txt` route handler**

```typescript
import { routeMap } from '@/data/route-map';
import { insightEntries } from '@/data/insights-cms';
import { BRAND } from '@/data/brand';

export function GET() {
  const now = new Date();
  const lastUpdated = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;

  const pages = Object.values(routeMap)
    .filter((r) => !r.noIndex && r.metaDescription)
    .map((r) => `### ${r.title}\n\nURL: ${r.path}\n\n${r.metaDescription}`)
    .join('\n\n');

  const insights = insightEntries
    .map((e) => `### ${e.title}\n\nURL: /insights/${e.slug}\n\n${e.summary}\n\n${e.bodyMdx}`)
    .join('\n\n');

  const content = `# ${BRAND.productName} — Full Content Export

> ${BRAND.positioning}

Last Updated: ${lastUpdated}

## Pages

${pages}

## Insights

${insights}

## Glossary

- **LAP**: Lap Analysis Platform — the product name. Always uppercase.
- **Telemetry**: GPS coordinates + sensor data (speed, g-force, RPM) recorded by a data logger during a racing session.
- **Session**: One continuous recording from a data logger device, typically covering a practice, qualifying, or race stint.
- **Corner**: An auto-detected turn section of a racing track, identified from GPS trajectory curvature analysis.
- **Pillar Scores**: Four scoring dimensions — Pace (/25), Consistency (/25), Execution (/25), Robustness (/25) — totalling /100 with letter grades.
- **RaceChrono**: A popular mobile app that records GPS and OBD telemetry data during track sessions.
- **RaceBox**: A standalone GPS data logger designed for motorsport use.

## Pricing

- **Demo**: Free — 3 analyses per month, basic scoring, 50 MB upload limit.
- **Racer**: \u20ac9/month or \u20ac69/year — 50 analyses, advanced coaching, session comparison, 500 MB upload.
- **World-Class**: \u20ac15/month or \u20ac109/year — unlimited analyses, all features, API access, 2 GB upload.

## FAQ

- **What file formats does LAP support?** RaceChrono CSV, RaceBox CSV, AiM CSV, MoTeC CSV. GPS data with at least latitude, longitude, and speed columns.
- **How does corner detection work?** LAP analyses GPS trajectory curvature to identify turn entry, apex, and exit points automatically. No manual track mapping required.
- **What are the four scoring pillars?** Pace (how fast vs your best), Consistency (lap-to-lap variation), Execution (corner technique quality), Robustness (ability to maintain pace under changing conditions).
- **Can I compare sessions from different days?** Yes — the comparison tool synchronises two sessions by distance, showing speed, line, and g-force differences corner by corner.
`;

  return new Response(content, {
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      'Cache-Control': 'public, s-maxage=3600, stale-while-revalidate=600',
    },
  });
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx vitest run src/__tests__/llms-txt.test.ts`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add lap-website/src/app/llms.txt/ lap-website/src/app/llms-full.txt/ lap-website/src/__tests__/llms-txt.test.ts
git commit -m "feat(seo): llms.txt + llms-full.txt route handlers for AI crawler optimization"
```

---

## Task 6: `robots.ts` — AI Crawler Directives

**Files:**
- Modify: `lap-website/src/app/robots.ts`

- [ ] **Step 1: Read current robots.ts**

Read `lap-website/src/app/robots.ts` to confirm current content.

- [ ] **Step 2: Replace with AI crawler directives**

```typescript
import type { MetadataRoute } from 'next';
import { getSiteUrl } from '@/lib/site-url';

export default function robots(): MetadataRoute.Robots {
  const siteUrl = getSiteUrl();

  return {
    rules: [
      // Traditional search
      { userAgent: 'Googlebot', allow: '/' },

      // AI training crawlers (future model knowledge, 3-12 month lag)
      { userAgent: 'GPTBot', allow: '/' },
      { userAgent: 'ClaudeBot', allow: '/' },
      { userAgent: 'Google-Extended', allow: '/' },
      { userAgent: 'Applebot-Extended', allow: '/' },
      { userAgent: 'Meta-ExternalAgent', allow: '/' },

      // AI retrieval crawlers (live AI search — blocking = instant disappearance)
      { userAgent: 'ChatGPT-User', allow: '/' },
      { userAgent: 'PerplexityBot', allow: '/' },

      // Block data aggregators (no benefit)
      { userAgent: 'CCBot', disallow: '/' },
      { userAgent: 'DataForSeoBot', disallow: '/' },

      // Default
      {
        userAgent: '*',
        allow: '/',
        disallow: ['/api/', '/app/', '/admin/'],
      },
    ],
    sitemap: `${siteUrl}/sitemap.xml`,
    host: siteUrl,
  };
}
```

- [ ] **Step 3: Verify build**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npm run build`
Expected: Build succeeds.

- [ ] **Step 4: Commit**

```bash
git add lap-website/src/app/robots.ts
git commit -m "feat(seo): robots.txt AI crawler directives — allow training + retrieval bots, block aggregators"
```

---

## Task 7: JSON-LD Schema Enhancement + SEO Components

**Files:**
- Modify: `lap-website/src/app/layout.tsx` (WebSite schema + featureList)
- Create: `lap-website/src/components/seo/BreadcrumbJsonLd.tsx`
- Create: `lap-website/src/components/seo/PageJsonLd.tsx`
- Create: `lap-website/src/components/seo/EntityGlossary.tsx`
- Create: `lap-website/src/components/seo/RelatedPages.tsx`

- [ ] **Step 1: Create BreadcrumbJsonLd component**

```typescript
import { buildBreadcrumbs } from '@/data/route-map';
import { getSiteUrl } from '@/lib/site-url';

interface Props {
  pathname: string;
}

export function BreadcrumbJsonLd({ pathname }: Props) {
  const crumbs = buildBreadcrumbs(pathname);
  if (crumbs.length === 0) return null;

  const siteUrl = getSiteUrl();
  const items = [
    ...crumbs.map((c, i) => ({
      '@type': 'ListItem' as const,
      position: i + 1,
      name: c.label,
      item: `${siteUrl}${c.href}`,
    })),
    {
      '@type': 'ListItem' as const,
      position: crumbs.length + 1,
      name: pathname.split('/').pop() || 'Page',
      item: `${siteUrl}${pathname}`,
    },
  ];

  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: items,
  };

  return (
    <script
      type="application/ld+json"
      // Content is statically generated from trusted route-map data (not user input)
      dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
    />
  );
}
```

- [ ] **Step 2: Create PageJsonLd component**

```typescript
import { getSiteUrl } from '@/lib/site-url';

type SchemaType = 'FAQPage' | 'Article' | 'WebPage';

interface FAQItem {
  question: string;
  answer: string;
}

interface Props {
  type: SchemaType;
  title: string;
  description: string;
  pathname: string;
  faqItems?: FAQItem[];
  datePublished?: string;
  dateModified?: string;
  author?: string;
}

export function PageJsonLd({
  type, title, description, pathname,
  faqItems, datePublished, dateModified, author,
}: Props) {
  const siteUrl = getSiteUrl();
  const url = `${siteUrl}${pathname}`;
  const schemas: object[] = [];

  if (type === 'FAQPage' && faqItems?.length) {
    schemas.push({
      '@context': 'https://schema.org',
      '@type': 'FAQPage',
      mainEntity: faqItems.map((item) => ({
        '@type': 'Question',
        name: item.question,
        acceptedAnswer: { '@type': 'Answer', text: item.answer },
      })),
    });
  }

  if (type === 'Article') {
    schemas.push({
      '@context': 'https://schema.org',
      '@type': 'Article',
      headline: title,
      description,
      url,
      datePublished: datePublished ?? new Date().toISOString(),
      dateModified: dateModified ?? new Date().toISOString(),
      author: author
        ? { '@type': 'Person', name: author }
        : { '@type': 'Organization', name: 'Lap Coach' },
    });
  }

  if (type === 'WebPage' || schemas.length === 0) {
    schemas.push({
      '@context': 'https://schema.org',
      '@type': 'WebPage',
      name: title,
      description,
      url,
    });
  }

  return (
    <>
      {schemas.map((schema, i) => (
        <script
          key={i}
          type="application/ld+json"
          // Content is statically generated from trusted route-map + CMS data (not user input)
          dangerouslySetInnerHTML={{ __html: JSON.stringify(schema) }}
        />
      ))}
    </>
  );
}
```

- [ ] **Step 3: Create EntityGlossary component**

```typescript
const GLOSSARY = [
  { term: 'LAP', definition: 'Lap Analysis Platform — a motorsport telemetry analysis tool that scores driving and generates coaching insights.' },
  { term: 'Telemetry', definition: 'GPS coordinates and sensor data (speed, g-force, RPM) recorded by a data logger during a racing session.' },
  { term: 'Session', definition: 'One continuous recording from a data logger device, typically covering a practice, qualifying, or race stint.' },
  { term: 'Corner', definition: 'An auto-detected turn section of a racing track, identified from GPS trajectory curvature analysis.' },
  { term: 'Pillar Scores', definition: 'Four scoring dimensions — Pace, Consistency, Execution, Robustness — each scored out of 25 for a total of 100.' },
] as const;

export function EntityGlossary() {
  return (
    <details className="mt-12 border border-steel/20 rounded-lg">
      <summary className="cursor-pointer px-4 py-3 font-telemetry text-xs uppercase tracking-wider text-steel hover:text-chalk transition-colors">
        Glossary
      </summary>
      <dl className="px-4 pb-4 space-y-3">
        {GLOSSARY.map(({ term, definition }) => (
          <div key={term}>
            <dt className="font-monument text-sm text-chalk">{term}</dt>
            <dd className="text-sm text-steel font-body">{definition}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
```

- [ ] **Step 4: Create RelatedPages component**

```typescript
import Link from 'next/link';
import { routeMap } from '@/data/route-map';

interface Props {
  currentPath: string;
  maxLinks?: number;
}

export function RelatedPages({ currentPath, maxLinks = 4 }: Props) {
  const entry = routeMap[currentPath];
  if (!entry) return null;

  const siblings = Object.values(routeMap)
    .filter((r) =>
      r.path !== currentPath &&
      !r.noIndex &&
      r.metaDescription &&
      (r.parent === entry.parent || r.path === entry.parent),
    )
    .slice(0, maxLinks);

  if (siblings.length === 0) return null;

  return (
    <nav aria-label="Related pages" className="mt-16 border-t border-steel/20 pt-8">
      <h2 className="font-monument text-xs uppercase tracking-wider text-steel mb-4">
        Related Pages
      </h2>
      <ul className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {siblings.map((r) => (
          <li key={r.path}>
            <Link
              href={r.path}
              className="block p-3 rounded border border-steel/10 hover:border-gold/30 transition-colors"
            >
              <span className="font-monument text-sm text-chalk">{r.title}</span>
              {r.metaDescription && (
                <p className="text-xs text-steel mt-1 line-clamp-2 font-body">
                  {r.metaDescription.slice(0, 100)}
                </p>
              )}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
```

- [ ] **Step 5: Enhance root layout JSON-LD**

In `lap-website/src/app/layout.tsx`, add to the `@graph` array in the `jsonLd` object:

Add `WebSite` schema:
```typescript
{
  '@type': 'WebSite',
  name: BRAND.productName,
  url: siteUrl.href,
  potentialAction: {
    '@type': 'SearchAction',
    target: `${siteUrl.href}/insights?q={search_term_string}`,
    'query-input': 'required name=search_term_string',
  },
},
```

Add `featureList` to the existing `SoftwareApplication` entry:
```typescript
featureList: [
  'GPS telemetry ingestion from RaceChrono, RaceBox, AiM, MoTeC',
  'Automatic corner detection from GPS trajectory',
  'Four-pillar scoring: Pace, Consistency, Execution, Robustness',
  'Per-corner coaching insights',
  'Session-vs-session comparison with distance synchronization',
  'Track auto-detection from GPS coordinates',
  'PDF coaching reports',
],
```

- [ ] **Step 6: Verify build**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npm run build`
Expected: Build succeeds.

- [ ] **Step 7: Commit**

```bash
git add lap-website/src/components/seo/ lap-website/src/app/layout.tsx
git commit -m "feat(seo): BreadcrumbJsonLd, PageJsonLd, EntityGlossary, RelatedPages + enhanced root JSON-LD"
```

---

## Task 8: Marketing Page Schema Stacking + Meta Completeness

**Files:**
- Modify: `lap-website/src/app/(marketing)/pricing/page.tsx` (FAQPage + BreadcrumbJsonLd)
- Modify: `lap-website/src/app/(marketing)/help/page.tsx` (FAQPage + EntityGlossary)
- Modify: `lap-website/src/app/(marketing)/insights/[slug]/page.tsx` (Article schema)
- Modify: `lap-website/src/app/(marketing)/customers/page.tsx` (Review schema)
- Modify: marketing pages with `<time>` elements on dates

- [ ] **Step 1: Add schema to pricing page**

Import and render in the pricing page:

```typescript
import { BreadcrumbJsonLd } from '@/components/seo/BreadcrumbJsonLd';
import { PageJsonLd } from '@/components/seo/PageJsonLd';
```

Add before the main content:
```tsx
<BreadcrumbJsonLd pathname="/pricing" />
<PageJsonLd
  type="FAQPage"
  title="Pricing"
  description="Choose the right LAP plan for your racing programme."
  pathname="/pricing"
  faqItems={[
    { question: 'What file formats does LAP support?', answer: 'RaceChrono CSV, RaceBox CSV, AiM CSV, and MoTeC CSV with GPS data.' },
    { question: 'Can I switch plans?', answer: 'Yes, you can upgrade or downgrade at any time. Changes take effect on your next billing cycle.' },
    { question: 'Is there a free trial?', answer: 'The Demo tier is free forever with 3 analyses per month. No credit card required.' },
  ]}
/>
```

- [ ] **Step 2: Add schema to help page**

```typescript
import { BreadcrumbJsonLd } from '@/components/seo/BreadcrumbJsonLd';
import { PageJsonLd } from '@/components/seo/PageJsonLd';
import { EntityGlossary } from '@/components/seo/EntityGlossary';
import { RelatedPages } from '@/components/seo/RelatedPages';
```

Add `BreadcrumbJsonLd`, `PageJsonLd` (type FAQPage with the help page FAQ items), and at the bottom: `<EntityGlossary />` + `<RelatedPages currentPath="/help" />`.

- [ ] **Step 3: Add Article schema to insights pages**

In `lap-website/src/app/(marketing)/insights/[slug]/page.tsx`:

```typescript
import { BreadcrumbJsonLd } from '@/components/seo/BreadcrumbJsonLd';
import { PageJsonLd } from '@/components/seo/PageJsonLd';
```

```tsx
<BreadcrumbJsonLd pathname={`/insights/${entry.slug}`} />
<PageJsonLd
  type="Article"
  title={entry.title}
  description={entry.summary}
  pathname={`/insights/${entry.slug}`}
/>
```

- [ ] **Step 4: Add BreadcrumbJsonLd + RelatedPages to product page**

```typescript
import { BreadcrumbJsonLd } from '@/components/seo/BreadcrumbJsonLd';
import { EntityGlossary } from '@/components/seo/EntityGlossary';
import { RelatedPages } from '@/components/seo/RelatedPages';
```

Add at top: `<BreadcrumbJsonLd pathname="/product" />`
Add at bottom: `<EntityGlossary />` + `<RelatedPages currentPath="/product" />`

- [ ] **Step 5: Verify build**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npm run build`
Expected: Build succeeds.

- [ ] **Step 6: Commit**

```bash
git add lap-website/src/app/\(marketing\)/
git commit -m "feat(seo): JSON-LD schema stacking on pricing/help/insights/product + EntityGlossary + RelatedPages"
```

---

## Task 9: SEO Health Endpoint

**Files:**
- Create: `telemetry_tool/web/routes/seo_health.py`
- Modify: `telemetry_tool/web/app.py` (register blueprint)

- [ ] **Step 1: Write the SEO health endpoint**

```python
"""SEO health check — validates route metadata completeness.

GET /api/v1/seo/health — returns a report of SEO gaps across marketing routes.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

bp = Blueprint("seo_health", __name__, url_prefix="/api/v1/seo")

_ROUTE_MAP_PATH = (
    Path(__file__).resolve().parents[3] / "lap-website" / "src" / "data" / "route-map.ts"
)


def _parse_route_map() -> dict:
    """Extract route entries from route-map.ts (naive regex parse)."""
    if not _ROUTE_MAP_PATH.exists():
        return {}

    text = _ROUTE_MAP_PATH.read_text(encoding="utf-8")
    routes: dict = {}
    for match in re.finditer(r"'(/[^']*)':\s*\{([^}]+)\}", text):
        path = match.group(1)
        block = match.group(2)
        entry: dict = {"path": path}
        for field in ("title", "primaryKeyword", "metaDescription", "ogTitle", "ogDescription"):
            field_match = re.search(rf"{field}:\s*'([^']*)'", block)
            if field_match:
                entry[field] = field_match.group(1)
        entry["noIndex"] = "noIndex: true" in block
        routes[path] = entry
    return routes


@bp.route("/health", methods=["GET"])
def seo_health():
    """Return SEO completeness report for marketing routes."""
    routes = _parse_route_map()
    marketing = {k: v for k, v in routes.items() if not v.get("noIndex")}
    total = len(marketing)

    missing_meta = [k for k, v in marketing.items() if not v.get("metaDescription")]
    missing_keyword = [k for k, v in marketing.items() if not v.get("primaryKeyword")]
    missing_og = [k for k, v in marketing.items() if not v.get("ogTitle") and not v.get("ogDescription")]

    return jsonify({
        "ok": True,
        "data": {
            "total_marketing_routes": total,
            "routes_with_meta": total - len(missing_meta),
            "routes_missing_meta": missing_meta,
            "routes_missing_keyword": missing_keyword,
            "routes_missing_og": missing_og,
        },
    }), 200
```

- [ ] **Step 2: Register blueprint in app.py**

Add to `_blueprint_imports` in `telemetry_tool/web/app.py`:

```python
('.routes.seo_health',         'bp', 'seo_health_bp'),
```

- [ ] **Step 3: Commit**

```bash
git add telemetry_tool/web/routes/seo_health.py telemetry_tool/web/app.py
git commit -m "feat(api): SEO health endpoint — validates route metadata completeness"
```

---

## Task 10: Deploy and Verify

**Files:** None (deploy + smoke tests)

- [ ] **Step 1: Run backend tests**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai && python -m pytest telemetry_tool/tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 2: Run frontend tests + build**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npx vitest run && npm run build`
Expected: All tests pass, build succeeds.

- [ ] **Step 3: Deploy backend**

```bash
scp -r telemetry_tool/ root@46.225.227.24:/opt/lap-api/telemetry_tool/
scp alembic/versions/022_app_events.py root@46.225.227.24:/opt/lap-api/alembic/versions/
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml exec api alembic upgrade head && docker compose -f docker-compose.prod.yml build api && docker compose -f docker-compose.prod.yml up -d api"
```

- [ ] **Step 4: Verify backend health**

Run: `curl https://api.lap-coach.racing/healthz`
Expected: `{"status": "ok"}`

Run: `curl https://api.lap-coach.racing/api/v1/seo/health`
Expected: JSON with route completeness data.

- [ ] **Step 5: Deploy frontend**

Run: `cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npm run cf:deploy`
Expected: Cloudflare Workers deploy succeeds.

- [ ] **Step 6: Verify LLM files**

Run: `curl https://www.lap-coach.racing/llms.txt`
Expected: Plain text starting with `# LAP`

Run: `curl https://www.lap-coach.racing/llms-full.txt`
Expected: Longer plain text with FAQ, Pricing, Glossary sections.

- [ ] **Step 7: Verify robots.txt has AI crawler directives**

Run: `curl https://www.lap-coach.racing/robots.txt`
Expected: Contains directives for GPTBot, ClaudeBot, ChatGPT-User, PerplexityBot, CCBot (Disallow).
