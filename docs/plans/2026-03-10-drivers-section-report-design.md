# Drivers Section Full Re-Port — Design

**Date**: 2026-03-10
**Scope**: Backend API enrichment + frontend list fix + detail page rebuild

## Problem

The drivers section is partially ported:
- **List page** exists but has field-name mismatches (expects `driver_id`/`driver_name`, API returns `id`/`name`) and missing fields (`has_profile`, `style_label`, `total_laps`)
- **Detail page** is a stub ("Re-port in progress")
- **Progression page** is a stub
- Backend has rich data via `driver_repo.py` (profile, progression, style history, badges, best-ever relative) but JSON API only exposes basic CRUD

## Decisions

- **Layout**: Single scrollable detail page (no tabs, no separate progression route)
- **Charts**: Recharts (new dependency) — line charts for progression, radar chart for style features
- **Editing**: Inline edit for driver name and notes (click to edit, blur/Enter to save)
- **Delete progression route**: `/app/drivers/[id]/progression` replaced by section in detail page

## Backend Changes

### Enrich existing endpoints

**`GET /api/v1/drivers`** — Use `get_all_drivers()` from `driver_repo.py` which already returns `has_profile`, `style_label`, `total_laps`. Update `_map_driver()` to pass these through.

**`GET /api/v1/drivers/:id`** — Return full profile data alongside basic driver info. Auto-create profile if missing (like the Jinja2 route does).

### New endpoints

| Endpoint | Method | Returns |
|----------|--------|---------|
| `/api/v1/drivers/:id/progression` | GET | Progression data (score, pace, consistency over sessions) |
| `/api/v1/drivers/:id/style-history` | GET | Driving style features per session |
| `/api/v1/drivers/:id/badges` | GET | Earned badges |
| `/api/v1/drivers/:id/best-ever` | GET | Relative performance vs track records |
| `/api/v1/drivers/:id/sessions` | GET | All sessions with track name, date, score |
| `/api/v1/drivers/:id/profile` | PATCH | Update profile fields (weight, class, goals, etc.) |
| `/api/v1/drivers/:id` | DELETE | Cascade delete driver + all dependent data |

All endpoints reuse existing `driver_repo.py` functions.

## Frontend Changes

### List page fix (`drivers/page.tsx`)

- Fix `DriverRow` interface: `id` (not `driver_id`), `name` (not `driver_name`)
- Fix data unwrapping: API returns flat array in `data`, not `{ drivers: [...] }`
- Add `has_profile`, `style_label`, `total_laps` to type

### Detail page rebuild (`drivers/[id]/page.tsx`)

Scrollable sections:

1. **Header** — Name (inline editable), notes (inline editable), style badge pill
2. **Stats bar** — 5 stat cards: sessions, laps, PB, avg score, best-ever %
3. **Records held** — Track records (if any), otherwise hidden
4. **Progression charts** — Recharts LineChart: total_score and pace_delta over session_date
5. **Driving style** — RadarChart of 10 style features + style label history
6. **Badges** — Grid of earned badges
7. **Sessions table** — Track, date, best time, score, link to session
8. **Danger zone** — Delete with confirmation modal

### New components (`components/app/drivers/`)

- `InlineEdit.tsx` — Reusable click-to-edit text field
- `ProgressionChart.tsx` — Recharts line chart wrapper
- `StyleRadar.tsx` — Recharts radar chart for style features
- `BadgeGrid.tsx` — Badge display grid
- `DriverSessionsTable.tsx` — Sessions table with sorting

### Delete

- `drivers/[id]/progression/page.tsx` — no longer needed

## API Field Conventions

Frontend uses the `api_v1_entities.py` convention: `id`, `name` (not `driver_id`, `driver_name`). This matches tracks, karts, and weekends.

## Chart Theme

Recharts styled to match existing dark theme:
- Background: transparent (inherits `concrete` bg)
- Grid: `steel/20`
- Lines: `acid-green`, `pit-orange`, `marshal-yellow`
- Text: `chalk` for labels, `steel` for secondary
- Radar fill: `acid-green/20` with `acid-green` stroke
