"""Gamification engine — XP, achievements, streaks, drill tracking."""
from gamification.xp import (
    award_session_xp,
    award_drill_xp,
    compute_level,
    get_driver_progress,
)
from gamification.achievements import (
    check_achievements,
    get_achievement_status,
)
from gamification.streaks import update_streak

__all__ = [
    "award_session_xp", "award_drill_xp", "compute_level",
    "get_driver_progress", "check_achievements", "get_achievement_status",
    "update_streak",
]
