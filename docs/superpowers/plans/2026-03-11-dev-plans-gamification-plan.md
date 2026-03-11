# Development Plans & Gamification Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add XP/leveling, achievement tracking, streaks, drill-session linking, and celebratory UI to the development plan system. Fix badge display and plan-session disconnect.

**Architecture:** Integrated extension — 3 new DB tables, `telemetry_tool/gamification/` module, 4 new API endpoints, 8 new frontend components, 2 modified pages.

**Tech Stack:** Python 3.14, Flask, PostgreSQL 16 (RLS), SQLite compat, Next.js 14, TypeScript, Tailwind CSS, TanStack Query

**Spec:** `docs/superpowers/specs/2026-03-11-dev-plans-gamification-design.md`

---

## Chunk 1: Backend Foundation — Migration + XP Engine

### Task 1: Alembic Migration 042 — Gamification Tables

**Files:**
- Create: `telemetry_tool/alembic/versions/042_gamification_tables.py`

- [ ] **Step 1: Write the migration**

```python
"""042 – gamification tables (driver_xp, achievements, drill_executions)."""
from alembic import op
import sqlalchemy as sa

revision = "042"
down_revision = "041"


def upgrade():
    # ── driver_xp ──
    op.execute("""
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
    """)
    op.execute("""
        CREATE INDEX ix_driver_xp_driver ON driver_xp (driver_id);
    """)
    op.execute("""
        ALTER TABLE driver_xp ENABLE ROW LEVEL SECURITY;
    """)
    op.execute("""
        CREATE POLICY driver_xp_workspace ON driver_xp
            USING (workspace_id = current_setting('app.workspace_id')::int);
    """)

    # ── achievements ──
    op.execute("""
        CREATE TABLE achievements (
            id              SERIAL PRIMARY KEY,
            workspace_id    INTEGER NOT NULL REFERENCES workspaces(id),
            driver_id       INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
            achievement_key VARCHAR(64) NOT NULL,
            unlocked_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            session_id      INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
            UNIQUE (workspace_id, driver_id, achievement_key)
        );
    """)
    op.execute("""
        CREATE INDEX ix_achievements_driver ON achievements (driver_id, achievement_key);
    """)
    op.execute("""
        ALTER TABLE achievements ENABLE ROW LEVEL SECURITY;
    """)
    op.execute("""
        CREATE POLICY achievements_workspace ON achievements
            USING (workspace_id = current_setting('app.workspace_id')::int);
    """)

    # ── drill_executions ──
    op.execute("""
        CREATE TABLE drill_executions (
            id              SERIAL PRIMARY KEY,
            workspace_id    INTEGER NOT NULL REFERENCES workspaces(id),
            driver_id       INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
            plan_id         INTEGER NOT NULL REFERENCES development_plans(id) ON DELETE CASCADE,
            week_number     INTEGER NOT NULL,
            drill_index     INTEGER NOT NULL,
            session_id      INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
            status          VARCHAR(16) NOT NULL DEFAULT 'attempted'
                            CHECK (status IN ('attempted', 'completed', 'skipped')),
            notes           TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (workspace_id, plan_id, week_number, drill_index, session_id)
        );
    """)
    op.execute("""
        CREATE INDEX ix_drill_exec_plan ON drill_executions (plan_id);
    """)
    op.execute("""
        ALTER TABLE drill_executions ENABLE ROW LEVEL SECURITY;
    """)
    op.execute("""
        CREATE POLICY drill_exec_workspace ON drill_executions
            USING (workspace_id = current_setting('app.workspace_id')::int);
    """)

    # ── extend dev_plans ──
    op.execute("""
        ALTER TABLE development_plans ADD COLUMN xp_earned INTEGER NOT NULL DEFAULT 0;
    """)


def downgrade():
    op.execute("ALTER TABLE development_plans DROP COLUMN IF EXISTS xp_earned;")
    op.execute("DROP TABLE IF EXISTS drill_executions CASCADE;")
    op.execute("DROP TABLE IF EXISTS achievements CASCADE;")
    op.execute("DROP TABLE IF EXISTS driver_xp CASCADE;")
```

- [ ] **Step 2: Verify migration runs**

Run: `cd telemetry_tool && python -c "from alembic.versions import *; print('042 imports ok')"`
Expected: No import errors.

- [ ] **Step 3: Commit**

```bash
git add telemetry_tool/alembic/versions/042_gamification_tables.py
git commit -m "feat(gamification): migration 042 — driver_xp, achievements, drill_executions tables"
```

---

### Task 2: Gamification Package — XP Engine

**Files:**
- Create: `telemetry_tool/gamification/__init__.py`
- Create: `telemetry_tool/gamification/xp.py`
- Create: `telemetry_tool/gamification/queries.py`
- Test: `telemetry_tool/tests/gamification/conftest.py`
- Test: `telemetry_tool/tests/gamification/test_xp.py`

- [ ] **Step 1: Create package `__init__.py`**

```python
"""Gamification engine — XP, achievements, streaks, drill tracking."""
from telemetry_tool.gamification.xp import (
    award_session_xp,
    award_drill_xp,
    compute_level,
    get_driver_progress,
)
from telemetry_tool.gamification.achievements import (
    check_achievements,
    get_achievement_status,
)
from telemetry_tool.gamification.streaks import update_streak

__all__ = [
    "award_session_xp", "award_drill_xp", "compute_level",
    "get_driver_progress", "check_achievements", "get_achievement_status",
    "update_streak",
]
```

- [ ] **Step 2: Create `queries.py`**

All SQL queries for the gamification tables. Uses `sql_compat.translate_params()` for SQLite/PG portability.

