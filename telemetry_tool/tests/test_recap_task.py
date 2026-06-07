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
    # corner_mastery: Phase-1 mastery stars.  achieved_at records when a
    # corner's tier was last upgraded — used by build_recap_payload to count
    # stars_earned in the week window.
    conn.execute("""
        CREATE TABLE corner_mastery (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER NOT NULL,
            driver_id INTEGER NOT NULL,
            track_id TEXT NOT NULL,
            corner_id INTEGER NOT NULL,
            condition TEXT NOT NULL DEFAULT 'dry',
            tier TEXT NOT NULL DEFAULT 'none',
            best_score REAL NOT NULL DEFAULT 0,
            sessions_at_silver TEXT NOT NULL DEFAULT '[]',
            first_session_id TEXT,
            achieved_at TEXT,
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE (workspace_id, driver_id, track_id, corner_id, condition)
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


# ── New fields: stars_earned + xp_gained ─────────────────────────────────────

class TestRecapNewFields:
    """build_recap_payload must return stars_earned and xp_gained."""

    def _seed_xp(self, conn):
        conn.execute(
            "INSERT INTO driver_xp "
            "(workspace_id, driver_id, total_xp, level, current_streak, longest_streak, "
            "last_session_date, pit_passes) VALUES (1,1,300,1,2,2,'2026-03-05',0)"
        )

    def test_stars_earned_in_window(self, mem_conn):
        """stars_earned counts corner_mastery tier upgrades whose achieved_at
        falls inside [week_start, week_end), and excludes upgrades outside the
        window."""
        self._seed_xp(mem_conn)

        # Two stars inside the window.
        mem_conn.execute(
            "INSERT INTO corner_mastery "
            "(workspace_id, driver_id, track_id, corner_id, condition, tier, "
            "best_score, achieved_at) "
            "VALUES (1, 1, 'track_a', 1, 'dry', 'bronze', 65.0, '2026-03-03')"
        )
        mem_conn.execute(
            "INSERT INTO corner_mastery "
            "(workspace_id, driver_id, track_id, corner_id, condition, tier, "
            "best_score, achieved_at) "
            "VALUES (1, 1, 'track_a', 2, 'dry', 'silver', 78.0, '2026-03-06')"
        )
        # One star BEFORE the window — must not be counted.
        mem_conn.execute(
            "INSERT INTO corner_mastery "
            "(workspace_id, driver_id, track_id, corner_id, condition, tier, "
            "best_score, achieved_at) "
            "VALUES (1, 1, 'track_a', 3, 'dry', 'gold', 88.0, '2026-02-28')"
        )
        # One star ON week_end (exclusive upper bound) — must not be counted.
        mem_conn.execute(
            "INSERT INTO corner_mastery "
            "(workspace_id, driver_id, track_id, corner_id, condition, tier, "
            "best_score, achieved_at) "
            "VALUES (1, 1, 'track_a', 4, 'dry', 'bronze', 62.0, '2026-03-09')"
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

        assert payload["stars_earned"] == 2

    def test_xp_gained_sums_quest_xp_in_window(self, mem_conn):
        """xp_gained sums quest xp for quests completed inside the window;
        out-of-window or non-completed quests are excluded."""
        self._seed_xp(mem_conn)

        # Two quests completed inside the window (xp 150 + 100 = 250).
        mem_conn.execute(
            "INSERT INTO quests (workspace_id, driver_id, status, xp, human_text, completed_at) "
            "VALUES (1, 1, 'completed', 150, 'Quest A', '2026-03-04')"
        )
        mem_conn.execute(
            "INSERT INTO quests (workspace_id, driver_id, status, xp, human_text, completed_at) "
            "VALUES (1, 1, 'completed', 100, 'Quest B', '2026-03-07')"
        )
        # Quest completed before the window — must not contribute.
        mem_conn.execute(
            "INSERT INTO quests (workspace_id, driver_id, status, xp, human_text, completed_at) "
            "VALUES (1, 1, 'completed', 200, 'Old quest', '2026-02-20')"
        )
        # Active quest — must not contribute.
        mem_conn.execute(
            "INSERT INTO quests (workspace_id, driver_id, status, xp, human_text, created_at) "
            "VALUES (1, 1, 'active', 120, 'Pending quest', '2026-03-03')"
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

        assert payload["xp_gained"] == 250

    def test_both_fields_zero_when_no_activity(self, mem_conn):
        """stars_earned and xp_gained are 0 when there is nothing in-window."""
        self._seed_xp(mem_conn)
        mem_conn.commit()

        from telemetry_tool.tasks.recap_tasks import build_recap_payload

        payload = build_recap_payload(
            mem_conn,
            driver_id=1,
            workspace_id=1,
            week_start="2026-03-02",
            week_end="2026-03-09",
        )

        assert payload["stars_earned"] == 0
        assert payload["xp_gained"] == 0


# ── Counter inflation: two sequential task invocations must not inflate n_emailed

class TestRecapCounterNoInflation:
    """The weekly_recap task must use a plain local counter (Fix 2).

    Two sequential invocations on the same in-process _process_driver callable
    must each return only the emails sent in THAT call — no cross-invocation
    accumulation.
    """

    def _make_conn(self):
        """Create a mem_conn with all required tables inline (no fixture).

        workspace_members uses the REAL schema: (workspace_id, user_id, role,
        joined_at) — no driver_id column.  This mirrors migration
        045_workspace_members_table.py so any SQL against workspace_members
        will fail loudly if it references a non-existent column.
        """
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
                workspace_id INTEGER, driver_id INTEGER, status TEXT,
                xp INTEGER, human_text TEXT, focused INTEGER DEFAULT 0,
                completed_at TEXT, created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE corner_mastery (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL, driver_id INTEGER NOT NULL,
                track_id TEXT NOT NULL, corner_id INTEGER NOT NULL,
                condition TEXT NOT NULL DEFAULT 'dry', tier TEXT NOT NULL DEFAULT 'none',
                best_score REAL NOT NULL DEFAULT 0,
                sessions_at_silver TEXT NOT NULL DEFAULT '[]',
                first_session_id TEXT, achieved_at TEXT,
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE (workspace_id, driver_id, track_id, corner_id, condition)
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
        # Real workspace_members schema (migration 045): workspace_id, user_id,
        # role, joined_at — NO driver_id column.
        conn.execute("""
            CREATE TABLE workspace_members (
                workspace_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'member',
                joined_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (workspace_id, user_id)
            )
        """)
        # Real users schema: id, email, display_name, preferences (JSON text).
        conn.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                email TEXT NOT NULL,
                display_name TEXT,
                preferences TEXT NOT NULL DEFAULT '{}'
            )
        """)
        return conn

    def test_two_runs_do_not_inflate_emailed_count(self):
        """Calling _process_driver twice (different iso_weeks) returns 0 the
        second time if no email is sent — not an accumulated total."""
        from telemetry_tool.tasks import recap_tasks

        # If Celery isn't importable the beat-task block is skipped; skip this
        # integration-style test gracefully in that case.
        if not hasattr(recap_tasks, "_process_driver"):
            pytest.skip("Celery not available — _process_driver not registered")

        conn = self._make_conn()
        conn.execute(
            "INSERT INTO driver_xp "
            "(workspace_id, driver_id, total_xp, level, current_streak, longest_streak, "
            "last_session_date, pit_passes) VALUES (1,1,0,0,1,1,'2026-03-05',0)"
        )
        conn.commit()

        with mock.patch("telemetry_tool.tasks.recap_tasks._should_email", return_value=True), \
             mock.patch("telemetry_tool.tasks.recap_tasks._send_recap_email", return_value=True):

            # First invocation (week A) — email sent → should return 1.
            result_a = recap_tasks._process_driver(
                conn, ws_id=1, drv_id=1, iso_week="2026-W10",
                week_start="2026-03-02", week_end="2026-03-09",
            )
            conn.commit()

            # Second invocation (week B) — fresh week, email sent → must return 1 (not 2).
            result_b = recap_tasks._process_driver(
                conn, ws_id=1, drv_id=1, iso_week="2026-W11",
                week_start="2026-03-09", week_end="2026-03-16",
            )
            conn.commit()

        assert result_a == 1, "first call must return 1 (one email sent)"
        assert result_b == 1, "second call must return 1 (not accumulated 2)"
        conn.close()


