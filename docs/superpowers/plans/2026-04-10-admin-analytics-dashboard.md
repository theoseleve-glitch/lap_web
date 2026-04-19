# Admin Analytics Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add rich engagement analytics dashboard and per-user drill-down to the existing `/admin` panel.

**Architecture:** 2 new backend sub-blueprints under the existing admin package (analytics + user_detail), registered in `__init__.py`. Frontend uses Recharts for charts, TanStack Query for data fetching, and follows existing admin UI patterns (dark cards, MetricCard, table styles). All admin endpoints are superadmin-gated via the existing `require_superadmin` decorator.

**Tech Stack:** Flask (backend), Recharts + Next.js 14 + TanStack Query (frontend), Vitest (frontend tests), pytest (backend tests)

---

## Task 1: Backend — Admin Analytics Endpoints

**Files:**
- Create: `telemetry_tool/web/routes/admin/analytics.py`
- Modify: `telemetry_tool/web/routes/admin/__init__.py`

- [ ] **Step 1: Create the analytics blueprint**

Create `telemetry_tool/web/routes/admin/analytics.py`:

```python
"""Admin analytics — engagement metrics from app_events.

Endpoints:
- GET /admin/analytics/dau       — daily active users + event counts
- GET /admin/analytics/features  — feature adoption by event type
- GET /admin/analytics/retention — weekly signup cohort retention
- GET /admin/analytics/timeline  — most recent events with user info
- GET /admin/analytics/storage   — platform-wide storage summary
"""
from __future__ import annotations

import logging

from flask import Blueprint, request

from web.api_utils import api_response

from .middleware import require_superadmin

logger = logging.getLogger(__name__)

bp = Blueprint("admin_analytics", __name__)


def _get_conn():
    from web.db_pg import get_pg_connection
    return get_pg_connection()


def _serialize_row(row):
    r = dict(row) if not isinstance(row, dict) else row
    result = {}
    for k, v in r.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


@bp.route("/analytics/dau", methods=["GET"])
@require_superadmin
def analytics_dau():
    """Daily active users and event counts over a time window."""
    days = request.args.get("days", 30, type=int)
    days = min(days, 365)
    conn = _get_conn()

    rows = conn.execute(
        """
        SELECT date_trunc('day', created_at)::date AS date,
               COUNT(DISTINCT user_id) AS users,
               COUNT(*) AS events
        FROM app_events
        WHERE created_at >= now() - make_interval(days => %(days)s)
        GROUP BY 1 ORDER BY 1
        """,
        {"days": days},
    ).fetchall()
    daily = [_serialize_row(r) for r in rows]

    summary_row = conn.execute(
        """
        SELECT
          (SELECT COUNT(DISTINCT user_id) FROM app_events
           WHERE created_at >= date_trunc('day', now())) AS dau_today,
          (SELECT COUNT(DISTINCT user_id) FROM app_events
           WHERE created_at >= now() - interval '7 days') AS wau_7d,
          (SELECT COUNT(*) FROM app_events
           WHERE created_at >= now() - interval '30 days') AS total_events_30d,
          (SELECT COUNT(DISTINCT event_type) FROM app_events
           WHERE created_at >= now() - interval '30 days') AS unique_features
        """
    ).fetchone()

    return api_response({
        "days": daily,
        "summary": _serialize_row(summary_row) if summary_row else {},
    })


@bp.route("/analytics/features", methods=["GET"])
@require_superadmin
def analytics_features():
    """Feature adoption ranked by usage."""
    days = request.args.get("days", 30, type=int)
    days = min(days, 365)
    conn = _get_conn()

    rows = conn.execute(
        """
        SELECT event_type,
               COUNT(*) AS count,
               COUNT(DISTINCT user_id) AS unique_users
        FROM app_events
        WHERE created_at >= now() - make_interval(days => %(days)s)
        GROUP BY event_type
        ORDER BY count DESC
        LIMIT 15
        """,
        {"days": days},
    ).fetchall()

    return api_response({
        "features": [_serialize_row(r) for r in rows],
    })


@bp.route("/analytics/retention", methods=["GET"])
@require_superadmin
def analytics_retention():
    """Weekly signup cohort retention."""
    weeks = request.args.get("weeks", 8, type=int)
    weeks = min(weeks, 26)
    conn = _get_conn()

    rows = conn.execute(
        """
        WITH cohorts AS (
            SELECT id AS user_id,
                   date_trunc('week', created_at)::date AS cohort_week
            FROM users
            WHERE created_at >= now() - make_interval(weeks => %(weeks)s)
              AND deleted_at IS NULL
        ),
        week_offsets AS (
            SELECT generate_series(0, %(weeks)s) AS week_offset
        ),
        activity AS (
            SELECT c.cohort_week,
                   c.user_id,
                   wo.week_offset,
                   EXISTS (
                       SELECT 1 FROM app_events e
                       WHERE e.user_id = c.user_id
                         AND e.created_at >= c.cohort_week + make_interval(weeks => wo.week_offset)
                         AND e.created_at <  c.cohort_week + make_interval(weeks => wo.week_offset + 1)
                   ) AS was_active
            FROM cohorts c
            CROSS JOIN week_offsets wo
            WHERE c.cohort_week + make_interval(weeks => wo.week_offset) <= now()
        )
        SELECT cohort_week,
               COUNT(DISTINCT user_id) AS cohort_size,
               week_offset,
               COUNT(DISTINCT user_id) FILTER (WHERE was_active) AS active_count
        FROM activity
        GROUP BY cohort_week, week_offset
        ORDER BY cohort_week, week_offset
        """,
        {"weeks": weeks},
    ).fetchall()

    cohorts_map: dict = {}
    for row in rows:
        r = _serialize_row(row)
        cw = r["cohort_week"]
        if cw not in cohorts_map:
            cohorts_map[cw] = {"week": cw, "size": r["cohort_size"], "retention": []}
        size = cohorts_map[cw]["size"]
        pct = round(r["active_count"] / size * 100, 1) if size > 0 else 0
        cohorts_map[cw]["retention"].append(pct)

    return api_response({
        "cohorts": list(cohorts_map.values()),
    })


@bp.route("/analytics/timeline", methods=["GET"])
@require_superadmin
def analytics_timeline():
    """Most recent events with user info."""
    limit = request.args.get("limit", 50, type=int)
    limit = min(limit, 200)
    conn = _get_conn()

    rows = conn.execute(
        """
        SELECT e.event_type,
               u.email AS user_email,
               u.display_name AS user_name,
               e.path,
               e.properties,
               e.created_at
        FROM app_events e
        JOIN users u ON e.user_id = u.id
        ORDER BY e.created_at DESC
        LIMIT %(limit)s
        """,
        {"limit": limit},
    ).fetchall()

    return api_response({
        "events": [_serialize_row(r) for r in rows],
    })


@bp.route("/analytics/storage", methods=["GET"])
@require_superadmin
def analytics_storage():
    """Platform-wide storage summary."""
    conn = _get_conn()

    row = conn.execute(
        """
        SELECT
          COALESCE(SUM(file_size), 0) AS total_storage_bytes,
          COALESCE(AVG(file_size), 0) AS avg_storage_per_session_bytes,
          COUNT(*) AS total_sessions,
          COUNT(DISTINCT user_id) AS total_users_with_data
        FROM ingestion_jobs
        WHERE status = 'completed'
        """
    ).fetchone()

    return api_response(_serialize_row(row) if row else {
        "total_storage_bytes": 0,
        "avg_storage_per_session_bytes": 0,
        "total_sessions": 0,
        "total_users_with_data": 0,
    })
```

