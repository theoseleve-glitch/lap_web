"""Driver-level achievement badges — career milestones across all sessions.

Evaluates cumulative metrics (total laps, personal bests, consistency
streaks, etc.) to award milestone badges. Unlike session badges which
evaluate a single outing, these track long-term progression.

Public API
----------
- ``evaluate_driver_achievements(sessions, laps)`` → list of achievement dicts
"""

from __future__ import annotations

from typing import Any

# Achievement definitions: (id, label, description, evaluator_key)
_MILESTONES = [
    # Lap count milestones
    ("laps_10",     "First Steps",        "Complete 10 laps",                  "lap_count", 10),
    ("laps_50",     "Getting Serious",    "Complete 50 laps",                  "lap_count", 50),
    ("laps_100",    "Century Club",       "Complete 100 laps",                 "lap_count", 100),
    ("laps_500",    "Track Warrior",      "Complete 500 laps",                 "lap_count", 500),
    ("laps_1000",   "Lap Legend",         "Complete 1,000 laps",               "lap_count", 1000),
    # Session count milestones
    ("sessions_5",  "Regular Driver",     "Complete 5 sessions",               "session_count", 5),
    ("sessions_25", "Dedicated",          "Complete 25 sessions",              "session_count", 25),
    ("sessions_100","Track Addict",       "Complete 100 sessions",             "session_count", 100),
    # Score milestones
    ("score_70",    "Above Average",      "Achieve a session score of 70+",    "max_score", 70),
    ("score_80",    "High Performer",     "Achieve a session score of 80+",    "max_score", 80),
    ("score_90",    "Elite Driver",       "Achieve a session score of 90+",    "max_score", 90),
    # Consistency milestones
    ("consistency_3","Consistent Run",    "3 sessions in a row with score 60+","consistency_streak", 3),
    ("consistency_5","Iron Consistency",  "5 sessions in a row with score 60+","consistency_streak", 5),
    # Track variety
    ("tracks_3",    "Explorer",           "Drive at 3 different tracks",       "track_count", 3),
    ("tracks_5",    "Globetrotter",       "Drive at 5 different tracks",       "track_count", 5),
    ("tracks_10",   "Circuit Collector",  "Drive at 10 different tracks",      "track_count", 10),
    # Improvement
    ("pb_beat_3",   "Record Breaker",     "Beat your PB 3 times at one track", "pb_improvements", 3),
    ("pb_beat_5",   "Relentless",         "Beat your PB 5 times at one track", "pb_improvements", 5),
]


def evaluate_driver_achievements(
    sessions: list[dict[str, Any]],
    laps: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate driver career achievements from their session/lap history.

    Parameters
    ----------
    sessions : list[dict]
        All sessions for the driver. Each should have: session_id,
        total_score, best_lap_time_s, track_name, session_date, n_laps.
    laps : list[dict] | None
        Optional flat list of all laps. If None, lap count is estimated
        from sessions[i]["n_laps"].

    Returns
    -------
    list[dict]
        Earned achievements with keys: id, label, description, threshold,
        current_value, earned.
    """
    if not sessions:
        return []

    # Compute aggregate stats
    total_laps = sum(s.get("n_laps", 0) or 0 for s in sessions)
    if laps:
        total_laps = max(total_laps, len(laps))
    session_count = len(sessions)

    scores = [s.get("total_score") for s in sessions if s.get("total_score") is not None]
    max_score = max(scores) if scores else 0

    # Consistency streak (sessions sorted by date, consecutive score >= 60)
    sorted_sessions = sorted(sessions, key=lambda s: s.get("session_date", ""))
    max_streak = 0
    current_streak = 0
    for s in sorted_sessions:
        sc = s.get("total_score")
        if sc is not None and sc >= 60:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0

    # Track variety
    tracks = {s.get("track_name") for s in sessions if s.get("track_name")}
    track_count = len(tracks)

    # PB improvements per track
    pb_by_track: dict[str, list[float]] = {}
    for s in sorted_sessions:
        tn = s.get("track_name")
        bt = s.get("best_lap_time_s")
        if tn and bt is not None and bt > 0:
            if tn not in pb_by_track:
                pb_by_track[tn] = []
            pb_by_track[tn].append(bt)

    max_pb_improvements = 0
    for times in pb_by_track.values():
        improvements = 0
        current_pb = times[0]
        for t in times[1:]:
            if t < current_pb:
                improvements += 1
                current_pb = t
        max_pb_improvements = max(max_pb_improvements, improvements)

    # Evaluate each milestone
    stat_map = {
        "lap_count": total_laps,
        "session_count": session_count,
        "max_score": max_score,
        "consistency_streak": max_streak,
        "track_count": track_count,
        "pb_improvements": max_pb_improvements,
    }

    achievements = []
    for mid, label, desc, key, threshold in _MILESTONES:
        current = stat_map.get(key, 0)
        earned = current >= threshold
        achievements.append({
            "id": mid,
            "label": label,
            "description": desc,
            "threshold": threshold,
            "current_value": current,
            "earned": earned,
            "progress_pct": min(100, round((current / threshold) * 100)) if threshold > 0 else 0,
        })

    return achievements
