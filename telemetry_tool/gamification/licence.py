"""Licence tier system — career progression gated by skill + experience."""
from __future__ import annotations

from typing import Any

LICENCE_TIERS = [
    {"tier": "rookie",   "color": "#888888", "laps": 0,    "score": 0,  "extra": None},
    {"tier": "club",     "color": "#B6FF2E", "laps": 50,   "score": 50, "extra": None},
    {"tier": "national", "color": "#00d4ff", "laps": 200,  "score": 65, "extra": "2_tracks"},
    {"tier": "pro",      "color": "#D946EF", "laps": 500,  "score": 75, "extra": "3_pbs"},
    {"tier": "elite",    "color": "#FFD400", "laps": 1000, "score": 85, "extra": "cv_1.5"},
    {"tier": "legend",   "color": "#FF3B6B", "laps": 2000, "score": 90, "extra": "streak_5_80"},
]


def compute_licence_tier(
    total_laps: int,
    best_score: float,
    track_count: int = 0,
    pb_improvements: int = 0,
    best_cv: float | None = None,
    best_streak_80: int = 0,
) -> dict[str, Any]:
    """Compute current licence tier and progress to next.

    Args:
        total_laps: Cumulative laps across all sessions.
        best_score: Highest session score ever achieved.
        track_count: Number of distinct tracks driven.
        pb_improvements: Max PB beats at any single track.
        best_cv: Best (lowest) CV% achieved in any session.
        best_streak_80: Longest streak of sessions scoring 80+.

    Returns:
        Dict with tier, color, next_tier, progress breakdown.
    """
    current_idx = 0
    for i, t in enumerate(LICENCE_TIERS):
        if total_laps < t["laps"] or best_score < t["score"]:
            break
        if t["extra"] == "2_tracks" and track_count < 2:
            break
        if t["extra"] == "3_pbs" and pb_improvements < 3:
            break
        if t["extra"] == "cv_1.5" and (best_cv is None or best_cv > 1.5):
            break
        if t["extra"] == "streak_5_80" and best_streak_80 < 5:
            break
        current_idx = i

    current = LICENCE_TIERS[current_idx]
    next_tier = LICENCE_TIERS[current_idx + 1] if current_idx < len(LICENCE_TIERS) - 1 else None

    progress = {}
    if next_tier:
        progress["laps"] = {"current": total_laps, "required": next_tier["laps"]}
        progress["score"] = {"current": round(best_score, 1), "required": next_tier["score"]}

    return {
        "tier": current["tier"],
        "color": current["color"],
        "tier_index": current_idx,
        "total_tiers": len(LICENCE_TIERS),
        "next_tier": next_tier["tier"] if next_tier else None,
        "next_color": next_tier["color"] if next_tier else None,
        "progress": progress,
        "all_tiers": [{"tier": t["tier"], "color": t["color"]} for t in LICENCE_TIERS],
    }
