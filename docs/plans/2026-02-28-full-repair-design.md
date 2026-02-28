# Full Feature Repair Design

**Date:** 2026-02-28
**Status:** Approved
**Approach:** Backend-First (fix all API endpoints, then rebuild frontend pages)

## Problem

The SaaS conversion added a Next.js frontend over the existing Flask backend. The pipeline, database, and old Jinja2 UI are intact, but the new frontend's chart components are not wired to the backend correctly. ~16 chart components crash or show no data because the API endpoints return data in the wrong shape. Several features from the old tool (badges, corner replay, stint analysis, debrief, focus mode) have no Next.js equivalent yet.

## Scope

- Fix 9 existing API endpoints (wrong response shape)
- Create 8 new API endpoints (data exists in DB, no route)
- Rebuild the session detail page to match old tool (5 tabs, 20+ sections)
- Fix the dashboard page
- Add corner detail page
- Add focus mode overlay

## Architecture

### Tech Stack (unchanged)

- Backend: Flask + PostgreSQL 16 + Redis 7 + Celery
- Frontend: Next.js 14 + TypeScript + Tailwind + TanStack Query + Zustand
- Charts: Custom canvas-based components (25 total, already built)
- Deploy: Docker (API) + Cloudflare Workers (frontend)

## Section 1: Backend Endpoint Fixes

### Category 1: Shape Fixes (9 endpoints)

These exist in `api_v1_data.py` but return raw DB columns instead of the shape the frontend expects.

| Endpoint | Fix Description |
|---|---|
| `GET /sessions/{id}/fingerprint` | Map score_details fields to `{metrics: [{name, value, max}]}` array |
| `GET /sessions/{id}/sectors` | Aggregate session_sectors into `{sectors: [{name, best, avg, worst}]}` |
| `GET /sessions/{id}/speed-profile` | Compute speed envelope: `{distances[], best_lap[], average[], worst_lap[]}` |
| `GET /sessions/{id}/fatigue` | Map to parallel arrays: `{laps[], fatigue_index[], reaction_time[]}` |
| `GET /sessions/{id}/energy` | Map to parallel arrays: `{distances[], kinetic_energy[], braking_energy[]}` |
| `GET /sessions/{id}/consistency` | Build heatmap matrix: `{laps[], sectors[], deltas[][]}` |
| `GET /sessions/{id}/brake-points` | Extract from corner_metrics: `{distances[], speeds[], pressures[]}` |
| `GET /sessions/{id}/corner-mastery` | Aggregate per-corner: `{corners: [{name, score, entry_speed, apex_speed, exit_speed}]}` |
| `GET /dashboard/stats` | Return `{total_sessions, pb_time, avg_score, total_drivers, recent_sessions[]}` |

### Category 2: New Endpoints (8 endpoints)

Data exists in DB tables. Need new route handlers in `api_v1_data.py`.

| Endpoint | Source Table | Response Shape |
|---|---|---|
| `GET /sessions/{id}/lap-distribution` | laps | `{bins[], counts[], mean, median}` |
| `GET /sessions/{id}/lap-overlay` | gps_traces | `{distances[], laps: [{lap_number, speeds[]}], best_lap}` |
| `GET /sessions/{id}/throttle-map` | gps_traces (throttle channel) | `{distances[], laps[], throttle[][]}` |
| `GET /sessions/{id}/tyre-data` | laps (degradation) | `{laps[], degradation[]}` |
| `GET /sessions/{id}/weather` | session_weather | `{timestamps[], temperature[], humidity[], wind_speed[]}` |
| `GET /sessions/{id}/workload` | gps_traces (steering/G) | `{timestamps[], steering[], braking[], throttle[], total[]}` |
| `GET /sessions/{id}/stints` | stint_analysis | `{stints: [{stint_number, start_lap, end_lap, avg_time, best_time, laps_count}]}` |
| `GET /sessions/{id}/trends` | laps (computed) | `{laps[], pace_delta[], consistency_index[]}` |

