# Race Strategy Port — Design

**Date:** 2026-02-27
**Scope:** Port Flask/Jinja2 endurance race strategy tool to Next.js SaaS frontend
**Source:** `telemetry_tool/web/routes/race_strategy_v2.py` (1,484 lines), 5 Jinja2 templates, 2 JS files (1,814 lines)

---

## Context

The Flask backend has a complete endurance race strategy tool:
- Race config CRUD with driver rosters, fuel/ballast modeling, pit windows
- Stint optimization algorithm respecting driver constraints
- Live race dashboard (2s polling) with timer, fuel gauge, driver status, stint log
- TeamTalk chat, weather radar, safety car, rival tracker, audio alerts
- Import/export JSON, duplication

The Next.js frontend has a simplified sprint-race stub (~1,033 lines) that doesn't match the real endurance model. This stub will be **completely replaced**.

---

## Architecture

```
Next.js Pages (React)
    ↓ apiFetch() with auth + X-Workspace-Id
/api/v1/race-strategy/* (new Flask blueprint)
    ↓ SQL via PgConnectionWrapper
PostgreSQL 16 (RLS: workspace_id isolation)
    Tables: race_configs, race_drivers, race_stints, race_pit_stops,
            race_windows, race_messages, race_neutralizations, race_rivals
```

### Key decisions

- **New `/api/v1/race-strategy/` blueprint** — clean REST API following existing SaaS patterns (envelope responses, auth middleware, RLS). Existing HTML routes stay for desktop mode.
- **Full Alembic migration + RLS** — all race strategy tables get `workspace_id` column with row-level security policies, consistent with the 44 other workspace-scoped tables.
- **Replace stub entirely** — delete current sprint-model pages, build fresh endurance-model pages.
- **2 phases** — Phase A delivers core race management; Phase B adds advanced live features.

---

## Phase A — Core Race Management

### A1. Database: Alembic Migration

New migration `017_race_strategy_rls.py`:

**Tables to create/migrate** (from SQLite schema phase 15-17):

| Table | Key Columns | Notes |
|-------|-------------|-------|
| `race_configs` | race_id, workspace_id, race_name, track_name, team_name, race_duration_s, desired_stints, fuel_autonomy_s, status (draft→ready→live→finished), race_start_ts | Main record |
| `race_drivers` | id, race_id, driver_name, driver_order, weight_kg, min/max_stint_s, min/max_cumulative_s, min_rest_s, com_channel, color_hex | Per-race roster |
| `race_stints` | stint_id, race_id, stint_order, driver_id, planned_start/end/duration_s, actual_start/end/duration_s, fuel_at_start/end, ballast_kg, status | Planned + actual |
| `race_pit_stops` | pit_id, race_id, stint_id, planned_at_s, actual_at_s, duration_s, driver_change, refueled, fuel_added_kg, pit_type | Between stints |
| `race_windows` | id, race_id, window_type, label, start_s, end_s, refuel_allowed, driver_change_allowed | Pit strategy windows |

Phase B tables (created in migration but not used yet):
| `race_messages` | msg_id, race_id, author, message, category, created_at | TeamTalk |
| `race_neutralizations` | id, race_id, start_s, end_s, reason | Safety car |
| `race_rivals` | id, race_id, team_name, car_number | Competitor tracking |

All tables get:
- `workspace_id INTEGER NOT NULL DEFAULT current_setting('app.workspace_id')::int`
- RLS policy: `USING (workspace_id = current_setting('app.workspace_id')::int)`
- FK to `race_configs(race_id)` where applicable

### A2. Backend: New API Blueprint

`telemetry_tool/web/routes/api_v1_race_strategy.py`

Blueprint prefix: `/api/v1/race-strategy`