- [ ] **Step 2: Register the blueprint in `__init__.py`**

In `telemetry_tool/web/routes/admin/__init__.py`, add after the existing imports (around line 46):

```python
from .analytics import bp as analytics_bp  # noqa: E402
```

And add `analytics_bp` to the registration loop list (around line 48-51):

```python
for _sub_bp in [health_bp, users_bp, jobs_bp, billing_admin_bp,
                entitlements_bp, email_bp, security_bp, infra_bp,
                training_bp, monitoring_bp, analytics_bp]:
```

- [ ] **Step 3: Commit**

```bash
git add telemetry_tool/web/routes/admin/analytics.py telemetry_tool/web/routes/admin/__init__.py
git commit -m "feat(admin): analytics endpoints — DAU, features, retention, timeline, storage"
```

---

## Task 2: Backend — Per-User Detail Endpoints

**Files:**
- Create: `telemetry_tool/web/routes/admin/user_detail.py`
- Modify: `telemetry_tool/web/routes/admin/__init__.py`

- [ ] **Step 1: Create the user detail blueprint**

Create `telemetry_tool/web/routes/admin/user_detail.py`:

```python
"""Admin per-user detail — activity summary and storage metrics.

Endpoints:
- GET /admin/users/<id>/activity — 30-day activity summary
- GET /admin/users/<id>/storage  — storage, reports, and quota usage
"""
from __future__ import annotations

import logging

from flask import Blueprint

from web.api_utils import ErrorCode, api_error, api_response

from .middleware import require_superadmin

logger = logging.getLogger(__name__)

bp = Blueprint("admin_user_detail", __name__)


def _get_conn():
    from web.db_pg import get_pg_connection
    return get_pg_connection()


def _serialize_row(row):
    r = dict(row) if not isinstance(row, dict) else row
    result = {}
    for k, v in r.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


def _user_exists(conn, user_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM users WHERE id = %(uid)s AND deleted_at IS NULL",
        {"uid": user_id},
    ).fetchone()
    return row is not None


@bp.route("/users/<int:user_id>/activity", methods=["GET"])
@require_superadmin
def user_activity(user_id: int):
    """30-day activity summary for a specific user."""
    conn = _get_conn()

    if not _user_exists(conn, user_id):
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    # Aggregate metrics
    stats = conn.execute(
        """
        SELECT
          COUNT(*) AS events_30d,
          MAX(created_at) AS last_active,
          COUNT(*) FILTER (WHERE event_type = 'session.view') AS sessions_viewed,
          COUNT(*) FILTER (WHERE event_type = 'session.upload') AS uploads_30d
        FROM app_events
        WHERE user_id = %(uid)s
          AND created_at >= now() - interval '30 days'
        """,
        {"uid": user_id},
    ).fetchone()

    # Top features
    top_rows = conn.execute(
        """
        SELECT event_type, COUNT(*) AS count
        FROM app_events
        WHERE user_id = %(uid)s
          AND created_at >= now() - interval '30 days'
        GROUP BY event_type
        ORDER BY count DESC
        LIMIT 5
        """,
        {"uid": user_id},
    ).fetchall()

    # Recent events
    recent_rows = conn.execute(
        """
        SELECT event_type, path, properties, created_at
        FROM app_events
        WHERE user_id = %(uid)s
        ORDER BY created_at DESC
        LIMIT 20
        """,
        {"uid": user_id},
    ).fetchall()

    stats_dict = _serialize_row(stats) if stats else {}
    return api_response({
        "events_30d": stats_dict.get("events_30d", 0),
        "last_active": stats_dict.get("last_active"),
        "sessions_viewed": stats_dict.get("sessions_viewed", 0),
        "uploads_30d": stats_dict.get("uploads_30d", 0),
        "top_features": [_serialize_row(r) for r in top_rows],
        "recent": [_serialize_row(r) for r in recent_rows],
    })


@bp.route("/users/<int:user_id>/storage", methods=["GET"])
@require_superadmin
def user_storage(user_id: int):
    """Storage, reports, and quota usage for a specific user."""
    conn = _get_conn()

    if not _user_exists(conn, user_id):
        return api_error(ErrorCode.NOT_FOUND, "User not found", status=404)

    # Session/upload storage from ingestion_jobs
    storage = conn.execute(
        """
        SELECT
          COUNT(*) AS total_reports,
          COUNT(*) FILTER (
              WHERE created_at >= date_trunc('month', now())
          ) AS reports_this_month,
          COALESCE(SUM(file_size), 0) AS total_storage_bytes,
          COALESCE(AVG(file_size), 0) AS avg_storage_per_session_bytes
        FROM ingestion_jobs
        WHERE user_id = %(uid)s
          AND status = 'completed'
        """,
        {"uid": user_id},
    ).fetchone()

    # Plan limits from entitlements
    try:
        from auth.entitlements import get_user_entitlements
        ents = get_user_entitlements(conn, user_id=user_id)
        plan_tier = ents.get("plan_tier", "demo")
        analyses_limit = ents.get("analyses_per_month", 0)
        analyses_used = ents.get("analyses_used", 0)
        max_upload_mb = ents.get("max_upload_size_mb", 0)
    except Exception:
        plan_tier = "demo"
        analyses_limit = 0
        analyses_used = 0
        max_upload_mb = 50

    storage_dict = _serialize_row(storage) if storage else {}
    total_bytes = storage_dict.get("total_storage_bytes", 0)
    limit_bytes = int(max_upload_mb * 1024 * 1024) if max_upload_mb else 0
    storage_pct = round(total_bytes / limit_bytes * 100, 1) if limit_bytes > 0 else 0

    return api_response({
        "total_reports": storage_dict.get("total_reports", 0),
        "reports_this_month": storage_dict.get("reports_this_month", 0),
        "total_storage_bytes": total_bytes,
        "avg_storage_per_session_bytes": storage_dict.get("avg_storage_per_session_bytes", 0),
        "plan_tier": plan_tier,
        "plan_storage_limit_bytes": limit_bytes,
        "storage_pct": storage_pct,
        "analyses_used": analyses_used,
        "analyses_limit": analyses_limit,
    })
```

