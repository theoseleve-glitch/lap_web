# Corners & Coaching Restoration — Design v2

**Date:** 2026-03-02
**Status:** Approved
**Supersedes:** v1 (vanilla JS migration approach — abandoned in favor of fresh React build)

## Problem

The Corners & Coaching tab in the session detail page is incomplete:
- Corner replay uses a legacy component hitting old endpoints
- A new corner-replay suite exists but is orphaned (only in free-report, hits non-existent `/corner-replay` route)
- Missing: brake precision chart, corner mastery report card, throttle onset map, consistency heatmap
- No graceful degradation when theoretical lap fails
- Corner detail page is a stub

## Decisions

- **Fresh rebuild** of the entire CornersTab — scrap both legacy and orphaned implementations
- **Modular architecture** — each section is its own component file under `components/app/corners/`
- **Data contract fix** — `/corners` endpoint always returns corner boundaries; metrics are `null` with `available: false` when theoretical fails
- **Functional where data exists** — brake precision and corner mastery wire to real backend endpoints; throttle onset and consistency heatmap are visual placeholders

## Data Contract

### `GET /sessions/{id}/corners` (modified)

Always returns corner boundaries from detection step 06b. Merges coaching metrics from theoretical when available.

```json
{
  "corners": [
    {
      "corner_id": 1,
      "s_start": 120.5,
      "s_end": 185.3,
      "s_apex": 152.1,
      "direction": "L",
      "available": true,
      "entry_speed_actual": 18.2,
      "entry_speed_theory": 19.5,
      "apex_speed_actual": 14.1,
      "apex_speed_theory": 15.8,
      "exit_speed_actual": 17.6,
      "exit_speed_theory": 18.9,
      "time_loss_total_s": 0.42,
      "grip_utilisation_pct": 78.5,
      "primary_cause": "low_apex_speed",
      "coaching_hint": "Carry 1.7 m/s more through apex — trust front grip."
    }
  ]
}
```

When `available: false`: all metric fields are `null`, `coaching_hint` is `"Theoretical data unavailable for this corner"`.

### Existing endpoints (unchanged)

- `GET /sessions/{id}/corner-replay-data` — batch: GPS traces + corner positions + corner metrics + lap times
- `GET /sessions/{id}/corner-mastery` — per-corner mastery scores
- `GET /sessions/{id}/brake-precision` — per-corner brake point deltas
- `GET /sessions/{id}/corner-metrics` — per-lap corner metrics
- `GET /sessions/{id}/corner-metrics/summary` — aggregated per-corner averages

## Component Architecture

```
components/app/corners/
  CornersTab.tsx          — Layout orchestrator
  CornerReplay.tsx        — Canvas cockpit + GPS map + playback controls
  CoachingTable.tsx       — Sortable per-corner coaching table
  CornerSelection.tsx     — Corner checkboxes + save to localStorage
  BrakePrecisionChart.tsx — Real chart from /brake-precision
  CornerMasteryCard.tsx   — Real scores from /corner-mastery
  ThrottleOnsetMap.tsx    — Placeholder
  ConsistencyHeatmap.tsx  — Placeholder
  index.ts                — Re-exports
```

### CornersTab (orchestrator)

Fetches `GET /sessions/{id}/corners`. Renders sections top-to-bottom:

1. **Corner Replay** — full-width, ~400px
2. **Coaching Table + Corner Selection** — side by side (desktop), stacked (mobile)
3. **2x2 grid** — Brake Precision | Corner Mastery | Throttle Onset | Consistency Heatmap

### CornerReplay (fresh build)

3-pane layout:
- **Left**: Cockpit gauge — circular speedometer arc, G-force diamond
- **Center**: GPS map — canvas trace with corner markers, moving dot
- **Right**: Metrics sidebar — entry/apex/exit speed, brake point, time loss, coaching hint

Navigation: corner pills C1-C5, prev/next arrows
Playback: play/pause, speed (0.25x / 0.5x / 1x / 2x)
Modes: Review (single lap), Split (A vs B), Top 3
Keyboard: Space = play/pause, Left/Right = frame step, [ ] = prev/next corner
Data: fetches from `GET /sessions/{id}/corner-replay-data`

### CoachingTable

Columns:
- Corner # + direction badge (L/R)
- Entry / Apex / Exit speed (actual vs theoretical)
- Grip utilisation %
- Time loss (ms, color-coded: green < 100ms, yellow 100-300ms, red > 300ms)
- Coaching hint text
- Sortable by any column

### CornerSelection

- Checkbox per corner
- Select All / Clear buttons
- Persisted to `localStorage` keyed by session ID
- Controls which corners are highlighted in replay + table

### BrakePrecisionChart (real data)

- Fetches `GET /sessions/{id}/brake-precision`
- Horizontal bar chart: per-corner brake point delta (m) — actual vs theoretical
- Color: green = within 2m, yellow = 2-5m, red = >5m

### CornerMasteryCard (real data)

- Fetches `GET /sessions/{id}/corner-mastery`
- Per-corner mastery score (0-100) with letter grade
- Horizontal bar or radar visualization

### ThrottleOnsetMap + ConsistencyHeatmap (placeholders)

- Card with chart outline, label, "Coming Soon" badge
- No API calls

## Graceful Degradation

| Scenario | Behavior |
|----------|----------|
| Corner has `available: false` | Coaching table shows "--" for metrics, grayed row. Replay shows GPS trace + boundaries but no speed comparison. Hint says "Theoretical data unavailable." |
| No corners detected (empty list) | CornersTab shows centered message: "No corners detected for this session" |
| `/corner-replay-data` fails | Replay section shows error state with retry button. Other sections unaffected. |
| `/brake-precision` or `/corner-mastery` fails | Individual card shows error state. Other sections unaffected. |

## Files Modified

### Backend
- `telemetry_tool/web/routes/data_v2.py` — modify `/corners` endpoint to merge boundaries + coaching with `available` flag

### Frontend (new files)
- `lap-website/src/components/app/corners/CornersTab.tsx`
- `lap-website/src/components/app/corners/CornerReplay.tsx`
- `lap-website/src/components/app/corners/CoachingTable.tsx`
- `lap-website/src/components/app/corners/CornerSelection.tsx`
- `lap-website/src/components/app/corners/BrakePrecisionChart.tsx`
- `lap-website/src/components/app/corners/CornerMasteryCard.tsx`
- `lap-website/src/components/app/corners/ThrottleOnsetMap.tsx`
- `lap-website/src/components/app/corners/ConsistencyHeatmap.tsx`
- `lap-website/src/components/app/corners/index.ts`

### Frontend (modified files)
- `lap-website/src/app/app/sessions/[id]/page.tsx` — replace inline CornersTab with import from new module

### Frontend (removed)
- Remove legacy `src/components/shared/charts/CornerReplay.tsx` (replaced by new module)
