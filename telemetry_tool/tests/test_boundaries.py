"""Tests for TrackBoundaries dataclass and estimate_track_boundaries()."""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from telemetry_tool.reference_line import (
    TrackBoundaries,
    estimate_track_boundaries,
)


def _make_ref_line(n_points: int = 100, length_m: float = 500.0) -> pd.DataFrame:
    """Create a straight reference line along the X axis.

    Columns mirror what compute_reference_line() actually produces:
    snake_case OUT_* names (distance_m, x_ref_m, y_ref_m), NOT the
    RaceChrono _COL_* names used inside resampled_laps DataFrames.
    """
    dist = np.linspace(0, length_m, n_points)
    return pd.DataFrame({
        "distance_m": dist,
        "x_ref_m": dist,
        "y_ref_m": np.zeros(n_points),
    })


def _make_lap(ref_line: pd.DataFrame, y_offset: float = 0.0) -> pd.DataFrame:
    """Create a lap DataFrame offset laterally from the reference line.

    Lap DataFrames use RaceChrono _COL_* names ("Distance (m)", "X (m)",
    "Y (m)") regardless of the ref_line schema, mirroring what the real
    pipeline feeds estimate_track_boundaries via resampled_laps.
    """
    return pd.DataFrame({
        "Distance (m)": ref_line["distance_m"].values.copy(),
        "X (m)": ref_line["x_ref_m"].values.copy(),
        "Y (m)": ref_line["y_ref_m"].values + y_offset,
    })


class TestTrackBoundaries:
    def test_dataclass_to_dict(self):
        tb = TrackBoundaries(
            distance_m=np.array([0.0, 1.0, 2.0]),
            left_offset_m=np.array([3.0, 3.0, 3.0]),
            right_offset_m=np.array([-3.0, -3.0, -3.0]),
            confidence=np.array([1.0, 1.0, 1.0]),
            sample_count=np.array([10, 10, 10]),
        )
        d = tb.to_dict()
        assert isinstance(d, dict)
        assert set(d.keys()) == {
            "distance_m",
            "left_offset_m",
            "right_offset_m",
            "confidence",
            "sample_count",
        }
        assert d["distance_m"] == [0.0, 1.0, 2.0]
        assert d["left_offset_m"] == [3.0, 3.0, 3.0]

    def test_width_sanity(self):
        """Interior widths (away from smoothing edges) should be >= min_width_m."""
        ref = _make_ref_line()
        laps = {
            f"lap_{i}": _make_lap(ref, y_offset=0.5 * i)
            for i in range(5)
        }
        result = estimate_track_boundaries(laps, ref)
        assert result is not None
        widths = result.left_offset_m - result.right_offset_m
        # Smoothing kernel (default 15) causes edge roll-off; check interior
        margin = 15
        assert np.all(widths[margin:-margin] >= 4.0 - 1e-9)

    def test_synthetic_scatter(self):
        """10 laps scattered +/-3m -> interior boundaries within [4, 20]m."""
        ref = _make_ref_line()
        rng = np.random.RandomState(42)
        laps = {}
        for i in range(10):
            offset = rng.uniform(-3.0, 3.0)
            laps[f"lap_{i}"] = _make_lap(ref, y_offset=offset)
        result = estimate_track_boundaries(laps, ref)
        assert result is not None
        widths = result.left_offset_m - result.right_offset_m
        # Smoothing kernel causes edge roll-off; check interior
        margin = 15
        assert np.all(widths[margin:-margin] >= 4.0 - 1e-9)
        assert np.all(widths[margin:-margin] <= 20.0 + 1e-9)

    def test_confidence_from_sample_count(self):
        """2 laps -> counts=2 -> confidence = 2/5 = 0.4, between 0 and 1."""
        ref = _make_ref_line()
        laps = {
            "lap_0": _make_lap(ref, y_offset=1.0),
            "lap_1": _make_lap(ref, y_offset=-1.0),
        }
        result = estimate_track_boundaries(laps, ref)
        assert result is not None
        assert np.all(result.confidence >= 0.0)
        assert np.all(result.confidence <= 1.0)
        # With 2 laps, confidence should be 2/5 = 0.4
        assert np.allclose(result.confidence, 0.4, atol=1e-9)

    def test_empty_laps_returns_none(self):
        """An empty dict of laps should return None."""
        ref = _make_ref_line()
        result = estimate_track_boundaries({}, ref)
        assert result is None

    def test_none_ref_line_returns_none(self):
        """A None ref_line should return None rather than raise."""
        ref = _make_ref_line()
        laps = {"lap_0": _make_lap(ref, y_offset=1.0)}
        assert estimate_track_boundaries(laps, None) is None

    def test_empty_ref_line_returns_none(self):
        """An empty ref_line DataFrame should return None rather than raise."""
        ref = _make_ref_line()
        laps = {"lap_0": _make_lap(ref, y_offset=1.0)}
        assert estimate_track_boundaries(laps, pd.DataFrame()) is None

    def test_integrates_with_compute_reference_line(self):
        """Regression: estimate_track_boundaries must accept the schema
        that compute_reference_line() actually produces (snake_case OUT_*).
        Before this test existed, a column-name mismatch caused KeyError
        for every real session — silently swallowed by _safe_step."""
        from telemetry_tool.reference_line import compute_reference_line

        dist = np.linspace(0, 500, 100)

        def make_lap(y_offset):
            return pd.DataFrame({
                "Distance (m)": dist,
                "X (m)": dist,
                "Y (m)": np.full(100, y_offset),
            })

        laps = {1: make_lap(0.5), 2: make_lap(-0.5), 3: make_lap(0.3)}
        ref = compute_reference_line(laps, method="median")
        result = estimate_track_boundaries(laps, ref)
        assert result is not None
        assert len(result.distance_m) == len(ref)
