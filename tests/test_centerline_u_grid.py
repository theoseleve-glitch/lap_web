"""Phase-D unit tests — u-parameterization + per-u median.

Synthetic 3-circle median should reconstruct the underlying circle to
within 0.1 m even without lap-start alignment, because the symmetric
sampling of a circle makes per-u-bin median stable to phase offsets at
the noise floor.
"""
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
    interpolate_lap_to_u_grid,
    normalize_to_u,
    pointwise_median,
)


def _circle(radius: float, n: int, phi0: float = 0.0) -> np.ndarray:
    theta = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False) + phi0
    return np.column_stack([radius * np.cos(theta), radius * np.sin(theta)])


def test_normalize_to_u_monotonic_and_unit_bounded():
    """With cyclic=True (default), u[-1] = (N-1)/N < 1 for a one-loop
    trace (u=1 wraps back to lap_xy[0])."""
    lap = _circle(radius=10.0, n=500)
    u, lap_clean = normalize_to_u(lap)
    assert lap_clean.shape == lap.shape
    assert u[0] == 0.0
    assert u[-1] < 1.0, f"cyclic normalize_to_u must leave u[-1] < 1; got {u[-1]}"
    assert u[-1] > 0.99  # for a uniformly-sampled circle, ~ (N-1)/N
    assert np.all(np.diff(u) > 0)


def test_normalize_to_u_non_cyclic_u_endpoint_is_one():
    """With cyclic=False, u[-1] == 1 because divisor is the open-path length."""
    lap = _circle(radius=10.0, n=500)
    u, _ = normalize_to_u(lap, cyclic=False)
    assert u[-1] == pytest.approx(1.0)


def test_normalize_to_u_strips_duplicate_samples():
    base = _circle(10.0, 100)
    lap = np.vstack([base[:50], base[49:50], base[50:]])  # one repeated sample
    u, cleaned = normalize_to_u(lap)
    assert cleaned.shape[0] == base.shape[0]
    assert np.all(np.diff(u) > 0)


def test_interpolate_round_trip_circle():
    lap = _circle(10.0, 360)
    u, lap_clean = normalize_to_u(lap)
    u_grid = np.linspace(0.0, 1.0, 720, endpoint=False)
    resampled = interpolate_lap_to_u_grid(u, lap_clean, u_grid)
    # Each resampled point must lie on the circle (radius 10 ± small)
    radii = np.hypot(resampled[:, 0], resampled[:, 1])
    assert np.allclose(radii, 10.0, atol=0.05), \
        f"resampled radii range [{radii.min():.4f}, {radii.max():.4f}] not on r=10"


def test_interpolate_wrap_around_at_seam():
    """u_grid samples at u=0 and u very close to 1 should both fall on
    the circle (no spurious jump across the u=1 seam)."""
    lap = _circle(10.0, 100)
    u, lap_clean = normalize_to_u(lap)
    u_grid = np.array([0.0, 0.001, 0.999])
    resampled = interpolate_lap_to_u_grid(u, lap_clean, u_grid)
    radii = np.hypot(resampled[:, 0], resampled[:, 1])
    assert np.allclose(radii, 10.0, atol=0.1)


def test_small_phase_jitter_median_within_0p1m():
    """Three circles with **small** start-line jitter (1°, 2°) — per-axis
    median *without* lap-start alignment should still be on the circle
    within 0.1 m. Large-offset robustness needs the Phase-E alignment
    step (validated separately)."""
    n = 500
    laps = [_circle(10.0, n, phi0=phi) for phi in (0.0, np.deg2rad(1), np.deg2rad(2))]

    u_grid = np.linspace(0.0, 1.0, 512, endpoint=False)
    grids = []
    for lap in laps:
        u, lap_clean = normalize_to_u(lap)
        grids.append(interpolate_lap_to_u_grid(u, lap_clean, u_grid))

    median_xy = pointwise_median(grids)
    radii = np.hypot(median_xy[:, 0], median_xy[:, 1])

    assert np.allclose(radii, 10.0, atol=0.1), \
        f"small-jitter median radii in [{radii.min():.4f}, {radii.max():.4f}] — " \
        f"per-axis median fragile even to timing-line-level jitter"


def test_large_phase_offsets_need_alignment():
    """Documentation test: per-axis median alone CANNOT correct large
    phase offsets (15°+). The Phase-E lap-start alignment step is what
    closes this; this test pins the alignment-free behaviour so a
    later regression that silently 'fixes' it gets caught."""
    n = 500
    laps = [_circle(10.0, n, phi0=phi) for phi in (0.0, np.deg2rad(15), np.deg2rad(30))]

    u_grid = np.linspace(0.0, 1.0, 512, endpoint=False)
    grids = []
    for lap in laps:
        u, lap_clean = normalize_to_u(lap)
        grids.append(interpolate_lap_to_u_grid(u, lap_clean, u_grid))

    median_xy = pointwise_median(grids)
    radii = np.hypot(median_xy[:, 0], median_xy[:, 1])

    # Expect significant deviation from r=10 — this confirms the Phase-E
    # alignment is needed. ~3 % observed empirically (r drops to ~9.67 at
    # certain u). If a future fix tightens this *without* adding
    # alignment, that warrants investigation.
    radius_min = radii.min()
    assert radius_min < 9.9, \
        f"large-offset median radii unexpectedly within 0.1 m (min={radius_min:.4f}) — " \
        f"did alignment get added at u-grid level by accident?"


def test_pointwise_median_rejects_one_outlier_lap():
    """4 circle laps; lap 3 is a distorted ellipse. Median should ignore
    it because at any u-bucket 3 of 4 laps are on the circle and the
    median picks the middle value."""
    n = 500
    laps = [
        _circle(10.0, n),
        _circle(10.0, n, phi0=np.deg2rad(5)),
        _circle(10.0, n, phi0=np.deg2rad(10)),
        # 4th lap: ellipse a=15, b=5 (very distorted)
        np.column_stack([
            15.0 * np.cos(np.linspace(0.0, 2 * np.pi, n, endpoint=False)),
            5.0 * np.sin(np.linspace(0.0, 2 * np.pi, n, endpoint=False)),
        ]),
    ]

    u_grid = np.linspace(0.0, 1.0, 512, endpoint=False)
    grids = []
    for lap in laps:
        u, lap_clean = normalize_to_u(lap)
        grids.append(interpolate_lap_to_u_grid(u, lap_clean, u_grid))

    median_xy = pointwise_median(grids)
    radii = np.hypot(median_xy[:, 0], median_xy[:, 1])

    # Median should be close to 10 (the consensus circle), NOT a smear of
    # the ellipse in. Tolerance is loose-ish because median of 4 is
    # average of 2 middle values — the ellipse pulls one neighbour.
    assert np.allclose(radii, 10.0, atol=1.5), \
        f"single-outlier-lap median radii in [{radii.min():.4f}, " \
        f"{radii.max():.4f}] — median not rejecting the ellipse"
