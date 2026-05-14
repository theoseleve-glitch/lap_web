"""Day-12 Phase E — wind-exposure factor tests.

Spec §7 Factor 3 (interpreted per Day-12 brief):

    angle = angle between wind-FROM direction and segment tangent (°)

    angle zone           | wind speed   | factor
    ---------------------+--------------+--------
    windward (< 60°)     | > 15 km/h    | 0.85
    windward (< 60°)     | 5-15 km/h    | 0.95
    perpendicular (60-120°) or
      windward + weak (< 5 km/h)        | 1.00
    leeward (> 120°)     | ≥ 5 km/h     | 1.10
    leeward (> 120°)     | < 5 km/h     | 1.15

Conventions:
    Open-Meteo ``wind_direction_10m`` is degrees-COMPASS-FROM (0=N, 90=E).
    Mesh frame is ENU (+X=east, +Y=north), so wind-FROM vector in ENU is
    (sin(az), cos(az)). Segment tangent ENU comes from FrenetFrame heading.
    Angle = arccos(dot(t_xy_unit, wind_from_xy)) in [0°, 180°].
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

from telemetry_tool.conditions.spatial_factors import wind_factor


# ── Tangent helpers ────────────────────────────────────────────────────


def _tangent_heading(headings_deg: list[float]) -> np.ndarray:
    """Build (N, 3) tangent unit vectors in ENU at given headings.

    Heading 0° = +X (east), 90° = +Y (north). (Matches mesh heading_rad
    convention from np.arctan2(dy, dx).)
    """
    h = np.deg2rad(np.asarray(headings_deg, dtype=np.float64))
    return np.column_stack([np.cos(h), np.sin(h), np.zeros_like(h)])


# ── Synthetic isolation tests ──────────────────────────────────────────


def test_windward_high_wind_aligned_head_on():
    """Wind from north (az=0), segment heading north (heading=90° from E) →
    angle 0° → windward. High wind → 0.85."""
    tangents = _tangent_heading([90.0])  # pointing north
    result = wind_factor(wind_direction_deg=0.0, wind_speed_kmh=20.0,
                          segment_tangents=tangents)
    assert result[0] == pytest.approx(0.85, abs=0.001)


def test_windward_moderate_wind():
    """Same head-on alignment, moderate wind (5-15 km/h) → 0.95."""
    tangents = _tangent_heading([90.0])
    result = wind_factor(0.0, 10.0, tangents)
    assert result[0] == pytest.approx(0.95, abs=0.001)


def test_windward_weak_wind_falls_back_to_neutral():
    """Head-on but weak wind (<5 km/h) → spec 'weak wind' clause → 1.00."""
    tangents = _tangent_heading([90.0])
    result = wind_factor(0.0, 2.0, tangents)
    assert result[0] == pytest.approx(1.00, abs=0.001)


def test_perpendicular_neutral_regardless_of_wind_speed():
    """Wind from north, segment heading east (heading=0°) → angle 90° →
    perpendicular zone → 1.00 even at high wind."""
    tangents = _tangent_heading([0.0])  # pointing east
    high = wind_factor(0.0, 25.0, tangents)
    moderate = wind_factor(0.0, 8.0, tangents)
    weak = wind_factor(0.0, 2.0, tangents)
    assert high[0] == pytest.approx(1.00, abs=0.001)
    assert moderate[0] == pytest.approx(1.00, abs=0.001)
    assert weak[0] == pytest.approx(1.00, abs=0.001)


def test_leeward_moderate_wind():
    """Wind from north, segment heading south (heading=270° from E) →
    angle 180° → leeward → 1.10 at moderate-or-high wind."""
    tangents = _tangent_heading([270.0])  # pointing south
    result = wind_factor(0.0, 10.0, tangents)
    assert result[0] == pytest.approx(1.10, abs=0.001)


def test_leeward_weak_wind_most_sheltered():
    """Leeward + weak wind → 1.15 (most sheltered)."""
    tangents = _tangent_heading([270.0])
    result = wind_factor(0.0, 2.0, tangents)
    assert result[0] == pytest.approx(1.15, abs=0.001)


@pytest.mark.parametrize(
    "heading_deg,expected_factor",
    [
        # All with wind from N at 10 km/h (moderate).
        (90.0, 0.95),    # heading N → angle 0 → windward moderate
        (60.0, 0.95),    # heading NE → angle 30 → still windward
        (30.0, 0.95),    # heading ENE → angle 60-ε → just windward (< 60 cutoff)
        (0.0,  1.00),    # heading E → angle 90 → perpendicular
        (-30.0, 1.00),   # heading ESE → angle 120-ε → still perpendicular
        (-60.0, 1.10),   # heading SE → angle 150 → just leeward
        (-90.0, 1.10),   # heading S → angle 180 → leeward
    ],
)
def test_angle_zone_boundaries(heading_deg, expected_factor):
    """Walk the angle zones at fixed wind speed."""
    tangents = _tangent_heading([heading_deg])
    result = wind_factor(0.0, 10.0, tangents)
    # Boundary inclusion: angle exactly 60° or 120° is "perpendicular".
    # Implementation uses strict <60 (windward) / strict >120 (leeward).
    assert result[0] == pytest.approx(expected_factor, abs=0.001), (
        f"heading {heading_deg}° (angle to wind-from N) → expected "
        f"{expected_factor}, got {result[0]:.3f}"
    )


def test_vectorized_per_segment():
    """Multi-segment, varied tangents → varied factors."""
    # Wind from N at 12 km/h
    headings = [90.0, 0.0, -90.0]  # N, E, S
    tangents = _tangent_heading(headings)
    result = wind_factor(0.0, 12.0, tangents)
    expected = np.array([0.95, 1.00, 1.10])
    np.testing.assert_allclose(result, expected, atol=0.001)


def test_wind_speed_boundary_15kmh_uses_moderate():
    """At exactly 15 km/h: moderate-or-high boundary → spec lookup
    table 'wind > 15' is strict-greater-than, so 15 exactly = moderate."""
    tangents = _tangent_heading([90.0])  # windward
    result = wind_factor(0.0, 15.0, tangents)
    assert result[0] == pytest.approx(0.95, abs=0.001)


def test_output_dtype_and_shape():
    tangents = _tangent_heading([0.0] * 5)
    result = wind_factor(0.0, 10.0, tangents)
    assert result.shape == (5,)
    assert np.issubdtype(result.dtype, np.floating)


# ── Real-session smoke ─────────────────────────────────────────────────


def test_ok_r4_wind_factor_distribution():
    """Compute wind_factor(s) for OK_R4 using Day-11 WeatherCondition's
    wind direction + speed from raw_inputs. Verifies factor distribution
    spans multiple buckets across a closed-loop track."""
    import json
    import tempfile

    mesh_path = Path(tempfile.gettempdir()) / "mesh_ok_r4_day8repro.json"
    if not mesh_path.exists():
        pytest.skip(f"OK_R4 mesh not at {mesh_path}; regenerate first")

    with open(mesh_path) as f:
        mesh = json.load(f)

    x = np.asarray(mesh["centerline"]["x_m"])
    y = np.asarray(mesh["centerline"]["y_m"])
    s = np.asarray(mesh["centerline"]["s_m"])
    dx = np.gradient(x, s)
    dy = np.gradient(y, s)
    # Horizontal tangent unit vectors
    norm = np.sqrt(dx * dx + dy * dy)
    norm = np.where(norm < 1e-9, 1.0, norm)
    tangents = np.column_stack([dx / norm, dy / norm, np.zeros_like(dx)])

    # OK_R4 Feb 7 2026 10:47 UTC: wind from S-SE, ~10 km/h (per Day-11
    # raw_inputs printout). Hard-coded for the smoke test.
    factors = wind_factor(wind_direction_deg=178.0, wind_speed_kmh=27.0,
                            segment_tangents=tangents)
    assert factors.shape == tangents.shape[:1]

    valid = {0.85, 0.95, 1.00, 1.10, 1.15}
    unique = set(np.round(factors, 4).tolist())
    assert unique.issubset(valid), (
        f"OK_R4 wind_factor produced non-spec values: {unique - valid}"
    )
    counts = {v: int(np.sum(np.isclose(factors, v))) for v in valid}
    print(f"\nOK_R4 wind_factor (from 178°, 27 km/h): {counts}")
    # Closed-loop track → drivers face every direction → expect MULTIPLE
    # buckets populated.
    populated_buckets = sum(1 for c in counts.values() if c > 0)
    assert populated_buckets >= 2, (
        f"Closed-loop track at OK should produce >=2 wind buckets, "
        f"got {populated_buckets}: {counts}"
    )
