"""Competition-relative score from session-scoped self-reported results.

The deployed backend has no cohort/percentile infrastructure (no CohortMetric),
so this tier is computed entirely from the driver's own reflection: finishing
position, field size, gaps to rivals. It is ALWAYS labeled self-reported and
never verified against telemetry — honesty over false precision.
"""
from __future__ import annotations

from typing import Any

from scoring.helpers import _assign_grade

# Blend weights: position percentile dominates; gap-to-leader nuances it.
_W_POSITION = 0.75
_W_GAP = 0.25
# A DNF cannot present as a strong competition result regardless of position.
_DNF_SCORE_CAP = 40.0
# Gap (s) to leader at which the gap term reaches 0 (>= this = no gap credit).
_GAP_ZERO_S = 30.0


def _infer_total(race_result: dict[str, Any], competitors: list[dict[str, Any]]) -> int | None:
    total = race_result.get("race_total_competitors")
    if total:
        return int(total)
    positions = [c.get("final_position") for c in competitors if c.get("final_position")]
    own = race_result.get("race_position")
    candidates = [p for p in positions if p is not None]
    if own:
        candidates.append(int(own))
    return max(candidates) if candidates else None


def compute_competition_score(
    race_result: dict[str, Any] | None,
    competitors: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Peer-relative score in [0, 100], or None when there is no competition data."""
    competitors = competitors or []
    race_result = race_result or {}
    position = race_result.get("race_position")
    if not position and not competitors:
        return None

    total = _infer_total(race_result, competitors)
    provenance: list[dict[str, Any]] = [{
        "code": "SELF_REPORTED",
        "label": "Competition score is from the driver's self-reported result and "
                 "rivals — not verified against telemetry.",
        "dimension": None,
    }]

    # Position percentile: 1st -> 100, last -> 0 (single-entry field -> 100).
    if position and total and total > 1:
        percentile = round((total - int(position)) / (total - 1) * 100.0, 2)
    elif position and total == 1:
        percentile = 100.0
    else:
        percentile = None

    # Gap-to-leader term (smaller gap = better), only when supplied.
    gap_leader = race_result.get("race_gap_to_leader_s")
    if gap_leader is not None:
        gap_term = max(0.0, 1.0 - min(float(gap_leader), _GAP_ZERO_S) / _GAP_ZERO_S) * 100.0
    else:
        gap_term = None

    if percentile is not None and gap_term is not None:
        score = _W_POSITION * percentile + _W_GAP * gap_term
    elif percentile is not None:
        score = percentile
    elif gap_term is not None:
        score = gap_term
    else:
        score = 50.0
        provenance.append({
            "code": "SPARSE_INPUT",
            "label": "Insufficient position/gap data — neutral competition score.",
            "dimension": None,
        })

    is_dnf = bool(race_result.get("race_is_dnf"))
    if is_dnf:
        score = min(score, _DNF_SCORE_CAP)
        provenance.append({
            "code": "DNF",
            "label": "DNF caps the competition score.",
            "dimension": None,
        })

    score = round(max(0.0, min(100.0, score)), 4)
    return {
        "score": score,
        "grade": _assign_grade(score),
        "position": int(position) if position else None,
        "total_competitors": total,
        "percentile": percentile,
        "gap_to_leader_s": gap_leader,
        "gap_to_nearest_s": race_result.get("race_gap_to_nearest_s"),
        "is_dnf": is_dnf,
        "basis": "session_competitors_self_reported",
        "provenance": provenance,
    }
