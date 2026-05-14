"""Day-12 Phase C — drainage factor tests.

Spec §7 Factor 1: drainage from local elevation gradient.

    slope < 0.5%:   factor = 1.30   (flat — water pools, less drainage)
    0.5-2%:         factor = 1.10   (mild — slow drainage)
    2-5%:           factor = 1.00   (good — neutral)
    > 5%:           factor = 0.85   (steep — drains fast)

Slope is treated as ABSOLUTE (water pools regardless of climb/descent
direction). At boundary values (0.5%, 2%, 5%), the higher-grade bucket
applies (i.e., the lower factor — more drainage). Implementation:
    factor = 1.30 if |slope| < 0.5
           = 1.10 if 0.5 ≤ |slope| < 2.0
           = 1.00 if 2.0 ≤ |slope| < 5.0
           = 0.85 if |slope| ≥ 5.0
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_TELEMETRY_PKG = _REPO_ROOT / "telemetry_tool"
for _p in (_REPO_ROOT, _TELEMETRY_PKG):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from telemetry_tool.conditions.spatial_factors import drainage_factor


# ── Synthetic isolation tests ──────────────────────────────────────────


def test_flat_segment_pools():
    """slope = 0 → flat bucket → 1.30."""
    result = drainage_factor(np.array([0.0]))
    assert result[0] == pytest.approx(1.30, abs=0.001)


def test_mild_slope_1pct():
    """slope = 1% → mild bucket → 1.10."""
    result = drainage_factor(np.array([1.0]))
    assert result[0] == pytest.approx(1.10, abs=0.001)


def test_good_drainage_3pct():
    """slope = 3% → good bucket → 1.00."""
    result = drainage_factor(np.array([3.0]))
    assert result[0] == pytest.approx(1.00, abs=0.001)


def test_steep_grade_6pct():
    """slope = 6% → steep bucket → 0.85."""
    result = drainage_factor(np.array([6.0]))
    assert result[0] == pytest.approx(0.85, abs=0.001)


def test_descent_uses_abs_slope():
    """Descent (negative slope) drains identically to climb at same |slope|."""
    climb = drainage_factor(np.array([3.0]))
    descent = drainage_factor(np.array([-3.0]))
    assert climb[0] == descent[0]


@pytest.mark.parametrize(
    "boundary,expected_factor",
    [
        # Boundary inclusion: higher-slope bucket wins at the boundary value.
        (0.5, 1.10),  # 0.5% → mild bucket
        (2.0, 1.00),  # 2.0% → good bucket
        (5.0, 0.85),  # 5.0% → steep bucket
    ],
)
def test_boundary_uses_higher_grade_bucket(boundary, expected_factor):
    """At a boundary value the LOWER factor applies (higher-slope bucket)."""
    result = drainage_factor(np.array([boundary]))
    assert result[0] == pytest.approx(expected_factor, abs=0.001)


def test_just_below_boundary_uses_lower_grade_bucket():
    """Just below a boundary keeps the LOWER-slope (higher-factor) bucket."""
    just_below = drainage_factor(np.array([0.4999, 1.9999, 4.9999]))
    assert just_below[0] == pytest.approx(1.30, abs=0.001)  # flat
    assert just_below[1] == pytest.approx(1.10, abs=0.001)  # mild
    assert just_below[2] == pytest.approx(1.00, abs=0.001)  # good


def test_full_array_vectorized():
    """Input array → output array of same shape."""
    slopes = np.array([0.0, 0.3, 1.0, 2.5, 4.0, 6.0, -3.0])
    result = drainage_factor(slopes)
    assert result.shape == slopes.shape
    expected = np.array([1.30, 1.30, 1.10, 1.00, 1.00, 0.85, 1.00])
    np.testing.assert_allclose(result, expected, atol=0.001)


def test_output_dtype_is_float():
    """Result is a float array (not int)."""
    result = drainage_factor(np.array([1.0, 3.0]))
    assert np.issubdtype(result.dtype, np.floating)


# ── Real-session smoke ─────────────────────────────────────────────────


def test_ok_r4_drainage_factor_distribution():
    """Compute drainage_factor(s) from OK_R4 mesh slope_pct array.

    Verifies shape matches mesh n_points; verifies all values are in
    spec range {0.85, 1.00, 1.10, 1.30}; documents the distribution
    for Phase H surface.
    """
    # Try to load the OK_R4 mesh produced by Day-10.6 audit. Skip if
    # not findable — this is an empirical smoke, not a hard gate.
    import json
    import tempfile

    mesh_path = Path(tempfile.gettempdir()) / "mesh_ok_r4_day8repro.json"
    if not mesh_path.exists():
        pytest.skip(f"OK_R4 mesh not at {mesh_path}; regenerate via scripts/generate_mesh.py")

    with open(mesh_path) as f:
        mesh = json.load(f)

    # Slope from elevation gradient
    z = np.asarray(mesh["centerline"]["z_m"])
    s = np.asarray(mesh["centerline"]["s_m"])
    slope_pct = np.gradient(z, s) * 100.0  # m/m → %

    factors = drainage_factor(slope_pct)
    assert factors.shape == slope_pct.shape

    # All values from the spec table.
    valid_factors = {0.85, 1.00, 1.10, 1.30}
    unique = set(np.round(factors, 4).tolist())
    assert unique.issubset(valid_factors), (
        f"OK_R4 drainage_factor produced non-spec values: {unique - valid_factors}"
    )

    # Documentation: distribution + slope range.
    counts = {v: int(np.sum(np.isclose(factors, v))) for v in valid_factors}
    print(
        f"\nOK_R4 drainage_factor distribution: {counts} "
        f"(slope range {slope_pct.min():.2f}% to {slope_pct.max():.2f}%)"
    )
