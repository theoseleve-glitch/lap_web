"""Tests for per-label confidence in `classify_all_corners` (yaw-residual honesty gate).

Phase 2 of LAP coaching promotes the corner-diagnosis classifier to drive drill
selection. Its under/oversteer labels come from a yaw-residual computation that is
unreliable without a real curvature profile, or on a tier that lacks a physical
yaw-corroboration channel (e.g. a corrupt-gyro kart, bearing-only GPS tier). This
module verifies the `{"label": ..., "confidence": "high"|"low"}` cell shape and the
exact confidence rule.

Spec: docs/superpowers/specs/2026-03-12-corner-diagnosis-design.md
Brief: coach-sdd/p2-task-1-brief.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from coaching.corner_diagnosis import (
    _YAW_RESIDUAL_LABELS,
    _tier_has_reliable_yaw,
    classify_all_corners,
)

# Reuse the real synthetic-lap builders from the main classifier test suite
# (tests/test_corner_diagnosis.py) instead of inventing new lap data. Import by
# inserting the sibling `tests/` dir directly on sys.path and pulling the bare
# module name -- this worktree has an UNRELATED top-level `tests/` package at
# the repo root that shadows `tests.test_corner_diagnosis` when pytest's own
# package-walk resolves this file's dotted module name, so a plain
# `from tests.test_corner_diagnosis import ...` resolves to the wrong package.
_TESTS_DIR = str(Path(__file__).resolve().parent.parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from test_corner_diagnosis import _make_corner, _make_curvature_profile, _make_lap_df  # noqa: E402


def _make_yaw_heavy_lap_df(
    n=100, s_start=50.0, s_end=150.0, turn_end_m=75.0,
    total_angle_rad=np.pi / 6, speed_mps=25.0, has_accel=False,
):
    """Build a lap whose heading turns sharply over [s_start, turn_end_m] then
    goes flat for the remainder of the segment.

    Because the heading change is concentrated early rather than uniform across
    the whole segment, the "no curvature profile" fallback in
    `_compute_yaw_residual` (which assumes uniform curvature derived from the
    segment's total heading change) badly under-estimates the true turn-in rate.
    That produces a strong, sustained positive yaw residual in the entry zone
    which reliably classifies as `entry_oversteer` -- a real yaw-residual label,
    not a hand-waved one.
    """
    dist = np.linspace(s_start, s_end, n)
    heading = np.where(
        dist <= turn_end_m,
        total_angle_rad * (dist - s_start) / (turn_end_m - s_start),
        total_angle_rad,
    )
    speed = np.full(n, speed_mps)
    data = {
        "Distance (m)": dist,
        "Speed (m/s)": speed,
        "Heading (rad)": heading,
    }
    if has_accel:
        # Constant speed -> ~zero longitudinal accel, so no late_braking confound.
        data["accel_long_mps2"] = np.zeros(n)
        data["accel_lat_mps2"] = np.full(n, 0.5 * 9.81)
    return pd.DataFrame(data)


class TestPerLabelConfidenceShape:
    """The cell shape contract: {"label": str|None, "confidence": "high"|"low"}."""

    def test_cell_is_dict_with_label_and_confidence_keys(self):
        lap_df = _make_lap_df(v_entry_mps=30.0, v_min_mps=20.0, v_exit_mps=28.0)
        corner = _make_corner(s_entry=50.0, s_apex=100.0, s_exit=150.0, corner_index=1)
        theo = _make_lap_df(v_entry_mps=30.0, v_min_mps=20.0, v_exit_mps=28.0)

        out = classify_all_corners(
            resampled_laps={2: lap_df},
            theoretical_lap=theo,
            user_corners=[corner],
            vehicle_class="car",
            valid_lap_numbers=[2],
        )
        cell = out["2"]["1"]
        assert set(cell) >= {"label", "confidence"}
        assert cell["confidence"] in ("high", "low")

    def test_none_metrics_cell_is_low_confidence_dict(self):
        # Corner entirely outside the lap's distance range -> metrics extraction fails.
        lap_df = _make_lap_df(s_start=50.0, s_end=150.0)
        corner = _make_corner(s_entry=500.0, s_apex=550.0, s_exit=600.0, corner_index=1)

        out = classify_all_corners(
            resampled_laps={2: lap_df},
            theoretical_lap=None,
            user_corners=[corner],
            vehicle_class="car",
            valid_lap_numbers=[2],
        )
        cell = out["2"]["1"]
        assert cell == {"label": None, "confidence": "low"}


class TestYawResidualConfidenceRule:
    """Confidence is low for yaw-residual labels without a trustworthy yaw source."""

    def test_yaw_label_low_confidence_without_curvature(self):
        lap_df = _make_yaw_heavy_lap_df()  # no accel/pedal cols -> tier == "gps"
        corner = _make_corner(s_entry=50.0, s_apex=100.0, s_exit=150.0, corner_index=1)

        out = classify_all_corners(
            resampled_laps={2: lap_df},
            theoretical_lap=None,
            user_corners=[corner],
            vehicle_class="car",
            valid_lap_numbers=[2],
            curvature_profile=None,
        )
        cell = out["2"]["1"]
        assert set(cell) >= {"label", "confidence"}
        # Sanity: the scenario really is yaw-residual driven, not some other label.
        assert cell["label"] in _YAW_RESIDUAL_LABELS
        assert cell["confidence"] == "low"

    def test_yaw_label_low_confidence_on_unreliable_tier_even_with_curvature(self):
        """GPS tier (bearing-derived yaw, no accel corroboration) stays low-confidence
        even when a curvature profile IS supplied.
        """
        lap_df = _make_yaw_heavy_lap_df()  # tier == "gps"
        corner = _make_corner(s_entry=50.0, s_apex=100.0, s_exit=150.0, corner_index=1)
        curvature = _make_curvature_profile(s_start=0.0, s_end=200.0)

        out = classify_all_corners(
            resampled_laps={2: lap_df},
            theoretical_lap=None,
            user_corners=[corner],
            vehicle_class="car",
            valid_lap_numbers=[2],
            curvature_profile=curvature,
        )
        cell = out["2"]["1"]
        assert cell["label"] in _YAW_RESIDUAL_LABELS
        assert cell["confidence"] == "low"
        assert _tier_has_reliable_yaw("gps") is False

    def test_yaw_label_high_confidence_with_curvature_and_reliable_tier(self):
        lap_df = _make_yaw_heavy_lap_df(has_accel=True)  # accel cols -> tier == "accel"
        corner = _make_corner(s_entry=50.0, s_apex=100.0, s_exit=150.0, corner_index=1)
        curvature = _make_curvature_profile(s_start=0.0, s_end=200.0)

        out = classify_all_corners(
            resampled_laps={2: lap_df},
            theoretical_lap=None,
            user_corners=[corner],
            vehicle_class="car",
            valid_lap_numbers=[2],
            curvature_profile=curvature,
        )
        cell = out["2"]["1"]
        assert cell["label"] in _YAW_RESIDUAL_LABELS
        assert cell["confidence"] == "high"
        assert _tier_has_reliable_yaw("accel") is True

    def test_non_yaw_label_is_high_confidence(self):
        # Reuse the main suite's verified entry_overspeed scenario (non-yaw dominant label).
        lap_df_fast = _make_lap_df(v_entry_mps=33.0, v_min_mps=20.0, v_exit_mps=28.0)
        theo = _make_lap_df(v_entry_mps=30.0, v_min_mps=20.0, v_exit_mps=28.0)
        corner = _make_corner(s_entry=50.0, s_apex=100.0, s_exit=150.0, corner_index=1)

        out = classify_all_corners(
            resampled_laps={2: lap_df_fast},
            theoretical_lap=theo,
            user_corners=[corner],
            vehicle_class="car",
            valid_lap_numbers=[2],
            curvature_profile=None,
        )
        cell = out["2"]["1"]
        assert cell["label"] == "entry_overspeed"
        assert cell["label"] not in _YAW_RESIDUAL_LABELS
        assert cell["confidence"] == "high"
