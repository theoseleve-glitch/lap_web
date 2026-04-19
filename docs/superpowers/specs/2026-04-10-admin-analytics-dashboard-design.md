# Admin Analytics Dashboard + Per-User Drill-Down

**Date**: 2026-04-10
**Branch**: `feat/logger-download-sync`
**Status**: Approved

## Overview

Extend the existing `/admin` panel with two new pages:

1. **`/admin/analytics`** — Rich engagement dashboard with DAU chart, feature adoption bars, retention cohort table/chart, and event timeline.
2. **`/admin/users/[id]`** — Per-user detail page with activity summary, storage & reports metrics, quota progress bars, and recent event history.

Both pages use Recharts for visualizations and follow the existing admin UI patterns (dark cards, MetricCard component, TanStack Query for data fetching, superadmin gate).

## Backend API — New Admin Endpoints

All endpoints require `is_platform_admin` (existing admin middleware). All queries run against `app_events` + `sessions` + `users` tables.

### Analytics Endpoints

#### `GET /admin/analytics/dau`

Query params: `days` (default 30)

Returns daily active users and event counts:
```json
{
  "ok": true,
  "data": {
    "days": [
      { "date": "2026-04-09", "users": 12, "events": 247 },
      { "date": "2026-04-10", "users": 14, "events": 312 }
    ],
    "summary": {
      "dau_today": 14,
      "wau_7d": 38,
      "total_events_30d": 2847,
      "unique_features": 9
    }
  }
}
```

SQL: `SELECT date_trunc('day', created_at)::date AS date, COUNT(DISTINCT user_id) AS users, COUNT(*) AS events FROM app_events WHERE created_at >= now() - interval '${days} days' GROUP BY 1 ORDER BY 1`

Summary: separate queries for DAU (today), WAU (7d distinct), total events (30d), unique features (30d distinct event_type).

#### `GET /admin/analytics/features`

Query params: `days` (default 30)

Returns feature adoption ranked by usage:
```json
{
  "ok": true,
  "data": {
    "features": [
      { "event_type": "session.view", "count": 847, "unique_users": 38 },
      { "event_type": "chart.interact", "count": 614, "unique_users": 31 }
    ]
  }
}
```

SQL: `SELECT event_type, COUNT(*) AS count, COUNT(DISTINCT user_id) AS unique_users FROM app_events WHERE created_at >= now() - interval '${days} days' GROUP BY event_type ORDER BY count DESC LIMIT 15`

#### `GET /admin/analytics/retention`

Query params: `weeks` (default 8)

Returns weekly signup cohorts with retention percentages:
```json
{
  "ok": true,
  "data": {
    "cohorts": [
      {
        "week": "2026-03-10",
        "size": 12,
        "retention": [100, 83, 67, 50, 42]
      },
      {
        "week": "2026-03-17",
        "size": 8,
        "retention": [100, 75, 63, 38]
      }
    ]
  }
}
```

SQL approach:
1. Bucket users by `date_trunc('week', users.created_at)` for cohort assignment.
2. For each cohort week, check which users had any `app_events` in week 0, week 1, ..., week N.
3. Return percentage: `active_in_week_n / cohort_size * 100`.

This is a single query with a CTE: generate cohort buckets, cross-join with week offsets, left join app_events to check activity, then aggregate.

#### `GET /admin/analytics/timeline`

Query params: `limit` (default 50)

Returns most recent events with user info:
```json
{
  "ok": true,
  "data": {
    "events": [
      {
        "event_type": "session.view",
        "user_email": "alex@team-apex.com",
        "user_name": "Alex Dupont",
        "path": "/app/sessions/847",
        "properties": { "session_id": "847" },
        "created_at": "2026-04-10T14:32:01Z"
      }
    ]
  }
}
```

SQL: `SELECT e.event_type, u.email AS user_email, u.display_name AS user_name, e.path, e.properties, e.created_at FROM app_events e JOIN users u ON e.user_id = u.id ORDER BY e.created_at DESC LIMIT ${limit}`

#### `GET /admin/analytics/storage`

Returns platform-wide storage summary:
```json
{
  "ok": true,
  "data": {
    "total_storage_bytes": 4509715456,
    "avg_storage_per_user_bytes": 112742886,
    "total_sessions": 1247,
    "total_users_with_data": 40
  }
}
```

SQL: Aggregate `file_size` or raw data size from sessions table across all workspaces.

### Per-User Endpoints

