"""Tests for achievement engine — 15 achievements with check/unlock."""
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

    def test_sessions_10_at_threshold(self, mem_conn):
        ctx = {"session_count": 10, "badges": [], "streak": 0}
        result = check_achievements(mem_conn, 1, 1, session_id=10, context=ctx)
        keys = [a["key"] for a in result]
        assert "sessions_10" in keys
        assert "first_session" in keys  # also qualifies

    def test_sessions_10_below_threshold(self, mem_conn):
        ctx = {"session_count": 9, "badges": [], "streak": 0}
        result = check_achievements(mem_conn, 1, 1, session_id=9, context=ctx)
        keys = [a["key"] for a in result]
        assert "sessions_10" not in keys

    def test_streak_3_unlocks(self, mem_conn):
        ctx = {"session_count": 3, "badges": [], "streak": 3}
        result = check_achievements(mem_conn, 1, 1, session_id=3, context=ctx)
        keys = [a["key"] for a in result]
        assert "streak_3" in keys

    def test_streak_7_unlocks(self, mem_conn):
        ctx = {"session_count": 7, "badges": [], "streak": 7}
        result = check_achievements(mem_conn, 1, 1, session_id=7, context=ctx)
        keys = [a["key"] for a in result]
        assert "streak_7" in keys

    def test_first_badge_unlocks(self, mem_conn):
        badges = [{"id": "pace_master", "tier": "bronze"}]
        ctx = {"session_count": 1, "badges": badges, "streak": 0}
        result = check_achievements(mem_conn, 1, 1, session_id=1, context=ctx)
        keys = [a["key"] for a in result]
        assert "first_badge" in keys

    def test_all_bronze_unlocks(self, mem_conn):
        badges = [{"id": f"b{i}", "tier": "bronze"} for i in range(6)]
        ctx = {"session_count": 10, "badges": badges, "streak": 0}
        result = check_achievements(mem_conn, 1, 1, session_id=10, context=ctx)
        keys = [a["key"] for a in result]
        assert "all_bronze" in keys
        assert "first_badge" in keys

    def test_all_gold_requires_all_gold_tier(self, mem_conn):
        badges = [{"id": f"b{i}", "tier": "gold"} for i in range(5)]
        badges.append({"id": "b5", "tier": "silver"})
        ctx = {"session_count": 50, "badges": badges, "streak": 0}
        result = check_achievements(mem_conn, 1, 1, session_id=50, context=ctx)
        keys = [a["key"] for a in result]
        assert "all_gold" not in keys

    def test_personal_best(self, mem_conn):
        ctx = {"session_count": 5, "badges": [], "streak": 1, "is_personal_best": True}
        result = check_achievements(mem_conn, 1, 1, session_id=5, context=ctx)
        keys = [a["key"] for a in result]
        assert "personal_best" in keys

    def test_score_jump(self, mem_conn):
        ctx = {"session_count": 5, "badges": [], "streak": 0, "score_improvement": 12}
        result = check_achievements(mem_conn, 1, 1, session_id=5, context=ctx)
        keys = [a["key"] for a in result]
        assert "score_jump" in keys

    def test_score_jump_below_threshold(self, mem_conn):
        ctx = {"session_count": 5, "badges": [], "streak": 0, "score_improvement": 8}
        result = check_achievements(mem_conn, 1, 1, session_id=5, context=ctx)
        keys = [a["key"] for a in result]
        assert "score_jump" not in keys


class TestGetAchievementStatus:
    def test_returns_all_15(self, mem_conn):
        result = get_achievement_status(mem_conn, 1, 1)
        assert len(result) == len(ACHIEVEMENT_CATALOG)
        assert len(result) == 15

    def test_all_locked_initially(self, mem_conn):
        result = get_achievement_status(mem_conn, 1, 1)
        assert all(not a["unlocked"] for a in result)

    def test_shows_unlocked_after_check(self, mem_conn):
        ctx = {"session_count": 1, "badges": [], "streak": 0}
        check_achievements(mem_conn, 1, 1, session_id=1, context=ctx)
        result = get_achievement_status(mem_conn, 1, 1)
        first = next(a for a in result if a["key"] == "first_session")
        assert first["unlocked"] is True
        assert first["unlocked_at"] is not None

    def test_each_has_required_fields(self, mem_conn):
        result = get_achievement_status(mem_conn, 1, 1)
        for a in result:
            assert "key" in a
            assert "label" in a
            assert "description" in a
            assert "icon" in a
            assert "unlocked" in a
