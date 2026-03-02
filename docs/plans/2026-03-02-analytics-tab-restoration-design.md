# Analytics Tab Restoration — Design

**Date:** 2026-03-02
**Status:** Approved

## Problem

The Analytics tab in the session detail page only shows 3 charts (GPS map, Speed Trace, G-G Diagram) plus a Sector Panel. The original desktop tool had 10+ analysis modules. Missing: advanced track map with lap selection, lap speed overlay with multi-lap checkboxes, lap time distribution, lap progress tracker, session comparison, and development drills.

## Decisions

- **Wrap vanilla JS** where modules exist (`lap_overlay.js`, `lap_distribution.js`, `lap_progress.js`) — reuse proven rendering via `useVanillaChart` hook
- **Fresh React** for modules without vanilla JS (SessionComparison, DevelopmentDrills)
- **Inline session picker** for cross-session comparison (dropdown in Analytics tab, not a separate page)
- **Auto-generated drills** from scores.weaknesses[] + corner coaching data (frontend-only, no backend)
- **No backend changes** — all required endpoints already exist

## Data Contract

### Existing endpoints (all unchanged)

| Endpoint | Used By |
|----------|---------|
| `GET /sessions/{id}/track-map?lap=best\|all` | TrackMapAdvanced |
| `GET /sessions/{id}/sectors` | SectorPerformance |
| `GET /sessions/{id}/speed-trace?lap=N` | LapSpeedOverlay (via vanilla JS) |
| `GET /sessions/{id}/gg-data?lap=N` | GGExplorerPanel (via vanilla JS) |
| `GET /sessions/{id}/lap-distribution` | LapDistribution (via vanilla JS) |
| `GET /sessions/{id}/lap-progress` | LapProgressTracker (via vanilla JS) |
| `GET /sessions/{id}/compare?sessionKeyB=X` | SessionComparison |
| `GET /sessions` | SessionComparison (session picker) |

### DevelopmentDrills — no endpoint

Frontend-only. Reads `scores.weaknesses[]` and `corners[]` passed as props from the parent page.

## Component Architecture

```
components/app/analytics/
  AnalyticsTab.tsx          — Layout orchestrator
  TrackMapAdvanced.tsx      — Leaflet map + lap selector + all-laps + corners + zoom
  LapSpeedOverlay.tsx       — Vanilla JS wrapper (lap_overlay.js)
  LapDistribution.tsx       — Vanilla JS wrapper (lap_distribution.js)
  LapProgressTracker.tsx    — Vanilla JS wrapper (lap_progress.js)
  SessionComparison.tsx     — React: session picker + speed overlay + delta strip
  DevelopmentDrills.tsx     — Frontend drill generation from scores + corners
  index.ts                  — Barrel exports
```

### AnalyticsTab (orchestrator)

Receives props from page: `sessionId, gpsLaps, bestLap, scores, corners`.

Layout (top to bottom):
1. **Track Map Advanced** — full width, ~350px
2. **3-column grid** — Sector Performance | Lap Speed Overlay | G-G Explorer
3. **2-column grid** — Lap Distribution | Lap Progress Tracker
4. **Session Comparison** — full width with inline session picker
5. **Development Drills** — full width, 3-5 drill cards

Mobile: all sections stack single-column.

### TrackMapAdvanced

Extends existing `TrackMap.tsx` (Leaflet-based):
- Lap selector dropdown populated from `gpsLaps[]`
- "All Laps" toggle button
- Corner markers from `/track-map` response
- Fit-bounds zoom on lap change
- Props: `sessionId, gpsLaps, bestLap`
- Data: `/track-map?lap=all` or `/track-map?lap=best` via `useChartData`

### LapSpeedOverlay (vanilla JS wrapper)

- Script: `/js/lap_overlay.js` via `useVanillaChart` hook
- Multi-lap speed overlay with per-lap checkboxes
- Vanilla module fetches `/speed-trace?lap=N` per selected lap internally
- Container div with `id="lap-overlay"` for vanilla JS to render into

### LapDistribution (vanilla JS wrapper)

- Script: `/js/lap_distribution.js` via `useVanillaChart`
- Histogram + KDE overlay + box-plot + outlier badges + stats cards
- Vanilla module fetches `/lap-distribution` internally
- Container div with `id="lap-distribution"`

### LapProgressTracker (vanilla JS wrapper)

- Script: `/js/lap_progress.js` via `useVanillaChart`
- Running PB line, pace zones, flow state highlights, rolling CV, momentum
- Vanilla module fetches `/lap-progress` internally
- Container div with `id="lap-progress"`

### SessionComparison (React component)

- **Session picker**: dropdown fetches `/sessions` filtered to same track, shows 10 most recent
- **On select**: calls `/compare?sessionKeyB=...`
- **Renders**:
  - Distance-aligned speed overlay (2 lines on canvas, color-coded)
  - Cumulative time delta strip (green/red band)
  - Summary cards: best time A vs B, total delta, session dates
- **GPS overlay**: both traces on a small Leaflet map
- **Empty state**: "Select a session to compare" when no session picked

### DevelopmentDrills (frontend-only)

Reads `scores.weaknesses[]` and `corners[]` from props. Maps to drill templates:

| Weakness | Drill |
|----------|-------|
| `"consistency"` | "Repeat the same braking point for Corner {worst} across 5 laps" |
| `"pace"` | "Attack Corner {biggest_loss} entry by +{delta} km/h" |
| `"execution"` | "Focus on smooth throttle application through Corner {worst_grip}" |
| `"robustness"` | "Complete 10 clean laps without invalid markers" |
| (fallback) | "Drive 10 clean laps focusing on smooth inputs" |

Shows 3-5 cards with drill title, description, target corner/metric.

## Graceful Degradation

| Scenario | Behavior |
|----------|----------|
| No GPS data | Track Map shows "No GPS data available". Other sections unaffected. |
| No valid laps | LapDistribution + LapProgress show "Not enough data" message |
| Vanilla JS load fails | Individual section shows error + retry button |
| No same-track sessions | SessionComparison dropdown shows "No other sessions on this track" |
| No weaknesses in scores | DevelopmentDrills shows generic drills |
| Any fetch fails | Individual card error state. Other sections unaffected. |

## Files Modified

### Frontend (new files)
- `lap-website/src/components/app/analytics/AnalyticsTab.tsx`
- `lap-website/src/components/app/analytics/TrackMapAdvanced.tsx`
- `lap-website/src/components/app/analytics/LapSpeedOverlay.tsx`
- `lap-website/src/components/app/analytics/LapDistribution.tsx`
- `lap-website/src/components/app/analytics/LapProgressTracker.tsx`
- `lap-website/src/components/app/analytics/SessionComparison.tsx`
- `lap-website/src/components/app/analytics/DevelopmentDrills.tsx`
- `lap-website/src/components/app/analytics/index.ts`

### Frontend (modified files)
- `lap-website/src/app/app/sessions/[id]/page.tsx` — replace inline AnalyticsTab with import from new module, pass scores + corners props

### Backend
- No changes needed