- [ ] **Step 2: Register in `__init__.py`**

Add after the analytics import:

```python
from .user_detail import bp as user_detail_bp  # noqa: E402
```

And add `user_detail_bp` to the loop:

```python
for _sub_bp in [health_bp, users_bp, jobs_bp, billing_admin_bp,
                entitlements_bp, email_bp, security_bp, infra_bp,
                training_bp, monitoring_bp, analytics_bp, user_detail_bp]:
```

- [ ] **Step 3: Commit**

```bash
git add telemetry_tool/web/routes/admin/user_detail.py telemetry_tool/web/routes/admin/__init__.py
git commit -m "feat(admin): per-user activity + storage endpoints"
```

---

## Task 3: Frontend — Install Recharts + Chart Components

**Files:**
- Modify: `lap-website/package.json` (install recharts)
- Create: `lap-website/src/components/admin/DauChart.tsx`
- Create: `lap-website/src/components/admin/FeatureAdoptionChart.tsx`
- Create: `lap-website/src/components/admin/RetentionPanel.tsx`
- Create: `lap-website/src/components/admin/EventTimeline.tsx`
- Create: `lap-website/src/components/admin/StorageBar.tsx`

- [ ] **Step 1: Install recharts**

```bash
cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npm install recharts
```

- [ ] **Step 2: Create DauChart component**

