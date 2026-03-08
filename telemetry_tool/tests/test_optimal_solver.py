"""Tests for unified optimal lap solver."""
import math
import numpy as np
import pandas as pd
import pytest


def test_optimal_caps_fields():
    """OptimalCaps has all required fields and to_dict()."""
    from optimal_solver import OptimalCaps

    n = 100
    caps = OptimalCaps(
        distance_m=np.linspace(0, 500, n),
        v_cap=np.full(n, 30.0),
        ax_accel=np.full(n, 5.0),
        ax_brake=np.full(n, 8.0),
        curvature=np.full(n, 0.01),
        mu=np.full(n, 1.0),
        cap_source=["envelope_p98"] * n,
        solver_version="optimal_v2_1.0",
    )
    assert len(caps.distance_m) == n
    assert caps.solver_version == "optimal_v2_1.0"
    d = caps.to_dict()
    assert "solver_version" in d
    assert "cap_source_summary" in d


def test_optimal_result_fields():
    """OptimalResult has all required fields and to_dict()."""
    from optimal_solver import OptimalResult

    n = 100
    r = OptimalResult(
        distance_m=np.linspace(0, 500, n),
        v_opt_mps=np.full(n, 25.0),
        accel_profile_mps2=np.zeros(n),
        lap_time_s=20.0,
        cornering_limited=np.zeros(n, dtype=bool),
        accel_limited=np.zeros(n, dtype=bool),
        brake_limited=np.zeros(n, dtype=bool),
        cap_source=["envelope_p98"] * n,
        solver_version="optimal_v2_1.0",
        n_iterations=3,
    )
    assert r.lap_time_s == 20.0
    d = r.to_dict()
    assert "v_opt_mps" in d
    assert "lap_time_s" in d


def test_solve_straight_track():
    """Straight track (zero curvature) -> speed limited by v_cap and accel."""
    from optimal_solver import OptimalCaps, solve_optimal_speed

    n = 200
    dist = np.linspace(0, 1000, n)
    caps = OptimalCaps(
        distance_m=dist,
        v_cap=np.full(n, 50.0),
        ax_accel=np.full(n, 5.0),
        ax_brake=np.full(n, 8.0),
        curvature=np.zeros(n),  # straight
        mu=np.full(n, 1.5),
        cap_source=["test"] * n,
        solver_version="test",
    )
    result = solve_optimal_speed(caps)

    assert result.lap_time_s > 0
    assert result.lap_time_s < 100  # reasonable
    assert np.all(result.v_opt_mps >= 0)
    assert np.all(result.v_opt_mps <= 50.0 + 0.1)  # respect v_cap


def test_solve_corner_slows_down():
    """Track with one tight corner -> speed dips at corner."""
    from optimal_solver import OptimalCaps, solve_optimal_speed

    n = 200
    dist = np.linspace(0, 500, n)
    curvature = np.zeros(n)
    # Tight corner in the middle (radius = 20m, curvature = 0.05)
    mid = n // 2
    curvature[mid - 10:mid + 10] = 0.05

    caps = OptimalCaps(
        distance_m=dist,
        v_cap=np.full(n, 40.0),
        ax_accel=np.full(n, 5.0),
        ax_brake=np.full(n, 8.0),
        curvature=curvature,
        mu=np.full(n, 1.0),
        cap_source=["test"] * n,
        solver_version="test",
    )
    result = solve_optimal_speed(caps)

    # Speed at the corner should be lower than on the straights
    corner_speed = np.mean(result.v_opt_mps[mid - 5:mid + 5])
    straight_speed = np.mean(result.v_opt_mps[:20])
    assert corner_speed < straight_speed * 0.8

    # Some points should be cornering-limited
    assert result.cornering_limited[mid]


