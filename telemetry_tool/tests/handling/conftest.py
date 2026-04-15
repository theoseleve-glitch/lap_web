"""Shared fixtures for handling detector tests."""
import numpy as np
import pytest

from telemetry_tool.handling.types import CornerWindow, SessionContext


def _make_corner(
    n: int = 200,
    peak_g: float = 0.8,
    speed_mps: float = 15.0,
    corner_len_m: float = 80.0,
    duration_s: float = 4.0,
    direction: int = 1,
    late_apex: bool = False,
    early_apex: bool = False,
    exit_speed_drop: bool = False,
) -> CornerWindow:
    """Create a synthetic CornerWindow for testing."""
    t = np.linspace(0, duration_s, n)
    d = np.linspace(0, corner_len_m, n)
    s = np.ones(n) * speed_mps

    # Lateral G: sinusoidal with peak at mid-corner
    phase = np.linspace(0, np.pi, n)
    a_lat = np.sin(phase) * peak_g * direction

    # Speed: dip at apex (min-speed at center by default)
    apex_frac = 0.5
    if late_apex:
        apex_frac = 0.65  # min speed late
    elif early_apex:
        apex_frac = 0.35  # min speed early
    speed_dip = 3.0  # m/s dip
    s = s - speed_dip * np.exp(-((np.linspace(0, 1, n) - apex_frac) ** 2) / 0.02)

    if exit_speed_drop:
        s[n * 3 // 4:] -= 2.0  # extra speed loss at exit

    # Longitudinal G: braking at entry, accel at exit
    a_lon = np.zeros(n)
    a_lon[:n // 3] = -0.3
    a_lon[2 * n // 3:] = 0.2

    # Bearing: smooth rotation
    bearing = np.linspace(0, 90 * direction, n)
    yaw_dps = np.gradient(bearing, t)

    # Curvature: rough
    curv = np.abs(np.sin(phase) * 0.02)

    apex_g_local = int(np.argmax(np.abs(a_lat)))
    apex_speed_local = int(np.argmin(s))

    return CornerWindow(
        corner_id=0, start_i=0, end_i=n,
        apex_g_i=apex_g_local, apex_speed_i=apex_speed_local,
        time_s=t, dist_m=d, speed_mps=s,
        a_lat_g=a_lat, a_lon_g=a_lon, bearing_deg=bearing,
        lat_deg=np.ones(n) * 48.55, lon_deg=np.ones(n) * 0.27,
        yaw_rate_dps=yaw_dps, curvature=curv,
        peak_g=peak_g, corner_len_m=corner_len_m, corner_dur_s=duration_s,
        direction=direction,
        phase_entry=(0, n // 3), phase_mid=(n // 3, 2 * n // 3), phase_exit=(2 * n // 3, n),
        apex_lat=48.55, apex_lon=0.27,
    )


@pytest.fixture
def neutral_corner():
    return _make_corner()


@pytest.fixture
def understeer_corner():
    """Late apex + entry-heavy speed loss = understeer."""
    return _make_corner(late_apex=True)


@pytest.fixture
def oversteer_corner():
    """Early apex + exit speed drop = oversteer."""
    return _make_corner(early_apex=True, exit_speed_drop=True)


@pytest.fixture
def session_ctx():
    return SessionContext()
