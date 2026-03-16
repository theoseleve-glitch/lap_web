# Endurance Report System — Design Spec

**Date:** 2026-03-16
**Status:** Approved
**Scope:** Multi-driver endurance race reporting with 3-tier drill-down

---

## Problem

The session detail page shows the same generic report for all session types. For endurance races (2+ drivers, pit stops, stint strategy), this is useless — scores are polluted by mixing drivers, pit laps inflate anomalies, and there's no way to compare driver performance or see stint-by-stint progression.

## Solution

A 3-tier drill-down report system: **Team → Driver → Stint**. Auto-detect pit stops from lap times, let the user assign drivers to stints, then generate scoped reports at each level.

---

## Data Flow

```
Upload CSV (single file, all drivers concatenated)
  → Pipeline detects pit laps (lap_time > configurable threshold, default 120s)
  → Creates stint boundaries (groups of valid laps between pit laps)
  → User opens session → Endurance tab appears
  → User assigns drivers to stints + optional condition per stint
  → Backend scores per-stint (existing scorer, scoped to stint laps + condition)
  → Frontend renders 3-tier drill-down report
```

---

## Backend Changes

### New DB Tables

**`endurance_stints`**
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| session_id | TEXT FK → sessions | |
| stint_number | INT | 1-indexed |
| start_lap | INT | First valid lap number |
| end_lap | INT | Last valid lap number |
| pit_lap_number | INT NULL | The pit/swap lap that ends this stint |
| pit_lap_time_s | FLOAT NULL | Duration of the pit lap |
| condition | TEXT NULL | dry / damp / wet / mixed |
| workspace_id | INT FK → workspaces | RLS |

**`stint_drivers`**
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| stint_id | INT FK → endurance_stints | |
| driver_id | INT FK → drivers | |
| workspace_id | INT FK → workspaces | RLS |

### Pit Stop Detection Logic

Runs as a new pipeline stage after lap splitting, before scoring.

```
median_lap_time = median(all valid lap times)
pit_threshold = user_configured OR default 120 seconds

For each lap:
  if lap_time > pit_threshold → mark as pit_lap

Group consecutive valid (non-pit) laps into stints:
  stint 1 = laps 1–8 (pit lap 9)
  stint 2 = laps 10–17 (pit lap 18)
  etc.

First and last lap of session may be partial — flag but include.
```

### New API Endpoints

**`GET /api/v1/sessions/{id}/stints`**
Returns detected stints with per-stint summary stats.
```json
{
  "stints": [
    {
      "stint_number": 1,
      "start_lap": 1,
      "end_lap": 8,
      "lap_count": 8,
      "best_lap_time_s": 52.1,
      "mean_lap_time_s": 53.4,
      "consistency_cv_pct": 1.8,
      "pit_lap_time_s": 185.2,
      "condition": "dry",
      "driver_id": null,
      "driver_name": null
    }
  ],
  "pit_threshold_s": 120,
  "total_stints": 10
}
```

**`POST /api/v1/sessions/{id}/stints/configure`**
Re-detect stints with a new pit threshold.
```json
{ "pit_threshold_s": 90 }
```

**`POST /api/v1/sessions/{id}/stints/assign`**
Assign drivers to stints and optional conditions.
```json
{
  "assignments": [
    { "stint_number": 1, "driver_id": 42, "condition": "dry" },
    { "stint_number": 2, "driver_id": 42, "condition": "dry" },
    { "stint_number": 3, "driver_id": 17, "condition": "damp" }
  ]
}
```

**`GET /api/v1/sessions/{id}/endurance-report`**
Returns the full 3-tier report. Only available after driver assignment.
```json
{
  "team": {
    "total_laps": 87,
    "total_time_s": 4620.5,
    "total_stints": 10,
    "drivers": ["Théo", "William"],
    "scores": { "pace": 18.2, "consistency": 15.1, "robustness": 20.3 },
    "driver_comparison": [
      {
        "driver_name": "Théo",
        "stints": [1, 2, 3, 8, 10],
        "total_laps": 42,
        "best_lap_s": 51.4,
        "mean_lap_s": 52.8,
        "consistency_cv_pct": 1.6,
        "scores": { "pace": 19.1, "consistency": 16.2, "robustness": 21.0 }
      },
      {
        "driver_name": "William",
        "stints": [4, 5, 6, 7, 9],
        "total_laps": 45,
        "best_lap_s": 52.0,
        "mean_lap_s": 53.5,
        "consistency_cv_pct": 2.1,
        "scores": { "pace": 17.3, "consistency": 14.0, "robustness": 19.5 }
      }
    ]
  },
  "drivers": {
    "42": {
      "driver_name": "Théo",
      "stints": [
        {
          "stint_number": 1,
          "condition": "dry",
          "best_lap_s": 52.1,
          "mean_lap_s": 53.4,
          "lap_count": 8,
          "consistency_cv_pct": 1.8,
          "pace_fade_pct": 0.8,
          "scores": { "pace": 18.5, "consistency": 16.0, "robustness": 22.0 }
        }
      ],
      "best_lap_progression": [52.1, 51.8, 51.4, 52.0, 51.6],
      "aggregated_scores": { "pace": 19.1, "consistency": 16.2, "robustness": 21.0 }
    }
  }
}
```

