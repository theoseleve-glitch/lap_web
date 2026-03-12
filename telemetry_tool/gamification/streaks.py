"""Streak tracking — consecutive session days."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from gamification import queries as Q
from gamification.xp import XP_STREAK_PER_DAY


def update_streak(
    conn, driver_id: int, workspace_id: int, session_date: str,
) -> dict[str, Any]:
    """Update streak based on session date.

    Rules:
    - Same day: no change, no XP
    - Consecutive day: extend streak, +25 XP
    - Gap (2+ days): reset streak to 1, +25 XP
    - First ever: start streak at 1, +25 XP
    """
    current = Q.get_driver_xp(conn, driver_id, workspace_id)

    try:
        today = date.fromisoformat(session_date[:10])
    except (ValueError, TypeError):
        today = date.today()

    if not current or not current.get("last_session_date"):
        streak = 1
        longest = 1
        streak_xp = XP_STREAK_PER_DAY
    else:
        try:
            last = date.fromisoformat(str(current["last_session_date"])[:10])
        except (ValueError, TypeError):
            last = today - timedelta(days=2)

        delta = (today - last).days

        if delta == 0:
            return {
                "current_streak": current["current_streak"],
                "longest_streak": current["longest_streak"],
                "streak_xp": 0,
            }
        elif delta == 1:
            streak = current["current_streak"] + 1
            longest = max(streak, current["longest_streak"])
            streak_xp = XP_STREAK_PER_DAY
        else:
            streak = 1
            longest = current["longest_streak"]
            streak_xp = XP_STREAK_PER_DAY

    # Update XP row with new streak and date
    Q.upsert_driver_xp(
        conn, driver_id, workspace_id,
        xp_delta=streak_xp,
        level=current["level"] if current else 0,
        streak=streak, longest=longest,
        last_date=session_date[:10],
    )

    return {
        "current_streak": streak,
        "longest_streak": longest,
        "streak_xp": streak_xp,
    }
