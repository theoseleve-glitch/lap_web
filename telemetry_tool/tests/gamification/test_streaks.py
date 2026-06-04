"""Tests for streak tracking — consecutive session WEEK detection.

Dates are Monday-aligned for clarity: 2026-03-02, 03-09, 03-16, 03-30, 04-06,
04-13 are all Mondays; 03-05/03-08 fall in the same Mon-Sun week as 03-02.
"""
from telemetry_tool.gamification.streaks import update_streak
from telemetry_tool.gamification.xp import XP_STREAK_PER_DAY


class TestWeeklyStreaks:
    def test_first_session_starts_streak(self, mem_conn):
        result = update_streak(mem_conn, 1, 1, "2026-03-02")
        assert result["current_streak"] == 1
        assert result["longest_streak"] == 1
        assert result["streak_xp"] == XP_STREAK_PER_DAY

    def test_consecutive_week_extends(self, mem_conn):
        update_streak(mem_conn, 1, 1, "2026-03-02")
        result = update_streak(mem_conn, 1, 1, "2026-03-09")  # next week
        assert result["current_streak"] == 2
        assert result["longest_streak"] == 2

    def test_three_week_streak(self, mem_conn):
        update_streak(mem_conn, 1, 1, "2026-03-02")
        update_streak(mem_conn, 1, 1, "2026-03-09")
        result = update_streak(mem_conn, 1, 1, "2026-03-16")
        assert result["current_streak"] == 3

    def test_same_week_no_change(self, mem_conn):
        update_streak(mem_conn, 1, 1, "2026-03-02")  # Monday
        result = update_streak(mem_conn, 1, 1, "2026-03-05")  # same week (Thu)
        assert result["current_streak"] == 1
        assert result["streak_xp"] == 0

    def test_second_session_same_week_does_not_extend(self, mem_conn):
        update_streak(mem_conn, 1, 1, "2026-03-02")
        update_streak(mem_conn, 1, 1, "2026-03-09")  # week 2
        result = update_streak(mem_conn, 1, 1, "2026-03-12")  # still week 2
        assert result["current_streak"] == 2
        assert result["streak_xp"] == 0

    def test_gap_resets_streak(self, mem_conn):
        update_streak(mem_conn, 1, 1, "2026-03-02")
        update_streak(mem_conn, 1, 1, "2026-03-09")
        result = update_streak(mem_conn, 1, 1, "2026-03-30")  # 3-week gap from 03-09
        assert result["current_streak"] == 1

    def test_longest_streak_preserved_after_gap(self, mem_conn):
        update_streak(mem_conn, 1, 1, "2026-03-02")
        update_streak(mem_conn, 1, 1, "2026-03-09")
        update_streak(mem_conn, 1, 1, "2026-03-16")  # longest = 3
        result = update_streak(mem_conn, 1, 1, "2026-03-30")  # gap
        assert result["current_streak"] == 1
        assert result["longest_streak"] == 3

    def test_new_longest_replaces_old(self, mem_conn):
        # Build a 2-week streak
        update_streak(mem_conn, 1, 1, "2026-03-02")
        update_streak(mem_conn, 1, 1, "2026-03-09")
        # Gap (resets)
        update_streak(mem_conn, 1, 1, "2026-03-30")
        # Build a 3-week streak
        update_streak(mem_conn, 1, 1, "2026-04-06")
        result = update_streak(mem_conn, 1, 1, "2026-04-13")
        assert result["current_streak"] == 3
        assert result["longest_streak"] == 3
