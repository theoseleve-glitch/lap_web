"""Tests for distance-binned grip map."""
import numpy as np
import pandas as pd
import pytest


def test_grip_bin_stats_fields():
    """GripBinStats has all required fields and to_dict()."""
    from grip_map import GripBinStats

    b = GripBinStats(
        distance_m=100.0,
        mu_mean=1.1,
        mu_p50=1.0,
        mu_p90=1.3,
        mu_p95=1.4,
        mu_p99=1.5,
        sample_count=15,
        variance=0.02,
        confidence=0.85,
        source="lat_accel",
    )
    assert b.distance_m == 100.0
    assert b.mu_mean == 1.1
    d = b.to_dict()
    assert "confidence" in d
    assert "source" in d


def test_grip_map_fields():
    """GripMap has all required fields and to_dict()."""
    from grip_map import GripMap

    gm = GripMap(
        distance_bins=np.linspace(0, 500, 100),
        mu_mean=np.full(100, 1.0),
        mu_p90=np.full(100, 1.2),
        mu_p95=np.full(100, 1.3),
        bin_stats=[],
        global_mu=1.1,
        is_global_fallback=False,
        source="lat_accel",
        warning=None,
        n_laps_used=10,
    )
    assert len(gm.distance_bins) == 100
    assert gm.global_mu == 1.1
    d = gm.to_dict()
    assert "distance_bins" in d
    assert "is_global_fallback" in d


def test_grip_map_mu_at():
    """mu_at() interpolates correctly."""
    from grip_map import GripMap

    gm = GripMap(
        distance_bins=np.array([0.0, 100.0, 200.0, 300.0]),
        mu_mean=np.array([0.8, 1.0, 1.2, 0.9]),
        mu_p90=np.array([1.0, 1.2, 1.4, 1.1]),
        mu_p95=np.array([1.1, 1.3, 1.5, 1.2]),
        bin_stats=[],
        global_mu=1.0,
        is_global_fallback=False,
        source="lat_accel",
        warning=None,
        n_laps_used=10,
    )
    # At exact bin
    assert abs(gm.mu_at(100.0, "mean") - 1.0) < 0.01
    # Interpolated between bins
    mu_150 = gm.mu_at(150.0, "p95")
    assert 1.3 < mu_150 < 1.5  # between 1.3 and 1.5
    # Beyond range: clamp to edge
    assert abs(gm.mu_at(-10.0, "mean") - 0.8) < 0.01
    assert abs(gm.mu_at(500.0, "mean") - 0.9) < 0.01


def _make_synthetic_laps(n_laps=8, n_points=200, mu_profile=None):
    """Create synthetic laps with known grip profile.

    If mu_profile is None, uses constant mu=1.0.
    mu_profile: callable(distance) -> mu
    """
    rng = np.random.default_rng(42)
    lap_length = 500.0
    laps = {}

    for lap_num in range(1, n_laps + 1):
        dist = np.linspace(0, lap_length, n_points)
        speed = np.full(n_points, 20.0) + rng.normal(0, 0.5, n_points)
        speed = np.clip(speed, 5.0, 40.0)

        if mu_profile is not None:
            mu_at_dist = np.array([mu_profile(d) for d in dist])
        else:
            mu_at_dist = np.full(n_points, 1.0)

        # a_lat = mu * g (with noise)
        lat_accel_g = mu_at_dist * (1.0 + rng.normal(0, 0.05, n_points))
        # Randomly flip sign (left/right turns)
        sign = rng.choice([-1, 1], n_points)
        lat_accel_g *= sign

        laps[lap_num] = pd.DataFrame({
            "Distance (m)": dist,
            "Speed (m/s)": speed,
            "Lateral acceleration (G) *calc": lat_accel_g,
            "accel_long_mps2": rng.normal(0, 2.0, n_points),
        })

    return laps


def test_compute_grip_map_constant_mu():
    """Constant mu=1.0 across all bins."""
    from grip_map import compute_grip_map

    laps = _make_synthetic_laps(n_laps=8, mu_profile=lambda d: 1.0)
    gm = compute_grip_map(laps)

    assert not gm.is_global_fallback
    assert gm.source == "lat_accel"
    assert gm.warning is None
    assert gm.n_laps_used == 8

    # mu_mean should be close to 1.0 everywhere
    assert np.abs(np.median(gm.mu_mean) - 1.0) < 0.15
    # p95 should be slightly above mean
    assert np.median(gm.mu_p95) >= np.median(gm.mu_mean)


def test_compute_grip_map_varying_mu():
    """Varying mu: high in first half, low in second."""
    from grip_map import compute_grip_map

    def mu_profile(d):
        return 1.3 if d < 250 else 0.7

    laps = _make_synthetic_laps(n_laps=10, mu_profile=mu_profile)
    gm = compute_grip_map(laps)

    # First half bins should have higher mu than second half
    mid = len(gm.distance_bins) // 2
    first_half_mean = np.mean(gm.mu_mean[:mid])
    second_half_mean = np.mean(gm.mu_mean[mid:])
    assert first_half_mean > second_half_mean


def test_compute_grip_map_no_lat_accel_falls_back():
    """No lateral accel channel -> fallback to curvature*speed method."""
    from grip_map import compute_grip_map

    rng = np.random.default_rng(42)
    laps = {}
    for i in range(1, 6):
        laps[i] = pd.DataFrame({
            "Distance (m)": np.linspace(0, 500, 100),
            "Speed (m/s)": np.full(100, 20.0) + rng.normal(0, 0.5, 100),
            "accel_long_mps2": rng.normal(0, 1.0, 100),
        })

    # With curvature profile
    curv_df = pd.DataFrame({
        "distance_m": np.linspace(0, 500, 100),
        "curvature_1pm": np.full(100, 0.01),  # radius=100m
    })

    gm = compute_grip_map(laps, curvature_profile=curv_df)
    # Should use curvature_speed source or global fallback
    assert gm.source in ("curvature_speed", "lat_accel")
    assert gm.global_mu > 0


def test_compute_grip_map_too_few_laps():
    """Fewer than 3 laps -> global fallback."""
    from grip_map import compute_grip_map

    laps = _make_synthetic_laps(n_laps=2, mu_profile=lambda d: 1.0)
    gm = compute_grip_map(laps)

    assert gm.is_global_fallback is True
    assert gm.warning is not None
