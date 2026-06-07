"""First-upload bonus: the first session must always reach level 1."""
from telemetry_tool.gamification.xp import (
    XP_FIRST_SESSION, award_session_xp, compute_level,
)


class TestFirstSessionBonus:
    def test_first_session_reaches_level_1(self, mem_conn):
        result = award_session_xp(
            mem_conn, driver_id=1, workspace_id=1, session_id=1,
            is_first_session=True,
        )
        assert result["xp_breakdown"]["first_session"] == XP_FIRST_SESSION
        assert result["new_total"] >= 100
        assert result["new_level"] == 1
        assert result["leveled_up"] is True

    def test_second_session_gets_no_bonus(self, mem_conn):
        award_session_xp(mem_conn, 1, 1, 1, is_first_session=True)
        result = award_session_xp(mem_conn, 1, 1, 2, is_first_session=False)
        assert "first_session" not in result["xp_breakdown"]

    def test_default_is_no_bonus(self, mem_conn):
        result = award_session_xp(mem_conn, 1, 1, 1)
        assert "first_session" not in result["xp_breakdown"]
        assert compute_level(result["new_total"]) == 0  # 50 XP -> level 0
