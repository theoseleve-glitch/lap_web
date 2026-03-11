# Development Plans & Gamification Overhaul — Design Spec

**Date:** 2026-03-11
**Branch:** `feature/dev-plans-gamification`
**Status:** Approved

## Goal

Fix all existing issues in the development plan system and add a full gamification layer: XP/leveling, badge display, achievement tracking, streak counting, drill-session linking, and celebratory UI. Transform passive checklists into an active progression system that motivates drivers to improve.

## Current State & Problems

### What Works
- Dev plans CRUD (list, create, detail, update, delete)
- 5 pre-built templates (beginner, intermediate, advanced, race-prep, consistency-focus) in `development_plan.py` (2,743 lines)
- Free-form checklist progress (`progress_json: {items: [{text, done}]}`)
- 6 badges computed server-side (`scoring/badges.py`) — bronze/silver/gold tiers
- Dynamic drill generation from corner weakness scores (`DevelopmentDrills.tsx`)
- Progression chart (`ProgressionChart.tsx`) with score trend + consistency CV%

### Problems to Fix
1. **Badges computed but never displayed** — `evaluate_badges()` returns badges in scores response but no frontend component renders them
2. **Plans isolated from sessions** — No way to link a session to a plan drill; no drill execution tracking
3. **Progress is freeform checklist** — No structured tracking of which drill was attempted, lap count, success criteria, or metric targets
4. **No XP/leveling** — Only badges exist; no cumulative progression or driver levels
5. **No streaks/achievements** — No tracking of consecutive session days or milestone achievements
6. **No celebratory UI** — No notifications when badges earned, achievements unlocked, or plans completed
7. **Template file bloat** — `development_plan.py` is 2,743 lines with templates embedded in Python code
8. **Dynamic drills not persisted** — `DevelopmentDrills.tsx` generates drills on-the-fly; they can't be saved or tracked

## Architecture

Integrated extension of existing scoring/badges system. Minimal new tables (3), extends existing endpoints, builds focused UI components. No separate gamification microservice — this is a telemetry tool, gamification enhances it.

## Data Model

### New Table: `driver_xp`

One row per driver per workspace. Tracks cumulative XP and computed level.

```sql
CREATE TABLE driver_xp (
    id              SERIAL PRIMARY KEY,
    workspace_id    INTEGER NOT NULL REFERENCES workspaces(id),
    driver_id       INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
    total_xp        INTEGER NOT NULL DEFAULT 0,
    level           INTEGER NOT NULL DEFAULT 0,
    current_streak  INTEGER NOT NULL DEFAULT 0,
    longest_streak  INTEGER NOT NULL DEFAULT 0,
    last_session_date DATE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workspace_id, driver_id)
);
```

RLS policy: `workspace_id = current_setting('app.workspace_id')::int`

### New Table: `achievements`

Log of unlocked achievements per driver.

```sql
CREATE TABLE achievements (
    id              SERIAL PRIMARY KEY,
    workspace_id    INTEGER NOT NULL REFERENCES workspaces(id),
    driver_id       INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
    achievement_key VARCHAR(64) NOT NULL,
    unlocked_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    session_id      INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    UNIQUE (workspace_id, driver_id, achievement_key)
);
```

RLS policy: `workspace_id = current_setting('app.workspace_id')::int`

### New Table: `drill_executions`

Links sessions to plan drills. Bridges the plan-session disconnect.

```sql
CREATE TABLE drill_executions (
    id              SERIAL PRIMARY KEY,
    workspace_id    INTEGER NOT NULL REFERENCES workspaces(id),
    driver_id       INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
    plan_id         INTEGER NOT NULL REFERENCES dev_plans(id) ON DELETE CASCADE,
    week_number     INTEGER NOT NULL,
    drill_index     INTEGER NOT NULL,
    session_id      INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    status          VARCHAR(16) NOT NULL DEFAULT 'attempted'
                    CHECK (status IN ('attempted', 'completed', 'skipped')),
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workspace_id, plan_id, week_number, drill_index, session_id)
);
```

RLS policy: `workspace_id = current_setting('app.workspace_id')::int`

### Extended: `dev_plans`

Add column: `xp_earned INTEGER NOT NULL DEFAULT 0`

### XP Award Table

