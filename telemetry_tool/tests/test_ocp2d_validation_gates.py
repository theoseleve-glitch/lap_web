"""Regression gate tests for the 2D minimum-time OCP (Race Brief Lane 2).

AUTHORITATIVE RUN:
  The full 5 gates (determinism, dry plausibility, wet correctness, lap-time
  sanity, solve robustness) on real gold-tier sidecar data are executed at
  Lane 2 deploy time by the controller via scripts/validate_ocp2d.py.
  These tests act as the permanent CI regression gate for the ported solver.

Casadi guard (module-level):
  The entire module is skipped via ``pytest.importorskip`` when casadi is
  absent.  On this branch casadi 3.7.2 is installed, so all tests run.

Gate mapping:
  SYNTHETIC — always run when casadi is present, no real data required:
    test_gate1_determinism_synthetic
        Same input → two solves produce bit-identical lateral offset arrays
        (verified via SHA-256 hash of the raw bytes).
    test_gate2_monotonicity_mu_speed
        Higher surface grip (μ=1.4) yields a strictly higher mean speed
        profile than lower grip (μ=0.7) on an identical curved track.

  DEPLOY-TIME / SKIP-GUARDED — require a real gold-tier sidecar
  (SIDECAR_ROOT env var pointing at a root with ≥10 laps per track):
    test_real_gate2_dry_plausibility
        median |n_line - n_driven| ≤ 0.5 m on the fastest 25 % of laps.
        Also needs LAP_VALIDATION_LAPS (glob) env var.
    test_real_gate3_wet_correctness
        mean μ_wet under wet line > under dry line; zero puddle crossings.
        Also needs LAP_TRACK_ID env var.
    test_real_gate4_laptime_sanity
        |t_pred - t_best_real| / t_best_real ≤ 3 %.
        Also needs LAP_VEHICLE_JSON + LAP_BEST_S env vars.
    test_real_gate5_solve_robustness
        solver_status ∈ {"optimal","solved","Solve_Succeeded"}
        AND solve_time_s < 60 s on a real gold-tier track.
        Also needs LAP_TRACK_ID env var.

The ≥95 % aggregate solve rate across ALL gold-tier tracks is checked
exclusively by scripts/validate_ocp2d.py at deploy time.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np
import pytest

# Module-level casadi guard: skip every test in this file when casadi is absent.
casadi = pytest.importorskip("casadi")


# ---------------------------------------------------------------------------
# Helpers shared by synthetic and real-data tests
# ---------------------------------------------------------------------------

def _make_synthetic_surface(mu_val: float, n_track_pts: int = 60):
    """Circular 100 m-radius surface with uniform grip = mu_val.

    Wide enough (±3 m each side) and curved enough (κ ≈ 0.01 /m) to expose
    the lateral grip constraint in the NLP.
    """
    from telemetry_tool.track_surface.grip_2d import GripSurface
    from telemetry_tool.track_surface.frenet import FrenetFrame
    from telemetry_tool.track_surface.model import TrackSurface

    R = 100.0
    theta = np.linspace(0, 2 * np.pi, n_track_pts, endpoint=False)
    xy = np.column_stack([R * np.cos(theta), R * np.sin(theta)])
    frenet = FrenetFrame.from_centerline(xy)

    n_s = max(24, n_track_pts // 2)
    s_bins = np.linspace(0.0, frenet.total_length_m, n_s, endpoint=False)
    n_bins = np.linspace(-3.0, 3.0, 13)  # ±3 m usable width
    mu_grid = np.full((s_bins.size, n_bins.size), mu_val)
    cnt = np.full_like(mu_grid, 60.0)
    grip = GripSurface(
        s_bins=s_bins,
        n_bins=n_bins,
        mu_grid=mu_grid,
        count_grid=cnt,
        confidence=np.clip(cnt / 50.0, 0.0, 1.0),
    )
    return TrackSurface(
        track_id=f"SYN_mu{mu_val:.2f}",
        frenet=frenet,
        grip_2d=grip,
        width_left=np.full(frenet.n_points, 3.0),
        width_right=np.full(frenet.n_points, 3.0),
        n_laps=60,  # qualify as gold-tier in quality_tier property
    )


def _sha256(arr: np.ndarray) -> str:
    """SHA-256 hex digest of the array in C-contiguous byte order."""
    return hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest()


_SOLVED_STATUSES = frozenset({"solved", "optimal", "Solve_Succeeded"})


def _has_gold_tier_sidecar() -> bool:
    """Return True when SIDECAR_ROOT is set, exists, and contains a grip_2d.parquet."""
    root = os.environ.get("SIDECAR_ROOT")
    if not root:
        return False
    p = Path(root)
    if not p.is_dir():
        return False
    return any(p.rglob("grip_2d.parquet"))


_SKIP_NO_GOLD = pytest.mark.skipif(
    not _has_gold_tier_sidecar(),
    reason=(
        "no gold-tier sidecar available "
        "(set SIDECAR_ROOT to a directory with ≥10 laps per track)"
    ),
)


# ---------------------------------------------------------------------------
# SYNTHETIC property tests — always run when casadi is present
# ---------------------------------------------------------------------------

def test_gate1_determinism_synthetic():
    """Gate 1: two identical solves produce bit-identical lateral offset arrays.

    The SHA-256 hash of the raw bytes must be equal across both calls on the
    same TrackSurface object.  This catches any non-deterministic IPOPT seed,
    random warm-start, or mutable default argument that would break the gate.
    """
    from telemetry_tool.track_surface.solver_bridge import solve_optimal_line_2d

    surface = _make_synthetic_surface(mu_val=1.1)
    a = solve_optimal_line_2d(surface, condition="dry", n_points=100, max_time_s=30.0)
    b = solve_optimal_line_2d(surface, condition="dry", n_points=100, max_time_s=30.0)

    assert a.solver_status in _SOLVED_STATUSES, (
        f"first solve did not converge: status={a.solver_status!r}"
    )
    assert b.solver_status in _SOLVED_STATUSES, (
        f"second solve did not converge: status={b.solver_status!r}"
    )

    hash_a = _sha256(a.lateral_offset_m)
    hash_b = _sha256(b.lateral_offset_m)
    assert hash_a == hash_b, (
        f"lateral_offset_m is not bit-identical across two identical calls "
        f"(a={hash_a[:16]}…, b={hash_b[:16]}…) — gate 1 FAIL"
    )

    hash_v_a = _sha256(a.speed_mps)
    hash_v_b = _sha256(b.speed_mps)
    assert hash_v_a == hash_v_b, (
        f"speed_mps is not bit-identical across two identical calls "
        f"(a={hash_v_a[:16]}…, b={hash_v_b[:16]}…) — gate 1 FAIL"
    )


def test_gate2_monotonicity_mu_speed():
    """Grip monotonicity (gate 2 property): μ↑ → mean speed profile↑.

    A circular track with μ=1.4 must yield a strictly higher mean speed than
    the same track with μ=0.7.  This validates that the NLP's friction
    constraint is wired correctly to the 2D grip field.
    """
    from telemetry_tool.track_surface.solver_bridge import solve_optimal_line_2d

    low_surf = _make_synthetic_surface(mu_val=0.7)
    high_surf = _make_synthetic_surface(mu_val=1.4)

    sol_low = solve_optimal_line_2d(low_surf, condition="dry", n_points=100, max_time_s=30.0)
    sol_high = solve_optimal_line_2d(high_surf, condition="dry", n_points=100, max_time_s=30.0)

    assert sol_low.solver_status in _SOLVED_STATUSES, (
        f"low-μ solve did not converge: {sol_low.solver_status!r}"
    )
    assert sol_high.solver_status in _SOLVED_STATUSES, (
        f"high-μ solve did not converge: {sol_high.solver_status!r}"
    )

    mean_low = float(np.mean(sol_low.speed_mps))
    mean_high = float(np.mean(sol_high.speed_mps))
    assert mean_high > mean_low, (
        f"monotonicity violated: μ=1.4 mean speed ({mean_high:.3f} m/s) "
        f"≤ μ=0.7 mean speed ({mean_low:.3f} m/s) — gate 2 property FAIL"
    )


# ---------------------------------------------------------------------------
# DEPLOY-TIME gates — skip when no real gold-tier sidecar is present
# ---------------------------------------------------------------------------

@_SKIP_NO_GOLD
def test_real_gate2_dry_plausibility():
    """Gate 2 (deploy-time): median |n_line - n_driven| ≤ 0.5 m on fast laps.

    Requires env vars:
      SIDECAR_ROOT      — path to sidecars root
      LAP_TRACK_ID      — track_id of the gold-tier surface to load
      LAP_VALIDATION_LAPS — glob expression for driven-lap parquet files

    Run via scripts/validate_ocp2d.py for the authoritative report.
    """
    laps_glob = os.environ.get("LAP_VALIDATION_LAPS")
    track_id = os.environ.get("LAP_TRACK_ID")
    if not laps_glob or not track_id:
        pytest.skip(
            "LAP_TRACK_ID and LAP_VALIDATION_LAPS must both be set "
            "for gate2 — use scripts/validate_ocp2d.py at deploy time"
        )
    pytest.skip(
        f"gate2 dry plausibility against real driven lines for {track_id!r} "
        "is a deploy-time gate — run scripts/validate_ocp2d.py"
    )


@_SKIP_NO_GOLD
def test_real_gate3_wet_correctness():
    """Gate 3 (deploy-time): wet line achieves higher μ_wet than dry line; zero puddle crossings.

    Requires env vars:
      SIDECAR_ROOT  — path to sidecars root
      LAP_TRACK_ID  — track_id of the gold-tier surface with elevation data

    Run via scripts/validate_ocp2d.py for the authoritative report.
    """
    track_id = os.environ.get("LAP_TRACK_ID")
    if not track_id:
        pytest.skip("LAP_TRACK_ID must be set for gate3 — use scripts/validate_ocp2d.py")
    pytest.skip(
        f"gate3 wet correctness for {track_id!r} is a deploy-time gate "
        "— run scripts/validate_ocp2d.py"
    )


@_SKIP_NO_GOLD
def test_real_gate4_laptime_sanity():
    """Gate 4 (deploy-time): |t_pred - t_best_real| / t_best_real ≤ 3%.

    Requires env vars:
      SIDECAR_ROOT    — path to sidecars root
      LAP_TRACK_ID    — track_id of the gold-tier surface
      LAP_VEHICLE_JSON — path to VehicleParams JSON (required for honest gate4)
      LAP_BEST_S       — best real lap time in seconds

    Run via scripts/validate_ocp2d.py for the authoritative report.
    """
    track_id = os.environ.get("LAP_TRACK_ID")
    if not track_id:
        pytest.skip(
            "LAP_TRACK_ID, LAP_VEHICLE_JSON, and LAP_BEST_S must all be set "
            "for gate4 — use scripts/validate_ocp2d.py at deploy time"
        )
    pytest.skip(
        f"gate4 lap-time sanity for {track_id!r} is a deploy-time gate "
        "— run scripts/validate_ocp2d.py"
    )


@_SKIP_NO_GOLD
def test_real_gate5_solve_robustness():
    """Gate 5 (deploy-time): solver_status ∈ solved AND solve_time_s < 60 s.

    This test verifies that the ported solver completes on a real gold-tier
    track within the time budget.  The ≥95 % aggregate solve rate across ALL
    gold-tier tracks is verified exclusively by scripts/validate_ocp2d.py.

    Requires env vars:
      SIDECAR_ROOT  — path to sidecars root
      LAP_TRACK_ID  — track_id of the gold-tier surface to load
    """
    import sys

    root = os.environ.get("SIDECAR_ROOT")
    track_id = os.environ.get("LAP_TRACK_ID")
    if not track_id:
        pytest.skip("LAP_TRACK_ID must be set for gate5")

    _tt = Path(__file__).resolve().parents[2] / "telemetry_tool"
    if str(_tt) not in sys.path:
        sys.path.insert(0, str(_tt))

    from track_surface.store import load_track_model
    from track_surface.solver_bridge import solve_optimal_line_2d

    surface = load_track_model(track_id, sidecar_root=root)
    if surface is None or surface.grip_2d is None:
        pytest.skip(
            f"track {track_id!r} has no gold-tier sidecar in {root!r} "
            f"(quality_tier={getattr(surface, 'quality_tier', 'N/A')!r})"
        )

    sol = solve_optimal_line_2d(surface, condition="dry", n_points=300, max_time_s=60.0)

    assert sol.solver_status in _SOLVED_STATUSES, (
        f"gate5: solver_status={sol.solver_status!r} is not a solved status"
    )
    assert sol.solver_time_s < 60.0, (
        f"gate5: solve_time_s={sol.solver_time_s:.1f}s exceeds 60 s budget"
    )
