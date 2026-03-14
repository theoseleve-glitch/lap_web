"""Tests for per-corner QSS solver and actionable generation."""
import numpy as np
import pytest

from kart_envelope.solver.corner_solver import (
    solve_corner_qss,
    CornerOCPResult,
    CornerActionable,
    generate_actionables,
)


# ── QSS solver tests ────────────────────────────────────────────


class TestSolveCornerQSS:
    def test_hairpin_produces_speed_dip(self):
        """A tight hairpin should produce a speed dip at the apex."""
        n = 50
        distances = np.linspace(0, 100, n)
        curvature = np.zeros(n)
        curvature[15:35] = 0.05  # tight hairpin, radius ~20m

        result = solve_corner_qss(
            curvature=curvature,
            distances=distances,
            mu=1.0,
            v_entry=20.0,
            v_exit=20.0,
        )

        assert isinstance(result, CornerOCPResult)
        assert len(result.speeds) == n
        # Apex speed must be slower than boundary speeds
        assert result.optimal_apex_speed < 20.0
        assert result.optimal_time_s > 0

    def test_straight_maintains_speed(self):
        """A straight should accelerate from entry to exit."""
        n = 30
        distances = np.linspace(0, 50, n)
        curvature = np.zeros(n)

        result = solve_corner_qss(
            curvature=curvature,
            distances=distances,
            mu=1.2,
            v_entry=15.0,
            v_exit=25.0,
        )

        assert result.speeds[-1] >= result.speeds[0] - 0.1
        assert result.optimal_time_s > 0

    def test_respects_entry_boundary(self):
        """Speed at index 0 should not exceed v_entry."""
        distances = np.linspace(0, 80, 40)
        curvature = np.zeros(40)
        curvature[10:30] = 0.015

        result = solve_corner_qss(
            curvature=curvature, distances=distances,
            mu=1.0, v_entry=18.0, v_exit=18.0,
        )

        assert result.speeds[0] <= 18.0 + 0.01

    def test_respects_exit_boundary(self):
        """Speed at last index should not exceed v_exit."""
        distances = np.linspace(0, 80, 40)
        curvature = np.zeros(40)
        curvature[10:30] = 0.015

        result = solve_corner_qss(
            curvature=curvature, distances=distances,
            mu=1.0, v_entry=22.0, v_exit=16.0,
        )

        assert result.speeds[-1] <= 16.0 + 0.01

    def test_higher_friction_faster_apex(self):
        """Higher mu should allow faster apex speed."""
        n = 50
        distances = np.linspace(0, 100, n)
        curvature = np.zeros(n)
        curvature[15:35] = 0.02

        low_mu = solve_corner_qss(curvature=curvature, distances=distances, mu=0.8, v_entry=20.0, v_exit=20.0)
        high_mu = solve_corner_qss(curvature=curvature, distances=distances, mu=1.5, v_entry=20.0, v_exit=20.0)

        assert high_mu.optimal_apex_speed > low_mu.optimal_apex_speed

    def test_tighter_corner_slower_apex(self):
        """Higher curvature should produce slower apex."""
        n = 50
        distances = np.linspace(0, 100, n)

        mild = np.zeros(n)
        mild[15:35] = 0.01  # radius ~100m

        tight = np.zeros(n)
        tight[15:35] = 0.04  # radius ~25m

        r_mild = solve_corner_qss(curvature=mild, distances=distances, mu=1.2, v_entry=20.0, v_exit=20.0)
        r_tight = solve_corner_qss(curvature=tight, distances=distances, mu=1.2, v_entry=20.0, v_exit=20.0)

        assert r_tight.optimal_apex_speed < r_mild.optimal_apex_speed

    def test_to_dict_serialization(self):
        """to_dict() should produce a JSON-compatible dict."""
        distances = np.linspace(0, 50, 20)
        curvature = np.zeros(20)
        curvature[5:15] = 0.02

        result = solve_corner_qss(curvature=curvature, distances=distances, mu=1.2, v_entry=18.0, v_exit=18.0)
        result.corner_id = 3
        d = result.to_dict()

        assert d["corner_id"] == 3
        assert len(d["distances"]) == 20
        assert len(d["optimal_speeds"]) == 20
        assert isinstance(d["optimal_time_s"], float)

    def test_degenerate_2_points(self):
        """Should handle minimum 2-point segment."""
        result = solve_corner_qss(
            curvature=np.array([0.01, 0.01]),
            distances=np.array([0.0, 5.0]),
            mu=1.2, v_entry=15.0, v_exit=15.0,
        )
        assert len(result.speeds) == 2
        assert result.optimal_time_s > 0


# ── Actionable generation tests ─────────────────────────────────


class TestGenerateActionables:
    def _make_ocp(self, **overrides) -> CornerOCPResult:
        defaults = dict(
            corner_id=1, distances=[0, 50, 100], speeds=[20, 14, 18],
            optimal_apex_speed=14.0, optimal_entry_speed=20.0, optimal_exit_speed=18.0,
            optimal_time_s=5.0,
            actual_apex_speed=12.0, actual_entry_speed=18.0, actual_exit_speed=16.0,
            actual_time_s=5.5,
            time_delta_s=0.5, speed_delta_apex=-2.0,
        )
        defaults.update(overrides)
        return CornerOCPResult(**defaults)

    def test_always_returns_3(self):
        ocp = self._make_ocp()
        result = generate_actionables(ocp, corner_length_m=100.0)
        assert len(result) == 3

    def test_ranked_by_impact(self):
        ocp = self._make_ocp()
        result = generate_actionables(ocp, corner_length_m=100.0)
        assert result[0].rank == 1
        assert result[1].rank == 2
        assert result[2].rank == 3
        assert result[0].impact_ms >= result[1].impact_ms

    def test_actions_are_concrete(self):
        ocp = self._make_ocp()
        result = generate_actionables(
            ocp,
            actual_brake_dist=40.0, optimal_brake_dist=45.0,
            actual_throttle_dist=62.0, optimal_throttle_dist=55.0,
            corner_length_m=100.0,
        )
        for a in result:
            if a.impact_ms > 0:
                assert any(c.isdigit() for c in a.action), f"Not concrete: {a.action}"

    def test_valid_categories(self):
        ocp = self._make_ocp()
        result = generate_actionables(ocp, corner_length_m=100.0)
        valid = {"braking", "apex_speed", "exit_traction", "entry_speed", "trail_brake", "line"}
        for a in result:
            assert a.category in valid

    def test_valid_phases(self):
        ocp = self._make_ocp()
        result = generate_actionables(ocp, corner_length_m=100.0)
        for a in result:
            assert a.phase in {"entry", "mid", "exit"}

    def test_pads_when_few_candidates(self):
        """When driver is near-perfect, should still return 3 (padded)."""
        ocp = self._make_ocp(
            actual_apex_speed=13.9, actual_entry_speed=19.9, actual_exit_speed=17.9,
        )
        result = generate_actionables(ocp, corner_length_m=100.0)
        assert len(result) == 3

    def test_brake_point_actionable(self):
        # Use near-identical speeds so braking is the top actionable
        ocp = self._make_ocp(
            actual_apex_speed=13.9, actual_entry_speed=19.9, actual_exit_speed=17.9,
        )
        result = generate_actionables(
            ocp, actual_brake_dist=25.0, optimal_brake_dist=45.0,
            corner_length_m=100.0,
        )
        braking = [a for a in result if a.category == "braking"]
        assert len(braking) >= 1
        assert "20m" in braking[0].action  # 45 - 25 = 20m