def test_same_caps_same_result():
    """Same OptimalCaps -> identical v_opt regardless of how caps were built."""
    from optimal_solver import OptimalCaps, solve_optimal_speed

    n = 100
    dist = np.linspace(0, 500, n)
    curvature = np.zeros(n)
    curvature[40:60] = 0.03  # corner

    caps1 = OptimalCaps(
        distance_m=dist,
        v_cap=np.full(n, 35.0),
        ax_accel=np.full(n, 4.0),
        ax_brake=np.full(n, 7.0),
        curvature=curvature,
        mu=np.full(n, 1.2),
        cap_source=["envelope_p98"] * n,
        solver_version="v1",
    )
    caps2 = OptimalCaps(
        distance_m=dist.copy(),
        v_cap=np.full(n, 35.0),
        ax_accel=np.full(n, 4.0),
        ax_brake=np.full(n, 7.0),
        curvature=curvature.copy(),
        mu=np.full(n, 1.2),
        cap_source=["physics_hybrid"] * n,  # different source label
        solver_version="v2",  # different version label
    )

    r1 = solve_optimal_speed(caps1)
    r2 = solve_optimal_speed(caps2)

    # Physics must be identical — only provenance differs
    np.testing.assert_allclose(r1.v_opt_mps, r2.v_opt_mps, atol=1e-10)
    assert abs(r1.lap_time_s - r2.lap_time_s) < 1e-10


def test_solve_no_mu_uses_v_cap_only():
    """When mu is None, cornering limit comes only from v_cap."""
    from optimal_solver import OptimalCaps, solve_optimal_speed

    n = 100
    dist = np.linspace(0, 500, n)
    v_cap = np.full(n, 30.0)
    v_cap[40:60] = 15.0  # pre-computed corner speed cap

    caps = OptimalCaps(
        distance_m=dist,
        v_cap=v_cap,
        ax_accel=np.full(n, 5.0),
        ax_brake=np.full(n, 8.0),
        curvature=np.full(n, 0.02),  # curvature present but no mu
        mu=None,
        cap_source=["test"] * n,
        solver_version="test",
    )
    result = solve_optimal_speed(caps)

    # Corner speed should respect v_cap
    assert np.all(result.v_opt_mps[40:60] <= 15.0 + 0.1)


def test_caps_from_percentile_envelope():
    """Percentile envelope produces valid OptimalCaps."""
    from theoretical_engine import caps_from_percentile_envelope

    rng = np.random.default_rng(42)
    n_points = 200
    laps = []
    for _ in range(8):
        dist = np.linspace(0, 500, n_points)
        speed = np.full(n_points, 20.0) + rng.normal(0, 1.0, n_points)
        speed = np.clip(speed, 5.0, 40.0)
        laps.append(pd.DataFrame({
            "distance_m": dist,
            "speed_mps": speed,
            "accel_long_mps2": rng.normal(0, 2.0, n_points),
        }))

    curvature = np.full(n_points, 0.005)
    caps = caps_from_percentile_envelope(laps, curvature)

    assert len(caps.distance_m) == n_points
    assert np.all(caps.v_cap > 0)
    assert np.all(caps.ax_accel > 0)
    assert np.all(caps.ax_brake > 0)
    assert all(s == "envelope_p98" for s in caps.cap_source)


def test_caps_from_vehicle_model():
    """Physics vehicle model produces valid OptimalCaps."""
    from lap_simulation import caps_from_vehicle_model

    n = 200
    dist = np.linspace(0, 500, n)
    curvature = np.zeros(n)
    curvature[80:120] = 0.02  # corner

    caps = caps_from_vehicle_model(
        distance_m=dist,
        curvature=curvature,
        traction_mps2=5.0,
        braking_mps2=8.0,
        mu=1.2,
        v_max_mps=40.0,
    )

    assert len(caps.distance_m) == n
    assert np.all(caps.ax_accel > 0)
    assert np.all(caps.ax_brake > 0)
    assert caps.mu is not None
    assert all("physics" in s for s in caps.cap_source)

    # Corner speeds should be lower than straight speeds
    corner_cap = np.mean(caps.v_cap[90:110])
    straight_cap = np.mean(caps.v_cap[:20])
    assert corner_cap < straight_cap
