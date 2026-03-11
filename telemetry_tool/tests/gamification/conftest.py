"""Fixtures for gamification tests — in-memory SQLite with gamification schema."""
import sqlite3
import pytest


@pytest.fixture
def mem_conn():
    """In-memory SQLite with gamification + minimal session/plan tables."""
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
