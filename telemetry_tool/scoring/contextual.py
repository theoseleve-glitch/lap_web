"""Bounded, provenance-tagged feeling adjustments → the contextualized tier.

The absolute tier is never mutated. Adjustments operate on a *copy* of the base
pre-confidence/DR sub-scores, then the contextual pre-total is rescaled by the
same base_total/base_pre factor so the base's confidence and diminishing-returns
damping is preserved — which makes a zero-adjustment call return the base total
exactly. Every change is a labeled reason; nothing is silent.
"""
from __future__ import annotations

import copy
from typing import Any

from scoring.constants import (
    FEELING_PERCEIVED_MISMATCH_CONF,
    FEELING_TRAFFIC_RELIEF_CAP,
    FEELING_TRAFFIC_RELIEF_FRAC,
    FEELING_TYRE_RELIEF_CAP,
    FEELING_TYRE_RELIEF_FRAC,
)
from scoring.helpers import _assign_grade

RESULT_TAGS: set[str] = {
    "completed", "dnf", "crashed", "pit_issue", "traffic",
    "mechanical", "tyre_age_high", "red_flag",
}


def _bounded_relief(score: float, mx: float, frac: float, cap: float) -> float:
    """Fraction of the deficit-to-max, capped in absolute points, never negative."""
    deficit = max(0.0, mx - score)
    return round(min(cap, frac * deficit), 4)


def apply_feeling_adjustments(
    base_result: dict[str, Any],
    *,
    result_tags: list[str],
    perceived_conditions: str | None,
    track_state: str,
    felt_rating: int | None,
) -> dict[str, Any]:
    """Return the contextualized tier for a base score + reflection inputs.

    Returns ``{"total_score", "grade", "adjustments", "provenance"}``. When no
    tags apply and conditions match, the returned total equals the base total
    exactly (byte-identical contextualized tier).
    """
    tags = {str(t).lower() for t in (result_tags or [])}
    base_subs = base_result.get("sub_scores", {})
    base_total = float(base_result.get("total_score", 0.0) or 0.0)

    base_pre = sum(float(s.get("score", 0.0) or 0.0) for s in base_subs.values())
    subs = copy.deepcopy(base_subs)
    adjustments: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []

    # DNF / crash → robustness is a legitimate failure, not missing data.
    if "dnf" in tags or "crashed" in tags:
        rob = subs.get("robustness")
        if rob is not None:
            before = float(rob.get("score", 0.0) or 0.0)
            rob["score"] = 0.0
            adjustments.append({
                "code": "DNF_ROBUSTNESS_ZERO",
                "label": "Race ended in DNF/crash — robustness scored 0 as a legitimate "
                         "failure (not missing data).",
                "dimension": "robustness",
                "delta": round(-before, 4),
            })

    # Traffic → CV overstated inconsistency; bounded, capped consistency relief.
    if "traffic" in tags:
        cons = subs.get("consistency")
        if cons is not None:
            relief = _bounded_relief(float(cons.get("score", 0.0) or 0.0),
                                     float(cons.get("max", 0.0) or 0.0),
                                     FEELING_TRAFFIC_RELIEF_FRAC, FEELING_TRAFFIC_RELIEF_CAP)
            if relief > 0:
                cons["score"] = round(float(cons["score"]) + relief, 4)
                adjustments.append({
                    "code": "TRAFFIC_CONSISTENCY_RELIEF",
                    "label": f"Self-reported traffic — consistency given a bounded "
                             f"+{relief:g} pt relief (capped).",
                    "dimension": "consistency",
                    "delta": relief,
                })

    # High tyre age → expected pace fade normalized, bounded pace relief.
    if "tyre_age_high" in tags:
        pace = subs.get("pace")
        if pace is not None:
            relief = _bounded_relief(float(pace.get("score", 0.0) or 0.0),
                                     float(pace.get("max", 0.0) or 0.0),
                                     FEELING_TYRE_RELIEF_FRAC, FEELING_TYRE_RELIEF_CAP)
            if relief > 0:
                pace["score"] = round(float(pace["score"]) + relief, 4)
                adjustments.append({
                    "code": "TYRE_AGE_PACE_NORMALIZE",
                    "label": f"Self-reported high tyre age — pace given a bounded "
                             f"+{relief:g} pt relief (capped).",
                    "dimension": "pace",
                    "delta": relief,
                })

    adj_pre = sum(float(s.get("score", 0.0) or 0.0) for s in subs.values())
    scale = (base_total / base_pre) if base_pre > 0 else 1.0
    total = adj_pre * scale

    # Perceived conditions disagree with the (manual) track_state → confidence penalty.
    if perceived_conditions and track_state and \
            perceived_conditions.strip().lower() != track_state.strip().lower():
        total *= FEELING_PERCEIVED_MISMATCH_CONF
        provenance.append({
            "code": "PERCEIVED_CONDITION_MISMATCH",
            "label": f"Driver-perceived '{perceived_conditions}' ≠ recorded track state "
                     f"'{track_state}' — contextual score confidence reduced "
                     f"{int(round((1 - FEELING_PERCEIVED_MISMATCH_CONF) * 100))}%.",
            "dimension": None,
        })

    total = round(max(0.0, min(100.0, total)), 4)
    return {
        "total_score": total,
        "grade": _assign_grade(total),
        "adjustments": adjustments,
        "provenance": provenance,
    }
