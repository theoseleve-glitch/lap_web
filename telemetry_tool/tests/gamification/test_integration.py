"""Integration tests — full XP/achievement/streak flow end-to-end."""
import json
from telemetry_tool.gamification.xp import award_session_xp, get_driver_progress
from telemetry_tool.gamification.streaks import update_streak
from telemetry_tool.gamification.achievements import (
    check_achievements, get_achievement_status,
)
from telemetry_tool.gamification.queries import (
    insert_drill_execution, get_plan_executions,
    count_driver_sessions,
)


class TestFullFlow:
    """Simulate: first session → XP → streak → achievement → progress check."""

    def test_first_session_awards_xp_and_unlocks_first_session(self, mem_conn):
        """Upload first session → get XP + "First Laps" achievement."""
        # Insert a session row (simulating pipeline insert)
        mem_conn.execute(
            "INSERT INTO sessions (session_id, driver_id, session_date, best_lap_time_s) "
            "VALUES (1, 1, '2026-03-01', 45.3)"
        )

        # 1) Award session XP
        xp = award_session_xp(mem_conn, driver_id=1, workspace_id=1, session_id=1)
        assert xp["xp_gained"] == 50
        assert xp["new_total"] == 50

        # 2) Update streak
        streak = update_streak(mem_conn, driver_id=1, workspace_id=1, session_date="2026-03-01")
        assert streak["current_streak"] == 1

        # 3) Check achievements
        count = count_driver_sessions(mem_conn, driver_id=1, workspace_id=1)
        achievements = check_achievements(
            mem_conn, 1, 1, session_id=1,
            context={"session_count": count, "badges": [], "streak": 1},
        )
        keys = [a["key"] for a in achievements]
        assert "first_session" in keys

        # 4) Full progress
        progress = get_driver_progress(mem_conn, 1, 1)
        assert progress["total_xp"] == 75  # 50 session + 25 streak

    def test_multi_session_builds_streak_and_levels(self, mem_conn):
        """3 consecutive sessions → streak 3 + hat_trick achievement + level up."""
        for i, date in enumerate(["2026-03-01", "2026-03-02", "2026-03-03"], 1):
            mem_conn.execute(
                "INSERT INTO sessions (session_id, driver_id, session_date, best_lap_time_s) "
                "VALUES (?, 1, ?, 45.3)", (i, date),
            )
            award_session_xp(mem_conn, driver_id=1, workspace_id=1, session_id=i)
            update_streak(mem_conn, driver_id=1, workspace_id=1, session_date=date)

        # After 3 sessions: 150 XP session + 75 XP streak = 225 XP → level 1
        progress = get_driver_progress(mem_conn, 1, 1)
        assert progress["total_xp"] == 225
        assert progress["level"] == 1
        assert progress["current_streak"] == 3

        # Check achievements (streak_3 should unlock)
        achievements = check_achievements(
            mem_conn, 1, 1, session_id=3,
            context={"session_count": 3, "badges": [], "streak": 3},
        )
        keys = [a["key"] for a in achievements]
        assert "streak_3" in keys

    def test_badge_xp_triggers_level_up(self, mem_conn):
        """Gold badge XP pushes past level threshold."""
        badges = [{"id": "pace_master", "tier": "gold", "category": "pace"}]
        xp = award_session_xp(mem_conn, 1, 1, session_id=1, badges=badges)
        # 50 session + 300 gold badge = 350 XP → level 1
        assert xp["xp_gained"] == 350
        assert xp["leveled_up"] is True
        assert xp["new_level"] == 1

    def test_drill_execution_flow(self, mem_conn):
        """Create plan → execute drill → check execution list."""
        mem_conn.execute(
            "INSERT INTO development_plans (driver_id, plan_name) VALUES (1, 'Test Plan')"
        )
        mem_conn.execute(
            "INSERT INTO sessions (session_id, driver_id, session_date) VALUES (1, 1, '2026-03-01')"
        )

        # Execute a drill
        exec_id = insert_drill_execution(
            mem_conn, workspace_id=1, driver_id=1, plan_id=1,
            week_number=1, drill_index=0, session_id=1,
            status="completed", notes="Good progress on braking point",
        )
        assert exec_id is not None

        # Fetch executions
        execs = get_plan_executions(mem_conn, plan_id=1, workspace_id=1)
        assert len(execs) == 1
        assert execs[0]["status"] == "completed"
        assert execs[0]["notes"] == "Good progress on braking point"

    def test_personal_best_detection(self, mem_conn):
        """Faster lap time → PB XP awarded."""
        xp = award_session_xp(
            mem_conn, 1, 1, session_id=1,
            previous_best_lap=60.0, current_best_lap=58.5,
        )
        assert xp["xp_breakdown"]["personal_best"] == 200
        assert xp["xp_gained"] == 250  # 50 + 200

        # Check PB achievement
        achievements = check_achievements(
            mem_conn, 1, 1, session_id=1,
            context={
                "session_count": 1, "badges": [], "streak": 0,
                "is_personal_best": True,
            },
        )
        keys = [a["key"] for a in achievements]
        assert "personal_best" in keys

    def test_achievement_status_complete_view(self, mem_conn):
        """After unlocking some achievements, status shows correct counts."""
        # Unlock 3 achievements
        ctx = {"session_count": 10, "badges": [{"id": "b1", "tier": "bronze"}], "streak": 3}
        check_achievements(mem_conn, 1, 1, session_id=10, context=ctx)

        status = get_achievement_status(mem_conn, 1, 1)
        unlocked = [a for a in status if a["unlocked"]]
        locked = [a for a in status if not a["unlocked"]]

        assert len(unlocked) >= 3  # first_session, sessions_10, streak_3, first_badge
        assert len(locked) + len(unlocked) == 15

    def test_gamification_json_serializable(self, mem_conn):
        """Full progress output is JSON-serializable (API requirement)."""
        award_session_xp(mem_conn, 1, 1, session_id=1)
        update_streak(mem_conn, 1, 1, "2026-03-01")
        progress = get_driver_progress(mem_conn, 1, 1)
        achievements = get_achievement_status(mem_conn, 1, 1)

        result = {**progress, "achievements": achievements}
        json_str = json.dumps(result)
        assert len(json_str) > 100
        parsed = json.loads(json_str)
        assert parsed["total_xp"] > 0