#### `GET /admin/users/{id}/activity`

Returns 30-day activity summary for a specific user:
```json
{
  "ok": true,
  "data": {
    "events_30d": 247,
    "last_active": "2026-04-10T14:32:01Z",
    "sessions_viewed": 38,
    "uploads_30d": 12,
    "top_features": [
      { "event_type": "session.view", "count": 94 },
      { "event_type": "chart.interact", "count": 67 },
      { "event_type": "compare.run", "count": 31 },
      { "event_type": "session.tab_switch", "count": 28 },
      { "event_type": "report.download", "count": 15 }
    ],
    "recent": [
      {
        "event_type": "session.view",
        "path": "/app/sessions/847",
        "properties": { "session_id": "847" },
        "created_at": "2026-04-10T14:32:01Z"
      }
    ]
  }
}
```

Queries `app_events` filtered by user_id. `recent` limited to last 20 events.

#### `GET /admin/users/{id}/storage`

Returns storage and report metrics for a specific user:
```json
{
  "ok": true,
  "data": {
    "total_reports": 47,
    "reports_this_month": 8,
    "total_storage_bytes": 358612992,
    "avg_storage_per_session_bytes": 7630063,
    "plan_storage_limit_bytes": 524288000,
    "storage_pct": 68.4,
    "analyses_used": 8,
    "analyses_limit": 50
  }
}
```

Queries:
- `total_reports`: `COUNT(*)` from sessions where uploader is this user.
- `reports_this_month`: same, filtered by current billing period start.
- `total_storage_bytes`: `SUM(file_size)` from sessions (or upload records).
- `avg_storage_per_session_bytes`: `AVG(file_size)`.
- `plan_storage_limit_bytes`: from entitlement snapshot for user's plan tier.
- `storage_pct`: `total / limit * 100`.
- `analyses_used` / `analyses_limit`: from existing entitlement snapshot.

## Frontend — Analytics Dashboard Page

### Route: `/admin/analytics`

New page added to the existing admin layout sidebar (`adminNav` in `layout.tsx`).

### Dependencies

- `recharts` (new npm dependency, ~40KB gzipped) — `AreaChart`, `BarChart`, `LineChart`, `ResponsiveContainer`, `Tooltip`, `XAxis`, `YAxis`, `Area`, `Bar`, `Line`, `CartesianGrid`
- Existing: `@tanstack/react-query`, `apiFetch`

### Components

#### `AdminAnalyticsPage` (`/admin/analytics/page.tsx`)

Top-level page component. Fetches all 5 data endpoints via `useQuery` with 30s `refetchInterval` for DAU/timeline, 60s for features/retention/storage.

Layout: single scrollable column with 5 card sections.

#### Summary Bar

6 MetricCards in a `grid-cols-3 md:grid-cols-6` grid:
- DAU (today)
- WAU (7-day)
- Events (30d)
- Features Used
- Total Storage (formatted as GB/MB)
- Avg Storage/User

Uses existing `MetricCard` pattern from `/admin/page.tsx`.

#### `DauChart` component

Recharts `AreaChart` with:
- X-axis: date (formatted as "Apr 9")
- Y-axis: user count
- Fill: `#22c55e` (acid-green) at 20% opacity gradient
- Stroke: `#22c55e`
- Tooltip: date + exact user count + event count
- Period selector: 7d / 30d / 90d buttons, active state uses `acid-green` colors

#### `FeatureAdoptionChart` component

Recharts horizontal `BarChart`:
- Y-axis: event type labels (humanized: `session.view` -> "Session View")
- X-axis: count
- Bar fill: `#C9A84C` (gold)
- Secondary annotation: unique user count per feature
- Sorted descending by count

#### `RetentionPanel` component

Toggle between two views via `useState`:

**Table view** (default):
- HTML `<table>` — rows = cohort week, columns = Week 0 through Week N
- First column: cohort start date (e.g. "Mar 10") + cohort size
- Cell values: percentage (e.g. "83%")
- Cell background: `rgba(34, 197, 94, opacity)` where opacity = `percentage / 100 * 0.35`
- Empty cells (future weeks): show "—" in muted color

**Chart view**:
- Recharts `LineChart` with one `Line` per cohort
- X-axis: weeks since signup (W0, W1, W2...)
- Y-axis: % retained (0-100)
- Each cohort line labeled by start date
- Color palette cycles through: acid-green, gold, racing-purple, steel

Toggle: two buttons ("Table" / "Chart") matching the period selector style.

