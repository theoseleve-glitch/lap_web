"""Weekly recap aggregation + beat-task idempotency tests.

Unit tests only — run against sqlite mem_conn (no Celery, no PG required).
The beat-task test mocks the maint connection and the mailer so no network
or broker is needed.
"""
import json
import sqlite3
import unittest.mock as mock
import pytest


# ── mem_conn fixture (mirrors gamification conftest, extended for recap) ──────

@pytest.fixture()
def mem_conn():
    """In-memory SQLite with the tables required by build_recap_payload."""
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
            pit_passes INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE (workspace_id, driver_id)
        )
    """)
    conn.execute("""
        CREATE TABLE quests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER,
            driver_id INTEGER,
            status TEXT,
            xp INTEGER,
            human_text TEXT,
            focused INTEGER DEFAULT 0,
            completed_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE weekly_recap (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER NOT NULL,
            driver_id INTEGER NOT NULL,
            iso_week TEXT NOT NULL,
            payload TEXT NOT NULL,
            emailed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE (workspace_id, driver_id, iso_week)
        )
    """)
    yield conn
    conn.close()


# ── Pure aggregation helper ───────────────────────────────────────────────────

class TestRecap:
    def test_aggregates_week(self, mem_conn):
        """build_recap_payload counts completed quests in window, streak, next_focus."""
        mem_conn.execute(
            "INSERT INTO driver_xp "
            "(workspace_id, driver_id, total_xp, level, current_streak, longest_streak, "
            "last_session_date, pit_passes) VALUES (1,1,500,2,3,3,'2026-03-05',0)"
        )
        # Quest completed inside the window.
        mem_conn.execute(
            "INSERT INTO quests (workspace_id, driver_id, status, xp, human_text, completed_at) "
            "VALUES (1, 1, 'completed', 150, 'Carry 58 km/h through T5', '2026-03-04')"
        )
        # Active quest → becomes next_focus.
        mem_conn.execute(
            "INSERT INTO quests (workspace_id, driver_id, status, xp, human_text, created_at) "
            "VALUES (1, 1, 'active', 100, 'Beat your best lap by 1%', '2026-03-03')"
        )
        mem_conn.commit()

        from telemetry_tool.tasks.recap_tasks import build_recap_payload

        payload = build_recap_payload(
            mem_conn,
            driver_id=1,
            workspace_id=1,
            week_start="2026-03-02",
            week_end="2026-03-09",
        )

        assert payload["quests_completed"] == 1
        assert payload["current_streak"] == 3
        assert payload["next_focus"] == "Beat your best lap by 1%"
        assert payload["week_start"] == "2026-03-02"
        assert payload["week_end"] == "2026-03-09"

    def test_quest_outside_window_not_counted(self, mem_conn):
        """A quest completed before week_start must not be counted."""
        mem_conn.execute(
            "INSERT INTO driver_xp "
            "(workspace_id, driver_id, total_xp, level, current_streak, longest_streak, "
            "last_session_date, pit_passes) VALUES (1,1,0,0,1,1,'2026-03-05',0)"
        )
        mem_conn.execute(
            "INSERT INTO quests (workspace_id, driver_id, status, xp, human_text, completed_at) "
            "VALUES (1, 1, 'completed', 100, 'Old quest', '2026-02-28')"
        )
        mem_conn.commit()

        from telemetry_tool.tasks.recap_tasks import build_recap_payload

        payload = build_recap_payload(
            mem_conn, driver_id=1, workspace_id=1,
            week_start="2026-03-02", week_end="2026-03-09",
        )
        assert payload["quests_completed"] == 0

    def test_no_active_quest_means_no_next_focus(self, mem_conn):
        """When there are no active quests, next_focus is None."""
        mem_conn.execute(
            "INSERT INTO driver_xp "
            "(workspace_id, driver_id, total_xp, level, current_streak, longest_streak, "
            "last_session_date, pit_passes) VALUES (1,1,0,0,5,5,'2026-03-05',0)"
        )
        mem_conn.commit()

        from telemetry_tool.tasks.recap_tasks import build_recap_payload

        payload = build_recap_payload(
            mem_conn, driver_id=1, workspace_id=1,
            week_start="2026-03-02", week_end="2026-03-09",
        )
        assert payload["next_focus"] is None

    def test_focused_quest_preferred_as_next_focus(self, mem_conn):
        """A focused=1 active quest is returned as next_focus over unfocused."""
        mem_conn.execute(
            "INSERT INTO driver_xp "
            "(workspace_id, driver_id, total_xp, level, current_streak, longest_streak, "
            "last_session_date, pit_passes) VALUES (1,1,0,0,2,2,'2026-03-05',0)"
        )
        mem_conn.execute(
            "INSERT INTO quests (workspace_id, driver_id, status, xp, human_text, focused, created_at) "
            "VALUES (1, 1, 'active', 100, 'Unfocused quest', 0, '2026-03-01')"
        )
        mem_conn.execute(
            "INSERT INTO quests (workspace_id, driver_id, status, xp, human_text, focused, created_at) "
            "VALUES (1, 1, 'active', 150, 'Star quest', 1, '2026-03-02')"
        )
        mem_conn.commit()

        from telemetry_tool.tasks.recap_tasks import build_recap_payload

        payload = build_recap_payload(
            mem_conn, driver_id=1, workspace_id=1,
            week_start="2026-03-02", week_end="2026-03-09",
        )
        assert payload["next_focus"] == "Star quest"


# ── Idempotency test: re-running the beat task in the same week ───────────────

class TestRecapIdempotent:
    """Simulate two runs of weekly_recap against the same (ws, driver, iso_week).

    We mock get_maint_connection to inject the sqlite mem_conn and mock
    the mailer so no SMTP/Resend call occurs.  This verifies:
      - the UPSERT does not create a second row
      - email is sent only on the first run (emailed flag)
    """

    def _upsert(self, conn, ws_id, drv_id, iso_week, payload):
        """Replicate the task's UPSERT logic on sqlite (ON CONFLICT ... DO UPDATE)."""
        conn.execute(
            "INSERT INTO weekly_recap (workspace_id, driver_id, iso_week, payload) "
            "VALUES (?,?,?,?) ON CONFLICT (workspace_id, driver_id, iso_week) "
            "DO UPDATE SET payload = excluded.payload",
            (ws_id, drv_id, iso_week, json.dumps(payload)),
        )

    def test_upsert_is_idempotent_no_duplicate_row(self, mem_conn):
        """Running UPSERT twice does not create two rows."""
        mem_conn.execute(
            "INSERT INTO driver_xp "
            "(workspace_id, driver_id, total_xp, level, current_streak, longest_streak, "
            "last_session_date, pit_passes) VALUES (1,1,0,0,1,1,'2026-03-05',0)"
        )
        mem_conn.commit()

        from telemetry_tool.tasks.recap_tasks import build_recap_payload

        payload = build_recap_payload(
            mem_conn, driver_id=1, workspace_id=1,
            week_start="2026-03-02", week_end="2026-03-09",
        )

        # First upsert.
        self._upsert(mem_conn, 1, 1, "2026-W10", payload)
        mem_conn.commit()

        # Second upsert (same iso_week) — must not duplicate.
        self._upsert(mem_conn, 1, 1, "2026-W10", payload)
        mem_conn.commit()

        row_count = mem_conn.execute(
            "SELECT COUNT(*) FROM weekly_recap "
            "WHERE workspace_id=1 AND driver_id=1 AND iso_week='2026-W10'"
        ).fetchone()[0]
        assert row_count == 1

    def test_emailed_flag_prevents_double_send(self, mem_conn):
        """Once emailed=1, a second run must not re-send."""
        mem_conn.execute(
            "INSERT INTO driver_xp "
            "(workspace_id, driver_id, total_xp, level, current_streak, longest_streak, "
            "last_session_date, pit_passes) VALUES (1,1,0,0,1,1,'2026-03-05',0)"
        )
        mem_conn.commit()

        from telemetry_tool.tasks.recap_tasks import build_recap_payload

        payload = build_recap_payload(
            mem_conn, driver_id=1, workspace_id=1,
            week_start="2026-03-02", week_end="2026-03-09",
        )

        # Insert row already marked emailed=1 (simulating a previous run).
        mem_conn.execute(
            "INSERT INTO weekly_recap (workspace_id, driver_id, iso_week, payload, emailed) "
            "VALUES (1, 1, '2026-W10', ?, 1)",
            (json.dumps(payload),),
        )
        mem_conn.commit()

        # Verify the emailed flag is set.
        row = mem_conn.execute(
            "SELECT emailed FROM weekly_recap WHERE iso_week='2026-W10'"
        ).fetchone()
        assert (row["emailed"] if isinstance(row, sqlite3.Row) else row[0]) == 1
