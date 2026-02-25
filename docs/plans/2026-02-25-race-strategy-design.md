# Race Strategy — Endurance Race Management Tool

**Date:** 2026-02-25
**Status:** Approved
**Tier:** 1 (Core)

## Overview

A full endurance race management system integrated into the telemetry web dashboard. Covers the complete lifecycle: pre-race configuration, automated stint optimization, live race management with 6 interconnected components, and post-race summary.

Separate from the existing sprint tire strategy planner (`/predictions/race-strategy`). This tool lives at top-level `/race-strategy/` in the navigation.

## Architecture: Approach C — Config Pages + Single Live Dashboard

- Multi-page flow for pre-race config (familiar Flask/Jinja pattern)
- Single-page live dashboard for race execution (JS-driven, polling API)
- Fully server-backed: Flask + SQLite, multi-device access on local network

## User Flow

```
/race-strategy/           → Index: list saved races, hero card for live race
/race-strategy/new        → Config form (race, drivers, pits, fuel/ballast)
       ↓ POST save
/race-strategy/<id>       → Detail: review config, run optimizer, view stint plan
       ↓ "Optimize" → stint plan generated
       ↓ "Go Live"
/race-strategy/<id>/live  → Live dashboard (6 components, polls every 2s)
       ↓ "Finish Race"
/race-strategy/<id>/summary → Post-race read-only summary
```

## Database Schema (Phase 12)

### race_configs

| Column | Type | Notes |
|--------|------|-------|
| race_id | INTEGER PK | auto |
| race_name | TEXT NOT NULL | |
| track_name | TEXT | optional, can link to tracks table |
| team_name | TEXT | |
| race_duration_s | INTEGER NOT NULL | total race in seconds |
| reference_weight_kg | REAL | target reference weight |
| desired_stints | INTEGER | default 4 |
| fuel_autonomy_s | INTEGER | fuel range in seconds |
| min_pit_stop_s | INTEGER | default 60 |
| pit_speed_kmh | REAL | |
| pit_open_s | INTEGER | pit opens at (seconds from start) |
| pit_close_s | INTEGER | pit closes at (seconds before end) |
| empty_kart_kg | REAL | |
| full_tank_kg | REAL | |
| min_total_kart_kg | REAL | |
| weigh_on_pit_exit | INTEGER | boolean |
| qualifying_duration_s | INTEGER | |
| refuel_after_quali | INTEGER | boolean |
| status | TEXT | draft / ready / live / finished |
| created_at | TEXT | datetime |
| updated_at | TEXT | datetime |

### race_drivers

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | auto |
| race_id | INTEGER FK | → race_configs |
| driver_name | TEXT NOT NULL | |
| driver_order | INTEGER | position in rotation |
| min_stint_s | INTEGER | minimum stint duration |
| max_stint_s | INTEGER | maximum stint duration |
| min_cumulative_s | INTEGER | minimum total drive time |
| max_cumulative_s | INTEGER | maximum total drive time |
| min_rest_s | INTEGER | min rest between stints, default 0 |
| weight_kg | REAL | driver weight for ballast calc |

### race_stints

| Column | Type | Notes |
|--------|------|-------|
| stint_id | INTEGER PK | auto |
| race_id | INTEGER FK | → race_configs |
| stint_order | INTEGER | |
| driver_id | INTEGER FK | → race_drivers |
| planned_start_s | INTEGER | seconds from race start |
| planned_end_s | INTEGER | |
| planned_duration_s | INTEGER | |
| actual_start_s | INTEGER | filled during live |
| actual_end_s | INTEGER | |
| actual_duration_s | INTEGER | |
| fuel_at_start | REAL | |
| fuel_at_end | REAL | |
| ballast_kg | REAL | |
| notes | TEXT | |
| status | TEXT | planned / active / completed / skipped |

### race_pit_stops

| Column | Type | Notes |
|--------|------|-------|
| pit_id | INTEGER PK | auto |
| race_id | INTEGER FK | → race_configs |
| stint_id | INTEGER FK | → race_stints |
| planned_at_s | INTEGER | |
| actual_at_s | INTEGER | |
| duration_s | INTEGER | |
| driver_change | INTEGER | boolean |
| refueled | INTEGER | boolean |
| fuel_added_kg | REAL | |
| ballast_changed | INTEGER | boolean |
| notes | TEXT | |

**Design decision:** All times stored as seconds from race start. Simple math, no timezone issues.

## Optimizer Engine

### Algorithm: Constraint-Bounded Equal Distribution

