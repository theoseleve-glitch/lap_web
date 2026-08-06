"""Gamification engine — XP, achievements, streaks, drill tracking.

The imports below are RELATIVE deliberately. They used to be absolute
(``from gamification.xp import ...``), which resolves only when
``telemetry_tool/`` is itself on ``sys.path``. The tests in
``tests/gamification/`` import the full path -- ``telemetry_tool.gamification.xp``
-- and that runs this module as ``telemetry_tool.gamification``, where a
top-level ``gamification`` does not exist. Every one of the ten test modules
in that directory therefore failed at COLLECTION with
``ModuleNotFoundError: No module named 'gamification.xp'``.

The subsystem's entire test suite has been unrunnable, which is the most
likely reason a personal-best XP bug (min() over (lap, time) pairs, fixed in
24522a8) survived in production. Relative imports resolve correctly under
both import styles, so this keeps the existing absolute callers working.
"""
from .xp import (
    award_session_xp,
    award_drill_xp,
    compute_level,
    get_driver_progress,
)
from .achievements import (
    check_achievements,
    get_achievement_status,
)
from .streaks import update_streak

__all__ = [
    "award_session_xp", "award_drill_xp", "compute_level",
    "get_driver_progress", "check_achievements", "get_achievement_status",
    "update_streak",
]
