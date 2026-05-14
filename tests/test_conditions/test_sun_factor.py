"""Day-12 Phase D — sun-exposure factor tests.

Spec §7 Factor 2:
    sun_alignment = dot(sun_vector, segment_normal_unit)
    sun_alignment > 0.7:    factor = 0.85   (full sun)
    0.3 ≤ alignment ≤ 0.7:  factor = 0.95   (partial)
    alignment < 0.3:        factor = 1.15   (shaded)
    modifier: sun_altitude < 10°: factor *= 1.10
    sun_altitude < 0 (below horizon): factor = 1.15 everywhere

Sun position from pvlib (NREL). East-North-Up local frame:
    sun_vector = (cos(el)·sin(az), cos(el)·cos(az), sin(el))
Segment normal in same frame; both unit-length.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_TELEMETRY_PKG = _REPO_ROOT / "telemetry_tool"
for _p in (_REPO_ROOT, _TELEMETRY_PKG):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from telemetry_tool.conditions.spatial_factors import sun_factor, sun_vector_enu


# ── Synthetic isolation tests ──────────────────────────────────────────


def _normals_up(n: int) -> np.ndarray:
    """All segment normals pointing straight up (flat track)."""
    return np.tile(np.array([0.0, 0.0, 1.0]), (n, 1))


def _normals_horizontal(n: int) -> np.ndarray:
    """All segment normals horizontal (vertical surface, pointing east)."""
    return np.tile(np.array([1.0, 0.0, 0.0]), (n, 1))


def test_overhead_sun_flat_track_full_alignment():
    """Sun at zenith (el=90), flat track → alignment = 1.0 → factor = 0.85."""
    # Pick a tropical noon timestamp so sun is near-zenith.
    when = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)  # June solstice noon
    lat, lon = 0.0, 0.0  # equator at noon UTC → sun overhead
    normals = _normals_up(5)
    result = sun_factor(when, lat, lon, normals)
    assert np.all(result == pytest.approx(0.85, abs=0.001)), (
        f"Equator noon at solstice should give full-sun factor 0.85; got {result}"
    )


def test_horizontal_segment_no_direct_sun():
    """Segment normal horizontal pointing east, sun south → alignment ≈ 0 → factor = 1.15."""
    when = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    lat, lon = 45.0, 0.0  # northern hemisphere, sun in south
    normals = _normals_horizontal(3)  # pointing east, ⊥ to sun
    result = sun_factor(when, lat, lon, normals)
    # Sun is high (el ~68° at lat 45 summer solstice noon) so no low-altitude modifier.
    assert np.all(result == pytest.approx(1.15, abs=0.001)), (
        f"Horizontal segments ⊥ to high sun should be shaded (1.15); got {result}"
    )


def test_low_sun_altitude_modifier():
    """Sun altitude < 10°, segment aligned → factor = 0.85 * 1.10 = 0.935."""
    # Late January UTC noon at lat 65° (Arctic Circle); sun barely above horizon.
    when = datetime(2026, 1, 25, 12, 0, tzinfo=timezone.utc)
    lat, lon = 65.0, 0.0
    # Confirm sun is in fact < 10° elevation at this location/time:
    az_deg, el_deg = sun_vector_enu(when, lat, lon, return_az_el=True)
    assert 0 < el_deg < 10, f"test setup expects el ∈ (0, 10); got {el_deg:.2f}"
    # Now point segment normal directly at the sun.
    sun_vec = sun_vector_enu(when, lat, lon)
    normals = np.tile(sun_vec, (3, 1))  # 3 segments all aligned with sun
    result = sun_factor(when, lat, lon, normals)
    assert np.all(result == pytest.approx(0.85 * 1.10, abs=0.001)), (
        f"Low sun + full alignment should give 0.935 (0.85·1.10); got {result}"
    )


def test_sun_below_horizon_treated_as_nighttime():
    """sun_altitude < 0 → all segments factor = 1.15 (shaded)."""
    # Midnight UTC at lat 45°
    when = datetime(2026, 6, 21, 0, 0, tzinfo=timezone.utc)
    lat, lon = 45.0, 0.0
    az_deg, el_deg = sun_vector_enu(when, lat, lon, return_az_el=True)
    assert el_deg < 0, f"test setup expects below-horizon; got el={el_deg:.2f}"
    normals = _normals_up(4)
    result = sun_factor(when, lat, lon, normals)
    assert np.all(result == pytest.approx(1.15, abs=0.001)), (
        f"Nighttime should be uniformly shaded (1.15); got {result}"
    )


def test_partial_alignment_middle_bucket():
    """Alignment in (0.3, 0.7) → factor = 0.95."""
    # Construct a normal whose alignment with the sun is exactly 0.5.
    when = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    lat, lon = 30.0, 0.0
    sun_vec = sun_vector_enu(when, lat, lon)
    # Find a unit normal at alignment 0.5: take sun_vec and tilt away
    # in a direction perpendicular to it. Easy construction: solve for
    # n = a·sun + b·perpendicular where dot(n, sun) = a and |n|=1.
    # Pick a=0.5, find perpendicular vector, b=sqrt(1-0.25)=√0.75.
    # Perpendicular: any vector ⊥ to sun. Pick cross(sun, up).
    up = np.array([0.0, 0.0, 1.0])
    perp = np.cross(sun_vec, up)
    perp = perp / np.linalg.norm(perp)
    a = 0.5
    b = np.sqrt(1.0 - a * a)
    n = a * sun_vec + b * perp
    n = n / np.linalg.norm(n)
    # Sanity: alignment should be 0.5 to within fp noise.
    align = np.dot(n, sun_vec)
    assert align == pytest.approx(0.5, abs=1e-6)
    normals = np.tile(n, (2, 1))
    result = sun_factor(when, lat, lon, normals)
    assert np.all(result == pytest.approx(0.95, abs=0.001)), (
        f"Alignment 0.5 should give partial-sun factor 0.95; got {result}"
    )


def test_vectorized_per_segment_factors():
    """Multi-segment with varied normals → varied factors per segment."""
    when = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    lat, lon = 45.0, 0.0
    sun_vec = sun_vector_enu(when, lat, lon)
    up = np.array([0.0, 0.0, 1.0])
    perp = np.cross(sun_vec, up); perp /= np.linalg.norm(perp)
    # 3 normals at alignments 1.0 / 0.5 / 0.0
    n1 = sun_vec
    n2 = 0.5 * sun_vec + np.sqrt(0.75) * perp; n2 /= np.linalg.norm(n2)
    n3 = perp
    normals = np.vstack([n1, n2, n3])
    result = sun_factor(when, lat, lon, normals)
    expected = np.array([0.85, 0.95, 1.15])
    np.testing.assert_allclose(result, expected, atol=0.001)


def test_output_dtype_and_shape():
    when = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    normals = _normals_up(7)
    result = sun_factor(when, 30.0, 0.0, normals)
    assert result.shape == (7,)
    assert np.issubdtype(result.dtype, np.floating)


# ── Real-session smoke ─────────────────────────────────────────────────


def test_ok_r4_sun_factor_distribution():
    """Compute sun_factor(s) for OK_R4 (Feb 7 2026 10:47 UTC, Normandy).
    Late-winter low-angle sun + roughly flat OK track → expect
    distribution to be heavily weighted toward one bucket; document.
    """
    import json
    import tempfile

    mesh_path = Path(tempfile.gettempdir()) / "mesh_ok_r4_day8repro.json"
    if not mesh_path.exists():
        pytest.skip(f"OK_R4 mesh not at {mesh_path}; regenerate first")

    with open(mesh_path) as f:
        mesh = json.load(f)

    # Build per-segment 3D normals from heading + slope.
    x = np.asarray(mesh["centerline"]["x_m"])
    y = np.asarray(mesh["centerline"]["y_m"])
    z = np.asarray(mesh["centerline"]["z_m"])
    s = np.asarray(mesh["centerline"]["s_m"])
    dx = np.gradient(x, s)
    dy = np.gradient(y, s)
    dz = np.gradient(z, s)
    # Heading in XY plane:
    h = np.arctan2(dy, dx)
    slope = dz  # dz/ds — small fraction
    # Normal (unnormalized): (-slope·cos(h), -slope·sin(h), 1)
    nx = -slope * np.cos(h)
    ny = -slope * np.sin(h)
    nz = np.ones_like(slope)
    norm = np.sqrt(nx * nx + ny * ny + nz * nz)
    normals = np.column_stack([nx / norm, ny / norm, nz / norm])

    when = datetime(2026, 2, 7, 10, 47, tzinfo=timezone.utc)
    lat, lon = 48.55, 0.27
    factors = sun_factor(when, lat, lon, normals)

    valid = {0.85, 0.95, 1.15, 0.85 * 1.10, 0.95 * 1.10, 1.15 * 1.10}
    unique = set(np.round(factors, 4).tolist())
    assert unique.issubset({round(v, 4) for v in valid}), (
        f"OK_R4 sun_factor produced unexpected values: {unique}"
    )
    counts = {round(v, 4): int(np.sum(np.isclose(factors, v))) for v in valid}
    az_deg, el_deg = sun_vector_enu(when, lat, lon, return_az_el=True)
    print(
        f"\nOK_R4 sun_factor (az={az_deg:.1f}°, el={el_deg:.1f}°): {counts}"
    )
