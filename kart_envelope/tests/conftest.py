"""Shared fixtures for kart_envelope tests."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Ensure both project root and telemetry_tool are importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def default_config():
    from kart_envelope.config import default_config
    return default_config()


@pytest.fixture
def synthetic_oval_laps() -> dict[int, pd.DataFrame]:
    """Synthetic oval track data: two straights + two semicircles.

    Track: 500 m total, ds=0.5 m, 1000 points.
    Straights (0-125 m and 250-375 m): kappa=0, speed ~15 m/s.
    Turns (125-250 m and 375-500 m): kappa=0.04 (R=25 m), speed ~10 m/s.
    """
    np.random.seed(42)
    n = 1000
    ds = 0.5
    dist = np.arange(n) * ds

    # Curvature profile
    kappa = np.zeros(n)
    for lo, hi in [(125, 250), (375, 500)]:
        idx = (dist >= lo) & (dist < hi)
        kappa[idx] = 0.04

    # Speed: limited by lateral accel in corners
    ay_max = 8.0  # m/s^2
    v_corner = np.where(kappa > 0, np.sqrt(ay_max / kappa), 20.0)
    v_corner = np.minimum(v_corner, 20.0)

    # Smooth transitions
    v = v_corner.copy()
    for _ in range(50):
        for i in range(1, n):
            v[i] = min(v[i], np.sqrt(max(v[i - 1] ** 2 + 2 * 5.0 * ds, 0)))
        for i in range(n - 2, -1, -1):
            v[i] = min(v[i], np.sqrt(max(v[i + 1] ** 2 + 2 * 8.0 * ds, 0)))

    v = np.maximum(v, 2.0)
    # Add a bit of noise
    v_noisy = v + np.random.normal(0, 0.2, n)
    v_noisy = np.maximum(v_noisy, 2.0)

    # Time
    dt = ds / v_noisy
    time = np.cumsum(dt)

    # Accelerations
    ax = np.gradient(v_noisy, time)
    ay = v_noisy ** 2 * kappa

    # XY: approximate oval
    heading = np.cumsum(kappa * ds)
    x = np.cumsum(np.cos(heading) * ds)
    y = np.cumsum(np.sin(heading) * ds)

    laps = {}
    for lap_num in [1, 2, 3]:
        noise_scale = 0.05 * (lap_num - 1)  # progressively noisier
        df = pd.DataFrame({
            "time_s": time + np.random.uniform(-0.01, 0.01, n) * noise_scale,
            "distance_m": dist,
            "speed_mps": v_noisy + np.random.normal(0, 0.1 * noise_scale, n),
            "accel_long_mps2": ax + np.random.normal(0, 0.3, n),
            "accel_lat_mps2": ay * (0.9 + 0.1 * np.random.rand(n)),
            "x_m": x + np.random.normal(0, 0.1, n),
            "y_m": y + np.random.normal(0, 0.1, n),
            "lap_number": float(lap_num),
        })
        laps[lap_num] = df

    return laps


@pytest.fixture
def known_envelope():
    """A CapabilityEnvelope with known constant limits for testing."""
    from kart_envelope.envelope.capability import CapabilityEnvelope

    v_grid = np.linspace(3.0, 20.0, 10)
    return CapabilityEnvelope(
        v_grid=v_grid,
        ay_max=np.full(10, 8.0),        # 8 m/s^2 lateral
        ax_drive_max=np.full(10, 5.0),   # 5 m/s^2 traction
        ax_brake_max=np.full(10, 10.0),  # 10 m/s^2 braking
        p_combined=2.0,
        track_id="test_oval",
        kart_id="test_kart",
    )


@pytest.fixture
def oval_geometry() -> "TrackGeometry":
    """TrackGeometry for the synthetic oval."""
    from kart_envelope.track.geometry import TrackGeometry

    n = 1000
    ds = 0.5
    dist = np.arange(n) * ds
    kappa = np.zeros(n)
    for lo, hi in [(125, 250), (375, 500)]:
        idx = (dist >= lo) & (dist < hi)
        kappa[idx] = 0.04

    heading = np.cumsum(kappa * ds)
    x = np.cumsum(np.cos(heading) * ds)
    y = np.cumsum(np.sin(heading) * ds)

    return TrackGeometry(
        distance_m=dist,
        curvature_1pm=kappa,
        heading_rad=heading,
        x_ref_m=x,
        y_ref_m=y,
        lap_length_m=500.0,
        track_id="test_oval",
    )


@pytest.fixture
def small_oval_geometry() -> "TrackGeometry":
    """Smaller oval (100 pts) for tests that call the solver many times."""
    from kart_envelope.track.geometry import TrackGeometry

    n = 100
    ds = 5.0
    dist = np.arange(n) * ds
    kappa = np.zeros(n)
    for lo, hi in [(125, 250), (375, 500)]:
        idx = (dist >= lo) & (dist < hi)
        kappa[idx] = 0.04

    heading = np.cumsum(kappa * ds)
    x = np.cumsum(np.cos(heading) * ds)
    y = np.cumsum(np.sin(heading) * ds)

    return TrackGeometry(
        distance_m=dist,
        curvature_1pm=kappa,
        heading_rad=heading,
        x_ref_m=x,
        y_ref_m=y,
        lap_length_m=500.0,
        track_id="test_oval_small",
    )
