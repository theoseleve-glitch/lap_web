# Optimizer V2 — Advanced Race Strategy Engine

**Date**: 2026-03-17
**Status**: Approved
**Scope**: 4 optimizer improvements — CSP solver, fuel-integrated planning, competitive period weighting, weather-aware strategy

---

## Feature 1: Constraint Satisfaction Solver (CSP)

### Problem
The current greedy optimizer assigns stints in a single forward pass. If a choice leads to a downstream constraint violation (e.g., driver exceeds cumulative max, rest time impossible for next rotation), it only warns — never fixes.

### Approach
Replace the greedy pass with a full backtracking CSP solver that guarantees a valid solution if one exists.

### Algorithm

**Variables**: Each stint slot `i` in `1..N` has:
- `driver_id`: which driver
- `duration_s`: stint length

**Domains**: For each slot, the set of eligible drivers (not sleeping, not double-stinting unless allowed, rest time met).

**Constraints** (all hard):
- `duration <= driver.max_stint_s` (if set)
- `duration >= driver.min_stint_s` (if set)
- `cumulative(driver) <= driver.max_cumulative_s` (if set)
- `cumulative(driver) >= driver.min_cumulative_s` (checked at end)
- Rest: `start_s - last_end(driver) >= driver.min_rest_s`
- No double stint unless `driver.allow_double_stint`
- Sleep: stint does not overlap driver's sleep window
- Fuel: `duration <= fuel_level / burn_rate` (from Feature 2)
- Blackout: first stint >= `blackout_start_min * 60`, last pit before `race_duration - blackout_end_min * 60`

**Search**:
1. Compute N stints from race duration, pit time, fuel autonomy
2. For stint slot `i`, generate candidate drivers sorted by score (see Feature 3 for scoring)
3. For each candidate, compute feasible duration range `[min_dur, max_dur]`
4. Pick optimal duration within range (from performance budget or equal distribution)
5. Assign and recurse to slot `i+1`
6. If no candidate is feasible → **backtrack**: undo slot `i-1`, try next candidate
7. **Forward-checking**: after assignment, prune future domains. If any future slot has empty domain, backtrack immediately.
8. **Max backtrack depth**: 200. If exhausted, return best partial solution with violations.

**Output**: Same shape as current — `{feasible, stints, pit_stops, driver_summary, violations, warnings}`. With a valid solution, `violations` is empty.

### Performance
For 24 stints × 5 drivers, worst case is 5^24 but forward-checking prunes aggressively. Typical solutions found in < 100 assignments. Target: < 500ms.

---

## Feature 2: Fuel-Integrated Planning

### Problem
Currently fuel is checked post-hoc: optimizer plans stints, then a separate pass computes fuel levels and sets refuel flags. This can produce plans where fuel runs out mid-stint.

### Approach
Fuel becomes a first-class CSP variable tracked during the search.

### Fuel State in Search
- `fuel_level` initialized to `fuel_capacity` (or `fuel_after_quali` for stint 1)
- Each stint consumes: `burn_rate * duration`
- At each pit stop boundary, solver decides: refuel (→ full tank) or carry (→ current level)
- Quick change mode: always full tank, skip fuel tracking

### CSP Integration
- **Duration cap**: `max_dur = min(max_dur, fuel_level / burn_rate)` — can't drive longer than fuel allows
- **Refuel decision**: If `fuel_level < burn_rate * min_viable_stint_s` → must refuel
- **Refuel cost**: Refuel pit = `min_pit_stop_s`, no-refuel pit = `quick_pit_stop_s` or same. Different pit durations affect total available drive time.
- Refuel state is part of the search — backtracking can try refuel vs. no-refuel at each pit boundary

### No New Form Fields
Uses existing: `fuel_autonomy_s`, `full_tank_kg`, `empty_kart_kg`, `refueling_allowed`, `quick_change_enabled`.

---

## Feature 3: Competitive Period Weighting

### Problem
In performance mode, faster drivers get more total time but are distributed evenly across the race. They should be placed in the most competitive periods (race start, finish, post-weather-change).

### Approach
Automatic priority scoring per stint slot. No user input needed.

### Priority Phases
| Phase | Condition | Priority Score |
|-------|-----------|---------------|
| Normal | Default | 1.0 |
| Race start | First 5% of race duration | 1.5 |
| Race finish | Last 10% of race duration | 1.5 |
| Post-weather-change | First stint after a condition transition | 2.0 |

### Driver Scoring in CSP
For each stint slot, driver candidates are sorted by:
```
score = (1 / effective_lap_time) * priority_score * mode_weight
```

Where:
- `effective_lap_time` = `avg_lap_time_s` in dry, or `avg_lap_time_s / wet_confidence` in wet forecast
- `priority_score` = from table above
- `mode_weight` = 1.0 in equal mode, or `driver_budget_remaining / total_budget` in performance mode

Higher score = assigned first. The CSP tries the highest-scoring driver first at each slot, backtracking if constraints fail.

### Post-Weather-Change Detection
When the weather forecast (Feature 4) has a condition transition at time T:
- The stint starting at or just after T gets `priority_score = 2.0`
- Driver scoring uses `wet_confidence` (if transitioning to wet) or `1/avg_lap_time_s` (if transitioning to dry)

---

## Feature 4: Weather-Aware Strategy

### Problem
Rain is the biggest variable in kart endurance. Teams that react best to weather win. Pit stops during rain cost fewer laps (everyone is slower). The optimizer should cluster pit stops during rain and put rain specialists in the kart during wet periods.

### Data Model

