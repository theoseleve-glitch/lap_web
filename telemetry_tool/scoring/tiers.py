"""Assemble the tiered, honest score: absolute · contextualized · competition."""
from __future__ import annotations

from typing import Any

from scoring.contextual import apply_feeling_adjustments


def _reflection_present(feeling: dict[str, Any] | None) -> bool:
    if not feeling:
        return False
    return bool(
        feeling.get("result_tags")
        or feeling.get("felt_performance_rating") is not None
        or feeling.get("driver_perceived_conditions")
        or feeling.get("race_position") is not None
    )


def build_tiered_scores(
    base_result: dict[str, Any],
    *,
    feeling: dict[str, Any] | None = None,
    competition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose the three tiers. base_result is never mutated.

    With no feeling and no competition, the contextualized tier equals the
    absolute tier exactly and competition is None (byte-identical guarantee).
    """
    absolute = {
        "total_score": base_result.get("total_score"),
        "grade": base_result.get("grade"),
        "sub_scores": base_result.get("sub_scores", {}),
    }

    if _reflection_present(feeling):
        contextualized = apply_feeling_adjustments(
            base_result,
            result_tags=feeling.get("result_tags") or [],
            perceived_conditions=feeling.get("driver_perceived_conditions"),
            track_state=str(feeling.get("track_state") or "dry"),
            felt_rating=feeling.get("felt_performance_rating"),
        )
    else:
        contextualized = {
            "total_score": absolute["total_score"],
            "grade": absolute["grade"],
            "adjustments": [],
            "provenance": [],
        }

    return {
        "absolute": absolute,
        "contextualized": contextualized,
        "competition": competition,
        "reflection_present": _reflection_present(feeling),
    }