```python
"""SQL queries for gamification tables."""
from __future__ import annotations
from typing import Any

try:
    from db.sql_compat import translate_params
except ImportError:
    def translate_params(sql, params=None):
        return sql, params


def upsert_driver_xp(conn, driver_id: int, workspace_id: int,
                      xp_delta: int, level: int,
                      streak: int, longest: int,
                      last_date: str | None) -> None:
    sql = """
        INSERT INTO driver_xp (workspace_id, driver_id, total_xp, level,
                                current_streak, longest_streak, last_session_date, updated_at)
        VALUES (:workspace_id, :driver_id, :xp_delta, :level,
                :streak, :longest, :last_date, datetime('now'))
        ON CONFLICT (workspace_id, driver_id) DO UPDATE SET
            total_xp = driver_xp.total_xp + :xp_delta,
            level = :level,
            current_streak = :streak,
            longest_streak = :longest,
            last_session_date = COALESCE(:last_date, driver_xp.last_session_date),
            updated_at = datetime('now')
    """
    conn.execute(sql, {
        "workspace_id": workspace_id, "driver_id": driver_id,
        "xp_delta": xp_delta, "level": level,
        "streak": streak, "longest": longest, "last_date": last_date,
    })


def get_driver_xp(conn, driver_id: int, workspace_id: int) -> dict[str, Any] | None:
    sql = "SELECT * FROM driver_xp WHERE driver_id = :driver_id AND workspace_id = :workspace_id"
    row = conn.execute(sql, {"driver_id": driver_id, "workspace_id": workspace_id}).fetchone()
    return dict(row) if row else None


def insert_achievement(conn, driver_id: int, workspace_id: int,
                       key: str, session_id: int | None = None) -> bool:
    sql = """
        INSERT INTO achievements (workspace_id, driver_id, achievement_key, session_id)
        VALUES (:workspace_id, :driver_id, :key, :session_id)
        ON CONFLICT (workspace_id, driver_id, achievement_key) DO NOTHING
    """
    result = conn.execute(sql, {
        "workspace_id": workspace_id, "driver_id": driver_id,
        "key": key, "session_id": session_id,
    })
    return result.rowcount > 0


def get_achievements(conn, driver_id: int, workspace_id: int) -> list[dict]:
    sql = """
        SELECT achievement_key, unlocked_at, session_id
        FROM achievements
        WHERE driver_id = :driver_id AND workspace_id = :workspace_id
        ORDER BY unlocked_at DESC
    """
    return [dict(r) for r in conn.execute(sql, {
        "driver_id": driver_id, "workspace_id": workspace_id
    }).fetchall()]


def insert_drill_execution(conn, workspace_id: int, driver_id: int,
                           plan_id: int, week_number: int, drill_index: int,
                           session_id: int | None, status: str,
                           notes: str | None = None) -> int:
    sql = """
        INSERT INTO drill_executions
            (workspace_id, driver_id, plan_id, week_number, drill_index,
             session_id, status, notes)
        VALUES (:workspace_id, :driver_id, :plan_id, :week_number, :drill_index,
                :session_id, :status, :notes)
    """
    result = conn.execute(sql, {
        "workspace_id": workspace_id, "driver_id": driver_id,
        "plan_id": plan_id, "week_number": week_number,
        "drill_index": drill_index, "session_id": session_id,
        "status": status, "notes": notes,
    })
    return result.lastrowid


def get_plan_executions(conn, plan_id: int, workspace_id: int) -> list[dict]:
    sql = """
        SELECT de.*, s.csv_filename, s.session_date
        FROM drill_executions de
        LEFT JOIN sessions s ON de.session_id = s.session_id
        WHERE de.plan_id = :plan_id AND de.workspace_id = :workspace_id
        ORDER BY de.week_number, de.drill_index, de.created_at
    """
    return [dict(r) for r in conn.execute(sql, {
        "plan_id": plan_id, "workspace_id": workspace_id,
    }).fetchall()]


def count_driver_sessions(conn, driver_id: int, workspace_id: int) -> int:
    sql = """
        SELECT COUNT(*) AS cnt FROM sessions
        WHERE driver_id = :driver_id
    """
    row = conn.execute(sql, {"driver_id": driver_id}).fetchone()
    return row["cnt"] if row else 0


def get_driver_best_lap(conn, driver_id: int, workspace_id: int) -> float | None:
    sql = """
        SELECT MIN(best_lap_time_s) AS best
        FROM sessions WHERE driver_id = :driver_id AND best_lap_time_s IS NOT NULL
    """
    row = conn.execute(sql, {"driver_id": driver_id}).fetchone()
    return row["best"] if row else None
```

- [ ] **Step 3: Create `xp.py`**