### Category 3: Graceful Empty Data

All endpoints return `200 + {ok: true, data: {field: []}}` when no data exists. Never 404 for missing chart data.

## Section 2: Session Detail Page Rebuild

### Page Layout

```
HEADER: Track Name + Grade Badge
← Sessions breadcrumb

METADATA CARDS (2 rows)
Row 1: Date | Driver | Track | Type | Condition
Row 2: Laps | Best Lap | Mean Lap | Score | Kart

TABS: Overview | Corners & Coaching | Performance | Analytics | Lap Data  [Focus Mode ⊞]

TAB CONTENT
```

### Tab: Overview

- Score Breakdown: 4 horizontal bars (Pace/Consistency/Execution/Robustness) with score/max
- Charts (2x2): SpeedTrace, GGDiagram, TrackMap, DrivingStyle
- Fingerprint: "Areas for Improvement" with coaching drills (priority badges)
- Next Session Actions: numbered action cards from debrief engine
- Achievements & Rating: star rating (0-5) + badge cards (Gold/Silver/Bronze)

### Tab: Corners & Coaching

- Key Corners Replay: 3 sub-modes (Corner Review, Split Comparison, Top 3 Overlay)
- Theoretical Lap: theoretical time, actual best, gap %, method badge
- Corner Coaching table: Corner, Avg Entry, Avg Apex, Avg Exit, Grip %, Avg Loss, Coaching Hint

### Tab: Performance

- Charts (2x2): LapProgress, SectorChart, LapDistribution, LapOverlay
- Stint Analysis: stint cards (Best, Mean, CV%, Fade) + Stint Pace Timeline
- Tyre Cliff Detection: coaching text

### Tab: Analytics

- Style (2x2): Fingerprint, ConsistencyHeatmap, BrakeScatter, CornerMastery
- Physics (2x2): EnergyBalance, FatigueChart, SpeedProfile, ThrottleHeatmap

### Tab: Lap Data

- Lap stats row: Best, Mean, Std Dev, Consistency %, Best vs Mean, Top 25% Avg, Improvement, Valid Laps
- Lap Times bar chart (blue normal, orange best, red invalid)
- Full data table: Lap, Time, Avg Speed, Max Speed, Max Braking, Max Accel, Line, Phase

### Focus Mode

- Fullscreen overlay triggered by ⊞ button
- 4 resizable panels with icon dock sidebar
- Panel options: Track Map, Speed Trace, G-G Diagram, Lap Distribution

## Section 3: Dashboard + Other Pages

### Dashboard

- 6 stat cards: Sessions, Drivers, Tracks, Total Laps, Best Score, Avg Score
- Recent Sessions table: Date, Driver, Track, Type badge, Laps, Best Lap, Score, Grade
- Buttons: "+ New Analysis" → /app/analyze, "View All" → /app/sessions

### Corner Detail Page (`/app/sessions/[id]/corners/[cornerId]`)

- New page for corner deep dive
- Corner replay + cockpit gauges + coaching hints
- New endpoint: `GET /sessions/{id}/corners/{corner_id}`

### No Changes Needed

- Auth pages, Account pages, Race Strategy, Race Control, Marketing — all working

## Section 4: Error Handling & Deployment

### Error Handling

- Every chart: 3 states (loading spinner, error message, empty data)
- Every endpoint: 200 + empty arrays when no data (not 404)
- Graceful degradation: one chart failure doesn't break the page

### Deployment Plan

1. **Batch 1 (Backend):** Fix all 17 endpoints → SCP → Docker rebuild → deploy
2. **Batch 2 (Frontend):** Rebuild session detail page + new components → cf:deploy
3. **Batch 3 (Polish):** Dashboard + corner page + focus mode → deploy

### Testing

- Run pytest (2282 tests) after backend changes
- curl smoke test each endpoint against production
- Visual check each tab in browser
