"""Racing-line honesty layer (spec C, §5): tier decision, refusal taxonomy,
provenance assembly, and the consumer draw-guard.

Pure and dependency-light: ``decide_tier`` is a function of already-computed
signals (geometry provenance, grip quality tier, physics-validation result,
solve status). Fail-SAFE — any doubt degrades toward the LOWER tier; a
``speed_profile_only`` must never be rendered as a racing line.
"""
from __future__ import annotations

from typing import Any, Final

# Tier vocabulary — the ONLY legal values of track_racing_lines.tier.
TIER_OPTIMAL_LINE: Final = "optimal_line"
TIER_SPEED_PROFILE_ONLY: Final = "speed_profile_only"
TIER_REFUSED: Final = "refused"
TIERS: Final = frozenset({TIER_OPTIMAL_LINE, TIER_SPEED_PROFILE_ONLY, TIER_REFUSED})

# Refusal / degradation reason taxonomy (machine-readable).
REASON_GATES_FAILED: Final = "gates_failed"
REASON_BELOW_GRIP_FLOOR: Final = "below_grip_floor"
REASON_SOLVER_INFEASIBLE: Final = "solver_infeasible"
REASON_NO_GEOMETRY: Final = "no_geometry"
REASON_DERIVED_GEOMETRY: Final = "derived_geometry"
REASON_VALIDATION_RED: Final = "validation_red"

# Grip quality tiers, ranked (model.TrackSurface.quality_tier: bronze<silver<gold).
_GRIP_RANK: Final = {"bronze": 1, "silver": 2, "gold": 3}
_MIN_OPTIMAL_GRIP_RANK: Final = _GRIP_RANK["gold"]   # spec §5: grip tier >= gold

# Human-verified geometry marker (the geometry-factory success oracle).
_VERIFIED_BOUNDARY: Final = "gt_anchored_native"


def is_drawable_as_line(tier: str | None) -> bool:
    """The consumer guard (Race Brief Lanes 3-4): ONLY an ``optimal_line`` may
    be drawn as a racing line. Everything else — including an unknown tier — is
    a speed profile / nothing, never a line."""
    return tier == TIER_OPTIMAL_LINE


def decide_tier(
    *,
    boundary_source: str | None,
    grip_tier: str | None,
    validation_ok: bool,
    solve_status: str,
) -> tuple[str, str | None]:
    """Decide the honesty tier for a solved (or failed) racing line.

    Returns ``(tier, reason)`` — ``reason`` is None only for a clean
    ``optimal_line``. Fail-SAFE: unknown/absent signals degrade toward the
    lower tier; an ``optimal_line`` requires ALL of {human-verified GT
    geometry, grip tier >= gold, validation green, solve ok}. When several
    doubts apply the strongest (geometry, then grip, then validation) names
    the reason.
    """
    # Refused — the solve produced no usable line.
    if solve_status != "ok":
        reason = REASON_SOLVER_INFEASIBLE if solve_status == "failed" else REASON_GATES_FAILED
        return TIER_REFUSED, reason

    verified_geometry = boundary_source == _VERIFIED_BOUNDARY
    grip_rank = _GRIP_RANK.get((grip_tier or "").lower(), 0)   # unknown -> 0 (fail-safe)

    if not verified_geometry:
        return TIER_SPEED_PROFILE_ONLY, (
            REASON_NO_GEOMETRY if not boundary_source else REASON_DERIVED_GEOMETRY
        )
    if grip_rank < _MIN_OPTIMAL_GRIP_RANK:
        return TIER_SPEED_PROFILE_ONLY, REASON_BELOW_GRIP_FLOOR
    if not validation_ok:
        return TIER_SPEED_PROFILE_ONLY, REASON_VALIDATION_RED

    return TIER_OPTIMAL_LINE, None


def build_provenance(
    *,
    laps_used: int,
    grip_confidence_summary: dict | None,
    geometry_gates_version: str | None,
    solver_name: str,
    solver_version: str | None,
    validation: Any = None,
    warm_start_source: str | None = None,
) -> dict:
    """Assemble the JSON-serializable provenance record stored with a line.

    ``validation`` accepts a ValidationReport (``.to_dict()``), a plain dict,
    or None; anything exotic is stringified so the result always JSON-encodes.
    """
    if validation is not None and hasattr(validation, "to_dict"):
        validation = validation.to_dict()
    elif validation is not None and not isinstance(
        validation, (dict, list, str, int, float, bool)
    ):
        validation = str(validation)
    return {
        "laps_used": int(laps_used),
        "grip_confidence_summary": grip_confidence_summary or {},
        "geometry_gates_version": geometry_gates_version,
        "solver_name": solver_name,
        "solver_version": solver_version,
        "validation": validation,
        "warm_start_source": warm_start_source,
    }