Create `lap-website/src/components/admin/DauChart.tsx`:

A `'use client'` component that:
- Takes `data: { date: string; users: number; events: number }[]`
- Renders a Recharts `ResponsiveContainer` > `AreaChart` with acid-green gradient fill
- Period selector buttons (7d/30d/90d) that call `onPeriodChange(days: number)`
- Tooltip showing date, users, events
- Card wrapper matching admin style: `rounded-lg border border-white/10 bg-white/[0.03] p-5`

Props: `data`, `period` (number), `onPeriodChange` (callback).

Uses: `AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid` from `recharts`.

- [ ] **Step 3: Create FeatureAdoptionChart component**

Create `lap-website/src/components/admin/FeatureAdoptionChart.tsx`:

A `'use client'` component that:
- Takes `data: { event_type: string; count: number; unique_users: number }[]`
- Renders horizontal `BarChart` with gold bars
- Y-axis: humanized event names (`session.view` -> `Session View`)
- Annotation text for unique_users per bar
- Card wrapper

Uses: `BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer` from `recharts`.

Humanize function: `event_type.split('.').map(w => w[0].toUpperCase() + w.slice(1)).join(' ')`

- [ ] **Step 4: Create RetentionPanel component**

Create `lap-website/src/components/admin/RetentionPanel.tsx`:

A `'use client'` component with a `useState` toggle between `'table'` and `'chart'` views.

Takes `data: { week: string; size: number; retention: number[] }[]`.

**Table view**: HTML `<table>` with:
- Header: Cohort | Size | W0 | W1 | W2 | ... (up to max retention length)
- Rows: cohort week date | size | percentage cells
- Cell background: `rgba(34, 197, 94, ${pct / 100 * 0.35})`

