"""Tests for lap_oracle.track -- model construction and extraction."""
from __future__ import annotations

import numpy as np
import pytest

from telemetry_tool.lap_oracle.track.model import build_from_xy, resample_track
from telemetry_tool.lap_oracle.track.extractor import extract_from_telemetry_xy


# -- Helpers -------------------------------------------------------------

def _make_oval(n: int = 200, a: float = 200.0, b: float = 100.0) -> np.ndarray:
    """Return (n, 2) oval centerline with semi-axes *a* and *b*."""
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    x = a * np.cos(t)
    y = b * np.sin(t)
    return np.column_stack((x, y))


# -- build_from_xy -------------------------------------------------------

class TestBuildFromXY:
    def test_oval_n_points(self):
        xy = _make_oval(200)
        tm = build_from_xy(xy, name="oval")
        assert tm.n_points == 200

    def test_oval_total_length(self):
        xy = _make_oval(200, a=200, b=100)
        tm = build_from_xy(xy)
        # Ellipse perimeter with a=200, b=100 is roughly 960 m
        assert tm.total_length_m > 800

    def test_curvature_nonzero(self):
        xy = _make_oval(200)
        tm = build_from_xy(xy)
        assert np.any(tm.curvature != 0.0)

    def test_curvature_signs_oval(self):
        """On a CCW oval, curvature should be predominantly one sign."""
        xy = _make_oval(200)
        tm = build_from_xy(xy)
        # For a standard CCW ellipse the curvature should be mostly negative
        # (or mostly positive depending on convention).  Just check that the
        # majority share the same sign.
        pos = np.sum(tm.curvature > 0)
        neg = np.sum(tm.curvature < 0)
        dominant = max(pos, neg)
        assert dominant > 0.8 * tm.n_points

    def test_uniform_width(self):
        xy = _make_oval(50)
        tm = build_from_xy(xy, width=7.0)
        assert np.allclose(tm.width_left, 7.0)
        assert np.allclose(tm.width_right, 7.0)

    def test_elevation_zero(self):
        xy = _make_oval(50)
        tm = build_from_xy(xy)
        assert np.allclose(tm.elevation, 0.0)

    def test_banking_zero(self):
        xy = _make_oval(50)
        tm = build_from_xy(xy)
        assert np.allclose(tm.banking, 0.0)

    def test_grip_map_ones(self):
        xy = _make_oval(50)
        tm = build_from_xy(xy)
        assert np.allclose(tm.grip_map, 1.0)

    def test_name_and_sim(self):
        xy = _make_oval(50)
        tm = build_from_xy(xy, name="monza", sim="ac")
        assert tm.name == "monza"
        assert tm.sim == "ac"

    def test_too_few_points_raises(self):
        xy = np.column_stack((np.arange(5), np.arange(5)))
        with pytest.raises(ValueError, match="at least 10"):
            build_from_xy(xy)

    def test_bad_shape_raises(self):
        xy = np.zeros((20, 3))
        with pytest.raises(ValueError, match="Expected.*\\(N, 2\\)"):
            build_from_xy(xy)


# -- resample_track ------------------------------------------------------

class TestResampleTrack:
    def test_uniform_spacing(self):
        xy = _make_oval(200)
        tm = build_from_xy(xy)
        resampled = resample_track(tm, ds_target=5.0)
        ds = resampled.ds
        assert ds.size > 0
        cv = np.std(ds) / np.mean(ds)
        assert cv < 0.1, f"Spacing CV = {cv:.3f}, expected < 0.1"

    def test_preserves_name_sim(self):
        xy = _make_oval(200)
        tm = build_from_xy(xy, name="test_track", sim="ac")
        resampled = resample_track(tm, ds_target=5.0)
        assert resampled.name == "test_track"
        assert resampled.sim == "ac"

    def test_total_length_close(self):
        xy = _make_oval(200)
        tm = build_from_xy(xy)
        resampled = resample_track(tm, ds_target=2.0)
        # Resampled length should be within 1% of original
        assert abs(resampled.total_length_m - tm.total_length_m) / tm.total_length_m < 0.01


# -- extract_from_telemetry_xy -------------------------------------------

class TestExtractFromTelemetryXY:
    def test_works_with_n2(self):
        xy = _make_oval(100)
        tm = extract_from_telemetry_xy(xy, name="telem", sim="rc")
        assert tm is not None
        assert tm.n_points == 100

    def test_works_with_n3(self):
        xy3 = np.column_stack((_make_oval(100), np.zeros(100)))
        tm = extract_from_telemetry_xy(xy3)
        assert tm is not None
        assert tm.n_points == 100

    def test_returns_none_too_few(self):
        xy = _make_oval(15)
        result = extract_from_telemetry_xy(xy)
        assert result is None

    def test_returns_none_1d(self):
        result = extract_from_telemetry_xy(np.arange(10))
        assert result is None