| Action | XP | Trigger |
|--------|-----|---------|
| Upload session | +50 | Session upload completes |
| Complete a drill | +100 | Drill execution marked 'completed' |
| Complete a plan week | +250 | All drills in week completed |
| Complete full plan | +500 | All weeks completed |
| Earn bronze badge | +75 | Badge evaluated on session |
| Earn silver badge | +150 | Badge evaluated on session |
| Earn gold badge | +300 | Badge evaluated on session |
| Maintain streak (per day) | +25 | Consecutive session day detected |
| Beat personal best lap | +200 | Best lap time improved |

### Level Formula

```python
level = floor(sqrt(total_xp / 100))
```

| Level | Total XP Required |
|-------|-------------------|
| 1 | 100 |
| 2 | 400 |
| 3 | 900 |
| 5 | 2,500 |
| 10 | 10,000 |
| 15 | 22,500 |
| 20 | 40,000 |

No cap. Logarithmic feel — early levels come fast, later ones require sustained effort.

### Achievement Catalog (15 Achievements)

**Session milestones:**
- `first_session` — "First Laps" — Upload your first session
- `sessions_10` — "Regular" — 10 sessions uploaded
- `sessions_50` — "Dedicated" — 50 sessions uploaded
- `sessions_100` — "Veteran" — 100 sessions uploaded

**Badge milestones:**
- `first_badge` — "Medal Winner" — Earn any badge
- `all_bronze` — "Bronze Collection" — All 6 badges at bronze+
- `all_silver` — "Silver Collection" — All 6 badges at silver+
- `all_gold` — "Gold Standard" — All 6 badges at gold

**Streak milestones:**
- `streak_3` — "Hat Trick" — 3-day session streak
- `streak_7` — "Week Warrior" — 7-day session streak
- `streak_30` — "Iron Will" — 30-day session streak

**Plan milestones:**
- `plan_completed` — "Plan Complete" — Finish a development plan
- `all_drills_week` — "Perfect Week" — Complete all drills in a plan week

**Performance milestones:**
- `personal_best` — "New PB" — Beat your personal best lap time
- `score_jump` — "Level Up" — Improve total score by 10+ points session over session

## Backend Module: `telemetry_tool/gamification/`

### Package Structure

```
telemetry_tool/gamification/
    __init__.py           # Public API
    xp.py                 # XP calculation, level formula, award_xp()
    achievements.py       # Achievement catalog, check_and_unlock()
    streaks.py            # Streak tracking logic
    queries.py            # All SQL for driver_xp, achievements, drill_executions
```

### Public API (`__init__.py`)

```python
from telemetry_tool.gamification.xp import award_session_xp, award_drill_xp, award_plan_xp, get_driver_progress
from telemetry_tool.gamification.achievements import check_achievements, get_achievement_status
from telemetry_tool.gamification.streaks import update_streak
```

### `xp.py` — XP Engine

- `award_session_xp(conn, driver_id, workspace_id, session_id, scores, badges)` — Main entry point called after session upload. Awards: session XP (+50), badge XP (per new tier), personal best XP, streak XP. Returns `{xp_gained, new_total, old_level, new_level, new_achievements}`.
- `award_drill_xp(conn, driver_id, workspace_id, plan_id, week, drill_index)` — Called when drill marked completed. Awards +100. Checks week/plan completion for bonus XP.
- `award_plan_xp(conn, driver_id, workspace_id, plan_id)` — Called when plan fully completed. Awards +500.
- `get_driver_progress(conn, driver_id, workspace_id)` — Returns full progress: `{total_xp, level, xp_for_next_level, current_streak, longest_streak, badges, recent_xp_events}`.
- `compute_level(total_xp)` — Pure function: `floor(sqrt(total_xp / 100))`.
- `xp_for_level(level)` — Pure function: `level ** 2 * 100`.

### `achievements.py` — Achievement Engine

- `ACHIEVEMENT_CATALOG` — Dict of 15 achievements with key, label, description, icon_hint, check function name.
- `check_achievements(conn, driver_id, workspace_id, session_id, context)` — Runs all achievement checks against current driver state. `context` contains scores, badges, streak, session_count, etc. Returns list of newly unlocked achievements.
- `get_achievement_status(conn, driver_id, workspace_id)` — Returns all 15 achievements with locked/unlocked state and unlock date.
- Each achievement has a check function: e.g., `_check_sessions_10(context)` returns True if `context["session_count"] >= 10`.

