"""Phase-F unit tests — cyclic B-spline + curvature regularization +
arclength reparameterization."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TELEMETRY_PKG = _REPO_ROOT / "telemetry_tool"
for _p in (_REPO_ROOT, _TELEMETRY_PKG):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from track_surface.centerline import (  # noqa: E402
    ArclengthCenterline,
    ClosedSplineFit,
    fit_closed_spline_with_curvature_target,
    reparameterize_by_arclength,
)


def _circle_points(radius: float, n: int) -> np.ndarray:
    theta = np.linspace(0.0, 2 * np.pi, n, endpoint=False)
    return np.column_stack([radius * np.cos(theta), radius * np.sin(theta)])


def test_fit_closed_spline_on_clean_circle():
    """A noise-free circle should fit with kappa_max ≈ 1/r within a
    few % and tiny RMS deviation."""
    pts = _circle_points(10.0, 200)
    fit = fit_closed_spline_with_curvature_target(pts, kappa_max_target=0.2)
    assert isinstance(fit, ClosedSplineFit)
    assert fit.kappa_max <= 0.2 + 1e-9
    # Curvature should be close to 1/r = 0.1
    assert abs(fit.kappa_max - 0.1) < 0.02, \
        f"kappa_max {fit.kappa_max:.4f} far from theoretical 0.1 for r=10 circle"
    assert fit.rms_deviation < 0.1, \
        f"clean-circle RMS deviation {fit.rms_deviation:.4f} m unexpectedly large"


def test_fit_closed_spline_smooths_noisy_circle():
    """Add gaussian noise (σ=0.2 m) to circle samples; smoothing must
    bring kappa_max under target by increasing s."""
    rng = np.random.default_rng(seed=42)
    pts = _circle_points(10.0, 400) + rng.normal(scale=0.2, size=(400, 2))
    fit = fit_closed_spline_with_curvature_target(pts, kappa_max_target=0.2)
    assert fit.kappa_max <= 0.25  # within the hard cap


def test_reparameterize_circle_total_length():
    """ArclengthCenterline.total_length matches 2pi*r within 0.1 %."""
    pts = _circle_points(10.0, 200)
    fit = fit_closed_spline_with_curvature_target(pts, kappa_max_target=0.2)
    cl = reparameterize_by_arclength(fit)

    expected = 2 * np.pi * 10.0
    assert abs(cl.total_length - expected) / expected < 0.001, \
        f"total_length {cl.total_length:.4f} differs from {expected:.4f} by >0.1%"


def test_arclength_centerline_sample_and_tangent_and_normal():
    pts = _circle_points(10.0, 400)
    fit = fit_closed_spline_with_curvature_target(pts, kappa_max_target=0.2)
    cl = reparameterize_by_arclength(fit)

    # At s=0 we should be at approximately (10, 0)
    xy0 = cl.sample(0.0)
    assert xy0.shape == (1, 2)
    assert abs(xy0[0, 0] - 10.0) < 0.05
    assert abs(xy0[0, 1]) < 0.05

    # Tangent at s=0: circle traced CCW from (10, 0) → tangent ≈ (0, 1)
    t0 = cl.tangent(0.0)
    assert t0.shape == (1, 2)
    assert abs(t0[0, 0]) < 0.05
    assert abs(t0[0, 1] - 1.0) < 0.05

    # Normal at s=0: LEFT-pointing → 90° CCW of tangent → (-1, 0)
    n0 = cl.normal(0.0)
    assert n0.shape == (1, 2)
    assert abs(n0[0, 0] + 1.0) < 0.05
    assert abs(n0[0, 1]) < 0.05


def test_arclength_centerline_kappa_constant_for_circle():
    pts = _circle_points(10.0, 400)
    fit = fit_closed_spline_with_curvature_target(pts, kappa_max_target=0.2)
    cl = reparameterize_by_arclength(fit)

    s_vals = np.linspace(0.0, cl.total_length, 100, endpoint=False)
    k = cl.kappa(s_vals)
    # All kappa values should be close to 1/r = 0.1 with the same sign
    # (CCW traced ⇒ positive signed curvature)
    assert np.all(np.abs(k - 0.1) < 0.02), \
        f"circle kappa range [{k.min():.4f}, {k.max():.4f}] not within 0.08-0.12"


def test_reparameterize_wraps_around_arclength():
    """Sampling at s = total_length should wrap to s = 0 cleanly."""
    pts = _circle_points(10.0, 200)
    fit = fit_closed_spline_with_curvature_target(pts, kappa_max_target=0.2)
    cl = reparameterize_by_arclength(fit)

    xy0 = cl.sample(0.0)
    xy_wrap = cl.sample(cl.total_length)
    assert np.allclose(xy0, xy_wrap, atol=0.05), \
        f"s=0 = {xy0} disagrees with s=total = {xy_wrap}"


def test_fit_with_corner_well_below_target():
    """A rounded rectangle with corner_r = 8 m → true kappa = 0.125
    at corners (well below the 0.2 target). After smoothing, the
    cubic-B-spline overshoot at corners must still stay under the
    0.2 target without needing the hard-cap fallback."""
    seg = []
    straight_m = 30.0
    corner_r_m = 8.0  # → kappa = 0.125 << 0.2 target
    pts_per_segment = 50

    half = straight_m / 2 + corner_r_m
    xs = np.linspace(-half + corner_r_m, half - corner_r_m, pts_per_segment)
    seg.append(np.column_stack([xs, np.full_like(xs, -half)]))
    th = np.linspace(-np.pi / 2, 0.0, pts_per_segment, endpoint=False)
    cx, cy = half - corner_r_m, -half + corner_r_m
    seg.append(np.column_stack([cx + corner_r_m * np.cos(th), cy + corner_r_m * np.sin(th)]))
    ys = np.linspace(-half + corner_r_m, half - corner_r_m, pts_per_segment)
    seg.append(np.column_stack([np.full_like(ys, half), ys]))
    th = np.linspace(0.0, np.pi / 2, pts_per_segment, endpoint=False)
    cx, cy = half - corner_r_m, half - corner_r_m
    seg.append(np.column_stack([cx + corner_r_m * np.cos(th), cy + corner_r_m * np.sin(th)]))
    xs = np.linspace(half - corner_r_m, -half + corner_r_m, pts_per_segment)
    seg.append(np.column_stack([xs, np.full_like(xs, half)]))
    th = np.linspace(np.pi / 2, np.pi, pts_per_segment, endpoint=False)
    cx, cy = -half + corner_r_m, half - corner_r_m
    seg.append(np.column_stack([cx + corner_r_m * np.cos(th), cy + corner_r_m * np.sin(th)]))
    ys = np.linspace(half - corner_r_m, -half + corner_r_m, pts_per_segment)
    seg.append(np.column_stack([np.full_like(ys, -half), ys]))
    th = np.linspace(np.pi, 3 * np.pi / 2, pts_per_segment, endpoint=False)
    cx, cy = -half + corner_r_m, -half + corner_r_m
    seg.append(np.column_stack([cx + corner_r_m * np.cos(th), cy + corner_r_m * np.sin(th)]))
    pts = np.vstack(seg)

    fit = fit_closed_spline_with_curvature_target(pts, kappa_max_target=0.2)
    assert fit.kappa_max <= 0.2 + 1e-9, \
        f"kappa_max {fit.kappa_max:.4f} exceeds 0.2 target on r=8m corners"
