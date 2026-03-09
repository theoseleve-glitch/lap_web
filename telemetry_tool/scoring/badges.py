"""Badge / achievement system for session scoring."""
from __future__ import annotations

from typing import Any, Final

from scoring.constants import (
    BADGE_TIER_BRONZE,
    BADGE_TIER_GOLD,
    BADGE_TIER_SILVER,
    TOTAL_MAX,
)

# Badge definitions:  (id, label, category, sub_score_key | "total")

_BADGE_DEFS: Final[list[tuple[str, str, str, str]]] = [
    ("pace_master",           "Pace Master",           "pace",        "pace"),
    ("consistency_champion",  "Consistency Champion",   "consistency", "consistency"),
    ("execution_expert",      "Execution Expert",       "execution",   "execution"),
    ("endurance_warrior",     "Endurance Warrior",      "robustness",  "robustness"),
    ("adaptor",               "Adaptor",                "adaptation",  "adaptation"),
    ("flow_state",            "Flow State",             "total",       "total"),
]


def evaluate_badges(score_result: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate achievement badges from a ``score_session()`` result dict.

    Each badge maps to one scoring category (or the overall total).  The
    driver earns the *highest* qualifying tier -- bronze (>=60 %),
    silver (>=75 %), or gold (>=90 %) of the category maximum.

    Parameters
    ----------
    score_result:
        The dict returned by :func:`score_session` (must contain
        ``sub_scores`` and ``total_score``).

    Returns
    -------
    list[dict[str, Any]]
        One entry per earned badge, each with keys
        ``id``, ``label``, ``tier``, ``category``, ``criteria``.
        Empty list when no thresholds are met.
    """

    sub_scores: dict[str, Any] = score_result.get("sub_scores", {})
    total_score: float = float(score_result.get("total_score", 0.0))

    badges: list[dict[str, Any]] = []

    for badge_id, label, category, key in _BADGE_DEFS:
        # Resolve score and max for this badge
        if key == "total":
            score = total_score
            maximum = TOTAL_MAX
        else:
            entry = sub_scores.get(key)
            if entry is None:
                continue
            score = float(entry.get("score", 0.0))
            maximum = float(entry.get("max", 1.0))

        if maximum <= 0:
            continue

        frac = score / maximum

        # Determine highest qualifying tier
        if frac >= BADGE_TIER_GOLD:
            tier = "gold"
        elif frac >= BADGE_TIER_SILVER:
            tier = "silver"
        elif frac >= BADGE_TIER_BRONZE:
            tier = "bronze"
        else:
            continue

        badges.append({
            "id":       badge_id,
            "label":    label,
            "tier":     tier,
            "category": category,
            "criteria": f">={int(frac * 100)}% of {category} max",
        })

    return badges
