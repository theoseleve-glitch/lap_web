"""Port-integrity test for the 2D grip-aware solver ported onto feat/race-brief-lane2.

TDD Step 3 (written before the port is complete):
  * verifies the solver files were brought over intact
  * verifies the GripSurface.mu_limit_grid field exists
  * verifies solve_optimal_line_2d runs deterministically on a synthetic gold-tier surface

needs_casadi must NOT skip — casadi 3.7.2 is installed in the system Python.
"""
from __future__ import annotations

import numpy as np
import pytest

needs_casadi = pytest.importorskip("casadi")  # skips when casadi absent


# ---------------------------------------------------------------------------
# Fixture: synthetic gold-tier TrackSurface (straight 200 m, uniform mu=1.1)
# ---------------------------------------------------------------------------

def _synthetic_surface():
    """Build a minimal TrackSurface usable by solve_optimal_line_2d.

    No for_test constructor is needed — TrackSurface is a plain dataclass.
    Only the fields that surface_to_track_model reads are populated;
    all optional elevation / camber / boundary fields default to None.
    """
    from telemetry_tool.track_surface.grip_2d import GripSurface
    from telemetry_tool.track_surface.model import TrackSurface
    from telemetry_tool.track_surface.frenet import FrenetFrame

    # 40 s-bins × 17 n-bins, gold tier: 60 samples/cell -> conf == 1, mu_limit set
    s = np.arange(0, 200, 5.0)   # 40 points
    n = np.arange(-8, 9, 1.0)    # 17 points
    mu = np.full((s.size, n.size), 1.1)
    cnt = np.full_like(mu, 60.0)
    grip = GripSurface(
        s_bins=s,
        n_bins=n,
        mu_grid=mu,
        count_grid=cnt,
        confidence=np.clip(cnt / 50, 0, 1),
        mu_limit_grid=mu.copy(),
    )

    # Straight-line FrenetFrame — from_centerline computes curvature (≈0) automatically
    xy = np.column_stack([s, np.zeros(len(s))])  # 40 pts along x-axis
    frenet = FrenetFrame.from_centerline(xy)

    # Construct TrackSurface directly — no production-only constructor added
    return TrackSurface(
        track_id="SYN",
        frenet=frenet,
        grip_2d=grip,
    )


# ---------------------------------------------------------------------------
# Test: solver imports, runs, and is deterministic
# ---------------------------------------------------------------------------

def test_solve_optimal_line_2d_is_deterministic():
    from telemetry_tool.track_surface.solver_bridge import solve_optimal_line_2d

    surf = _synthetic_surface()
    a = solve_optimal_line_2d(surf, condition="dry", n_points=120, max_time_s=30.0)
    b = solve_optimal_line_2d(surf, condition="dry", n_points=120, max_time_s=30.0)

    assert a.solver_status in ("solved", "optimal", "Solve_Succeeded"), (
        f"expected a solved status, got {a.solver_status!r}"
    )
    assert np.allclose(a.lateral_offset_m, b.lateral_offset_m), (
        "solve_optimal_line_2d is not deterministic across two identical calls"
    )
    assert a.distance_m.shape == a.lateral_offset_m.shape == a.speed_mps.shape, (
        "OCPSolution arrays have inconsistent shapes: "
        f"distance={a.distance_m.shape}, lateral={a.lateral_offset_m.shape}, speed={a.speed_mps.shape}"
    )