### `streaks.py` — Streak Tracker

- `update_streak(conn, driver_id, workspace_id, session_date)` — Compares `session_date` to `last_session_date`. If consecutive day: increment `current_streak`. If same day: no change. If gap: reset `current_streak` to 1. Updates `longest_streak` if beaten. Returns `{current_streak, longest_streak, streak_xp}`.

### `queries.py` — SQL Layer

- `upsert_driver_xp(conn, driver_id, workspace_id, xp_delta, level, streak, longest, last_date)` — INSERT ON CONFLICT UPDATE
- `get_driver_xp(conn, driver_id, workspace_id)` — Single row fetch
- `insert_achievement(conn, driver_id, workspace_id, key, session_id)` — INSERT ON CONFLICT DO NOTHING (idempotent)
- `get_achievements(conn, driver_id, workspace_id)` — All unlocked achievements
- `insert_drill_execution(conn, ...)` — Log drill execution
- `get_plan_executions(conn, plan_id, workspace_id)` — All executions for a plan
- `count_driver_sessions(conn, driver_id, workspace_id)` — For achievement checks
- `get_driver_best_lap(conn, driver_id, workspace_id, track_id)` — For PB detection

All queries use `sql_compat.translate_params()` for SQLite/PG portability.

## Integration Points

### Session Upload (`sessions_v2.py`)

After pipeline completes and scores are available (existing code around line ~200):

```python
# Existing: scores = score_session(...)
# Existing: badges = evaluate_badges(scores)

# NEW: Gamification
from telemetry_tool.gamification import award_session_xp, check_achievements, update_streak
xp_result = award_session_xp(conn, driver_id, workspace_id, session_id, scores, badges)
streak_result = update_streak(conn, driver_id, workspace_id, session_date)
new_achievements = check_achievements(conn, driver_id, workspace_id, session_id, {
    "scores": scores, "badges": badges,
    "streak": streak_result["current_streak"],
    "session_count": count_driver_sessions(conn, driver_id, workspace_id),
})
# Include in response for frontend toast
analysis_json["gamification"] = {
    "xp_gained": xp_result["xp_gained"],
    "new_level": xp_result["new_level"] if xp_result["new_level"] > xp_result["old_level"] else None,
    "new_achievements": [a["key"] for a in new_achievements],
    "streak": streak_result["current_streak"],
}
```

### Dev Plans Endpoints (`api_v1_entities.py`)

New endpoints added to existing blueprint:

- `POST /api/v1/dev-plans/<id>/drills/<week>/<index>/execute` — Body: `{session_id, status, notes}`. Inserts drill_execution, calls `award_drill_xp()` if status=completed.
- `GET /api/v1/dev-plans/<id>/executions` — Returns all drill executions for plan with session details.
- `GET /api/v1/drivers/<id>/progress` — Calls `get_driver_progress()` + `get_achievement_status()`.
- `GET /api/v1/drivers/<id>/achievements` — Calls `get_achievement_status()`.

## Frontend Components

### New Components (`lap-website/src/components/app/gamification/`)