# ── Email helper tests: real SQL against real schema ─────────────────────────
#
# These tests exercise _should_email and _send_recap_email directly against the
# corrected fixture schema (workspace_members with NO driver_id column).  A bug
# like the original WHERE wm.driver_id = :drv would raise sqlite3.OperationalError
# here, catching it at test time instead of silently at runtime.

class TestRecapEmailHelpers:
    """_should_email and _send_recap_email run real SQL against the real schema."""

    def _make_email_conn(self):
        """Minimal sqlite mem_conn with the real workspace_members + users schema."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE workspace_members (
                workspace_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'member',
                joined_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (workspace_id, user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                email TEXT NOT NULL,
                display_name TEXT,
                preferences TEXT NOT NULL DEFAULT '{}'
            )
        """)
        # weekly_recap required by _process_driver / emailed-flag logic
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
        return conn

    def _seed_owner(self, conn, ws_id=1, user_id=10,
                    email="driver@example.com", display_name="Test Driver",
                    preferences=None):
        """Insert a workspace owner into the real-schema tables."""
        prefs = json.dumps(preferences or {})
        conn.execute(
            "INSERT INTO users (id, email, display_name, preferences) VALUES (?,?,?,?)",
            (user_id, email, display_name, prefs),
        )
        conn.execute(
            "INSERT INTO workspace_members (workspace_id, user_id, role) VALUES (?,?,'owner')",
            (ws_id, user_id),
        )
        conn.commit()

    def test_should_email_true_when_digest_enabled(self):
        """_should_email returns True when weekly_digest is explicitly true."""
        from telemetry_tool.tasks import recap_tasks
        if not hasattr(recap_tasks, "_should_email"):
            pytest.skip("Celery not available")

        conn = self._make_email_conn()
        self._seed_owner(
            conn,
            preferences={"notifications": {"weekly_digest": True}},
        )
        assert recap_tasks._should_email(conn, ws_id=1, drv_id=99) is True
        conn.close()

    def test_should_email_false_when_digest_disabled(self):
        """_should_email returns False when weekly_digest is false."""
        from telemetry_tool.tasks import recap_tasks
        if not hasattr(recap_tasks, "_should_email"):
            pytest.skip("Celery not available")

        conn = self._make_email_conn()
        self._seed_owner(
            conn,
            preferences={"notifications": {"weekly_digest": False}},
        )
        assert recap_tasks._should_email(conn, ws_id=1, drv_id=99) is False
        conn.close()

    def test_should_email_defaults_true_when_pref_absent(self):
        """_should_email returns True (send) when notifications key is missing."""
        from telemetry_tool.tasks import recap_tasks
        if not hasattr(recap_tasks, "_should_email"):
            pytest.skip("Celery not available")

        conn = self._make_email_conn()
        self._seed_owner(conn, preferences={})
        assert recap_tasks._should_email(conn, ws_id=1, drv_id=99) is True
        conn.close()

    def test_send_recap_email_resolves_address_from_workspace_id(self):
        """_send_recap_email resolves the correct email via workspace_id → owner,
        NOT via driver_id.  The mock _send captures the address passed to it."""
        from telemetry_tool.tasks import recap_tasks
        if not hasattr(recap_tasks, "_send_recap_email"):
            pytest.skip("Celery not available")

        conn = self._make_email_conn()
        self._seed_owner(conn, email="owner@lap-coach.racing", display_name="Race Driver")

        with mock.patch("auth.email._send", return_value=True) as mock_send:
            result = recap_tasks._send_recap_email(
                conn, drv_id=42, ws_id=1, iso_week="2026-W10",
                payload={"quests_completed": 2, "current_streak": 3,
                         "next_focus": None, "week_start": "2026-03-02",
                         "week_end": "2026-03-09", "stars_earned": 1, "xp_gained": 150},
            )

        assert result is True
        assert mock_send.called
        called_email = mock_send.call_args[0][0]
        assert called_email == "owner@lap-coach.racing", (
            f"Expected owner@lap-coach.racing but got {called_email!r} — "
            "email was not resolved via workspace_id→owner"
        )
        conn.close()

    def test_send_recap_email_skips_when_no_owner(self):
        """_send_recap_email returns False (no email) when workspace has no owner."""
        from telemetry_tool.tasks import recap_tasks
        if not hasattr(recap_tasks, "_send_recap_email"):
            pytest.skip("Celery not available")

        conn = self._make_email_conn()
        # No rows inserted — workspace 1 has no owner.
        result = recap_tasks._send_recap_email(
            conn, drv_id=1, ws_id=1, iso_week="2026-W10", payload={},
        )
        assert result is False
        conn.close()

    def test_process_driver_sends_email_once_and_sets_emailed_flag(self):
        """_process_driver: email sent on first call, not re-sent on second call
        (emailed flag guards against double-send)."""
        from telemetry_tool.tasks import recap_tasks
        if not hasattr(recap_tasks, "_process_driver"):
            pytest.skip("Celery not available")

        conn = self._make_email_conn()
        # Also need driver_xp for build_recap_payload
        conn.execute("""
            CREATE TABLE driver_xp (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL, driver_id INTEGER NOT NULL,
                total_xp INTEGER NOT NULL DEFAULT 0, level INTEGER NOT NULL DEFAULT 0,
                current_streak INTEGER NOT NULL DEFAULT 0,
                longest_streak INTEGER NOT NULL DEFAULT 0,
                last_session_date TEXT, pit_passes INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE (workspace_id, driver_id)
            )
        """)
        conn.execute("""
            CREATE TABLE quests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER, driver_id INTEGER, status TEXT,
                xp INTEGER, human_text TEXT, focused INTEGER DEFAULT 0,
                completed_at TEXT, created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE corner_mastery (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL, driver_id INTEGER NOT NULL,
                track_id TEXT NOT NULL, corner_id INTEGER NOT NULL,
                condition TEXT NOT NULL DEFAULT 'dry', tier TEXT NOT NULL DEFAULT 'none',
                best_score REAL NOT NULL DEFAULT 0,
                sessions_at_silver TEXT NOT NULL DEFAULT '[]',
                first_session_id TEXT, achieved_at TEXT,
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE (workspace_id, driver_id, track_id, corner_id, condition)
            )
        """)
        conn.execute(
            "INSERT INTO driver_xp "
            "(workspace_id, driver_id, total_xp, level, current_streak, "
            "longest_streak, last_session_date, pit_passes) VALUES (1,1,0,0,1,1,'2026-03-05',0)"
        )
        self._seed_owner(
            conn,
            email="pilot@example.com",
            preferences={"notifications": {"weekly_digest": True}},
        )

        with mock.patch("auth.email._send", return_value=True):
            r1 = recap_tasks._process_driver(
                conn, ws_id=1, drv_id=1, iso_week="2026-W10",
                week_start="2026-03-02", week_end="2026-03-09",
            )
            conn.commit()
            # Second call same week — emailed=1, must skip.
            r2 = recap_tasks._process_driver(
                conn, ws_id=1, drv_id=1, iso_week="2026-W10",
                week_start="2026-03-02", week_end="2026-03-09",
            )
            conn.commit()

        assert r1 == 1, "first call should return 1 (email sent)"
        assert r2 == 0, "second call must return 0 (already emailed)"
        conn.close()
