"""Tests for combined friction envelope."""
import numpy as np
import pandas as pd
import pytest


def test_friction_bin_fields():
    """FrictionBin has all required fields and to_dict()."""
    from friction_envelope import FrictionBin

    fb = FrictionBin(
        speed_center_mps=15.0,
        combined_g_p95=1.3,
        lat_max_g=1.2,
        accel_max_g=0.8,
        brake_max_g=1.5,
        sample_count=50,
        confidence=0.9,
    )
    assert fb.speed_center_mps == 15.0
    assert fb.combined_g_p95 == 1.3
    d = fb.to_dict()
    assert "brake_max_g" in d


def test_friction_envelope_fields():
    """FrictionEnvelope has all required fields and to_dict()."""
    from friction_envelope import FrictionEnvelope

    fe = FrictionEnvelope(
        speed_bins=np.array([5.0, 15.0, 25.0]),
        friction_bins=[],
        global_combined_g=1.2,
        is_reliable=True,
        warning=None,
    )
    assert fe.is_reliable is True
    d = fe.to_dict()
    assert "global_combined_g" in d


def _make_friction_laps(n_laps=8, n_points=200, mu_circle=1.2):
    """Create laps with known friction circle radius."""
    rng = np.random.default_rng(42)
    laps = {}
    for lap_num in range(1, n_laps + 1):
        dist = np.linspace(0, 500, n_points)
        speed = np.full(n_points, 20.0) + rng.normal(0, 2.0, n_points)
        speed = np.clip(speed, 5.0, 40.0)

        # Generate points inside the friction circle
        angles = rng.uniform(0, 2 * np.pi, n_points)
        radii = rng.uniform(0.3, 0.95, n_points) * mu_circle
        a_lat_g = radii * np.cos(angles)
        a_long_g = radii * np.sin(angles)

        laps[lap_num] = pd.DataFrame({
            "Distance (m)": dist,
            "Speed (m/s)": speed,
            "Lateral acceleration (G) *calc": a_lat_g,
            "accel_long_mps2": a_long_g * 9.80665,  # convert to m/s^2
        })
    return laps


def test_compute_friction_envelope_known_circle():
    """Known friction circle mu=1.2 → recovered envelope close."""
    from friction_envelope import compute_friction_envelope

    laps = _make_friction_laps(n_laps=10, mu_circle=1.2)
    fe = compute_friction_envelope(laps)

    assert fe.is_reliable is True
    assert fe.warning is None
    # Global combined G should be close to mu_circle
    assert abs(fe.global_combined_g - 1.2) < 0.3


def test_friction_envelope_is_feasible():
    """is_feasible() checks combined accel constraint."""
    from friction_envelope import compute_friction_envelope

    laps = _make_friction_laps(n_laps=10, mu_circle=1.0)
    fe = compute_friction_envelope(laps)

    # Well within circle should be feasible
    assert fe.is_feasible(20.0, 0.3, 0.3) is True
    # Way outside circle should be infeasible
    assert fe.is_feasible(20.0, 2.0, 2.0) is False


def test_friction_envelope_max_lat_at_long():
    """max_lat_at_long() returns reduced lateral under braking."""
    from friction_envelope import compute_friction_envelope

    laps = _make_friction_laps(n_laps=10, mu_circle=1.2)
    fe = compute_friction_envelope(laps)

    # Zero longitudinal → max lateral
    max_lat_0 = fe.max_lat_at_long(20.0, 0.0)
    # Under braking → reduced lateral
    max_lat_brake = fe.max_lat_at_long(20.0, 0.8)
    assert max_lat_brake < max_lat_0


def test_friction_envelope_too_few_samples():
    """Fewer than 50 total samples → is_reliable=False."""
    from friction_envelope import compute_friction_envelope

    rng = np.random.default_rng(42)
    laps = {1: pd.DataFrame({
        "Distance (m)": np.linspace(0, 100, 10),
        "Speed (m/s)": np.full(10, 20.0),
        "Lateral acceleration (G) *calc": rng.normal(0, 0.3, 10),
        "accel_long_mps2": rng.normal(0, 1.0, 10),
    })}

    fe = compute_friction_envelope(laps)
    assert fe.is_reliable is False
    assert fe.warning is not None
