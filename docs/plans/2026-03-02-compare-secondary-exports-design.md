# Compare Flows, Secondary Pages & Exports — Design

**Date**: 2026-03-02
**Status**: Approved
**Scope**: Fix Compare regressions, restore secondary pages, implement Exports

---

## 1. Compare Flows

### 1.1 Session Compare — Side-by-Side Panel Enhancement

The existing `/app/compare/sessions` page (1097 lines) has working session selectors, metadata cards, score breakdown, speed overlay canvas, and lap tables. Enhance with a **side-by-side panel layout** below the existing scores section.

**Layout**: A vertical chart selector rail on the left with four options. Selecting one loads a two-panel view:

| Selector | Left Panel | Right Panel |
|---|---|---|
| Speed Overlay (default) | Speed trace canvas (existing) | Cumulative time delta strip (existing) |
| GPS Overlay | Leaflet/Canvas GPS map, both traces (A=acid-green, B=pit-orange) | Zoom/pan controls, corner markers |
| Sector Delta | Sector-by-sector time bar chart (horizontal bars, A vs B) | Net time delta per sector, total delta |
| Corner-by-Corner | Corner time loss waterfall chart | Corner speed comparison (min speed, entry/exit speed) |

**Data sources**:
- Speed overlay: existing `GET /api/v1/sessions/{id}/compare?sessionKeyB=...` — `distances`, `speeds_a`, `speeds_b`, `delta_s`
- GPS overlay: same endpoint already returns `gps_a`, `gps_b` (latitudes/longitudes arrays) — currently unused by frontend
- Sector delta: new backend computation — derive sectors from corners, compute time-in-sector from distance/speed arrays
- Corner-by-corner: `GET /api/v1/sessions/{id}/corners` for each session, aligned by corner number

**New backend endpoint**: `GET /api/v1/sessions/{id}/compare/sectors?sessionKeyB=...`
- Returns `{ sectors: [{ sector_id, name, time_a, time_b, delta }], corners: [{ corner_id, name, time_a, time_b, delta, min_speed_a, min_speed_b, entry_speed_a, entry_speed_b, exit_speed_a, exit_speed_b }] }`
- Derives sectors from corner boundaries in the session's corner data
- Computes per-sector and per-corner times from the distance/speed trace using `ds/v` integration

**Chart sync**: All panels share the distance-based hover-sync Zustand store (`hover-sync-store.ts`). Hovering on any chart highlights the corresponding position on all visible charts.

### 1.2 SessionComparison Widget Bug Fix

`lap-website/src/components/app/analytics/SessionComparison.tsx` has a field name mismatch with the backend:

| Frontend expects | Backend returns | Fix |
|---|---|---|
| `speed_a` | `speeds_a` | Map on receipt |
| `speed_b` | `speeds_b` | Map on receipt |
| `time_delta_cumulative` | `delta_s` | Map on receipt |
| `best_a_s` | `session_a.best_time_s` | Map on receipt |
| `best_b_s` | `session_b.best_time_s` | Map on receipt |

### 1.3 Driver Compare — New Page

**Route**: `/app/compare/drivers`

**UI**: Two driver dropdowns populated from `GET /api/v1/drivers`. On selection:
1. **Radar chart** (Canvas 2D) — 4 axes: Pace, Consistency, Execution, Robustness. Each axis shows the driver's average score across all their sessions. Driver A in acid-green, Driver B in pit-orange.
2. **Trend lines** — Line chart showing total score over last N sessions for each driver (time on x-axis, score on y-axis).
3. **Summary stats table** — Side-by-side: total sessions, avg total score, best total score, tracks driven count.

**New backend endpoint**: `GET /api/v1/compare/drivers?a={driver_id}&b={driver_id}`
- Returns `{ driver_a: { driver, avg_scores: {pace, consistency, execution, robustness}, trend: [{session_date, total_score}], stats: {sessions, avg_score, best_score, tracks} }, driver_b: { ... } }`
- Aggregates from existing `score_details` and `sessions` tables

### 1.4 Compare Hub Update

Add dropdowns directly on the hub page so users can start a comparison immediately without navigating to a sub-page first. Each card (Session Compare, Driver Compare) gets inline selectors that navigate with pre-selected values.

---

## 2. Secondary Pages

### 2.1 Weekends — Bug Fix

**Problem**: `weekends/[id]/page.tsx` makes a separate call to `GET /api/v1/weekends/${id}/sessions` which doesn't exist. The session data is already embedded in `GET /api/v1/weekends/${id}` response under the `sessions` key.