**Chart view**: Recharts `LineChart` with one `Line` per cohort.
- X-axis: week offset labels (W0, W1, W2...)
- Y-axis: 0-100%
- Color palette: `['#22c55e', '#C9A84C', '#8B5CF6', '#949494']`

Toggle buttons styled like the DAU period selector.

- [ ] **Step 5: Create EventTimeline component**

Create `lap-website/src/components/admin/EventTimeline.tsx`:

Takes `data: { event_type: string; user_email: string; user_name: string | null; path: string; properties: Record<string, unknown>; created_at: string }[]`.

Renders a scrollable list (`max-h-[400px] overflow-y-auto`) with rows showing:
- Timestamp (formatted HH:mm:ss)
- User email (truncated)
- Event badge with color based on prefix:
  - `session.*`: gold (`bg-[#C9A84C]/15 text-[#C9A84C] border-[#C9A84C]/30`)
  - `chart.*`, `compare.*`: racing-purple (`bg-[#8B5CF6]/15 text-[#8B5CF6]`)
  - `report.*`: acid-green
  - `limit.*`: safety-red
  - default: white/10
- Path

Card wrapper.

- [ ] **Step 6: Create StorageBar component**

Create `lap-website/src/components/admin/StorageBar.tsx`:

Takes `label: string`, `used: number`, `limit: number`, `unit: string` (e.g. "MB", "analyses"), `formatValue?: (n: number) => string`.

Renders:
- Label + value text (`used / limit (pct%)`)
- Progress bar div with width = `pct%`
- Color: green if pct < 60, gold if 60-80, red if > 80
- Subtitle showing remaining

```typescript
const pct = limit > 0 ? Math.min((used / limit) * 100, 100) : 0;
const color = pct < 60 ? '#22c55e' : pct < 80 ? '#C9A84C' : '#FF2A2A';
```

- [ ] **Step 7: Verify build**

```bash
cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npm run build
```

- [ ] **Step 8: Commit**

```bash
git add lap-website/package.json lap-website/package-lock.json lap-website/src/components/admin/
git commit -m "feat(admin): Recharts chart components — DauChart, FeatureAdoption, RetentionPanel, EventTimeline, StorageBar"
```

---

## Task 4: Frontend — Analytics Dashboard Page

**Files:**
- Create: `lap-website/src/app/admin/analytics/page.tsx`
- Modify: `lap-website/src/app/admin/layout.tsx`

- [ ] **Step 1: Create the analytics page**

Create `lap-website/src/app/admin/analytics/page.tsx`:

A `'use client'` page component that:

1. Uses `useState` for DAU period (default 30).
2. Fetches 5 endpoints via `useQuery`:
   - `admin-dau`: `apiFetch('/admin/analytics/dau?days=${period}')` refetchInterval 30s
   - `admin-features`: `apiFetch('/admin/analytics/features?days=30')` refetchInterval 60s
   - `admin-retention`: `apiFetch('/admin/analytics/retention?weeks=8')` refetchInterval 60s
   - `admin-timeline`: `apiFetch('/admin/analytics/timeline?limit=50')` refetchInterval 30s
   - `admin-storage`: `apiFetch('/admin/analytics/storage')` refetchInterval 60s

3. Renders:
   - `<h1>` "Analytics"
   - **Summary bar**: 6 MetricCards in `grid-cols-3 md:grid-cols-6`:
     - DAU Today: `dau.summary.dau_today`
     - WAU (7d): `dau.summary.wau_7d`
     - Events (30d): `dau.summary.total_events_30d`
     - Features: `dau.summary.unique_features`
     - Total Storage: format `storage.total_storage_bytes` as GB/MB
     - Avg/User: format `storage.avg_storage_per_session_bytes`
   - `<DauChart>` with `data={dau.days}` `period={period}` `onPeriodChange={setPeriod}`
   - `<FeatureAdoptionChart>` with `data={features.features}`
   - `<RetentionPanel>` with `data={retention.cohorts}`
   - `<EventTimeline>` with `data={timeline.events}`

Reuse the existing `MetricCard` pattern from `/admin/page.tsx` — inline it (simple div with label + value + optional sub).

Format bytes helper: `function formatBytes(bytes: number): string` — returns "X.X GB", "X.X MB", or "X KB".

