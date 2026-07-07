"""Honesty layer (spec C, §5): tier decision, refusal taxonomy, provenance,
consumer draw-guard. Pure logic — fully verifiable without PG or a solver."""
import json

from track_surface.honesty import (
    REASON_BELOW_GRIP_FLOOR,
    REASON_DERIVED_GEOMETRY,
    REASON_NO_GEOMETRY,
    REASON_SOLVER_INFEASIBLE,
    REASON_VALIDATION_RED,
    TIER_OPTIMAL_LINE,
    TIER_REFUSED,
    TIER_SPEED_PROFILE_ONLY,
    TIERS,
    build_provenance,
    decide_tier,
    is_drawable_as_line,
)


class TestDecideTier:
    def test_optimal_line_all_green(self):
        tier, reason = decide_tier(boundary_source="gt_anchored_native",
                                   grip_tier="gold", validation_ok=True, solve_status="ok")
        assert tier == TIER_OPTIMAL_LINE
        assert reason is None

    def test_derived_geometry_degrades(self):
        tier, reason = decide_tier(boundary_source="predicted",
                                   grip_tier="gold", validation_ok=True, solve_status="ok")
        assert tier == TIER_SPEED_PROFILE_ONLY
        assert reason == REASON_DERIVED_GEOMETRY

    def test_no_geometry_degrades(self):
        tier, reason = decide_tier(boundary_source=None,
                                   grip_tier="gold", validation_ok=True, solve_status="ok")
        assert tier == TIER_SPEED_PROFILE_ONLY
        assert reason == REASON_NO_GEOMETRY

    def test_below_grip_floor_degrades(self):
        for g in ("silver", "bronze"):
            tier, reason = decide_tier(boundary_source="gt_anchored_native",
                                       grip_tier=g, validation_ok=True, solve_status="ok")
            assert tier == TIER_SPEED_PROFILE_ONLY
            assert reason == REASON_BELOW_GRIP_FLOOR

    def test_unknown_grip_is_failsafe(self):
        # unknown grip must NOT be treated as gold — degrade.
        tier, reason = decide_tier(boundary_source="gt_anchored_native",
                                   grip_tier=None, validation_ok=True, solve_status="ok")
        assert tier == TIER_SPEED_PROFILE_ONLY
        assert reason == REASON_BELOW_GRIP_FLOOR

    def test_validation_red_degrades_even_on_gt_gold(self):
        tier, reason = decide_tier(boundary_source="gt_anchored_native",
                                   grip_tier="gold", validation_ok=False, solve_status="ok")
        assert tier == TIER_SPEED_PROFILE_ONLY
        assert reason == REASON_VALIDATION_RED

    def test_failed_solve_refused(self):
        tier, reason = decide_tier(boundary_source="gt_anchored_native",
                                   grip_tier="gold", validation_ok=True, solve_status="failed")
        assert tier == TIER_REFUSED
        assert reason == REASON_SOLVER_INFEASIBLE

    def test_geometry_doubt_takes_precedence_over_grip(self):
        # both geometry and grip are bad -> the geometry reason wins (strongest).
        tier, reason = decide_tier(boundary_source=None,
                                   grip_tier="bronze", validation_ok=True, solve_status="ok")
        assert tier == TIER_SPEED_PROFILE_ONLY
        assert reason == REASON_NO_GEOMETRY

    def test_vocabulary_is_exactly_three(self):
        assert TIERS == {TIER_OPTIMAL_LINE, TIER_SPEED_PROFILE_ONLY, TIER_REFUSED}


class TestDrawGuard:
    def test_only_optimal_line_is_drawable(self):
        assert is_drawable_as_line(TIER_OPTIMAL_LINE) is True
        for t in (TIER_SPEED_PROFILE_ONLY, TIER_REFUSED, None, "garbage"):
            assert is_drawable_as_line(t) is False


class TestProvenance:
    def test_json_serializable_with_expected_keys(self):
        class _Rep:
            def to_dict(self):
                return {"ok": True, "residual_max": 0.4}

        prov = build_provenance(
            laps_used=42, grip_confidence_summary={"p90": 0.9},
            geometry_gates_version="v1", solver_name="ocp_2d_stitched",
            solver_version="abc123", validation=_Rep(), warm_start_source="prev_line",
        )
        assert set(prov) >= {
            "laps_used", "grip_confidence_summary", "geometry_gates_version",
            "solver_name", "solver_version", "validation", "warm_start_source",
        }
        assert prov["laps_used"] == 42
        assert prov["validation"] == {"ok": True, "residual_max": 0.4}
        json.dumps(prov)  # must be serializable

    def test_none_validation_and_none_summary_ok(self):
        prov = build_provenance(
            laps_used=0, grip_confidence_summary=None, geometry_gates_version=None,
            solver_name="x", solver_version=None, validation=None,
        )
        assert prov["grip_confidence_summary"] == {}
        assert prov["validation"] is None
        json.dumps(prov)
