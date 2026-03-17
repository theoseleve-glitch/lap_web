# Race Strategy Live Features Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 4 features to the race strategy live dashboard: blackout windows, tech stop, quick change mode, and penalty tracker.

**Architecture:** Each feature follows DB → service → API → frontend. Features are independent — each chunk can be built and deployed separately. The `services/race_strategy.py` file (1597 lines) is over the 500-line limit, so new service functions go into dedicated files per feature rather than growing it further.

**Tech Stack:** Python Flask API, PostgreSQL (RLS), Next.js 14, TypeScript, Tailwind CSS, TanStack Query

**Spec:** `docs/superpowers/specs/2026-03-17-race-strategy-live-features-design.md`

---

## File Map

### Backend — New Files
- `telemetry_tool/services/race_strategy_tech.py` — tech stop + blackout service functions
- `telemetry_tool/services/race_strategy_penalty.py` — penalty service functions

### Backend — Modified Files
- `telemetry_tool/db/schema.py` — add columns to race_configs, race_stints; add race_penalties table
- `telemetry_tool/race_strategy_v2.py` — optimizer blackout enforcement
- `telemetry_tool/race_state_engine.py` — quick change fuel logic
- `telemetry_tool/services/race_strategy.py` — add quick_change to create/update/pit_out, blackout fields
- `telemetry_tool/web/routes/api_v1_race_strategy.py` — new endpoints

### Frontend — Modified Files
- `lap-website/src/components/app/race-strategy/RaceConfigForm.tsx` — form fields
- `lap-website/src/app/app/race-strategy/[id]/live/page.tsx` — all 4 features in live dashboard

### Test Files
- `telemetry_tool/tests/test_blackout.py`
- `telemetry_tool/tests/test_tech_stop.py`
- `telemetry_tool/tests/test_quick_change.py`
- `telemetry_tool/tests/test_penalty.py`

---

## Chunk 1: Blackout Windows

### Task 1.1: Database columns

**Files:**
- Modify: `telemetry_tool/db/schema.py` — add columns to `_RACE_CONFIGS_TABLE`

- [ ] **Step 1: Add columns to SQLite schema**

In `schema.py`, add to `_RACE_CONFIGS_TABLE` before `quick_pit_stop_s`:
```python
    blackout_start_min  INTEGER,
    blackout_end_min    INTEGER,
```

- [ ] **Step 2: Add columns to PostgreSQL**

```bash
ssh root@46.225.227.24 "docker exec lap-api-postgres-1 psql -U telemetry -d telemetry -c \"
ALTER TABLE race_configs ADD COLUMN IF NOT EXISTS blackout_start_min INTEGER;
ALTER TABLE race_configs ADD COLUMN IF NOT EXISTS blackout_end_min INTEGER;
\""
```

- [ ] **Step 3: Commit**

```bash
git add telemetry_tool/db/schema.py
git commit -m "feat: add blackout window columns to race_configs"
```

### Task 1.2: Service — create/update support

**Files:**
- Modify: `telemetry_tool/services/race_strategy.py` — add blackout fields to create_race and update_race INSERT/UPDATE

- [ ] **Step 1: Add `blackout_start_min` and `blackout_end_min` to create_race INSERT**

Add the two columns to the INSERT statement and params tuple in `create_race()`, `import_race()`, and `duplicate_race()` (3 occurrences). Also add to `update_race()` UPDATE statement.

Values: `race.get("blackout_start_min")` and `race.get("blackout_end_min")`.

- [ ] **Step 2: Verify syntax**

```bash
python -c "import ast; ast.parse(open('telemetry_tool/services/race_strategy.py').read()); print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add telemetry_tool/services/race_strategy.py
git commit -m "feat: persist blackout window fields in create/update race"
```

### Task 1.3: Optimizer — blackout enforcement

**Files:**
- Modify: `telemetry_tool/race_strategy_v2.py`
- Test: `telemetry_tool/tests/test_blackout.py`

- [ ] **Step 1: Write tests**

