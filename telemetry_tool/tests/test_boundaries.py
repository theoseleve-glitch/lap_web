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
    """Create a straight reference line along the X axis."""
    dist = np.linspace(0, length_m, n_points)
    return pd.DataFrame({
        "Distance (m)": dist,
        "X (m)": dist,
        "Y (m)": np.zeros(n_points),
    })


def _make_lap(ref_line: pd.DataFrame, y_offset: float = 0.0) -> pd.DataFrame:
    """Create a lap DataFrame offset laterally from the reference line."""
    return pd.DataFrame({
        "Distance (m)": ref_line["Distance (m)"].values.copy(),
        "X (m)": ref_line["X (m)"].values.copy(),
        "Y (m)": ref_line["Y (m)"].values + y_offset,
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