### Scoring

- **Per-stint:** Run existing `score_session()` with laps scoped to that stint. Pass stint's `condition` as `track_state` so wet/dry thresholds apply correctly. Session type forced to `endurance_stint`.
- **Per-driver:** Aggregate across all driver's stints. Pace = best of all stints. Consistency = CV across ALL the driver's laps. Robustness = pace fade from their first stint to last stint.
- **Team:** Score computed from all valid laps. Robustness weighs 1.6x (existing endurance weight).

---

## Frontend: Endurance Tab

### When It Appears

The Endurance tab appears in session detail when:
- `session_type` is `endurance`, `endurance_race`, or `endurance_stint`, OR
- The pipeline detected ≥1 pit lap (lap_time > threshold)

### Setup Flow (first visit, no assignments yet)

1. Banner: "We detected **10 stints** across **87 laps** (pit threshold: 120s)"
2. Threshold adjuster: slider or input, "Adjust" button → re-detects via API
3. Stint table: stint #, lap range, best lap, mean, duration — for context
4. **"Add Driver"** button → text input for driver name (or select from existing drivers in workspace)
5. For each driver: checkboxes to assign stints
6. Optional: condition dropdown per stint (dry/damp/wet/mixed), defaults to "dry"
7. **"Generate Report"** button → saves assignments, triggers scoring, renders Tier 3

### Tier 3 — Team Report (landing view after setup)

- **Race Summary Cards:** total laps, total time, drivers, stints, average pit time
- **Driver Comparison Table:** columns = driver name, stints, total laps, best lap, mean, CV%, robustness, score
- **Strategy Timeline:** horizontal bar chart — X axis = lap number, colored blocks per driver showing who drove when. Pit stops shown as gaps.
- **Team Score Breakdown:** Pace / Consistency / Robustness bars (like existing score bars)

### Tier 2 — Driver Report (click a driver row)

- **Driver Header:** name, total laps, total stints, overall best lap
- **Stint Cards Grid:** each card = stint #, condition badge (colored pill), best lap, mean, CV%, lap count, pace fade %
- **Best Lap Progression:** small line chart — X = stint number, Y = best lap time. Shows if driver is improving or fading across the race.
- **Driver Score Breakdown:** Pace / Consistency / Robustness
- **Back → Team Report**

### Tier 1 — Stint Report (click a stint card)

- **Reuses existing Overview tab layout** — score bars, stat cards, lap table, session debrief
- **Scoped to only that stint's laps** — all stats computed from laps `start_lap` to `end_lap`
- **Condition badge** shown in header
- **Back → Driver Report**

---

## Data Dependencies

| Component | Depends On |
|-----------|-----------|
| Pit detection | Laps table (lap_time_s) |
| Stint boundaries | Pit detection output |
| Per-stint scoring | Existing scorer + condition override |
| Driver assignment | User input + drivers table |
| Endurance report API | Stint boundaries + driver assignments + per-stint scores |
| Frontend Endurance tab | Endurance report API |

## Migration

New Alembic migration for `endurance_stints` and `stint_drivers` tables with RLS policies and workspace_id columns.

## Testing

- Unit: pit detection with various thresholds (120s, 90s, 30s)
- Unit: stint boundary edge cases (pit at first lap, pit at last lap, consecutive pits)
- Unit: per-stint scoring produces different results than whole-session scoring
- Integration: full flow — upload → detect → assign → report
- Frontend: drill-down navigation Team → Driver → Stint → back

---

## Out of Scope (V2+)

- Automatic driver identification from telemetry signatures
- Stint strategy optimizer ("when should you pit?")
- Live timing / real-time stint tracking
- Tire degradation model per stint
- Fuel consumption tracking
- Corner-level coaching per stint (depends on corners V2)
