"""Achievement catalog and unlock logic — 15 achievements."""
from __future__ import annotations

from typing import Any, Callable

from . import queries as Q

# ── Achievement Catalog ──────────────────────────────────────

ACHIEVEMENT_CATALOG: list[dict[str, str]] = [
    {"key": "first_session",   "label": "First Laps",         "description": "Upload your first session",            "icon": "flag"},
    {"key": "sessions_10",     "label": "Regular",            "description": "10 sessions uploaded",                  "icon": "calendar"},
    {"key": "sessions_50",     "label": "Dedicated",          "description": "50 sessions uploaded",                  "icon": "star"},
    {"key": "sessions_100",    "label": "Veteran",            "description": "100 sessions uploaded",                 "icon": "trophy"},
    {"key": "first_badge",     "label": "Medal Winner",       "description": "Earn any badge",                        "icon": "medal"},
    {"key": "all_bronze",      "label": "Bronze Collection",  "description": "All 6 badges at bronze or above",       "icon": "shield"},
    {"key": "all_silver",      "label": "Silver Collection",  "description": "All 6 badges at silver or above",       "icon": "shield"},
    {"key": "all_gold",        "label": "Gold Standard",      "description": "All 6 badges at gold",                  "icon": "crown"},
    {"key": "streak_3",        "label": "Hat Trick",          "description": "3-day session streak",                  "icon": "fire"},
    {"key": "streak_7",        "label": "Week Warrior",       "description": "7-day session streak",                  "icon": "fire"},
    {"key": "streak_30",       "label": "Iron Will",          "description": "30-day session streak",                 "icon": "fire"},
    {"key": "plan_completed",  "label": "Plan Complete",      "description": "Finish a development plan",             "icon": "check-circle"},
    {"key": "all_drills_week", "label": "Perfect Week",       "description": "Complete all drills in a plan week",    "icon": "list-check"},
    {"key": "personal_best",   "label": "New PB",             "description": "Beat your personal best lap time",      "icon": "zap"},
    {"key": "score_jump",      "label": "Level Up",           "description": "Improve total score by 10+ points",     "icon": "trending-up"},
]

_CATALOG_MAP: dict[str, dict] = {a["key"]: a for a in ACHIEVEMENT_CATALOG}

# ── Check Functions ──────────────────────────────────────────


def _check_first_session(ctx: dict) -> bool:
    return ctx.get("session_count", 0) >= 1


def _check_sessions_10(ctx: dict) -> bool:
    return ctx.get("session_count", 0) >= 10


def _check_sessions_50(ctx: dict) -> bool:
    return ctx.get("session_count", 0) >= 50


def _check_sessions_100(ctx: dict) -> bool:
    return ctx.get("session_count", 0) >= 100


def _check_first_badge(ctx: dict) -> bool:
    return len(ctx.get("badges", [])) >= 1


def _check_all_bronze(ctx: dict) -> bool:
    return len(ctx.get("badges", [])) >= 6


def _check_all_silver(ctx: dict) -> bool:
    badges = ctx.get("badges", [])
    return len([b for b in badges if b.get("tier") in ("silver", "gold")]) >= 6


def _check_all_gold(ctx: dict) -> bool:
    badges = ctx.get("badges", [])
    return len([b for b in badges if b.get("tier") == "gold"]) >= 6


def _check_streak_3(ctx: dict) -> bool:
    return ctx.get("streak", 0) >= 3


def _check_streak_7(ctx: dict) -> bool:
    return ctx.get("streak", 0) >= 7


def _check_streak_30(ctx: dict) -> bool:
    return ctx.get("streak", 0) >= 30


def _check_plan_completed(ctx: dict) -> bool:
    return ctx.get("plan_just_completed", False)


def _check_all_drills_week(ctx: dict) -> bool:
    return ctx.get("week_just_completed", False)


def _check_personal_best(ctx: dict) -> bool:
    return ctx.get("is_personal_best", False)


def _check_score_jump(ctx: dict) -> bool:
    return ctx.get("score_improvement", 0) >= 10


_CHECKS: dict[str, Callable[[dict], bool]] = {
    "first_session":   _check_first_session,
    "sessions_10":     _check_sessions_10,
    "sessions_50":     _check_sessions_50,
    "sessions_100":    _check_sessions_100,
    "first_badge":     _check_first_badge,
    "all_bronze":      _check_all_bronze,
    "all_silver":      _check_all_silver,
    "all_gold":        _check_all_gold,
    "streak_3":        _check_streak_3,
    "streak_7":        _check_streak_7,
    "streak_30":       _check_streak_30,
    "plan_completed":  _check_plan_completed,
    "all_drills_week": _check_all_drills_week,
    "personal_best":   _check_personal_best,
    "score_jump":      _check_score_jump,
}


def check_achievements(
    conn, driver_id: int, workspace_id: int,
    session_id: int | None, context: dict,
) -> list[dict]:
    """Check all achievements against context, unlock new ones.

    Returns list of newly unlocked achievement dicts.
    """
    already = {a["achievement_key"] for a in Q.get_achievements(conn, driver_id, workspace_id)}
    newly_unlocked: list[dict] = []

    for key, check_fn in _CHECKS.items():
        if key in already:
            continue
        if check_fn(context):
            inserted = Q.insert_achievement(conn, driver_id, workspace_id, key, session_id)
            if inserted:
                newly_unlocked.append(_CATALOG_MAP[key])

    return newly_unlocked


def get_achievement_status(
    conn, driver_id: int, workspace_id: int,
) -> list[dict]:
    """All 15 achievements with locked/unlocked state and unlock date."""
    unlocked = {
        a["achievement_key"]: a["unlocked_at"]
        for a in Q.get_achievements(conn, driver_id, workspace_id)
    }

    return [
        {
            **entry,
            "unlocked": entry["key"] in unlocked,
            "unlocked_at": unlocked.get(entry["key"]),
        }
        for entry in ACHIEVEMENT_CATALOG
    ]