1. Compute effective race time: `D - (S-1) * P` (subtract pit overhead)
2. Compute ideal stint length: `effective_time / S`
3. Cap by fuel autonomy
4. Assign drivers via round-robin, adjusting duration per driver constraints:
   - `min_stint_s <= duration <= max_stint_s`
   - Cumulative within `[min_cumulative, max_cumulative]`
   - Rest gap >= `min_rest_s`
   - Duration <= fuel autonomy
5. Report infeasible constraints with suggestions
6. Redistribute slack to other stints

### Ballast Calculation

```
ballast_kg = min_total_kart_kg - empty_kart_kg - fuel_at_start_kg - driver_weight_kg
```

Recalculated per stint. Accounts for driver weight differences.

### Mid-Race Re-optimization

Takes completed stints as fixed, recomputes remaining stints with updated time budgets and driver cumulative totals.

## Live Dashboard — 6 Components

Single page, 2-column grid layout. JS polls `GET /api/race-strategy/<id>/state` every 2s.

### 1. Race Timer
- Elapsed / remaining (computed client-side from `race_start_timestamp`)
- Current stint N of total
- Progress bar: green → yellow (25% left) → red (10% left)

### 2. Fuel & Ballast
- Fuel percentage bar (estimated from stint time vs fuel autonomy)
- Remaining autonomy in minutes
- Current ballast for active driver
- Total kart weight vs reference (green/red indicator)

### 3. Current & Next Driver
- Active driver with elapsed time in stint
- Progress bar toward max stint
- Next driver: rest time, cumulative total, constraint status
- "End Stint" button triggers pit stop flow

### 4. Stint Order & Durations
- Timeline: completed (checkmark), active (pulsing), planned (outline)
- Color-coded per driver
- Drag-to-reorder planned stints (triggers re-optimize)

### 5. Stint Log
- Table: stint #, driver, planned time, actual time, delta, fuel, notes
- Active stint row highlighted
- Editable notes field

### 6. Race Summary
- Elapsed/remaining, pit count, driver time distribution bars
- Strategy health: ON PLAN / AHEAD / BEHIND
- Cumulative time vs min/max constraint progress per driver

### State Sync

- Timer ticks client-side (no polling dependency for clock)
- `GET /state` returns full race state every 2s
- User actions (`POST /stint/end`, `/pit`, `/reoptimize`) return updated state
- Page reload recovers full state from server

## Routes

### Page Routes (Jinja-rendered)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/race-strategy/` | Index: list races |
| GET | `/race-strategy/new` | Config form |
| POST | `/race-strategy/new` | Save config |
| GET | `/race-strategy/<id>` | Detail: review + optimize |
| POST | `/race-strategy/<id>/update` | Update config |
| POST | `/race-strategy/<id>/optimize` | Run optimizer |
| POST | `/race-strategy/<id>/go-live` | Start race |
| GET | `/race-strategy/<id>/live` | Live dashboard |
| POST | `/race-strategy/<id>/finish` | End race |
| GET | `/race-strategy/<id>/summary` | Post-race summary |

### API Routes (JSON, used by live dashboard JS)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/race-strategy/<id>/state` | Full race state |
| POST | `/api/race-strategy/<id>/stint/start` | Start next stint |
| POST | `/api/race-strategy/<id>/stint/end` | End current stint |
| POST | `/api/race-strategy/<id>/pit` | Log pit stop |
| POST | `/api/race-strategy/<id>/reoptimize` | Re-calc remaining stints |

## File Structure

```
telemetry_tool/
  race_strategy_v2.py                  # Optimizer engine
  db/schema.py                         # + Phase 12 tables
  web/
    app.py                             # + blueprint registration
    routes/
      race_strategy_v2.py              # Blueprint: all routes
    templates/
      base.html                        # + nav link
      race_strategy/
        index.html                     # Race list
        config.html                    # New/edit config form
        detail.html                    # Review + optimize + go-live
        live.html                      # Live dashboard
        summary.html                   # Post-race summary
    static/
      js/
        race_strategy.js               # Config page interactions
        race_strategy_live.js          # Live dashboard (timer, sync, 6 components)
        race_strategy_optimizer.js     # Stint plan visualization
      css/
        race_strategy.css              # All race strategy styles
```

## Feature Tiers

### Tier 1 (This Design)
- Full config form, optimizer, live dashboard, summary
- 6 interconnected components
- Mid-race re-optimization
- Ballast calculator

### Tier 2 (Future)
- Import/Export (JSON)
- Vertical/grid view toggle
- Qualifying config with refuel-after
- Pit windows (refueling windows, tech stops, opening/closing)

### Tier 3 (Future)
- TeamTalk
- APEX LiveTiming links
- Multilingual
- Light theme
- Weather integration
