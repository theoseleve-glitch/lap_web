"""Comeback detection — weeks since the driver's previous session."""
from telemetry_tool.gamification.quests import weeks_since_last_session


class TestComeback:
    def test_counts_weeks_excluding_this_session(self, mem_conn):
        # mem_conn already has a sessions table (7 columns); use named params
        mem_conn.execute(
            "INSERT INTO sessions (session_id, driver_id, workspace_id, session_date) "
            "VALUES ('s0', 1, 1, '2026-03-01')")
        mem_conn.execute(
            "INSERT INTO sessions (session_id, driver_id, workspace_id, session_date) "
            "VALUES ('s1', 1, 1, '2026-03-25')")
        wk = weeks_since_last_session(mem_conn, 1, 1, "s1", "2026-03-25")
        assert wk == 3   # ~24 days → 3 whole weeks

    def test_first_session_returns_zero(self, mem_conn):
        mem_conn.execute(
            "INSERT INTO sessions (session_id, driver_id, workspace_id, session_date) "
            "VALUES ('s1', 1, 1, '2026-03-25')")
        assert weeks_since_last_session(mem_conn, 1, 1, "s1", "2026-03-25") == 0