**Per driver** — add to `race_drivers`:
- `wet_confidence REAL DEFAULT 0.5` — 0.0 (terrible in rain) to 1.0 (rain specialist)

**Weather forecast** — new table `race_weather_windows`:
```sql
CREATE TABLE race_weather_windows (
    id              SERIAL PRIMARY KEY,
    race_id         INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    start_s         INTEGER NOT NULL,
    end_s           INTEGER NOT NULL,
    condition       TEXT NOT NULL DEFAULT 'dry',  -- 'dry', 'damp', 'wet'
    confidence_pct  INTEGER NOT NULL DEFAULT 100,
    workspace_id    INTEGER NOT NULL
);
```
With RLS policy.

**Live condition** — add to `race_configs`:
- `current_condition TEXT NOT NULL DEFAULT 'dry'`

### Optimizer Integration

**Pace adjustment**: During a wet forecast window, each driver's effective lap time:
```
effective_lap_time = avg_lap_time_s / wet_confidence
```
- Alice (62s dry, 0.8 wet) → 77.5s in wet
- Charlie (66s dry, 0.95 wet) → 69.5s in wet — Charlie is faster in rain

**Pit cost in wet**:
```
pit_cost_laps = pit_time_s / effective_lap_time
```
- Dry: 120s / 62s = 1.94 laps lost
- Wet: 120s / 77.5s = 1.55 laps lost
- Saving: 0.39 laps per pit in rain

**CSP integration**:
- For each stint slot, check if it falls within a wet forecast window
- If yes, use wet-adjusted pace for driver scoring and duration planning
- The solver naturally prefers to place pit stops during rain (lower cost)
- Specifically: when choosing between "pit now (rain)" vs "pit later (dry)", the solver picks rain because the duration-to-laps ratio is better

**Pit clustering heuristic**: When a rain window is forecasted:
- Prefer shorter stints before rain (to synchronize pit entry with rain start)
- Prefer longer stints during rain (rain specialist stays out, competitor pits more)
- The CSP handles this via the priority scoring + fuel-integrated planning

**Scenario comparison** (when confidence < 100%):
- Solver runs twice: once with weather, once without
- Returns both plans: `plan_weather` and `plan_dry`
- Frontend shows side by side with total lap difference
- `delta_laps = plan_weather.total_laps - plan_dry.total_laps`

### Service Functions

`race_strategy_weather.py`:
- `add_weather_window(conn, race_id, start_s, end_s, condition, confidence_pct)` → id
- `update_weather_window(conn, race_id, window_id, ...)` → ok
- `delete_weather_window(conn, race_id, window_id)` → ok
- `get_weather_windows(conn, race_id)` → list[dict]
- `set_current_condition(conn, race_id, condition)` → ok

### API Endpoints
- `POST /race-strategy/<id>/weather-window` — add forecast window
- `PUT /race-strategy/<id>/weather-window/<wid>` — update
- `DELETE /race-strategy/<id>/weather-window/<wid>` — delete
- `GET /race-strategy/<id>/weather-windows` — list all
- `POST /race-strategy/<id>/condition` — set live condition (dry/damp/wet)

### Form (Pre-Race)
- Per-driver: "Wet confidence" number input (0–100%, stored as 0.0–1.0)
- Weather forecast section (complex+ tier): table of time windows
  - Columns: Start (hh:mm), End (hh:mm), Condition (dropdown), Confidence (%)
  - Add/Remove rows
  - Default: empty (full dry race assumed)

### Live Dashboard
- "Condition" button in action bar: dropdown for dry/damp/wet
- When condition changes from current, show suggestion: "Condition changed to WET — Re-optimize?"
- Current condition badge next to LIVE badge in header
- Weather forecast timeline bar (similar to stint timeline) showing forecasted conditions

---

## Architecture

### New Files
- `telemetry_tool/optimizer/csp_solver.py` — pure CSP backtracking solver, no DB, no Flask
- `telemetry_tool/optimizer/weather.py` — weather scenario evaluation, pace adjustment helpers
- `telemetry_tool/services/race_strategy_weather.py` — CRUD for weather windows + live condition

### Modified Files
- `telemetry_tool/race_strategy_v2.py` — new `optimize_stints_v2()` that calls CSP solver
- `telemetry_tool/services/race_strategy.py` — pass weather data + wet_confidence to optimizer, add `wet_confidence` to `_save_drivers`
- `telemetry_tool/db/schema.py` — `race_weather_windows` table, `wet_confidence` on drivers, `current_condition` on race_configs
- `telemetry_tool/web/routes/api_v1_race_strategy.py` — weather + condition endpoints
- `lap-website/src/components/app/race-strategy/RaceConfigForm.tsx` — wet confidence per driver, forecast window editor
- `lap-website/src/app/app/race-strategy/[id]/live/page.tsx` — condition button, weather timeline, scenario display

### Testing Strategy
- `test_csp_solver.py` — unit tests for the solver in isolation (no DB, no Flask)
  - Valid solution found for various constraint combinations
  - Backtracking triggers when greedy fails
  - Fuel exhaustion prevented
  - Sleep windows respected
  - All constraint types enforced
  - Performance: < 500ms for 24 stints × 5 drivers
- `test_weather.py` — weather pace adjustment, pit cost calculation, scenario comparison
- `test_optimizer_v2.py` — integration: full optimize_stints_v2 with weather + CSP

---

## What's NOT Included (YAGNI)
- No weather API integration (manual forecast only)
- No pace degradation model per driver
- No Monte Carlo simulation
- No tire compound modeling
- No automated live condition detection from telemetry
- No rival team strategy modeling
