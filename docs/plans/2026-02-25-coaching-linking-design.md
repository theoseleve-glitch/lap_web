# Coaching: Session-Drill Linking & Plan Completion

**Date:** 2026-02-25
**Status:** Approved

## Problem

Driver development plans have drills with metric targets, but no way to connect an analyzed session to a specific drill. Completing a plan has no celebration, no badge, and no aggregate stats.

## Features

### BB. Session-Drill Linking

**New table: `plan_drill_sessions`**

```sql
CREATE TABLE IF NOT EXISTS plan_drill_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id     INTEGER NOT NULL REFERENCES development_plans(id),
    week_index  INTEGER NOT NULL,
    drill_index INTEGER NOT NULL,
    session_id  TEXT NOT NULL REFERENCES sessions(session_id),
    linked_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(plan_id, week_index, drill_index, session_id)
);
```

**API endpoints:**

| Method | URL | Purpose |
|--------|-----|---------|
| POST | `/api/dev-plans/plan/<plan_id>/link-session` | Link session to drill, auto-complete drill |
| DELETE | `/api/dev-plans/plan/<plan_id>/unlink-session` | Remove link |
| GET | `/api/dev-plans/plan/<plan_id>/drill-sessions` | All linked sessions grouped by week/drill |

**Request body (link):** `{week_index, drill_index, session_id}`

**Drill evaluation:** When linked, if drill has `metric` + `target`, compare against session data. Return `met: true/false` + actual value. Informational only.

**UI (dev_plan_detail.html):**
- "Link Session" button per drill opens dropdown of driver's analyzed sessions
- Linked sessions show as compact cards: date, track, best lap, score, pass/fail indicator
- Linking auto-checks drill completion

### BC. Plan Completion Celebration

**Schema changes:**
- Add `completed_at TEXT` to `development_plans`
- New `driver_badges` table:

```sql
CREATE TABLE IF NOT EXISTS driver_badges (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id     INTEGER NOT NULL REFERENCES drivers(driver_id),
    badge_type    TEXT NOT NULL,
    badge_name    TEXT NOT NULL,
    badge_level   TEXT,
    metadata_json TEXT,
    earned_at     TEXT NOT NULL DEFAULT (datetime('now')),
    plan_id       INTEGER REFERENCES development_plans(id)
);
```

**Completion trigger:** When `completion_pct` hits 100% after progress update or session link, auto-set `status='completed'`, `completed_at=datetime('now')`. Create badge with aggregate stats.

**Aggregate stats (metadata_json):**
- `total_laps`, `total_track_time_s`, `drills_completed`, `sessions_linked`
- `improvement_pct` (first vs last linked session score)
- `skills_learned` (week titles completed)

**Celebration UI:**
- CSS+JS confetti animation (no library)
- Modal: badge earned, plan name, level, stats summary
- "View on Profile" link

**Driver profile (driver_profile.html):**
- New "Badges" section below meta-grid
- Badge cards: medal icon by level, plan name, earned date
- Click to expand: aggregate stats

## Testing

- Link/unlink session API
- Drill auto-completion on link
- Plan completion trigger + badge creation
- Aggregate stats computation
- Badge display on driver profile route