Create `telemetry_tool/tests/test_blackout.py`:
```python
"""Tests for blackout window enforcement in the optimizer."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from race_strategy_v2 import optimize_stints

def _config(**overrides):
    base = {
        "race_duration_s": 14400,  # 4h
        "desired_stints": 4,
        "min_pit_stop_s": 120,
    }
    base.update(overrides)
    return base

DRIVERS = [
    {"id": 1, "driver_name": "Alice", "driver_order": 1, "weight_kg": 70},
    {"id": 2, "driver_name": "Bob", "driver_order": 2, "weight_kg": 75},
]

def test_blackout_start_enforces_minimum_first_stint():
    """First stint must be >= blackout_start_min * 60."""
    result = optimize_stints(_config(blackout_start_min=10), DRIVERS)
    first = result["stints"][0]
    assert first["planned_duration_s"] >= 600  # 10 min

def test_blackout_end_no_pit_in_final_window():
    """No pit stop should be scheduled in the last blackout_end_min minutes."""
    result = optimize_stints(_config(blackout_end_min=15), DRIVERS)
    cutoff = 14400 - 15 * 60  # 13500s
    for p in result["pit_stops"]:
        assert p["at_s"] <= cutoff

def test_no_blackout_no_change():
    """Without blackout settings, optimizer behaves as before."""
    r1 = optimize_stints(_config(), DRIVERS)
    r2 = optimize_stints(_config(blackout_start_min=None, blackout_end_min=None), DRIVERS)
    assert len(r1["stints"]) == len(r2["stints"])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest telemetry_tool/tests/test_blackout.py -v
```
Expected: `test_blackout_start_enforces_minimum_first_stint` and `test_blackout_end_no_pit_in_final_window` FAIL.

- [ ] **Step 3: Implement blackout enforcement in optimizer**

In `race_strategy_v2.py`, after the existing pit window enforcement block (around line 270), add:

```python
    # Blackout window enforcement
    blackout_start_s = (config.get("blackout_start_min") or 0) * 60
    blackout_end_s = (config.get("blackout_end_min") or 0) * 60

    if blackout_start_s > 0 and len(stints) > 1:
        first = stints[0]
        if first["planned_duration_s"] < blackout_start_s:
            deficit = blackout_start_s - first["planned_duration_s"]
            first["planned_duration_s"] = blackout_start_s
            first["planned_end_s"] = first["planned_start_s"] + blackout_start_s
            # Steal time from last stint
            stints[-1]["planned_duration_s"] = max(0, stints[-1]["planned_duration_s"] - deficit)
            # Rebuild timeline
            clock = first["planned_end_s"] + pit_time
            for j in range(1, len(stints)):
                stints[j]["planned_start_s"] = round(clock)
                stints[j]["planned_end_s"] = round(clock + stints[j]["planned_duration_s"])
                clock += stints[j]["planned_duration_s"]
                if j < len(stints) - 1:
                    clock += pit_time

    if blackout_end_s > 0 and len(stints) > 1:
        cutoff = race_duration - blackout_end_s
        # Move last pit stop to before cutoff
        last_pit_idx = len(stints) - 2
        last_pit_at = stints[last_pit_idx]["planned_end_s"]
        if last_pit_at > cutoff:
            overshoot = last_pit_at - cutoff
            stints[last_pit_idx]["planned_duration_s"] -= overshoot
            stints[last_pit_idx]["planned_end_s"] -= overshoot
            stints[-1]["planned_start_s"] -= overshoot
            stints[-1]["planned_duration_s"] += overshoot
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest telemetry_tool/tests/test_blackout.py -v
```
Expected: All PASS.

- [ ] **Step 5: Run existing tests to verify no regressions**

