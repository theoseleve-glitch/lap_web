"""Pit Pass: earn at 4-week milestones, spend on a single missed week."""
from telemetry_tool.gamification.streaks import update_streak
from telemetry_tool.gamification import queries as Q


def _seed(conn, streak, last_date, passes=0):
    conn.execute(
        "INSERT INTO driver_xp (workspace_id, driver_id, total_xp, level, current_streak, longest_streak, last_session_date, pit_passes) "
        "VALUES (1,1,0,0,:s,:s,:d,:p)", {"s": streak, "d": last_date, "p": passes})


class TestPitPass:
    def test_earned_at_fourth_week(self, mem_conn):
        _seed(mem_conn, streak=3, last_date="2026-03-02")   # next week makes streak 4
        update_streak(mem_conn, 1, 1, "2026-03-09")
        row = Q.get_driver_xp(mem_conn, 1, 1)
        assert row["pit_passes"] == 1

    def test_capped(self, mem_conn):
        _seed(mem_conn, streak=11, last_date="2026-03-02", passes=3)  # week 12 milestone
        update_streak(mem_conn, 1, 1, "2026-03-09")
        row = Q.get_driver_xp(mem_conn, 1, 1)
        assert row["pit_passes"] == 3   # cap

    def test_spent_on_single_missed_week(self, mem_conn):
        _seed(mem_conn, streak=5, last_date="2026-03-02", passes=1)   # gap of 2 weeks (one missed)
        res = update_streak(mem_conn, 1, 1, "2026-03-16")
        row = Q.get_driver_xp(mem_conn, 1, 1)
        assert res.get("pit_pass_used") is True
        assert row["current_streak"] == 6   # preserved + extended, not reset
        assert row["pit_passes"] == 0

    def test_two_missed_weeks_resets_even_with_pass(self, mem_conn):
        _seed(mem_conn, streak=5, last_date="2026-03-02", passes=1)   # gap of 3 weeks
        res = update_streak(mem_conn, 1, 1, "2026-03-23")
        row = Q.get_driver_xp(mem_conn, 1, 1)
        assert res.get("pit_pass_used") is not True
        assert row["current_streak"] == 1
        assert row["pit_passes"] == 1   # not spent