- [ ] **Step 2: Add Analytics to admin nav**

In `lap-website/src/app/admin/layout.tsx`, update `adminNav`:

```typescript
const adminNav = [
  { href: "/admin", label: "Dashboard", icon: "\u25C9" },
  { href: "/admin/analytics", label: "Analytics", icon: "\u25C8" },
  { href: "/admin/users", label: "Users", icon: "\u25CE" },
  { href: "/admin/audit", label: "Audit Log", icon: "\u2630" },
];
```

- [ ] **Step 3: Verify build**

```bash
cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add lap-website/src/app/admin/analytics/ lap-website/src/app/admin/layout.tsx
git commit -m "feat(admin): analytics dashboard page — DAU chart, feature adoption, retention, timeline"
```

---

## Task 5: Frontend — Per-User Drill-Down Page

**Files:**
- Create: `lap-website/src/app/admin/users/[id]/page.tsx`
- Modify: `lap-website/src/app/admin/users/page.tsx`

- [ ] **Step 1: Create the user detail page**

Create `lap-website/src/app/admin/users/[id]/page.tsx`:

A `'use client'` page that:

1. Extracts `id` from `useParams()`.
2. Fetches 3 endpoints via `useQuery`:
   - `admin-user-${id}`: `apiFetch('/admin/users/${id}')` — existing endpoint for user profile
   - `admin-user-${id}-activity`: `apiFetch('/admin/users/${id}/activity')`
   - `admin-user-${id}-storage`: `apiFetch('/admin/users/${id}/storage')`

3. Renders:
   - **Back link**: `<Link href="/admin/users">` "← Back to Users"
   - **User header**: avatar circle (first letter, gold bg), name, email, plan badge, status badge, join date
   - **Two-column grid** (`grid-cols-1 md:grid-cols-2 gap-4`):
     - Left: **Activity Panel** — 2x2 metric grid (Events, Last Active, Sessions Viewed, Uploads) + Top Features list
     - Right: **Storage & Reports Panel** — 2x2 metric grid (Total Reports, This Month, Total Storage, Avg/Session) + `<StorageBar>` for storage + `<StorageBar>` for analyses quota
   - **Recent Events table** (full width) — columns: Time, Event (badge), Path, Details

Plan badge color: acid-green for active subscriptions, white/10 for demo/free.
Status badge: safety-red for suspended, acid-green for active.

Use `formatBytes()` (same helper as analytics page — can inline or import).

- [ ] **Step 2: Make user rows clickable in the users list**

In `lap-website/src/app/admin/users/page.tsx`, wrap each user table row in a `<Link>`:

Find the `<tr key={user.id}>` (around line 92) and add:
- Import `Link` from `next/link` at the top
- Add an onClick or wrap the first `<td>` content in a Link:

Add a "View" link in the Actions column, before the suspend/unsuspend buttons:

```tsx
<Link
  href={`/admin/users/${user.id}`}
  className="rounded px-2 py-1 text-xs text-white/50 hover:bg-white/10 hover:text-white"
>
  View
</Link>
```

- [ ] **Step 3: Verify build**

```bash
cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add lap-website/src/app/admin/users/ 
git commit -m "feat(admin): per-user drill-down page — activity, storage, reports, recent events"
```

---

## Task 6: Deploy and Verify

- [ ] **Step 1: Run frontend build**

```bash
cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npm run build
```

- [ ] **Step 2: Deploy backend**

```bash
scp -r telemetry_tool/web/routes/admin/ root@46.225.227.24:/opt/lap-api/telemetry_tool/telemetry_tool/web/routes/admin/
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml build api && docker compose -f docker-compose.prod.yml up -d api"
```

- [ ] **Step 3: Verify backend health**

```bash
curl https://api.lap-coach.racing/healthz
```

- [ ] **Step 4: Deploy frontend**

```bash
cd C:/Users/Admin/Documents/Telemetry/Analysis/V2_claude_ai/lap-website && npm run cf:deploy
```

- [ ] **Step 5: Verify admin pages**

Open `https://www.lap-coach.racing/admin/analytics` — verify all 5 sections render.
Open `https://www.lap-coach.racing/admin/users` — verify "View" link appears, click to drill-down page.