#### `EventTimeline` component

Scrollable list (max-height with overflow-y-auto):
- Each row: timestamp, user email/name, event type badge (color-coded), path
- Event badge colors:
  - `session.*`: gold
  - `chart.*`: racing-purple
  - `compare.*`: racing-purple
  - `page.*`: steel
  - `report.*`: acid-green
  - `limit.*`: safety-red
- Auto-refreshes every 30s

## Frontend — Per-User Drill-Down Page

### Route: `/admin/users/[id]/page.tsx`

Accessed by clicking a user row in the existing `/admin/users` table. Back link returns to the user list.

### Layout

Three sections stacked:

#### User Header

Full-width bar with:
- Avatar circle (first letter of name, gold background)
- Name + email
- Plan tier badge (acid-green for active plans)
- Subscription status badge
- Join date

#### Two-Column Grid (Activity + Storage)

**Left: Activity Panel**
- 2x2 grid of small metrics: Events (30d), Last Active, Sessions Viewed, Uploads
- "Top Features" list: 5 rows with event type name + count, right-aligned
- All data from `GET /admin/users/{id}/activity`

**Right: Storage & Reports Panel**
- 2x2 grid: Total Reports, This Month, Total Storage, Avg/Session
- Storage progress bar:
  - Shows `used / limit (pct%)`
  - Color: green (< 60%), gold (60-80%), red (> 80%)
  - Subtitle: "X MB remaining on Y plan"
- Analyses quota bar:
  - Shows `used / limit (pct%)`
  - Same color logic
  - Subtitle: "X analyses remaining"
- All data from `GET /admin/users/{id}/storage`

#### Full-Width Recent Events Table

HTML `<table>` with columns: Time, Event (color-coded badge), Path, Details (properties rendered inline).
- 20 most recent events from `GET /admin/users/{id}/activity` `.recent` field
- Same badge color scheme as the analytics timeline

### Linking from Users List

Modify existing `/admin/users/page.tsx`: make each user row a `<Link>` to `/admin/users/${user.id}`. Add a small chevron or "View" link in the last column.

## Admin Layout Changes

Add "Analytics" to `adminNav` in `/admin/layout.tsx`:

```typescript
const adminNav = [
  { href: "/admin", label: "Dashboard", icon: "◉" },
  { href: "/admin/analytics", label: "Analytics", icon: "◈" },
  { href: "/admin/users", label: "Users", icon: "◎" },
  { href: "/admin/audit", label: "Audit Log", icon: "☰" },
];
```

## Files Changed

### Backend (new)
- `telemetry_tool/web/routes/admin/analytics.py` — 5 analytics endpoints (dau, features, retention, timeline, storage)
- `telemetry_tool/web/routes/admin/user_detail.py` — 2 per-user endpoints (activity, storage)

### Backend (modified)
- `telemetry_tool/web/routes/admin/__init__.py` — register new blueprints

### Frontend (new)
- `lap-website/src/app/admin/analytics/page.tsx` — analytics dashboard page
- `lap-website/src/app/admin/users/[id]/page.tsx` — per-user drill-down page
- `lap-website/src/components/admin/DauChart.tsx` — Recharts area chart
- `lap-website/src/components/admin/FeatureAdoptionChart.tsx` — Recharts horizontal bar chart
- `lap-website/src/components/admin/RetentionPanel.tsx` — table + line chart toggle
- `lap-website/src/components/admin/EventTimeline.tsx` — scrollable event feed
- `lap-website/src/components/admin/StorageBar.tsx` — color-coded progress bar
- `lap-website/src/components/admin/UserActivityPanel.tsx` — activity metrics + top features
- `lap-website/src/components/admin/UserStoragePanel.tsx` — storage + reports + quota bars

### Frontend (modified)
- `lap-website/src/app/admin/layout.tsx` — add Analytics to sidebar nav
- `lap-website/src/app/admin/users/page.tsx` — make user rows clickable links
- `lap-website/package.json` — add `recharts` dependency

## Dependencies

- New npm: `recharts` (~40KB gzipped)
- No new Python packages — uses existing psycopg2, Flask blueprints
- Requires `app_events` table from migration 052 (already deployed)

## Rollout

1. Backend: add analytics + user_detail blueprints, register in admin init, deploy.
2. Frontend: install recharts, create components + pages, modify layout + users list, build, deploy.
3. Verify: open `/admin/analytics`, check all 5 sections render; click a user, check drill-down loads.
