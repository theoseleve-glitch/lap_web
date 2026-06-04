"""Streak tracking — consecutive session weeks (ISO weeks with >=1 session)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from gamification import queries as Q
from gamification.xp import XP_STREAK_PER_DAY


def _week_monday(d: date) -> date:
    """Monday of the ISO week containing d (week-bucket key)."""
    return d - timedelta(days=d.weekday())


def update_streak(
    conn, driver_id: int, workspace_id: int, session_date: str,
) -> dict[str, Any]:
    """Update the WEEKLY streak based on session date.

    A weekly streak counts consecutive calendar weeks (Mon-Sun) that contain
    at least one session.

    Rules:
    - Same week as the last session: no change, no XP
    - An earlier week than the last session (out-of-order upload): no change
    - The immediately following week: extend streak, +XP
    - A gap of 2+ weeks: reset streak to 1, +XP
    - First ever: start streak at 1, +XP
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
            last = today - timedelta(days=14)

        # Distance in whole weeks between the two sessions' week-buckets.
        week_delta = (_week_monday(today) - _week_monday(last)).days // 7

        if week_delta <= 0:
            # Same week, or an out-of-order earlier session — no change, no XP,
            # and do not move last_session_date backwards.
            return {
                "current_streak": current["current_streak"],
                "longest_streak": current["longest_streak"],
                "streak_xp": 0,
            }
        elif week_delta == 1:
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