#### `BadgeDisplay.tsx`
- Props: `badges: Badge[]` (from scores response)
- Shows horizontal row of medal icons
- Color: bronze (#cd7f32), silver (#c0c0c0), gold (#ffd700)
- Tooltip on hover with badge name + criteria
- Empty state: "No badges earned yet"

#### `XPProgressBar.tsx`
- Props: `totalXp: number, level: number`
- Shows level number in circle + progress bar to next level
- Acid-green fill on asphalt background
- Label: "Level {n} — {current} / {next} XP"
- Animated fill on mount (CSS transition)

#### `StreakCounter.tsx`
- Props: `currentStreak: number, longestStreak: number`
- Flame icon (emoji or SVG) + "N day streak"
- Pulse animation when streak > 0
- Tooltip: "Longest: N days"
- Hides when streak = 0

#### `AchievementGrid.tsx`
- Props: `achievements: Achievement[]` (all 15 with locked/unlocked)
- 3-column or 5-column grid of circular icons
- Unlocked: full color + name + date
- Locked: grayscale silhouette + "???"
- Count: "X / 15 unlocked"

#### `AchievementToast.tsx`
- Props: `achievement: {key, label, description}`
- Fixed position top-right
- Gold border, dark background
- Slide-in animation, auto-dismiss 5s
- Trophy icon + achievement name + description

#### `LevelUpModal.tsx`
- Props: `oldLevel: number, newLevel: number, totalXp: number`
- Centered modal with backdrop
- Shows old → new level with arrow
- Celebratory CSS animation (pulse/glow)
- "Continue" button to dismiss

#### `DrillExecutionForm.tsx`
- Props: `planId, weekNumber, drillIndex, onSubmit`
- Inline expandable form within plan detail
- Session selector (dropdown of recent sessions for this driver)
- Status: attempted / completed / skipped (radio buttons)
- Notes textarea
- Submit creates drill_execution via API

#### `PlanProgressTimeline.tsx`
- Props: `weeks: Week[], executions: DrillExecution[]`
- Vertical timeline with week nodes
- Each week shows drill names with status icons (check/spinner/circle)
- Completion percentage per week
- Connected by vertical line (acid-green for completed sections, steel for pending)

### Modified Pages

#### Session Detail `app/sessions/[id]/page.tsx`
- Add `BadgeDisplay` below scores section
- Check response for `gamification` key — if present, show `AchievementToast` for new achievements, `LevelUpModal` if level increased

#### Plan Detail `app/development/[id]/page.tsx`
- Add `PlanProgressTimeline` above existing checklist (or replace it)
- Each drill gets `DrillExecutionForm` expand button
- Show plan XP earned

#### Plans List `app/development/page.tsx`
- Show XP earned per plan on card
- Show drill-execution-based completion % (not just checklist %)

#### AppShell or Driver Header
- Add `XPProgressBar` + `StreakCounter` to the app header when a driver is selected

#### DevelopmentDrills.tsx
- Add "Save to Plan" button on each generated drill
- Opens plan selector → saves as new drill execution entry

## Migration: 042_gamification_tables

```python
revision = "042"
down_revision = "041"

def upgrade():
    # 1. driver_xp table
    # 2. achievements table
    # 3. drill_executions table
    # 4. ALTER dev_plans ADD COLUMN xp_earned INTEGER NOT NULL DEFAULT 0
    # 5. RLS policies on all 3 new tables
    # 6. Indexes: driver_xp(driver_id), achievements(driver_id, achievement_key), drill_executions(plan_id)

def downgrade():
    # Drop tables and column in reverse
```

## Existing Issue Fixes (included in this work)

1. **Badge display** — Wire `BadgeDisplay` into session detail page scores section
2. **Plan-session disconnect** — `drill_executions` table bridges this
3. **Checklist → structured tracking** — `PlanProgressTimeline` replaces freeform checklist; old `progress_json` kept as fallback for pre-migration plans
4. **Dynamic drills not persisted** — "Save to Plan" action on `DevelopmentDrills.tsx`
5. **Template bloat** — Extract 5 templates from `development_plan.py` to JSON files in `telemetry_tool/development_plan_templates/` (one per template)

## Not In Scope (YAGNI)

- Leaderboards / social features
- Custom achievements via admin UI
- XP tuning admin panel
- Animation libraries (Framer Motion, Lottie) — CSS only
- Push notifications
- Achievement sharing / social media

## Testing Strategy

- **Backend unit tests:** XP calculation (level formula, award amounts), achievement check functions, streak logic (consecutive/gap/same-day)
- **Backend integration test:** Session upload → XP award → achievement unlock → API returns progress
- **Frontend:** TypeScript type-check (`npx tsc --noEmit`), matching coaching V3 pattern
- **Migration:** Up/down test on empty database

## Priority Order

| Priority | Tasks |
|----------|-------|
| P0 | Migration 042, gamification module (xp, achievements, streaks, queries) |
| P1 | API endpoints, session upload integration, BadgeDisplay component |
| P2 | XPProgressBar, StreakCounter, AchievementGrid, AchievementToast, LevelUpModal |
| P2 | DrillExecutionForm, PlanProgressTimeline |
| P3 | Template JSON extraction, "Save to Plan" on DevelopmentDrills |
