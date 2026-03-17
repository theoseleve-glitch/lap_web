# Corner Coaching UI — Design Spec

**Date:** 2026-03-14
**Status:** Approved
**Scope:** Frontend only — `lap-website/src/components/app/corners/`

## Overview

Rebuild the Corners & Coaching tab as a two-screen experience: a track map entry point and a full-takeover corner detail view. The driver clicks a corner on the map, gets a verdict + speed comparison above the fold, and can expand accordion panels for deeper analysis.

Design principles: **clear** (instant understanding of what's wrong), **visual** (charts and bars over text walls), **dynamic** (animated transitions, progressive disclosure).

## Screen 1: Track Map (Entry Point)

The Corners & Coaching tab opens with a canvas-rendered track map showing the full circuit GPS trace.

### Track Rendering

Use equirectangular projection: normalize lat/lon to bounding box, scale to canvas dimensions with 10% padding. Update projection on canvas resize via `ResizeObserver`. Apply `devicePixelRatio` scaling for Retina displays.

### Corner Dots

Each detected corner is a numbered dot plotted at its GPS position on the track. Dots are color-coded by time loss severity:

| Time Loss | Color | Tailwind Token |
|-----------|-------|----------------|
| < 50ms | Green | `acid-green` |
| 50–150ms | Yellow | `marshal-yellow` |
| 150–300ms | Amber | `pit-orange` |
| > 300ms | Red | `safety-red` |
| No theoretical data | Gray | `text-steel` |

### Interaction

- Click a corner dot → transition to Corner Detail View (full takeover)
- Hover shows tooltip: corner number, direction (L/R), time loss
- At the first corner, `← Prev` is disabled (not hidden). At the last corner, `Next →` is disabled. No wrap-around.

### Data Source

- `GET /api/v1/sessions/{id}/corners` → `{ corners: CornerData[] }`
- `GET /api/v1/sessions/{id}/gps-trace` → `{ latitudes: number[], longitudes: number[], speeds: number[], distances: number[] }` (defaults to best lap)
- `GET /api/v1/sessions/{id}/corner-positions` → `{ corners: CornerPosition[] }` with `lat`, `lon`, `s_apex` per corner

### Empty State

If no corners detected: centered message "No corners detected for this session" with a brief explanation that corner detection requires sufficient GPS data.

---

## Screen 2: Corner Detail View (Full Takeover)

Replaces the track map entirely. A back button returns to the map.

### Top Bar

| Element | Position | Behavior |
|---------|----------|----------|
| `← Back to track` | Left | Returns to track map |
| Corner label | Center-left | e.g., `CORNER 3` in `font-monument` |
| Corner type badge | After label | e.g., `RIGHT HAIRPIN` in a `bg-white/10` pill |
| `← Prev` / `Next →` | Right | Navigate between corners sequentially. Disabled (not hidden) at first/last corner. No wrap-around. |

### Section 1: The Verdict (Always Visible)

Two-column layout. Always rendered above the fold.

**Left column — Time Loss Badge:**
- Large monospace number (e.g., `-0.34s`)
- Color: `safety-red` if losing time, `acid-green` if gaining
- Label: "Time Lost" in small uppercase below
- If `time_loss_total_s` is null (no theoretical data): show `—` with label "No theoretical data"

**Right column — Cause + Coaching Tip:**
- Primary cause badge (e.g., `LATE BRAKING`) in a colored pill matching severity
- Affected phase tag (e.g., `Entry phase`) in `text-steel`
- Coaching tip: 1–2 sentence explanation of the problem and a concrete action to try. The action sentence is highlighted in `text-acid-green` / bold.
- If `available: false` or `primary_cause` is null: show "No theoretical data available for this corner" in `text-steel`

**Data fields used (from `/corners` response):**
- `time_loss_total_s` → time loss number (null when no theoretical)
- `primary_cause` → cause badge text
- `coaching_hint` → tip text
- Phase derived from which speed delta (entry/apex/exit) is largest

### Section 2: Speed Comparison Bars (Always Visible)

Three horizontal bar rows: **Entry**, **Apex**, **Exit**.

Each row:
- Label on the left (`Entry` / `Apex` / `Exit`)
- Horizontal bar: filled width proportional to actual speed, with a dashed vertical line at the theoretical speed position
- Actual speed value inside the bar (left-aligned, monospace, chalk color)
- Theoretical speed value (right-aligned, `acid-green`, monospace)
- Delta value on the far right: red if negative (slower than theoretical), green if positive
- If theoretical speed is null: show actual speed bar only, no dashed line, no delta — label "actual only"

Speed values displayed in **km/h** (multiply m/s from API by 3.6).

**Data fields used (from `/corners` response):**
- `entry_speed_actual`, `entry_speed_theory`
- `apex_speed_actual`, `apex_speed_theory`
- `exit_speed_actual`, `exit_speed_theory`

---

### Section 3: Accordion Panels (Below Fold)

Four expandable panels with animated expand/collapse (height transition + content fade-in). Independent toggles — multiple can be open simultaneously.

Each panel header shows:
- Panel title (bold, `text-chalk`)
- One-line description (small, `text-steel`)
- Chevron indicator (`▸` collapsed, `▾` expanded)

---

#### Panel 1: Lap-by-Lap Breakdown

**Purpose:** Show consistency and progression across laps at this corner.

**Visualization:** Compact table (or horizontal bar chart) with one row per lap.

| Column | Source | Format |
|--------|--------|--------|
| Lap # | `lap_number` | Integer |
| Brake Point | `brake_point_m` | `XXm` from corner entry |
| Apex Speed | `apex_speed_mps` | km/h (×3.6) |
| Exit Speed | `exit_speed_mps` | km/h (×3.6) |
| Time Loss | `time_loss_ms` | ms, color-coded |

**Highlights:**
- Best lap (lowest time loss) row highlighted with `acid-green` left border
- Worst lap row highlighted with `safety-red` left border
- If apex speed improves across laps, show a small "improving" trend arrow

**Data source:** `GET /api/v1/sessions/{id}/corner-metrics` → response is `{ corners: [...], available: bool }`. Filter `data.corners` by `corner_id` matching the selected corner.

**Empty state:** "Lap data not available for this corner"

---

#### Panel 2: Theoretical Best

**Purpose:** Show the physics-optimal speed profile through this corner zone compared to the driver's actual best lap.

**Visualization:** Speed-over-distance mini chart (canvas-rendered).

- **X-axis:** Distance (meters), spanning `s_start` to `s_end` of this corner
- **Y-axis:** Speed (km/h)
- **Traces:**
  - Actual best lap: solid white/chalk line — from `gps-trace` response (`speeds[]` / `distances[]`), sliced to the corner zone `[s_start, s_end]` via interpolation
  - Theoretical optimal: dashed `acid-green` line — from `/theoretical` response (`speeds[]` / `distances[]`), sliced to the same zone
- **Delta shading:** Area between the two curves, colored red where actual < theoretical, green where actual > theoretical

**Note:** The two speed arrays are different resolutions and must be interpolated to align on a common distance axis for the chart and delta shading.

**Below the chart — Key Metrics row:**

| Metric | Value | Source |
|--------|-------|--------|
| Theoretical Apex Speed | km/h | From `/theoretical` → `corner_coaching[]` filtered by `corner_id` → field `theoretical_apex_speed_mps × 3.6` (raw internal name, not the mapped name used by `/corners`) |
| Optimal Brake Point | meters | From `/corners` → the selected corner's `brake_release` object if present, otherwise omit |
| Optimal Exit Speed | km/h | From `/theoretical` → `corner_coaching[]` → `theoretical_exit_speed_mps × 3.6` |
| Simulation Method | label | From `/theoretical` → `simulation_method` (e.g., "kart_envelope_solver") |

**Data sources:**
- Theoretical line: `GET /api/v1/sessions/{id}/theoretical` → `speeds[]` / `distances[]` + `corner_coaching[]`
- Actual line: `GET /api/v1/sessions/{id}/gps-trace` → `speeds[]` / `distances[]` (best lap, default behavior)

**Empty state:** If no theoretical data available: "Theoretical lap not available for this session" with `reason_code` explanation.

---

#### Panel 3: Handling Events

**Purpose:** Show detected car behavior issues at this corner.

**Visualization:** Vertical list of event cards.

Each event card:
- **Type badge:** `UNDERSTEER` (blue-ish) or `OVERSTEER` (orange-ish)
- **Severity pill:** `mild` / `moderate` / `severe` (green → yellow → red)
- **Phase tag:** `entry` / `mid` / `exit`
- **Cause text:** One-line explanation (from `cause_detail`)
- **Time cost:** If available, `time_cost_s` formatted as ms

**Data fields used (from `/corners` response):** `corners[].handling_events[]` → `event_type`, `severity`, `cause`, `cause_detail`, `corner_phase`, `magnitude`, `time_cost_s`

**Empty state:** "No handling events detected" with a green checkmark — this is good news, means clean driving through this corner.

---

#### Panel 4: Progressive Steps

**Purpose:** Actionable improvement plan tied to the primary cause.

**Visualization:** Numbered vertical list.

Each step:
- Step number in a circle (1, 2, 3...)
- Instruction text
- Visual difficulty progression: steps go from easiest (top) to most advanced (bottom)
- Optional: a subtle difficulty indicator (dots or a gradient bar alongside the steps)

**Data source:** `GET /api/v1/sessions/{id}/coaching` → `focus_areas[]` filtered by `corner_ids` containing this corner. Use the `advice` string from the matching focus area. If no match, fall back to `corners[].coaching_hint` from the `/corners` endpoint as a single tip.

**Note:** The backend `focus_areas[].advice` is a single string, not an array of steps. The frontend splits this into numbered steps if the text contains natural delimiters (sentences, semicolons, or numbered items). If it's a single sentence, render it as a single step.

**Empty state:** If no coaching data and no `coaching_hint` available, show "No coaching available for this corner."

---

## Component Architecture

```
CornersTab (entry point — thin orchestrator)
├── useCornerData (custom hook — all 6 React Query calls + derived selectors)
│
├── TrackMapView (Screen 1)
│   ├── Canvas track renderer (GPS trace, equirectangular projection)
│   ├── CornerDot × N (clickable, color-coded)
│   └── CornerTooltip (hover)
│
└── CornerDetailView (Screen 2 — full takeover)
    ├── CornerDetailHeader (back, label, prev/next)
    ├── VerdictSection (time loss + cause + tip)
    ├── SpeedComparisonBars (entry/apex/exit)
    └── AccordionPanel × 4
        ├── LapByLapPanel
        ├── TheoreticalBestPanel
        ├── HandlingEventsPanel
        └── ProgressiveStepsPanel
```

## Data Fetching Strategy

All data is fetched when the Corners & Coaching tab mounts (6 parallel requests via React Query):

| Query Key | Endpoint | Stale Time |
|-----------|----------|------------|
| `['corners', sessionId]` | `/sessions/{id}/corners` | 5 min |
| `['corner-metrics', sessionId]` | `/sessions/{id}/corner-metrics` | 5 min |
| `['theoretical', sessionId]` | `/sessions/{id}/theoretical` | 5 min |
| `['coaching', sessionId]` | `/sessions/{id}/coaching` | 5 min |
| `['gps-trace', sessionId]` | `/sessions/{id}/gps-trace` | 5 min |
| `['corner-positions', sessionId]` | `/sessions/{id}/corner-positions` | 5 min |

No additional fetches when navigating between corners — all data is already in cache, filtered client-side by `corner_id`.

## Loading & Error States

**Loading:** While any of the 6 queries are in flight, show a centered spinner with "Loading corner data..." text. Corner dots are not interactive until `corners` and `corner-positions` queries resolve. If the user navigates to a corner detail (e.g., via deep link) while data is loading, show skeleton placeholders for each section.

**Error:** If any fetch fails, show a centered error message: "Failed to load corner data" with a "Try again" button that calls `refetch()` on the failed queries. Consistent with the `QueryError` pattern used elsewhere in the app.

## Animations

- **Map → Detail transition:** Fade out map, fade in detail view (150ms)
- **Accordion expand:** Height animation (200ms ease-out) + content fade-in (150ms, delayed 50ms)
- **Speed bars:** Width animates from 0 to final value on mount (300ms ease-out, staggered: entry → apex → exit)
- **Corner dot hover:** Scale 1 → 1.3 (100ms)

## Color Semantics

Consistent with existing design system:

| Token | Hex | Usage |
|-------|-----|-------|
| `acid-green` | `#C6F135` | Positive values, theoretical targets, good performance |
| `safety-red` | `#FF2A2A` | Time loss, negative deltas, severe issues |
| `marshal-yellow` | `#F5C518` | Warnings, moderate issues |
| `pit-orange` | `#FF6B2B` | Interactive accents, amber-level issues |
| `chalk` | `#F0EDE5` | Primary text |
| `steel` | `#888` | Secondary text, labels |
| `asphalt` | `#1A1A1A` | Backgrounds |
| `concrete` | `#2A2A2A` | Card/panel backgrounds |

## Graceful Degradation

Each section handles missing data independently:

| Scenario | Behavior |
|----------|----------|
| Corner `available: false` / no theoretical | Verdict shows `—` for time loss, "No theoretical data" label; speed bars show actual only (no dashed line, no delta); cause shows "No theoretical data available" |
| No theoretical data | Theoretical Best panel shows "Theoretical lap not available" with `reason_code` |
| No corner metrics | Lap-by-Lap panel shows "Lap data not available for this corner" |
| No handling events | Panel shows green "No handling events detected" |
| No coaching data | Progressive Steps falls back to `coaching_hint` from `/corners`; if also null, shows "No coaching available" |
| No GPS trace | Track map shows "GPS data not available"; corners listed as plain text links instead |
| API fetch fails | Tab shows centered error with "Try again" button |

## Files to Create

| File | Purpose | Est. Lines |
|------|---------|------------|
| `corners/CornersTab.tsx` | Thin orchestrator: view state (map vs detail), renders child views | ~80 |
| `corners/useCornerData.ts` | Custom hook: 6 React Query calls + derived selectors (corners for selected ID, metrics filtered, etc.) | ~120 |
| `corners/TrackMapView.tsx` | Canvas track map with corner dots, equirectangular projection, DPR scaling | ~280 |
| `corners/CornerDetailView.tsx` | Full detail layout orchestrator | ~100 |
| `corners/CornerDetailHeader.tsx` | Top bar (back, label, type badge, prev/next) | ~50 |
| `corners/VerdictSection.tsx` | Time loss + cause + coaching tip | ~80 |
| `corners/SpeedComparisonBars.tsx` | Entry/apex/exit speed bars with animation | ~120 |
| `corners/AccordionPanel.tsx` | Reusable animated accordion wrapper | ~60 |
| `corners/LapByLapPanel.tsx` | Per-lap metrics table with highlights | ~120 |
| `corners/TheoreticalBestPanel.tsx` | Speed-over-distance canvas chart with delta shading | ~200 |
| `corners/HandlingEventsPanel.tsx` | Event list with badges | ~80 |
| `corners/ProgressiveStepsPanel.tsx` | Numbered improvement steps | ~70 |
| `corners/index.ts` | Barrel exports + `CornerData` type | ~10 |
| **Total** | | **~1,370** |

## Out of Scope

- Corner replay (video-style playback) — deferred, separate feature
- Multi-session trend charts — deferred to future iteration
- Corner editing / user-defined corners — existing `CornerEditor.tsx` handles this separately
- Session-level coaching debrief (narrative, drills, goals) — separate from per-corner view
- Comparison between two sessions at the same corner — future feature