```bash
pytest telemetry_tool/tests/test_race_strategy_v2.py -v
```

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/race_strategy_v2.py telemetry_tool/tests/test_blackout.py
git commit -m "feat: optimizer enforces blackout windows"
```

### Task 1.4: Frontend — form fields + live warning

**Files:**
- Modify: `lap-website/src/components/app/race-strategy/RaceConfigForm.tsx`
- Modify: `lap-website/src/app/app/race-strategy/[id]/live/page.tsx`

- [ ] **Step 1: Add form fields**

In `RaceConfigForm.tsx`, add two number inputs in the Pit Strategy section (after the mandatory change / refueling checkboxes):
- "No pit first (min)" → state `blackoutStart`, payload key `blackout_start_min`
- "No pit last (min)" → state `blackoutEnd`, payload key `blackout_end_min`

- [ ] **Step 2: Add blackout warning to live dashboard**

In `live/page.tsx`, compute blackout state from `elapsed` and `race.blackout_start_min` / `race.blackout_end_min`. When in a blackout period, show a red banner above the Pit In button: "Blackout period — 20-lap penalty if you pit now. [countdown]"

- [ ] **Step 3: Build and verify**

```bash
cd lap-website && npm run build
```

- [ ] **Step 4: Deploy**

```bash
# Backend
scp telemetry_tool/race_strategy_v2.py root@46.225.227.24:/opt/lap-api/telemetry_tool/
scp telemetry_tool/services/race_strategy.py root@46.225.227.24:/opt/lap-api/telemetry_tool/services/
ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml build api && docker compose -f docker-compose.prod.yml up -d api"
# Frontend
cd lap-website && powershell -Command "Remove-Item -Path '.next','.open-next' -Recurse -Force -ErrorAction SilentlyContinue"
npm run build && npx @opennextjs/cloudflare build && OPENNEXTJS_CLOUDFLARE_SKIP_BUILD=1 npx wrangler deploy
```

- [ ] **Step 5: Commit**

```bash
git add lap-website/src/components/app/race-strategy/RaceConfigForm.tsx lap-website/src/app/app/race-strategy/\[id\]/live/page.tsx
git commit -m "feat: blackout window form fields and live dashboard warning"
```

---

## Chunk 2: Tech Stop

### Task 2.1: Database columns

**Files:**
- Modify: `telemetry_tool/db/schema.py`

- [ ] **Step 1: Add columns to SQLite schema and PostgreSQL**

Add to `_RACE_CONFIGS_TABLE`:
```python
    tech_stop_enabled       INTEGER NOT NULL DEFAULT 0,
    tech_stop_duration_s    INTEGER DEFAULT 360,
    tech_stop_window_start_s INTEGER,
    tech_stop_window_end_s  INTEGER,
```

Add to PG:
```bash
ssh root@46.225.227.24 "docker exec lap-api-postgres-1 psql -U telemetry -d telemetry -c \"
ALTER TABLE race_configs ADD COLUMN IF NOT EXISTS tech_stop_enabled BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE race_configs ADD COLUMN IF NOT EXISTS tech_stop_duration_s INTEGER DEFAULT 360;
ALTER TABLE race_configs ADD COLUMN IF NOT EXISTS tech_stop_window_start_s INTEGER;
ALTER TABLE race_configs ADD COLUMN IF NOT EXISTS tech_stop_window_end_s INTEGER;
\""
```

- [ ] **Step 2: Commit**

### Task 2.2: Service functions

**Files:**
- Create: `telemetry_tool/services/race_strategy_tech.py`
- Test: `telemetry_tool/tests/test_tech_stop.py`

- [ ] **Step 1: Write tests**

Create `telemetry_tool/tests/test_tech_stop.py` with tests for:
- `test_tech_stop_in_does_not_end_stint` — active stint stays active
- `test_tech_stop_in_sets_pit_in_at` — records pit entry time
- `test_tech_stop_out_requires_minimum_duration` — returns None if too early
- `test_tech_stop_out_records_tech_pit_stop` — creates pit_stop with type='tech'
- `test_tech_stop_out_clears_pit_state` — pit_in_at_s set to NULL
- `test_tech_stop_time_not_in_driver_total` — tech stop time excluded from drive time

- [ ] **Step 2: Implement `tech_stop_in` and `tech_stop_out`**

Create `telemetry_tool/services/race_strategy_tech.py`:
```python
"""Tech stop and blackout service functions."""
from services.race_strategy import get_race, _compute_elapsed_s

