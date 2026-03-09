"""Tests for raceline optimizer: line variants and point-mass simulation."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from raceline_optimizer import (
    LineVariant,
    RacelineResult,
    generate_line_variants,
    optimize_corner_lines,
    simulate_variant_time,
)


class TestLineVariant:
    def test_to_dict(self):
        lv = LineVariant(
            variant_id="C3_late_apex", corner_id=3, apex_type="late",
            offset_profile_m=[0, 1, 2, 1, 0], estimated_time_s=2.5,
            delta_vs_baseline_s=-0.05, constraints_hit=[],
        )
        d = lv.to_dict()
        assert d["apex_type"] == "late"
        assert d["corner_id"] == 3


class TestRacelineResult:
    def test_to_dict(self):
        rr = RacelineResult(corner_results={}, total_delta_s=0.0, n_variants_evaluated=0)
        d = rr.to_dict()
        assert "total_delta_s" in d


class TestGenerateLineVariants:
    def test_generates_3_variants(self):
        corner = {"corner_id": 1, "entry_s": 100, "apex_s": 150, "exit_s": 200}
        ref_dist = np.linspace(0, 500, 100)
        ref_line = {"distance_m": ref_dist, "curvature": np.sin(ref_dist / 50) * 0.01}
        boundaries = {
            "left_offset_m": np.ones(100) * 5,
            "right_offset_m": np.ones(100) * -5,
            "distance_m": ref_dist,
        }
        variants = generate_line_variants(corner, ref_line, boundaries, n_variants=3)
        assert len(variants) == 3
        apex_types = {v.apex_type for v in variants}
        assert "early" in apex_types
        assert "neutral" in apex_types
        assert "late" in apex_types

    def test_short_corner_returns_empty(self):
        corner = {"corner_id": 1, "entry_s": 100, "exit_s": 101}
        ref_dist = np.linspace(0, 500, 100)
        ref_line = {"distance_m": ref_dist, "curvature": np.zeros(100)}
        boundaries = {
            "left_offset_m": np.ones(100) * 5,
            "right_offset_m": np.ones(100) * -5,
            "distance_m": ref_dist,
        }
        variants = generate_line_variants(corner, ref_line, boundaries)
        assert len(variants) == 0


class TestSimulateVariantTime:
    def test_higher_curvature_slower(self):
        low_curv = np.ones(50) * 0.005
        high_curv = np.ones(50) * 0.02
        t_low = simulate_variant_time(low_curv, entry_speed=25.0, friction_mu=1.2)
        t_high = simulate_variant_time(high_curv, entry_speed=25.0, friction_mu=1.2)
        assert t_high > t_low

    def test_positive_time(self):
        curv = np.ones(30) * 0.01
        t = simulate_variant_time(curv, entry_speed=20.0, friction_mu=1.0)
        assert t > 0

    def test_empty_profile(self):
        t = simulate_variant_time(np.array([]), entry_speed=20.0, friction_mu=1.0)
        assert t == 0.0


class TestOptimizeCornerLines:
    def test_toy_track(self):
        corners = [{"corner_id": 1, "entry_s": 100, "apex_s": 150, "exit_s": 200}]
        ref_dist = np.linspace(0, 500, 100)
        ref_line = {"distance_m": ref_dist, "curvature": np.sin(ref_dist / 50) * 0.01}
        boundaries = {
            "left_offset_m": np.ones(100) * 5,
            "right_offset_m": np.ones(100) * -5,
            "distance_m": ref_dist,
        }
        result = optimize_corner_lines(corners, ref_line, boundaries, {"mu": 1.2})
        assert isinstance(result, RacelineResult)
        assert result.n_variants_evaluated > 0

    def test_empty_corners(self):
        result = optimize_corner_lines([], {}, {}, {"mu": 1.2})
        assert result.n_variants_evaluated == 0
