"""Phase-E unit tests — lap-start cross-correlation alignment.

After ``align_laps_circularly``, the post-median trace must reconstruct
the underlying geometry within 0.1 m even for laps that started at
materially different phases (15° = N/24 grid points).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TELEMETRY_PKG = _REPO_ROOT / "telemetry_tool"
for _p in (_REPO_ROOT, _TELEMETRY_PKG):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from track_surface.centerline import (  # noqa: E402
    align_laps_circularly,
    interpolate_lap_to_u_grid,
    normalize_to_u,
    pointwise_median,
)


def _three_phase_circles(radius: float, n: int, phis_deg: list[float]) -> list[np.ndarray]:
    laps = []
    for phi in phis_deg:
        theta = np.linspace(0.0, 2 * np.pi, n, endpoint=False) + np.deg2rad(phi)
        laps.append(np.column_stack([radius * np.cos(theta), radius * np.sin(theta)]))
    return laps


def _laps_on_u_grid(laps, n_grid=512):
    u_grid = np.linspace(0.0, 1.0, n_grid, endpoint=False)
    grids = []
    for lap in laps:
        u, lap_clean = normalize_to_u(lap)
        grids.append(interpolate_lap_to_u_grid(u, lap_clean, u_grid))
    return grids, u_grid


def test_alignment_recovers_circle_after_15deg_phase_shift():
    """Phase-E rationale test: three circles with 0°, 15°, 30° start-phase
    offsets. Pointwise median *post-alignment* should hold the radius to
    within 0.1 m everywhere (vs ~3 % deviation without alignment — see
    test_large_phase_offsets_need_alignment in test_centerline_u_grid)."""
    laps = _three_phase_circles(10.0, 500, [0.0, 15.0, 30.0])
    grids, _ = _laps_on_u_grid(laps, n_grid=512)
    aligned, shifts = align_laps_circularly(grids)

    median_xy = pointwise_median(aligned)
    radii = np.hypot(median_xy[:, 0], median_xy[:, 1])

    assert np.allclose(radii, 10.0, atol=0.1), \
        f"post-alignment radii [{radii.min():.4f}, {radii.max():.4f}] not within 0.1 m"

    # Reference lap should have shift = 0; the other two should have
    # shifts roughly corresponding to 15° and 30° in u-grid steps
    # (15/360 * 512 ≈ 21; 30/360 * 512 ≈ 43). Sign depends on which lap
    # was picked as reference, but the magnitudes should be in that band.
    nonzero = [abs(s) for s in shifts if s != 0]
    assert any(s > 0 for s in nonzero), \
        f"no non-zero shifts found; alignment may be degenerate. shifts={shifts}"


def test_alignment_no_change_when_laps_already_aligned():
    """If all laps start at the same phase, alignment should be a no-op
    (shift = 0 everywhere)."""
    laps = _three_phase_circles(10.0, 500, [0.0, 0.0, 0.0])
    grids, _ = _laps_on_u_grid(laps, n_grid=512)
    aligned, shifts = align_laps_circularly(grids)

    assert all(s == 0 for s in shifts), f"unexpected shifts when laps are already aligned: {shifts}"

    # Output should be unchanged
    for orig, post in zip(grids, aligned):
        assert np.allclose(orig, post)


def test_alignment_picks_median_arclength_reference_by_default():
    """The default reference is the lap with median on-grid arclength —
    avoids picking the outlier lap as reference."""
    # Two clean circles + one ellipse outlier. The reference should be
    # one of the two clean circles.
    n = 500
    clean = [
        np.column_stack([
            10.0 * np.cos(np.linspace(0, 2 * np.pi, n, endpoint=False) + phi),
            10.0 * np.sin(np.linspace(0, 2 * np.pi, n, endpoint=False) + phi),
        ])
        for phi in (0.0, np.deg2rad(2))
    ]
    outlier = np.column_stack([
        15.0 * np.cos(np.linspace(0, 2 * np.pi, n, endpoint=False)),
        5.0 * np.sin(np.linspace(0, 2 * np.pi, n, endpoint=False)),
    ])
    laps = clean + [outlier]
    grids, _ = _laps_on_u_grid(laps, n_grid=512)
    aligned, shifts = align_laps_circularly(grids)

    # The reference (shift=0) should be one of the clean circles (indices 0 or 1)
    ref_idx = shifts.index(0)
    assert ref_idx in (0, 1), \
        f"reference picked index {ref_idx} — should be a clean circle (0 or 1), not the ellipse (2)"


def test_alignment_handles_negative_shift():
    """If lap is shifted in the negative direction (started "earlier" in
    u-grid space), alignment still resolves it. Sanity check that
    np.roll + the convolution math agree on sign."""
    n_grid = 256
    u_grid = np.linspace(0.0, 1.0, n_grid, endpoint=False)
    theta = 2 * np.pi * u_grid
    ref = np.column_stack([10.0 * np.cos(theta), 10.0 * np.sin(theta)])
    # Hand-craft a "shifted" lap by rolling by -10 (i.e., lap[i] = ref[(i+10) % N])
    lap_shifted = np.roll(ref, -10, axis=0)
    aligned, shifts = align_laps_circularly([ref, lap_shifted])

    # The reference is ref (lap 0); lap 1 should get rolled by +10 to undo
    # the artificial -10 shift.
    assert shifts[0] == 0
    assert shifts[1] == 10 % n_grid, f"expected shift 10, got {shifts[1]}"
    # After alignment, lap 1 should be approximately equal to ref
    assert np.allclose(aligned[0], aligned[1], atol=1e-6)