def tech_stop_in(conn, race_id):
    race = get_race(conn, race_id)
    if not race:
        return None
    elapsed = _compute_elapsed_s(race.get("race_start_ts"), race)
    # Set pit_in_at_s but do NOT change active stint status
    conn.execute(
        "UPDATE race_configs SET pit_in_at_s = ? WHERE race_id = ?",
        (elapsed, race_id),
    )
    conn.commit()
    return {"ok": True, "elapsed_s": elapsed, "tech_stop": True}

def tech_stop_out(conn, race_id):
    race = get_race(conn, race_id)
    if not race:
        return None
    pit_in_at = race.get("pit_in_at_s")
    if pit_in_at is None:
        return None
    elapsed = _compute_elapsed_s(race.get("race_start_ts"), race)
    duration = max(0, elapsed - pit_in_at)
    min_dur = race.get("tech_stop_duration_s") or 360
    if duration < min_dur:
        return None  # too early
    # Find active stint to link
    active = conn.execute(
        "SELECT stint_id FROM race_stints WHERE race_id = ? AND status = 'active'",
        (race_id,),
    ).fetchone()
    stint_id = (active["stint_id"] if isinstance(active, dict) else active[0]) if active else None
    conn.execute(
        "INSERT INTO race_pit_stops (race_id, stint_id, actual_at_s, duration_s, "
        "driver_change, refueled, pit_type) VALUES (?,?,?,?,?,?,?)",
        (race_id, stint_id, pit_in_at, duration, False, False, "tech"),
    )
    conn.execute(
        "UPDATE race_configs SET pit_in_at_s = NULL WHERE race_id = ?",
        (race_id,),
    )
    conn.commit()
    return {"ok": True, "elapsed_s": elapsed, "tech_stop_duration_s": duration}
```

- [ ] **Step 3: Run tests, verify pass**
- [ ] **Step 4: Add API endpoints in `api_v1_race_strategy.py`**

Add `POST /<race_id>/tech-stop-in` and `POST /<race_id>/tech-stop-out`.

- [ ] **Step 5: Add form fields and live dashboard button**

Form: checkbox "Mandatory tech stop" + duration + window start/end (complex+ tier).
Live: "Tech Stop" button (amber). When in tech stop, show countdown panel.

- [ ] **Step 6: Build, test, deploy, commit**

---

## Chunk 3: Quick Change Mode

### Task 3.1: Database columns

**Files:**
- Modify: `telemetry_tool/db/schema.py`

- [ ] **Step 1: Add columns**

Add to `_RACE_CONFIGS_TABLE`:
```python
    quick_change_enabled    INTEGER NOT NULL DEFAULT 0,
```

Add to `_RACE_STINTS_TABLE`:
```python
    kart_number             TEXT,
```

Add to PG:
```bash
ssh root@46.225.227.24 "docker exec lap-api-postgres-1 psql -U telemetry -d telemetry -c \"
ALTER TABLE race_configs ADD COLUMN IF NOT EXISTS quick_change_enabled BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE race_stints ADD COLUMN IF NOT EXISTS kart_number TEXT;
\""
```

- [ ] **Step 2: Commit**

### Task 3.2: Fuel logic + kart number

**Files:**
- Modify: `telemetry_tool/race_state_engine.py` — `_calc_fuel_state`
- Modify: `telemetry_tool/services/race_strategy.py` — `pit_out` accepts `kart_number`
- Test: `telemetry_tool/tests/test_quick_change.py`

- [ ] **Step 1: Write tests**

```python
def test_quick_change_fuel_always_full():
    """When quick_change_enabled, every stint starts with full fuel."""
    config = {**BASE_CONFIG, "quick_change_enabled": True}
    engine = RaceStateEngine(config, drivers, stints, pit_stops)
    for s in engine.stints:
        assert s.fuel_at_start_kg == engine.fuel_model.full_tank_kg

