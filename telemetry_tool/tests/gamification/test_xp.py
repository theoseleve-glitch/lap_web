"""Tests for XP engine — level formula, session/drill/badge awards."""
from telemetry_tool.gamification.xp import (
    compute_level, xp_for_level, award_session_xp, award_drill_xp,
    get_driver_progress, XP_SESSION, XP_BADGE_GOLD, XP_BADGE_SILVER,
    XP_BADGE_BRONZE, XP_PERSONAL_BEST, XP_DRILL_COMPLETE,
)


class TestComputeLevel:
    def test_zero_xp(self):
        assert compute_level(0) == 0

    def test_below_100(self):
        assert compute_level(99) == 0

    def test_level_1(self):
        assert compute_level(100) == 1

    def test_level_2(self):
        assert compute_level(400) == 2

    def test_level_5(self):
        assert compute_level(2500) == 5

    def test_level_10(self):
        assert compute_level(10000) == 10

    def test_between_levels(self):
        # sqrt(350/100) = sqrt(3.5) = 1.87 → floor = 1
        assert compute_level(350) == 1

    def test_large_xp(self):
        assert compute_level(40000) == 20


class TestXpForLevel:
    def test_level_0(self):
        assert xp_for_level(0) == 0

    def test_level_1(self):
        assert xp_for_level(1) == 100

    def test_level_5(self):
        assert xp_for_level(5) == 2500

    def test_level_10(self):
        assert xp_for_level(10) == 10000


class TestAwardSessionXp:
    def test_basic_session_xp(self, mem_conn):
        result = award_session_xp(mem_conn, driver_id=1, workspace_id=1, session_id=1)
        assert result["xp_gained"] == XP_SESSION
        assert result["new_total"] == XP_SESSION
        assert result["old_level"] == 0
        assert result["leveled_up"] is False

    def test_gold_badge_xp(self, mem_conn):
        badges = [{"id": "pace_master", "tier": "gold", "category": "pace"}]
        result = award_session_xp(mem_conn, 1, 1, 1, badges=badges)
        assert result["xp_gained"] == XP_SESSION + XP_BADGE_GOLD
        assert "badge_pace_master" in result["xp_breakdown"]

    def test_silver_badge_xp(self, mem_conn):
        badges = [{"id": "consistency_champion", "tier": "silver"}]
        result = award_session_xp(mem_conn, 1, 1, 1, badges=badges)
        assert result["xp_gained"] == XP_SESSION + XP_BADGE_SILVER

    def test_bronze_badge_xp(self, mem_conn):
        badges = [{"id": "execution_expert", "tier": "bronze"}]
        result = award_session_xp(mem_conn, 1, 1, 1, badges=badges)
        assert result["xp_gained"] == XP_SESSION + XP_BADGE_BRONZE

    def test_multiple_badges(self, mem_conn):
        badges = [
            {"id": "b1", "tier": "gold"},
            {"id": "b2", "tier": "silver"},
        ]
        result = award_session_xp(mem_conn, 1, 1, 1, badges=badges)
        expected = XP_SESSION + XP_BADGE_GOLD + XP_BADGE_SILVER
        assert result["xp_gained"] == expected

    def test_personal_best_xp(self, mem_conn):
        result = award_session_xp(
            mem_conn, 1, 1, 1,
            previous_best_lap=60.0, current_best_lap=59.5,
        )
        assert result["xp_gained"] == XP_SESSION + XP_PERSONAL_BEST

    def test_no_pb_when_slower(self, mem_conn):
        result = award_session_xp(
            mem_conn, 1, 1, 1,
            previous_best_lap=60.0, current_best_lap=61.0,
        )
        assert result["xp_gained"] == XP_SESSION

    def test_cumulative_xp(self, mem_conn):
        award_session_xp(mem_conn, 1, 1, session_id=1)
        result = award_session_xp(mem_conn, 1, 1, session_id=2)
        assert result["new_total"] == XP_SESSION * 2
        assert result["old_total"] == XP_SESSION

    def test_level_up_detected(self, mem_conn):
        # 2 sessions = 100 XP = level 1
        award_session_xp(mem_conn, 1, 1, session_id=1)
        result = award_session_xp(mem_conn, 1, 1, session_id=2)
        assert result["leveled_up"] is True
        assert result["new_level"] == 1
        assert result["old_level"] == 0


class TestAwardDrillXp:
    def test_basic_drill_xp(self, mem_conn):
        # Need a plan in the DB
        mem_conn.execute(
            "INSERT INTO development_plans (driver_id, plan_name) VALUES (1, 'Test Plan')"
        )
        # Need initial XP row
        award_session_xp(mem_conn, 1, 1, session_id=1)
        result = award_drill_xp(mem_conn, driver_id=1, workspace_id=1, plan_id=1)
        assert result["xp_gained"] >= XP_DRILL_COMPLETE


class TestGetDriverProgress:
    def test_no_data_returns_defaults(self, mem_conn):
        result = get_driver_progress(mem_conn, driver_id=999, workspace_id=1)
        assert result["total_xp"] == 0
        assert result["level"] == 0
        assert result["xp_for_next_level"] == 100

    def test_after_sessions(self, mem_conn):
        award_session_xp(mem_conn, 1, 1, session_id=1)
        award_session_xp(mem_conn, 1, 1, session_id=2)
        result = get_driver_progress(mem_conn, driver_id=1, workspace_id=1)
        assert result["total_xp"] == XP_SESSION * 2
        assert result["level"] == 1
        assert result["xp_for_current_level"] == 100
        assert result["xp_for_next_level"] == 400