| Method | Path | Purpose | Request | Response |
|--------|------|---------|---------|----------|
| GET | `/` | List races | — | `{ races: RaceConfig[] }` |
| POST | `/` | Create race | `{ race, drivers, windows }` | `{ race_id }` |
| GET | `/<id>` | Get race detail | — | `{ race, drivers, stints, pit_stops, windows }` |
| PUT | `/<id>` | Update race config | `{ race, drivers, windows }` | `{ ok }` |
| DELETE | `/<id>` | Delete race | — | `{ ok }` |
| POST | `/<id>/optimize` | Run stint optimization | — | `{ stints, pit_stops }` |
| POST | `/<id>/go-live` | Start live race | — | `{ ok }` |
| POST | `/<id>/finish` | End race | — | `{ ok }` |
| GET | `/<id>/state` | Live state (2s poll) | — | Full state JSON |
| POST | `/<id>/end-stint` | End current stint | — | `{ ok, next_driver }` |
| POST | `/<id>/toggle-fuel` | Toggle refuel | `{ stint_order }` | `{ ok }` |
| POST | `/<id>/set-pit-type` | Change pit type | `{ stint_order, pit_type }` | `{ ok }` |
| POST | `/<id>/reoptimize` | Re-optimize remaining | — | `{ stints }` |
| GET | `/<id>/export` | Export full JSON | — | Race JSON |
| POST | `/import` | Import race JSON | file upload | `{ race_id }` |
| POST | `/<id>/duplicate` | Clone race | — | `{ race_id }` |
| GET | `/<id>/summary` | Post-race stats | — | Summary JSON |

Logic reused from `race_strategy_v2.py` — extracted into a service layer to avoid duplication.

### A3. Frontend: Replace Stub Pages

Delete all existing files in `src/app/app/race-strategy/`.

New pages:

**1. List Page** (`page.tsx`)
- Table: race name, track, team, duration, stints, status badge, created date
- Status colors: draft (steel), ready (marshal-yellow), live (acid-green pulse), finished (chalk)
- Actions: New Race, Import Race (JSON upload)
- Click row → detail page

**2. Config Page** (`new/page.tsx` + `[id]/edit/page.tsx`)
- Multi-section form matching Flask `config.html`:
  - Race Details: name, team, track (autocomplete from `/api/v1/tracks`), duration (H:MM picker), desired stints
  - Drivers: dynamic rows — name, weight, COM channel, color picker, expandable constraints (min/max stint, cumulative, rest)
  - Pit Strategy: min pit stop, pit speed, quick pit stop, mandatory driver change, refueling allowed
  - Pit Windows: dynamic rows — type (pitlane/refuel/tech_stop), label, start/end times, rules
  - Fuel & Weight: fuel autonomy, empty kart, full tank, min total, reference weight, weigh on exit
  - Qualifying (collapsible): duration, refuel after
- Submit → POST/PUT `/api/v1/race-strategy`

**3. Detail Page** (`[id]/page.tsx`)
- Config summary cards (race, weight, qualifying)
- Driver roster table
- Stint plan timeline bar (colored by driver) + table with pit stops inline
- Fuel toggle buttons + pit type toggle buttons (FULL/QUICK)
- Actions: Optimize, Go Live (if ready), Edit, Export, Import Plan, Duplicate

**4. Basic Live Dashboard** (`[id]/live/page.tsx`)
- Race timer (elapsed/remaining, color-coded progress bar)
- Fuel & ballast gauge (kg-based, autonomy countdown, burn rate)
- Current driver + next driver cards (stint elapsed bar, COM badge)
- Stint log table (planned vs actual, delta, ballast, fuel)
- Race summary strip (elapsed, remaining, pit count, strategy health)
- Stint timeline bar
- Pit window status bar (3 cards: pit lane, refuel, tech stop)
- Action buttons: End Stint, Re-Optimize, Finish Race
- 2s polling via React Query