def test_pit_out_stores_kart_number():
    """pit_out with kart_number stores it on the new stint."""
    # Create race, go live, pit_in, then pit_out with kart_number="K42"
    # Verify race_stints row has kart_number = "K42"
```

- [ ] **Step 2: Implement fuel bypass in `_calc_fuel_state`**

In `race_state_engine.py`, at the start of `_calc_fuel_state`:
```python
if self.config.get("quick_change_enabled") and stint.stint_order > 1:
    stint.fuel_at_start_kg = fm.full_tank_kg
    # Still compute fuel_at_end normally (burns during stint)
    sc_overlap = self._neutralized_overlap(stint.planned_start_s, stint.planned_end_s)
    effective_burn_s = max(0.0, stint.planned_duration_s - sc_overlap)
    stint.fuel_at_end_kg = stint.fuel_at_start_kg - fm.burn_rate_kgs * effective_burn_s
    return
```

- [ ] **Step 3: Add `kart_number` param to `pit_out` service**

In `pit_out()`, accept `kart_number: str | None = None`. After activating the next stint, if kart_number is provided:
```python
if kart_number and next_stint:
    conn.execute(
        "UPDATE race_stints SET kart_number = ? WHERE stint_id = ?",
        (kart_number, next_stint_id),
    )
```

- [ ] **Step 4: Update pit-out API endpoint to pass kart_number from request body**
- [ ] **Step 5: Run tests, verify pass**
- [ ] **Step 6: Frontend — form checkbox, kart number input on Pit Out, kart history section, stint log column**
- [ ] **Step 7: Build, test, deploy, commit**

---

## Chunk 4: Penalty Tracker

### Task 4.1: Database table

**Files:**
- Modify: `telemetry_tool/db/schema.py`

- [ ] **Step 1: Add race_penalties table to SQLite schema**

```python
_RACE_PENALTIES_TABLE = """
CREATE TABLE IF NOT EXISTS race_penalties (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id         INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    stint_order     INTEGER,
    elapsed_s       INTEGER NOT NULL,
    penalty_type    TEXT NOT NULL,
    laps_deducted   INTEGER NOT NULL DEFAULT 0,
    passage_duration_s INTEGER,
    reason          TEXT,
    cleared         INTEGER NOT NULL DEFAULT 0,
    cleared_at_s    INTEGER,
    workspace_id    INTEGER
);
"""
```

Add to `ALL_TABLES` list.

- [ ] **Step 2: Create table in PostgreSQL**

```bash
ssh root@46.225.227.24 "docker exec lap-api-postgres-1 psql -U telemetry -d telemetry -c \"
CREATE TABLE IF NOT EXISTS race_penalties (
    id              SERIAL PRIMARY KEY,
    race_id         INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    stint_order     INTEGER,
    elapsed_s       INTEGER NOT NULL,
    penalty_type    TEXT NOT NULL,
    laps_deducted   INTEGER NOT NULL DEFAULT 0,
    passage_duration_s INTEGER,
    reason          TEXT,
    cleared         BOOLEAN NOT NULL DEFAULT false,
    cleared_at_s    INTEGER,
    workspace_id    INTEGER NOT NULL DEFAULT current_setting('app.current_workspace_id')::integer
);
CREATE INDEX IF NOT EXISTS idx_race_penalties_race ON race_penalties(race_id);
ALTER TABLE race_penalties ENABLE ROW LEVEL SECURITY;
DO \\\$\\\$ BEGIN
CREATE POLICY race_penalties_tenant ON race_penalties
    USING (workspace_id = current_setting('app.current_workspace_id')::integer)
    WITH CHECK (workspace_id = current_setting('app.current_workspace_id')::integer);
