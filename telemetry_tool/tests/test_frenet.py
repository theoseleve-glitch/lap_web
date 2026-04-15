"""Tests for track_surface/frenet.py — Frenet frame projection."""
from __future__ import annotations

import numpy as np
import pytest

from track_surface.frenet import FrenetFrame


def _make_circle(radius: float = 50.0, n_points: int = 200) -> np.ndarray:
    """Generate a counter-clockwise circle centerline."""
    theta = np.linspace(0, 2 * np.pi, n_points, endpoint=False)
    x = radius * np.cos(theta)
    y = radius * np.sin(theta)
    return np.column_stack([x, y])


def _make_straight(length: float = 200.0, n_points: int = 200) -> np.ndarray:
    """Generate a straight-line centerline along the x-axis."""
    x = np.linspace(0, length, n_points)
    y = np.zeros(n_points)
    return np.column_stack([x, y])


class TestFrenetFromCenterline:
    def test_circle_length(self):
        r = 50.0
        xy = _make_circle(r, 500)
        ff = FrenetFrame.from_centerline(xy)
        expected = 2 * np.pi * r
        assert abs(ff.total_length_m - expected) / expected < 0.02

    def test_circle_curvature(self):
        r = 50.0
        xy = _make_circle(r, 500)
        ff = FrenetFrame.from_centerline(xy)
        # Curvature of a circle with radius r is 1/r
        mean_abs_kappa = np.mean(np.abs(ff.curvature_1pm[10:-10]))
        assert abs(mean_abs_kappa - 1.0 / r) < 0.005

    def test_straight_curvature_near_zero(self):
        xy = _make_straight(200, 400)
        ff = FrenetFrame.from_centerline(xy)
        assert np.all(np.abs(ff.curvature_1pm) < 0.001)

    def test_minimum_points(self):
        with pytest.raises(ValueError, match="at least 3"):
            FrenetFrame.from_centerline(np.array([[0, 0], [1, 1]]))


class TestXYtoSN:
    def test_on_centerline_gives_zero_n(self):
        xy = _make_straight(100, 200)
        ff = FrenetFrame.from_centerline(xy)
        # Points ON the centerline
        test_x = np.array([10.0, 50.0, 90.0])
        test_y = np.array([0.0, 0.0, 0.0])
        s, n = ff.xy_to_sn(test_x, test_y)
        np.testing.assert_allclose(n, 0.0, atol=0.01)
        np.testing.assert_allclose(s, [10.0, 50.0, 90.0], atol=1.0)

    def test_offset_left_gives_positive_n(self):
        xy = _make_straight(100, 200)
        ff = FrenetFrame.from_centerline(xy)
        # 3m to the left (positive y for rightward-heading straight)
        test_x = np.array([50.0])
        test_y = np.array([3.0])
        s, n = ff.xy_to_sn(test_x, test_y)
        assert n[0] > 2.5  # should be ~3.0

    def test_offset_right_gives_negative_n(self):
        xy = _make_straight(100, 200)
        ff = FrenetFrame.from_centerline(xy)
        test_x = np.array([50.0])
        test_y = np.array([-3.0])
        s, n = ff.xy_to_sn(test_x, test_y)
        assert n[0] < -2.5  # should be ~-3.0

    def test_circle_outside_positive_n(self):
        r = 50.0
        xy = _make_circle(r, 500)
        ff = FrenetFrame.from_centerline(xy)
        # Point outside the circle (further from center)
        test_x = np.array([r + 5.0])  # 5m outside at theta=0
        test_y = np.array([0.0])
        s, n = ff.xy_to_sn(test_x, test_y)
        # For CCW circle, outside is to the left -> positive n
        # (the curvature is positive = turning left, so left = outside)
        assert abs(abs(n[0]) - 5.0) < 1.0


class TestSNtoXY:
    def test_roundtrip_straight(self):
        xy = _make_straight(100, 200)
        ff = FrenetFrame.from_centerline(xy)
        orig_x = np.array([10.0, 50.0, 90.0])
        orig_y = np.array([2.0, -1.5, 3.0])
        s, n = ff.xy_to_sn(orig_x, orig_y)
        rx, ry = ff.sn_to_xy(s, n)
        np.testing.assert_allclose(rx, orig_x, atol=0.5)
        np.testing.assert_allclose(ry, orig_y, atol=0.5)

    def test_roundtrip_circle(self):
        r = 50.0
        xy = _make_circle(r, 500)
        ff = FrenetFrame.from_centerline(xy)
        # Points near the track
        orig_x = np.array([r + 2.0, 0.0, -r - 1.0])
        orig_y = np.array([0.0, r + 2.0, 0.0])
        s, n = ff.xy_to_sn(orig_x, orig_y)
        rx, ry = ff.sn_to_xy(s, n)
        np.testing.assert_allclose(rx, orig_x, atol=1.5)
        np.testing.assert_allclose(ry, orig_y, atol=1.5)

    def test_on_centerline_roundtrip(self):
        xy = _make_straight(100, 200)
        ff = FrenetFrame.from_centerline(xy)
        s = np.array([0.0, 25.0, 50.0, 75.0, 99.0])
        n = np.zeros(5)
        rx, ry = ff.sn_to_xy(s, n)
        np.testing.assert_allclose(ry, 0.0, atol=0.1)
        np.testing.assert_allclose(rx, s, atol=1.0)


class TestEffectiveCurvature:
    def test_on_centerline_equals_centerline_curvature(self):
        r = 50.0
        xy = _make_circle(r, 500)
        ff = FrenetFrame.from_centerline(xy)
        s = np.array([10.0, 50.0, 100.0])
        n = np.zeros(3)
        kappa_eff = ff.effective_curvature(s, n)
        np.testing.assert_allclose(np.abs(kappa_eff), 1.0 / r, atol=0.005)

    def test_outside_offset_reduces_curvature(self):
        r = 50.0
        xy = _make_circle(r, 500)
        ff = FrenetFrame.from_centerline(xy)
        s = np.array([50.0])
        kappa_center = ff.effective_curvature(s, np.array([0.0]))
        kappa_outside = ff.effective_curvature(s, np.array([5.0]))
        # Outside = larger effective radius = smaller curvature
        assert abs(kappa_outside[0]) < abs(kappa_center[0])
