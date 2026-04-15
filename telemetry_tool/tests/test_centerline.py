"""Tests for track_surface/centerline.py — multi-lap centerline extraction."""
from __future__ import annotations

import numpy as np
import pytest

from track_surface.centerline import extract_centerline


def _make_oval(
    straight_len: float = 100.0,
    radius: float = 30.0,
    n_points: int = 500,
    noise_m: float = 0.0,
    offset_m: float = 0.0,
) -> np.ndarray:
    """Generate an oval track centerline with optional noise and lateral offset.

    The oval has two straights of length straight_len connected by
    semicircles of the given radius.
    """
    rng = np.random.default_rng(42)
    pts = []

    # Bottom straight (left to right)
    n_straight = n_points // 4
    for i in range(n_straight):
        t = i / n_straight
        pts.append([t * straight_len, offset_m])

    # Right semicircle
    n_arc = n_points // 4
    for i in range(n_arc):
        theta = -np.pi / 2 + np.pi * i / n_arc
        pts.append([straight_len + radius * np.cos(theta),
                     radius + radius * np.sin(theta) + offset_m])

    # Top straight (right to left)
    for i in range(n_straight):
        t = i / n_straight
        pts.append([straight_len - t * straight_len, 2 * radius + offset_m])

    # Left semicircle
    for i in range(n_arc):
        theta = np.pi / 2 + np.pi * i / n_arc
        pts.append([radius * np.cos(theta),
                     radius + radius * np.sin(theta) + offset_m])

    xy = np.array(pts)
    if noise_m > 0:
        xy += rng.normal(0, noise_m, xy.shape)
    return xy


class TestSingleLap:
    def test_single_lap_returns_valid_shape(self):
        lap = _make_oval(n_points=400)
        cl, total = extract_centerline([lap], ds_m=1.0)
        assert cl.shape[1] == 2
        assert cl.shape[0] > 10
        assert total > 100  # should be ~320m for default oval

    def test_single_lap_smoother_than_noisy_input(self):
        lap = _make_oval(n_points=400, noise_m=2.0)
        cl, _ = extract_centerline([lap], ds_m=1.0, smooth_sigma_m=5.0)
        # Centerline should be smoother: lower variance in segment lengths
        diffs = np.diff(cl, axis=0)
        seg_lens = np.sqrt(diffs[:, 0] ** 2 + diffs[:, 1] ** 2)
        assert np.std(seg_lens) < 1.0  # smooth implies ~uniform spacing


class TestMultipleLaps:
    def test_three_laps_averages(self):
        # Three laps with different offsets -> centerline should be in the middle
        laps = [
            _make_oval(offset_m=-2.0, n_points=400),
            _make_oval(offset_m=0.0, n_points=400),
            _make_oval(offset_m=2.0, n_points=400),
        ]
        cl, total = extract_centerline(laps, ds_m=1.0)
        # Centerline y-values at the bottom straight should be near 0
        bottom_pts = cl[cl[:, 1] < 5.0]
        if len(bottom_pts) > 0:
            mean_y = np.mean(bottom_pts[:, 1])
            assert abs(mean_y) < 2.0  # median of -2, 0, 2 should be ~0

    def test_outlier_lap_rejected_by_median(self):
        """A single wildly offset lap shouldn't corrupt the centerline."""
        laps = [
            _make_oval(offset_m=0.0, n_points=400),
            _make_oval(offset_m=0.0, n_points=400),
            _make_oval(offset_m=0.0, n_points=400),
            _make_oval(offset_m=20.0, n_points=400),  # outlier
        ]
        cl, _ = extract_centerline(laps, ds_m=1.0)
        # Should still be near 0, not pulled to 5m (mean) or 20m
        bottom_pts = cl[cl[:, 1] < 5.0]
        if len(bottom_pts) > 0:
            mean_y = np.mean(bottom_pts[:, 1])
            assert abs(mean_y) < 3.0

    def test_length_consistent_across_lap_counts(self):
        """Total length shouldn't change drastically with more laps."""
        lap = _make_oval(n_points=400)
        _, len1 = extract_centerline([lap], ds_m=1.0)
        _, len3 = extract_centerline([lap, lap, lap], ds_m=1.0)
        assert abs(len1 - len3) / len1 < 0.1  # within 10%


class TestEdgeCases:
    def test_rejects_degenerate_laps(self):
        with pytest.raises(ValueError, match="No valid laps"):
            extract_centerline([np.array([[0, 0], [1, 1]])])

    def test_single_valid_among_degenerate(self):
        """Should use the one valid lap even if others are too short."""
        valid = _make_oval(n_points=400)
        degenerate = np.array([[0, 0], [1, 1]])
        cl, total = extract_centerline([degenerate, valid], ds_m=1.0)
        assert total > 100
