"""Tests for streak tracking — consecutive session day detection."""
from telemetry_tool.gamification.streaks import update_streak
from telemetry_tool.gamification.xp import XP_STREAK_PER_DAY


class TestStreaks:
    def test_first_session_starts_streak(self, mem_conn):
        result = update_streak(mem_conn, 1, 1, "2026-03-01")
        assert result["current_streak"] == 1
        assert result["longest_streak"] == 1
        assert result["streak_xp"] == XP_STREAK_PER_DAY

    def test_consecutive_day_extends(self, mem_conn):
        update_streak(mem_conn, 1, 1, "2026-03-01")
        result = update_streak(mem_conn, 1, 1, "2026-03-02")
        assert result["current_streak"] == 2
        assert result["longest_streak"] == 2

    def test_three_day_streak(self, mem_conn):
        update_streak(mem_conn, 1, 1, "2026-03-01")
        update_streak(mem_conn, 1, 1, "2026-03-02")
        result = update_streak(mem_conn, 1, 1, "2026-03-03")
        assert result["current_streak"] == 3

    def test_same_day_no_change(self, mem_conn):
        update_streak(mem_conn, 1, 1, "2026-03-01")
        result = update_streak(mem_conn, 1, 1, "2026-03-01")
        assert result["current_streak"] == 1
        assert result["streak_xp"] == 0

    def test_gap_resets_streak(self, mem_conn):
        update_streak(mem_conn, 1, 1, "2026-03-01")
        update_streak(mem_conn, 1, 1, "2026-03-02")
        result = update_streak(mem_conn, 1, 1, "2026-03-05")  # 3-day gap
        assert result["current_streak"] == 1

    def test_longest_streak_preserved_after_gap(self, mem_conn):
        update_streak(mem_conn, 1, 1, "2026-03-01")
        update_streak(mem_conn, 1, 1, "2026-03-02")
        update_streak(mem_conn, 1, 1, "2026-03-03")
        # Now longest = 3
        result = update_streak(mem_conn, 1, 1, "2026-03-10")  # gap
        assert result["current_streak"] == 1
        assert result["longest_streak"] == 3

    def test_new_longest_replaces_old(self, mem_conn):
        # Build 2-day streak
        update_streak(mem_conn, 1, 1, "2026-03-01")
        update_streak(mem_conn, 1, 1, "2026-03-02")
        # Gap
        update_streak(mem_conn, 1, 1, "2026-03-10")
        # Build 3-day streak
        update_streak(mem_conn, 1, 1, "2026-03-11")
        result = update_streak(mem_conn, 1, 1, "2026-03-12")
        assert result["current_streak"] == 3
        assert result["longest_streak"] == 3