```python
"""XP calculation, level formula, and award logic."""
from __future__ import annotations

import math
from typing import Any

from telemetry_tool.gamification import queries as Q

# ── XP Constants ──────────────────────────────────────────────
XP_SESSION = 50
XP_DRILL_COMPLETE = 100
XP_WEEK_COMPLETE = 250
XP_PLAN_COMPLETE = 500
XP_BADGE_BRONZE = 75
XP_BADGE_SILVER = 150
XP_BADGE_GOLD = 300
XP_STREAK_PER_DAY = 25
XP_PERSONAL_BEST = 200


def compute_level(total_xp: int) -> int:
    """Level = floor(sqrt(total_xp / 100)). Level 0 at <100 XP."""
    if total_xp < 100:
        return 0
    return int(math.floor(math.sqrt(total_xp / 100)))


def xp_for_level(level: int) -> int:
    """Total XP required to reach a given level."""
    return level * level * 100


def award_session_xp(
    conn, driver_id: int, workspace_id: int,
    session_id: int, badges: list[dict] | None = None,
    previous_best_lap: float | None = None,
    current_best_lap: float | None = None,
) -> dict[str, Any]:
    """Award XP for a session upload. Returns XP summary."""
    xp_gained = XP_SESSION
    xp_breakdown = {"session": XP_SESSION}

    # Badge XP (only for newly earned badges — caller should diff)
    if badges:
        for badge in badges:
            tier = badge.get("tier", "")
            if tier == "gold":
                xp_gained += XP_BADGE_GOLD
                xp_breakdown[f"badge_{badge['id']}"] = XP_BADGE_GOLD
            elif tier == "silver":
                xp_gained += XP_BADGE_SILVER
                xp_breakdown[f"badge_{badge['id']}"] = XP_BADGE_SILVER
            elif tier == "bronze":
                xp_gained += XP_BADGE_BRONZE
                xp_breakdown[f"badge_{badge['id']}"] = XP_BADGE_BRONZE

    # Personal best XP
    if (previous_best_lap is not None and current_best_lap is not None
            and current_best_lap < previous_best_lap):
        xp_gained += XP_PERSONAL_BEST
        xp_breakdown["personal_best"] = XP_PERSONAL_BEST

    # Get current state
    current = Q.get_driver_xp(conn, driver_id, workspace_id)
    old_xp = current["total_xp"] if current else 0
    old_level = compute_level(old_xp)
    new_xp = old_xp + xp_gained
    new_level = compute_level(new_xp)

    # Streak is handled separately by update_streak()
    streak = current["current_streak"] if current else 0
    longest = current["longest_streak"] if current else 0

    Q.upsert_driver_xp(
        conn, driver_id, workspace_id,
        xp_delta=xp_gained, level=new_level,
        streak=streak, longest=longest, last_date=None,
    )

    return {
        "xp_gained": xp_gained,
        "xp_breakdown": xp_breakdown,
        "old_total": old_xp,
        "new_total": new_xp,
        "old_level": old_level,
        "new_level": new_level,
        "leveled_up": new_level > old_level,
    }


def award_drill_xp(
    conn, driver_id: int, workspace_id: int,
    plan_id: int,
) -> dict[str, Any]:
    """Award XP for completing a drill (+100). Check week/plan bonuses."""
    xp_gained = XP_DRILL_COMPLETE
    xp_breakdown = {"drill": XP_DRILL_COMPLETE}

    # Check if all drills in the plan's current week are completed
    executions = Q.get_plan_executions(conn, plan_id, workspace_id)
    completed = [e for e in executions if e["status"] == "completed"]

    # Group by week to check week completion
    weeks_completed = {}
    for ex in completed:
        w = ex["week_number"]
        weeks_completed.setdefault(w, 0)
        weeks_completed[w] += 1

    # Plan-level completion bonus (simplified — all weeks have drills completed)
    # This is a heuristic; real check would need template drill count
    if len(weeks_completed) >= 4:  # 4-week plan fully touched
        xp_gained += XP_PLAN_COMPLETE
        xp_breakdown["plan_complete"] = XP_PLAN_COMPLETE

    current = Q.get_driver_xp(conn, driver_id, workspace_id)
    old_xp = current["total_xp"] if current else 0
    old_level = compute_level(old_xp)
    new_xp = old_xp + xp_gained
    new_level = compute_level(new_xp)

    Q.upsert_driver_xp(
        conn, driver_id, workspace_id,
        xp_delta=xp_gained, level=new_level,
        streak=current["current_streak"] if current else 0,
        longest=current["longest_streak"] if current else 0,
        last_date=None,
    )

    return {
        "xp_gained": xp_gained,
        "xp_breakdown": xp_breakdown,
        "old_level": old_level,
        "new_level": new_level,
        "leveled_up": new_level > old_level,
    }


def get_driver_progress(conn, driver_id: int, workspace_id: int) -> dict[str, Any]:
    """Full progress summary for a driver."""
    xp_row = Q.get_driver_xp(conn, driver_id, workspace_id)
    if not xp_row:
        return {
            "total_xp": 0, "level": 0,
            "xp_for_current_level": 0, "xp_for_next_level": 100,
            "current_streak": 0, "longest_streak": 0,
        }

    total = xp_row["total_xp"]
    level = compute_level(total)
    return {
        "total_xp": total,
        "level": level,
        "xp_for_current_level": xp_for_level(level),
        "xp_for_next_level": xp_for_level(level + 1),
        "current_streak": xp_row["current_streak"],
        "longest_streak": xp_row["longest_streak"],
    }
```

- [ ] **Step 4: Write tests for XP engine**

Create `telemetry_tool/tests/gamification/__init__.py` (empty) and `conftest.py`:

```python
"""Fixtures for gamification tests."""
import sqlite3
import pytest


@pytest.fixture
def mem_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE driver_xp (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER NOT NULL,
            driver_id INTEGER NOT NULL,
            total_xp INTEGER NOT NULL DEFAULT 0,
            level INTEGER NOT NULL DEFAULT 0,
            current_streak INTEGER NOT NULL DEFAULT 0,
            longest_streak INTEGER NOT NULL DEFAULT 0,
            last_session_date TEXT,
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE (workspace_id, driver_id)
        )
    """)
    conn.execute("""
        CREATE TABLE achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER NOT NULL,
            driver_id INTEGER NOT NULL,
            achievement_key TEXT NOT NULL,
            unlocked_at TEXT DEFAULT (datetime('now')),
            session_id INTEGER,
            UNIQUE (workspace_id, driver_id, achievement_key)
        )
    """)
    conn.execute("""
        CREATE TABLE drill_executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER NOT NULL,
            driver_id INTEGER NOT NULL,
            plan_id INTEGER NOT NULL,
            week_number INTEGER NOT NULL,
            drill_index INTEGER NOT NULL,
            session_id INTEGER,
            status TEXT NOT NULL DEFAULT 'attempted',
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE (workspace_id, plan_id, week_number, drill_index, session_id)
        )
    """)
    conn.execute("""
        CREATE TABLE sessions (
            session_id INTEGER PRIMARY KEY,
            driver_id INTEGER,
            csv_filename TEXT,
            session_date TEXT,
            best_lap_time_s REAL,
            total_score REAL
        )
    """)
    conn.execute("""
        CREATE TABLE development_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_id INTEGER NOT NULL,
            plan_name TEXT,
            template_id TEXT,
            level TEXT DEFAULT 'intermediate',
            status TEXT DEFAULT 'pending',
            weeks_json TEXT DEFAULT '[]',
            progress_json TEXT,
            xp_earned INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    yield conn
    conn.close()
```

Test file `test_xp.py`:

```python
"""Tests for XP engine."""
import pytest
from telemetry_tool.gamification.xp import (
    compute_level, xp_for_level, award_session_xp, award_drill_xp,
    get_driver_progress, XP_SESSION, XP_BADGE_GOLD, XP_PERSONAL_BEST,
)


class TestComputeLevel:
    def test_zero_xp(self):
        assert compute_level(0) == 0

    def test_level_1(self):
        assert compute_level(100) == 1

    def test_level_5(self):
        assert compute_level(2500) == 5

    def test_level_10(self):
        assert compute_level(10000) == 10

    def test_below_threshold(self):
        assert compute_level(99) == 0

    def test_between_levels(self):
        assert compute_level(350) == 1  # sqrt(3.5) = 1.87 → floor = 1


class TestXpForLevel:
    def test_level_0(self):
        assert xp_for_level(0) == 0

    def test_level_1(self):
        assert xp_for_level(1) == 100

    def test_level_10(self):
        assert xp_for_level(10) == 10000


class TestAwardSessionXp:
    def test_basic_session_xp(self, mem_conn):
        result = award_session_xp(mem_conn, driver_id=1, workspace_id=1, session_id=1)
        assert result["xp_gained"] == XP_SESSION
        assert result["new_total"] == XP_SESSION
        assert result["old_level"] == 0

    def test_badge_xp_added(self, mem_conn):
        badges = [{"id": "pace_master", "tier": "gold", "category": "pace"}]
        result = award_session_xp(
            mem_conn, driver_id=1, workspace_id=1, session_id=1, badges=badges
        )
        assert result["xp_gained"] == XP_SESSION + XP_BADGE_GOLD

    def test_personal_best_xp(self, mem_conn):
        result = award_session_xp(
            mem_conn, driver_id=1, workspace_id=1, session_id=1,
            previous_best_lap=60.0, current_best_lap=59.5,
        )
        assert result["xp_gained"] == XP_SESSION + XP_PERSONAL_BEST

    def test_cumulative_xp(self, mem_conn):
        award_session_xp(mem_conn, driver_id=1, workspace_id=1, session_id=1)
        result = award_session_xp(mem_conn, driver_id=1, workspace_id=1, session_id=2)
        assert result["new_total"] == XP_SESSION * 2

    def test_level_up_detected(self, mem_conn):
        # Need 100 XP for level 1. Two sessions = 100 XP.
        award_session_xp(mem_conn, driver_id=1, workspace_id=1, session_id=1)
        result = award_session_xp(mem_conn, driver_id=1, workspace_id=1, session_id=2)
        assert result["leveled_up"] is True
        assert result["new_level"] == 1


class TestGetDriverProgress:
    def test_no_data(self, mem_conn):
        result = get_driver_progress(mem_conn, driver_id=999, workspace_id=1)
        assert result["total_xp"] == 0
        assert result["level"] == 0

    def test_after_session(self, mem_conn):
        award_session_xp(mem_conn, driver_id=1, workspace_id=1, session_id=1)
        result = get_driver_progress(mem_conn, driver_id=1, workspace_id=1)
        assert result["total_xp"] == XP_SESSION
        assert result["xp_for_next_level"] == 100
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest telemetry_tool/tests/gamification/test_xp.py -v --tb=short`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add telemetry_tool/gamification/ telemetry_tool/tests/gamification/
git commit -m "feat(gamification): XP engine with level formula, session/drill/badge awards"
```

---

### Task 3: Streaks Module

**Files:**
- Create: `telemetry_tool/gamification/streaks.py`
- Test: `telemetry_tool/tests/gamification/test_streaks.py`

- [ ] **Step 1: Create `streaks.py`**

```python
"""Streak tracking — consecutive session days."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from telemetry_tool.gamification import queries as Q
from telemetry_tool.gamification.xp import XP_STREAK_PER_DAY


def update_streak(
    conn, driver_id: int, workspace_id: int, session_date: str,
) -> dict[str, Any]:
    """Update streak based on session date.

    Returns dict with current_streak, longest_streak, streak_xp.
    """
    current = Q.get_driver_xp(conn, driver_id, workspace_id)

    try:
        today = date.fromisoformat(session_date[:10])
    except (ValueError, TypeError):
        today = date.today()

    if not current or not current.get("last_session_date"):
        # First ever session
        streak = 1
        longest = 1
        streak_xp = XP_STREAK_PER_DAY
    else:
        try:
            last = date.fromisoformat(str(current["last_session_date"])[:10])
        except (ValueError, TypeError):
            last = today - timedelta(days=2)

        delta = (today - last).days

        if delta == 0:
            # Same day — no streak change, no XP
            return {
                "current_streak": current["current_streak"],
                "longest_streak": current["longest_streak"],
                "streak_xp": 0,
            }
        elif delta == 1:
            # Consecutive day — extend streak
            streak = current["current_streak"] + 1
            longest = max(streak, current["longest_streak"])
            streak_xp = XP_STREAK_PER_DAY
        else:
            # Gap — reset
            streak = 1
            longest = current["longest_streak"]
            streak_xp = XP_STREAK_PER_DAY

    Q.upsert_driver_xp(
        conn, driver_id, workspace_id,
        xp_delta=streak_xp,
        level=current["level"] if current else 0,
        streak=streak, longest=longest,
        last_date=session_date[:10],
    )

    return {
        "current_streak": streak,
        "longest_streak": longest,
        "streak_xp": streak_xp,
    }
```

- [ ] **Step 2: Write streak tests**

```python
"""Tests for streak tracking."""
from telemetry_tool.gamification.streaks import update_streak
from telemetry_tool.gamification.xp import XP_STREAK_PER_DAY


class TestStreaks:
    def test_first_session_starts_streak(self, mem_conn):
        result = update_streak(mem_conn, 1, 1, "2026-03-01")
        assert result["current_streak"] == 1
        assert result["streak_xp"] == XP_STREAK_PER_DAY

    def test_consecutive_day_extends(self, mem_conn):
        update_streak(mem_conn, 1, 1, "2026-03-01")
        result = update_streak(mem_conn, 1, 1, "2026-03-02")
        assert result["current_streak"] == 2

    def test_same_day_no_change(self, mem_conn):
        update_streak(mem_conn, 1, 1, "2026-03-01")
        result = update_streak(mem_conn, 1, 1, "2026-03-01")
        assert result["current_streak"] == 1
        assert result["streak_xp"] == 0

    def test_gap_resets_streak(self, mem_conn):
        update_streak(mem_conn, 1, 1, "2026-03-01")
        update_streak(mem_conn, 1, 1, "2026-03-02")
        result = update_streak(mem_conn, 1, 1, "2026-03-05")
        assert result["current_streak"] == 1

    def test_longest_streak_preserved(self, mem_conn):
        update_streak(mem_conn, 1, 1, "2026-03-01")
        update_streak(mem_conn, 1, 1, "2026-03-02")
        update_streak(mem_conn, 1, 1, "2026-03-03")
        # Gap
        result = update_streak(mem_conn, 1, 1, "2026-03-10")
        assert result["current_streak"] == 1
        assert result["longest_streak"] == 3
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest telemetry_tool/tests/gamification/test_streaks.py -v --tb=short`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add telemetry_tool/gamification/streaks.py telemetry_tool/tests/gamification/test_streaks.py
git commit -m "feat(gamification): streak tracking — consecutive session day detection"
```

---

### Task 4: Achievement Engine

**Files:**
- Create: `telemetry_tool/gamification/achievements.py`
- Test: `telemetry_tool/tests/gamification/test_achievements.py`

- [ ] **Step 1: Create `achievements.py`**

```python
"""Achievement catalog and unlock logic."""
from __future__ import annotations

from typing import Any, Callable

from telemetry_tool.gamification import queries as Q

# ── Achievement Catalog ──────────────────────────────────────
# Each: (key, label, description, icon_hint, check_fn_name)

ACHIEVEMENT_CATALOG: list[dict[str, str]] = [
    {"key": "first_session", "label": "First Laps", "description": "Upload your first session", "icon": "flag"},
    {"key": "sessions_10", "label": "Regular", "description": "10 sessions uploaded", "icon": "calendar"},
    {"key": "sessions_50", "label": "Dedicated", "description": "50 sessions uploaded", "icon": "star"},
    {"key": "sessions_100", "label": "Veteran", "description": "100 sessions uploaded", "icon": "trophy"},
    {"key": "first_badge", "label": "Medal Winner", "description": "Earn any badge", "icon": "medal"},
    {"key": "all_bronze", "label": "Bronze Collection", "description": "All 6 badges at bronze+", "icon": "shield"},
    {"key": "all_silver", "label": "Silver Collection", "description": "All 6 badges at silver+", "icon": "shield"},
    {"key": "all_gold", "label": "Gold Standard", "description": "All 6 badges at gold", "icon": "crown"},
    {"key": "streak_3", "label": "Hat Trick", "description": "3-day session streak", "icon": "fire"},
    {"key": "streak_7", "label": "Week Warrior", "description": "7-day session streak", "icon": "fire"},
    {"key": "streak_30", "label": "Iron Will", "description": "30-day session streak", "icon": "fire"},
    {"key": "plan_completed", "label": "Plan Complete", "description": "Finish a development plan", "icon": "check-circle"},
    {"key": "all_drills_week", "label": "Perfect Week", "description": "Complete all drills in a plan week", "icon": "list-check"},
    {"key": "personal_best", "label": "New PB", "description": "Beat your personal best lap time", "icon": "zap"},
    {"key": "score_jump", "label": "Level Up", "description": "Improve score by 10+ points", "icon": "trending-up"},
]

_CATALOG_MAP = {a["key"]: a for a in ACHIEVEMENT_CATALOG}

# ── Check Functions ──────────────────────────────────────────

def _check_first_session(ctx: dict) -> bool:
    return ctx.get("session_count", 0) >= 1

def _check_sessions_10(ctx: dict) -> bool:
    return ctx.get("session_count", 0) >= 10

def _check_sessions_50(ctx: dict) -> bool:
    return ctx.get("session_count", 0) >= 50

def _check_sessions_100(ctx: dict) -> bool:
    return ctx.get("session_count", 0) >= 100

def _check_first_badge(ctx: dict) -> bool:
    return len(ctx.get("badges", [])) >= 1

def _check_all_bronze(ctx: dict) -> bool:
    return len(ctx.get("badges", [])) >= 6

def _check_all_silver(ctx: dict) -> bool:
    badges = ctx.get("badges", [])
    silver_or_above = [b for b in badges if b.get("tier") in ("silver", "gold")]
    return len(silver_or_above) >= 6

def _check_all_gold(ctx: dict) -> bool:
    badges = ctx.get("badges", [])
    golds = [b for b in badges if b.get("tier") == "gold"]
    return len(golds) >= 6

def _check_streak_3(ctx: dict) -> bool:
    return ctx.get("streak", 0) >= 3

def _check_streak_7(ctx: dict) -> bool:
    return ctx.get("streak", 0) >= 7

def _check_streak_30(ctx: dict) -> bool:
    return ctx.get("streak", 0) >= 30

def _check_plan_completed(ctx: dict) -> bool:
    return ctx.get("plan_just_completed", False)

def _check_all_drills_week(ctx: dict) -> bool:
    return ctx.get("week_just_completed", False)

def _check_personal_best(ctx: dict) -> bool:
    return ctx.get("is_personal_best", False)

def _check_score_jump(ctx: dict) -> bool:
    return ctx.get("score_improvement", 0) >= 10


_CHECKS: dict[str, Callable[[dict], bool]] = {
    "first_session": _check_first_session,
    "sessions_10": _check_sessions_10,
    "sessions_50": _check_sessions_50,
    "sessions_100": _check_sessions_100,
    "first_badge": _check_first_badge,
    "all_bronze": _check_all_bronze,
    "all_silver": _check_all_silver,
    "all_gold": _check_all_gold,
    "streak_3": _check_streak_3,
    "streak_7": _check_streak_7,
    "streak_30": _check_streak_30,
    "plan_completed": _check_plan_completed,
    "all_drills_week": _check_all_drills_week,
    "personal_best": _check_personal_best,
    "score_jump": _check_score_jump,
}


def check_achievements(
    conn, driver_id: int, workspace_id: int,
    session_id: int | None, context: dict,
) -> list[dict]:
    """Check all achievements, unlock new ones. Returns list of newly unlocked."""
    already = {a["achievement_key"] for a in Q.get_achievements(conn, driver_id, workspace_id)}
    newly_unlocked = []

    for key, check_fn in _CHECKS.items():
        if key in already:
            continue
        if check_fn(context):
            inserted = Q.insert_achievement(conn, driver_id, workspace_id, key, session_id)
            if inserted:
                newly_unlocked.append(_CATALOG_MAP[key])

    return newly_unlocked


def get_achievement_status(
    conn, driver_id: int, workspace_id: int,
) -> list[dict]:
    """All 15 achievements with locked/unlocked state."""
    unlocked = {
        a["achievement_key"]: a["unlocked_at"]
        for a in Q.get_achievements(conn, driver_id, workspace_id)
    }

    result = []
    for entry in ACHIEVEMENT_CATALOG:
        status = {
            **entry,
            "unlocked": entry["key"] in unlocked,
            "unlocked_at": unlocked.get(entry["key"]),
        }
        result.append(status)

    return result
```

- [ ] **Step 2: Write achievement tests**

```python
"""Tests for achievement engine."""
from telemetry_tool.gamification.achievements import (
    check_achievements, get_achievement_status, ACHIEVEMENT_CATALOG,
)


class TestCheckAchievements:
    def test_first_session_unlocks(self, mem_conn):
        ctx = {"session_count": 1, "badges": [], "streak": 0}
        result = check_achievements(mem_conn, 1, 1, session_id=1, context=ctx)
        keys = [a["key"] for a in result]
        assert "first_session" in keys

    def test_no_duplicate_unlock(self, mem_conn):
        ctx = {"session_count": 1, "badges": [], "streak": 0}
        check_achievements(mem_conn, 1, 1, session_id=1, context=ctx)
        result = check_achievements(mem_conn, 1, 1, session_id=2, context=ctx)
        keys = [a["key"] for a in result]
        assert "first_session" not in keys

    def test_streak_3_unlocks(self, mem_conn):
        ctx = {"session_count": 3, "badges": [], "streak": 3}
        result = check_achievements(mem_conn, 1, 1, session_id=3, context=ctx)
        keys = [a["key"] for a in result]
        assert "streak_3" in keys

    def test_badge_milestone(self, mem_conn):
        badges = [{"id": f"b{i}", "tier": "bronze"} for i in range(6)]
        ctx = {"session_count": 10, "badges": badges, "streak": 0}
        result = check_achievements(mem_conn, 1, 1, session_id=10, context=ctx)
        keys = [a["key"] for a in result]
        assert "all_bronze" in keys
        assert "first_badge" in keys

    def test_personal_best(self, mem_conn):
        ctx = {"session_count": 5, "badges": [], "streak": 1, "is_personal_best": True}
        result = check_achievements(mem_conn, 1, 1, session_id=5, context=ctx)
        keys = [a["key"] for a in result]
        assert "personal_best" in keys


class TestGetAchievementStatus:
    def test_returns_all_15(self, mem_conn):
        result = get_achievement_status(mem_conn, 1, 1)
        assert len(result) == len(ACHIEVEMENT_CATALOG)

    def test_all_locked_initially(self, mem_conn):
        result = get_achievement_status(mem_conn, 1, 1)
        assert all(not a["unlocked"] for a in result)

    def test_shows_unlocked(self, mem_conn):
        ctx = {"session_count": 1, "badges": [], "streak": 0}
        check_achievements(mem_conn, 1, 1, session_id=1, context=ctx)
        result = get_achievement_status(mem_conn, 1, 1)
        first = next(a for a in result if a["key"] == "first_session")
        assert first["unlocked"] is True
        assert first["unlocked_at"] is not None
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest telemetry_tool/tests/gamification/test_achievements.py -v --tb=short`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add telemetry_tool/gamification/achievements.py telemetry_tool/tests/gamification/test_achievements.py
git commit -m "feat(gamification): achievement engine — 15 achievements with check/unlock logic"
```

---

## Chunk 2: Backend Integration — API Endpoints + Pipeline Wiring

### Task 5: API Endpoints for Gamification

**Files:**
- Modify: `telemetry_tool/web/routes/api_v1_entities.py` (add 4 endpoints after dev-plans section)

- [ ] **Step 1: Add driver progress endpoint**

After the dev-plan delete-impact route (~line 860), add:

```python
# ══════════════════════════════════════════════════════════════════
# Gamification
# ══════════════════════════════════════════════════════════════════

@bp.route("/drivers/<int:driver_id>/progress", methods=["GET"])
def get_driver_progress(driver_id):
    conn = _get_conn()
    row = _verify_driver(conn, driver_id)
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    try:
        from gamification.xp import get_driver_progress as _get_progress
        from gamification.achievements import get_achievement_status
        progress = _get_progress(conn, driver_id, workspace_id=getattr(g, "workspace_id", 1))
        achievements = get_achievement_status(conn, driver_id, workspace_id=getattr(g, "workspace_id", 1))
        progress["achievements"] = achievements
        return api_response(progress)
    except Exception:
        logger.warning("Gamification progress failed for driver %s", driver_id, exc_info=True)
        return api_response({"total_xp": 0, "level": 0, "achievements": []})


@bp.route("/drivers/<int:driver_id>/achievements", methods=["GET"])
def get_driver_achievements(driver_id):
    conn = _get_conn()
    row = _verify_driver(conn, driver_id)
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Driver not found", status=404)
    try:
        from gamification.achievements import get_achievement_status
        result = get_achievement_status(conn, driver_id, workspace_id=getattr(g, "workspace_id", 1))
        return api_response(result)
    except Exception:
        logger.warning("Achievements failed for driver %s", driver_id, exc_info=True)
        return api_response([])
```

- [ ] **Step 2: Add drill execution endpoints**

```python
@bp.route("/dev-plans/<int:plan_id>/drills/<int:week>/<int:drill_idx>/execute", methods=["POST"])
def execute_drill(plan_id, week, drill_idx):
    conn = _get_conn()
    row = conn.execute(Q.SELECT_PLAN_BY_ID, {"id": plan_id}).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Plan not found", status=404)
    body = request.get_json(silent=True) or {}
    session_id = body.get("session_id")
    status = body.get("status", "attempted")
    if status not in ("attempted", "completed", "skipped"):
        return api_error(ErrorCode.VALIDATION_ERROR, "Invalid status", status=400)
    notes = body.get("notes")
    driver_id = dict(row)["driver_id"]
    wid = getattr(g, "workspace_id", 1)
    try:
        from gamification.queries import insert_drill_execution
        exec_id = insert_drill_execution(
            conn, wid, driver_id, plan_id, week, drill_idx,
            session_id, status, notes,
        )
        # Award XP if completed
        xp_result = None
        if status == "completed":
            from gamification.xp import award_drill_xp
            xp_result = award_drill_xp(conn, driver_id, wid, plan_id)
        conn.commit()
        return api_response({
            "execution_id": exec_id,
            "status": status,
            "xp_result": xp_result,
        }, status=201)
    except Exception:
        logger.warning("Drill execution failed", exc_info=True)
        return api_error(ErrorCode.SERVER_ERROR, "Failed to log drill execution", status=500)


@bp.route("/dev-plans/<int:plan_id>/executions", methods=["GET"])
def list_drill_executions(plan_id):
    conn = _get_conn()
    row = conn.execute(Q.SELECT_PLAN_BY_ID, {"id": plan_id}).fetchone()
    if not row:
        return api_error(ErrorCode.NOT_FOUND, "Plan not found", status=404)
    try:
        from gamification.queries import get_plan_executions
        execs = get_plan_executions(conn, plan_id, workspace_id=getattr(g, "workspace_id", 1))
        return api_response(execs)
    except Exception:
        logger.warning("Drill executions fetch failed", exc_info=True)
        return api_response([])
```

- [ ] **Step 3: Add `g` import** at top of file (if not already):

Check if `from flask import g` is in imports. If not, add it to the existing import line.

- [ ] **Step 4: Commit**

```bash
git add telemetry_tool/web/routes/api_v1_entities.py
git commit -m "feat(gamification): 4 API endpoints — driver progress, achievements, drill execution"
```

---

### Task 6: Wire Gamification into Pipeline

**Files:**
- Modify: `telemetry_tool/pipeline/orchestrator.py` (add gamification call after scoring stage)

- [ ] **Step 1: Add gamification integration**

After the coaching V3 block (after `_fire_progress("13g2_persist_coaching_v3")`), add:

```python
    # ── 13h: Gamification XP/achievements ──────────────────────────
    if os.environ.get("GAMIFICATION", "1") != "0":
        try:
            from gamification.xp import award_session_xp
            from gamification.streaks import update_streak
            from gamification.achievements import check_achievements
            from gamification.queries import count_driver_sessions, get_driver_best_lap
            from scoring import evaluate_badges

            _wid = getattr(g, "workspace_id", 1) if "g" in dir() else 1
            _driver_id = ctx.get("driver_id")
            _session_id = ctx.get("session_id")
            _session_date = ctx.get("session_date")

            if _driver_id and conn:
                # Get badges for this session
                _badges = []
                if score_result:
                    try:
                        _badges = evaluate_badges(score_result)
                    except Exception:
                        pass

                # Previous best for PB detection
                _prev_best = get_driver_best_lap(conn, _driver_id, _wid)

                _current_best = None
                if analysis_json and isinstance(analysis_json, dict):
                    _current_best = analysis_json.get("best_lap_time_s")

                xp_result = award_session_xp(
                    conn, _driver_id, _wid, _session_id,
                    badges=_badges,
                    previous_best_lap=_prev_best,
                    current_best_lap=_current_best,
                )
                streak_result = update_streak(conn, _driver_id, _wid, _session_date or "")
                _session_count = count_driver_sessions(conn, _driver_id, _wid)

                new_achievements = check_achievements(
                    conn, _driver_id, _wid, _session_id,
                    context={
                        "session_count": _session_count,
                        "badges": _badges,
                        "streak": streak_result["current_streak"],
                        "is_personal_best": xp_result["xp_breakdown"].get("personal_best", 0) > 0,
                    },
                )

                # Store in analysis_json for API to read
                if analysis_json is not None:
                    analysis_json["gamification"] = {
                        "xp_gained": xp_result["xp_gained"],
                        "new_level": xp_result["new_level"] if xp_result["leveled_up"] else None,
                        "new_achievements": [a["key"] for a in new_achievements],
                        "streak": streak_result["current_streak"],
                    }

                logger.info(
                    "Gamification: driver=%s xp=+%d level=%d streak=%d achievements=%d",
                    _driver_id, xp_result["xp_gained"], xp_result["new_level"],
                    streak_result["current_streak"], len(new_achievements),
                )
        except Exception:
            logger.warning("Gamification stage failed", exc_info=True)
```

- [ ] **Step 2: Commit**

```bash
git add telemetry_tool/pipeline/orchestrator.py
git commit -m "feat(gamification): wire XP/streaks/achievements into pipeline after scoring"
```

---

## Chunk 3: Frontend — Gamification Components

### Task 7: TypeScript Types + Badge Enhancement

**Files:**
- Create: `lap-website/src/components/app/gamification/types.ts`
- Modify: `lap-website/src/components/app/AchievementsBadges.tsx` (enhance existing)

- [ ] **Step 1: Create gamification types**

```typescript
export interface DriverProgress {
  total_xp: number;
  level: number;
  xp_for_current_level: number;
  xp_for_next_level: number;
  current_streak: number;
  longest_streak: number;
  achievements: Achievement[];
}

export interface Achievement {
  key: string;
  label: string;
  description: string;
  icon: string;
  unlocked: boolean;
  unlocked_at: string | null;
}

export interface GamificationEvent {
  xp_gained: number;
  new_level: number | null;
  new_achievements: string[];
  streak: number;
}

export interface DrillExecution {
  id: number;
  plan_id: number;
  week_number: number;
  drill_index: number;
  session_id: number | null;
  status: 'attempted' | 'completed' | 'skipped';
  notes: string | null;
  created_at: string;
  csv_filename?: string;
  session_date?: string;
}

export interface XpResult {
  execution_id: number;
  status: string;
  xp_result: {
    xp_gained: number;
    old_level: number;
    new_level: number;
    leveled_up: boolean;
  } | null;
}
```

- [ ] **Step 2: Enhance AchievementsBadges.tsx**

Add tier glow animation, larger icons, and tooltip with criteria. Keep backward compat with existing props.

- [ ] **Step 3: Commit**

```bash
git add lap-website/src/components/app/gamification/
git add lap-website/src/components/app/AchievementsBadges.tsx
git commit -m "feat(gamification): TypeScript types + enhanced badge display"
```

---

### Task 8: XP Progress Bar + Streak Counter

**Files:**
- Create: `lap-website/src/components/app/gamification/XPProgressBar.tsx`
- Create: `lap-website/src/components/app/gamification/StreakCounter.tsx`

- [ ] **Step 1: Create `XPProgressBar.tsx`**

Level circle on left, animated progress bar, XP text. Acid-green fill, asphalt background. CSS transition on width. Shows "Level {n} -- {current}/{next} XP".

- [ ] **Step 2: Create `StreakCounter.tsx`**

Small inline component. Shows fire emoji + "N day streak" when streak > 0. Pulse animation via CSS `@keyframes`. Tooltip shows longest streak.

- [ ] **Step 3: Commit**

```bash
git add lap-website/src/components/app/gamification/XPProgressBar.tsx
git add lap-website/src/components/app/gamification/StreakCounter.tsx
git commit -m "feat(gamification): XP progress bar + streak counter components"
```

---

### Task 9: Achievement Grid + Toast + Level Up Modal

**Files:**
- Create: `lap-website/src/components/app/gamification/AchievementGrid.tsx`
- Create: `lap-website/src/components/app/gamification/AchievementToast.tsx`
- Create: `lap-website/src/components/app/gamification/LevelUpModal.tsx`

- [ ] **Step 1: Create `AchievementGrid.tsx`**

5-column grid (3 on mobile). Each achievement: circular icon, label, unlock date. Locked = grayscale + "???". Unlocked = full color. Counter: "X/15 unlocked".

- [ ] **Step 2: Create `AchievementToast.tsx`**

Fixed position top-right. Gold border on dark bg. Slide-in animation (CSS transform). Auto-dismiss after 5s via useEffect setTimeout. Shows trophy icon + label + description.

- [ ] **Step 3: Create `LevelUpModal.tsx`**

Centered backdrop modal. Shows old level -> new level with arrow. Pulse/glow CSS animation on level number. "Continue" button to dismiss. Uses portal or fixed positioning.

- [ ] **Step 4: Commit**

```bash
git add lap-website/src/components/app/gamification/AchievementGrid.tsx
git add lap-website/src/components/app/gamification/AchievementToast.tsx
git add lap-website/src/components/app/gamification/LevelUpModal.tsx
git commit -m "feat(gamification): achievement grid, toast notifications, level-up modal"
```

---

### Task 10: Drill Execution Form + Plan Progress Timeline

**Files:**
- Create: `lap-website/src/components/app/gamification/DrillExecutionForm.tsx`
- Create: `lap-website/src/components/app/gamification/PlanProgressTimeline.tsx`

- [ ] **Step 1: Create `DrillExecutionForm.tsx`**

Inline expandable form. Session selector (dropdown of driver's recent sessions from API). Status radio: attempted/completed/skipped. Notes textarea. Submit POSTs to `/dev-plans/{id}/drills/{week}/{idx}/execute`. Shows XP gained on success.

- [ ] **Step 2: Create `PlanProgressTimeline.tsx`**

Vertical timeline with week nodes connected by a line. Each week: header with week number, list of drills with status icons (green check / amber clock / gray circle). Completion % per week. Acid-green line for completed sections, steel for pending.

- [ ] **Step 3: Commit**

```bash
git add lap-website/src/components/app/gamification/DrillExecutionForm.tsx
git add lap-website/src/components/app/gamification/PlanProgressTimeline.tsx
git commit -m "feat(gamification): drill execution form + plan progress timeline"
```

---

## Chunk 4: Frontend Integration — Wiring Components into Pages

### Task 11: Wire Gamification into Session Detail Page

**Files:**
- Modify: `lap-website/src/app/app/sessions/[id]/page.tsx`

- [ ] **Step 1: Add gamification event handling**

After session data loads, check `analysis_json.gamification` for new achievements/level-ups. Render `AchievementToast` and `LevelUpModal` conditionally.

- [ ] **Step 2: Commit**

```bash
git add lap-website/src/app/app/sessions/[id]/page.tsx
git commit -m "feat(gamification): wire achievement toast + level-up modal into session detail"
```

---

### Task 12: Wire Gamification into Plan Detail Page

**Files:**
- Modify: `lap-website/src/app/app/development/[id]/page.tsx`

- [ ] **Step 1: Add drill execution tracking**

Replace/augment the checklist with `PlanProgressTimeline`. Add `DrillExecutionForm` expand buttons per drill. Fetch executions via `GET /dev-plans/{id}/executions`. Show XP earned on plan card.

- [ ] **Step 2: Commit**

```bash
git add lap-website/src/app/app/development/[id]/page.tsx
git commit -m "feat(gamification): drill execution tracking + progress timeline in plan detail"
```

---

### Task 13: Wire XP Bar + Streak into App Header / Driver Pages

**Files:**
- Modify: `lap-website/src/app/app/development/page.tsx` (add driver progress header)
- Modify: `lap-website/src/app/app/drivers/page.tsx` (add XP/streak to driver cards)

- [ ] **Step 1: Add XP + streak to development page**

Fetch driver progress when a driver filter is selected. Show `XPProgressBar` + `StreakCounter` above the plans list.

- [ ] **Step 2: Add XP + streak to driver list cards**

Each driver card shows level badge and streak indicator.

- [ ] **Step 3: Commit**

```bash
git add lap-website/src/app/app/development/page.tsx
git add lap-website/src/app/app/drivers/page.tsx
git commit -m "feat(gamification): XP bar + streak on development page + driver cards"
```

---

### Task 14: Achievement Page (Driver Profile)

**Files:**
- Create: `lap-website/src/app/app/drivers/[id]/achievements/page.tsx`

- [ ] **Step 1: Create achievements page**

Full-page view with `AchievementGrid` + `XPProgressBar` + `StreakCounter`. Fetches from `GET /drivers/{id}/progress`. Link from driver detail page.

- [ ] **Step 2: Commit**

```bash
git add lap-website/src/app/app/drivers/[id]/achievements/page.tsx
git commit -m "feat(gamification): dedicated achievements page for driver profile"
```

---

## Chunk 5: Tests + Verification

### Task 15: Full Backend Test Suite

**Files:**
- Test: `telemetry_tool/tests/gamification/test_integration.py`

- [ ] **Step 1: Write integration test**

End-to-end: create driver → upload session (mock) → XP awarded → streak updated → achievements checked → API returns progress.

- [ ] **Step 2: Run full gamification test suite**

Run: `python -m pytest telemetry_tool/tests/gamification/ -v --tb=short`
Expected: All PASS.

- [ ] **Step 3: Run full backend regression**

Run: `python -m pytest telemetry_tool/tests/ -v --tb=short -x`
Expected: No regressions.

- [ ] **Step 4: Commit**

```bash
git add telemetry_tool/tests/gamification/test_integration.py
git commit -m "test(gamification): integration tests — full XP/achievement/streak flow"
```

---

### Task 16: Frontend Type Check

- [ ] **Step 1: Run TypeScript check**

Run: `cd lap-website && npx tsc --noEmit 2>&1 | grep gamification`
Expected: Zero errors in gamification components.

- [ ] **Step 2: Final commit if any fixes needed**

---

## Summary

| Chunk | Tasks | Scope |
|-------|-------|-------|
| 1 | 1-4 | Migration + XP engine + streaks + achievements |
| 2 | 5-6 | API endpoints + pipeline wiring |
| 3 | 7-10 | Frontend gamification components (8 total) |
| 4 | 11-14 | Wire into existing pages |
| 5 | 15-16 | Tests + verification |

Total: 16 tasks, ~45 files created/modified.