**5. Summary Page** (`[id]/summary/page.tsx`)
- Top-level stats: race duration, drive time, pit time, stints, pit stops, drivers
- Stint timeline bar
- Driver stats: bar chart + table (total drive, # stints, longest, shortest)
- Stint log: planned vs actual with delta
- Pit stops table
- Actions: Export, Duplicate, View Config

---

## Phase B — Advanced Live Features

### B1. TeamTalk Chat
- Chat panel in live dashboard
- Category-colored messages (general, pit, driver, weather, flag)
- Author name field + category dropdown + send
- Auto-scroll, POST `/api/v1/race-strategy/<id>/messages`

### B2. Weather Integration
- Conditions strip: temperature, grip score (progress bar), track state, wind
- Weather card: detailed current conditions
- Forecast bar: hourly blocks with rain opacity
- Rain radar: RainViewer tile map centered on track
- New endpoint: GET `/api/v1/race-strategy/<id>/weather`

### B3. Safety Car / Neutralization
- Toggle button: Deploy SC / End SC
- Full-width neutralization banner
- POST `/api/v1/race-strategy/<id>/neutralization/start|end`
- Visual: banner + timer freeze indication

### B4. Rival Tracker
- Add rival: team name + car number
- Event log: pit stops, driver changes (with race time)
- POST `/api/v1/race-strategy/<id>/rivals`

### B5. Alert Manager
- Toast notifications (appear, auto-dismiss 8s)
- Alert types: fuel critical/warning, pit window open/closing, stint limit, safety car, weather
- Audio tones (Web Audio API: sine/square/sawtooth frequencies)
- Mute toggle (localStorage)
- Alert history panel (max 20 recent)
- Browser notification API (permission request)

### B6. Layout Modes
- Grid (default), Vertical (single column), Pit Wall (large font, high contrast)
- CSS class swap on root container
- Toggle buttons in header

---

## Files Inventory

### Phase A

**Backend:**
- `alembic/versions/017_race_strategy_rls.py` — New migration
- `telemetry_tool/web/routes/api_v1_race_strategy.py` — New API blueprint
- `telemetry_tool/web/app.py` — Register new blueprint
- `telemetry_tool/services/race_strategy.py` — Extracted service layer (shared between v2 routes and API)

**Frontend (delete + create):**
- Delete: `src/app/app/race-strategy/` (all existing files)
- Create: `src/app/app/race-strategy/page.tsx` — List
- Create: `src/app/app/race-strategy/new/page.tsx` — Config (create)
- Create: `src/app/app/race-strategy/[id]/page.tsx` — Detail
- Create: `src/app/app/race-strategy/[id]/edit/page.tsx` — Config (edit)
- Create: `src/app/app/race-strategy/[id]/live/page.tsx` — Live dashboard
- Create: `src/app/app/race-strategy/[id]/summary/page.tsx` — Summary

### Phase B

**Backend:**
- Add to `api_v1_race_strategy.py`: messages, weather, neutralization, rivals endpoints

**Frontend:**
- `src/components/race-strategy/TeamTalk.tsx`
- `src/components/race-strategy/WeatherPanel.tsx`
- `src/components/race-strategy/RainRadar.tsx`
- `src/components/race-strategy/NeutralizationBanner.tsx`
- `src/components/race-strategy/RivalTracker.tsx`
- `src/components/race-strategy/AlertManager.tsx`
- `src/components/race-strategy/LayoutToggle.tsx`
- Update: `[id]/live/page.tsx` — integrate all Phase B components

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Optimization algorithm complexity | Extract from existing `race_strategy_v2.py` — it's already implemented |
| RLS migration on production | Test locally first; race strategy tables are new (no data to migrate) |
| Live dashboard performance | React Query with 2s polling; memoize expensive computations |
| Weather API reliability | Open-Meteo is free/reliable; 5-min cache prevents hammering |
| Audio alerts blocked by browser | Require user gesture before enabling; mute by default |
| Large migration scope | All tables created in single migration; RLS policies follow established pattern |
