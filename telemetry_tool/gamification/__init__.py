"""Gamification engine — XP, achievements, streaks, drill tracking."""
from telemetry_tool.gamification.xp import (
    award_session_xp,
    award_drill_xp,
    compute_level,
    get_driver_progress,
)
from telemetry_tool.gamification.achievements import (
    check_achievements,
    get_achievement_status,
)
from telemetry_tool.gamification.streaks import update_streak

__all__ = [
    "award_session_xp", "award_drill_xp", "compute_level",
    "get_driver_progress", "check_achievements", "get_achievement_status",
    "update_streak",
]
