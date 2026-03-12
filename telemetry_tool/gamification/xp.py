"""XP calculation, level formula, and award logic."""
from __future__ import annotations

import math
from typing import Any

from gamification import queries as Q

# ── XP Constants ──────────────────────────────────────────────
XP_SESSION = 50
XP_DRILL_COMPLETE = 100
XP_WEEK_COMPLETE = 250
XP_PLAN_COMPLETE = 500
XP_BADGE_BRONZE = 75
XP_BADGE_SILVER = 150
XP_BADGE_GOLD = 300
XP_STREAK_PER_DAY = 25
XP_PERSONAL_BEST = 200


def compute_level(total_xp: int) -> int:
    """Level = floor(sqrt(total_xp / 100)). Level 0 below 100 XP."""
    if total_xp < 100:
        return 0
    return int(math.floor(math.sqrt(total_xp / 100)))


def xp_for_level(level: int) -> int:
    """Total XP required to reach a given level."""
    return level * level * 100


def award_session_xp(
    conn, driver_id: int, workspace_id: int,
    session_id: int, badges: list[dict] | None = None,
    previous_best_lap: float | None = None,
    current_best_lap: float | None = None,
) -> dict[str, Any]:
    """Award XP for a session upload. Returns XP summary."""
    xp_gained = XP_SESSION
    xp_breakdown: dict[str, int] = {"session": XP_SESSION}

    # Badge XP
    if badges:
        for badge in badges:
            tier = badge.get("tier", "")
            badge_id = badge.get("id", "unknown")
            if tier == "gold":
                xp_gained += XP_BADGE_GOLD
                xp_breakdown[f"badge_{badge_id}"] = XP_BADGE_GOLD
            elif tier == "silver":
                xp_gained += XP_BADGE_SILVER
                xp_breakdown[f"badge_{badge_id}"] = XP_BADGE_SILVER
            elif tier == "bronze":
                xp_gained += XP_BADGE_BRONZE
                xp_breakdown[f"badge_{badge_id}"] = XP_BADGE_BRONZE

    # Personal best XP
    if (previous_best_lap is not None and current_best_lap is not None
            and current_best_lap < previous_best_lap):
        xp_gained += XP_PERSONAL_BEST
        xp_breakdown["personal_best"] = XP_PERSONAL_BEST

    # Get current state
    current = Q.get_driver_xp(conn, driver_id, workspace_id)
    old_xp = current["total_xp"] if current else 0
    old_level = compute_level(old_xp)
    new_xp = old_xp + xp_gained
    new_level = compute_level(new_xp)

    # Streak preserved from separate update_streak() call
    streak = current["current_streak"] if current else 0
    longest = current["longest_streak"] if current else 0

    Q.upsert_driver_xp(
        conn, driver_id, workspace_id,
        xp_delta=xp_gained, level=new_level,
        streak=streak, longest=longest, last_date=None,
    )

    return {
        "xp_gained": xp_gained,
        "xp_breakdown": xp_breakdown,
        "old_total": old_xp,
        "new_total": new_xp,
        "old_level": old_level,
        "new_level": new_level,
        "leveled_up": new_level > old_level,
    }


def award_drill_xp(
    conn, driver_id: int, workspace_id: int,
    plan_id: int,
) -> dict[str, Any]:
    """Award XP for completing a drill (+100). Check plan completion bonus."""
    xp_gained = XP_DRILL_COMPLETE
    xp_breakdown: dict[str, int] = {"drill": XP_DRILL_COMPLETE}

    # Check plan completion (all 4 weeks touched with completed drills)
    executions = Q.get_plan_executions(conn, plan_id, workspace_id)
    completed = [e for e in executions if e["status"] == "completed"]
    weeks_with_completions = {e["week_number"] for e in completed}

    if len(weeks_with_completions) >= 4:
        xp_gained += XP_PLAN_COMPLETE
        xp_breakdown["plan_complete"] = XP_PLAN_COMPLETE

    current = Q.get_driver_xp(conn, driver_id, workspace_id)
    old_xp = current["total_xp"] if current else 0
    old_level = compute_level(old_xp)
    new_xp = old_xp + xp_gained
    new_level = compute_level(new_xp)

    Q.upsert_driver_xp(
        conn, driver_id, workspace_id,
        xp_delta=xp_gained, level=new_level,
        streak=current["current_streak"] if current else 0,
        longest=current["longest_streak"] if current else 0,
        last_date=None,
    )

    return {
        "xp_gained": xp_gained,
        "xp_breakdown": xp_breakdown,
        "old_level": old_level,
        "new_level": new_level,
        "leveled_up": new_level > old_level,
    }


def get_driver_progress(conn, driver_id: int, workspace_id: int) -> dict[str, Any]:
    """Full progress summary for a driver."""
    xp_row = Q.get_driver_xp(conn, driver_id, workspace_id)
    if not xp_row:
        return {
            "total_xp": 0, "level": 0,
            "xp_for_current_level": 0, "xp_for_next_level": 100,
            "current_streak": 0, "longest_streak": 0,
        }

    total = xp_row["total_xp"]
    level = compute_level(total)
    return {
        "total_xp": total,
        "level": level,
        "xp_for_current_level": xp_for_level(level),
        "xp_for_next_level": xp_for_level(level + 1),
        "current_streak": xp_row["current_streak"],
        "longest_streak": xp_row["longest_streak"],
    }