EXCEPTION WHEN duplicate_object THEN NULL;
END \\\$\\\$;
\""
```

- [ ] **Step 3: Commit**

### Task 4.2: Service functions

**Files:**
- Create: `telemetry_tool/services/race_strategy_penalty.py`
- Test: `telemetry_tool/tests/test_penalty.py`

- [ ] **Step 1: Write tests**

Tests for:
- `test_add_penalty_creates_record`
- `test_add_passage_penalty_with_duration`
- `test_clear_penalty_marks_cleared`
- `test_clear_penalty_rejects_auto_laps` — auto_laps can't be cleared
- `test_get_penalties_returns_list`
- `test_total_laps_deducted`
- `test_active_passage_exists`

- [ ] **Step 2: Implement service**

Create `telemetry_tool/services/race_strategy_penalty.py`:
```python
"""Penalty tracking service functions."""
from services.race_strategy import get_race, _compute_elapsed_s

def add_penalty(conn, race_id, penalty_type, laps_deducted, reason,
                passage_duration_s=None):
    race = get_race(conn, race_id)
    if not race:
        return None
    elapsed = _compute_elapsed_s(race.get("race_start_ts"), race)
    # Get current stint order
    active = conn.execute(
        "SELECT stint_order FROM race_stints WHERE race_id = ? AND status = 'active'",
        (race_id,),
    ).fetchone()
    stint_order = (active[0] if active else None)
    conn.execute(
        "INSERT INTO race_penalties "
        "(race_id, stint_order, elapsed_s, penalty_type, laps_deducted, "
        " passage_duration_s, reason) "
        "VALUES (?,?,?,?,?,?,?)",
        (race_id, stint_order, elapsed, penalty_type,
         laps_deducted, passage_duration_s, reason),
    )
    conn.commit()
    return {"ok": True, "elapsed_s": elapsed}

def clear_penalty(conn, race_id, penalty_id):
    race = get_race(conn, race_id)
    if not race:
        return None
    elapsed = _compute_elapsed_s(race.get("race_start_ts"), race)
    row = conn.execute(
        "SELECT * FROM race_penalties WHERE id = ? AND race_id = ?",
        (penalty_id, race_id),
    ).fetchone()
    if not row:
        return None
    conn.execute(
        "UPDATE race_penalties SET cleared = true, cleared_at_s = ? WHERE id = ?",
        (elapsed, penalty_id),
    )
    conn.commit()
    return {"ok": True}

def get_penalties(conn, race_id):
    rows = conn.execute(
        "SELECT * FROM race_penalties WHERE race_id = ? ORDER BY elapsed_s",
        (race_id,),
    ).fetchall()
    return [dict(r) for r in rows]

def get_active_passage(conn, race_id):
    """Return the first uncleared passage penalty, or None."""
    row = conn.execute(
        "SELECT * FROM race_penalties "
        "WHERE race_id = ? AND penalty_type = 'passage' AND cleared = false "
        "ORDER BY elapsed_s LIMIT 1",
        (race_id,),
    ).fetchone()
    return dict(row) if row else None
```

- [ ] **Step 3: Run tests, verify pass**

- [ ] **Step 4: Add API endpoints**

In `api_v1_race_strategy.py`:
- `POST /<race_id>/penalty` — add penalty
- `POST /<race_id>/penalty/<penalty_id>/clear` — clear passage penalty
- `GET /<race_id>/penalties` — list penalties

- [ ] **Step 5: Add penalties to live state response**

In `get_live_state()`, query penalties and include:
```python
penalties = get_penalties(conn, race_id)
active_passage = get_active_passage(conn, race_id)
# Add to return dict:
"penalties": penalties,
"active_passage": active_passage,
"total_penalty_laps": sum(p.get("laps_deducted", 0) for p in penalties),
```

- [ ] **Step 6: Frontend — penalty button, inline form, banner, log, passage enforcement on pit out**

Live dashboard:
- "Penalty" button (red) in action bar → inline form
- Active passage banner when unserved
- Penalty log (collapsible)
- Pit Out disabled until passage time served (when active passage + in pit)
- Driver summary: show total penalty laps

- [ ] **Step 7: Build, test, deploy, commit**

---

## Deployment Sequence

Each chunk can be deployed independently. For each:
1. Run all tests locally
2. `scp` backend files to VPS
3. `docker compose build api && up -d api`
4. `curl healthz` to verify
5. Build + deploy frontend via OpenNext + Wrangler
6. Verify on live site