**Fix**: Remove the separate sessions fetch. Read sessions from the weekend detail response. No backend changes.

### 2.2 Leaderboard — Frontend Build

Backend `GET /api/v1/leaderboard?track_id=&driver_id=&limit=` already exists and returns session-level rows ranked by `best_lap_time_s ASC`.

**Build**:
- Sortable `DataTable` with columns: Rank, Driver, Track, Best Lap Time, Date, Grade
- Track filter dropdown (from `GET /api/v1/tracks`)
- Driver filter dropdown (from `GET /api/v1/drivers`)
- Sort by best lap time (default), date, driver name
- Pagination via limit/offset
- Grade color badges consistent with session detail styling

### 2.3 Development Plans — Full Build

Backend CRUD exists: `GET/POST/PATCH/DELETE /api/v1/dev-plans` with `?driver_id=` filter.

**Build**:
- Add "Dev Plans" to sidebar nav under STRATEGIST group
- **List page** (`/app/development/page.tsx`): driver selector dropdown, grid of plan cards showing name, driver, progress percentage, created date
- **Create modal**: plan name, driver selector, template grid (optional pre-built templates like "Corner Improvement", "Consistency Focus")
- **Detail page** (`/app/development/[id]/page.tsx`): plan metadata, progress tracking with editable checklist items (stored in `progress_json`), update/delete actions

### 2.4 Analytics Sub-Pages — Coming Soon

All 5 sub-pages (Weather, Trends, Meteo, Pace Predictor, Weight Simulator) get "Coming Soon" treatment:
- Hub page cards receive a semi-transparent overlay with "Coming Soon" badge
- Cards remain visible but non-clickable (remove `<Link>`, add `cursor-not-allowed`)
- Sub-page stubs replaced with a shared `ComingSoon` component that shows the feature name, brief description, and a "Back to Analytics" link

---

## 3. Exports

### 3.1 Database Migration

New `exports` table:
```sql
CREATE TABLE exports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    user_id UUID NOT NULL REFERENCES users(id),
    data_type VARCHAR(50) NOT NULL,  -- sessions, laps, drivers, tracks, scores
    format VARCHAR(20) NOT NULL,     -- csv, json, pdf, parquet
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, generating, ready, failed
    file_path TEXT,
    file_size BIGINT,
    filters JSONB,        -- optional query filters used
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
```
RLS policy: `workspace_id = current_setting('app.workspace_id')::uuid`

### 3.2 Backend Endpoints

**`POST /api/v1/exports/generate`**
- Body: `{ data_type, format, filters? }`
- Validates data_type in (sessions, laps, drivers, tracks, scores), format in (csv, json, pdf, parquet)
- Checks entitlement (export feature gate + per-tier rate limit)
- Creates DB row with status=`pending`
- Dispatches Celery task `generate_export.delay(export_id)`
- Returns `{ id, status: "pending" }`

**`GET /api/v1/exports`**
- Lists user's exports, newest first
- Returns `[{ id, data_type, format, status, file_size, created_at, completed_at }]`

**`GET /api/v1/exports/{id}/download`**
- Validates export belongs to user's workspace and status=`ready`
- Returns file with appropriate Content-Type and Content-Disposition headers
- Time-limited: exports auto-expire after 24 hours

### 3.3 Celery Task

`telemetry_tool/tasks/export_tasks.py` on `default` queue:
- Updates status to `generating`
- Queries data based on `data_type` with workspace_id filter
- Generates file in requested format:
  - **CSV**: Python `csv` module
  - **JSON**: `json.dumps` with datetime serialization
  - **PDF**: `reportlab` (table layout)
  - **Parquet**: `pyarrow`
- Saves to `data/exports/{export_id}.{format}`
- Updates DB row: status=`ready`, file_path, file_size, completed_at
- On error: status=`failed`, error message

### 3.4 Frontend Wiring

The existing `exports/page.tsx` already has the form and history table UI. Wire it to real endpoints:
- Fix API paths to match the new routes
- Add polling for in-progress exports (5-second interval)
- Download button triggers `GET /api/v1/exports/{id}/download`

---

## 4. Cross-Cutting

- **Entitlement gating**: Compare and Exports are gated by `canUse('comparison')` and `canUse('export')` respectively. Leaderboard and Dev Plans are ungated.
- **Error states**: All new pages use the existing error/loading/empty state patterns from the codebase.
- **Chart sync**: Compare panels participate in the existing distance-based hover sync store.
